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
        self.saved_user = None

    def write_current(self, table):
        if self.unavailable:
            raise ConnectionError("temporary outage")
        self.saved_user = table["seats"]["east"]["id"]

    def write_history(self, match):
        raise AssertionError("No match should be submitted in this test")


def test_periodic_worker_retries_without_another_request(tmp_path):
    settings = Settings(database_path=tmp_path / "worker.sqlite3", mock_auth_enabled=True, sync_interval_seconds=0.02)
    sheets = RecoveringSheets()
    app = create_app(settings, sheets)
    with TestClient(app) as client:
        ensure_table(client,1)
        response = client.get("/api/sit?table=1&seat=east", headers={"Authorization": "Bearer demo-1"})
        assert response.status_code == 202
        sheets.unavailable = False
        deadline = time.monotonic() + 3
        while sheets.saved_user is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sheets.saved_user == "u1"


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
