"""Registered-name controls run against isolated accounts and score databases."""
import json
import os
from pathlib import Path
import subprocess

import web_server
from test_web_score_bridge import website


def test_registered_user_combobox_and_single_seating_entry(website, monkeypatch):
    url, _, _ = website
    accounts = json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"] = "admin"
    for index in range(1, 25):
        accounts["users"][f"guest{index:02}"] = {
            **accounts["users"]["photo2"], "name": f"guest{index:02}",
            "account_id": f"private-account-{index}", "role": "user",
        }
    accounts["users"]["guest-disabled"] = {
        **accounts["users"]["photo2"], "name": "guest-disabled", "account_id": "private-disabled", "disabled": True,
    }
    web_server.USERS_FILE.write_text(json.dumps(accounts), encoding="utf-8")
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: [])
    monkeypatch.setattr(web_server, "build_dashboard", lambda *a, **kw: {"stats": {"member_count": 32}, "rankings": [], "recent_yakuman": []})
    env = os.environ.copy()
    env["NFC_TEST_URL"] = url
    env["NODE_PATH"] = str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_registered_users.cjs"], env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
