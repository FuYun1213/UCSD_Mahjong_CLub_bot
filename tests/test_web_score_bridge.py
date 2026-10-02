import json
import os
from pathlib import Path
import socket
import random
import subprocess
import threading
import time

import pytest
import requests
import uvicorn

import web_server
from mahjong_api.config import Settings
from mahjong_api.main import create_app
from test_mahjong_api import FakeSheets


@pytest.fixture
def website(tmp_path, monkeypatch):
    """Real website/session process + real ASGI server, with isolated data only."""
    monkeypatch.setenv("DISCORD_RESERVATION_REMINDERS_ENABLED", "false")
    for key in ("NARTS_EXTERNAL_API_KEY", "NARTS_EXTERNAL_API_KEY_FILE", "NARTS_EXTERNAL_API_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    accounts = {}
    for i in range(1, 9):
        salt, digest = web_server.password_hash("photo-test-password")
        accounts[f"photo{i}"] = {"name": f"photo{i}", "salt": salt, "password_hash": digest,
                                 "account_id": f"photo-user-{i}", "role": "user"}
    accounts_file = tmp_path / "accounts.json"
    accounts_file.write_text(json.dumps({"users": accounts}), encoding="utf-8")
    monkeypatch.setattr(web_server, "USERS_FILE", accounts_file)
    monkeypatch.setattr(web_server, "MAHJONG_DB_FILE", tmp_path / "club.sqlite3")
    monkeypatch.setattr(web_server, "LIVE_DB_FILE", tmp_path / "live.sqlite3")
    monkeypatch.setattr(web_server, "YAKUMAN_UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("NFC_DATABASE_PATH", str(tmp_path / "scores.sqlite3"))
    monkeypatch.setenv("TABLE_ACCOUNT_FILE", str(accounts_file))
    monkeypatch.setattr(web_server, "_sessions", {})
    monkeypatch.setattr(web_server, "_rate_limits", {})
    class QuietHandler(web_server.Handler):
        def log_message(self, *args):
            pass
    # Windows can allocate a Chromium-blocked port such as 6666 for port 0.
    for _ in range(50):
        try:
            web = web_server.WebHTTPServer(("127.0.0.1", random.SystemRandom().randrange(20000, 60000)), QuietHandler)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("No available browser-safe test port")
    url = f"http://127.0.0.1:{web.server_port}"
    web_thread = threading.Thread(target=web.serve_forever, daemon=True)
    web_thread.start()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    api_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    monkeypatch.setenv("NFC_API_URL", api_url)
    settings = Settings(database_path=tmp_path / "scores.sqlite3", mock_auth_enabled=False,
                        auth_profile_url=url + "/api/session", vision_enabled=True, sync_interval_seconds=0.05)
    sink = FakeSheets()
    app = create_app(settings, sink)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    api_thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    api_thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and api_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        from test_mahjong_api import ensure_table
        from types import SimpleNamespace
        for name in ("web","1","photo","A","B","browser-0","browser-1","browser-2","browser-3"):
            ensure_table(SimpleNamespace(app=app),name)
        yield url, app, sink
    finally:
        server.should_exit = True
        api_thread.join(timeout=10)
        web.shutdown()
        web.server_close()
        web_thread.join(timeout=5)
        listener.close()


def login(url, number):
    session = requests.Session()
    response = session.post(url + "/api/login", json={"username": f"photo{number}", "password": "photo-test-password"}, timeout=10)
    assert response.status_code == 200
    assert session.cookies.get("mahjong_session")
    return session


def test_cookie_photo_upload_through_existing_website(website):
    url, app, sink = website
    assert requests.get(url + "/score", timeout=10).status_code == 200
    missing = requests.post(url + "/api/sit?table=web&seat=east", timeout=10)
    assert missing.status_code == 401
    assert "redirect_url" in missing.json()["detail"]
    sessions = []
    for i, seat in enumerate(("east", "south", "west", "north"), 1):
        session = login(url, i)
        sessions.append(session)
        response = session.post(url + f"/api/sit?table=web&seat={seat}", headers={"Origin": url}, timeout=10)
        assert response.status_code == 200, response.text
        match_id = response.json()["match_id"]
    assert sink.current_calls == 0
    history_entered, history_release = threading.Event(), threading.Event()
    original_history = sink.write_history
    def blocked_history(match):
        history_entered.set()
        assert history_release.wait(10), "The HTTP response waited for its history worker"
        original_history(match)
    sink.write_history = blocked_history
    photo = Path(__file__).parent / "fixtures/displays/photo_4.png"
    try:
        response = sessions[1].post(url + "/api/recognize_photo", data={"table": "web", "match_id": match_id},
                                files={"file": ("negative.png", photo.read_bytes(), "image/png")},
                                headers={"Origin": url, "Idempotency-Key": "web-negative"}, timeout=10)
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "pending" and body["local_saved"] and body["local_completed"]
        assert body["result"]["players"]["south"]["final_points"] == 93500
        assert body["result"]["players"]["north"]["final_points"] == -13600
        assert body["normalization"]["multiplier"] == 100
        assert history_entered.wait(2)
        assert len(sink.history) == 0
        current = app.state.service.table("web")
        assert not any(current["seats"].values())
        assert current["match_id"] != match_id and current["round"] == 2
    finally:
        history_release.set()
    deadline = time.monotonic() + 5
    while app.state.service.history.status(match_id)["status"] != "synced" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app.state.service.history.status(match_id)["status"] == "synced"
    assert len(sink.history) == 1 and sink.current_calls == 0
    saved = next(iter(sink.history.values()))
    assert saved["match_id"] == match_id
    assert saved["result"] == app.state.service.store.match(match_id)["result"]
    assert saved["result"] == {key: body["result"][key] for key in saved["result"]}
    assert body["result"]["uploader_name"] == "photo2"
    # Exact-origin checking must survive the proxy, even for a prefix lookalike.
    rejected = sessions[0].post(url + "/api/sit?table=web&seat=east", headers={"Origin": url + ".evil.invalid"}, timeout=10)
    assert rejected.status_code == 403
    assert requests.post(url + "/api/sync", timeout=10).status_code == 404
    for session in sessions:
        session.close()


@pytest.mark.skipif(os.getenv("NFC_BROWSER_TESTS") != "1", reason="Set NFC_BROWSER_TESTS=1 with Playwright installed to run browser tests")
def test_real_browser_photo_flow(website):
    url, _, sink = website
    env = os.environ.copy()
    env["NFC_TEST_URL"] = url
    env["NODE_PATH"] = str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_photo.cjs"], env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(sink.history) == 5
