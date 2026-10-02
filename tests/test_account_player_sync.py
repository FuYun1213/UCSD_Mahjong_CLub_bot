"""Regression tests for website/Discord registrations, using isolated files only."""
import ast
import asyncio
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import mahjong_store
import player_directory
import web_server
from cogs import personaldata, recordgame


@pytest.fixture
def directory(tmp_path, monkeypatch):
    path = tmp_path / "players.sqlite3"
    monkeypatch.setenv("MAHJONG_DB_FILE", str(path))
    monkeypatch.setattr(web_server, "MAHJONG_DB_FILE", path)
    monkeypatch.setattr(web_server, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(recordgame, "MAHJONG_DB_FILE", path)
    monkeypatch.setattr(recordgame, "get_sheet", Mock(side_effect=AssertionError("No Sheets calls in autocomplete")))
    monkeypatch.setattr(personaldata, "USERS_FILE", tmp_path / "users.json")
    with closing(mahjong_store.connect(path)) as db:
        mahjong_store.upsert_player(db, "Existing Player")
    return path


def choices(module, query):
    return [x.value for x in asyncio.run(module.player_name_autocomplete(None, query))]


def test_website_registration_appears_in_warm_discord_lists(directory):
    for module in (recordgame, personaldata):
        assert choices(module, "Player") == ["Existing Player"]
    web_server.register_user({"username": "New Player", "password": "test-password"})
    for module in (recordgame, personaldata):
        assert "New Player" in choices(module, "Player")
    token, name = web_server.login_user({"username": "new player", "password": "test-password"})
    assert token and name == "New Player"


@pytest.mark.parametrize("scope", [None, "Total games", "2026 Fall"])
def test_registered_zero_game_profile(directory, scope):
    with closing(mahjong_store.connect(directory)) as db:
        mahjong_store.upsert_player(db, "轻松放铳")
    data, error = personaldata.get_personal_detailed_data("轻松放铳", scope)
    assert error is None
    assert data["games_played"] == 0
    assert data["personal_data"]["selected_game_count"] == 0
    assert data["personal_data"]["history"] == []
    assert data["personal_data"]["mmr_value"] == 1500
    assert personaldata.render_personal_data_image(data).read(8) == b"\x89PNG\r\n\x1a\n"


def test_unknown_player_is_still_not_found(directory):
    data, error = personaldata.get_personal_detailed_data("Unknown Player")
    assert data is None and "not found" in error


def test_lookup_is_fresh_after_other_process_write_and_uses_configured_path(directory, tmp_path, monkeypatch):
    assert choices(recordgame, "Existing") == ["Existing Player"]
    monkeypatch.chdir(tmp_path)
    with closing(mahjong_store.connect(directory)) as db:
        mahjong_store.upsert_player(db, "Existing Newcomer")
    assert set(choices(recordgame, "existing")) == {"Existing Player", "Existing Newcomer"}
    assert "Existing Newcomer" in choices(personaldata, "  EXISTING   newcomer ")


def test_exact_match_survives_discord_25_result_limit():
    names = [f"Player {i}" for i in range(40)] + ["Player"]
    result = player_directory.matching_names(names, "PLAYER")
    assert len(result) == 25 and result[0] == "Player"


def registration_helper(gc):
    # Import the actual synchronous helper without connecting or starting the bot.
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "perform_google_sheet_registration")
    namespace = {"gc": gc, "SHEET_ID": "test", "mahjong_store": mahjong_store}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"), namespace)
    return namespace[function.name]


def test_discord_registration_commits_shared_player(directory):
    sheet = Mock()
    worksheet = sheet.open_by_key.return_value.worksheet.return_value
    worksheet.col_values.return_value = ["Name", "Existing Player"]
    result = registration_helper(sheet)("Discord Newcomer")
    assert result["sql_player_id"]
    assert "Discord Newcomer" in choices(recordgame, "newcomer")
    assert "Discord Newcomer" in choices(personaldata, "newcomer")
    assert personaldata.get_personal_detailed_data("Discord Newcomer")[0]


def test_discord_sql_failure_never_reports_registration_success(directory, monkeypatch):
    sheet = Mock()
    sheet.open_by_key.return_value.worksheet.return_value.col_values.return_value = ["Name"]
    monkeypatch.setattr(mahjong_store, "connect", Mock(side_effect=OSError("database unavailable")))
    result = registration_helper(sheet)("Failed Player")
    assert isinstance(result, str) and "成功" not in result


def test_discord_only_id_gets_password_setup_guidance_then_same_profile(directory):
    with pytest.raises(web_server.WebsiteRegistrationRequired) as error:
        web_server.login_user({"username": "Existing Player", "password": "unused"})
    assert error.value.code == "website_registration_required"
    with closing(mahjong_store.connect(directory)) as db:
        before = dict(db.execute("select * from players where name_key = ?", ("existing player",)).fetchone())
    import account_registration
    with pytest.raises(ValueError, match="Claim Existing ID"):
        web_server.register_user({"username": "existing player", "password": "new-password"})
    from test_registered_names import account
    account(web_server.USERS_FILE, "ReviewAdmin", role="admin")
    account_registration.submit_claim(web_server, {"player_id":"club-"+str(before["id"]),"password":"new-password","confirm_password":"new-password"})
    account_registration.review(web_server, {"claim_id":account_registration.claims(web_server)[0]["id"],"decision":"approve"}, "ReviewAdmin")
    _, name = web_server.login_user({"username": "Existing Player", "password": "new-password"})
    assert name == "Existing Player"
    with closing(mahjong_store.connect(directory)) as db:
        after = dict(db.execute("select * from players where name_key = ?", ("existing player",)).fetchone())
    assert before == after
    with pytest.raises(ValueError, match="Incorrect username or password"):
        web_server.login_user({"username": "Existing Player", "password": "wrong-password"})


from test_web_score_bridge import website


def test_browser_discord_id_first_website_login(website, directory, tmp_path, monkeypatch):
    monkeypatch.setattr(web_server,"LIVE_DB_FILE",tmp_path/"live.sqlite3")
    import os
    import subprocess
    url, app, _ = website
    import registered_names
    accounts = registered_names.read_accounts(web_server.USERS_FILE)
    salt, digest = web_server.password_hash("test-password")
    accounts["users"]["reviewadmin"] = {"name":"ReviewAdmin","salt":salt,"password_hash":digest,"role":"admin","account_id":"review-admin"}
    registered_names.write_accounts(web_server.USERS_FILE,accounts)
    environment = os.environ.copy()
    environment["NFC_TEST_URL"] = url
    environment["NODE_PATH"] = str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_account_sync.cjs"], env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
