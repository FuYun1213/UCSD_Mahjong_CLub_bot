"""Guest identities stay scoped, permissionless, and atomic across interpreters."""
import copy
import json
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Manager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from mahjong_api.auth import get_current_user
from mahjong_api.database_models import Metadata
from mahjong_api.guest_migrations import migrate_guests
from mahjong_api.guest_models import GuestRecovery, TournamentParticipant
from mahjong_api.guest_routes import cookie
from mahjong_api.guest_service import GuestService, hashed
from mahjong_api.models import SEATS
from mahjong_api.store import Conflict, Store, now
from mahjong_api.table_models import ActiveTableMember, TableMembershipEvent
from mahjong_api.tournament_models import Tournament, TournamentAudit, TournamentCheckIn, TournamentTableSession
from test_table_v3 import setup, make, token, raw, ADMIN, USERS, data
from test_tournament import command
from test_tournament_v10 import guest_cup


def enroll(svc, tid, table, name="Visitor", seat="east", secret=None, **extra):
    return svc.join(tid, {"table_id":table["id"], "name":name, "seat":seat, **extra}, secret)


def running(setup):
    tables,app,state,table,svc=guest_cup(setup)
    for user in USERS[:4]:
        command(tables.tournaments,state["id"],"player",registered_user_id=user.id)
    command(tables.tournaments,state["id"],"start")
    return tables,app,state,table,svc


def counts(tables):
    with tables.store.connect() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in
                     (TournamentParticipant, ActiveTableMember, TournamentCheckIn, TableMembershipEvent))


def test_public_guest_context_has_authoritative_seats_and_no_credentials(setup):
    tables,app,state,table,svc=guest_cup(setup);tid=state["id"]
    joined,secret=enroll(svc,tid,table,seat="west")
    result=svc.context(tid,secret)
    seat=result["tables"][0]["seats"]["west"]
    assert seat=={**joined["participant"]}
    assert result["tables"][0]["seats"]["east"] is None
    assert result["current_membership"]=={"table_id":table["id"],"seat":"west"}
    assert result["participant"]["id"]==joined["participant"]["id"]
    text=json.dumps(result)
    assert all(value not in text for value in (secret,hashed(secret),"session_hash","session_expires_at","created_by","account_id"))
    assert svc.context(tid,None)["participant"] is None
    before=counts(tables)
    assert TestClient(app).get(f"/api/guest/tournaments/{tid}").status_code==200
    assert counts(tables)==before


def test_guest_cross_origin_cannot_bypass_with_unrelated_authorization(setup):
    tables,app,state,table,svc=guest_cup(setup);tid=state["id"]
    client=TestClient(app)
    response=client.post(f"/api/guest/tournaments/{tid}/join",json={"table_id":table["id"],"name":"CSRF"},
        headers={"Origin":"https://evil.invalid","Authorization":"Bearer irrelevant"})
    assert response.status_code==403
    assert counts(tables)==(0,0,0,0)


def test_cookie_has_no_admin_or_score_or_other_guest_permissions(setup):
    tables,app,state,table,svc=guest_cup(setup);tid=state["id"]
    first,secret=enroll(svc,tid,table)
    second,other=enroll(svc,tid,table,"Second","south")
    client=TestClient(app);client.cookies.set(cookie(tid),secret)
    for path,body in [(f"/api/tournaments/{tid}/actions",{"action":"guest_merge","data":{}}),
                      (f"/api/tournaments/{tid}/guest-seat",{"player_id":second["participant"]["id"]}),
                      (f"/api/tournaments/{tid}/guest-recovery",{"player_id":second["participant"]["id"]}),
                      (f"/api/tournaments/{tid}/manual-preview",{}),
                      ("/api/manual-score/preview",{})]:
        assert client.post(path,json=body).status_code==401
    assert client.get(f"/api/tournaments/{tid}/participants").status_code==401
    response=client.post(f"/api/guest/tournaments/{tid}/leave",json={"player_id":second["participant"]["id"],"role":"admin"})
    assert response.status_code==200
    with tables.store.connect() as db:
        assert db.get(ActiveTableMember,first["participant"]["id"]) is None
        assert db.get(ActiveTableMember,second["participant"]["id"]) is not None


