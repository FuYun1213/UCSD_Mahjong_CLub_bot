import json
import sqlite3

from sqlalchemy import func, select

from mahjong_api.database_models import MatchPlayer
from mahjong_api.scoring import calculate_match_result
from mahjong_api.store import Store


def test_v1_sqlite_migrates_without_inventing_durations(tmp_path):
    path = tmp_path / "old.sqlite3"
    scores = {"east": 35000, "south": 20000, "west": 15000, "north": 30000}
    points = calculate_match_result(scores)
    result = {"table": "1", "round": 1, "match_id": "old-match", "played_at": "2026-09-01T00:00:00Z",
              "players": {seat: {"user": {"id": seat, "name": seat}, **value} for seat, value in points.items()}}
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE nfc_tables(slot INTEGER PRIMARY KEY AUTOINCREMENT,table_id TEXT UNIQUE,round_no INTEGER,
            current_match_id TEXT UNIQUE,pending_match_id TEXT,updated_at TEXT,dirty INTEGER);
        CREATE TABLE nfc_matches(sequence INTEGER PRIMARY KEY AUTOINCREMENT,match_id TEXT UNIQUE,table_id TEXT,
            round_no INTEGER,scores_json TEXT,result_json TEXT,history_synced INTEGER,clear_synced INTEGER);
        INSERT INTO nfc_tables VALUES(1,'1',2,'next-match',NULL,'2026-09-01',0);
        """)
        db.execute("INSERT INTO nfc_matches VALUES(1,?,?,?,?,?,?,?)", ("old-match", "1", 1, json.dumps(scores), json.dumps(result), 1, 1))
    store = Store(path)
    try:
        assert store.stats()["average_duration_seconds"] is None
        assert store.table("1")["round_no"] == 2
        assert store.match("old-match")["result"] == result
        with store.connect() as db:
            assert db.scalar(select(func.count()).select_from(MatchPlayer)) == 4
    finally:
        store.close()
    store = Store(path)
    try:
        with store.connect() as db:
            assert db.scalar(select(func.count()).select_from(MatchPlayer)) == 4
    finally:
        store.close()


def test_existing_store_preserves_rank_and_seat_separately(tmp_path):
    import mahjong_store

    connection = mahjong_store.connect(tmp_path / "legacy.sqlite3")
    try:
        game_id = mahjong_store.import_game(connection, ["N", "E", "S", "W"], [40000, 30000, 20000, 10000],
            "2026-09-16 12:00:00", seat_winds=["north", "east", "south", "west"], source_seat_order="EWSN")
        rows = connection.execute("SELECT rank_order,seat_wind,source_position FROM game_players WHERE game_id=? ORDER BY rank_order", (game_id,)).fetchall()
        assert [tuple(row) for row in rows] == [(0, "north", 3), (1, "east", 0), (2, "south", 2), (3, "west", 1)]
        assert connection.execute("SELECT source_seat_order FROM games WHERE id=?", (game_id,)).fetchone()[0] == "EWSN"
    finally:
        connection.close()


def test_existing_website_session_id_is_stable(tmp_path, monkeypatch):
    import web_server

    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"users": {"alice": {"name": "Alice", "password_hash": "unchanged"}}}), encoding="utf-8")
    monkeypatch.setattr(web_server, "USERS_FILE", path)
    first = web_server.stable_account_id("Alice")
    assert first == web_server.stable_account_id("ALICE")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["users"]["alice"]["password_hash"] == "unchanged"
    data["users"]["renamed"] = data["users"].pop("alice")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert web_server.stable_account_id("renamed") == first


def test_legacy_payload_order_is_ewsn():
    import web_server

    entries = web_server.game_entries_from_payload({f"rank{i}_name": str(i) for i in range(1, 5)})
    assert [entry["seatWind"] for entry in entries] == ["E", "W", "S", "N"]
