"""V9 logical sessions, range validation, durable migration and process races."""
import json
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from multiprocessing import Manager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from mahjong_api.auth import get_current_user
from mahjong_api.database_models import Metadata
from mahjong_api.reservation_session_models import ReservationSession
from mahjong_api.reservation_sessions import session_participants
from mahjong_api.reservation_reminders import reservation_reminders, get_next_whole_hour
from mahjong_api.store import Conflict, Store
from mahjong_api.table_models import ClubTable, TableReservation, ReservationParticipant
from test_table_v3 import setup, make, data, USERS, ADMIN

START="2026-09-21T01:00:00.000+00:00"


def stamp(minutes):
    return (datetime.fromisoformat(START)+timedelta(minutes=minutes)).isoformat(timespec="milliseconds")


def reserve(s,t,minutes=0,people=None,duration=60,user=None):
    return s.reserve(t["id"],data(start_at=stamp(minutes),end_at=stamp(minutes+duration),
        participant_ids=people if people is not None else [(user or USERS[0]).id]),user or USERS[0])


def sessions(s,t):
    return s.get(t["id"],USERS[0])["reservation_sessions"]


def test_default_range_uses_actual_next_hour_and_cross_year():
    result=get_next_whole_hour("2026-12-31T23:20:00-08:00","America/Los_Angeles")
    assert result["start_at"]=="2027-01-01T08:00:00.000+00:00"
    assert result["end_at"]=="2027-01-01T09:00:00.000+00:00"
    assert (result["end_local_month"],result["end_local_day"],result["end_local_time"])==(1,1,"01:00")


@pytest.mark.parametrize("minutes,same",[(20,True),(60,True),(61,False)])
def test_exact_bounded_start_span(setup,minutes,same):
    s,_=setup;t=make(s)
    a=reserve(s,t);b=reserve(s,t,minutes,user=USERS[1])
    assert (a["session_id"]==b["session_id"]) is same
    assert a["id"]!=b["id"] and a["user_id"]!=b["user_id"]
    assert b["start_at"]==stamp(minutes)


def test_chain_never_expands_past_one_hour_and_end_not_overlap_required(setup):
    s,_=setup;t=make(s)
    a=reserve(s,t,0,duration=10);b=reserve(s,t,50,duration=100);c=reserve(s,t,100)
    assert a["session_id"]==b["session_id"]!=c["session_id"]
    assert sessions(s,t)[0]["start_at"]==stamp(0)
    assert sessions(s,t)[0]["end_at"]==stamp(150)
    assert [r["start_at"] for r in sessions(s,t)[0]["reservations"]]==[stamp(0),stamp(50)]


def test_distinct_union_capacity_and_full_session_creates_another(setup):
    s,_=setup;t=make(s)
    a=reserve(s,t,people=[u.id for u in USERS[:3]])
    b=reserve(s,t,20,people=[USERS[2].id,USERS[3].id])
    c=reserve(s,t,30,user=USERS[4])
    assert a["session_id"]==b["session_id"]!=c["session_id"]
    assert sessions(s,t)[0]["participant_count"]==4
    assert len(sessions(s,t)[0]["participants"])==4
    assert len(s.get(t["id"],USERS[0])["reservations"])==3


def test_candidate_scope_ranking_capacity_and_manual_table_choice(setup):
    s,_=setup;a,b,c=make(s,1),make(s,2),make(s,3)
    first=reserve(s,a,0,people=[USERS[0].id,USERS[1].id])
    second=reserve(s,b,0,people=[USERS[2].id])
    reserve(s,c,0,people=[u.id for u in USERS[:4]])
    result=s.reservation_candidates(a["id"],{"start_at":stamp(20),"participant_ids":[USERS[4].id]},USERS[4])
    assert [r["id"] for r in result["candidates"]]==[second["session_id"],first["session_id"]]
    assert result["default_table_id"]==b["id"]
    assert result["default_end_at"]==stamp(80)
    manual=reserve(s,a,20,user=USERS[4])
    assert manual["table_id"]==a["id"] and manual["session_id"]==first["session_id"]
    with s.store.connect() as db:
        db.get(ClubTable,b["id"]).scope="venue:elsewhere"
        db.get(ReservationSession,second["session_id"]).scope="venue:elsewhere"
    isolated=s.reservation_candidates(a["id"],{"start_at":stamp(20),"participant_ids":[USERS[5].id]},USERS[5])
    assert all(row["table_id"]!=b["id"] for row in isolated["candidates"])