def test_expired_cookie_does_not_recover_identity_by_name_and_scores_remain(setup):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    first,secret=enroll(svc,tid,table)
    with tables.store.connect() as db:
        db.get(TournamentParticipant,first["participant"]["id"]).session_expires_at="2000-01-01T00:00:00.000+00:00"
    assert svc.identity(tid,secret) is None
    with pytest.raises(Conflict,match="guest_name_taken"):
        enroll(svc,tid,table,secret=secret)
    assert len(tables.tournaments.get(tid)["players"])==1
    assert counts(tables)[:2]==(1,1)


def test_names_are_unique_per_competition_and_database_enforced(setup):
    tables,_,state,table,svc=guest_cup(setup)
    first,_=enroll(svc,state["id"],table,"  Visitor  ")
    other=tables.tournaments.create(data(name="Second",settings={"allow_guest_auto_enrollment":True}),ADMIN.id)
    t2=make(tables,3,other["id"])
    second,_=enroll(svc,other["id"],t2,"VISITOR")
    assert second["participant"]["id"]!=first["participant"]["id"]
    with pytest.raises(IntegrityError),tables.store.connect() as db:
        db.add(TournamentParticipant(id="guest-test-direct",tournament_id=state["id"],name="visitor",
            normalized_name="visitor",participant_type="guest",created_at=now(),created_by="test"))
        db.flush()


def test_recovery_rotation_is_scoped_one_use_and_audited(setup):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    joined,secret=enroll(svc,tid,table);pid=joined["participant"]["id"]
    first=svc.issue_recovery(tid,{"player_id":pid,"reason":"Verified in person"},ADMIN)
    second=svc.issue_recovery(tid,{"player_id":pid,"reason":"Replace missing link"},ADMIN)
    with pytest.raises(Conflict,match="invalid_recovery"):svc.recover(tid,first)
    with pytest.raises(Conflict,match="invalid_recovery"):svc.recover("other-tournament",second)
    replacement=svc.recover(tid,second)
    assert svc.identity(tid,secret) is None
    assert svc.identity(tid,replacement)["id"]==pid
    with pytest.raises(Conflict,match="invalid_recovery"):svc.recover(tid,second)
    with tables.store.connect() as db:
        text=" ".join(db.scalars(select(TournamentAudit.detail_json)))
        assert all(token not in text for token in (secret,first,second,replacement))
        assert db.scalar(select(func.count()).select_from(GuestRecovery).where(GuestRecovery.used_at.is_(None)))==0


def test_recovery_failures_roll_back_claim_and_existing_session(setup,monkeypatch):
    import mahjong_api.guest_service as module
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    joined,secret=enroll(svc,tid,table)
    recovery=svc.issue_recovery(tid,{"player_id":joined["participant"]["id"],"reason":"Verified"},ADMIN)
    def fail(*args,**kwargs):raise RuntimeError("audit unavailable")
    monkeypatch.setattr(module,"audit",fail)
    with pytest.raises(RuntimeError):svc.recover(tid,recovery)
    assert svc.identity(tid,secret)["id"]==joined["participant"]["id"]
    with tables.store.connect() as db:assert db.get(GuestRecovery,hashed(recovery)).used_at is None


def test_failed_join_rolls_back_roster_guest_member_checkin_and_audit(setup,monkeypatch):
    import mahjong_api.guest_service as module
    tables,_,state,table,svc=running(setup);tid=state["id"]
    before=tables.tournaments.get(tid)
    def fail(*args,**kwargs):raise RuntimeError("commit preparation failed")
    monkeypatch.setattr(module,"mutate_state",fail)
    with pytest.raises(RuntimeError):enroll(svc,tid,table)
    assert counts(tables)==(0,0,0,0)
    after=tables.tournaments.get(tid)
    assert after["players"]==before["players"] and after["rounds"]==before["rounds"] and after["audit"]==before["audit"]


def test_leave_releases_draft_slot_and_promotion_uses_real_round(setup):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    first,secret=enroll(svc,tid,table)
    svc.leave(tid,secret)
    assert svc.context(tid,secret)["tables"][0]["seats"]["east"] is None
    second,_=enroll(svc,tid,table,"Replacement")
    enroll(svc,tid,table,seat="south",secret=secret)
    for user in USERS[:2]:command(tables.tournaments,tid,"player",registered_user_id=user.id)
    command(tables.tournaments,tid,"start")
    repeat,_=enroll(svc,tid,table,seat="south",secret=secret)
    assert repeat["participant"]["id"]==first["participant"]["id"]
    with tables.store.connect() as db:
        member=db.get(ActiveTableMember,first["participant"]["id"])
        session=db.get(TournamentTableSession,member.match_id)
        assert session.round_id!="enrollment" and json.loads(session.roster_json)[1]==member.user_id
        assert db.scalar(select(func.count()).select_from(TournamentCheckIn).where(TournamentCheckIn.player_id==member.user_id))==1


