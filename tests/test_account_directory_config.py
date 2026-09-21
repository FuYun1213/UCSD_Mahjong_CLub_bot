"""Import-time account configuration must agree across all application workers."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("configured", [False, True])
def test_workers_share_account_directory_in_fresh_process(tmp_path, configured):
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(root), env.get("PYTHONPATH", "")]))
    env.pop("TABLE_ACCOUNT_FILE", None)
    if configured:
        env["TABLE_ACCOUNT_FILE"] = str(tmp_path / "account_state" / "web_users.json")
    code = r'''
import json
import os
from pathlib import Path
from types import SimpleNamespace
import registered_names
import web_server
from cogs import personaldata
from mahjong_api.table_service import TableService

configured = "TABLE_ACCOUNT_FILE" in os.environ
expected = Path(os.environ["TABLE_ACCOUNT_FILE"]) if configured else web_server.ROOT / "web_users.json"
assert web_server.USERS_FILE == personaldata.USERS_FILE == expected
service = TableService(SimpleNamespace(store=None), SimpleNamespace())
if not configured:
    # Check the API default without reading or migrating workspace accounts.
    paths = []
    registered_names.account_rows = lambda path, ids=None: paths.append(path) or []
    assert service._account_rows() == []
    assert paths == [expected]
else:
    from fastapi.testclient import TestClient
    from mahjong_api.config import Settings
    from mahjong_api.main import create_app
    from mahjong_api.sheets import DisabledSheets
    expected.parent.mkdir()
    expected.write_text(json.dumps({"users": {"directory test": {
        "name": "Directory Test", "account_id": "directory-id", "role": "user",
        "salt": "test-salt", "password_hash": "test-hash"}}}), encoding="utf-8")
    personaldata.bind_registered_discord("Directory Test", "123456789012345678", "Test Discord")
    assert web_server.users_data()["users"]["directory test"]["discord_id"] == "123456789012345678"
    app = create_app(Settings(database_path=Path.cwd() / "api.sqlite3",
        club_database_path=str(Path.cwd() / "club.sqlite3"), sync_interval_seconds=3600), DisabledSheets())
    with TestClient(app):
        assert app.state.service.sheets.account_path == expected
        profiles = app.state.tables._account_rows()
        assert [(p["id"], p["name"]) for p in profiles] == [("directory-id", "Directory Test")]
    assert registered_names.database_path(expected).parent == expected.parent
    assert registered_names.database_path(expected).is_file()
    assert Path(str(expected.resolve()) + ".lock").is_file()
    assert registered_names._pending_file(expected).parent == expected.parent
    assert not registered_names._pending_file(expected).exists()
print("account_directory_configuration_verified")
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "account_directory_configuration_verified" in result.stdout
