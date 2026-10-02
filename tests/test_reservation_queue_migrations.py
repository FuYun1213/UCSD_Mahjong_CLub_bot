"""V19 queue migration rejects partial schema and invalid reservation plans."""

import sqlite3

import pytest

from mahjong_api.reservation_queue_migrations import (
    migrate_reservation_queue, validate_reservation_queue_schema,
)
from mahjong_api.store import Store


@pytest.fixture
def queue_store(tmp_path):
    store = Store(tmp_path / "nfc.sqlite3")
    try:
        yield store
    finally:
        store.close()


def connect(store):
    return sqlite3.connect(str(store.path))


def insert_reservation(db, *, row_id="reservation-1", kind="finite", count=1):
    db.execute(
        "INSERT INTO table_reservations "
        "(id,table_id,user_id,user_name,scheduled_at,end_at,plan_kind,planned_games,"
        "created_at,status,note,updated_at,version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row_id, "table-1", "user-1", "User", "2026-09-20T21:20:00+00:00",
         "2026-09-20T22:20:00+00:00", kind, count,
         "2026-09-20T21:00:00+00:00", "active", "", "2026-09-20T21:00:00+00:00", 1),
    )


def test_queue_validator_accepts_fresh_and_repeated_migration(queue_store):
    with connect(queue_store) as db:
        validate_reservation_queue_schema(db)
        insert_reservation(db, kind="legacy_unknown", count=None)
    migrate_reservation_queue(queue_store.engine)
    with connect(queue_store) as db:
        validate_reservation_queue_schema(db)
        assert db.execute("SELECT plan_kind,planned_games FROM table_reservations").fetchone() == (
            "legacy_unknown", None)


@pytest.mark.parametrize("kind,count", [
    (None, None), ("legacy_unknown", 1), ("any", 1),
    ("finite", None), ("finite", 0), ("unsupported", 1),
])
def test_plan_triggers_reject_invalid_new_and_changed_rows(queue_store, kind, count):
    with connect(queue_store) as db:
        with pytest.raises(sqlite3.IntegrityError, match="invalid_reservation_plan"):
            insert_reservation(db, kind=kind, count=count)
        insert_reservation(db, row_id="valid")
        with pytest.raises(sqlite3.IntegrityError, match="invalid_reservation_plan"):
            db.execute("UPDATE table_reservations SET plan_kind=?,planned_games=? WHERE id='valid'",
                       (kind, count))


def test_validator_rejects_legacy_unknown_with_invented_count(queue_store):
    with connect(queue_store) as db:
        db.execute("DROP TRIGGER trg_reservation_plan_update")
        insert_reservation(db, kind="legacy_unknown", count=None)
        db.execute("UPDATE table_reservations SET planned_games=3")
        # Restoring the correct trigger must not conceal an already corrupt row.
        db.commit()
    with pytest.raises(RuntimeError, match="invalid plan rows"):
        migrate_reservation_queue(queue_store.engine)


@pytest.mark.parametrize("drift,expected", [
    ("DROP INDEX ix_reservation_queue_order", "ix_reservation_queue_order"),
    ("DROP INDEX ix_reservation_queue_batch_table_status", "ix_reservation_queue_batch_table_status"),
    ("DROP TRIGGER trg_reservation_plan_update", "trg_reservation_plan_update"),
])
def test_validator_rejects_missing_indexes_or_triggers(queue_store, drift, expected):
    with connect(queue_store) as db:
        db.execute(drift)
        with pytest.raises(RuntimeError, match=expected):
            validate_reservation_queue_schema(db)


def test_repeated_migration_rejects_same_named_wrong_index(queue_store):
    with connect(queue_store) as db:
        db.execute("DROP INDEX ix_reservation_queue_order")
        db.execute("CREATE INDEX ix_reservation_queue_order ON table_reservation_participants(user_id)")
    with pytest.raises(RuntimeError, match="ix_reservation_queue_order"):
        migrate_reservation_queue(queue_store.engine)


def test_validator_rejects_nullable_plan_kind_and_null_row(queue_store):
    with connect(queue_store) as db:
        db.execute("DROP TABLE table_reservations")
        db.execute(
            "CREATE TABLE table_reservations ("
            "id VARCHAR(64) NOT NULL PRIMARY KEY, table_id VARCHAR(64) NOT NULL, "
            "user_id VARCHAR(128) NOT NULL, user_name VARCHAR(128) NOT NULL, "
            "scheduled_at VARCHAR(40) NOT NULL, end_at VARCHAR(40) NOT NULL, "
            "plan_kind VARCHAR(16), planned_games INTEGER, "
            "created_at VARCHAR(40) NOT NULL, status VARCHAR(16) NOT NULL, "
            "note TEXT NOT NULL, updated_at VARCHAR(40) NOT NULL, version INTEGER NOT NULL)"
        )
        insert_reservation(db, kind=None, count=None)
        with pytest.raises(RuntimeError, match="nullable table_reservations.plan_kind"):
            validate_reservation_queue_schema(db)


def test_validator_rejects_missing_queue_foreign_key_and_status_check(queue_store):
    with connect(queue_store) as db:
        db.execute("DROP TABLE reservation_game_links")
        db.execute(
            "CREATE TABLE reservation_game_links ("
            "game_id VARCHAR(64) NOT NULL, user_id VARCHAR(128) NOT NULL, "
            "reservation_id VARCHAR(64) NOT NULL, batch_id VARCHAR(64), "
            "status VARCHAR(16) NOT NULL, linked_at VARCHAR(40) NOT NULL, "
            "updated_at VARCHAR(40) NOT NULL, PRIMARY KEY(game_id,user_id))"
        )
        with pytest.raises(RuntimeError, match="wrong foreign keys reservation_game_links"):
            validate_reservation_queue_schema(db)
        db.execute(
            "CREATE INDEX ix_reservation_game_link_reservation "
            "ON reservation_game_links(reservation_id,user_id,status)"
        )
        # Still lacks both the batch FK and the status check.
        with pytest.raises(RuntimeError, match="wrong foreign keys reservation_game_links"):
            validate_reservation_queue_schema(db)
