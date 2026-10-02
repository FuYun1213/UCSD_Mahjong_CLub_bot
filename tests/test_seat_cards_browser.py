"""Real seat-card interactions against isolated website accounts and databases."""
import json
import os
from pathlib import Path
import subprocess

import web_server
from test_web_score_bridge import website


def test_seat_cards_self_join_move_auth_errors_and_keyboard(website, monkeypatch):
    url, app, _ = website
    accounts = json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"] = "admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts), encoding="utf-8")
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: [])
    monkeypatch.setattr(web_server, "build_dashboard", lambda *a, **kw: {"stats": {"member_count": 8}, "rankings": [], "recent_yakuman": []})
    environment = os.environ.copy()
    environment["NFC_TEST_URL"] = url
    environment["NODE_PATH"] = str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_seat_cards.cjs"], env=environment, capture_output=True,
                            text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    from sqlalchemy import select
    from mahjong_api.table_models import ActiveTableMember
    with app.state.service.store.connect() as db:
        members = list(db.scalars(select(ActiveTableMember)))
        assert len(members) == len({member.user_id for member in members}) == 3
    print(result.stdout)
