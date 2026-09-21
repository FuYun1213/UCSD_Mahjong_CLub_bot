
"""Table v3 end-to-end persistence, authorization and shared entry contracts."""
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from mahjong_api.main import create_app
from mahjong_api.config import Settings
from mahjong_api.models import User
from mahjong_api.auth import get_current_user
from mahjong_api.sheets import DisabledSheets
from mahjong_api.store import Conflict, Store
from mahjong_api.table_models import ClubTable, ActiveTableMember, TableJoinToken, TableMembershipEvent, TableReservation
from mahjong_api.tournament_models import Tournament, TournamentTableSession, TournamentAudit
from mahjong_api.database_models import Metadata, SeatRecord
from mahjong_api.logging_filters import redact_table_token
from test_tournament import command, tournament, round_complete
from test_tournament_v2 import action, waiting, check_all, participate

ADMIN=User(id="admin-1",name="Administrator",role="admin")
USERS=[User(id="person-"+str(i),name="Person "+str(i)) for i in range(12)]

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.delenv("TABLE_TOKEN_SECRET_FILE",raising=False)
    app=create_app(Settings(database_path=tmp_path/"tables.sqlite3",mock_auth_enabled=True),DisabledSheets())
    with TestClient(app):
        service=app.state.tables
        service.account_lookup=lambda ids:[{"id":u.id,"name":u.name,"disabled":u.id=="disabled"} for u in USERS+[ADMIN,User(id="disabled",name="Disabled")] if ids is None or u.id in ids]
        yield service,app

def data(**kw):return {"request_id":str(uuid4()),**kw}
def make(s,n=3,tid=None):return s.create(data(number=n,tournament_id=tid),ADMIN)
def token(s,t,channel="qr",**kw):return s.issue_token(t["id"],data(channel=channel,**kw),ADMIN)
def raw(tok):return tok["path"].rsplit("/",1)[1]

def test_registry_arbitrary_numbers_stable_ids_and_scope(setup):
    s,_=setup
    tables=[make(s,n) for n in (2,3,10)]
    assert [t["number"] for t in s.list(USERS[0])["tables"]]==[2,3,10]
    assert all(t["id"]!=str(t["number"]) for t in tables)
    with pytest.raises(Conflict,match="duplicate_table_number"):make(s,3)
    st=s.tournaments.create(data(name="Different scope"),ADMIN.id)
    assert make(s,3,st["id"])["number"]==3
    for n in (0,-1,1.5,True,"2"):
        with pytest.raises(Conflict,match="invalid_table_number"):make(s,n)
    with pytest.raises(Conflict,match="admin_required"):s.create(data(number=8),USERS[0])

def test_qr_nfc_independence_rotation_revocation_hash_only(setup):
    s,_=setup;a,b=make(s,3),make(s,8)
    qr,nfc,other=token(s,a),token(s,a,"nfc"),token(s,b)
    with s.store.connect() as db:
        saved=db.get(TableJoinToken,qr["id"])
        assert saved.token_hash==hashlib.sha256(raw(qr).encode()).hexdigest()
        assert raw(qr) not in str(saved.__dict__)
        audit=" ".join(db.scalars(select(TournamentAudit.detail_json)))
        assert raw(qr) not in audit
    assert s.token_info(raw(qr))["number"]==3
    s.update(a["id"],{"number":30},ADMIN)
    assert s.token_info(raw(qr))["number"]==30
    token(s,a)
    with pytest.raises(Conflict,match="invalid_join_token"):s.token_info(raw(qr))
    assert s.token_info(raw(other))["number"]==8
    assert s.token_info(raw(nfc))["channel"]=="nfc"
    s.revoke_token(nfc["id"],ADMIN)
    s.revoke_token(nfc["id"],ADMIN)
    with pytest.raises(Conflict,match="invalid_join_token"):s.join_token(raw(nfc),USERS[0],"revoked")
    with pytest.raises(Conflict,match="admin_required"):s.issue_token(a["id"],data(channel="qr"),USERS[0])

