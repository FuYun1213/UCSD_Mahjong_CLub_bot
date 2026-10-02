from test_mahjong_api import ensure_table
import time

from fastapi.testclient import TestClient

from mahjong_api.config import Settings
from mahjong_api.main import create_app
from mahjong_api.models import User


class RecoveringSheets:
    enabled = True

    def __init__(self):
        self.unavailable = True
        self.history = {}
        self.attempts = 0
        self.current_calls = 0

    def write_current(self, table):
        self.current_calls += 1
        raise AssertionError("Seat projection must never be sent")

    def write_history(self, match):
        self.attempts += 1
        if self.unavailable:
            raise ConnectionError("temporary history outage")
        self.history[match["match_id"]] = match

    def reconcile_history(self, match):
        saved = self.history.get(match["match_id"])
        return "absent" if saved is None else "matched" if saved["result"] == match["result"] else "conflict"


def test_periodic_worker_retries_without_another_request(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from mahjong_api.history_delivery_models import ScoreDelivery
    for key in ("NARTS_EXTERNAL_API_KEY", "NARTS_EXTERNAL_API_KEY_FILE", "NARTS_EXTERNAL_API_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TABLE_ACCOUNT_FILE", str(tmp_path / "accounts.json"))
    settings = Settings(database_path=tmp_path / "worker.sqlite3", mock_auth_enabled=True, sync_interval_seconds=0.05)
    sheets = RecoveringSheets()
    app = create_app(settings, sheets)
    with TestClient(app) as client:
        ensure_table(client, 1)
        for number, wind in enumerate(("east", "south", "west", "north"), 1):
            response = client.post("/api/sit?table=1&seat=" + wind,
                                  headers={"Authorization": "Bearer demo-" + str(number)})
            assert response.status_code == 200
            assert response.json()["sync_status"] == "not_required"
        match_id = response.json()["match_id"]
        assert sheets.current_calls == 0
        saved = client.post("/api/submit_scores", headers={"Authorization": "Bearer demo-1"},
            json={"table": "1", "match_id": match_id,
                  "scores": {"bottom": "35000", "right": "20000", "top": "15000", "left": "30000"}})
        assert saved.status_code == 202
        assert saved.json()["local_saved"] and saved.json()["local_completed"]
        deadline = time.monotonic() + 3
        while app.state.service.history.status(match_id)["status"] != "delivery_unknown" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert app.state.service.history.status(match_id)["status"] == "delivery_unknown"
        assert sheets.attempts == 1 and not sheets.history
        sheets.unavailable = False
        # Simulate elapsed persisted backoff; only the real periodic worker sends.
        with app.state.service.store.connect() as db:
            row = db.scalar(select(ScoreDelivery).where(ScoreDelivery.game_id == match_id))
            row.next_attempt_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        deadline = time.monotonic() + 3
        while app.state.service.history.status(match_id)["status"] != "synced" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert app.state.service.history.status(match_id)["status"] == "synced"
        assert sheets.attempts == 2 and sheets.current_calls == 0
        snapshot = sheets.history[match_id]["result"]
        assert snapshot == app.state.service.store.match(match_id)["result"]
        assert snapshot == {key: saved.json()["result"][key] for key in snapshot}
        assert {wind: player["final_points"] for wind, player in snapshot["players"].items()} == {
            "east": 35000, "south": 20000, "west": 15000, "north": 30000}
        state = app.state.service.table("1")
        assert state["round"] == 2 and state["match_id"] != match_id and not any(state["seats"].values())


def test_real_auth_dependency_can_replace_mock(tmp_path):
    from mahjong_api.auth import get_current_user
    from mahjong_api.sheets import DisabledSheets

    settings = Settings(database_path=tmp_path / "auth.sqlite3")
    app = create_app(settings, DisabledSheets())
    app.dependency_overrides[get_current_user] = lambda: User(id="existing-account-id", name="网站玩家")
    with TestClient(app) as client:
        ensure_table(client,1)
        response = client.post("/api/sit?table=1&seat=east")
        assert response.status_code == 200
        assert response.json()["user"] == "网站玩家"
        assert app.state.service.table("1")["seats"]["east"] == "existing-account-id"


def test_missing_machine_key_is_explicitly_unconfigured(tmp_path):
    from mahjong_api.sheets import DisabledSheets

    settings = Settings(database_path=tmp_path / "key.sqlite3")
    with TestClient(create_app(settings, DisabledSheets())) as client:
        assert client.post("/api/sync").status_code == 503
