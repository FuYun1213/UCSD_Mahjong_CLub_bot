"""Regressions for the existing bot-command binding and single avatar field."""
import asyncio
import base64
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
import registered_names as names
import web_server
from cogs import personaldata
from mahjong_api.registered_display import with_registered_names
from test_registered_names import directory, account

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aY1sAAAAASUVORK5CYII="
DISCORD_PNG = "data:image/png;base64,ZGlzY29yZC1jYWNoZWQtdGVzdC1pbWFnZQ=="
FIRST = "123456789012345678"
SECOND = "234567890123456789"


@pytest.fixture
def bound_directory(directory, monkeypatch):
    path, _ = directory
    monkeypatch.setattr(personaldata, "USERS_FILE", path)
    return directory


def test_existing_upload_has_priority_binding_and_unbinding_preserve_identity(bound_directory):
    path, _ = bound_directory
    uid = account(path, "Alice", avatar=PNG)
    before = names.read_accounts(path)["users"]["alice"].copy()
    assert personaldata.bind_registered_discord("Alice", FIRST, "nickname", DISCORD_PNG) == "Alice"
    current = names.read_accounts(path)["users"]["alice"]
    assert current["account_id"] == uid and current["avatar"] == PNG
    assert current["password_hash"] == before["password_hash"]
    assert current["discord_id"] == FIRST
    personaldata.unbind_registered_discord(FIRST)
    current = names.read_accounts(path)["users"]["alice"]
    assert current["account_id"] == uid and current["avatar"] == PNG
    assert "discord_id" not in current and "discord_name" not in current


def test_empty_avatar_uses_cached_discord_image_and_keeps_existing_unbind_behavior(bound_directory):
    path, _ = bound_directory
    account(path,"Alice")
    personaldata.bind_registered_discord("Alice",FIRST,"nickname",DISCORD_PNG)
    assert web_server.avatar_for_name("Alice") == DISCORD_PNG
    personaldata.unbind_registered_discord(FIRST)
    assert web_server.avatar_for_name("Alice") == ""
    # New Discord fallback is separate so unlinking removes it.
    assert web_server.current_user_profile_from_name("Alice")["discord_id"] == ""


def test_upload_after_binding_takes_priority_without_removing_binding(bound_directory):
    path,_ = bound_directory
    account(path,"Alice")
    personaldata.bind_registered_discord("Alice",FIRST,"nickname",DISCORD_PNG)
    web_server.update_user_avatar("Alice",PNG)
    personaldata.bind_registered_discord("Alice",FIRST,"renamed Discord",DISCORD_PNG)
    profile=web_server.current_user_profile_from_name("Alice")
    assert profile["avatar"] == PNG and profile["discord_id"] == FIRST
    assert profile["discord_name"] == "renamed Discord"


def test_rebinding_and_website_unbind_keep_account_and_avatar(bound_directory):
    path,_=bound_directory
    uid=account(path,"Alice",avatar=PNG)
    personaldata.bind_registered_discord("Alice",FIRST,"first")
    personaldata.bind_registered_discord("Alice",SECOND,"second")
    assert personaldata.bound_name_for_discord(FIRST) == ""
    assert personaldata.bound_name_for_discord(SECOND) == "Alice"
    profile=web_server.unbind_discord_account("Alice")
    assert profile["id"] == uid and profile["avatar"] == PNG
    assert profile["discord_id"] == ""


def test_registered_rename_does_not_change_bound_identity_or_avatar(bound_directory):
    path,_=bound_directory
    uid=account(path,"Alice",avatar=PNG)
    account(path,"Admin",role="admin")
    personaldata.bind_registered_discord("Alice",FIRST,"nickname")
    web_server.admin_registered_name({"user_id":uid,"expected_name":"Alice","new_name":"Alice New","confirm":True},"Admin")
    profile=web_server.current_user_profile_from_name("Alice New")
    assert (profile["id"],profile["discord_id"],profile["avatar"]) == (uid,FIRST,PNG)
    assert personaldata.bound_name_for_discord(FIRST) == "Alice New"


def test_transfer_existing_discord_binding_preserves_both_account_avatars(bound_directory):
    path,_=bound_directory
    alice=account(path,"Alice",avatar=PNG)
    bob=account(path,"Bob",avatar=DISCORD_PNG)
    personaldata.bind_registered_discord("Alice",FIRST,"nickname")
    with pytest.raises(ValueError, match="already bound"):
        personaldata.bind_registered_discord("Bob",FIRST,"nickname")
    rows=names.read_accounts(path)["users"]
    assert rows["alice"]["discord_id"] == FIRST and "discord_id" not in rows["bob"]
    assert rows["alice"]["account_id"] == alice and rows["bob"]["account_id"] == bob
    assert rows["alice"]["avatar"] == PNG and rows["bob"]["avatar"] == DISCORD_PNG



@pytest.mark.parametrize("failed",[False,True])
def test_actual_bind_command_callback_survives_discord_avatar_failure(bound_directory,failed):
    path,_=bound_directory
    uid=account(path,"Alice")
    read=AsyncMock(side_effect=OSError("avatar unavailable") if failed else None,return_value=b"png bytes")
    image=SimpleNamespace(read=read)
    user=SimpleNamespace(id=FIRST,display_avatar=SimpleNamespace(with_size=Mock(return_value=image)))
    interaction=SimpleNamespace(user=user,response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
    asyncio.run(personaldata.PersonalData.bind_web_account.callback(None,interaction,"Alice"))
    row=names.read_accounts(path)["users"]["alice"]
    assert row["account_id"] == uid and row["discord_id"] == FIRST
    assert bool(row.get("discord_avatar")) is not failed
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.call_args.kwargs["ephemeral"]
    asyncio.run(personaldata.PersonalData.unbind_web_account.callback(None,interaction))
    assert "discord_id" not in names.read_accounts(path)["users"]["alice"]


def test_avatar_name_projection_is_read_only_and_does_not_expose_binding():
    profiles=[{"id":"stable-alice","name":"Alice","avatar":PNG,"discord_id":FIRST,"access_token":"private"}]
    payload={"players":{"east":{"id":"stable-alice","name":"old"}},"participants":[{"user_id":"stable-alice","name":"old"}],"public":{"east":{"occupied":True}}}
    original=deepcopy(payload)
    projected=with_registered_names(payload,profiles)
    assert projected["players"]["east"]["avatar"] == PNG
    assert projected["participants"][0]["avatar"] == PNG
    assert projected["public"] == {"east":{"occupied":True}}
    assert payload == original
    assert "discord_id" not in str(projected) and "private" not in str(projected)
    projected=with_registered_names(projected,[{"id":"stable-alice","name":"Alice","avatar":""}])
    assert projected["players"]["east"]["avatar"] == ""


def test_unchanged_default_avatar_is_empty_and_search_keeps_uploaded_avatar(bound_directory):
    path,_=bound_directory
    uid=account(path,"Alice",avatar=PNG)
    account(path,"Bob")
    assert web_server.avatar_for_name("Bob") == ""
    row=next(row for row in names.account_rows(path) if row["id"] == uid)
    assert row["avatar"] == PNG and "discord_id" not in row
