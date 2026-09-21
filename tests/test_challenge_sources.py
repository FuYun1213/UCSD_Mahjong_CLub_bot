from contextlib import closing
import json
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
import pytest

import mahjong_store
from competition_service import CompetitionService,SLUG
from mahjong_api.store import Store
from mahjong_api.tournament_models import Tournament,TournamentTableSession
from mahjong_api.guest_models import TournamentParticipant
from mahjong_api.database_models import TableState
from mahjong_api.models import SEATS
from test_placement_challenge import api,game,board
from test_manual_score import manual,preview,confirm,PLAYERS,POINTS,AUTH
from test_mahjong_api import settings,setup,fill,submit


def service_for(club,nfc,folder,players):
    folder.mkdir(exist_ok=True)
    accounts=folder/"accounts.json"
    accounts.write_text(json.dumps({"users":{p["name"]:{"name":p["name"],"account_id":p["id"]} for p in players}}),encoding="utf-8")
    with closing(mahjong_store.connect(club)):pass
    svc=CompetitionService(club,nfc,accounts,folder/"images");svc.seed();return svc


def test_real_manual_late_confirmation_and_projection_once(manual,tmp_path):
    client,app,club,accounts=manual
    result=preview(client,played_at="2026-09-25T23:59:59").json()
    with app.state.service.store.connect() as db:
        from mahjong_api.manual_score_models import ManualScoreDraft
        draft=db.scalar(select(ManualScoreDraft).where(ManualScoreDraft.id==result["draft_id"]))
        draft.created_at="2026-09-26T22:00:00+00:00"
    response=confirm(client,result);assert response.status_code==200,response.text
    assert response.json()["result"]["authoritative_played_at"]=="2026-09-26T06:59:59+00:00"
    svc=service_for(club,tmp_path/"api.sqlite3",tmp_path/"competition",accounts)
    rows=board(svc);assert [r["total"] for r in rows]==[7,5,3,2] and all(r["games"]==1 for r in rows)
    with closing(svc.db()) as db:assert db.execute("SELECT count(*) FROM competition_games").fetchone()[0]==1


def test_manual_time_is_in_idempotency_fingerprint(manual):
    client,app,club,accounts=manual
    body={"players":PLAYERS,"scores":POINTS,"request_id":str(uuid4()),"played_at":"2026-09-25T20:00:00"}
    response=client.post("/api/manual-score/upload",json=body,headers=AUTH);assert response.status_code==200
    changed=client.post("/api/manual-score/upload",json={**body,"played_at":"2026-09-26T20:00:00"},headers=AUTH)
    assert changed.status_code==409


def test_legacy_manual_without_event_time_not_silently_counted(manual,tmp_path):
    client,app,club,accounts=manual
    result=preview(client).json();confirm(client,result)
    svc=service_for(club,tmp_path/"api.sqlite3",tmp_path/"competition",accounts)
    assert board(svc)==[]


def test_photo_confirmation_uses_table_start_not_upload(setup,tmp_path):
    client,sheets,service=setup
    match=fill(client)
    with service.store.connect() as db:
        table=db.scalar(select(TableState).where(TableState.table_id=="1"));table.started_at="2026-09-26T06:59:59+00:00"
    result=submit(client,match_id=match).json()["result"]
    assert result["authoritative_played_at"]=="2026-09-26T06:59:59+00:00"
    svc=service_for(tmp_path/"club.sqlite3",tmp_path/"test.sqlite3",tmp_path/"competition",[p["user"] for p in result["players"].values()])
    assert [r["total"] for r in board(svc)]==[7,5,3,2]
    # The same match later arrives in the club ledger: still one game.
    from mahjong_api.club_history import ClubHistorySink
    from mahjong_api.sheets import DisabledSheets
    ClubHistorySink(DisabledSheets(),svc.club_path)._save_game({"match_id":match,"result":result})
    assert all(r["games"]==1 for r in board(svc))
    with closing(mahjong_store.connect(svc.club_path)) as db:
        gid=db.execute("SELECT id FROM games WHERE nfc_match_id=?",(match,)).fetchone()[0]
        mahjong_store.revert_game(db,gid)
    assert board(svc)==[]  # The retained NFC snapshot cannot resurrect deletion.


def tournament_result(api,guest_id="guest-one",tid="cup-one",name="Visitor"):
    store=Store(api.nfc_path)
    match="match-"+tid
    people=[{"id":guest_id,"name":name,"placement":1},*[{"id":"account-"+n,"name":n,"placement":i+2} for i,n in enumerate("BCD")]]
    state={"id":tid,"schema_version":2,"settings":{"allow_guest_auto_enrollment":True},"status":"running","players":[{"id":p["id"],"name":p["name"],"participant_type":"guest" if p["id"]==guest_id else "registered"} for p in people],"rounds":[{"id":"r1","status":"confirmed","tables":[{"match_id":match,"result":{"players":people}}]}]}
    with store.connect() as db:
        db.add(Tournament(id=tid,state_json=json.dumps(state)))
        db.flush()
        db.add(TournamentParticipant(id=guest_id,tournament_id=tid,name=name,normalized_name=name.lower(),created_at="2026-09-21T07:00:00+00:00",created_by="admin",participant_type="guest"))
        db.add(TournamentTableSession(id=match,tournament_id=tid,round_id="r1",table_id="table-"+tid,number=1,roster_json=json.dumps([p["id"] for p in people]),status="COMPLETED",started_at="2026-09-22T07:00:00+00:00"))
    store.close()
    return tid


def test_guest_lazy_enrollment_merge_has_one_total(api):
    game(api);tournament_result(api)
    assert len(board(api))==5
    store=Store(api.nfc_path)
    with store.connect() as db:
        p=db.get(TournamentParticipant,"guest-one");p.merged_into_user_id="account-A";p.merged_at="2026-09-23T07:00:00+00:00";p.merged_by="admin"
    store.close();rows=board(api)
    assert len(rows)==4 and next(r for r in rows if r["name"]=="A")["total"]==14
    before=rows;api.sync(rebuild=SLUG);assert api.view(SLUG)["leaderboard"]==before


def test_scoped_guests_with_same_name_remain_distinct(api):
    tournament_result(api);tournament_result(api,"guest-two","cup-two")
    guests=[r for r in board(api) if r["type"]=="guest"]
    assert len(guests)==2 and all(p["total"]==7 for p in guests)


@pytest.mark.parametrize("flag",["is_test","void","cancelled","duplicate_of"])
def test_tournament_flags_invalidate_game(api,flag):
    tid=tournament_result(api)
    with closing(__import__('sqlite3').connect(api.nfc_path)) as db,db:
        state=json.loads(db.execute("SELECT state_json FROM tournaments WHERE id=?",(tid,)).fetchone()[0]);state["rounds"][0]["tables"][0][flag]=True
        db.execute("UPDATE tournaments SET state_json=? WHERE id=?",(json.dumps(state),tid))
    assert board(api)==[]
