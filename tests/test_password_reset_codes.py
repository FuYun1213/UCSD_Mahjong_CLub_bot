"""Recovery uses isolated accounts; Discord delivery is always stubbed."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlparse, parse_qs
import pytest
import requests
import web_server as web
import registered_names
from account_passwords import verify_password
from test_registered_names import directory, account
from test_web_score_bridge import website, login

OLD="Original!Password"
NEW="UserChosen!Password"

@pytest.fixture
def recovery(directory, monkeypatch):
    path,_=directory
    salt,digest=web.password_hash(OLD)
    for name,role in [("Alice","user"),("Bob","user"),("Ops","admin"),("Super","super_admin")]:
        account(path,name,role=role,salt=salt,password_hash=digest)
    monkeypatch.setattr(web,"_session_account_ids",{})
    actions=[];messages=[]
    monkeypatch.setattr(web,"record_action",lambda **event:actions.append(event))
    monkeypatch.setattr(web,"discord_request",lambda method,route,payload:messages.append((method,route,payload)))
    monkeypatch.setenv("PUBLIC_SITE_URL","https://club.example")
    return path,actions,messages

def issue(name="Alice",actor="Ops"):
    return web.reset_user_password({"username":name},actor)

def redeem(code,name="Alice",password=NEW):
    return web.redeem_password_reset({"username":name,"reset_code":code,"new_password":password,"confirm_password":password})

def row(path,name="Alice"):
    return json.loads(path.read_text(encoding="utf-8"))["users"][name.lower()]

def test_issue_does_not_change_password_or_sessions_and_stores_only_hash(recovery):
    path,actions,_=recovery;token,_=web.login_user({"username":"Alice","password":OLD})
    before=row(path);result=issue();after=row(path)
    assert verify_password(OLD,after) and after["password_hash"]==before["password_hash"]
    assert token in web._sessions and result["expires_in"]==1800
    assert len(result["reset_code"])==14 and result["reset_url"]=="/login#reset-password"
    assert result["reset_code"] not in path.read_text()
    assert result["reset_code"].replace("-","") not in path.read_text()
    assert result["reset_code"] not in json.dumps(actions)
    assert "digest" in after["password_reset"]

@pytest.mark.parametrize("actor,target,allowed",[("Alice","Bob",False),("Ops","Alice",True),("Ops","Ops",False),("Ops","Super",False),("Super","Ops",True),("Super","Super",True)])
def test_issuance_role_boundaries(recovery,actor,target,allowed):
    if allowed:assert issue(target,actor)["ok"]
    else:
        with pytest.raises(PermissionError):issue(target,actor)

@pytest.mark.parametrize("field",["new_password","password","confirm_password"])
def test_legacy_admin_direct_password_change_is_rejected(recovery,field):
    path,_,_=recovery
    with pytest.raises(web.PasswordResetError) as error:web.reset_user_password({"username":"Alice",field:NEW},"Super")
    assert error.value.code=="admin_password_reset_disabled"
    assert verify_password(OLD,row(path)) and "password_reset" not in row(path)

def test_code_is_account_bound_single_use_and_revoke_all_own_sessions(recovery):
    path,actions,_=recovery
    first,_=web.login_user({"username":"Alice","password":OLD});second,_=web.login_user({"username":"Alice","password":OLD});other,_=web.login_user({"username":"Bob","password":OLD})
    code=issue()["reset_code"]
    with pytest.raises(web.PasswordResetError):redeem(code,"Bob")
    assert redeem(" "+code.lower().replace("-"," ")+" ")["ok"]
    assert verify_password(NEW,row(path)) and not verify_password(OLD,row(path))
    assert first not in web._sessions and second not in web._sessions and other in web._sessions
    assert first not in web._session_account_ids and second not in web._session_account_ids
    assert "password_reset" not in row(path)
    with pytest.raises(web.PasswordResetError):redeem(code)
    with pytest.raises(ValueError):web.login_user({"username":"Alice","password":OLD})
    assert web.login_user({"username":"Alice","password":NEW})[1]=="Alice"
    assert len([a for a in actions if a["action_type"]=="redeem_password_reset_code"])==1
    assert NEW not in json.dumps(actions)

def test_reissue_invalidates_previous_code(recovery):
    old=issue()["reset_code"];new=issue()["reset_code"];assert old!=new
    with pytest.raises(web.PasswordResetError):redeem(old)
    assert redeem(new)["ok"]

def test_expiry_boundary_and_attempt_limit_persist(recovery,monkeypatch):
    path,_,_=recovery;result=issue()
    with monkeypatch.context() as patch:
        patch.setattr(web.time,"time",lambda:result["expires_at"])
        with pytest.raises(web.PasswordResetError):redeem(result["reset_code"])
    assert "password_reset" not in row(path)
    result=issue()
    for _ in range(5):
        with pytest.raises(web.PasswordResetError):redeem("WRONG-CODE")
    with pytest.raises(web.PasswordResetError):redeem(result["reset_code"])
    assert verify_password(OLD,row(path))
    assert redeem(issue()["reset_code"])["ok"]

@pytest.mark.parametrize("extra,code",[({"new_password":"short","confirm_password":"short"},"invalid_reset_password"),({"new_password":"x"*1025,"confirm_password":"x"*1025},"invalid_reset_password"),({"new_password":None},"invalid_reset_password"),({"confirm_password":"different"},"reset_password_mismatch")])
def test_password_validation_does_not_consume_valid_code(recovery,extra,code):
    issued=issue()["reset_code"]
    data={"username":"Alice","reset_code":issued,"new_password":NEW,"confirm_password":NEW,**extra}
    with pytest.raises(web.PasswordResetError) as error:web.redeem_password_reset(data)
    assert error.value.code==code
    assert redeem(issued)["ok"]

@pytest.mark.parametrize("flag,value",[("disabled",True),("is_active",False),("status","banned"),("status","pending_claim")])
def test_disabled_accounts_cannot_receive_or_redeem_codes(recovery,flag,value):
    path,_,_=recovery;code=issue()["reset_code"]
    data=web.users_data();data["users"]["alice"][flag]=value;web.write_json(path,data)
    with pytest.raises(ValueError):issue()
    with pytest.raises(web.PasswordResetError):redeem(code)

def test_concurrent_redemptions_only_one_succeeds(recovery):
    path,actions,_=recovery;code=issue()["reset_code"];barrier=threading.Barrier(2)
    def attempt(index):
        barrier.wait()
        try:redeem(code,password=NEW+str(index));return "ok"
        except web.PasswordResetError:return "consumed"
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(attempt,[1,2]))==["consumed","ok"]
    assert len([a for a in actions if a["action_type"]=="redeem_password_reset_code"])==1

def test_regular_password_change_revokes_pending_reset_code(recovery):
    code=issue()["reset_code"]
    web.change_password("Alice",{"old_password":OLD,"new_password":NEW,"confirm_password":NEW})
    with pytest.raises(web.PasswordResetError):redeem(code)

def test_failed_account_publication_does_not_consume_code(recovery,monkeypatch):
    path,_,_=recovery;code=issue()["reset_code"]
    with monkeypatch.context() as patch:
        def fail(*args):raise OSError("simulated disk failure")
        patch.setattr(web,"write_json",fail)
        with pytest.raises(OSError):redeem(code)
    assert verify_password(OLD,row(path)) and redeem(code)["ok"]

def test_stable_identity_guard_rejects_changed_admin_selection(recovery):
    with pytest.raises(web.PasswordResetError) as error:web.reset_user_password({"username":"Alice","user_id":"not-alice"},"Ops")
    assert error.value.code=="stale_reset_account"

def test_request_uses_only_designated_channel_and_authenticated_admin_link(recovery):
    path,_,messages=recovery
    result=web.request_password_reset({"username":"Alice"})
    assert result["ok"] and len(messages)==1
    method,route,payload=messages[0]
    assert method=="POST" and route=="/channels/1488771447915544586/messages"
    assert payload["allowed_mentions"]=={"parse":[]}
    link=urlparse(payload["embeds"][0]["url"])
    assert link.scheme=="https" and link.netloc=="club.example" and link.fragment=="account-recovery"
    assert parse_qs(link.query)=={"page":["admin"],"recovery_user":[row(path)["account_id"]]}
    assert payload["embeds"][0]["fields"][0]["value"]=="Alice"
    assert "password_reset" not in row(path) and verify_password(OLD,row(path))
    assert "reset_code" not in json.dumps(payload) and OLD not in json.dumps(payload)
    assert web.request_password_reset({"username":"Alice"})==result and len(messages)==1
    assert web.request_password_reset({"username":"Not registered"})==result and len(messages)==1

def test_notification_failure_is_retryable_and_does_not_expose_provider_details(recovery,monkeypatch):
    path,_,messages=recovery
    with monkeypatch.context() as patch:
        def fail(*args):raise RuntimeError("private provider credential")
        patch.setattr(web,"discord_request",fail)
        with pytest.raises(web.PasswordResetError) as error:web.request_password_reset({"username":"Alice"})
        assert error.value.code=="reset_notification_failed" and "credential" not in str(error.value)
    assert "password_reset_request" not in row(path)
    assert web.request_password_reset({"username":"Alice"})["ok"] and len(messages)==1

def test_simultaneous_reset_requests_only_send_one_notification(recovery):
    _,_,messages=recovery;barrier=threading.Barrier(2)
    def attempt(_):barrier.wait();return web.request_password_reset({"username":"Alice"})
    with ThreadPoolExecutor(max_workers=2) as pool:assert all(r["ok"] for r in pool.map(attempt,[1,2]))
    assert len(messages)==1

@pytest.fixture
def recovery_website(website,monkeypatch):
    url,_,_=website;data=web.users_data();data["users"]["photo1"]["role"]="admin";data["users"]["photo8"]["role"]="super_admin";web.write_json(web.USERS_FILE,data)
    messages=[];actions=[]
    monkeypatch.setattr(web,"discord_request",lambda *args:messages.append(args))
    monkeypatch.setattr(web,"record_action",lambda **kw:actions.append(kw))
    monkeypatch.setattr(web,"admin_recent_actions",lambda *a,**kw:{"ok":True,"actions":[]})
    monkeypatch.setenv("PUBLIC_SITE_URL",url)
    return url,messages,actions

def test_real_http_permissions_origin_cookie_revocation_and_secret_projection(recovery_website):
    url,messages,_=recovery_website;admin=login(url,1);user=login(url,2)
    endpoint=url+"/api/admin/password-reset";data={"username":"photo2"}
    assert requests.post(endpoint,json=data).status_code==401
    assert user.post(endpoint,json=data).status_code==403
    assert admin.post(endpoint,json=data,headers={"Origin":"https://evil.example"}).status_code==403
    assert admin.post(endpoint,json={**data,"new_password":"admin-chosen"}).status_code==400
    issued=admin.post(endpoint,json=data);assert issued.status_code==200
    assert "no-store" in issued.headers["Cache-Control"]
    code=issued.json()["reset_code"]
    for path in ["/api/session","/api/registered-users"]:
        assert code not in admin.get(url+path).text
        assert "password_reset" not in admin.get(url+path).text
    payload={"username":"photo2","reset_code":code,"new_password":NEW,"confirm_password":NEW}
    assert requests.post(url+"/api/reset-password",json=payload,headers={"Origin":"https://evil.example"}).status_code==401
    assert requests.post(url+"/api/reset-password",json=payload,headers={"Origin":url}).status_code==200
    assert user.get(url+"/api/session").json()["profile"] is None
    assert admin.get(url+"/api/session").json()["profile"]["name"]=="photo1"
    assert requests.post(url+"/api/reset-password",json=payload).status_code==400
    assert requests.post(url+"/api/forgot-password",json={"username":"photo3"}).status_code==200
    assert messages[0][1]=="/channels/1488771447915544586/messages"
    assert requests.get(url+"/api/club-tables").status_code==401

def test_recovery_flow_and_admin_notification_link_in_browser(recovery_website):
    url,messages,_=recovery_website
    env={**os.environ,"NFC_TEST_URL":url,"NODE_PATH":str(Path(os.environ.get('NODE_PATH') or '.venv-api/browser-tests/node_modules').resolve())}
    result=subprocess.run(['node','tests/browser_password_reset.cjs'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=160)
    assert result.returncode==0,result.stdout+result.stderr
    assert len(messages)==1 and messages[0][1]=="/channels/1488771447915544586/messages"


def test_login_racing_reset_cannot_keep_an_old_password_session(recovery,monkeypatch):
    path,_,_=recovery;code=issue()["reset_code"]
    entered,release=threading.Event(),threading.Event();original=web.verify_password
    def delayed(password,account):
        result=original(password,account);entered.set();assert release.wait(5);return result
    monkeypatch.setattr(web,"verify_password",delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        logging_in=pool.submit(web.login_user,{"username":"Alice","password":OLD})
        assert entered.wait(5)
        resetting=pool.submit(redeem,code);release.set()
        token,_=logging_in.result();assert resetting.result()["ok"]
    assert token not in web._sessions


def test_recovery_endpoint_keeps_existing_ip_rate_limit(recovery_website,monkeypatch):
    url,messages,_=recovery_website
    monkeypatch.setattr(web,"WRITE_RATE_LIMIT",1)
    assert requests.post(url+"/api/forgot-password",json={"username":"photo2"}).status_code==200
    response=requests.post(url+"/api/forgot-password",json={"username":"photo3"})
    assert response.status_code==401 and len(messages)==1
