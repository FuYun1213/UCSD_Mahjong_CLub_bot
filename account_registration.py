"""Durable administrator-approved claims in the existing account directory DB.

An approving row is a recovery journal. Publishing it is idempotent and uses the
existing player's stable identity without changing the club player row.
"""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import re
import secrets
import sqlite3
import time
import registered_names as names
import mahjong_store
import account_legacy_links
from account_passwords import hash_password

ALREADY = "This ID is already registered. Please log in or contact an administrator."


def connect(path):
    db = names._connect(path)
    claim_schema = """CREATE TABLE IF NOT EXISTS account_claims (
        id TEXT PRIMARY KEY, legacy_player_id INTEGER NOT NULL,
        legacy_name TEXT NOT NULL, registered_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL, password_hash TEXT,
        account_id TEXT NOT NULL, resume_hash TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'pending', return_to TEXT NOT NULL DEFAULT '/',
        bind_discord INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_by TEXT, reviewed_at TEXT, reason TEXT NOT NULL DEFAULT ''
      )"""
    old = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='account_claims'").fetchone()
    password_required = old and any(
        row[1] == "password_hash" and row[3]
        for row in db.execute("PRAGMA table_info(account_claims)"))
    if old and ("account_id TEXT NOT NULL UNIQUE" in old[0] or password_required):
        # Preserve every claim while allowing an unset password. This also
        # repairs the early v10 account_id uniqueness draft.
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("ALTER TABLE account_claims RENAME TO account_claims_v10_old")
            db.execute(claim_schema)
            db.execute("INSERT INTO account_claims SELECT * FROM account_claims_v10_old")
            db.execute("DROP TABLE account_claims_v10_old")
            db.commit()
        except Exception:
            db.rollback()
            raise
    db.execute(claim_schema)
    db.executescript("""
      CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_claim_player ON account_claims(legacy_player_id)
        WHERE status IN ('pending','approving','approved');
      CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_claim_name ON account_claims(normalized_name)
        WHERE status IN ('pending','approving');
      CREATE TABLE IF NOT EXISTS account_registration_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
        actor_id TEXT NOT NULL, detail TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
    """)
    return db


def audit(db, action, actor, **detail):
    db.execute("INSERT INTO account_registration_audit(action,actor_id,detail) VALUES(?,?,?)",
               (action, str(actor), json.dumps(detail, ensure_ascii=False)))


def safe_return(value):
    from urllib.parse import urlsplit, unquote
    import posixpath
    value = str(value or "/")
    if len(value) > 2000 or not value.startswith("/"):
        return "/"
    decoded = value
    try:
        for _ in range(4):
            if (decoded.startswith("//") or "\\" in decoded
                    or any(ord(c) < 32 or ord(c) == 127 for c in decoded)):
                return "/"
            parsed = urlsplit(decoded)
            if parsed.scheme or parsed.netloc or posixpath.normpath(parsed.path).rstrip("/").lower() in {"/register", "/login"}:
                return "/"
            next_value = unquote(decoded)
            if next_value == decoded:
                return value
            decoded = next_value
    except ValueError:
        pass
    return "/"


def player_id(value):
    # Names (including names consisting only of digits) never identify the row.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Existing ID was not found or needs administrator review.")
    match = re.fullmatch(r"(?:(?:club-)|(?:historical:))?([1-9][0-9]{0,18})", str(value).strip())
    if not match or int(match[1]) > 9223372036854775807:
        raise ValueError("Existing ID was not found or needs administrator review.")
    return int(match[1])


def _player_name(player, players):
    if (player.get("disabled") or player.get("is_active") in (False, 0)
            or player.get("deleted_at") or player.get("status") in {"disabled", "deleted", "banned"}):
        raise ValueError("This ID is unavailable. Please contact an administrator.")
    name = names.display_name(player["name"])
    if sum(names.normalize_name(p["name"]) == names.normalize_name(name) for p in players) != 1:
        raise ValueError("Existing ID was not found or needs administrator review.")
    return name


def legacy_player(web, value):
    selected_id = player_id(value)
    with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as db:
        players = [dict(r) for r in db.execute("SELECT * FROM players")]
    player = next((p for p in players if p["id"] == selected_id), None)
    if player is None:
        raise ValueError("Existing ID was not found or needs administrator review.")
    _player_name(player, players)
    return player


