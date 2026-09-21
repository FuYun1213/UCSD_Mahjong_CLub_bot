"""Placement/game-count scoring and scoped anonymous competition identities."""
from contextlib import closing
import copy
import json
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from fastapi.testclient import TestClient
from mahjong_api.store import Conflict
from mahjong_api.tournament_rules import settings_value, score_table, standings, PLACEMENT_FIELDS
from mahjong_api.tournament_models import Tournament, TournamentAudit
from mahjong_api.guest_models import TournamentParticipant
from mahjong_api.guest_service import GuestService
from mahjong_api.guest_routes import cookie
from mahjong_api.table_models import ActiveTableMember
from mahjong_api.auth import get_current_user
from test_table_v3 import setup,make,token,raw,ADMIN,USERS,data
from test_tournament import rig,tournament,command,round_complete

RULES={"scoring_mode":"placement_and_game_count",**dict(zip(PLACEMENT_FIELDS,[5,3,1,0,2])),"allow_guest_auto_enrollment":True}


@pytest.mark.parametrize("key",PLACEMENT_FIELDS)
def test_all_five_scores_required(key):
    value=RULES.copy();value.pop(key)
    with pytest.raises(Conflict):settings_value(value)
    value[key]=""
    with pytest.raises(Conflict):settings_value(value)


def test_zero_negative_and_nonzero_sum_are_allowed():
    rules=settings_value({**RULES,**dict(zip(PLACEMENT_FIELDS,[-1,0,2,4,-3]))})
    assert rules["first_placement_game_score"]==-1 and rules["game_participation_score"]==-3


def state_for_scores():
    return {"settings":settings_value(RULES),"players":[{"id":p,"name":p} for p in "ABCD"],"rounds":[],"finals":None,"penalties":[]}


def test_independent_formula_has_no_conversion_fields_and_ties():
    state=state_for_scores();table={"seats":list("ABCD")}
    state["settings"].update(uma=[999,888,777,666],return_point=99999,divisor=1,min_unit=100)
    result=score_table(state,table,dict(zip("ABCD",[40000,30000,20000,10000])))
    assert [p["gameScore"] for p in result["players"]]==[7,5,3,2]
    assert all(not set(p)&{"placementPoints","convertedPoints","returnPoint","pointDifference","winnerOtherTotal"} for p in result["players"])
    assert set(result["rules"])=={"scoring_mode",*PLACEMENT_FIELDS}
    # A places first, second and fourth: 8 placement points + 6 participation.
    for points in ([40000,30000,20000,10000],[30000,40000,20000,10000],[10000,40000,30000,20000]):
        state["rounds"].append({"status":"confirmed","byes":[],"tables":[{"result":score_table(state,table,dict(zip("ABCD",points)))}]})
    row=next(r for r in standings(state) if r["id"]=="A")
    assert (row["score"],row["completed_rounds"],row["placement_score_total"],row["participation_score_total"])==(14,3,8,6)
    state["penalties"]=[{"status":"active","phase":"swiss","player_id":"A","amount":"-2"}]
    assert next(r for r in standings(state) if r["id"]=="A")["score"]==16
    state["settings"].update(dict(zip(PLACEMENT_FIELDS,[0,0,0,0,0])))
    state["rounds"]=[];state["penalties"]=[]
    assert [r["rank"] for r in standings(state)]==[1,1,1,1]


@pytest.mark.parametrize("status",["draft","pending","active","cancelled","void"])
def test_unconfirmed_games_do_not_count(status):
    state=state_for_scores();state["rounds"]=[{"status":status,"byes":[],"tables":[]}]
    assert all(r["completed_rounds"]==0 and r["score"]==0 for r in standings(state))


@pytest.mark.parametrize("flag",["void","is_test","duplicate_of"])
def test_invalid_confirmed_table_not_counted(flag):
    state=state_for_scores();result=score_table(state,{"seats":list("ABCD")},dict(zip("ABCD",[40000,30000,20000,10000])))
    state["rounds"]=[{"status":"confirmed","byes":[],"tables":[{"result":result,flag:True}]}]
    assert all(r["completed_rounds"]==0 for r in standings(state))


