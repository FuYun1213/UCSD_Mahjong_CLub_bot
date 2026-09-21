"""Legacy live-game identity migration and continuation after registered-name changes."""
from contextlib import closing
import json
import sqlite3

import pytest
import mahjong_store
import registered_names
import web_server
from test_registered_names import directory, account


def people(path):
    ids = {name: account(path, name) for name in ("Alice", "Bob", "Carol", "Dan")}
    ids["Admin"] = account(path, "Admin", role="admin")
    return ids


def seed_legacy(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE live_games(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,status TEXT NOT NULL,
            dealer_index INTEGER NOT NULL,honba INTEGER NOT NULL,round_number INTEGER NOT NULL,
            player1 TEXT NOT NULL,player2 TEXT NOT NULL,player3 TEXT NOT NULL,player4 TEXT NOT NULL,
            score1 INTEGER NOT NULL,score2 INTEGER NOT NULL,score3 INTEGER NOT NULL,score4 INTEGER NOT NULL,created_by TEXT NOT NULL);
          CREATE TABLE live_hands(id INTEGER PRIMARY KEY AUTOINCREMENT,game_id INTEGER NOT NULL,created_at TEXT NOT NULL,
            hand_type TEXT NOT NULL,dealer_index INTEGER NOT NULL,honba_before INTEGER NOT NULL,honba_after INTEGER NOT NULL,
            winner TEXT,deal_in TEXT,win_points INTEGER,deal_in_points INTEGER,yaku TEXT,dealer_tenpai INTEGER NOT NULL,
            dealer_continued INTEGER NOT NULL,notes TEXT,recorded_by TEXT NOT NULL);
          INSERT INTO live_games VALUES(17,'2026-09-19','active',0,0,1,'Alice','Bob','Unknown Legacy','Dan',25000,25000,25000,25000,'Admin');
          INSERT INTO live_hands VALUES(31,17,'2026-09-19','win',0,0,1,'Alice','Bob',1000,1000,'',0,1,'original hand','Admin');
        """)


def test_rename_migrates_legacy_live_identity_and_continues_same_game(directory):
    path, dbpath = directory
    ids = people(path)
    seed_legacy(web_server.LIVE_DB_FILE)
    with closing(mahjong_store.connect(dbpath)) as db:
        player_id = mahjong_store.upsert_player(db,"Alice")["id"]
    web_server.admin_registered_name({"user_id":ids["Alice"],"new_name":"Alice New","expected_name":"Alice","confirm":True},"Admin")
    game = web_server.active_live_games()[0]
    assert game["id"] == 17 and game["player1"] == "Alice New" and game["player1_user_id"] == ids["Alice"]
    assert game["player3"] == "Unknown Legacy" and game["player3_user_id"] is None
    updated = web_server.record_live_hand({"game_id":17,"hand_type":"win","winner":"Alice New","deal_in":"Bob","win_points":1000},"Admin")
    assert updated["id"] == 17 and updated["score1"] == 26000 and updated["score2"] == 24000
    with closing(web_server.live_db()) as db:
        raw_game = dict(db.execute("SELECT * FROM live_games WHERE id=17").fetchone())
        old_hand = dict(db.execute("SELECT * FROM live_hands WHERE id=31").fetchone())
        new_hand = dict(db.execute("SELECT * FROM live_hands ORDER BY id DESC LIMIT 1").fetchone())
    assert raw_game["player1"] == "Alice" and raw_game["player1_user_id"] == ids["Alice"]
    assert old_hand["winner"] == "Alice" and old_hand["winner_user_id"] == ids["Alice"]
    assert new_hand["winner"] == "Alice New" and new_hand["winner_user_id"] == ids["Alice"]
    assert web_server.project_live_record(old_hand, registered_names.account_rows(path))["winner"] == "Alice New"
    with sqlite3.connect(dbpath) as db:
        assert db.execute("SELECT id FROM players WHERE name='Alice New'").fetchone()[0] == player_id
    # Repeated migration leaves snapshots, primary keys and original hand count intact.
    with closing(web_server.live_db()) as db:
        assert db.execute("SELECT count(*) FROM live_hands").fetchone()[0] == 2
        assert db.execute("SELECT identity_version FROM live_hands WHERE id=31").fetchone()[0] == 1


def test_new_account_reusing_old_or_unregistered_name_cannot_claim_legacy_seat(directory):
    path, _ = directory
    ids = people(path)
    seed_legacy(web_server.LIVE_DB_FILE)
    web_server.admin_registered_name({"user_id":ids["Alice"],"new_name":"Alice New","expected_name":"Alice","confirm":True},"Admin")
    web_server.register_user({"username":"Alice","password":"new-password"})
    web_server.register_user({"username":"Unknown Legacy","password":"new-password"})
    for name in ("Alice","Unknown Legacy"):
        with pytest.raises(ValueError,match="linked to this live game"):
            web_server.record_live_hand({"game_id":17,"winner":name,"win_points":1000},"Admin")
    game = web_server.active_live_games()[0]
    assert game["player1"] == "Alice New" and game["player1_user_id"] == ids["Alice"]
    assert game["player3_user_id"] is None


def test_new_live_game_and_hand_validate_actual_accounts_and_store_ids(directory):
    path, _ = directory
    ids = people(path)
    body = {f"player{i}":name for i,name in enumerate(("Alice","Bob","Carol","Dan"),1)}
    with pytest.raises(ValueError,match="registered user"):
        web_server.create_live_game({**body,"player1":"Invented"},"Admin")
    with pytest.raises(ValueError,match="unique"):
        web_server.create_live_game({**body,"player1":"Bob"},"Admin")
    game = web_server.create_live_game({**body,"player1":"Forged display text","player1_user_id":ids["Alice"]},"Admin")
    assert game["player1"] == "Alice" and game["player1_user_id"] == ids["Alice"]
    assert game["created_by_user_id"] == ids["Admin"]
    updated = web_server.record_live_hand({"game_id":game["id"],"winner":"Forged name","winner_user_id":ids["Alice"],"deal_in_user_id":ids["Bob"],"win_points":1000},"Admin")
    assert updated["score1"] == 26000
    with closing(web_server.live_db()) as db:
        hand = dict(db.execute("SELECT * FROM live_hands").fetchone())
    assert hand["winner_user_id"] == ids["Alice"] and hand["deal_in_user_id"] == ids["Bob"]
    assert hand["recorded_by_user_id"] == ids["Admin"]
    data = registered_names.read_accounts(path)
    data["users"]["alice"]["disabled"] = True
    registered_names.write_accounts(path,data)
    with pytest.raises(ValueError,match="registered user"):
        web_server.record_live_hand({"game_id":game["id"],"winner_user_id":ids["Alice"],"win_points":1000},"Admin")


def test_ambiguous_existing_names_are_not_guessed_during_live_migration(directory):
    path, _ = directory
    people(path)
    data = registered_names.read_accounts(path)
    data["users"]["second-legacy-key"] = {"name":"Alice","account_id":"separate-identity","role":"user"}
    path.write_text(json.dumps(data),encoding="utf-8")
    seed_legacy(web_server.LIVE_DB_FILE)
    game = web_server.active_live_games()[0]
    assert game["player1"] == "Alice" and game["player1_user_id"] is None


def test_live_hand_and_rename_serialize_by_account_identity(directory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path, _ = directory
    ids = people(path)
    game = web_server.create_live_game({f"player{i}":name for i,name in enumerate(("Alice","Bob","Carol","Dan"),1)},"Admin")
    barrier = Barrier(2)
    def rename():
        barrier.wait()
        return web_server.admin_registered_name({"user_id":ids["Alice"],"new_name":"Alice New","expected_name":"Alice","confirm":True},"Admin")
    def hand():
        barrier.wait()
        return web_server.record_live_hand({"game_id":game["id"],"winner_user_id":ids["Alice"],"deal_in_user_id":ids["Bob"],"win_points":1000},"Admin")
    with ThreadPoolExecutor(max_workers=2) as executor:
        changed, scored = executor.submit(rename), executor.submit(hand)
        assert changed.result(timeout=10)["ok"]
        assert scored.result(timeout=10)["id"] == game["id"]
    current = web_server.active_live_games()[0]
    assert current["player1"] == "Alice New" and current["score1"] == 26000
    with closing(web_server.live_db()) as db:
        assert db.execute("SELECT count(*) FROM live_hands").fetchone()[0] == 1
        assert db.execute("SELECT winner_user_id FROM live_hands").fetchone()[0] == ids["Alice"]


def test_legacy_unregistered_roster_remains_playable_without_creating_identity(directory):
    path, _ = directory
    ids = people(path)
    seed_legacy(web_server.LIVE_DB_FILE)
    before = registered_names.read_accounts(path)
    game = web_server.active_live_games()[0]
    old_ids = [game[f"player{i}_user_id"] for i in range(1,5)]
    updated = web_server.record_live_hand({"game_id":17,"winner":"Unknown Legacy","deal_in_user_id":ids["Bob"],"win_points":1000},"Admin")
    assert updated["score3"] == 26000 and updated["score2"] == 24000
    assert [updated[f"player{i}_user_id"] for i in range(1,5)] == old_ids
    with closing(web_server.live_db()) as db:
        hand = dict(db.execute("SELECT * FROM live_hands ORDER BY id DESC LIMIT 1").fetchone())
    assert hand["winner"] == "Unknown Legacy" and hand["winner_user_id"] is None
    assert hand["deal_in_user_id"] == ids["Bob"]
    assert set(registered_names.read_accounts(path)["users"]) == set(before["users"])
    with pytest.raises(ValueError):
        web_server.record_live_hand({"game_id":17,"winner":"Unknown Legacy","winner_user_id":"forged-identity","win_points":1000},"Admin")
    with pytest.raises(ValueError):
        web_server.record_live_hand({"game_id":17,"winner":"unknown legacy","win_points":1000},"Admin")