@pytest.mark.parametrize("channel,purpose,seat,method",[("qr","table_landing",None,"qr_entry"),("qr","seat_join","west","qr_west"),("nfc","table_join",None,"nfc")])
def test_guest_tokens_keep_context_bound_wind_and_join_source(setup,channel,purpose,seat,method):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    entry=raw(token(tables,table,channel,purpose=purpose,seat=seat))
    joined,_=enroll(svc,tid,table,seat=seat or "east",entry_token=entry)
    with tables.store.connect() as db:assert db.get(ActiveTableMember,joined["participant"]["id"]).join_method==method
    another=make(tables,4,tid)
    before=counts(tables)
    with pytest.raises(Conflict,match="invalid_join_token"):
        enroll(svc,tid,another,"Wrong context",entry_token=entry)
    assert counts(tables)==before


def test_partial_roster_reserved_seats_are_not_publicly_shown_empty(setup):
    tables,_,state,table,svc=running(setup);tid=state["id"]
    joined,secret=enroll(svc,tid,table,seat="west")
    svc.leave(tid,secret)
    assert svc.context(tid,None)["tables"][0]["seats"]["west"]["id"]==joined["participant"]["id"]
    with pytest.raises(Conflict,match="seat_occupied"):
        enroll(svc,tid,table,"Another",seat="west")
    assert counts(tables)[:2]==(1,0)


def _process(args):
    from mahjong_api.config import Settings
    from mahjong_api.service import MatchService
    from mahjong_api.sheets import DisabledSheets
    from mahjong_api.table_service import TableService
    from mahjong_api.tournament import TournamentService
    path,tid,op,body,secret,barrier=args
    settings=Settings(database_path=Path(path));store=Store(settings.database_path)
    try:
        matches=MatchService(store,DisabledSheets(),settings)
        tables=TableService(matches,TournamentService(store,matches.external),
            account_lookup=lambda ids:[{"id":u.id,"name":u.name} for u in USERS+[ADMIN] if ids is None or u.id in ids])
        service=GuestService(tables.tournaments,tables)
        barrier.wait(timeout=30)
        try:
            if op=="join":result=service.join(tid,body,secret)[0]
            elif op=="recover":result={"token":service.recover(tid,secret)}
            elif op=="leave":result=service.leave(tid,secret)
            elif op=="start":result=tables.tournaments.participant_action(tid,body["match_id"],"start_table",ADMIN,str(uuid4()))
            elif op=="registered":result=tables.join_token(body["entry_token"],USERS[0],str(uuid4()))
            return {"ok":True,"result":result}
        except Conflict as exc:return {"error":exc.detail["code"]}
    finally:store.close()


def race(tables,tid,calls):
    with Manager() as manager:
        barrier=manager.Barrier(len(calls))
        args=[(str(tables.store.path),tid,op,body,secret,barrier) for op,body,secret in calls]
        with ProcessPoolExecutor(len(args)) as pool:return list(pool.map(_process,args))


def test_separate_processes_recovery_consumes_once(setup):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    joined,secret=enroll(svc,tid,table)
    link=svc.issue_recovery(tid,{"player_id":joined["participant"]["id"],"reason":"Verified"},ADMIN)
    results=race(tables,tid,[("recover",{},link)]*2)
    assert sum(r.get("ok",False) for r in results)==1
    assert [r["error"] for r in results if "error" in r]==["invalid_recovery"]
    new=next(r["result"]["token"] for r in results if r.get("ok"))
    assert svc.identity(tid,secret) is None and svc.identity(tid,new)["id"]==joined["participant"]["id"]


@pytest.mark.parametrize("same_name",[True,False])
def test_separate_processes_name_and_empty_seat_claim_are_atomic(setup,same_name):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    calls=[("join",{"table_id":table["id"],"seat":"east","name":"Name" if same_name else f"Name {i}"},None) for i in range(2)]
    results=race(tables,tid,calls)
    assert sum(r.get("ok",False) for r in results)==1
    assert [r["error"] for r in results if "error" in r]==["guest_name_taken" if same_name else "seat_occupied"]
    assert counts(tables)==(1,1,0,1)
    assert len(tables.tournaments.get(tid)["players"])==1


