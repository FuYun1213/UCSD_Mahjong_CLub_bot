"""Real credential/approval persistence; no production data or outbound calls."""
import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
import web_server as web
import registered_names as names
import account_registration as reg
import account_discord as discord
from account_passwords import verify_password
from test_registered_names import directory, account
import mahjong_store


def form(name="New Member", **extra):
    return {"username":name,"password":"Example!2026","confirm_password":"Example!2026",**extra}


def legacy(web, name="Old Player"):
    with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as db:
        return dict(mahjong_store.upsert_player(db,name))


def test_new_account_generated_identity_argon_default_role_and_login(directory):
    path,_=directory
    reg.create_new(web,form("Jin"))
    row=names.read_accounts(path)["users"]["jin"]
    assert row["password_hash"].startswith("$argon2id$") and row["role"]=="user"
    assert "Example!2026" not in path.read_text()
    assert row["account_id"] and row["club_player_id"]
    assert web.login_user(form(" JIN "))[1]=="Jin"
    assert web.current_user_profile_from_name("Jin")["avatar"]==""


@pytest.mark.parametrize("extra",[{"confirm_password":"bad"},{"password":"x"},{"username":"  "},{"password":None}])
def test_server_validation(directory,extra):
    with pytest.raises(ValueError):reg.create_new(web,form(**extra))


@pytest.mark.parametrize("second",["ALICE"," alice ","Ａｌｉｃｅ"])
def test_unique_names_and_database_constraint(directory,second):
    path,_=directory
    reg.create_new(web,form("Alice"))
    with pytest.raises(ValueError):reg.create_new(web,form(second))
    with sqlite3.connect(names.database_path(path)) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO registered_users(account_id,registered_name,normalized_registered_name,legacy_key,enabled) VALUES('other','alice','alice','other',1)")


def test_existing_id_requires_approval_and_cannot_be_stolen_by_new_registration(directory):
    path,_=directory
    old=legacy(web)
    with pytest.raises(ValueError,match="Claim Existing"):reg.create_new(web,form("Old Player"))
    token=reg.submit_claim(web,form("Old Player",legacy_id=old["id"]))
    assert not names.read_accounts(path)["users"]
    with pytest.raises(ValueError):web.login_user(form("Old Player"))
    assert reg.resume(web,token)==({"status":"pending"},None)
    claim=reg.claims(web)[0]
    with pytest.raises(PermissionError):reg.review(web,{"claim_id":claim["id"],"decision":"approve"},"stranger")
    assert legacy(web)["id"]==old["id"]


def test_approval_keeps_player_aggregates_and_completes_once(directory):
    path,dbpath=directory
    old=legacy(web)
    with sqlite3.connect(dbpath) as db:db.execute("UPDATE players SET games_played=12,total_pt=40 WHERE id=?",(old["id"],))
    account(path,"Admin",role="admin")
    token=reg.submit_claim(web,form("Old Player",legacy_id=old["id"],redirect_url="/?tournament=local",bind_discord=True))
    result=reg.review(web,{"claim_id":reg.claims(web)[0]["id"],"decision":"approve"},"Admin")
    assert result["status"]=="approved"
    with sqlite3.connect(dbpath) as db:
        row=db.execute("SELECT id,name,games_played,total_pt FROM players WHERE id=?",(old["id"],)).fetchone()
    assert row==(old["id"],"Old Player",12,40)
    body,uid=reg.resume(web,token)
    assert body["redirect_url"]=="/?tournament=local" and body["bind_discord"]
    assert reg.resume(web,token)==({"status":"none"},None)
    assert web.login_user(form("Old Player"))[1]=="Old Player"
    assert names.read_accounts(path)["users"]["old player"]["club_player_id"]==old["id"]
    with closing(reg.connect(path)) as db:
        assert db.execute("SELECT password_hash FROM account_claims").fetchone()[0]==""
        assert "Example!2026" not in str(db.execute("SELECT * FROM account_registration_audit").fetchall())


def test_reject_preserves_original_and_already_claimed_does_not_leak(directory):
    path,dbpath=directory;old=legacy(web);account(path,"Admin",role="admin")
    token=reg.submit_claim(web,form("Old Player",legacy_id=old["id"]))
    reg.review(web,{"claim_id":reg.claims(web)[0]["id"],"decision":"reject"},"Admin")
    assert reg.resume(web,token)[0]["status"]=="rejected"
    with sqlite3.connect(dbpath) as db:assert db.execute("SELECT name FROM players WHERE id=?",(old["id"],)).fetchone()[0]=="Old Player"
    account(path,"Private Account",club_player_id=old["id"],discord_id="123456789012345678")
    with pytest.raises(ValueError) as e:reg.submit_claim(web,form("Another",legacy_id=old["id"]))
    assert str(e.value)==reg.ALREADY and "Private" not in str(e.value)


