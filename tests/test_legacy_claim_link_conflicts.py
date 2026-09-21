"""Approved legacy claims must never overwrite an existing account binding."""
from contextlib import closing
import copy
import json

import pytest
from sqlalchemy import event, select, text

import account_legacy_links as links
import account_registration as registration
import registered_names as names
import web_server as web
from mahjong_api.database_models import User as ScoreUser
from mahjong_api.store import Store, now
from mahjong_api.table_models import ActiveTableMember, ClubTable
from mahjong_api.tournament_models import Tournament, TournamentAudit, TournamentTableSession
from mahjong_api.tournament_rules import settings_value
from test_registered_names import directory, account
from test_registration_v10 import form, legacy


@pytest.fixture
def linked_history(directory, tmp_path, monkeypatch):
    path,_=directory
    player=legacy(web)
    score_path=tmp_path/"legacy-scores.sqlite3"
    monkeypatch.delenv("NFC_DATABASE_URL",raising=False)
    monkeypatch.setenv("NFC_DATABASE_PATH",str(score_path))
    store=Store(score_path)
    uid="old-nfc-id"
    aliases=[uid,"club-"+str(player["id"])]
    with store.connect() as db:
        db.add(ScoreUser(id=uid,name=player["name"]))
        for index,pid in enumerate(aliases):
            tid="history-"+str(index)
            state={"id":tid,"schema_version":3,"name":"History","settings":settings_value({}),
                "status":"registration","players":[{"id":pid,"name":player["name"]}],
                "rounds":[{"status":"confirmed","tables":[{"result":{"immutable_history":True,"player_id":pid}}]}],
                "preview":None,"finals":None}
            db.add(Tournament(id=tid,version=1,state_json=json.dumps(state)))
        db.flush()
        db.add(ClubTable(id="history-table",scope="tournament:history-0",tournament_id="history-0",number=1,
            display_name="Original Table",status="open",capacity=4,created_at=now(),created_by="admin"))
        db.flush()
        db.add(TournamentTableSession(id="history-match",tournament_id="history-0",round_id="legacy-round",
            table_id="history-table",number=1,roster_json=json.dumps([uid]),status="IN_PROGRESS"))
        db.add(ActiveTableMember(user_id=uid,table_id="history-table",match_id="history-match",seat="east",
            joined_at=now(),join_method="manual",added_by_user_id=uid))
    claim={"id":"approved-claim","legacy_player_id":player["id"],"account_id":uid,
           "registered_name":"Old Player","reviewed_by":"admin"}
    try:yield store,claim,path,player
    finally:store.close()


def snapshot(store):
    with store.connect() as db:
        return {table:[tuple(row) for row in db.execute(text("SELECT * FROM "+table))] for table in
            ("nfc_users","tournaments","tournament_audit","tournament_table_sessions","active_table_members")}


def conflict(store,tid="history-1",bound="different-bound-account"):
    with store.connect() as db:
        row=db.get(Tournament,tid);state=json.loads(row.state_json)
        state["players"][0]["account_id"]=bound
        row.state_json=json.dumps(state)


def test_unbound_history_links_once_with_stable_ids_and_members_unchanged(linked_history):
    store,claim,_,_=linked_history
    before=snapshot(store)
    links.publish(web,claim)
    after=snapshot(store)
    assert after["active_table_members"]==before["active_table_members"]
    assert after["tournament_table_sessions"]==before["tournament_table_sessions"]
    with store.connect() as db:
        for row in db.scalars(select(Tournament)):
            old=json.loads(next(r[2] for r in before["tournaments"] if r[0]==row.id))
            state=json.loads(row.state_json)
            assert state["rounds"]==old["rounds"] and state["players"][0]["id"]==old["players"][0]["id"]
            assert state["players"][0]["account_id"]==claim["account_id"]
            assert state["players"][0]["participant_type"]=="registered_user"
            assert row.version==2
        assert len(list(db.scalars(select(TournamentAudit))))==2
    links.publish(web,claim)
    assert snapshot(store)==after


def test_existing_same_binding_is_an_idempotent_noop(linked_history):
    store,claim,_,_=linked_history
    for tid in ("history-0","history-1"):conflict(store,tid,claim["account_id"])
    before=snapshot(store)
    links.publish(web,claim)
    assert snapshot(store)==before


@pytest.mark.parametrize("tid",["history-0","history-1"])
def test_different_binding_rejects_all_publication_without_touching_history(linked_history,tid):
    store,claim,_,_=linked_history
    conflict(store,tid)
    before=snapshot(store)
    claim={**claim,"registered_name":"Proposed New Name"}
    with pytest.raises(names.RegisteredNameError) as error:links.publish(web,claim)
    assert error.value.code=="legacy_identity_conflict"
    assert snapshot(store)==before


def test_late_version_conflict_rolls_back_name_first_link_and_audit(linked_history,monkeypatch):
    store,claim,_,_=linked_history
    before=snapshot(store)
    real=links.create_engine
    updates=[]
    def injected(*args,**kwargs):
        engine=real(*args,**kwargs)
        @event.listens_for(engine,"before_cursor_execute",retval=True)
        def lose_second_update(connection,cursor,statement,parameters,context,executemany):
            if statement.startswith("UPDATE tournaments SET"):
                updates.append(statement)
                if len(updates)==2:
                    statement+=" AND 1=0"
            return statement,parameters
        return engine
    monkeypatch.setattr(links,"create_engine",injected)
    with pytest.raises(ValueError,match="Tournament changed"):
        links.publish(web,{**claim,"registered_name":"Changed In Transaction"})
    assert len(updates)==2
    assert snapshot(store)==before


def test_old_approving_resume_keeps_journal_and_one_pending_account(linked_history):
    store,claim,path,player=linked_history
    account(path,"Admin",role="admin")
    secret=registration.submit_claim(web,form(player["name"],legacy_id=player["id"]))
    queued=registration.claims(web)[0]
    conflict(store)
    before=snapshot(store)
    with pytest.raises(names.RegisteredNameError,match="different account"):
        registration.review(web,{"claim_id":queued["id"],"decision":"approve"},"Admin")
    directory=names.read_accounts(path)
    created=[user for user in directory["users"].values() if user.get("account_id")==claim["account_id"]]
    assert len(created)==1 and created[0]["status"]=="pending_claim"
    for _ in range(2):
        with pytest.raises(names.RegisteredNameError,match="different account"):
            registration.resume(web,secret)
    with closing(registration.connect(path)) as db:
        journal=dict(db.execute("SELECT * FROM account_claims WHERE id=?",(queued["id"],)).fetchone())
    assert journal["status"]=="approving" and journal["password_hash"]
    assert names.read_accounts(path)==directory
    assert snapshot(store)==before