def claimable_players(web, query="", limit=20):
    """Public, minimal selection from historical players, never account records."""
    if not isinstance(query, str) or len(query) > 128:
        raise ValueError("Search must contain no more than 128 characters.")
    try:
        limit = max(1, min(50, int(limit)))
    except (ValueError, TypeError):
        raise ValueError("Invalid result limit.") from None
    query = names.normalize_name(query)
    with names.account_lock(web.USERS_FILE):
        recover_creations(web)
        # Complete any already committed rename before reading club names.
        web.users_data()
        with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as db:
            players = [dict(r) for r in db.execute("SELECT * FROM players")]
        with closing(connect(web.USERS_FILE)) as db:
            reserved = list(db.execute("SELECT legacy_player_id,normalized_name,status FROM account_claims WHERE status IN ('pending','approving','approved')"))
        reserved_ids = {row[0] for row in reserved}
        reserved_names = {row[1] for row in reserved if row[2] in {"pending", "approving"}}
        result = []
        for player in sorted(players, key=lambda p: (names.normalize_name(p["name"]), p["id"])):
            if player["id"] in reserved_ids or query not in names.normalize_name(player["name"]):
                continue
            try:
                name = _player_name(player, players)
                if names.normalize_name(name) in reserved_names or is_claimed(web, player):
                    continue
            except ValueError:
                # Ambiguous legacy identities require an administrator, never a guess.
                continue
            result.append({"id": "club-" + str(player["id"]), "name": name})
            if len(result) > limit:
                break
        return {"players": result[:limit], "has_more": len(result) > limit}


def is_claimed(web, player, ignore=None):
    # A committed creation intent already owns this player, even while JSON
    # publication is interrupted or a different account-directory mount is used.
    with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as club:
        if club.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_creation_intents'").fetchone():
            intent = club.execute("SELECT account_id FROM account_creation_intents WHERE player_id=?", (player["id"],)).fetchone()
            if intent is not None and str(intent["account_id"]) != str(ignore):
                return True
    legacy_identity = account_legacy_links.identity(web, player)
    matches = [a for k, a in web.users_data()["users"].items()
               if str(a.get("account_id")) != str(ignore)
               and (a.get("account_id") == legacy_identity
                    or str(a.get("club_player_id")) == str(player["id"])
                    or names.normalize_name(a.get("name", k)) == names.normalize_name(player["name"]))]
    # History sync creates neutral accounts for recorded players. They have
    # no ownership proof, so an administrator-reviewed claim remains possible.
    return bool(matches) and not (len(matches) == 1 and _claimable_auto_account(matches[0], player))


def _claimable_auto_account(account, player):
    return (account.get("auto_registered") is True
            and str(account.get("club_player_id")) == str(player["id"])
            and not account.get("password_hash") and not account.get("discord_id")
            and account.get("status") in {None, "active"}
            and not account.get("disabled") and account.get("is_active") is not False)


def validate(web, data, *, confirmation=True, allow_account_id=None):
    if not isinstance(data, dict):
        raise ValueError("Invalid registration form.")
    if not isinstance(data.get("username"), str):
        raise ValueError("Please enter a valid registered name.")
    name = names.display_name(data.get("username"))
    password = None
    if "password" in data:
        # Existing clients may still send a password. New forms omit both
        # fields; never manufacture an empty or temporary credential.
        password = data["password"]
        if not isinstance(password, str) or not 6 <= len(password) <= 1024:
            raise ValueError("Password must contain 6–1024 characters.")
        if confirmation and password != data.get("confirm_password"):
            raise ValueError("Passwords must match.")
    elif data.get("confirm_password") not in (None, ""):
        raise ValueError("Passwords must match.")
    if not names.ensure_directory(web.USERS_FILE)["ready"]:
        raise ValueError("Registration is paused while administrators resolve duplicate registered names.")
    if any(names.normalize_name(a.get("name", k)) == names.normalize_name(name)
           and (not allow_account_id or str(a.get("account_id")) != str(allow_account_id))
           for k, a in web.users_data()["users"].items()):
        raise names.RegisteredNameError("This registered name is already in use.", "registered_name_taken")
    with closing(connect(web.USERS_FILE)) as db:
        if db.execute("SELECT 1 FROM account_claims WHERE normalized_name=? AND status IN ('pending','approving')", (names.normalize_name(name),)).fetchone():
            raise ValueError("This name has a pending registration. Please contact an administrator.")
    return name, password