def test_separate_processes_same_guest_cannot_move_between_tables(setup):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    joined,secret=enroll(svc,tid,table);svc.leave(tid,secret)
    second=make(tables,4,tid)
    results=race(tables,tid,[("join",{"table_id":t["id"],"seat":"east"},secret) for t in (table,second)])
    assert sum(r.get("ok",False) for r in results)==1
    assert [r["error"] for r in results if "error" in r]==["already_at_other_table"]
    assert counts(tables)[:2]==(1,1)


def test_separate_processes_leave_and_start_cannot_produce_started_incomplete_table(setup):
    tables,_,state,table,svc=running(setup);tid=state["id"]
    people=[enroll(svc,tid,table,f"Guest {i}",seat) for i,seat in enumerate(SEATS)]
    mid=tables.tournaments.get(tid)["rounds"][-1]["tables"][0]["match_id"]
    results=race(tables,tid,[("start",{"match_id":mid},None),("leave",{},people[0][1])])
    assert sum(r.get("ok",False) for r in results)==1
    with tables.store.connect() as db:
        session=db.get(TournamentTableSession,mid)
        count=db.scalar(select(func.count()).select_from(ActiveTableMember).where(ActiveTableMember.match_id==mid))
        assert (session.started_at is not None and count==4) or (session.started_at is None and count==3)
    assert next(r["error"] for r in results if "error" in r) in {"already_started","check_in_incomplete"}


def test_registered_and_guest_processes_share_table_lock_without_overwriting(setup):
    tables,_,state,table,svc=running(setup);tid=state["id"]
    enroll(svc,tid,table,"Existing",seat="south")
    with tables.store.connect() as db:
        row=db.get(Tournament,tid);saved=json.loads(row.state_json)
        group=saved["rounds"][-1]["tables"][0];group["seats"][0]=USERS[0].id
        db.get(TournamentTableSession,group["match_id"]).roster_json=json.dumps(group["seats"])
        row.state_json=json.dumps(saved)
    entry=raw(token(tables,table,"qr",purpose="seat_join",seat="east"))
    results=race(tables,tid,[("registered",{"entry_token":entry},None),
        ("join",{"table_id":table["id"],"name":"Another","seat":"west"},None)])
    assert all(r.get("ok") for r in results),results
    with tables.store.connect() as db:
        members=list(db.scalars(select(ActiveTableMember).where(ActiveTableMember.table_id==table["id"])))
        assert len(members)==3 and {m.seat for m in members}=={"east","south","west"}
        assert db.get(ActiveTableMember,USERS[0].id).seat=="east"


def test_old_database_guest_backfill_preserves_results_and_is_idempotent(setup,tmp_path):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    for i in range(4):state=command(tables.tournaments,tid,"guest_add",name=f"Legacy {i}")
    ids=[p["id"] for p in state["players"]]
    state=command(tables.tournaments,tid,"manual_game",players=ids,scores=dict(zip(ids,[40000,30000,20000,10000])))
    target=tmp_path/"v9.sqlite3"
    with sqlite3.connect(tables.store.path) as source,sqlite3.connect(target) as old:
        source.backup(old)
        row=old.execute("SELECT state_json,version FROM tournaments WHERE id=?",(tid,)).fetchone()
        legacy=json.loads(row[0]);legacy["settings"].pop("allow_guest_auto_enrollment")
        for player in legacy["players"]:player.pop("participant_type")
        old.execute("UPDATE tournaments SET state_json=? WHERE id=?",(json.dumps(legacy),tid))
        old.execute("DROP TABLE tournament_guest_recovery");old.execute("DROP TABLE tournament_participants")
        old.execute("DELETE FROM nfc_metadata WHERE key='registration_tournament_v10'");old.commit()
        audit_before=old.execute("SELECT * FROM tournament_audit ORDER BY id").fetchall()
    upgraded=Store(target)
    try:
        with upgraded.connect() as db:
            row=db.get(Tournament,tid);saved=json.loads(row.state_json)
            assert saved["rounds"]==legacy["rounds"] and row.version==state["version"]
            assert saved["settings"]["allow_guest_auto_enrollment"] is False
            assert db.scalar(select(func.count()).select_from(TournamentParticipant))==4
            assert all(p.session_hash is None for p in db.scalars(select(TournamentParticipant)))
            once=row.state_json
        migrate_guests(upgraded.engine)
        with upgraded.connect() as db:assert db.get(Tournament,tid).state_json==once
        with sqlite3.connect(target) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall()==[]
            assert connection.execute("SELECT * FROM tournament_audit ORDER BY id").fetchall()==audit_before
    finally:upgraded.close()


