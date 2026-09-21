"""Idempotent additive table v3 migration. No historical match/rule result rewrites."""
import json
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session
from .database_models import TableState, SeatRecord, Metadata
from .tournament_models import Tournament, TournamentTableSession, TournamentCheckIn
from .table_models import ClubTable, ActiveTableMember, TableJoinToken, TableReservation, ReservationParticipant
from .table_membership import register_ordinary, register_tournament_table, event
from .models import User, SEATS
from .store import now


def migrate_tables(engine):
    migrate_tables_v5(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tournaments_deleted_at ON tournaments (deleted_at)"))
    with Session(engine) as db, db.begin():
        if db.get(Metadata, "table_v3_migrated"):
            return
        stamp = now()
        for score in db.scalars(select(TableState).order_by(TableState.slot)):
            table = register_ordinary(db, score)
            for seat in db.scalars(select(SeatRecord).where(SeatRecord.table_id == score.table_id)):
                if db.get(ActiveTableMember, seat.user_id) is None:
                    db.add(ActiveTableMember(user_id=seat.user_id, table_id=table.id,
                        match_id=score.current_match_id, joined_at=score.started_at or stamp,
                        join_method="manual", added_by_user_id=seat.user_id, seat=seat.seat))
                    event(db, table.id, score.current_match_id, seat.user_id, "migration",
                          "joined", "manual", score.started_at or stamp, "legacy_membership")
                    db.flush()
        for tournament in db.scalars(select(Tournament)):
            state = json.loads(tournament.state_json)
            limit = state.get("settings", {}).get("time_limit_seconds")
            if limit in (0, ""):
                state["settings"]["time_limit_seconds"] = None
                tournament.state_json = json.dumps(state, ensure_ascii=False, sort_keys=True)
            for session in db.scalars(select(TournamentTableSession).where(
                    TournamentTableSession.tournament_id == tournament.id)):
                table = register_tournament_table(db, tournament.id,
                    {"table_id": session.table_id, "number": session.number}, len(json.loads(session.roster_json)))
                if session.time_limit_seconds == 0:
                    session.time_limit_seconds = None
                    if not session.started_at:
                        session.ends_at = None
                if session.status in {"COMPLETED", "LOCKED"} or state["status"] in {"ended", "locked"}:
                    continue
                for checkin in db.scalars(select(TournamentCheckIn).where(
                        TournamentCheckIn.match_id == session.id,
                        TournamentCheckIn.generation == session.generation)):
                    # Retain original check-ins even if old data contains conflicting
                    # seating; never silently move an already active ordinary member.
                    if db.get(ActiveTableMember, checkin.account_id) is None:
                        db.add(ActiveTableMember(user_id=checkin.account_id, table_id=table.id,
                            match_id=session.id, joined_at=checkin.checked_at,
                            join_method="manual", added_by_user_id=checkin.account_id,
                            seat=tournament_seat(session, checkin.player_id)))
                        event(db, table.id, session.id, checkin.account_id, "migration", "joined",
                              "manual", checkin.checked_at, "legacy_check_in")
                        db.flush()
        db.add(Metadata(key="table_v3_migrated", value="1"))



def tournament_seat(session, player_id):
    """Translate the persisted tournament roster once, on the server."""
    roster = json.loads(session.roster_json)
    if player_id not in roster:
        return None
    index = roster.index(player_id)
    # Preserve legacy tournaments with 5–8 positions; those extra positions
    # remain unlabelled rather than inventing additional compass winds.
    return SEATS[index] if index < len(SEATS) else None


def migrate_tables_v5(engine):
    """Add columns, backfill explicit winds/participants, then enforce uniqueness.

    SQLite cannot add CHECK constraints to an existing table without rebuilding
    it, so equivalent triggers protect upgraded databases without copying data.
    PostgreSQL receives native CHECK constraints. All steps are restartable.
    """
    additions = {
        "table_join_tokens": {"purpose": "VARCHAR(24) NOT NULL DEFAULT 'table_landing'", "seat": "VARCHAR(5)"},
        "active_table_members": {"seat": "VARCHAR(5)", "status": "VARCHAR(16) NOT NULL DEFAULT 'active'", "left_at": "VARCHAR(40)"},
        "table_membership_events": {"seat": "VARCHAR(5)"},
        "table_reservations": {"version": "INTEGER NOT NULL DEFAULT 1", "updated_by": "VARCHAR(128)", "cancelled_by": "VARCHAR(128)"},
    }
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, fields in additions.items():
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, definition in fields.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        conn.execute(text("DROP INDEX IF EXISTS uq_active_table_token_channel"))
    with Session(engine) as db, db.begin():
        if db.get(Metadata, "table_v5_migrated") is None:
            for token in db.scalars(select(TableJoinToken)):
                if token.channel != "qr":
                    token.purpose = "table_join"
            for member in db.scalars(select(ActiveTableMember)):
                table = db.get(ClubTable, member.table_id)
                if table.score_table_id:
                    seat = db.scalar(select(SeatRecord).where(SeatRecord.table_id == table.score_table_id, SeatRecord.user_id == member.user_id))
                    if seat:
                        member.seat = seat.seat
                else:
                    session = db.get(TournamentTableSession, member.match_id)
                    if session:
                        checkin = db.scalar(select(TournamentCheckIn).where(TournamentCheckIn.match_id == session.id, TournamentCheckIn.account_id == member.user_id, TournamentCheckIn.generation == session.generation))
                        if checkin:
                            member.seat = tournament_seat(session, checkin.player_id)
            for reservation in db.scalars(select(TableReservation)):
                if db.get(ReservationParticipant, (reservation.id, reservation.user_id)) is None:
                    db.add(ReservationParticipant(reservation_id=reservation.id, user_id=reservation.user_id,
                        user_name=reservation.user_name, added_at=reservation.created_at))
                reservation.updated_by = reservation.user_id
            db.add(Metadata(key="table_v5_migrated", value="1"))
    constraints = {
        "table_join_tokens": "purpose IN ('table_landing','seat_join','table_join') AND ((purpose = 'seat_join' AND seat IS NOT NULL AND seat IN ('east','south','west','north')) OR (purpose != 'seat_join' AND seat IS NULL))",
        "active_table_members": "(seat IS NULL OR seat IN ('east','south','west','north')) AND status = 'active' AND left_at IS NULL",
    }
    with engine.begin() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_table_wind ON active_table_members (table_id, seat)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_table_token_landing ON table_join_tokens (table_id, channel, purpose) WHERE revoked_at IS NULL AND seat IS NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_table_token_seat ON table_join_tokens (table_id, channel, purpose, seat) WHERE revoked_at IS NULL AND seat IS NOT NULL"))
        for table, condition in constraints.items():
            if engine.dialect.name == "sqlite":
                # A single-row subquery exposes NEW columns under their original names.
                for operation in ("INSERT", "UPDATE"):
                    trigger = f"check_v5_{table}_{operation.lower()}"
                    columns = ("purpose", "seat") if table == "table_join_tokens" else ("seat", "status", "left_at")
                    projection = ", ".join(f"NEW.{c} AS {c}" for c in columns)
                    conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON {table} BEGIN SELECT CASE WHEN NOT (SELECT {condition} FROM (SELECT {projection})) THEN RAISE(ABORT, 'invalid_v5_table_data') END; END"))
            elif engine.dialect.name == "postgresql":
                name = "check_v5_" + table
                existing = {c["name"] for c in inspect(conn).get_check_constraints(table)}
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition})"))
