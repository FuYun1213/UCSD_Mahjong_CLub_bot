"""Additive queue migration and independent SQLite schema validation.

Historical reservation counts remain unknown until an administrator assigns them.
"""

import re
import sqlite3

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, text

from . import table_models  # Register referenced column types for standalone verification.
from .reservation_queue_models import (
    ReservationDurationSample, ReservationDurationSummary, ReservationGameLink,
    ReservationQueueAudit, ReservationQueueBatch, ReservationQueueBatchMember,
    ReservationQueueState,
)


_QUEUE_MODELS = (
    ReservationQueueState, ReservationQueueBatch, ReservationQueueBatchMember,
    ReservationGameLink, ReservationQueueAudit, ReservationDurationSample,
    ReservationDurationSummary,
)

_PLAN_INVALID = (
    "NEW.plan_kind IS NULL OR "
    "(NEW.plan_kind='finite' AND (NEW.planned_games IS NULL OR "
    "typeof(NEW.planned_games)!='integer' OR NEW.planned_games<1)) OR "
    "(NEW.plan_kind IN ('any','legacy_unknown') AND NEW.planned_games IS NOT NULL) OR "
    "NEW.plan_kind NOT IN ('finite','any','legacy_unknown')"
)

_PLAN_TRIGGERS = {
    action: (
        f"CREATE TRIGGER IF NOT EXISTS trg_reservation_plan_{action} "
        f"BEFORE {action.upper()} ON table_reservations "
        f"FOR EACH ROW WHEN ({_PLAN_INVALID}) "
        "BEGIN SELECT RAISE(ABORT, 'invalid_reservation_plan'); END"
    )
    for action in ("insert", "update")
}

