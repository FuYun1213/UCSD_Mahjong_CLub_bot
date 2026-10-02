"""Cross-page seat actions and retired entry points use isolated real services."""
import os
from pathlib import Path
import subprocess

import requests
import web_server
from test_web_score_bridge import website


def test_seat_actions_and_retired_public_features(website, monkeypatch):
    url, app, _ = website
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: [])
    monkeypatch.setattr(web_server, "build_dashboard", lambda *a, **kw:
                        {"stats": {"member_count": 8}, "rankings": [], "recent_yakuman": []})
    if os.environ.get("DORA_RELEASE_WEB"):
        monkeypatch.setattr(web_server, "WEB_DIR", Path(os.environ["DORA_RELEASE_WEB"]).resolve())
    for path in ("/api/public-player-history?player_id=club-1", "/api/register/players?q=photo"):
        response = requests.get(url + path, timeout=10)
        assert response.status_code == 410 and response.json()["code"] == "feature_removed"
    for path in ("/api/register/claim", "/api/register/resume"):
        response = requests.post(url + path, json={}, timeout=10)
        assert response.status_code == 410 and response.json()["code"] == "feature_removed"
    response = requests.get(url + "/player-history", allow_redirects=False, timeout=10)
    assert response.status_code == 302 and response.headers["Location"] == "/"
    env = os.environ.copy()
    env["NFC_TEST_URL"] = url
    env["NODE_PATH"] = str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_seat_actions.cjs"], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=210)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
    # Real outsider removals retain the actor and target in the existing audit.
    from sqlalchemy import select
    from mahjong_api.table_models import TableMembershipEvent
    with app.state.service.store.connect() as db:
        events = list(db.scalars(select(TableMembershipEvent).where(TableMembershipEvent.action == "removed")))
        assert len(events) == 2
        assert all(event.actor_id == "photo-user-8" for event in events)
