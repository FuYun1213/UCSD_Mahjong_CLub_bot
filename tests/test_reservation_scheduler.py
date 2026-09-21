"""The reminder scheduler runs without a browser and does not block API startup."""
import logging
import threading
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from mahjong_api.config import Settings
from mahjong_api.models import User
from test_mahjong_api import FakeSheets
import mahjong_api.main as main_module


def test_scheduler_is_independent_of_browser_and_reservation_request(tmp_path,monkeypatch):
    entered,release=threading.Event(),threading.Event()
    class SlowReminders:
        def __init__(self,tables):self.tables=tables
        def tick(self,limit=10):
            entered.set()
            assert release.wait(6)
    monkeypatch.setattr(main_module,"DiscordReminderService",SlowReminders)
    app=main_module.create_app(Settings(database_path=tmp_path/"scores.sqlite3",mock_auth_enabled=True),FakeSheets())
    with TestClient(app) as client:
        assert entered.wait(3)  # No browser or API request starts the scheduler.
        app.state.tables.account_lookup=lambda ids=None:[{"id":"u1","name":"Alice","avatar":"","disabled":False}]
        table=app.state.tables.create({"request_id":"scheduler-table","number":1},User(id="admin",name="Admin",role="admin"))
        try:
            response=client.post("/api/club-tables/"+table["id"]+"/reservations",json={
                "scheduled_at":(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),
                "request_id":"scheduler-reservation"},headers={"Authorization":"Bearer demo-1"})
            assert response.status_code==200,response.text
            assert response.json()["session_id"] and response.json()["end_at"]
        finally:
            release.set()


def test_scheduler_failure_isolated_and_exception_secrets_are_not_logged(tmp_path,monkeypatch,caplog):
    called=threading.Event()
    secret="TEST-NOT-A-REAL-DISCORD-OR-OAUTH-TOKEN"
    class BrokenReminders:
        def __init__(self,tables):pass
        def tick(self,limit=10):
            called.set()
            raise RuntimeError(secret)
    monkeypatch.setattr(main_module,"DiscordReminderService",BrokenReminders)
    caplog.set_level(logging.WARNING)
    app=main_module.create_app(Settings(database_path=tmp_path/"scores.sqlite3",mock_auth_enabled=True),FakeSheets())
    with TestClient(app) as client:
        assert called.wait(3)
        response=client.get("/api/statistics",headers={"Authorization":"Bearer demo-1"})
        assert response.status_code==200,response.text
    assert secret not in caplog.text
    assert "Discord reservation scheduler failed; will retry" in caplog.text