def creation_schema(club):
    # The player row and its publication intent commit in the SAME club DB.
    # A crash cannot leave a new player indistinguishable from an old identity.
    club.execute("""CREATE TABLE IF NOT EXISTS account_creation_intents (
      account_id TEXT PRIMARY KEY, player_id INTEGER NOT NULL UNIQUE,
      accounts_path TEXT NOT NULL, registered_name TEXT NOT NULL, normalized_name TEXT NOT NULL,
      password_hash TEXT, status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(player_id) REFERENCES players(id)
    )""")
    column = next((row for row in club.execute("PRAGMA table_info(account_creation_intents)")
                   if row[1] == "password_hash"), None)
    if column and column[3]:
        try:
            club.execute("BEGIN IMMEDIATE")
            club.execute("ALTER TABLE account_creation_intents RENAME TO account_creation_intents_password_old")
            club.execute("""CREATE TABLE account_creation_intents (
              account_id TEXT PRIMARY KEY, player_id INTEGER NOT NULL UNIQUE,
              accounts_path TEXT NOT NULL, registered_name TEXT NOT NULL, normalized_name TEXT NOT NULL,
              password_hash TEXT, status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(player_id) REFERENCES players(id)
            )""")
            club.execute("""INSERT INTO account_creation_intents
              (account_id,player_id,accounts_path,registered_name,normalized_name,password_hash,status,created_at)
              SELECT account_id,player_id,accounts_path,registered_name,normalized_name,password_hash,status,created_at
              FROM account_creation_intents_password_old""")
            club.execute("DROP TABLE account_creation_intents_password_old")
            club.commit()
        except Exception:
            club.rollback()
            raise
    club.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_creation_name ON account_creation_intents(normalized_name) WHERE status='pending'")
    club.commit()


def publish_creation(web, record):
    with names.account_lock(web.USERS_FILE):
        if record.get("accounts_path") != str(Path(web.USERS_FILE).resolve()):
            raise ValueError("Registration recovery needs administrator review.")
        directory = names.read_accounts(web.USERS_FILE)
        found = [(key, user) for key, user in directory["users"].items()
                 if str(user.get("account_id")) == record["account_id"]]
        if any(str(user.get("club_player_id")) == str(record["player_id"]) and
               str(user.get("account_id")) != str(record["account_id"]) for user in directory["users"].values()):
            raise ValueError("Registration recovery needs administrator review; no existing account was changed.")
        with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as club:
            source = club.execute("SELECT id,name FROM players WHERE id=?", (record["player_id"],)).fetchone()
        if source is None or (not found and names.normalize_name(source["name"]) != record["normalized_name"]):
            raise ValueError("Registration recovery needs administrator review; the original player was changed.")
        if not found:
            if any(names.normalize_name(user.get("name", key)) == record["normalized_name"]
                   for key, user in directory["users"].items()):
                raise ValueError("Registration recovery needs administrator review; no existing account was changed.")
            directory["users"][record["normalized_name"]] = {
                "name":record["registered_name"], "salt":"", "password_hash":record["password_hash"],
                "role":"user", "account_id":record["account_id"], "club_player_id":record["player_id"]}
            names.write_accounts(web.USERS_FILE, directory)
        elif len(found) != 1 or found[0][1].get("club_player_id") != record["player_id"]:
            raise ValueError("Registration recovery needs administrator review.")
        with closing(connect(web.USERS_FILE)) as db, db:
            if not db.execute("SELECT 1 FROM account_registration_audit WHERE action='register_new' AND actor_id=?",
                              (record["account_id"],)).fetchone():
                audit(db, "register_new", record["account_id"], name=record["registered_name"], club_player_id=record["player_id"])
        with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as club, club:
            club.execute("UPDATE account_creation_intents SET status='published',password_hash='' WHERE account_id=?",
                         (record["account_id"],))