def test_migration_duplicate_legacy_names_rolls_back_without_losing_history(setup):
    tables,_=setup
    state=tables.tournaments.create(data(name="Legacy"),ADMIN.id);tid=state["id"]
    with tables.store.connect() as db:
        row=db.get(Tournament,tid);saved=json.loads(row.state_json)
        saved["players"]=[{"id":"guest-one","name":"Same"},{"id":"guest-two","name":"SAME"}]
        row.state_json=json.dumps(saved);db.execute(delete(Metadata).where(Metadata.key=="registration_tournament_v10"))
        before=row.state_json
    with pytest.raises(IntegrityError):migrate_guests(tables.store.engine)
    with tables.store.connect() as db:
        assert db.get(Tournament,tid).state_json==before
        assert db.scalar(select(func.count()).select_from(TournamentParticipant))==0
        assert db.get(Metadata,"registration_tournament_v10") is None
        saved["players"][1]["name"]="Different";db.get(Tournament,tid).state_json=json.dumps(saved)
    migrate_guests(tables.store.engine)
    with tables.store.connect() as db:assert db.get(Metadata,"registration_tournament_v10").value=="1"


def test_merge_preserves_stable_results_audit_and_projects_current_registered_avatar(setup):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    first,secret=enroll(svc,tid,table);pid=first["participant"]["id"]
    svc.leave(tid,secret)
    for i in range(3):state=command(tables.tournaments,tid,"guest_add",name=f"Other {i}")
    ids=[p["id"] for p in state["players"]]
    state=command(tables.tournaments,tid,"manual_game",players=ids,scores=dict(zip(ids,[40000,30000,20000,10000])))
    historical=copy.deepcopy(state["rounds"])
    before={p["id"]:p["score"] for p in state["standings"]}
    recovery=svc.issue_recovery(tid,{"player_id":pid,"reason":"Verified before merge"},ADMIN)
    state=command(tables.tournaments,tid,"guest_merge",player_id=pid,account_id=USERS[0].id,reason="Verified owner")
    assert state["rounds"]==historical
    assert {p["id"]:p["score"] for p in state["standings"]}==before
    merged=next(p for p in state["players"] if p["id"]==pid)
    assert merged["participant_type"]=="registered_user" and merged["account_id"]==USERS[0].id
    assert svc.identity(tid,secret) is None
    with pytest.raises(Conflict,match="invalid_recovery"):svc.recover(tid,recovery)
    assert any(a["action"]=="guest_enrolled" for a in state["audit"])
    merge=next(a for a in state["audit"] if a["action"]=="guest_merge")
    assert merge["actor_id"]==ADMIN.id and merge["detail"]["before"]["id"]==merge["detail"]["after"]["id"]==pid
    # Projection follows the account relation even after a later avatar/name change.
    from mahjong_api.registered_display import with_registered_names
    profile={"id":USERS[0].id,"name":"Current Registered","avatar":"/uploads/current.png"}
    projected=with_registered_names(state,[profile])
    ranked=next(p for p in projected["standings"] if p["id"]==pid)
    assert (ranked["name"],ranked["avatar"],ranked["account_id"])==(profile["name"],profile["avatar"],profile["id"])
    assert next(p for p in projected["standings"] if p["id"]!=pid)["avatar"]==""
    # Future competition senders can resolve the formal binding using this
    # preserved account_id; no competition notification scheduler is invented.
    from mahjong_api.discord_reminder_sender import build_message
    directory={profile["id"]:{**profile,"discord_id":"123456789012345678"}}
    resolved=directory[ranked["account_id"]]
    message=build_message(table_number=3,start_at="2026-09-20T12:00:00+00:00",end_at="2026-09-20T13:00:00+00:00",
        participants=[resolved],nonce="merged-preview",capacity=4)
    assert message["allowed_mentions"]["users"]==[resolved["discord_id"]]


def test_guest_message_cannot_create_mentions_and_default_avatar_is_empty(setup):
    from mahjong_api.discord_reminder_sender import build_message
    tables,_,state,table,svc=guest_cup(setup)
    result,_=enroll(svc,state["id"],table,"Visitor <@123456789012345678> @everyone")
    guest=result["participant"]
    assert guest["participant_type"]=="guest" and guest["avatar"]=="" and "discord_id" not in guest
    message=build_message(table_number=3,start_at="2026-09-20T12:00:00+00:00",end_at="2026-09-20T13:00:00+00:00",
        participants=[guest],nonce="guest-preview",capacity=4)
    assert message["allowed_mentions"]=={"parse":[],"users":[],"roles":[],"replied_user":False}
    assert "Visitor" in message["content"] and "<@" not in message["content"] and "@everyone" not in message["content"]