def test_snapshot_at_confirmation_and_explicit_recalculation(rig):
    s,*_=rig;st=tournament(s,4);tid=st["id"]
    command(s,tid,"settings",settings=RULES);command(s,tid,"start");command(s,tid,"pair");st=command(s,tid,"confirm_seats")
    table=st["rounds"][-1]["tables"][0]
    command(s,tid,"score_table",table=table["number"],scores=dict(zip(table["seats"],[40000,30000,20000,10000])))
    command(s,tid,"settings",settings={"game_participation_score":3})
    st=command(s,tid,"confirm_round");snapshot=copy.deepcopy(st["rounds"][0]["tables"][0]["result"])
    assert snapshot["rules"]["game_participation_score"]==3
    st=command(s,tid,"settings",settings={"game_participation_score":4})
    assert st["rounds"][0]["tables"][0]["result"]==snapshot
    st=command(s,tid,"recalculate",reason="Approved new rules")
    assert st["rounds"][0]["tables"][0]["result"]["rules"]["game_participation_score"]==4
    assert st["rounds"][0]["tables"][0]["result_revisions"][0]==snapshot
    assert any(a["action"]=="recalculate" for a in st["audit"])


def guest_cup(setup,allow=True):
    tables,app=setup
    st=tables.tournaments.create(data(name="Guest Cup",settings={**RULES,"allow_guest_auto_enrollment":allow}),ADMIN.id)
    table=make(tables,3,st["id"])
    return tables,app,st,table,GuestService(tables.tournaments,tables)


def test_guest_default_off_and_no_ordinary_context(setup):
    tables,app,st,table,svc=guest_cup(setup,False)
    with pytest.raises(Conflict,match="guest_not_allowed"):svc.join(st["id"],{"table_id":table["id"],"name":"Visitor"},None)
    command(tables.tournaments,st["id"],"settings",settings={"allow_guest_auto_enrollment":True})
    ordinary=make(tables,9)
    with pytest.raises(Conflict,match="guest_context_required"):svc.join(st["id"],{"table_id":ordinary["id"],"name":"Visitor"},None)
    assert not tables.tournaments.get(st["id"])["players"]


def test_guest_join_reuses_cookie_and_stable_roster_and_never_leaks_token(setup):
    tables,app,st,table,svc=guest_cup(setup);entry=raw(token(tables,table,"nfc"))
    result,secret=svc.join(st["id"],{"table_id":table["id"],"name":"  Ｖisitor  ","entry_token":entry},None)
    assert secret and result["participant"]["name"]=="Visitor"
    repeat,again=svc.join(st["id"],{"table_id":table["id"],"name":"changed"},secret)
    assert repeat==result and again is None
    with tables.store.connect() as db:
        row=db.get(TournamentParticipant,result["participant"]["id"])
        assert secret not in str(row.__dict__) and row.session_hash!=secret
        assert db.scalar(select(func.count()).select_from(ActiveTableMember))==1
        assert secret not in " ".join(db.scalars(select(TournamentAudit.detail_json)))
    assert len(tables.tournaments.get(st["id"])["players"])==1
    assert not any(p["id"]==result["participant"]["id"] for p in tables._account_rows())


@pytest.mark.parametrize("name",[" ","Person 0"," ＰＥＲＳＯＮ ０ "])
def test_guest_name_validation_and_impersonation(setup,name):
    tables,app,st,table,svc=guest_cup(setup)
    with pytest.raises((Conflict,ValueError)):svc.join(st["id"],{"table_id":table["id"],"name":name},None)


def test_other_cookie_cannot_take_same_name_or_leave_another_guest(setup):
    tables,app,st,table,svc=guest_cup(setup)
    one,secret=svc.join(st["id"],{"table_id":table["id"],"name":"Alice Guest"},None)
    with pytest.raises(Conflict,match="guest_name_taken"):svc.join(st["id"],{"table_id":table["id"],"name":" ALICE GUEST "},"forged")
    with pytest.raises(Conflict,match="guest_session_required"):svc.leave(st["id"],"forged")
    assert tables.get(table["id"],ADMIN)["player_count"]==1


def test_guest_manual_scores_merge_preserve_totals(setup):
    tables,app,st,table,svc=guest_cup(setup);tid=st["id"];s=tables.tournaments
    for i in range(4):st=command(s,tid,"guest_add",name="Guest "+str(i))
    ids=[p["id"] for p in st["players"]]
    st=command(s,tid,"manual_game",players=ids,scores=dict(zip(ids,[40000,30000,20000,10000])))
    before=[r["score"] for r in st["standings"]]
    st=command(s,tid,"guest_merge",player_id=ids[0],account_id=USERS[0].id,reason="Identity checked")
    assert [r["score"] for r in st["standings"]]==before
    assert len(st["rounds"])==1 and len(st["players"])==4
    assert st["players"][0]["account_id"]==USERS[0].id
    assert any(a["action"]=="guest_merge" for a in st["audit"])


