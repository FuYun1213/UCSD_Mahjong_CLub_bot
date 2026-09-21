
"""Reservation regressions, registered-account choices, and legacy registration IDs."""
import copy,json
import pytest
from fastapi.testclient import TestClient
from mahjong_api.auth import get_current_user
from mahjong_api.store import Conflict
from test_table_v3 import setup, make, data, ADMIN, USERS

def test_registered_choices_only_public_profiles_and_unseated_accounts(setup,tmp_path,monkeypatch):
    s,_=setup;t=make(s);other=make(s,8)
    s.join(t["id"],USERS[0]);s.join(other["id"],USERS[1])
    s.account_lookup=None
    accounts={"users":{u.name:{"account_id":u.id,"name":u.name,"password_hash":"never-return","discord_id":"private","disabled":u==USERS[3]} for u in USERS[:5]}}
    path=tmp_path/"registered.json";path.write_text(json.dumps(accounts))
    monkeypatch.setenv("TABLE_ACCOUNT_FILE",str(path))
    result=s.available_players(t["id"],USERS[0])
    assert {p["id"] for p in result["players"]}=={USERS[2].id,USERS[4].id}
    assert all(set(p)=={"id","name","avatar"} for p in result["players"])
    assert "never-return" not in json.dumps(result) and "discord_id" not in json.dumps(result)
    assert s.available_players(t["id"],USERS[0],"PeRsOn 4")["players"][0]["id"]==USERS[4].id
    assert s.available_players(t["id"],USERS[0],"unknown")["players"]==[]
    with pytest.raises(Conflict,match="must_join_first"):s.available_players(t["id"],USERS[5])
    assert len(s.available_players(t["id"],ADMIN)["players"])==2
    # The write endpoint still verifies identity regardless of choices shown by the browser.
    with pytest.raises(Conflict,match="account_not_found"):s.add_players(t["id"],data(user_ids=["made-up"]),USERS[0])

def test_available_choices_rechecked_at_confirmation(setup):
    s,_=setup;t=make(s);other=make(s,8);s.join(t["id"],USERS[0])
    assert USERS[1].id in {p["id"] for p in s.available_players(t["id"],USERS[0])["players"]}
    s.join(other["id"],USERS[1])
    with pytest.raises(Conflict,match="already_at_other_table"):s.add_players(t["id"],data(user_ids=[USERS[1].id]),USERS[0])

def test_admin_can_reserve_without_joining_and_cancel(setup):
    s,app=setup;t=make(s)
    app.dependency_overrides[get_current_user]=lambda:ADMIN
    client=TestClient(app)
    result=client.post("/api/club-tables/"+t["id"]+"/reservations",json=data(scheduled_at="2026-10-02T18:00:00-07:00",note="Admin reservation"))
    assert result.status_code==200
    reservation=result.json()
    assert reservation["user_id"]==ADMIN.id and reservation["status"]=="active"
    assert s.get(t["id"],ADMIN)["player_count"]==0
    assert client.post("/api/table-reservations/"+reservation["id"],json={"status":"cancelled","version":reservation["version"]}).status_code==200

def test_registered_choice_api_requires_login_and_membership(setup):
    s,app=setup;t=make(s);client=TestClient(app)
    url="/api/club-tables/"+t["id"]+"/players"
    assert client.get(url).status_code==401
    app.dependency_overrides[get_current_user]=lambda:USERS[0]
    assert client.get(url).status_code==403
    s.join(t["id"],USERS[0])
    assert client.get(url,params={"q":USERS[1].name}).json()["players"][0]["id"]==USERS[1].id

def test_legacy_registered_accounts_receive_stable_ids_without_changing_credentials(tmp_path,monkeypatch):
    import web_server
    original={"users":{"alice":{"name":"Alice","salt":"old-salt","password_hash":"old-hash","role":"user"},
                       "bob":{"name":"Bob","account_id":"existing-id","password_hash":"other-hash","role":"admin"}}}
    path=tmp_path/"old-accounts.json";path.write_text(json.dumps(original))
    monkeypatch.setattr(web_server,"USERS_FILE",path)
    assert web_server.stable_account_id("Bob")=="existing-id"
    updated=json.loads(path.read_text())
    assert updated["users"]["alice"]["account_id"]
    assert web_server.stable_account_id("Alice")==updated["users"]["alice"]["account_id"]
    for key,account in original["users"].items():
        assert all(updated["users"][key][field]==value for field,value in account.items())
