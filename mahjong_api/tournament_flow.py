"""Shared persistence helpers for tournament v2. No ordinary match data is changed."""
import copy
import json
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select, update
from .tournament_models import Tournament, TournamentTableSession, TournamentCheckIn, TournamentPenalty


def lock_tournament(db, tid):
    """Shared writer gate: acquire before reading state, then lock physical tables.

    SQLite obtains the database writer lock without changing the version. On
    PostgreSQL the row lock serializes capacity/state checks across processes.
    Callers retain the established outer membership/account lock ordering.
    """
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(Tournament).where(Tournament.id == tid).values(version=Tournament.version)
                   .execution_options(synchronize_session=False))
        row = db.get(Tournament, tid)
        if row is not None:
            db.refresh(row)
        return row
    return db.scalar(select(Tournament).where(Tournament.id == tid).with_for_update()
                     .execution_options(populate_existing=True))


def stable_id(tid, key):
    return str(uuid5(NAMESPACE_URL, "mahjong:" + tid + ":" + key))


def table_groups(state):
    for rnd in state["rounds"]:
        yield rnd["id"], rnd["tables"], rnd["status"] == "confirmed"
    final = state.get("finals")
    if final and final["status"] != "preview":
        yield final["id"], final["tables"], state["status"] in {"ended", "locked"}


def ensure_sessions(db, state, legacy=False):
    """Called in the same transaction as confirmed seating or the additive migration."""
    for rid, tables, completed in table_groups(state):
        for table in tables:
            from .table_models import ClubTable
            existing = db.scalar(select(ClubTable).where(ClubTable.tournament_id == state["id"], ClubTable.number == table["number"]))
            table.setdefault("table_id", existing.id if existing else stable_id(state["id"], "table:" + str(table["number"])))
            table.setdefault("match_id", stable_id(state["id"], rid + ":" + str(table["number"])))
            from .table_membership import register_tournament_table
            register_tournament_table(db, state["id"], table, len(table["seats"]))
            if db.get(TournamentTableSession, table["match_id"]) is None:
                status = "COMPLETED" if completed else ("SCORE_PENDING" if table.get("draft") else "IN_PROGRESS") if legacy else "WAITING_FOR_CHECK_IN"
                db.add(TournamentTableSession(id=table["match_id"], tournament_id=state["id"], round_id=rid,
                    table_id=table["table_id"], number=table["number"], roster_json=json.dumps(table["seats"]),
                    status=status, time_limit_seconds=state["settings"].get("time_limit_seconds"),
                    generation=0, legacy=int(legacy)))
    db.flush()


def penalty_dict(row):
    return {key: getattr(row, key) for key in ("id", "tournament_id", "player_id", "amount", "reason",
        "created_at", "created_by", "round_id", "match_id", "phase", "status", "revoked_at",
        "revoked_by", "revoke_reason", "replaces")}


def attach_penalties(db, state):
    state["penalties"] = [penalty_dict(p) for p in db.scalars(select(TournamentPenalty)
        .where(TournamentPenalty.tournament_id == state["id"]).order_by(TournamentPenalty.created_at, TournamentPenalty.id))]


def decorate_tables(db, state, timestamp):
    checks = list(db.scalars(select(TournamentCheckIn).where(TournamentCheckIn.tournament_id == state["id"])))
    for _, tables, _ in table_groups(state):
        for table in tables:
            row = db.get(TournamentTableSession, table["match_id"])
            if row is None:
                continue
            from .table_models import ClubTable
            registry = db.get(ClubTable, row.table_id)
            table["display_number"] = registry.number if registry else table["number"]
            checked = {c.player_id: {"at": c.checked_at} for c in checks
                       if c.match_id == row.id and c.generation == row.generation}
            status = row.status
            if state["status"] == "locked":
                status = "LOCKED"
            elif status == "IN_PROGRESS" and row.ends_at and row.ends_at <= timestamp:
                # Projection only: expiry cannot commit scores or issue a penalty.
                status = "TIME_EXPIRED"
            table["session"] = {"id": row.id, "table_id": row.table_id, "round_id": row.round_id,
                "status": status, "started_at": row.started_at, "ends_at": row.ends_at,
                "time_limit_seconds": row.time_limit_seconds, "checked_in": checked,
                "all_checked_in": set(checked) == set(table["seats"]), "legacy": bool(row.legacy)}


def upgrade_state(db, row):
    state = json.loads(row.state_json)
    if state.get("schema_version", 1) >= 2:
        return False
    # Do not touch draft/result/rules snapshots or the three existing unit fields.
    state["settings"].setdefault("scoring_mode", "legacy")
    state["settings"].setdefault("return_point", state["settings"]["base_points"])
    state["settings"].setdefault("time_limit_seconds", None)
    state["schema_version"] = 2
    state.setdefault("table_ids", {})
    if state.get("finals"):
        state["finals"].setdefault("id", stable_id(state["id"], "finals"))
    for rnd in state["rounds"] + ([state["preview"]] if state.get("preview") else []):
        for table in rnd["tables"]:
            from .table_models import ClubTable
            existing = db.scalar(select(ClubTable).where(ClubTable.tournament_id == state["id"], ClubTable.number == table["number"]))
            table.setdefault("table_id", existing.id if existing else stable_id(state["id"], "table:" + str(table["number"])))
    ensure_sessions(db, state, legacy=True)
    row.state_json = json.dumps(state, ensure_ascii=False, sort_keys=True)
    row.version += 1
    return True


def assign_registered_tables(db, state, tables):
    """Reuse immutable registered IDs; numbers need not be contiguous.
    Only new previews receive assignments. Existing results retain their snapshots.
    """
    from uuid import uuid4
    from .table_models import ClubTable
    from .table_membership import register_tournament_table
    rows = list(db.scalars(select(ClubTable).where(ClubTable.tournament_id == state["id"]).order_by(ClubTable.number)))
    available = [r for r in rows if r.status == "open"]
    used = {r.number for r in rows}
    for index, table in enumerate(tables):
        if index < len(available):
            row = available[index]
            table["table_id"], table["number"] = row.id, row.number
        else:
            number = max(used, default=0) + 1
            used.add(number)
            table["table_id"], table["number"] = str(uuid4()), number
            register_tournament_table(db, state["id"], table, state["settings"]["table_size"])
