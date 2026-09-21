"""Additive, restartable seat-swap migration; existing seats/history stay intact."""
from uuid import uuid4
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session
from .database_models import Metadata


def migrate_seat_swaps(engine):
    fields = {"membership_id": "VARCHAR(64)", "seat_version": "INTEGER NOT NULL DEFAULT 1"}
    with engine.begin() as conn:
        existing = {c["name"] for c in inspect(conn).get_columns("active_table_members")}
        for field, definition in fields.items():
            if field not in existing:
                conn.execute(text(f"ALTER TABLE active_table_members ADD COLUMN {field} {definition}"))
    with Session(engine) as db, db.begin():
        for user_id in db.scalars(text("SELECT user_id FROM active_table_members WHERE membership_id IS NULL")):
            db.execute(text("UPDATE active_table_members SET membership_id=:identity WHERE user_id=:uid"), {"identity":str(uuid4()),"uid":user_id})
        if db.get(Metadata, "seat_swap_v1_migrated") is None:
            db.add(Metadata(key="seat_swap_v1_migrated", value="1"))
    with engine.begin() as conn:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_membership_identity ON active_table_members (membership_id)"))
        if engine.dialect.name == "sqlite":
            for operation in ("INSERT", "UPDATE"):
                conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS check_seat_swap_member_{operation.lower()} BEFORE {operation} ON active_table_members WHEN NEW.membership_id IS NULL OR NEW.seat_version IS NULL OR NEW.seat_version < 1 BEGIN SELECT RAISE(ABORT, 'invalid_membership_revision'); END"))
        elif engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE active_table_members ALTER COLUMN membership_id SET NOT NULL"))
            name = "check_seat_swap_member_revision"
            if name not in {c["name"] for c in inspect(conn).get_check_constraints("active_table_members")}:
                conn.execute(text("ALTER TABLE active_table_members ADD CONSTRAINT check_seat_swap_member_revision CHECK (seat_version >= 1)"))