def recover_creations(web):
    path = Path(web.MAHJONG_DB_FILE)
    if not path.is_file():
        return
    with names.account_lock(web.USERS_FILE):
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_creation_intents'").fetchone():
                return
            pending = [dict(row) for row in db.execute("SELECT * FROM account_creation_intents WHERE status='pending' AND accounts_path=?",
                (str(Path(web.USERS_FILE).resolve()),))]
        for record in pending:
            publish_creation(web, record)


def initialize(web):
    with names.account_lock(web.USERS_FILE):
        with closing(connect(web.USERS_FILE)):
            pass
        with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as club:
            creation_schema(club)
        recover_creations(web)


def search_players(web, query="", cursor="", limit=10, *, played_only=False):
    """Search canonical club-player IDs without exposing website account IDs."""
    if not isinstance(query, str) or len(query) > 128:
        raise ValueError("Search must contain no more than 128 characters.")
    try:
        limit = max(1, min(25, int(limit)))
        offset = max(0, min(100000, int(cursor or 0)))
    except (TypeError, ValueError):
        raise ValueError("Invalid search page.") from None
    raw_query = query.strip()
    if not raw_query:
        return {"users": [], "next_cursor": None, "has_more": False}
    numeric = re.fullmatch(r"(?:(?:club-)|(?:historical:))?([1-9][0-9]{0,18})", raw_query)
    normalized = names.normalize_name(raw_query)
    with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as db:
        db.create_function("account_search_normalize", 1, names.normalize_name, deterministic=True)
        where = ["EXISTS (SELECT 1 FROM game_players gp WHERE gp.player_id=p.id)"] if played_only else []
        arguments = []
        if numeric and int(numeric.group(1)) <= 9223372036854775807:
            where.append("p.id=?")
            arguments.append(int(numeric.group(1)))
            order = "p.id"
        else:
            where.append("instr(account_search_normalize(p.name),?)>0")
            arguments.append(normalized)
            order = "CASE WHEN account_search_normalize(p.name)=? THEN 0 WHEN substr(account_search_normalize(p.name),1,length(?))=? THEN 1 ELSE 2 END, account_search_normalize(p.name),p.id"
            arguments.extend((normalized, normalized, normalized))
        rows = db.execute(
            "SELECT p.id,p.name FROM players p WHERE " + " AND ".join(where)
            + " ORDER BY " + order + " LIMIT ? OFFSET ?",
            (*arguments, limit + 1, offset),
        ).fetchall()
    more = len(rows) > limit
    return {
        "users": [{"id": "club-" + str(row["id"]), "name": row["name"], "display_id": str(row["id"])}
                  for row in rows[:limit]],
        "next_cursor": str(offset + limit) if more else None,
        "has_more": more,
    }


def _matching_account(data, player):
    linked = [(key, account) for key, account in data.get("users", {}).items()
              if str(account.get("club_player_id")) == str(player["id"])]
    if len(linked) > 1:
        raise ValueError("This player ID has conflicting website accounts. Please contact an administrator.")
    if linked:
        return linked[0]
    by_name = [(key, account) for key, account in data.get("users", {}).items()
               if account.get("club_player_id") in (None, "")
               if names.normalize_name(account.get("name", key)) == names.normalize_name(player["name"])]
    if len(by_name) > 1:
        raise ValueError("This player ID has conflicting website accounts. Please contact an administrator.")
    return by_name[0] if by_name else (None, None)


def _new_historical_account(data, player, claim=None):
    used = {str(account.get("account_id")) for account in data.get("users", {}).values()
            if account.get("account_id")}
    preferred = str(claim["account_id"]) if claim else "club-" + str(player["id"])
    account_id = preferred if preferred not in used else secrets.token_urlsafe(24)
    return {
        "name": player["name"],
        "salt": "",
        "password_hash": claim["password_hash"] if claim else None,
        "role": "user",
        "account_id": account_id,
        "club_player_id": int(player["id"]),
        "status": "active",
        "auto_registered": True,
    }


