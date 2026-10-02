"""Add game snapshots without guessing any historical roster or end time."""
from sqlalchemy import inspect, text


def migrate_game_rounds(engine):
    # Base.metadata.create_all creates this table. Existing matches are left
    # alone because the mutable current seat table cannot reconstruct them.
    if not inspect(engine).has_table("nfc_game_rounds"):
        return
    with engine.begin() as connection:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_game_round_table_status ON nfc_game_rounds (table_id,status,started_at)"))
        game_columns = {column["name"] for column in inspect(connection).get_columns("nfc_game_rounds")}
        if "actual_end_by" not in game_columns:
            connection.execute(text("ALTER TABLE nfc_game_rounds ADD COLUMN actual_end_by VARCHAR(128)"))
        if inspect(connection).has_table("reservation_discord_notifications"):
            columns = {column["name"] for column in inspect(connection).get_columns("reservation_discord_notifications")}
            additions = {
                "batch_id": "VARCHAR(64)",
                "predecessor_game_id": "VARCHAR(64)",
                "member_version": "INTEGER",
                "member_ids_json": "VARCHAR(2048)",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE reservation_discord_notifications ADD COLUMN {name} {definition}"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_queue_notice_batch ON reservation_discord_notifications (batch_id,status,notification_type)"))