def test_merge_is_rejected_during_live_session_even_if_member_was_removed(setup):
    from mahjong_api.table_membership import release_member
    tables,_,state,table,svc=running(setup);tid=state["id"]
    joined,_=enroll(svc,tid,table);pid=joined["participant"]["id"]
    with tables.store.connect() as db:
        member=db.get(ActiveTableMember,pid)
        db.get(TournamentTableSession,member.match_id).started_at=now()
        release_member(db,member,ADMIN.id,"administrative_closure")
    with pytest.raises(Conflict,match="identity_frozen"):
        command(tables.tournaments,tid,"guest_merge",player_id=pid,account_id=USERS[4].id,reason="Verified")


def test_legacy_larger_table_keeps_non_wind_slots_compatible(setup):
    tables,_=setup
    state=tables.tournaments.create(data(name="Five players",settings={"scoring_mode":"legacy","table_size":5,
        "uma":[0,0,0,0,0],"allow_guest_auto_enrollment":True}),ADMIN.id)
    table=make(tables,3,state["id"]);svc=GuestService(tables.tournaments,tables)
    results=[svc.join(state["id"],{"table_id":table["id"],"name":f"Guest {i}"},None)[0] for i in range(5)]
    assert [r["seat"] for r in results]==[*SEATS,None]
    assert counts(tables)[:2]==(5,5)
    with pytest.raises(Conflict,match="seat_occupied"):
        svc.join(state["id"],{"table_id":table["id"],"name":"Sixth"},None)
    assert counts(tables)[:2]==(5,5)


def test_join_rejects_revoked_entry_and_stale_match_without_orphan_guest(setup):
    tables,_,state,table,svc=guest_cup(setup);tid=state["id"]
    entry=token(tables,table,"nfc");tables.revoke_token(entry["id"],ADMIN)
    with pytest.raises(Conflict,match="invalid_join_token"):enroll(svc,tid,table,entry_token=raw(entry))
    with pytest.raises(Conflict,match="stale_match"):enroll(svc,tid,table,match_id="stale-session")
    assert counts(tables)==(0,0,0,0) and tables.tournaments.get(tid)["players"]==[]


def _migrate_process(args):
    from sqlalchemy import create_engine
    path,barrier=args
    engine=create_engine("sqlite:///"+Path(path).as_posix(),connect_args={"timeout":30})
    try:
        barrier.wait(timeout=30)
        migrate_guests(engine)
        return "ok"
    finally:engine.dispose()


def test_two_processes_migrate_old_guest_rows_once(setup):
    tables,_=setup
    state=tables.tournaments.create(data(name="Legacy"),ADMIN.id);tid=state["id"]
    with tables.store.connect() as db:
        row=db.get(Tournament,tid);saved=json.loads(row.state_json)
        saved["players"]=[{"id":"guest-one","name":"One"},{"id":"guest-two","name":"Two"}]
        row.state_json=json.dumps(saved);db.execute(delete(Metadata).where(Metadata.key=="registration_tournament_v10"))
    with Manager() as manager:
        barrier=manager.Barrier(2)
        with ProcessPoolExecutor(2) as pool:
            assert list(pool.map(_migrate_process,[(str(tables.store.path),barrier)]*2))==["ok","ok"]
    with tables.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TournamentParticipant))==2
        assert db.get(Metadata,"registration_tournament_v10").value=="1"


def test_finished_session_is_available_for_next_guest_round_in_context(setup):
    tables,_,state,table,svc=running(setup);tid=state["id"]
    people=[enroll(svc,tid,table,f"Guest {i}",seat) for i,seat in enumerate(SEATS)]
    ids=[person[0]["participant"]["id"] for person in people]
    group=tables.tournaments.get(tid)["rounds"][-1]["tables"][0]
    tables.tournaments.participant_action(tid,group["match_id"],"start_table",ADMIN,str(uuid4()))
    command(tables.tournaments,tid,"score_table",table=table["number"],scores=dict(zip(ids,[40000,30000,20000,10000])))
    command(tables.tournaments,tid,"confirm_round")
    context=svc.context(tid,people[0][1])["tables"][0]
    assert context["started_at"] is None and all(p is None for p in context["seats"].values())
    rejoined,_=enroll(svc,tid,table,secret=people[0][1])
    assert rejoined["participant"]["id"]==ids[0]