def sync_historical_accounts(web):
    """Activate every player with a recorded game without guessing orphan ownership."""
    with names.account_lock(web.USERS_FILE):
        recover_creations(web)
        with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as club:
            all_players = [dict(row) for row in club.execute("SELECT id,name FROM players ORDER BY id")]
            eligible_ids = {row[0] for row in club.execute("SELECT DISTINCT player_id FROM game_players")}
        players_by_id = {int(player["id"]): player for player in all_players}
        eligible = [player for player in all_players if int(player["id"]) in eligible_ids]
        directory = names.read_accounts(web.USERS_FILE)
        changed = False
        # Missing links are not enough evidence to delete an account: a partial
        # restore or mismatched mount can look the same. Confirmed merge recovery
        # is handled separately from its audit evidence.
        for key, account in list(directory.get("users", {}).items()):
            linked = account.get("club_player_id")
            if linked is not None:
                try:
                    current = players_by_id.get(int(linked))
                except (TypeError, ValueError):
                    current = None
                if current is None:
                    continue
            else:
                matches = [player for player in all_players
                           if names.normalize_name(player["name"]) == names.normalize_name(account.get("name", key))]
                if len(matches) == 1:
                    account["club_player_id"] = int(matches[0]["id"])
                    changed = True

        with closing(connect(web.USERS_FILE)) as claims_db:
            claim_rows = {int(row["legacy_player_id"]): dict(row) for row in claims_db.execute(
                "SELECT * FROM account_claims WHERE status IN ('pending','approving') ORDER BY created_at")}

        for player in eligible:
            key, account = _matching_account(directory, player)
            if account is not None:
                if account.get("club_player_id") != int(player["id"]):
                    account["club_player_id"] = int(player["id"])
                    changed = True
                continue
            if int(player["id"]) in claim_rows:
                # Background sync must not replace administrator review.
                continue
            normalized = names.normalize_name(player["name"])
            if normalized in directory["users"]:
                # A key collision with another identity needs review.
                continue
            directory["users"][normalized] = _new_historical_account(directory, player)
            changed = True

        if changed:
            names.write_accounts(web.USERS_FILE, directory)
        return {"created": sum(1 for account in directory["users"].values() if account.get("auto_registered"))}


def ensure_player_account(web, player):
    """Return the unique active account for a played club player, creating it if needed."""
    with names.account_lock(web.USERS_FILE):
        directory = names.read_accounts(web.USERS_FILE)
        key, account = _matching_account(directory, player)
        if account is None:
            normalized = names.normalize_name(player["name"])
            if normalized in directory["users"]:
                raise ValueError("This player ID has conflicting website accounts. Please contact an administrator.")
            account = _new_historical_account(directory, player)
            directory["users"][normalized] = account
            names.write_accounts(web.USERS_FILE, directory)
        elif account.get("club_player_id") != int(player["id"]):
            account["club_player_id"] = int(player["id"])
            names.write_accounts(web.USERS_FILE, directory)
        return dict(account)


def inspect_player_account_merge(web, source, target):
    """Validate directory-side merge hazards before the club DB is committed."""
    with names.account_lock(web.USERS_FILE):
        directory = names.read_accounts(web.USERS_FILE)
        source_key, source_account = _matching_account(directory, source)
        target_key, target_account = _matching_account(directory, target)
        destination_key = names.normalize_name(target["name"])
        destination_account = directory.get("users", {}).get(destination_key)
        moves_to_destination = target_account is None or source_account is target_account
        if (moves_to_destination and destination_account is not None
                and destination_account is not source_account
                and destination_account is not target_account):
            raise ValueError("The target player name conflicts with another website account.")
        return {
            "source_account": dict(source_account) if source_account is not None else None,
            "target_account": dict(target_account) if target_account is not None else None,
            "deletes_source": bool(source_account is not None and target_account is not None
                                   and source_account is not target_account),
            "source_key": source_key,
            "target_key": target_key,
        }


