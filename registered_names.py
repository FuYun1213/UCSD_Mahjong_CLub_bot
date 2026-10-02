"""Registered-name directory; credentials remain in the existing JSON account file.

Stable account IDs are retained. The directory is added next to that file, so a
sandbox/test account file always gets its own database and lock. A legacy
collision leaves a reviewable staging table; no accounts are discarded/renamed.
"""
from contextlib import contextmanager, closing, ExitStack
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
from request_performance import measure

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCAL = threading.local()
_DIRECTORY_VERSIONS = {}


def _file_version(path):
    try:
        stat = Path(path).stat()
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except FileNotFoundError:
        return None



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
    """Time only acquisition of the existing reentrant process and file locks."""
    with ExitStack() as stack:
        with measure('accountLockWaitMs'):
            stack.enter_context(_account_lock(accounts_path, blocking=blocking))
        yield


@contextmanager
def _account_lock(accounts_path, *, blocking=True):
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
      CREATE TABLE IF NOT EXISTS registered_name_suffixes (
        suffix TEXT NOT NULL, account_id TEXT NOT NULL,
        PRIMARY KEY(suffix,account_id)
      );
      CREATE INDEX IF NOT EXISTS ix_registered_suffix_account ON registered_name_suffixes(account_id);
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
      CREATE TABLE IF NOT EXISTS account_sessions (
        token_hash TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL
      );
      CREATE INDEX IF NOT EXISTS ix_account_sessions_account
        ON account_sessions(account_id);
      CREATE INDEX IF NOT EXISTS ix_account_sessions_expiry
        ON account_sessions(expires_at);
      CREATE TABLE IF NOT EXISTS player_merge_intents (
        operation_id TEXT PRIMARY KEY,
        source_player_id INTEGER NOT NULL,
        target_player_id INTEGER NOT NULL,
        source_name TEXT NOT NULL,
        target_name TEXT NOT NULL,
        source_account_id TEXT NOT NULL DEFAULT '',
        target_account_id TEXT NOT NULL DEFAULT '',
        delete_source_account INTEGER NOT NULL DEFAULT 0,
        evidence_key TEXT NOT NULL DEFAULT '',
        evidence_origin TEXT NOT NULL DEFAULT '',
        operation_kind TEXT NOT NULL DEFAULT 'merge',
        status TEXT NOT NULL DEFAULT 'staged',
        last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE INDEX IF NOT EXISTS ix_player_merge_intents_status
        ON player_merge_intents(status,created_at);
      CREATE TABLE IF NOT EXISTS player_merge_evidence_receipts (
        evidence_key TEXT PRIMARY KEY,
        evidence_origin TEXT NOT NULL,
        operation_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE INDEX IF NOT EXISTS ix_player_merge_evidence_receipts_status
        ON player_merge_evidence_receipts(status,updated_at);
    """)
    merge_columns = {row[1] for row in db.execute("PRAGMA table_info(player_merge_intents)")}
    for column, declaration in {
        "source_account_id": "TEXT NOT NULL DEFAULT ''",
        "target_account_id": "TEXT NOT NULL DEFAULT ''",
        "delete_source_account": "INTEGER NOT NULL DEFAULT 0",
        "evidence_key": "TEXT NOT NULL DEFAULT ''",
        "evidence_origin": "TEXT NOT NULL DEFAULT ''",
        "operation_kind": "TEXT NOT NULL DEFAULT 'merge'",
    }.items():
        if column not in merge_columns:
            db.execute(f"ALTER TABLE player_merge_intents ADD COLUMN {column} {declaration}")
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
    # A rename reserves registered_users' new spelling before recovering its
    # JSON/history projections. That row is therefore not proof that the suffix
    # index already contains the new name. Its longest actual suffix is the full
    # indexed spelling; compare that value to rebuild both fresh renames and
    # mismatches left by older versions, only when directory sync is required.
    indexed = {r["account_id"]:r["suffix"] for r in db.execute("""
        SELECT suffixes.account_id, suffixes.suffix
        FROM registered_name_suffixes AS suffixes
        JOIN (SELECT account_id, MAX(length(suffix)) AS name_length
              FROM registered_name_suffixes GROUP BY account_id) AS names
          ON names.account_id=suffixes.account_id AND length(suffixes.suffix)=names.name_length
    """)}
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
        if indexed.get(account_id) != normalized:
            db.execute("DELETE FROM registered_name_suffixes WHERE account_id=?",(account_id,))
            db.executemany("INSERT OR IGNORE INTO registered_name_suffixes(suffix,account_id) VALUES(?,?)",
                           [(normalized[i:],account_id) for i in range(len(normalized))])
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
    db.execute("DELETE FROM registered_name_suffixes WHERE account_id NOT IN (" + (",".join("?" for _ in ids) or "NULL") + ")", tuple(ids))
    if not ids: db.execute("DELETE FROM registered_name_suffixes")
    report = duplicate_report(data)
    # Deleted entries are removed from the name namespace but remain in audit.
    db.execute("DELETE FROM registered_users WHERE account_id NOT IN (" + (",".join("?" for _ in ids) or "NULL") + ")", tuple(ids))
    if not ids:
        db.execute("DELETE FROM registered_users")
    if report["ready"]:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_registered_users_normalized_name ON registered_users(normalized_registered_name)")
    return changed, report


def ensure_directory(accounts_path):
    # Account writers publish atomically under this same lock. A changed JSON,
    # directory database, or pending recovery file always invalidates the fast path.
    key = str(Path(accounts_path).resolve())
    with account_lock(accounts_path):
        version = (_file_version(accounts_path), (_file_version(database_path(accounts_path)), _file_version(str(database_path(accounts_path))+"-wal")))
        cached = _DIRECTORY_VERSIONS.get(key)
        if cached and cached[0] == version and not _pending_file(accounts_path).exists():
            return dict(cached[1])
        with closing(_connect(accounts_path)) as db:
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
        _DIRECTORY_VERSIONS[key] = ((_file_version(accounts_path), (_file_version(database_path(accounts_path)), _file_version(str(database_path(accounts_path))+"-wal"))), dict(report))
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
    if not query:
        return {"users":[],"next_cursor":None,"has_more":False}
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
                           WHERE enabled=1 AND account_id IN (
                             SELECT account_id FROM registered_name_suffixes WHERE suffix>=? AND suffix<?)
                           ORDER BY CASE WHEN normalized_registered_name=? THEN 0
                             WHEN substr(normalized_registered_name,1,length(?))=? THEN 1 ELSE 2 END,
                             normalized_registered_name,account_id LIMIT ? OFFSET ?""",
                          (query, query + chr(0x10ffff), query, query, query, limit + 1, offset)).fetchall()
    more = len(rows) > limit
    next_cursor = base64.urlsafe_b64encode(json.dumps([fingerprint, offset + limit]).encode()).decode().rstrip("=") if more else None
    return {"users": [dict(row) for row in rows[:limit]], "next_cursor": next_cursor, "has_more": more}


def current_name_map(accounts_path, ids=None):
    return {row["id"]: row["name"] for row in account_rows(accounts_path, ids)}


def _session_digest(token):
    if not isinstance(token, str) or not token or len(token) > 512:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def remember_session(accounts_path, token, account_id, expires_at):
    """Persist only a session-token digest so browser logins survive restarts."""
    digest = _session_digest(token)
    account_id = str(account_id or "")
    expires_at = int(expires_at or 0)
    now = int(time.time())
    if not digest or not account_id or expires_at <= now:
        raise ValueError("Invalid account session.")
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db, db:
        db.execute("DELETE FROM account_sessions WHERE expires_at<=?", (now,))
        db.execute("""INSERT INTO account_sessions(token_hash,account_id,expires_at,created_at,last_seen_at)
                      VALUES(?,?,?,?,?) ON CONFLICT(token_hash) DO UPDATE SET
                      account_id=excluded.account_id,expires_at=excluded.expires_at,last_seen_at=excluded.last_seen_at""",
                   (digest, account_id, expires_at, now, now))


def session_account_id(accounts_path, token, *, now=None):
    """Resolve a durable browser session without ever storing its raw token."""
    digest = _session_digest(token)
    if not digest:
        return None
    now = int(time.time() if now is None else now)
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db:
        row = db.execute("SELECT account_id,expires_at,last_seen_at FROM account_sessions WHERE token_hash=?",
                         (digest,)).fetchone()
        if not row:
            return None
        if int(row["expires_at"]) <= now:
            db.execute("DELETE FROM account_sessions WHERE token_hash=?", (digest,))
            db.commit()
            return None
        # Bound write amplification while still recording that a long-lived
        # credential remains in active use.
        if now - int(row["last_seen_at"]) >= 24 * 60 * 60:
            db.execute("UPDATE account_sessions SET last_seen_at=? WHERE token_hash=?", (now, digest))
            db.commit()
        return str(row["account_id"])


def forget_session(accounts_path, token):
    digest = _session_digest(token)
    if not digest:
        return
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db, db:
        db.execute("DELETE FROM account_sessions WHERE token_hash=?", (digest,))


def revoke_sessions(accounts_path, account_id):
    account_id = str(account_id or "")
    if not account_id:
        return
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db, db:
        db.execute("DELETE FROM account_sessions WHERE account_id=?", (account_id,))


def move_sessions(accounts_path, source_account_id, target_account_id):
    source_account_id = str(source_account_id or "")
    target_account_id = str(target_account_id or "")
    if not source_account_id or not target_account_id or source_account_id == target_account_id:
        return
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db, db:
        db.execute("UPDATE account_sessions SET account_id=? WHERE account_id=?",
                   (target_account_id, source_account_id))


def stage_player_merge(accounts_path, source, target, *, source_account_id="",
                       target_account_id="", delete_source_account=False,
                       evidence_key="", evidence_origin=""):
    """Record cross-store recovery evidence before the club database changes."""
    operation_id = secrets.token_hex(16)
    evidence_key = str(evidence_key or "")
    evidence_origin = str(evidence_origin or "")
    if len(evidence_key) > 128 or len(evidence_origin) > 32:
        raise ValueError("Invalid player-merge evidence receipt.")
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db, db:
        if evidence_key:
            receipt = db.execute(
                "SELECT status FROM player_merge_evidence_receipts WHERE evidence_key=?",
                (evidence_key,),
            ).fetchone()
            if receipt and receipt["status"] in {"completed", "blocked"}:
                raise ValueError("Player-merge evidence was already consumed.")
        db.execute("""INSERT INTO player_merge_intents(
                        operation_id,source_player_id,target_player_id,source_name,target_name,
                        source_account_id,target_account_id,delete_source_account,
                        evidence_key,evidence_origin,status
                      ) VALUES(?,?,?,?,?,?,?,?,?,?,'staged')""",
                   (operation_id, int(source["id"]), int(target["id"]),
                    str(source["name"]), str(target["name"]),
                    str(source_account_id or ""), str(target_account_id or ""),
                    1 if delete_source_account else 0, evidence_key, evidence_origin))
        if evidence_key:
            db.execute("""INSERT INTO player_merge_evidence_receipts(
                            evidence_key,evidence_origin,operation_id,status
                          ) VALUES(?,?,?,'pending')
                          ON CONFLICT(evidence_key) DO UPDATE SET
                            evidence_origin=excluded.evidence_origin,
                            operation_id=excluded.operation_id,
                            status='pending',updated_at=CURRENT_TIMESTAMP
                          WHERE player_merge_evidence_receipts.status NOT IN ('completed','blocked')""",
                       (evidence_key, evidence_origin, operation_id))
    return operation_id


def stage_player_rename(accounts_path, source, target_name, *, source_account_id="",
                        target_account_id="", evidence_key="", evidence_origin="static"):
    """Journal a confirmed rename-as-target before changing the club database."""
    operation_id = secrets.token_hex(16)
    evidence_key = str(evidence_key or "")
    evidence_origin = str(evidence_origin or "")
    if not evidence_key or len(evidence_key) > 128 or len(evidence_origin) > 32:
        raise ValueError("Invalid player-rename evidence receipt.")
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db, db:
        receipt = db.execute(
            "SELECT status FROM player_merge_evidence_receipts WHERE evidence_key=?",
            (evidence_key,),
        ).fetchone()
        if receipt and receipt["status"] in {"completed", "blocked"}:
            raise ValueError("Player-rename evidence was already consumed.")
        db.execute("""INSERT INTO player_merge_intents(
                        operation_id,source_player_id,target_player_id,source_name,target_name,
                        source_account_id,target_account_id,delete_source_account,
                        evidence_key,evidence_origin,operation_kind,status
                      ) VALUES(?,?,?,?,?,?,?,0,?,?, 'rename','staged')""",
                   (operation_id, int(source["id"]), int(source["id"]),
                    str(source["name"]), str(target_name),
                    str(source_account_id or ""), str(target_account_id or ""),
                    evidence_key, evidence_origin))
        db.execute("""INSERT INTO player_merge_evidence_receipts(
                        evidence_key,evidence_origin,operation_id,status
                      ) VALUES(?,?,?,'pending')
                      ON CONFLICT(evidence_key) DO UPDATE SET
                        evidence_origin=excluded.evidence_origin,
                        operation_id=excluded.operation_id,
                        status='pending',updated_at=CURRENT_TIMESTAMP
                      WHERE player_merge_evidence_receipts.status NOT IN ('completed','blocked')""",
                   (evidence_key, evidence_origin, operation_id))
    return operation_id


def update_player_merge(accounts_path, operation_id, status, error=""):
    allowed = {"staged", "club_merged", "account_error", "failed", "completed"}
    if status not in allowed:
        raise ValueError("Invalid player merge state.")
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db, db:
        intent = db.execute(
            "SELECT evidence_key FROM player_merge_intents WHERE operation_id=?",
            (str(operation_id),),
        ).fetchone()
        db.execute("""UPDATE player_merge_intents
                      SET status=?,last_error=?,updated_at=CURRENT_TIMESTAMP
                      WHERE operation_id=?""",
                   (status, str(error or "")[:1000], str(operation_id)))
        if intent and intent["evidence_key"]:
            receipt_status = status if status in {"completed", "failed"} else "pending"
            db.execute("""UPDATE player_merge_evidence_receipts
                          SET status=?,updated_at=CURRENT_TIMESTAMP
                          WHERE evidence_key=? AND operation_id=?""",
                       (receipt_status, intent["evidence_key"], str(operation_id)))


def player_merge_evidence_receipts(accounts_path):
    """Return non-sensitive one-time receipts for legacy merge evidence."""
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db:
        return {
            str(row["evidence_key"]): dict(row)
            for row in db.execute(
                "SELECT evidence_key,evidence_origin,operation_id,status "
                "FROM player_merge_evidence_receipts"
            )
        }


def update_player_merge_evidence_receipt(accounts_path, evidence_key, evidence_origin,
                                         status, operation_id=""):
    """Persist a one-time legacy-evidence outcome without storing player names."""
    allowed = {"pending", "failed", "blocked", "completed"}
    if status not in allowed:
        raise ValueError("Invalid player-merge evidence receipt state.")
    evidence_key = str(evidence_key or "")
    evidence_origin = str(evidence_origin or "")
    operation_id = str(operation_id or "")
    if not evidence_key or len(evidence_key) > 128 or len(evidence_origin) > 32:
        raise ValueError("Invalid player-merge evidence receipt.")
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db, db:
        db.execute("""INSERT INTO player_merge_evidence_receipts(
                        evidence_key,evidence_origin,operation_id,status
                      ) VALUES(?,?,?,?)
                      ON CONFLICT(evidence_key) DO UPDATE SET
                        evidence_origin=excluded.evidence_origin,
                        operation_id=excluded.operation_id,
                        status=excluded.status,updated_at=CURRENT_TIMESTAMP
                      WHERE player_merge_evidence_receipts.status NOT IN ('completed','blocked')""",
                   (evidence_key, evidence_origin, operation_id, status))


def pending_player_merges(accounts_path):
    """Return merge journals that may need account-directory publication."""
    with account_lock(accounts_path), closing(_connect(accounts_path)) as db:
        return [dict(row) for row in db.execute(
            """SELECT * FROM player_merge_intents
               WHERE status IN ('staged','club_merged','account_error')
               ORDER BY created_at,operation_id""")]


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
