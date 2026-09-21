"""Registered-name directory; credentials remain in the existing JSON account file.

Stable account IDs are retained. The directory is added next to that file, so a
sandbox/test account file always gets its own database and lock. A legacy
collision leaves a reviewable staging table; no accounts are discarded/renamed.
"""
from contextlib import contextmanager, closing
from functools import wraps
from pathlib import Path
import base64
import hashlib
import errno
import json
import os
import secrets
import sqlite3
import tempfile
import threading
import time
import unicodedata

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCAL = threading.local()


class RegisteredNameError(ValueError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def display_name(value):
    name = " ".join(unicodedata.normalize("NFKC", str(value or "")).split())
    if not name or len(name) > 128 or any(unicodedata.category(c) in {"Cc", "Cs"} for c in name):
        raise ValueError("Please enter a valid registered name (1–128 characters).")
    return name


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def database_path(accounts_path):
    return Path(accounts_path).with_suffix(".registered.sqlite3")


@contextmanager
def account_lock(accounts_path, *, blocking=True):
    """Serialize all JSON account read/modify/write operations across workers."""
    key = str(Path(accounts_path).resolve())
    if not _LOCKS_GUARD.acquire(blocking=blocking):
        raise TimeoutError("Account directory is busy. Please retry.")
    try:
        lock = _LOCKS.setdefault(key, threading.RLock())
    finally:
        _LOCKS_GUARD.release()
    if not lock.acquire(blocking=blocking):
        raise TimeoutError("Account directory is busy. Please retry.")
    try:
        held = getattr(_LOCAL, "held", set())
        if key in held:
            yield
            return
        path = Path(key + ".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, 2)
                if not handle.tell():
                    handle.write(b"\0"); handle.flush()
                handle.seek(0)
                deadline = time.monotonic() + 30
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if not blocking or time.monotonic() >= deadline:
                            raise TimeoutError("Account directory is busy. Please retry.") from None
                        time.sleep(.025)
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                except BlockingIOError:
                    raise TimeoutError("Account directory is busy. Please retry.") from None
            _LOCAL.held = held | {key}
            try:
                yield
            finally:
                _LOCAL.held = held
                if os.name == "nt":
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    finally:
        lock.release()


def _load(path):
    _publish_pending_file(path)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"users": {}, "player_icons": {}}
    except (OSError, json.JSONDecodeError):
        raise ValueError("Account directory is unavailable. Please contact an administrator.") from None
    if not isinstance(data, dict) or not isinstance(data.get("users", {}), dict):
        raise ValueError("Account directory is unavailable. Please contact an administrator.")
    data.setdefault("users", {})
    data.setdefault("player_icons", {})
    return data


def _pending_file(path):
    return Path(str(path) + ".pending")


def _publish_pending_file(path):
    path = Path(path)
    pending = _pending_file(path)
    if not pending.exists():
        return
    payload = pending.read_text(encoding="utf-8")
    # Refuse an incomplete recovery record instead of treating credentials as empty.
    if not isinstance(json.loads(payload), dict):
        raise ValueError("Account recovery needs administrator review.")
    try:
        os.replace(pending, path)
    except OSError as error:
        if error.errno not in {errno.EBUSY, errno.EXDEV}:
            raise
        # For an exact Docker file mount, the durable pending copy survives even
        # a process death immediately after truncation. Every reader recovers it.
        with path.open("w", encoding="utf-8") as output:
            output.write(payload)
            output.flush(); os.fsync(output.fileno())
        pending.unlink()


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.flush(); os.fsync(output.fileno())
        # The recovery copy contains credentials: mkstemp creates it mode 0600.
        # Publish it atomically before touching the legacy, possibly mounted file.
        os.replace(temporary, _pending_file(path))
        _publish_pending_file(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _connect(path):
    db = sqlite3.connect(database_path(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
      PRAGMA busy_timeout=30000;
      CREATE TABLE IF NOT EXISTS registered_users (
        account_id TEXT PRIMARY KEY,
        registered_name TEXT NOT NULL,
        normalized_registered_name TEXT NOT NULL,
        legacy_key TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        avatar TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE TABLE IF NOT EXISTS pending_registered_name_changes (
        operation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL UNIQUE,
        old_name TEXT NOT NULL, new_name TEXT NOT NULL,
        club_database TEXT NOT NULL, club_player_id INTEGER,
        old_role TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE TABLE IF NOT EXISTS registered_name_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id TEXT NOT NULL,
        old_name TEXT NOT NULL,
        new_name TEXT NOT NULL,
        admin_id TEXT NOT NULL,
        admin_name TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
    """)
    return db


def duplicate_report(data):
    groups = {}
    invalid = []
    for key, account in data.get("users", {}).items():
        if not isinstance(account, dict):
            invalid.append({"name": str(key), "issue": "invalid_account"})
            continue
        name = str(account.get("name", key))
        normalized = normalize_name(name)
        if not normalized:
            invalid.append({"name": name, "issue": "empty_name"})
        groups.setdefault(normalized, []).append({"id": account.get("account_id", ""), "name": name})
    duplicates = [{"normalized_name": name, "users": accounts}
                  for name, accounts in groups.items() if len(accounts) > 1]
    return {"duplicates": duplicates, "invalid": invalid,
            "ready": not duplicates and not invalid, "account_count": len(data.get("users", {}))}


def _sync(db, data):
    ids = set()
    changed = False
    for key, account in data["users"].items():
        if not isinstance(account, dict):
            continue
        if not account.get("account_id"):
            account["account_id"] = secrets.token_urlsafe(24)
            changed = True
        account_id = str(account["account_id"])
        if account_id in ids:
            raise ValueError("Duplicate account identity requires administrator review.")
        ids.add(account_id)
        name = str(account.get("name", key))
        normalized = normalize_name(name)
        for field, value in (("registeredName", name), ("normalizedRegisteredName", normalized)):
            if account.get(field) != value:
                account[field] = value
                changed = True
        enabled = not (account.get("disabled") or account.get("is_active") is False
                       or account.get("status") in {"disabled", "banned", "deleted", "pending_claim"})
        db.execute("""INSERT INTO registered_users(account_id,registered_name,normalized_registered_name,legacy_key,enabled,avatar)
                      VALUES(?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET
                      registered_name=excluded.registered_name, normalized_registered_name=excluded.normalized_registered_name,
                      legacy_key=excluded.legacy_key, enabled=excluded.enabled, avatar=excluded.avatar,
                      updated_at=CASE WHEN registered_name<>excluded.registered_name THEN CURRENT_TIMESTAMP ELSE updated_at END""",
                   (account_id, name, normalized, str(key), int(enabled), str(account.get("avatar", "") or account.get("discord_avatar", ""))))
    # Removed/disabled accounts can no longer be selected; audit IDs stay intact.
    if ids:
        db.execute("UPDATE registered_users SET enabled=0 WHERE account_id NOT IN (" + ",".join("?" for _ in ids) + ")", tuple(ids))
    else:
        db.execute("UPDATE registered_users SET enabled=0")
    report = duplicate_report(data)
    # Deleted entries are removed from the name namespace but remain in audit.
    db.execute("DELETE FROM registered_users WHERE account_id NOT IN (" + (",".join("?" for _ in ids) or "NULL") + ")", tuple(ids))
    if not ids:
        db.execute("DELETE FROM registered_users")
    if report["ready"]:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_registered_users_normalized_name ON registered_users(normalized_registered_name)")
    return changed, report


def ensure_directory(accounts_path):
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db:
        _recover_pending(accounts_path)
        data = _load(accounts_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            changed, report = _sync(db, data)
            if changed:
                _write(accounts_path, data)
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            raise RegisteredNameError("This registered name is already in use.", "registered_name_taken") from None
        report["unique_constraint"] = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='uq_registered_users_normalized_name'").fetchone())
        return report


def write_accounts(accounts_path, data, *, audit=None):
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db:
        _recover_pending(accounts_path)
        old = _load(accounts_path)
        try:
            db.execute("BEGIN IMMEDIATE")
            _sync(db, data)
            if audit:
                db.execute("""INSERT INTO registered_name_audit(account_id,old_name,new_name,admin_id,admin_name,reason)
                              VALUES(:account_id,:old_name,:new_name,:admin_id,:admin_name,:reason)""", audit)
            _write(accounts_path, data)
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            raise RegisteredNameError("This registered name is already in use.", "registered_name_taken") from None
        except Exception:
            db.rollback()
            _write(accounts_path, old)
            raise


def account_rows(accounts_path, ids=None):
    """Internal directory projection, with current names and no credentials."""
    ensure_directory(accounts_path)
    with closing(_connect(accounts_path)) as db:
        sql = "SELECT account_id AS id, registered_name AS name, avatar, enabled FROM registered_users"
        args = ()
        if ids is not None:
            if not ids:
                return []
            sql += " WHERE account_id IN (" + ",".join("?" for _ in ids) + ")"
            args = tuple(str(value) for value in ids)
        return [{"id": row["id"], "name": row["name"], "avatar": row["avatar"],
                 "disabled": not bool(row["enabled"])} for row in db.execute(sql, args)]


def search_accounts(accounts_path, query="", cursor="", limit=10, ids=None):
    """Bounded server-side search; opaque cursor is tied to the normalized query."""
    query = normalize_name(query)
    if len(query) > 128:
        raise ValueError("Search text is too long.")
    try:
        limit = max(1, min(25, int(limit)))
    except (TypeError, ValueError):
        raise ValueError("Invalid search limit.") from None
    if ids is not None:
        if len(ids) > 50 or any(not isinstance(value, str) or not value or len(value) > 128 for value in ids):
            raise ValueError("Invalid selection.")
        rows = account_rows(accounts_path, list(dict.fromkeys(ids)))
        return {"users": [{k: row[k] for k in ("id", "name", "avatar")} for row in rows if not row["disabled"]],
                "next_cursor": None, "has_more": False}
    offset = 0
    fingerprint = hashlib.sha256(query.encode()).hexdigest()[:12]
    if cursor:
        try:
            token = json.loads(base64.urlsafe_b64decode(str(cursor) + "=" * (-len(str(cursor)) % 4)))
            offset = int(token[1])
            if token[0] != fingerprint or not 0 <= offset <= 100000:
                raise ValueError
        except Exception:
            raise ValueError("Invalid search page. Please search again.") from None
    ensure_directory(accounts_path)
    with closing(_connect(accounts_path)) as db:
        rows = db.execute("""SELECT account_id AS id,registered_name AS name,avatar FROM registered_users
                           WHERE enabled=1 AND instr(normalized_registered_name,?)>0
                           ORDER BY CASE WHEN normalized_registered_name=? THEN 0
                             WHEN substr(normalized_registered_name,1,length(?))=? THEN 1 ELSE 2 END,
                             normalized_registered_name,account_id LIMIT ? OFFSET ?""",
                          (query, query, query, query, limit + 1, offset)).fetchall()
    more = len(rows) > limit
    next_cursor = base64.urlsafe_b64encode(json.dumps([fingerprint, offset + limit]).encode()).decode().rstrip("=") if more else None
    return {"users": [dict(row) for row in rows[:limit]], "next_cursor": next_cursor, "has_more": more}


def current_name_map(accounts_path, ids=None):
    return {row["id"]: row["name"] for row in account_rows(accounts_path, ids)}


def _recover_pending(accounts_path):
    """Finish committed rename intents after an interrupted file/DB publication.

    The unique name and audit were committed before any legacy store changes.
    Replaying by stable IDs is idempotent, including a failure after club commit
    or JSON write. No credentials are copied into the journal.
    """
    if not database_path(accounts_path).exists():
        return
    with closing(_connect(accounts_path)) as db:
        changes = [dict(row) for row in db.execute("SELECT * FROM pending_registered_name_changes ORDER BY created_at,operation_id")]
    for change in changes:
        import mahjong_store
        if change["club_player_id"] is not None:
            with mahjong_store.connect(change["club_database"]) as club:
                row = club.execute("SELECT * FROM players WHERE id=?", (change["club_player_id"],)).fetchone()
                if not row:
                    raise ValueError("A pending name change needs administrator review.")
                if row["name"] != change["new_name"]:
                    mahjong_store.rename_player(club, row["name"], change["new_name"], commit=False)
        data = _load(accounts_path)
        selected = [(key, user) for key, user in data["users"].items()
                    if str(user.get("account_id")) == change["account_id"]]
        if len(selected) != 1:
            raise ValueError("A pending name change needs administrator review.")
        old_key, user = selected[0]
        new_key = normalize_name(change["new_name"])
        if new_key in data["users"] and str(data["users"][new_key].get("account_id")) != change["account_id"]:
            raise ValueError("A pending name change needs administrator review.")
        user["name"] = change["new_name"]
        user["registeredName"] = change["new_name"]
        user["normalizedRegisteredName"] = new_key
        user.setdefault("role", change["old_role"])
        data["users"].pop(old_key)
        data["users"][new_key] = user
        icons = data.get("player_icons", {})
        if old_key != new_key and old_key in icons:
            icons[new_key] = icons.pop(old_key)
        _write(accounts_path, data)
        with closing(_connect(accounts_path)) as db:
            db.execute("BEGIN IMMEDIATE")
            _sync(db, data)
            db.execute("DELETE FROM pending_registered_name_changes WHERE operation_id=?", (change["operation_id"],))
            db.commit()


def read_accounts(accounts_path):
    with account_lock(accounts_path):
        _recover_pending(accounts_path)
        return _load(accounts_path)


def rename_account(accounts_path, *, account_id, old_name, new_name, club_database,
                   club_player_id, old_role, admin_id, admin_name, reason=""):
    """Reserve the unique name and audit durably, then publish legacy projections."""
    with account_lock(accounts_path):
        ensure_directory(accounts_path)
        new_name = display_name(new_name)
        data = _load(accounts_path)
        account = next((user for user in data["users"].values() if str(user.get("account_id")) == str(account_id)), None)
        if not account or account.get("name") != old_name:
            raise RegisteredNameError("The registered name has changed. Refresh and confirm again.", "stale_name")
        if any(str(user.get("account_id")) != str(account_id) and normalize_name(user.get("name", key)) == normalize_name(new_name)
               for key, user in data["users"].items()):
            raise RegisteredNameError("This registered name is already in use.", "registered_name_taken")
        with closing(_connect(accounts_path)) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE registered_users SET registered_name=?,normalized_registered_name=?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?",
                           (new_name, normalize_name(new_name), str(account_id)))
                db.execute("""INSERT INTO registered_name_audit(account_id,old_name,new_name,admin_id,admin_name,reason)
                              VALUES(?,?,?,?,?,?)""", (str(account_id),old_name,new_name,str(admin_id),admin_name,reason))
                db.execute("""INSERT INTO pending_registered_name_changes(operation_id,account_id,old_name,new_name,club_database,club_player_id,old_role)
                              VALUES(?,?,?,?,?,?,?)""", (secrets.token_hex(16),str(account_id),old_name,new_name,str(Path(club_database).resolve()),club_player_id,old_role))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                raise RegisteredNameError("This registered name is already in use.", "registered_name_taken") from None
        _recover_pending(accounts_path)