def test_candidate_ties_creation_then_stable_id(setup):
    s,_=setup;a,b=make(s,1),make(s,2)
    x=reserve(s,a);y=reserve(s,b)
    with s.store.connect() as db:
        db.get(ReservationSession,x["session_id"]).created_at="2020-01-01T00:00:00+00:00"
        db.get(ReservationSession,y["session_id"]).created_at="2021-01-01T00:00:00+00:00"
    query={"start_at":stamp(20),"participant_ids":[USERS[1].id]}
    assert s.reservation_candidates(a["id"],query,USERS[1])["default_session_id"]==x["session_id"]
    with s.store.connect() as db:
        db.get(ReservationSession,y["session_id"]).created_at="2020-01-01T00:00:00+00:00"
    assert s.reservation_candidates(a["id"],query,USERS[1])["default_session_id"]==min(x["session_id"],y["session_id"])


def test_edit_only_moves_changed_record_range_recalculates_and_cancel_retains_history(setup):
    s,_=setup;t=make(s)
    a=reserve(s,t,0);b=reserve(s,t,20,duration=180,user=USERS[1]);c=reserve(s,t,150,user=USERS[2])
    edited=s.update_reservation(b["id"],{"version":1,"start_at":stamp(40),"end_at":stamp(240)},USERS[1])
    assert edited["session_id"]==a["session_id"]
    assert edited["session"]["end_at"]==stamp(240)
    moved=s.update_reservation(b["id"],{"version":2,"start_at":stamp(180),"end_at":stamp(300)},USERS[1])
    assert moved["session_id"]==c["session_id"]
    assert sessions(s,t)[0]["end_at"]==stamp(60)
    s.update_reservation(a["id"],{"version":1,"status":"cancelled"},USERS[0])
    with s.store.connect() as db:
        assert db.get(ReservationSession,a["session_id"]).status=="cancelled"
        assert db.get(TableReservation,a["id"]).status=="cancelled"
        assert db.scalar(select(func.count()).select_from(TableReservation))==3
    with pytest.raises(Conflict,match="reservation_not_owner"):
        s.update_reservation(b["id"],{"version":3,"status":"cancelled"},USERS[0])


def test_manual_table_edit_preserves_other_records_and_ownership(setup):
    s,_=setup;a,b=make(s,1),make(s,2)
    first=reserve(s,a);other=reserve(s,a,20,user=USERS[1])
    moved=s.update_reservation(first["id"],{"version":1,"table_id":b["id"]},USERS[0])
    assert moved["table_id"]==b["id"] and moved["user_id"]==first["user_id"]
    assert moved["start_at"]==first["start_at"] and moved["end_at"]==first["end_at"]
    assert sessions(s,a)[0]["reservations"][0]["id"]==other["id"]


@pytest.mark.parametrize("end",[stamp(-1),stamp(0)])
def test_end_must_be_after_start_without_persisting_partial_rows(setup,end):
    s,_=setup;t=make(s)
    with pytest.raises(Conflict,match="invalid_reservation_end"):
        s.reserve(t["id"],data(start_at=START,end_at=end),USERS[0])
    assert not sessions(s,t)
    with pytest.raises(IntegrityError):
        with s.store.connect() as db:
            db.add(TableReservation(id="bad",table_id=t["id"],user_id=USERS[0].id,user_name="x",
                scheduled_at=START,end_at=end,created_at=START,updated_at=START,status="active"))


@pytest.mark.parametrize("now,start,end,expected",[
    ("2026-09-20T10:00:00-07:00",(9,20,"23:30"),(9,21,"01:00"),90),
    ("2026-09-20T10:00:00-07:00",(9,30,"23:30"),(10,1,"01:30"),120),
    ("2026-12-20T10:00:00-08:00",(12,31,"23:30"),(1,1,"01:30"),120),
    ("2028-02-20T10:00:00-08:00",(2,28,"23:30"),(2,29,"01:30"),120),
])
def test_yearless_fields_cross_midnight_month_year_leap(setup,now,start,end,expected):
    s,_=setup;t=make(s);s.clock=lambda:now
    row=s.reserve(t["id"],data(month=start[0],day=start[1],time=start[2],
        end_month=end[0],end_day=end[1],end_time=end[2]),USERS[0])
    assert (datetime.fromisoformat(row["end_at"])-datetime.fromisoformat(row["start_at"])).total_seconds()==expected*60
    assert row["start_at"].endswith("+00:00") and row["end_at"].endswith("+00:00")
    assert row["end_local_day"]==end[1]
    s.clock=lambda:"2040-01-01T00:00:00+00:00"
    unchanged=s.update_reservation(row["id"],{"version":1,"note":"same dates"},USERS[0])
    assert unchanged["start_at"]==row["start_at"] and unchanged["end_at"]==row["end_at"]