@pytest.mark.parametrize("channel",["qr","nfc","universal"])
def test_shared_join_leave_idempotence_and_closed_tokens(setup,channel):
    s,_=setup;t=make(s);entry=token(s,t,channel,**({"purpose":"seat_join","seat":"east"} if channel=="qr" else {}))
    for _ in range(3):s.join_token(raw(entry),USERS[0],str(uuid4()))
    view=s.get(t["id"],USERS[0]);assert view["player_count"]==1
    assert view["members"][0]["join_method"]==("nfc" if channel=="nfc" else "qr_east" if channel=="qr" else "qr")
    other=make(s,8)
    with pytest.raises(Conflict,match="already_at_other_table"):s.join(other["id"],USERS[0])
    assert s.leave(t["id"],USERS[0])["changed"]
    assert not s.leave(t["id"],USERS[0])["changed"]
    assert s.get(t["id"],USERS[0])["player_count"]==0
    with s.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TableMembershipEvent))==2
    s.update(t["id"],{"status":"closed"},ADMIN)
    with pytest.raises(Conflict,match="table_closed"):s.join_token(raw(entry),USERS[0],"closed")
    s.join(other["id"],USERS[0])

def test_concurrent_membership_and_capacity(setup):
    s,_=setup;one,two=make(s,1),make(s,2)
    def join(t,u):
        try:s.join(t["id"],u);return True
        except Conflict:return False
    with ThreadPoolExecutor(2) as pool:out=list(pool.map(lambda t:join(t,USERS[0]),[one,two]))
    assert sum(out)==1
    active=next(t for t in (one,two) if s.get(t["id"],USERS[0])["player_count"])
    with ThreadPoolExecutor(8) as pool:out=list(pool.map(lambda u:join(active,u),USERS[1:9]))
    assert sum(out)==3
    assert s.get(active["id"],USERS[0])["started_at"]
    with pytest.raises(Conflict,match="cannot_leave_started"):s.leave(active["id"],USERS[0])
    with s.store.connect() as db:assert db.scalar(select(func.count()).select_from(ActiveTableMember))==4

def test_manual_ids_transaction_source_reset_preserves_history(setup):
    s,_=setup;t=make(s);s.join(t["id"],USERS[0])
    for ids,code in [(["unknown"],"account_not_found"),(["disabled"],"account_disabled"),([USERS[0].id],"cannot_add_self"),
                     ([USERS[1].id]*2,"duplicate_player_ids"),([p.id for p in USERS[1:5]],"table_full")]:
        with pytest.raises(Conflict,match=code):s.add_players(t["id"],data(user_ids=ids),USERS[0])
    others=make(s,10);s.join(others["id"],USERS[3])
    with pytest.raises(Conflict,match="already_at_other_table"):s.add_players(t["id"],data(user_ids=[USERS[1].id,USERS[3].id]),USERS[0])
    assert s.get(t["id"],USERS[0])["player_count"]==1
    preview=s.preview_players(t["id"],USERS[1].id+","+USERS[2].id,USERS[0])
    assert set(preview["players"][0])=={"id","name","avatar"}
    payload=data(user_ids=USERS[1].id+" \n"+USERS[2].id)
    s.add_players(t["id"],payload,USERS[0]);assert s.add_players(t["id"],payload,USERS[0])["replayed"]
    members=s.get(t["id"],USERS[0])["members"]
    assert all(m["join_method"]=="registered_name" and m["added_by_user_id"]==USERS[0].id for m in members if m["user_id"]!=USERS[0].id)
    s.add_players(t["id"],data(user_ids=[USERS[4].id]),ADMIN)
    with pytest.raises(Conflict,match="admin_required"):s.reset(t["id"],data(reason="bad"),USERS[0])
    oldmatch=s.get(t["id"],ADMIN)["current_match_id"]
    s.reset(t["id"],data(reason="Wrong roster"),ADMIN)
    fresh=s.get(t["id"],ADMIN);assert fresh["player_count"]==0 and fresh["current_match_id"]!=oldmatch
    with s.store.connect() as db:
        audit=db.scalar(select(TournamentAudit).where(TournamentAudit.action=="table_match_aborted"))
        snapshot=json.loads(audit.detail_json)["snapshot"]
        assert len(snapshot["roster"])==4 and snapshot["match_id"]==oldmatch
        assert db.scalar(select(func.count()).select_from(TableMembershipEvent).where(TableMembershipEvent.action=="left"))==4

