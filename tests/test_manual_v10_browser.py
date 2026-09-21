import os
import subprocess
from pathlib import Path
from uuid import uuid4

import registered_names
import web_server
from test_web_score_bridge import website
from test_tournament_v10 import RULES


def test_manual_game_lost_response_then_reload_is_not_duplicated(website):
    url, app, _ = website
    directory = registered_names.read_accounts(web_server.USERS_FILE)
    directory["users"]["photo1"]["role"] = "admin"
    registered_names.write_accounts(web_server.USERS_FILE, directory)
    state = app.state.tournaments.create({"name": "Retry Test", "settings": RULES, "request_id": str(uuid4())}, "photo-user-1")
    env = {**os.environ, "NFC_TEST_URL": url, "V10_TID": state["id"],
           "NODE_PATH": str(Path(".venv-api/browser-tests/node_modules").resolve())}
    result = subprocess.run(["node", "tests/browser_manual_v10.cjs"], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
