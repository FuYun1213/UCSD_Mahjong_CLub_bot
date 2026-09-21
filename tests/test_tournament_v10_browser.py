"""V10 tournament UI with isolated real accounts, website and score API."""
import json
import os
from pathlib import Path
import subprocess
import pytest
import registered_names
import web_server
from test_web_score_bridge import website


@pytest.mark.skipif(os.getenv("NFC_BROWSER_TESTS") != "1", reason="Set NFC_BROWSER_TESTS=1 to run the real browser")
def test_placement_guest_tournament_browser(website, tmp_path, monkeypatch):
    url, _, _ = website
    monkeypatch.setattr(web_server, "MAHJONG_DB_FILE", tmp_path / "club.sqlite3")
    monkeypatch.setattr(web_server, "LIVE_DB_FILE", tmp_path / "live.sqlite3")
    monkeypatch.setattr(web_server, "record_action", lambda **kw: kw)
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: [])
    accounts = registered_names.read_accounts(web_server.USERS_FILE)
    accounts["users"]["photo1"]["role"] = "admin"
    registered_names.write_accounts(web_server.USERS_FILE, accounts)
    env = {**os.environ, "NFC_TEST_URL": url, "NODE_PATH": str(Path(".venv-api/browser-tests/node_modules").resolve())}
    result = subprocess.run(["node", "tests/browser_tournament_v10.cjs"], env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