def test_reservations_informational_owned_timezone_audited(setup):
    s,_=setup;t=make(s)
    body=data(scheduled_at="2026-09-20T18:00:00-07:00",note="Evening")
    reservation=s.reserve(t["id"],body,USERS[0])
    assert reservation["scheduled_at"].startswith("2026-09-21T01:00:00")
    assert "seat" not in reservation
    assert s.reserve(t["id"],body,USERS[0])["id"]==reservation["id"]
    assert s.get(t["id"],USERS[0])["player_count"]==0
    s.reserve(t["id"],data(scheduled_at=reservation["scheduled_at"]),USERS[1])
    s.join(t["id"],USERS[2])
    with pytest.raises(Conflict,match="reservation_not_owner"):s.update_reservation(reservation["id"],{"status":"cancelled"},USERS[2])
    assert len(s.list(ADMIN,True)["tables"][0]["reservations"])==2
    s.update_reservation(reservation["id"],{"note":"Changed","version":1},USERS[0])
    s.update_reservation(reservation["id"],{"status":"cancelled","version":2},USERS[0])
    s.update_reservation(reservation["id"],{"status":"cancelled","version":2},USERS[0])
    assert s.get(t["id"],USERS[0])["player_count"]==1
    with pytest.raises(Conflict):s.reserve(t["id"],data(scheduled_at="2026-09-20T18:00:00"),USERS[0])
    with pytest.raises(Conflict):s.reserve(t["id"],data(scheduled_at=reservation["scheduled_at"],seat="east"),USERS[0])
    with s.store.connect() as db:assert db.scalar(select(func.count()).select_from(TableReservation))==2

def test_tournament_removed_fields_and_noncontiguous_table_pairing(setup):
    s,_=setup;comp=s.tournaments
    st=comp.create(data(name="No units",settings={"raw_step":"garbage","divisor":0,"min_unit":False,"allow_guest_auto_enrollment":True}),ADMIN.id)
    tid=st["id"];assert not {"raw_step","divisor","min_unit"}&st["settings"].keys()
    for i in range(8):command(comp,tid,"player",name="Guest "+str(i))
    tables=[make(s,n,tid) for n in (3,8)]
    action(comp,tid,"start");state=action(comp,tid,"pair")
    assert [t["number"] for t in state["preview"]["tables"]]==[3,8]
    assert [t["table_id"] for t in state["preview"]["tables"]]==[t["id"] for t in tables]
    state=action(comp,tid,"confirm_seats");match=state["rounds"][0]["tables"][0]
    entry=token(s,tables[0],"nfc")
    s.join_token(raw(entry),User(id=match["seats"][0],name="Player"),"joined")
    s.update(tables[0]["id"],{"number":10},ADMIN)
    state=comp.get(tid)
    assert state["rounds"][0]["tables"][0]["display_number"]==10
    assert s.token_info(raw(entry))["number"]==10

