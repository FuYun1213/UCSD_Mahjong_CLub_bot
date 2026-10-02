"""Restartable additive V9 migration; no reservation or participant is merged/deleted."""
from datetime import timedelta
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session
from .database_models import Metadata
from .table_models import ClubTable, TableReservation
from .reservation_sessions import assign_session, instant, lock_scope


def prepare_reservation_sessions(engine):
    existing = {column["name"] for column in inspect(engine).get_columns("table_reservations")}
    with engine.begin() as connection:
        if not {"end_at", "session_id"} <= existing:
            connection.execute(text("DELETE FROM nfc_metadata WHERE key='reservation_sessions_v9_migrated'"))
        if "end_at" not in existing:
            connection.execute(text("ALTER TABLE table_reservations ADD COLUMN end_at VARCHAR(40)"))
        if "session_id" not in existing:
            connection.execute(text("ALTER TABLE table_reservations ADD COLUMN session_id VARCHAR(64) REFERENCES reservation_sessions(id)"))


def migrate_reservation_sessions(engine):
    with Session(engine) as db, db.begin():
        if not db.get(Metadata, "reservation_sessions_v9_migrated"):
            # The global migration row also protects an empty registry and two
            # app instances performing the first backfill at the same time.
            lock_scope(db, "__reservation_migration_v9__")
            db.expire_all()
            if not db.get(Metadata, "reservation_sessions_v9_migrated"):
                _backfill(db)
                db.add(Metadata(key="reservation_sessions_v9_migrated", value="1"))
    with engine.begin() as connection:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_window ON reservation_sessions(table_id,status,end_at,start_at,id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_candidate ON reservation_sessions(scope,status,start_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_session_status ON table_reservations (session_id,status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_start_status ON table_reservations (scheduled_at,status)"))
        if engine.dialect.name == "sqlite":
            for operation in ("INSERT", "UPDATE"):
                connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS check_reservation_end_{operation.lower()} BEFORE {operation} ON table_reservations WHEN NEW.end_at IS NULL OR NEW.end_at <= NEW.scheduled_at BEGIN SELECT RAISE(ABORT,'invalid_reservation_end'); END"))
        elif engine.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE table_reservations ALTER COLUMN end_at SET NOT NULL"))
            checks = {row["name"] for row in inspect(connection).get_check_constraints("table_reservations")}
            if "check_reservation_end_v9" not in checks:
                connection.execute(text("ALTER TABLE table_reservations ADD CONSTRAINT check_reservation_end_v9 CHECK (end_at > scheduled_at)"))


def _backfill(db):
    for scope in sorted({table.scope for table in db.scalars(select(ClubTable))}):
        lock_scope(db, scope)
    rows = list(db.scalars(select(TableReservation).order_by(
        TableReservation.scheduled_at, TableReservation.created_at, TableReservation.id)))
    for row in rows:
        row.scheduled_at = instant(row.scheduled_at).isoformat(timespec="milliseconds")
        if not row.end_at:
            row.end_at = (instant(row.scheduled_at)+timedelta(hours=1)).isoformat(timespec="milliseconds")
        else:
            row.end_at = instant(row.end_at).isoformat(timespec="milliseconds")
        if not row.session_id:
            table = db.get(ClubTable, row.table_id)
            if row.status == "active":
                assign_session(db, row, table, row.updated_at or row.created_at)
            else:
                # Preserve individual ownership and inactive history in a
                # cancelled logical session, excluded from all grouping.
                from uuid import uuid4
                from .reservation_session_models import ReservationSession
                session = ReservationSession(id=str(uuid4()),scope=table.scope,table_id=table.id,
                    start_at=row.scheduled_at,end_at=row.end_at,status="cancelled",
                    created_at=row.created_at,updated_at=row.updated_at or row.created_at)
                db.add(session); db.flush(); row.session_id=session.id