def merge_player_accounts(web, source, target):
    """Publish the account-directory half of a completed club-player merge."""
    with names.account_lock(web.USERS_FILE):
        directory = names.read_accounts(web.USERS_FILE)
        source_key, source_account = _matching_account(directory, source)
        target_key, target_account = _matching_account(directory, target)
        source_account_id = str(source_account.get("account_id") or "") if source_account else ""
        revoke_source = False

        if source_account is not None and target_account is source_account:
            source_account["role"] = source_account.get("role") or web.default_role_for_name(
                source_account.get("name", source["name"]))
            target_account.update(name=target["name"], club_player_id=int(target["id"]))
            old_key = source_key
            target_key = names.normalize_name(target["name"])
            if old_key != target_key:
                if target_key in directory["users"] and directory["users"][target_key] is not target_account:
                    raise ValueError("The target player name conflicts with another website account.")
                directory["users"].pop(old_key, None)
                directory["users"][target_key] = target_account
        elif target_account is not None:
            if source_account is not None:
                # Target identity, password, bindings and role are authoritative.
                # Never turn a source privilege into a target privilege.
                directory["users"].pop(source_key, None)
                revoke_source = True
            target_account.update(name=target["name"], club_player_id=int(target["id"]))
        elif source_account is not None:
            # No target login exists: this is the same person's only stable
            # identity, so rebind it to the surviving club player.
            directory["users"].pop(source_key, None)
            source_account["role"] = source_account.get("role") or web.default_role_for_name(
                source_account.get("name", source["name"]))
            source_account.update(name=target["name"], club_player_id=int(target["id"]))
            target_key = names.normalize_name(target["name"])
            if target_key in directory["users"] and directory["users"][target_key] is not source_account:
                raise ValueError("The target player name conflicts with another website account.")
            directory["users"][target_key] = source_account
            target_account = source_account
        else:
            target_key = names.normalize_name(target["name"])
            if target_key in directory["users"]:
                raise ValueError("The target player name conflicts with another website account.")
            target_account = _new_historical_account(directory, target)
            directory["users"][target_key] = target_account

        icons = directory.setdefault("player_icons", {})
        source_icon_key = names.normalize_name(source["name"])
        target_icon_key = names.normalize_name(target["name"])
        if source_icon_key in icons and target_icon_key not in icons:
            icons[target_icon_key] = icons[source_icon_key]
        if source_icon_key != target_icon_key:
            icons.pop(source_icon_key, None)

        names.write_accounts(web.USERS_FILE, directory)
        target_account_id = str(target_account.get("account_id") or "")
        if revoke_source and source_account_id:
            names.revoke_sessions(web.USERS_FILE, source_account_id)
        with closing(connect(web.USERS_FILE)) as db, db:
            db.execute("""UPDATE account_claims SET status='rejected',password_hash='',reviewed_by='system:player-merge',
                reviewed_at=CURRENT_TIMESTAMP,reason=?
                WHERE legacy_player_id=? AND status IN ('pending','approving')""",
                ("Player merged into club-" + str(target["id"]), int(source["id"])))
        return {"source_account_id": source_account_id or None,
                "target_account_id": target_account_id or None,
                "source_sessions_revoked": revoke_source}


def create_new(web, data, *, confirmation=True):
    with names.account_lock(web.USERS_FILE):
        recover_creations(web)
        name, password = validate(web, data, confirmation=confirmation)
        digest = hash_password(password)[1] if password is not None else None
        account_id = secrets.token_urlsafe(24)
        with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as club:
            creation_schema(club)
            try:
                club.execute("BEGIN IMMEDIATE")
                if any(names.normalize_name(p[0]) == names.normalize_name(name) for p in club.execute("SELECT name FROM players")):
                    raise ValueError("This is an existing ID. Select the player name at sign-in.")
                cursor = club.execute("INSERT INTO players(name,name_key) VALUES(?,?)", (name, mahjong_store.normalize_name(name)))
                record = {"account_id":account_id, "player_id":cursor.lastrowid,
                          "accounts_path":str(Path(web.USERS_FILE).resolve()), "registered_name":name,
                          "normalized_name":names.normalize_name(name), "password_hash":digest}
                club.execute("""INSERT INTO account_creation_intents(account_id,player_id,accounts_path,registered_name,normalized_name,password_hash)
                    VALUES(:account_id,:player_id,:accounts_path,:registered_name,:normalized_name,:password_hash)""", record)
                club.commit()
            except Exception:
                club.rollback()
                raise
        publish_creation(web, record)
        web.clear_sheet_cache()
        return name


