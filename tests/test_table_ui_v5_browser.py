"""Browser coverage uses isolated website accounts and a temporary database."""
import json
import os
from pathlib import Path
import subprocess
import web_server
from test_web_score_bridge import website


def test_browser_table_v5_workflow(website, monkeypatch):
    url, _, _ = website
    accounts = json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"] = "admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts), encoding="utf-8")
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: [])
    monkeypatch.setattr(web_server, "build_dashboard", lambda *a, **kw: {"stats": {"member_count": 8}, "rankings": [], "recent_yakuman": []})
    env = os.environ.copy()
    env["NFC_TEST_URL"] = url
    env["NODE_PATH"] = str(Path(".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_table_v5.cjs"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