def test_missing_id_and_duplicate_pending_claim(directory):
    with pytest.raises(ValueError,match="not found"):reg.submit_claim(web,form(legacy_id="missing"))
    old=legacy(web);reg.submit_claim(web,form("Old Player",legacy_id=old["id"]))
    with pytest.raises(ValueError):reg.submit_claim(web,form("Second",legacy_id=old["id"]))


def test_legacy_pbkdf2_password_and_session_rotation(directory):
    path,_=directory;salt="legacy"
    digest=hashlib.pbkdf2_hmac("sha256",b"old-password",salt.encode(),120000).hex()
    uid=account(path,"Old Login",salt=salt,password_hash=digest)
    old,name=web.login_user({"username":"Old Login","password":"old-password"})
    handler=SimpleNamespace(headers={"Cookie":"mahjong_session="+old})
    new,_=web.issue_session(handler,uid)
    assert old!=new and old not in web._sessions
    web.change_password(name,{"old_password":"old-password","new_password":"new-password","confirm_password":"new-password"})
    assert names.read_accounts(path)["users"]["old login"]["password_hash"].startswith("$argon2id$")


def test_discord_upload_priority_unique_binding_unbind_and_default(directory):
    path,_=directory;reg.create_new(web,form("Alice"));reg.create_new(web,form("Bob"))
    uid=web.stable_account_id("Alice");other=web.stable_account_id("Bob")
    discord.bind(path,uid,"123456789012345678","Discord","https://cdn.discordapp.com/avatar.png")
    assert web.avatar_for_name("Alice").startswith("https://")
    upload="data:image/png;base64,dXBsb2Fk";web.update_user_avatar("Alice",upload)
    discord.bind(path,uid,"123456789012345678","Discord","https://cdn.discordapp.com/new.png")
    assert web.avatar_for_name("Alice")==upload
    with pytest.raises(ValueError,match="already bound"):discord.bind(path,other,"123456789012345678","Discord")
    web.unbind_discord_account("Alice");assert web.avatar_for_name("Alice")==upload
    discord.bind(path,other,"123456789012345678","Discord","https://cdn.discordapp.com/other.png")
    web.unbind_discord_account("Bob");assert web.avatar_for_name("Bob")==""


def test_oauth_state_bound_to_session_and_failure_keeps_account(directory,monkeypatch):
    path,_=directory;reg.create_new(web,form());uid=web.stable_account_id("New Member")
    for key in ("DISCORD_CLIENT_ID","DISCORD_CLIENT_SECRET","DISCORD_REDIRECT_URI"):monkeypatch.setenv(key,"test")
    from urllib.parse import urlsplit,parse_qs
    state=parse_qs(urlsplit(discord.start(uid,"cookie","/target")).query)["state"][0]
    with pytest.raises(ValueError):discord.complete(path,{"state":state,"code":"code"},uid,"different")
    state=parse_qs(urlsplit(discord.start(uid,"cookie","/target")).query)["state"][0]
    assert discord.complete(path,{"state":state,"error":"access_denied"},uid,"cookie")==('/target',False)
    assert web.login_user(form())[1]=="New Member"


@pytest.mark.parametrize("target",["//evil.example","/\\evil.example","/%2f%2fevil.example","/\nLocation: evil","https://evil.example","/register"])
def test_return_target_is_local(target):assert reg.safe_return(target)=="/"


def test_claim_retains_existing_score_identity_and_historical_snapshot(directory, monkeypatch, tmp_path):
    from mahjong_api.store import Store
    from mahjong_api.database_models import User as ScoreUser
    from mahjong_api.tournament_models import Tournament
    from mahjong_api.tournament_rules import settings_value
    path,_=directory;old=legacy(web);account(path,"Admin",role="admin")
    score_path=tmp_path/"scores.sqlite3"
    monkeypatch.setenv("NFC_DATABASE_PATH",str(score_path))
    store=Store(score_path)
    state={"id":"historic","name":"History","settings":settings_value({}),"status":"draft","players":[{"id":"old-nfc-id","name":"Old Player"}],"rounds":[],"preview":None,"finals":None,"schema_version":3}
    with store.connect() as db:
        db.add(ScoreUser(id="old-nfc-id",name="Old Player"))
        db.add(Tournament(id="historic",version=1,state_json=json.dumps(state)))
    reg.submit_claim(web,form("Old Player",legacy_id=old["id"]))
    reg.review(web,{"claim_id":reg.claims(web)[0]["id"],"decision":"approve"},"Admin")
    assert web.stable_account_id("Old Player")=="old-nfc-id"
    with store.connect() as db:
        saved=json.loads(db.get(Tournament,"historic").state_json)
        assert saved["players"][0]["id"]=="old-nfc-id"
        assert saved["players"][0]["account_id"]=="old-nfc-id"
        assert saved["rounds"]==state["rounds"]
        assert db.get(ScoreUser,"old-nfc-id").name=="Old Player"
    store.close()