@pytest.mark.parametrize("limit",[None,60])
def test_time_limit_start_snapshot_persists(setup,limit):
    s,_=setup;comp=s.tournaments;tid,t=waiting(comp,limit=limit)
    check_all(comp,tid,t);participate(comp,tid,t,"start_table")
    first=comp.get(tid)["rounds"][0]["tables"][0]["session"]
    assert (first["ends_at"] is None)==(limit is None)
    assert first["time_limit_seconds"]==limit
    action(comp,tid,"settings",settings={"time_limit_seconds":None if limit else 60})
    next_=comp.get(tid)["rounds"][0]["tables"][0]["session"]
    assert (first["started_at"],first["ends_at"],first["time_limit_seconds"])==(next_["started_at"],next_["ends_at"],next_["time_limit_seconds"])
    comp.clock=lambda:(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    assert comp.get(tid)["rounds"][0]["tables"][0]["session"]["status"]==("TIME_EXPIRED" if limit else "IN_PROGRESS")
    reopened=Store(s.store.path)
    try:
        with reopened.connect() as db:
            row=db.get(TournamentTableSession,t["match_id"]);assert row.ends_at==first["ends_at"]
    finally:reopened.close()

def test_soft_delete_keeps_results_reservations_audit_and_revokes_tokens(setup):
    s,_=setup;comp=s.tournaments;st=tournament(comp,4);tid=st["id"]
    command(comp,tid,"start");st=round_complete(comp,tid)
    table=s.list(ADMIN,True)["tables"][0]
    qr,nfc=token(s,table),token(s,table,"nfc")
    s.reserve(table["id"],data(scheduled_at="2026-10-01T12:00:00Z"),USERS[0])
    with s.store.connect() as db:
        before=json.loads(db.get(Tournament,tid).state_json)["rounds"]
    body=data(version=st["version"],confirm_name=st["name"],reason="Duplicate")
    with pytest.raises(Conflict,match="admin_required"):comp.soft_delete(tid,body,USERS[0])
    with pytest.raises(Conflict):comp.soft_delete(tid,{**body,"confirm_name":"bad"},ADMIN)
    result=comp.soft_delete(tid,body,ADMIN)
    assert comp.soft_delete(tid,body,ADMIN)==result
    assert not comp.list()
    with pytest.raises(Conflict,match="tournament_deleted"):comp.get(tid)
    for entry in (qr,nfc):
        with pytest.raises(Conflict):s.join_token(raw(entry),USERS[0],str(uuid4()))
    with s.store.connect() as db:
        row=db.get(Tournament,tid);assert row.deleted_by==ADMIN.id
        assert json.loads(row.state_json)["rounds"]==before
        assert db.scalar(select(func.count()).select_from(TableReservation))==1
        assert db.scalar(select(func.count()).select_from(TournamentAudit).where(TournamentAudit.action=="tournament_deleted"))==1

def test_api_admin_and_auth_boundary_qr_png_ndef_and_redaction(setup):
    s,app=setup;t=make(s);qr=token(s,t);nfc=token(s,t,"nfc")
    client=TestClient(app)
    if True:
        assert client.post("/api/table-join-tokens/"+raw(nfc)+"/join",json=data()).status_code==401
        app.dependency_overrides[get_current_user]=lambda:USERS[0]
        for path,body in [("/api/admin/club-tables",data(number=8)),("/api/admin/club-tables/"+t["id"]+"/tokens",data(channel="qr")),
                          ("/api/tournaments/fake/delete",data())]:
            assert client.post(path,json=body).status_code==403
        assert client.get("/api/admin/table-tokens/"+qr["id"]+"/qr.png").status_code==403
        app.dependency_overrides[get_current_user]=lambda:ADMIN
        png=client.get("/api/admin/table-tokens/"+qr["id"]+"/qr.png")
        assert png.status_code==200 and png.content.startswith(b"\x89PNG")
        from PIL import Image
        import io
        assert Image.open(io.BytesIO(png.content)).size[0]>=600
        ndef=client.get("/api/admin/table-tokens/"+nfc["id"]+"/ndef.json")
        assert ndef.json()["records"]==[{"recordType":"url","data":"http://testserver"+nfc["path"]}]
        assert "Table-3" in ndef.headers["content-disposition"]
        app.dependency_overrides[get_current_user]=lambda:USERS[0]
        response=client.post("/api/table-join-tokens/"+raw(nfc)+"/join",json=data())
        assert response.status_code==200 and response.json()["join_method"]=="nfc"
        assert client.get("/api/session").status_code==404 # never mint another user's session
    line='POST /api/table-join-tokens/'+raw(nfc)+'/join HTTP/1.1 200'
    assert raw(nfc) not in redact_table_token(line)
    assert redact_table_token(line).endswith('/join HTTP/1.1 200')


def test_migration_rebuilds_legacy_registry_and_members_once(setup):
    s,_=setup
    from sqlalchemy import delete
    from mahjong_api.migrations import migrate
    s.matches.sit("legacy-machine-8","east",USERS[0])
    with s.store.connect() as db:
        db.execute(delete(TableMembershipEvent));db.execute(delete(ActiveTableMember));db.execute(delete(ClubTable))
        db.execute(delete(Metadata).where(Metadata.key=="table_v3_migrated"))
        old_seats=[(r.table_id,r.seat,r.user_id) for r in db.scalars(select(SeatRecord))]
    migrate(s.store.engine);migrate(s.store.engine)
    with s.store.connect() as db:
        assert [(r.table_id,r.seat,r.user_id) for r in db.scalars(select(SeatRecord))]==old_seats
        assert db.scalar(select(func.count()).select_from(ClubTable))==1
        assert db.scalar(select(func.count()).select_from(TableMembershipEvent))==1
        assert db.scalar(select(ClubTable)).score_table_id=="legacy-machine-8"

def test_token_expiry_and_service_restart_keep_same_entry(setup):
    s,_=setup;t=make(s);end=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    entry=token(s,t,"nfc",expires_at=end)
    from mahjong_api.table_service import TableService
    again=TableService(s.matches,s.tournaments)
    assert again.get(t["id"],ADMIN,True)["tokens"][0]["path"]==entry["path"]
    again.clock=lambda:(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
    assert not again.get(t["id"],ADMIN,True)["tokens"][0]["valid"]
    with pytest.raises(Conflict,match="token_expired"):again.join_token(raw(entry),USERS[0],"expired")

def test_ordinary_and_tournament_membership_share_constraint(setup):
    s,_=setup;tid,t=waiting(s.tournaments)
    uid=t["seats"][0];person=User(id=uid,name="Assigned Player");ordinary=make(s,9)
    s.join(ordinary["id"],person)
    with pytest.raises(Conflict,match="already_at_other_table"):participate(s.tournaments,tid,t,"check_in",uid)
    s.leave(ordinary["id"],person);participate(s.tournaments,tid,t,"check_in",uid)
    with pytest.raises(Conflict,match="already_at_other_table"):s.join(ordinary["id"],person)

def test_db_unique_member_and_scoped_number_constraints(setup):
    s,_=setup;first,second=make(s,3),make(s,8);s.join(first["id"],USERS[0])
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        with s.store.connect() as db:
            db.add(ActiveTableMember(user_id=USERS[0].id,table_id=second["id"],match_id="other",joined_at=s.clock(),join_method="manual",added_by_user_id=USERS[0].id))
    assert s.get(first["id"],USERS[0])["player_count"]==1
    assert s.get(second["id"],USERS[0])["player_count"]==0

def test_legacy_time_values_canonical_and_new_settings_ignore_retired_fields():
    from mahjong_api.tournament_rules import settings_value
    for value in (0,"",None):
        assert settings_value({"time_limit_seconds":value})["time_limit_seconds"] is None
    for value in (-1,1.5,True,False):
        with pytest.raises(Conflict):settings_value({"time_limit_seconds":value})
    old={"divisor":2000,"raw_step":100,"min_unit":.5}
    result=settings_value({"divisor":1000},old)
    assert all(result[k]==v for k,v in old.items())

def test_closed_table_and_deleted_competition_block_all_join_methods(setup):
    s,_=setup;t=make(s);entry=token(s,t,"nfc");s.update(t["id"],{"status":"closed"},ADMIN)
    for call in [lambda:s.join(t["id"],USERS[0]),lambda:s.add_players(t["id"],data(user_ids=[USERS[1].id]),ADMIN),lambda:s.join_token(raw(entry),USERS[0],"closed-again")]:
        with pytest.raises(Conflict,match="table_closed"):call()
    assert not s.get(t["id"],ADMIN,True)["tokens"][0]["valid"]

def test_encoded_login_target_redaction_preserves_audit_metadata():
    from urllib.parse import quote
    value="GET /login?redirect_url="+quote("/join-table/syntheticSecretToken123456",safe="")+" HTTP/1.1"
    redacted=redact_table_token(value)
    assert "syntheticSecret" not in redacted
    assert redacted.startswith("GET /login?redirect_url=") and redacted.endswith(" HTTP/1.1")