_QUEUE_INDEXES = {
    "table_reservations": {
        "ix_reservation_plan_activity": ("table_id", "status", "plan_kind", "scheduled_at"),
    },
    "table_reservation_participants": {
        "ix_reservation_queue_order": ("queue_position", "reservation_id", "user_id"),
    },
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError("invalid reservation queue schema: " + message)


def _sql_key(value: str) -> str:
    return re.sub(r'[\s"\[\]]+', "", value).lower()


def _quoted_pragma(db: sqlite3.Connection, name: str, operation: str):
    # Names below come only from ORM metadata or SQLite's own index_list.
    quoted = '"' + name.replace('"', '""') + '"'
    return db.execute(f"PRAGMA {operation}({quoted})").fetchall()


def _indexes(db: sqlite3.Connection, table_name: str) -> dict[str, tuple[tuple[str, ...], bool, bool]]:
    result = {}
    for row in _quoted_pragma(db, table_name, "index_list"):
        columns = tuple(item[2] for item in _quoted_pragma(db, row[1], "index_info"))
        result[row[1]] = (columns, bool(row[2]), bool(row[4]))
    return result


def validate_reservation_queue_schema(db: sqlite3.Connection) -> None:
    """Reject partial/drifted V19 queue schemas and invalid reservation plans.

    This accepts a plain sqlite3 connection, so the offline release verifier can
    validate a migrated private copy without starting the application.
    """
    tables = dict(db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall())
    for name, required in {
        "table_reservations": {"plan_kind", "planned_games"},
        "table_reservation_participants": {"queue_position"},
    }.items():
        _require(name in tables, f"missing table {name}")
        actual = {row[1]: row for row in _quoted_pragma(db, name, "table_info")}
        _require(required <= actual.keys(), f"missing columns in {name}: {sorted(required - actual.keys())}")
    reservation_columns = {row[1]: row for row in _quoted_pragma(db, "table_reservations", "table_info")}
    _require(bool(reservation_columns["plan_kind"][3]), "nullable table_reservations.plan_kind")
    _require(reservation_columns["plan_kind"][2].upper() == "VARCHAR(16)",
             "wrong type table_reservations.plan_kind")
    _require(reservation_columns["planned_games"][2].upper() == "INTEGER",
             "wrong type table_reservations.planned_games")
    participant_columns = {row[1]: row for row in _quoted_pragma(db, "table_reservation_participants", "table_info")}
    _require(participant_columns["queue_position"][2].upper() == "INTEGER",
             "wrong type table_reservation_participants.queue_position")
    for table_name, expected in _QUEUE_INDEXES.items():
        indexes = _indexes(db, table_name)
        for index_name, columns in expected.items():
            _require(indexes.get(index_name) == (columns, False, False), f"missing or drifted index {index_name}")
    participant_fks = {
        (row[3], row[2], row[4], row[6].upper())
        for row in _quoted_pragma(db, "table_reservation_participants", "foreign_key_list")
    }
    _require(("reservation_id", "table_reservations", "id", "CASCADE") in participant_fks,
             "missing participant reservation cascade")

    for model in _QUEUE_MODELS:
        table = model.__table__
        name = table.name
        _require(name in tables, f"missing table {name}")
        actual_columns = {row[1]: row for row in _quoted_pragma(db, name, "table_info")}
        expected_columns = {column.name for column in table.columns}
        _require(expected_columns <= actual_columns.keys(),
                 f"missing columns in {name}: {sorted(expected_columns - actual_columns.keys())}")
        for column in table.columns:
            actual = actual_columns[column.name]
            _require(bool(actual[3]) == (not column.nullable), f"wrong nullability {name}.{column.name}")
            _require(actual[2].upper() == str(column.type).upper(), f"wrong type {name}.{column.name}")
        expected_pk = tuple(column.name for column in table.primary_key.columns)
        actual_pk = tuple(row[1] for row in sorted(actual_columns.values(), key=lambda row: row[5]) if row[5])
        _require(actual_pk == expected_pk, f"wrong primary key {name}")

        actual_fks = {
            (row[3], row[2], row[4], row[6].upper())
            for row in _quoted_pragma(db, name, "foreign_key_list")
        }
        expected_fks = {
            (column.name, *key.target_fullname.rsplit(".", 1), (key.ondelete or "NO ACTION").upper())
            for column in table.columns for key in column.foreign_keys
        }
        _require(actual_fks == expected_fks, f"wrong foreign keys {name}")

        indexes = _indexes(db, name)
        for index in table.indexes:
            columns = tuple(column.name for column in index.columns)
            _require(indexes.get(index.name) == (columns, bool(index.unique), False),
                     f"missing or drifted index {index.name}")
        unique_sets = {columns for columns, unique, partial in indexes.values() if unique and not partial}
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                columns = tuple(column.name for column in constraint.columns)
                _require(columns in unique_sets, f"missing unique constraint {name}:{columns}")
            if isinstance(constraint, CheckConstraint):
                expected = "check(" + str(constraint.sqltext) + ")"
                _require(_sql_key(expected) in _sql_key(tables[name]),
                         f"missing check constraint {name}:{constraint.sqltext}")

    triggers = dict(db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='table_reservations'"
    ).fetchall())
    for action, expected in _PLAN_TRIGGERS.items():
        name = f"trg_reservation_plan_{action}"
        _require(name in triggers and _sql_key(triggers[name]) == _sql_key(expected.replace("CREATE TRIGGER IF NOT EXISTS", "CREATE TRIGGER")),
                 f"missing or drifted plan trigger {name}")
    invalid = db.execute(
        "SELECT id FROM table_reservations WHERE "
        "plan_kind IS NULL OR "
        "(plan_kind='finite' AND (planned_games IS NULL OR "
        "typeof(planned_games)!='integer' OR planned_games<1)) OR "
        "(plan_kind IN ('any','legacy_unknown') AND planned_games IS NOT NULL) OR "
        "plan_kind NOT IN ('finite','any','legacy_unknown') LIMIT 5"
    ).fetchall()
    _require(not invalid, "invalid plan rows: " + ", ".join(str(row[0]) for row in invalid))


def migrate_reservation_queue(engine):
    columns = {column["name"] for column in inspect(engine).get_columns("table_reservations")}
    participant_columns = {column["name"] for column in inspect(engine).get_columns("table_reservation_participants")}
    if not {"plan_kind", "planned_games"} <= columns or "queue_position" not in participant_columns:
        raise RuntimeError("reservation queue columns missing after additive migration")
    with engine.begin() as connection:
        batch_columns = {column["name"] for column in inspect(connection).get_columns("reservation_queue_batches")}
        if "suggested_start_at" not in batch_columns:
            connection.execute(text("ALTER TABLE reservation_queue_batches ADD COLUMN suggested_start_at VARCHAR(40)"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_reservation_queue_order "
            "ON table_reservation_participants(queue_position, reservation_id, user_id)"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_reservation_plan_activity "
            "ON table_reservations(table_id, status, plan_kind, scheduled_at)"))
        for sql in _PLAN_TRIGGERS.values():
            connection.execute(text(sql))
        validate_reservation_queue_schema(connection.connection.driver_connection)
