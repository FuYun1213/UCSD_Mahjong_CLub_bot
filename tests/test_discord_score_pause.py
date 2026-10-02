"""The admin setting blocks only the Discord score-entry command."""
import asyncio
from contextlib import closing
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import requests

import mahjong_store
import web_server as web
from cogs import recordgame
from test_registered_names import account, directory


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.deferred = False

    async def send_message(self, content, **kwargs):
        self.messages.append((content, kwargs))

    async def defer(self):
        self.deferred = True


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content, **kwargs):
        self.messages.append(content)


def run_record_game():
    interaction = SimpleNamespace(response=FakeResponse(), followup=FakeFollowup())
    cog = recordgame.RecordGame.__new__(recordgame.RecordGame)
    asyncio.run(recordgame.RecordGame.record_game.callback(
        cog, interaction, "Same", 40000, "Same", 30000,
        "Third", 20000, "Fourth", 10000,
    ))
    return interaction


def test_discord_command_blocks_before_any_writes_and_resumes(directory, monkeypatch):
    _, db = directory
    monkeypatch.setattr(recordgame, "MAHJONG_DB_FILE", db)
    monkeypatch.setattr(recordgame, "get_sheet", lambda: (_ for _ in ()).throw(AssertionError("sheet accessed")))
    with closing(mahjong_store.connect(db)) as connection:
        assert mahjong_store.discord_score_paused(connection) is False
        mahjong_store.set_discord_score_paused(connection, True)
    paused = run_record_game()
    assert paused.response.messages == []
    assert paused.response.deferred is True
    assert paused.followup.messages == [recordgame.DISCORD_SCORE_PAUSED_MESSAGE]
    with closing(mahjong_store.connect(db)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
        mahjong_store.set_discord_score_paused(connection, False)
    resumed = run_record_game()
    assert resumed.response.deferred is True
    assert resumed.response.messages == []
    assert resumed.followup.messages == ["Name duplicated. Please check the four players."]


def test_discord_command_fails_closed_when_setting_cannot_be_read(directory, monkeypatch):
    _, db = directory
    monkeypatch.setattr(recordgame, "MAHJONG_DB_FILE", db)
    def broken_connect(_):
        raise OSError("synthetic database outage")
    monkeypatch.setattr(recordgame.mahjong_store, "connect", broken_connect)
    interaction = run_record_game()
    assert interaction.response.messages == []
    assert interaction.response.deferred is True
    assert interaction.followup.messages == [recordgame.DISCORD_SCORE_PAUSED_MESSAGE]


def test_admin_http_toggle_is_authenticated_validated_and_persistent(directory, monkeypatch):
    monkeypatch.setattr(web, "_rate_limits", {})
    accounts, db = directory
    admin_id = account(accounts, "Score Admin", role="admin")
    member_id = account(accounts, "Score Member")
    admin_token, _ = web.issue_session(SimpleNamespace(headers={}), admin_id)
    member_token, _ = web.issue_session(SimpleNamespace(headers={}), member_id)

    class QuietHandler(web.Handler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = "http://127.0.0.1:%s/api/admin/discord-score" % server.server_port
        anonymous = requests.Session()
        member = requests.Session()
        member.cookies.set("mahjong_session", member_token)
        admin = requests.Session()
        admin.cookies.set("mahjong_session", admin_token)
        assert anonymous.get(url, timeout=10).status_code == 401
        assert anonymous.post(url, json={"paused": True}, timeout=10).status_code == 401
        assert member.get(url, timeout=10).status_code == 403
        assert member.post(url, json={"paused": True}, timeout=10).status_code == 403
        assert admin.get(url, timeout=10).json() == {"ok": True, "paused": False}
        assert admin.post(url, json={"paused": "true"}, timeout=10).status_code == 400
        response = admin.post(url, json={"paused": True}, timeout=10)
        assert response.status_code == 200 and response.json() == {"ok": True, "paused": True}
        with closing(mahjong_store.connect(db)) as connection:
            assert mahjong_store.discord_score_paused(connection) is True
        assert admin.get(url, timeout=10).json()["paused"] is True
        assert admin.post(url, json={"paused": False}, timeout=10).json()["paused"] is False
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
