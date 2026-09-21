"""Explicit approved claims retain pre-existing score/seat identities.

Reads/writes only the configured score database. It never creates one or performs
name-based automatic account merging; the administrator-approved player is passed in.
"""
import json
import os
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import create_engine, inspect, text
import registered_names as names


@contextmanager
def database(web):
    url = os.getenv("NFC_DATABASE_URL")
    path = Path(os.getenv("NFC_DATABASE_PATH", str(web.ROOT / "data/nfc_matches.sqlite3")))
    # Isolated account fixtures never fall back to the real application's DB.
    if not url and (not path.exists() or not os.getenv("NFC_DATABASE_PATH") and Path(web.USERS_FILE).parent != web.ROOT):
        yield None
        return
    engine = create_engine(url or "sqlite:///" + str(path.resolve()).replace("\\", "/"))
    try:
        with engine.begin() as db:
            yield db
    finally:
        engine.dispose()


def identity(web, player):
    with database(web) as db:
        if db is None or not inspect(db).has_table("nfc_users"):
            return "club-" + str(player["id"])
        # Guest rows exist here only for score/member foreign keys. Their
        # names never make them an eligible global login identity; merging a
        # competition Guest requires the separate audited administrator flow.
        guest_ids = set()
        if inspect(db).has_table("tournament_participants"):
            guest_ids = {str(row[0]) for row in db.execute(text("SELECT id FROM tournament_participants"))}
        matches = [str(r.id) for r in db.execute(text("SELECT id,name FROM nfc_users"))
                   if not str(r.id).startswith("guest-") and str(r.id) not in guest_ids
                   and names.normalize_name(r.name) == names.normalize_name(player["name"])]
        if len(matches) > 1:
            raise ValueError("This existing ID has conflicting historical identities. Please contact an administrator.")
        return matches[0] if matches else "club-" + str(player["id"])


def publish(web, claim):
    uid = str(claim["account_id"])
    aliases = {uid, "club-" + str(claim["legacy_player_id"])}
    with database(web) as db:
        if db is None:
            return
        inspector = inspect(db)
        changes = []
        if inspector.has_table("tournaments"):
            # Validate every affected identity before updating even a display
            # name. An approval cannot overwrite an earlier explicit binding.
            for row in db.execute(text("SELECT id,version,state_json FROM tournaments")).all():
                state = json.loads(row.state_json)
                changed = False
                for player in state["players"]:
                    if str(player["id"]) not in aliases:
                        continue
                    bound = player.get("account_id")
                    if bound not in (None, "") and str(bound) != uid:
                        raise names.RegisteredNameError(
                            "This existing player is linked to a different account. Please contact an administrator.",
                            "legacy_identity_conflict")
                    if bound != uid:
                        player["account_id"] = uid
                        player["participant_type"] = "registered_user"
                        changed = True
                if changed:
                    changes.append((row, state))
        if inspector.has_table("nfc_users"):
            db.execute(text("UPDATE nfc_users SET name=:name WHERE id=:id"), {"name":claim["registered_name"],"id":uid})
        for row, state in changes:
            # The version check and enclosing transaction also protect against
            # a concurrent approval or administrator edit after the preflight.
            updated = db.execute(text("UPDATE tournaments SET state_json=:state,version=version+1 WHERE id=:id AND version=:version"),
                {"state":json.dumps(state,ensure_ascii=False),"id":row.id,"version":row.version})
            if updated.rowcount != 1:
                raise ValueError("Tournament changed during approval. Retry approval to finish linking history.")
            db.execute(text("INSERT INTO tournament_audit(tournament_id,actor_id,created_at,action,detail_json) VALUES(:tid,:actor,:at,:action,:detail)"),
                {"tid":row.id,"actor":claim["reviewed_by"],"at":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                 "action":"legacy_claim_linked","detail":json.dumps({"claim_id":claim["id"],"account_id":uid})})