def test_no_arbitrary_max_duration_and_session_window_uses_actual_end(setup):
    s,_=setup;t=make(s)
    row=reserve(s,t,duration=60*24*20)
    s.clock=lambda:stamp(-60)
    assert reservation_reminders(s,t["id"],USERS[0])["reminders"][0]["id"]==row["session_id"]
    s.clock=lambda:stamp(60*24*20)
    assert reservation_reminders(s,t["id"],USERS[0])["reminders"]
    s.clock=lambda:stamp(60*24*20+.001)
    assert not reservation_reminders(s,t["id"],USERS[0])["reminders"]


def test_candidate_api_auth_validation_and_profiles(setup):
    s,app=setup;t=make(s);reserve(s,t)
    client=TestClient(app);path=f"/api/club-tables/{t['id']}/reservation-candidates"
    assert client.get(path).status_code==401
    app.dependency_overrides[get_current_user]=lambda:USERS[0]
    assert client.get(path,params={"month":"invalid","day":20,"time":"18:00"}).status_code==409
    response=client.get(path,params={"scheduled_at":stamp(10)})
    assert response.status_code==200 and response.json()["default_table_id"]==t["id"]


def test_grouping_failure_rolls_back_record_participants_session_and_version(setup,monkeypatch):
    s,_=setup;t=make(s);row=reserve(s,t)
    import mahjong_api.reservation_operations as operations
    real=operations.assign_session
    def fail(*args,**kwargs):
        real(*args,**kwargs)
        raise RuntimeError("after full assignment")
    monkeypatch.setattr(operations,"assign_session",fail)
    with pytest.raises(RuntimeError):
        reserve(s,t,180,user=USERS[1])
    with pytest.raises(RuntimeError):
        s.update_reservation(row["id"],{"version":1,"start_at":stamp(180),"end_at":stamp(240),
            "participant_ids":[USERS[1].id]},USERS[0])
    with s.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TableReservation))==1
        assert db.scalar(select(func.count()).select_from(ReservationSession))==1
        assert db.get(TableReservation,row["id"]).version==1
        assert db.get(TableReservation,row["id"]).scheduled_at==START
        assert session_participants(db,row["session_id"])[0]["user_id"]==USERS[0].id


def _process(args):
    from mahjong_api.config import Settings
    from mahjong_api.service import MatchService
    from mahjong_api.sheets import DisabledSheets
    from mahjong_api.table_service import TableService
    from mahjong_api.tournament import TournamentService
    from mahjong_api.models import User
    path,table,uid,operation,body,barrier=args
    store=Store(Path(path))
    try:
        matches=MatchService(store,DisabledSheets(),Settings(database_path=Path(path)))
        s=TableService(matches,TournamentService(store,matches.external),
            account_lookup=lambda ids:[{"id":u.id,"name":u.name} for u in USERS])
        user=User(id=uid,name=uid)
        barrier.wait(timeout=30)
        try:
            return s.reserve(table,body,user) if operation=="create" else s.update_reservation(table,body,user)
        except Conflict as error:
            return {"error":error.detail["code"]}
    finally:
        store.close()


def race(s,calls):
    with Manager() as manager:
        barrier=manager.Barrier(len(calls))
        args=[(str(s.store.path),table,user.id,op,body,barrier) for table,user,op,body in calls]
        with ProcessPoolExecutor(len(args)) as pool:
            return list(pool.map(_process,args))


def test_independent_process_creates_share_one_eligible_session(setup):
    s,_=setup;t=make(s)
    out=race(s,[(t["id"],USERS[i],"create",data(start_at=stamp(i*20))) for i in range(2)])
    assert out[0]["session_id"]==out[1]["session_id"]
    assert len(sessions(s,t))==1 and sessions(s,t)[0]["participant_count"]==2


