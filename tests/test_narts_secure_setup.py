import json
from pathlib import Path
import pytest
from sqlalchemy import select
from mahjong_api.external_sync import ExternalSync, headers, server_key
from mahjong_api.store import Store
from mahjong_api.tournament_models import TournamentAudit
from scripts.configure_narts_server import configure


def test_private_key_rotation_and_no_secret_in_config(tmp_path, monkeypatch):
    key_path = tmp_path / "key"
    monkeypatch.setenv("NARTS_EXTERNAL_API_KEY_FILE", str(key_path))
    monkeypatch.setenv("NARTS_EXTERNAL_API_KEY", "legacy-environment-value")
    assert server_key("narts") == "legacy-environment-value"
    key_path.write_text("narts-test-private-secret-one")
    assert headers("narts")["Authorization"] == "Bearer narts-test-private-secret-one"
    store = Store(tmp_path / "config.sqlite3")
    try:
        assert ExternalSync(store).config()["key_configured"] is True
        assert "secret-one" not in json.dumps(ExternalSync(store).config())
        key_path.write_text("narts-test-private-secret-two")
        assert server_key("narts") == "narts-test-private-secret-two"
    finally:
        store.close()


def test_secure_setup_saves_key_and_config_with_safe_audit(tmp_path, monkeypatch):
    key = "narts-test-secret-abcdefghijklmnop"
    monkeypatch.setenv("NARTS_EXTERNAL_API_KEY_FILE", str(tmp_path / "private-key"))
    monkeypatch.setenv("NFC_DATABASE_PATH", str(tmp_path / "matches.sqlite3"))
    monkeypatch.delenv("NFC_DATABASE_URL", raising=False)
    monkeypatch.setattr(ExternalSync, "request", lambda self, *a, **kw: (405, {}))
    result = configure({"key": key, "endpoint": "https://example.com/matches"})
    assert result == {"ok": True, "key_configured": True, "test_code": "reachable_unverified"}
    assert (tmp_path / "private-key").read_text() == key
    assert not list(tmp_path.glob(".narts-*"))
    store = Store(tmp_path / "matches.sqlite3")
    try:
        config = ExternalSync(store).config()
        assert config["enabled"] is True and config["endpoint"] == "https://example.com/matches"
        with store.connect() as db:
            audit = [(x.action, x.detail_json) for x in db.scalars(select(TournamentAudit))]
        assert "api_key_configured" in [x[0] for x in audit]
        assert key not in json.dumps([config, audit, result])
    finally:
        store.close()


@pytest.mark.parametrize("key,endpoint", [("contains spaces", "https://example.com"), ("narts-abcdefghijklmnopqrst", "http://example.com")])
def test_secure_setup_rejects_bad_input_without_overwriting_key(tmp_path, monkeypatch, key, endpoint):
    target = tmp_path / "key"
    target.write_text("existing-key")
    monkeypatch.setenv("NARTS_EXTERNAL_API_KEY_FILE", str(target))
    with pytest.raises(Exception):
        configure({"key": key, "endpoint": endpoint})
    assert target.read_text() == "existing-key"

from contextlib import contextmanager
from fastapi.testclient import TestClient
from mahjong_api.auth import get_current_user
from mahjong_api.config import Settings
from mahjong_api.main import create_app
from mahjong_api.models import User
from mahjong_api.sheets import DisabledSheets
from mahjong_api.database_models import Metadata
from mahjong_api.store import Conflict
import mahjong_api.external_sync as sync_module


