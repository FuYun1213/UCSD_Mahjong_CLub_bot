"""Exercise the rendered account forms against temporary identity/history stores."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess

import mahjong_store
import registered_names
import web_server
from test_web_score_bridge import website


def test_registered_name_admin_and_app_forms(website, tmp_path, monkeypatch):
    url, _, _ = website
    accounts = json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"] = "super_admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts), encoding="utf-8")
    history = tmp_path / "club-history.sqlite3"
    monkeypatch.setattr(web_server, "MAHJONG_DB_FILE", history)
    monkeypatch.setenv("MAHJONG_DB_FILE", str(history))
    monkeypatch.setattr(web_server, "LIVE_DB_FILE", str(tmp_path / "live.sqlite3"))
    actions = []
    monkeypatch.setattr(web_server, "record_action", lambda **action: actions.append(action))
    monkeypatch.setattr(web_server, "admin_recent_actions", lambda *a, **kw: {"ok": True, "actions": []})
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: [f"photo{i}" for i in range(1, 9)])
    monkeypatch.setattr(web_server, "build_dashboard", lambda *a, **kw: {"stats": {"member_count": 8}, "rankings": [], "recent_yakuman": []})
    with mahjong_store.connect(history) as db:
        original = mahjong_store.upsert_player(db, "photo2")
        original_id = original["id"]
    env = os.environ.copy()
    env["NFC_TEST_URL"] = url
    env["NODE_PATH"] = str(Path(".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_registered_admin.cjs"], env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    with mahjong_store.connect(history) as db:
        player = db.execute("SELECT id,name FROM players WHERE id=?", (original_id,)).fetchone()
        assert player["name"] == "Renamed Photo Two"
    renamed = json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))["users"]["renamed photo two"]
    assert renamed["account_id"] == "photo-user-2"
    with sqlite3.connect(registered_names.database_path(web_server.USERS_FILE)) as db:
        audit = db.execute("SELECT account_id,old_name,new_name,admin_id,reason FROM registered_name_audit").fetchall()
    assert audit == [("photo-user-2", "photo2", "Renamed Photo Two", "photo-user-1", "Correcting registered spelling")]
    assert len([action for action in actions if action["action_type"] == "rename_registered_name"]) == 1
    print(result.stdout)