def test_independent_process_capacity_race_never_oversells(setup):
    s,_=setup;t=make(s);reserve(s,t,people=[u.id for u in USERS[:3]])
    out=race(s,[(t["id"],USERS[i],"create",data(start_at=stamp(10))) for i in (3,4)])
    assert len(sessions(s,t))==2
    assert sorted(row["participant_count"] for row in sessions(s,t))==[1,4]
    assert out[0]["session_id"]!=out[1]["session_id"]


def test_independent_edit_join_and_cancel_recompute_latest_rows(setup):
    s,_=setup;t=make(s);first=reserve(s,t);second=reserve(s,t,20,user=USERS[1])
    out=race(s,[(first["id"],USERS[0],"edit",{"version":1,"start_at":stamp(120),"end_at":stamp(180)}),
                (t["id"],USERS[2],"create",data(start_at=stamp(30)))])
    assert all("error" not in row for row in out)
    assert sorted(len(row["reservations"]) for row in sessions(s,t))==[1,2]
    for session in sessions(s,t):
        starts=[datetime.fromisoformat(r["start_at"]) for r in session["reservations"]]
        assert (max(starts)-min(starts)).total_seconds()<=3600
        assert session["start_at"]==min(r["start_at"] for r in session["reservations"])
    out=race(s,[(second["id"],USERS[1],"edit",{"version":1,"status":"cancelled"}),
                (t["id"],USERS[3],"create",data(start_at=stamp(40)))])
    assert all("error" not in row for row in out)
    with s.store.connect() as db:
        assert all(USERS[1].id not in {p["user_id"] for p in session_participants(db,row.id)}
                   for row in db.scalars(select(ReservationSession).where(ReservationSession.status=="active")))


def test_real_old_schema_backfill_preserves_records_and_is_idempotent(setup,tmp_path):
    s,_=setup;t=make(s);reserve(s,t,people=[USERS[0].id,USERS[1].id]);reserve(s,t,20,user=USERS[2])
    target=tmp_path/"old-reservation-schema.sqlite3"
    columns="id,table_id,user_id,user_name,scheduled_at,created_at,status,note,cancelled_at,updated_at,version,updated_by,cancelled_by"
    with sqlite3.connect(s.store.path) as source,sqlite3.connect(target) as db:
        source.backup(db);db.execute("PRAGMA foreign_keys=OFF")
        before=db.execute("SELECT "+columns+" FROM table_reservations ORDER BY id").fetchall()
        people=db.execute("SELECT * FROM table_reservation_participants ORDER BY reservation_id,user_id").fetchall()
        db.execute("DROP TABLE table_reservations")
        db.execute("DROP TABLE reservation_sessions")
        db.execute("DROP TABLE reservation_scope_locks")
        db.execute("CREATE TABLE table_reservations (id VARCHAR(64) PRIMARY KEY,table_id VARCHAR(64) NOT NULL,user_id VARCHAR(128) NOT NULL,user_name VARCHAR(128) NOT NULL,scheduled_at VARCHAR(40) NOT NULL,created_at VARCHAR(40) NOT NULL,status VARCHAR(16) NOT NULL,note TEXT NOT NULL,cancelled_at VARCHAR(40),updated_at VARCHAR(40) NOT NULL,version INTEGER NOT NULL,updated_by VARCHAR(128),cancelled_by VARCHAR(128))")
        db.executemany("INSERT INTO table_reservations ("+columns+") VALUES ("+",".join("?" for _ in columns.split(","))+")",before)
        db.execute("DELETE FROM nfc_metadata WHERE key='reservation_sessions_v9_migrated'");db.commit()
    upgraded=Store(target)
    try:
        with upgraded.connect() as db:
            assert [tuple(r) for r in db.execute(text("SELECT "+columns+" FROM table_reservations ORDER BY id"))]==before
            assert [tuple(r) for r in db.execute(text("SELECT * FROM table_reservation_participants ORDER BY reservation_id,user_id"))]==people
            rows=list(db.scalars(select(TableReservation)))
            ids={r.id:r.session_id for r in rows}
            assert len(set(ids.values()))==1
            assert all((datetime.fromisoformat(r.end_at)-datetime.fromisoformat(r.scheduled_at)).total_seconds()==3600 for r in rows)
        from mahjong_api.migrations import migrate
        migrate(upgraded.engine)
        with upgraded.connect() as db:
            assert {r.id:r.session_id for r in db.scalars(select(TableReservation))}==ids
            assert db.get(Metadata,"reservation_sessions_v9_migrated")
    finally:
        upgraded.close()