def test_guest_http_permissions_cookie_csrf_and_recovery(setup):
    tables,app,st,table,svc=guest_cup(setup);tid=st["id"]
    with closing(TestClient(app)) as client:
        # Using the existing lifespan once more reinitializes the store services.
        app.state.tables.account_lookup=tables.account_lookup
        response=client.post(f"/api/guest/tournaments/{tid}/join",json={"table_id":table["id"],"name":"Browser Guest"})
        assert response.status_code==200,response.text
        assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=lax" in response.headers["set-cookie"]
        pid=response.json()["participant"]["id"]
        assert client.post(f"/api/tournaments/{tid}/actions",json={"action":"settings","data":{}}).status_code==401
        assert client.post("/api/manual-score/preview",json={}).status_code==401
        assert client.post(f"/api/guest/tournaments/{tid}/leave",headers={"Origin":"https://evil.invalid"}).status_code==403
        app.dependency_overrides[get_current_user]=lambda:ADMIN
        response=client.post(f"/api/tournaments/{tid}/guest-recovery",json={"player_id":pid,"reason":"Verified in person"})
        assert response.status_code==200,response.text
        recovery=response.json()["url"].split("guest_recovery=")[1]
        app.dependency_overrides.clear();client.cookies.clear()
        assert client.post(f"/api/guest/tournaments/{tid}/recover",json={"token":recovery}).status_code==200
        assert client.get(f"/api/guest/tournaments/{tid}").json()["participant"]["id"]==pid
        assert client.post(f"/api/guest/tournaments/{tid}/recover",json={"token":recovery}).status_code==409


def test_running_guest_table_full_checkin_and_draft_exclusion(setup):
    tables,app,st,table,svc=guest_cup(setup);tid=st["id"]
    # Existing registered roster starts the tournament; an additional guest table can fill progressively.
    for u in USERS[:4]:command(tables.tournaments,tid,"player",registered_user_id=u.id)
    command(tables.tournaments,tid,"start")
    secrets=[];ids=[]
    for i in range(4):
        result,secret=svc.join(tid,{"table_id":table["id"],"name":"Guest "+str(i),"seat":["east","south","west","north"][i]},None)
        secrets.append(secret);ids.append(result["participant"]["id"])
    st=tables.tournaments.get(tid);tb=st["rounds"][0]["tables"][0]
    assert tb["session"]["status"]=="READY_TO_START"
    tables.tournaments.participant_action(tid,tb["match_id"],"start_table",ADMIN,str(uuid4()))
    assert svc.join(tid,{"table_id":table["id"]},secrets[0])[0]["participant"]["id"]==ids[0]
    st=command(tables.tournaments,tid,"score_table",table=table["number"],scores=dict(zip(ids,[40000,30000,20000,10000])))
    assert all(r["completed_rounds"]==0 for r in st["standings"])
    st=command(tables.tournaments,tid,"confirm_round")
    assert [r["score"] for r in st["standings"] if r["id"] in ids]==[7,5,3,2]


def test_admin_seating_and_guest_rejoin_after_leave(setup):
    tables,app,st,table,svc=guest_cup(setup);tid=st["id"]
    st=command(tables.tournaments,tid,"guest_add",name="Admin Seated")
    pid=st["players"][0]["id"]
    result,secret=svc.join(tid,{"table_id":table["id"],"player_id":pid,"seat":"south"},None,admin_user=ADMIN)
    assert secret is None and result["seat"]=="south"
    own,secret=svc.join(tid,{"table_id":table["id"],"name":"Self Guest","seat":"west"},None)
    svc.leave(tid,secret)
    again,_=svc.join(tid,{"table_id":table["id"],"seat":"west"},secret)
    assert own==again


def test_guest_notification_has_name_and_no_mention():
    from mahjong_api.discord_reminder_sender import build_message
    message=build_message(table_number=3,start_at="2026-09-20T12:00:00+00:00",end_at="2026-09-20T13:00:00+00:00",
        participants=[{"id":"guest-opaque","name":"Guest Name"}],nonce="test",capacity=4)
    assert "Guest Name" in message["content"] and "<@" not in message["content"]
    assert message["allowed_mentions"]["users"]==[]