@pytest.fixture
def setup_client(tmp_path, monkeypatch):
    monkeypatch.delenv("NARTS_EXTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("NARTS_EXTERNAL_API_ENDPOINT", raising=False)
    monkeypatch.setenv("NARTS_EXTERNAL_API_KEY_FILE", str(tmp_path / "private-key"))
    app = create_app(Settings(database_path=tmp_path / "api.sqlite3"), DisabledSheets())
    app.dependency_overrides[get_current_user] = lambda: User(id="web-admin", name="Admin", role="admin")
    with TestClient(app) as client:
        yield client, app, tmp_path / "private-key"


def key_config(**extra):
    return {"endpoint": "https://example.com/matches", "adapter": "narts", "enabled": True,
            "api_key": "narts-isolated-web-test-abcdefghijklmnop", **extra}


def test_web_key_saved_verified_and_preserved_when_blank(setup_client):
    client, app, target = setup_client
    payload = key_config()
    response = client.post("/api/external-config", json=payload)
    assert response.status_code == 200
    assert response.json()["key_configured"] and response.json()["enabled"]
    assert response.json()["saved_at"]
    assert payload["api_key"] not in response.text
    assert target.read_text() == payload["api_key"]
    response = client.post("/api/external-config", json=key_config(api_key=""))
    assert response.status_code == 200 and target.read_text() == payload["api_key"]
    current = client.get("/api/external-config").json()
    assert current["enabled"] and current["key_configured"]
    reopened = Store(app.state.settings.database_path)
    try:
        assert ExternalSync(reopened).config() == current
        with reopened.connect() as db:
            rows = [x.detail_json for x in db.scalars(select(TournamentAudit))]
            config = db.get(Metadata, "external_api_v1").value
        assert payload["api_key"] not in json.dumps(rows) + config
    finally:
        reopened.close()


@pytest.mark.parametrize("value,code", [
    ("contains spaces", "api_key_invalid_characters"),
    ("contains\r\nnewline", "api_key_invalid_characters"),
    ("invisible\u200bcharacter", "api_key_invalid_characters"),
    ("delete\x7fcharacter", "api_key_invalid_characters"),
    ("x" * 4097, "api_key_too_long"),
    (123, "invalid_api_key"), (["opaque-secret"], "invalid_api_key"),
])
def test_web_invalid_key_leaves_existing_key_untouched(setup_client, value, code):
    client, _, target = setup_client
    target.write_text("narts-existing-key-abcdefghijklmnop")
    response = client.post("/api/external-config", json=key_config(api_key=value))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert target.read_text() == "narts-existing-key-abcdefghijklmnop"


def test_web_permissions_and_origin_guard_key_write(setup_client):
    client, app, target = setup_client
    app.dependency_overrides[get_current_user] = lambda: User(id="player", name="Player", role="user")
    assert client.post("/api/external-config", json=key_config()).status_code == 403
    app.dependency_overrides.clear()
    assert client.post("/api/external-config", json=key_config()).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: User(id="admin", name="Admin", role="admin")
    assert client.post("/api/external-config", json=key_config(), headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert not target.exists()


def test_web_enable_without_key_is_actionable_not_false_success(setup_client):
    client, _, target = setup_client
    response = client.post("/api/external-config", json=key_config(api_key=""))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "missing_api_key"
    assert not target.exists()


def test_key_write_error_safe_and_previous_key_preserved(setup_client, monkeypatch):
    client, _, target = setup_client
    target.write_text("narts-existing-key-abcdefghijklmnop")
    def fail(*args):
        raise PermissionError("PRIVATE PATH AND SECRET MUST NEVER LEAK")
    monkeypatch.setattr(sync_module, "_replace_private_file", fail)
    response = client.post("/api/external-config", json=key_config())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "key_storage_error"
    assert "PRIVATE" not in response.text
    assert target.read_text() == "narts-existing-key-abcdefghijklmnop"


@pytest.mark.parametrize("existing", [False, True])
def test_database_failure_restores_previous_key(setup_client, monkeypatch, existing):
    client, app, target = setup_client
    if existing:
        target.write_text("narts-existing-key-abcdefghijklmnop")
    @contextmanager
    def fail_commit():
        with real_connect() as db:
            yield db
            raise RuntimeError("SECRET DATABASE DETAILS MUST NEVER LEAK")
    real_connect = app.state.external.store.connect
    monkeypatch.setattr(app.state.external.store, "connect", fail_commit)
    response = client.post("/api/external-config", json=key_config())
    assert response.status_code == 409 and response.json()["detail"]["code"] == "config_save_failed"
    assert "SECRET" not in response.text
    assert target.exists() == existing
    if existing:
        assert target.read_text() == "narts-existing-key-abcdefghijklmnop"
    with real_connect() as db:
        assert db.get(Metadata, "external_api_v1") is None
        assert not list(db.scalars(select(TournamentAudit)))


def test_connection_failure_keeps_saved_key_and_enabled_config(setup_client):
    client, app, target = setup_client
    assert client.post("/api/external-config", json=key_config()).status_code == 200
    calls = []
    def fail(endpoint, adapter, body, method):
        calls.append((body, method))
        return 401, {}
    app.state.external.transport = fail
    response = client.post("/api/external-test")
    assert response.json()["code"] == "external_auth"
    assert calls == [(None, "HEAD")]
    current = client.get("/api/external-config").json()
    assert current["enabled"] and current["key_configured"] and target.exists()
    assert current["last_test"]["code"] == "external_auth"


def test_cli_known_failure_code_never_echoes_input(monkeypatch, capsys):
    from scripts.configure_narts_server import main
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"key": "PRIVATE INVALID SECRET"})))
    assert main() == 1
    output = capsys.readouterr().out
    assert json.loads(output)["code"] == "api_key_invalid_characters"
    assert "PRIVATE" not in output

@pytest.mark.parametrize("key", ["opaque.token_ABC123", "narts_ABC123", "NARTS-CaseSensitive", "short", "x", "narts-"])
def test_provider_opaque_key_has_no_guessed_prefix_or_minimum(setup_client, key):
    client, _, target = setup_client
    response = client.post("/api/external-config", json=key_config(api_key=key))
    assert response.status_code == 200
    assert response.json()["key_configured"] is True
    assert target.read_text() == key


def test_surrounding_whitespace_removed_but_key_case_preserved(setup_client):
    client, _, target = setup_client
    response = client.post("/api/external-config", json=key_config(api_key="  Opaque_Token.AbC-123\r\n"))
    assert response.status_code == 200
    assert target.read_text() == "Opaque_Token.AbC-123"
