"""Additive upgrade of the previous NFC SQLite schema; never relabel legacy ranks."""

import json

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .database_models import Base, MatchHistory, MatchPlayer, Metadata, SeatRecord, User
from .models import SEATS


def migrate(engine):
    from . import guest_models, tournament_models, table_models, manual_score_models, seat_swap_models, reservation_session_models, discord_reminder_models  # Register additive tables.
    inspector = inspect(engine)
    additions = {
        "tournaments": {"deleted_at": "VARCHAR(40)", "deleted_by": "VARCHAR(128)", "delete_reason": "TEXT"},
        "nfc_score_drafts": {"photo_sha256": "VARCHAR(64)"},
        "nfc_tables": {"started_at": "VARCHAR(40)"},
        "nfc_matches": {
            "started_at": "VARCHAR(40)", "ended_at": "VARCHAR(40)",
            "duration_seconds": "INTEGER", "uploader_id": "VARCHAR(128)",
            "seat_order": "VARCHAR(16) NOT NULL DEFAULT 'ESWN'",
            "source_seat_order": "VARCHAR(16) NOT NULL DEFAULT 'ESWN'",
        },
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
    Base.metadata.create_all(engine)
    from .reservation_session_migrations import prepare_reservation_sessions, migrate_reservation_sessions
    prepare_reservation_sessions(engine)
    from .seat_swap_migrations import migrate_seat_swaps
    migrate_seat_swaps(engine)
    # V2 is additive and runs independently of the older NFC migration marker.
    from .tournament_models import Tournament
    from .tournament_flow import upgrade_state
    with Session(engine) as db, db.begin():
        for tournament in db.scalars(select(Tournament)):
            upgrade_state(db, tournament)
        if db.get(Metadata, "tournament_v2_migrated") is None:
            db.add(Metadata(key="tournament_v2_migrated", value="1"))
    from .guest_migrations import migrate_guests
    migrate_guests(engine)
    from .table_migrations import migrate_tables
    migrate_tables(engine)
    migrate_reservation_sessions(engine)
    from .discord_reminder_migrations import migrate_discord_reminders
    migrate_discord_reminders(engine)
    from .manual_score_migrations import migrate_manual_scores
    migrate_manual_scores(engine)
    with Session(engine) as db, db.begin():
        if db.get(Metadata, "orm_v2_migrated") is not None:
            return
        for seat in db.scalars(select(SeatRecord)):
            if db.get(User, seat.user_id) is None:
                db.add(User(id=seat.user_id, name=seat.user_name))
                db.flush()
        for match in db.scalars(select(MatchHistory)):
            result = json.loads(match.result_json)
            # Earlier NFC code already used named ESWN keys. Its time was the
            # submission time, not a known start; leave duration NULL, not zero.
            for position, seat in enumerate(SEATS):
                player = result["players"][seat]
                uid = str(player["user"]["id"])
                if db.get(User, uid) is None:
                    db.add(User(id=uid, name=player["user"]["name"]))
                    db.flush()
                if db.get(MatchPlayer, (match.match_id, seat)) is None:
                    db.add(MatchPlayer(match_id=match.match_id, seat=seat, user_id=uid,
                        user_name=player["user"]["name"], initial_points=player["initial_points"],
                        final_points=player["final_points"], delta_points=player["delta_points"],
                        source_position=position))

        db.add(Metadata(key="orm_v2_migrated", value="1"))