def submit_claim(web, data):
    if not isinstance(data, dict):
        raise ValueError("Invalid registration form.")
    with names.account_lock(web.USERS_FILE):
        recover_creations(web)
        player = legacy_player(web, data.get("player_id", data.get("legacy_id")))
        if "player_id" in data and "legacy_id" in data and player_id(data["legacy_id"]) != player["id"]:
            raise ValueError("Select one existing player.")
        if is_claimed(web, player):
            raise ValueError(ALREADY)
        current_name = names.display_name(player["name"])
        if "username" in data and (not isinstance(data["username"], str)
                or names.normalize_name(data["username"]) != names.normalize_name(current_name)):
            raise names.RegisteredNameError("Existing player registration uses the selected player's current name.", "existing_player_name_mismatch")
        _, existing_account = _matching_account(web.users_data(), player)
        account_id = (existing_account["account_id"] if existing_account is not None
                      and _claimable_auto_account(existing_account, player)
                      else account_legacy_links.identity(web, player))
        name, password = validate(web, {**data, "username": current_name},
                                  allow_account_id=account_id)
        token, claim_id = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with closing(connect(web.USERS_FILE)) as db:
            try:
                db.execute("""INSERT INTO account_claims(id,legacy_player_id,legacy_name,registered_name,normalized_name,
                  password_hash,account_id,resume_hash,return_to,bind_discord) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (claim_id, player["id"], player["name"], name, names.normalize_name(name),
                   hash_password(password)[1] if password is not None else None,
                   account_id, hashlib.sha256(token.encode()).hexdigest(), safe_return(data.get("redirect_url")), int(data.get("bind_discord") is True)))
                audit(db, "claim_submitted", "applicant", claim_id=claim_id, legacy_player_id=player["id"], name=name)
                db.commit()
            except sqlite3.IntegrityError:
                raise ValueError("This ID has a pending registration. Please contact an administrator.") from None
        return token


def claims(web):
    with names.account_lock(web.USERS_FILE):
        web.users_data()
        with closing(connect(web.USERS_FILE)) as db:
            rows = [dict(r) for r in db.execute("""SELECT id,legacy_player_id,legacy_name,registered_name,status,created_at,reason
              FROM account_claims ORDER BY created_at DESC LIMIT 200""")]
        with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as club:
            current = {r["id"]: r["name"] for r in club.execute("SELECT id,name FROM players")}
        for row in rows:
            source = current.get(row.pop("legacy_player_id"))
            if source is not None and row["status"] in {"pending", "approving"}:
                row["legacy_name"] = row["registered_name"] = source
        return rows


def _canonical_claim(web, claim):
    # Account lock covers source-name reads and all publication phases. Reading
    # accounts first finishes any old, already committed registered-name journal.
    directory = web.users_data()
    player = legacy_player(web, claim["legacy_player_id"])
    if is_claimed(web, player, claim["account_id"]):
        raise ValueError(ALREADY)
    own = [a for a in directory["users"].values() if a.get("account_id") == claim["account_id"]]
    if own and (len(own) != 1 or str(own[0].get("club_player_id")) != str(player["id"])):
        raise ValueError("Registration recovery needs administrator review; no existing account was changed.")
    name = names.display_name(player["name"])
    if own and (own[0].get("disabled") or own[0].get("is_active") is False
                or own[0].get("status") not in {None, "active", "pending_claim"}):
        raise ValueError("This ID is unavailable. Please contact an administrator.")
    if (own and own[0].get("status") != "pending_claim"
            and not _claimable_auto_account(own[0], player)
            and own[0].get("name") != name):
        # A separately owned active account must never be renamed by a claim.
        raise ValueError("Registration recovery needs administrator review; no existing account was changed.")
    with closing(connect(web.USERS_FILE)) as db:
        if db.execute("SELECT 1 FROM account_claims WHERE id<>? AND normalized_name=? AND status IN ('pending','approving')",
                      (claim["id"], names.normalize_name(name))).fetchone():
            raise ValueError("This name has a pending registration. Please contact an administrator.")
    return {**claim, "registered_name": name, "normalized_name": names.normalize_name(name)}, directory


def publish_approved(web, claim):
    """Replay durable approval using the original row's current name, never rename it."""
    with names.account_lock(web.USERS_FILE):
        # Reload the durable journal, rather than trusting a caller's stale snapshot.
        with closing(connect(web.USERS_FILE)) as db:
            row = db.execute("SELECT * FROM account_claims WHERE id=?", (claim["id"],)).fetchone()
        if not row or row["status"] not in {"approving", "approved"}:
            raise ValueError("Administrator approval is required.")
        if row["status"] == "approved":
            return
        claim, directory = _canonical_claim(web, dict(row))
        with closing(connect(web.USERS_FILE)) as db, db:
            db.execute("UPDATE account_claims SET registered_name=?,normalized_name=? WHERE id=?",
                       (claim["registered_name"], claim["normalized_name"], claim["id"]))
        found = [(k, a) for k, a in directory["users"].items() if a.get("account_id") == claim["account_id"]]
        if not found:
            directory["users"][claim["normalized_name"]] = {
                "name": claim["registered_name"], "salt": "", "password_hash": claim["password_hash"],
                "account_id": claim["account_id"], "club_player_id": claim["legacy_player_id"],
                "role": "user", "status": "pending_claim",
            }
            names.write_accounts(web.USERS_FILE, directory)
        elif found[0][1].get("name") != claim["registered_name"]:
            # Only the unpublished account may follow a source correction. This
            # does not change the source player or any existing score/history row.
            key, account = found[0]
            del directory["users"][key]
            account["name"] = claim["registered_name"]
            directory["users"][claim["normalized_name"]] = account
            names.write_accounts(web.USERS_FILE, directory)
        account_legacy_links.publish(web, claim)
        directory = web.users_data()
        for account in directory["users"].values():
            if account.get("account_id") == claim["account_id"]:
                account["status"] = "active"
                if account.get("auto_registered") is True:
                    account["auto_registered"] = False
        names.write_accounts(web.USERS_FILE, directory)
        with closing(connect(web.USERS_FILE)) as db, db:
            db.execute("UPDATE account_claims SET status='approved',password_hash='' WHERE id=?", (claim["id"],))
        web.clear_sheet_cache()


def review(web, data, actor):
    if not web.is_admin(actor):
        raise PermissionError("Only administrators can review claims.")
    decision = data.get("decision")
    if decision not in {"approve", "reject"}:
        raise ValueError("Choose approve or reject.")
    with names.account_lock(web.USERS_FILE), closing(connect(web.USERS_FILE)) as db:
        recover_creations(web)
        row = db.execute("SELECT * FROM account_claims WHERE id=?", (str(data.get("claim_id", "")),)).fetchone()
        if not row:
            raise ValueError("Claim not found.")
        claim = dict(row)
        if claim["status"] not in {"pending", "approving"}:
            return {"ok": True, "status": claim["status"]}
        if claim["status"] == "approving" and decision != "approve":
            raise ValueError("An approved claim is being activated. Retry approval to finish.")
        if decision == "approve":
            claim, _ = _canonical_claim(web, claim)
        status = "approving" if decision == "approve" else "rejected"
        reviewer = web.stable_account_id(actor)
        db.execute("UPDATE account_claims SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP,reason=?,registered_name=?,normalized_name=? WHERE id=?",
                   (status, reviewer, str(data.get("reason", ""))[:500], claim["registered_name"], claim["normalized_name"], claim["id"]))
        if decision == "reject":
            db.execute("UPDATE account_claims SET password_hash='' WHERE id=?", (claim["id"],))
        audit(db, "claim_" + decision, reviewer, claim_id=claim["id"], legacy_player_id=claim["legacy_player_id"])
        db.commit()
        if decision == "approve":
            publish_approved(web, {**claim, "reviewed_by": reviewer})
        return {"ok": True, "status": "approved" if decision == "approve" else "rejected"}


def resume(web, token):
    with names.account_lock(web.USERS_FILE), closing(connect(web.USERS_FILE)) as db:
        row = db.execute("SELECT * FROM account_claims WHERE resume_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row:
            return {"status": "none"}, None
        claim = dict(row)
        if claim["status"] == "approving":
            publish_approved(web, claim)
            claim["status"] = "approved"
        if claim["status"] != "approved":
            return {"status": claim["status"]}, None
        # One browser completion per approval; subsequent access uses normal login.
        db.execute("UPDATE account_claims SET resume_hash=? WHERE id=?", (secrets.token_hex(32), claim["id"]))
        db.commit()
        return {"status": "approved", "redirect_url": claim["return_to"], "bind_discord": bool(claim["bind_discord"])}, claim["account_id"]
