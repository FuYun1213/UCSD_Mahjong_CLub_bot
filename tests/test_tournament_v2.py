"""V2 rules, permissions, additive migration and server-clock workflows."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, delete
from mahjong_api.auth import get_current_user
from mahjong_api.config import Settings
from mahjong_api.external_sync import ExternalSync
from mahjong_api.http_security import request_scheme, same_origin
from mahjong_api.main import create_app
from mahjong_api.migrations import migrate
from mahjong_api.models import User
from mahjong_api.sheets import DisabledSheets
from mahjong_api.store import Store, Conflict
from mahjong_api.tournament import TournamentService
from mahjong_api.tournament_models import Tournament, TournamentCheckIn, TournamentTableSession
from mahjong_api.tournament_rules import score_table, settings_value
from test_tournament import rig, tournament, command, round_complete, finals

ADMIN=User(id="admin-1",name="Admin",role="admin")

def action(s,tid,name,**data):
    return s.apply(tid,name,dict(version=s.get(tid)["version"],request_id=str(uuid4()),**data),ADMIN.id,actor_user=ADMIN)

def waiting(s,count=4,limit=60):
    st=tournament(s,count);tid=st["id"]
    action(s,tid,"settings",settings={"time_limit_seconds":limit})
    action(s,tid,"start");action(s,tid,"pair");st=action(s,tid,"confirm_seats")
    return tid,st["rounds"][-1]["tables"][0]

def participate(s,tid,t,name,pid=None,key=None):
    return s.participant_action(tid,t["match_id"],name,User(id=pid or t["seats"][0],name="Player"),key or str(uuid4()))

def check_all(s,tid,t):
    for pid in t["seats"]:participate(s,tid,t,"check_in",pid)

@pytest.mark.parametrize("divisor,unit,expected",[(1000,.1,[60,10,-20,-50]),(2000,.1,[45,10,-15,-40]),(3000,.1,[40,10,-13.3,-36.7])])
def test_return_formula_uses_existing_divisor_and_rounding(rig,divisor,unit,expected):
    s,*_=rig;tid,t=waiting(s)
    st=action(s,tid,"settings",settings={"return_point":30000,"divisor":divisor,"min_unit":unit,"uma":[999,10,-10,-30]})
    st["settings"].update({"raw_step":100,"divisor":divisor,"min_unit":unit})  # Legacy snapshot compatibility only.
    result=score_table(st,t,dict(zip(t["seats"],[40000,30000,20000,10000])))
    assert [p["gameScore"] for p in result["players"]]==expected
    assert result["players"][0]["placementPointsApplied"] is False
    assert result["rules"]["raw_step"]==100
    assert result["rules"]["divisor"]==divisor
    assert result["rules"]["min_unit"]==unit
    assert result["players"][2]["pointDifference"]==-10000

def test_winner_uses_absolute_sum_even_when_others_positive(rig):
    s,*_=rig;tid,t=waiting(s)
    st=action(s,tid,"settings",settings={"return_point":0,"uma":[-999,0,0,0]})
    result=score_table(st,t,dict(zip(t["seats"],[40000,30000,20000,10000])))
    assert [p["gameScore"] for p in result["players"]]==[60,30,20,10]

@pytest.mark.parametrize("uma",[[1,2,3],[1,2,3,4,5],None])
def test_exact_four_placement_values(uma):
    with pytest.raises(Conflict):settings_value({"uma":uma})
    assert settings_value({"uma":[0,-1,2,0]})["uma"]==[0,-1,2,0]

def test_return_snapshot_does_not_change_confirmed_result(rig):
    s,*_=rig;st=tournament(s,4);tid=st["id"]
    command(s,tid,"start");st=round_complete(s,tid)
    result=copy.deepcopy(st["rounds"][0]["tables"][0]["result"])
    st=action(s,tid,"settings",settings={"return_point":50000,"uma":[1,2,3,4]})
    assert st["rounds"][0]["tables"][0]["result"]==result

def test_self_check_in_idempotence_assignment_and_start_gate(rig):
    s,_,store,_=rig;tid,t=waiting(s,8)
    other=next(p["id"] for p in s.get(tid)["players"] if p["id"] not in t["seats"])
    with pytest.raises(Conflict,match="not_assigned"):participate(s,tid,t,"check_in",other)
    with pytest.raises(Conflict,match="check_in_incomplete"):participate(s,tid,t,"start_table")
    participate(s,tid,t,"check_in",key="same-check")
    participate(s,tid,t,"check_in",key="same-check")
    participate(s,tid,t,"check_in")
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TournamentCheckIn))==1
    check_all(s,tid,t)
    assert s.get(tid)["rounds"][0]["tables"][0]["session"]["status"]=="READY_TO_START"
    with ThreadPoolExecutor(4) as pool:
        states=list(pool.map(lambda pid:participate(s,tid,t,"start_table",pid),t["seats"]))
    starts={x["rounds"][0]["tables"][0]["session"]["started_at"] for x in states}
    assert len(starts)==1 and None not in starts
    assert sum(a["action"]=="start_table" for a in s.get(tid)["audit"])==1
    with pytest.raises(Conflict,match="already_started"):participate(s,tid,t,"check_in")

def test_timer_persistence_expiration_no_automatic_scores(rig):
    s,_,store,_=rig;tid,t=waiting(s)
    s.clock=lambda:"2026-09-17T12:00:00.000+00:00"
    check_all(s,tid,t);st=participate(s,tid,t,"start_table")
    session=st["rounds"][0]["tables"][0]["session"]
    assert session["ends_at"]=="2026-09-17T12:01:00.000+00:00"
    s.clock=lambda:"2026-09-17T12:01:01.000+00:00"
    st=s.get(tid)
    assert st["rounds"][0]["tables"][0]["session"]["status"]=="TIME_EXPIRED"
    assert not st["penalties"] and not st["rounds"][0]["tables"][0]["result"]
    fresh=Store(store.path)
    try:
        service=TournamentService(fresh,ExternalSync(fresh));service.clock=s.clock
        assert service.get(tid)["rounds"]==st["rounds"]
    finally:fresh.close()
    # Expiration never removes the ability to submit.
    st=action(s,tid,"score_table",table=1,scores=dict(zip(t["seats"],[40000,30000,20000,10000])))
    assert st["rounds"][0]["tables"][0]["session"]["status"]=="SCORE_PENDING"

def test_explicit_reset_retains_old_check_in_history(rig):
    s,_,store,_=rig;tid,t=waiting(s)
    check_all(s,tid,t);participate(s,tid,t,"start_table")
    st=action(s,tid,"reset_table",match_id=t["match_id"],reason="Restart approved")
    session=st["rounds"][0]["tables"][0]["session"]
    assert session["started_at"] is None and not session["checked_in"]
    check_all(s,tid,t)
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TournamentCheckIn))==8
    assert any(a["action"]=="reset_table" for a in st["audit"])

def test_penalty_admin_guard_history_edit_and_revoke(rig):
    s,*_=rig;st=tournament(s,4);tid=st["id"]
    command(s,tid,"start");st=round_complete(s,tid)
    original=copy.deepcopy(st["rounds"]);pid=st["standings"][0]["id"];score=st["standings"][0]["score"]
    data={"version":st["version"],"request_id":"no","player_id":pid,"amount":10,"reason":"Penalty"}
    for user in (None,User(id=ADMIN.id,name="Player",role="user")):
        with pytest.raises(Conflict,match="admin_required"):s.apply(tid,"penalty_add",data,ADMIN.id,actor_user=user)
    st=action(s,tid,"penalty_add",player_id=pid,amount=10,reason="Late")
    p=st["penalties"][0];row=next(r for r in st["standings"] if r["id"]==pid)
    assert row["game_score"]==score and row["penalty_total"]==-10 and row["score"]==score-10
    st=action(s,tid,"penalty_edit",penalty_id=p["id"],amount=5,reason="Review")
    assert {p["status"] for p in st["penalties"]}=={"active","replaced"}
    active=next(p for p in st["penalties"] if p["status"]=="active")
    st=action(s,tid,"penalty_revoke",penalty_id=active["id"],reason="Appeal")
    assert next(r for r in st["standings"] if r["id"]==pid)["score"]==score
    assert st["rounds"]==original
    assert {"penalty_add","penalty_edit","penalty_revoke"} <= {a["action"] for a in st["audit"]}
    assert all(p["created_by"]==ADMIN.id and p["revoked_by"]==ADMIN.id for p in st["penalties"])

def test_penalties_carry_proportionally_into_finals(rig):
    s,*_=rig;st=tournament(s,4);tid=st["id"]
    command(s,tid,"start");st=round_complete(s,tid);pid=st["standings"][0]["id"]
    st=action(s,tid,"penalty_add",player_id=pid,amount=10,reason="Late");pen=st["penalties"][0]
    st=finals(s,tid,carry="ratio",ratio=.5);row=next(r for r in st["standings"] if r["id"]==pid)
    before=row["score"];assert row["penalty_total"]==-5
    st=action(s,tid,"penalty_revoke",penalty_id=pen["id"],reason="Review")
    assert next(r for r in st["standings"] if r["id"]==pid)["score"]==before+5
    st=action(s,tid,"penalty_add",player_id=pid,amount=3,reason="Finals")
    assert next(r for r in st["standings"] if r["id"]==pid)["score"]==before+2

def test_identity_binding_admin_and_freeze(rig):
    s,*_=rig;tid,t=waiting(s)
    def registered(ids):
        if not all(uid in {"real-account", "other"} for uid in ids):
            raise Conflict("account_not_found", "account_not_found")
        return [{"id": uid, "name": "Registered " + uid} for uid in ids]
    s.account_lookup = registered
    pid=t["seats"][0]
    action(s,tid,"bind_account",player_id=pid,account_id="real-account")
    with pytest.raises(Conflict,match="not_assigned"):participate(s,tid,t,"check_in",pid)
    participate(s,tid,t,"check_in","real-account")
    with pytest.raises(Conflict,match="identity_frozen"):action(s,tid,"bind_account",player_id=pid,account_id="other")

def test_additive_legacy_migration_preserves_names_and_scores(rig):
    s,_,store,_=rig;st=tournament(s,4);tid=st["id"]
    command(s,tid,"start");round_complete(s,tid)
    with store.connect() as db:
        row=db.get(Tournament,tid);old=json.loads(row.state_json);old["schema_version"]=1
        for k in ("return_point","scoring_mode","time_limit_seconds"):old["settings"].pop(k)
        table=old["rounds"][0]["tables"][0];table.pop("table_id");table["name"]="Historical Machine"
        result=copy.deepcopy(table["result"])
        for k in ("return_point","scoring_mode","time_limit_seconds"):table["result"]["rules"].pop(k)
        result=copy.deepcopy(table["result"])
        row.state_json=json.dumps(old)
        db.execute(delete(TournamentCheckIn));db.execute(delete(TournamentTableSession))
    migrate(store.engine);migrate(store.engine)
    st=s.get(tid);table=st["rounds"][0]["tables"][0]
    assert st["settings"]["scoring_mode"]=="legacy"
    assert table["name"]=="Historical Machine" and table["result"]==result
    assert table["session"]["status"]=="COMPLETED" and table["session"]["started_at"] is None

def test_trusted_headers_exact_origin_and_secure_cookie(monkeypatch):
    from web_server import secure_cookie_suffix
    monkeypatch.setenv("PUBLIC_SITE_URL","https://ucsdmj.org")
    h=SimpleNamespace(client_address=("127.0.0.1",123),headers={"Host":"ucsdmj.org","X-Forwarded-Proto":"https","Origin":"https://ucsdmj.org"})
    assert request_scheme(h)=="https" and same_origin(h)
    assert all(x in secure_cookie_suffix(h) for x in ("Secure","HttpOnly","SameSite=Lax"))
    h.headers["Origin"]="https://ucsdmj.org.evil.invalid";assert not same_origin(h)
    h.client_address=("192.0.2.10",123);assert request_scheme(h)=="http"

def test_route_rejects_penalty_and_check_in_spoofing(tmp_path):
    app=create_app(Settings(database_path=tmp_path/"routes.db"),DisabledSheets())
    who=User(id="admin-1",name="Admin",role="admin")
    app.dependency_overrides[get_current_user]=lambda:who
    with TestClient(app) as c:
        tid,t=waiting(app.state.tournaments)
        pid=t["seats"][0]
        who.role="user"
        r=c.post("/api/tournaments/"+tid+"/actions",json={"action":"penalty_add","data":{"player_id":pid,"amount":10,"reason":"hack","version":1,"request_id":"hack"}})
        assert r.status_code==403
        who.id=pid
        r=c.post("/api/tournaments/"+tid+"/tables/"+t["match_id"]+"/check-in",json={"request_id":"spoof","player_id":t["seats"][1]})
        assert r.status_code==422
        assert c.post("/api/tournaments/"+tid+"/tables/"+t["match_id"]+"/check-in",json={"request_id":"self"}).status_code==200
