"""Add scoped guest identities without recalculating or relabelling score history."""
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from .guest_models import TournamentParticipant
from .tournament_models import Tournament
from .database_models import Metadata
from .tournament_rules import name_key, require
from .store import now


def migrate_guests(engine):
    # A durable marker serializes simultaneous process startup. All backfills and
    # the final marker commit together, so interrupted upgrades safely retry.
    with Session(engine) as db, db.begin():
        if engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        key = "registration_tournament_v10"
        db.execute(insert(Metadata).values(key=key, value="pending").on_conflict_do_nothing(index_elements=[Metadata.key]))
        marker = db.scalar(select(Metadata).where(Metadata.key == key).with_for_update())
        if marker.value == "1":
            return
        for row in db.scalars(select(Tournament).order_by(Tournament.id)):
            state = json.loads(row.state_json)
            changed = "allow_guest_auto_enrollment" not in state["settings"]
            state["settings"].setdefault("allow_guest_auto_enrollment", False)
            for p in state["players"]:
                if not p.get("account_id") and (p.get("participant_type") == "guest" or str(p["id"]).startswith("guest-")):
                    if p.get("participant_type") != "guest":
                        p["participant_type"] = "guest"
                        changed = True
                    existing = db.get(TournamentParticipant, p["id"])
                    require(existing is None or existing.tournament_id == row.id, "guest_migration_identity_conflict")
                    if existing is None:
                        db.add(TournamentParticipant(id=p["id"], tournament_id=row.id,
                            participant_type="guest", name=p["name"], normalized_name=name_key(p["name"]),
                            created_at=state.get("created_at") or now(), created_by="migration"))
            if changed:
                row.state_json = json.dumps(state, ensure_ascii=False)
        marker.value = "1"
