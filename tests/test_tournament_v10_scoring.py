"""Focused V10 scoring regression tests; no real accounts or external delivery."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select
from mahjong_api.models import User
from mahjong_api.store import Conflict, Store
from mahjong_api.tournament_models import Tournament, TournamentAudit
from mahjong_api.tournament_flow import lock_tournament
from mahjong_api.tournament_rules import PLACEMENT_FIELDS, settings_value, score_table, standings
from test_tournament import rig, tournament, command, round_complete
from test_table_v3 import setup

RULES = {"scoring_mode":"placement_and_game_count", **dict(zip(PLACEMENT_FIELDS,[5,3,1,0,2])),
         "allow_guest_auto_enrollment": True}
ADMIN = User(id="admin-1",name="Admin",role="admin")


def placement_cup(service):
    state=tournament(service,4)
    command(service,state['id'],'settings',settings=RULES)
    command(service,state['id'],'start')
    return state['id']


def persisted(service,tid):
    with service.store.connect() as db:
        return copy.deepcopy(json.loads(db.get(Tournament,tid).state_json))


def test_confirmation_uses_latest_scores_without_revalidating_old_point_settings(rig):
    service,*_=rig;tid=placement_cup(service)
    command(service,tid,'pair');state=command(service,tid,'confirm_seats')
    table=state['rounds'][0]['tables'][0]
    command(service,tid,'score_table',table=table['number'],scores=dict(zip(table['seats'],[40000,30000,20000,10000])))
    command(service,tid,'settings',settings={'game_participation_score':3,'base_points':30000,'return_point':90000,'uma':[99,88,77,66]})
    state=command(service,tid,'confirm_round')
    result=state['rounds'][0]['tables'][0]['result']
    assert [p['gameScore'] for p in result['players']]==[8,6,4,3]
    assert [p['rawScore'] for p in result['players']]==[40000,30000,20000,10000]
    assert set(result['rules'])=={'scoring_mode',*PLACEMENT_FIELDS}


def test_explicit_reprice_preserves_game_identity_raw_scores_and_original_snapshot(rig):
    service,*_=rig;tid=placement_cup(service)
    state=round_complete(service,tid)
    original=persisted(service,tid)['rounds'][0]['tables'][0]
    command(service,tid,'settings',settings={'game_participation_score':-0.25,'base_points':30000})
    assert persisted(service,tid)['rounds'][0]['tables'][0]==original
    state=command(service,tid,'recalculate',reason='  Verified rule correction  ')
    current=state['rounds'][0]['tables'][0]
    assert current['match_id']==original['match_id']
    assert current['result_revisions']==[original['result']]
    assert current['result']['request_id']==original['result']['request_id']
    assert [p['rawScore'] for p in current['result']['players']]==[p['rawScore'] for p in original['result']['players']]
    assert [p['gameScore'] for p in current['result']['players']]==[4.75,2.75,0.75,-0.25]
    assert all(r['completed_rounds']==1 for r in state['standings'])
    audit=next(a for a in state['audit'] if a['action']=='recalculate')
    assert audit['actor_id']==ADMIN.id and audit['detail']['games_recalculated']==1
    assert audit['detail']['reason']=='Verified rule correction'
    assert audit['detail']['before'][0]['tables'][0]['result']==original['result']


@pytest.mark.parametrize('actor',[None,User(id='admin-1',name='Fake',role='user'),User(id='different-admin',name='Other',role='admin')])
def test_recalculation_requires_server_authenticated_matching_admin(rig,actor):
    service,*_=rig;tid=placement_cup(service);round_complete(service,tid)
    before=persisted(service,tid)
    with pytest.raises(Conflict,match='admin_required'):
        service.apply(tid,'recalculate',{'version':service.get(tid)['version'],'request_id':str(uuid4()),'reason':'forged'},'admin-1',actor_user=actor)
    assert persisted(service,tid)==before


@pytest.mark.parametrize('reason',[None,'', '   ', 'x'*501])
def test_recalculation_requires_bounded_reason_and_is_atomic(rig,reason):
    service,*_=rig;tid=placement_cup(service);round_complete(service,tid)
    before=persisted(service,tid)
    with pytest.raises(Conflict,match='reason_required'):
        command(service,tid,'recalculate',reason=reason)
    assert persisted(service,tid)==before


def test_recalculation_request_is_idempotent_without_double_audit_or_game_count(rig):
    service,*_=rig;tid=placement_cup(service);round_complete(service,tid)
    data={'version':service.get(tid)['version'],'request_id':str(uuid4()),'reason':'Reviewed'}
    service.apply(tid,'recalculate',data,ADMIN.id,actor_user=ADMIN)
    service.apply(tid,'recalculate',data,ADMIN.id,actor_user=ADMIN)
    state=service.get(tid)
    assert len(state['rounds'][0]['tables'][0]['result_revisions'])==1
    assert all(r['completed_rounds']==1 for r in state['standings'])
    assert len([a for a in state['audit'] if a['action']=='recalculate'])==1


def test_fractional_rewards_and_penalties_ignore_legacy_rounding_and_revoke_cleanly(rig):
    service,*_=rig;tid=placement_cup(service);state=round_complete(service,tid)
    pid=state['standings'][0]['id'];before=state['standings'][0]['game_score']
    state=command(service,tid,'penalty_add',player_id=pid,amount='0.025',reason='Deduction')
    state=command(service,tid,'penalty_add',player_id=pid,amount='-0.0375',reason='Award')
    row=next(r for r in state['standings'] if r['id']==pid)
    assert row['penalty_total']==0.0125 and row['score']==before+0.0125
    assert row['completed_rounds']==1 and row['game_score']==before
    award=next(p for p in state['penalties'] if p['amount']=='-0.0375')
    state=command(service,tid,'penalty_revoke',penalty_id=award['id'],reason='Award withdrawn')
    row=next(r for r in state['standings'] if r['id']==pid)
    assert row['penalty_total']==-0.025 and row['score']==before-0.025


def scoring_state():
    return {'settings':settings_value(RULES),'players':[{'id':p,'name':p} for p in 'ABCDEFG'],
            'rounds':[],'finals':None,'penalties':[]}


def confirmed_game(state,players,match_id='match-1'):
    table={'seats':list(players),'match_id':match_id}
    table['result']=score_table(state,table,dict(zip(players,[40000,30000,20000,10000])))
    return {'status':'confirmed','byes':[],'tables':[table]}


@pytest.mark.parametrize('level,field,value',[
    ('round','duplicate_of','old-round'),('round','cancelled',True),('table','status','cancelled'),
    ('table','status','void'),('table','status','draft'),('table','status','pending'),('table','cancelled',True),
])
def test_explicitly_excluded_confirmed_records_never_add_participation(level,field,value):
    state=scoring_state();rnd=confirmed_game(state,'ABCD')
    (rnd if level=='round' else rnd['tables'][0])[field]=value
    state['rounds']=[rnd]
    assert all(r['completed_rounds']==0 and r['game_score']==0 for r in standings(state))


def test_same_confirmed_match_cannot_count_twice_even_without_duplicate_flag():
    state=scoring_state();rnd=confirmed_game(state,'ABCD')
    state['rounds']=[rnd,copy.deepcopy(rnd)]
    assert all(r['completed_rounds']==1 for r in standings(state) if r['id'] in 'ABCD')
    assert next(r for r in standings(state) if r['id']=='A')['score']==7


def test_equal_totals_share_rank_despite_raw_points_first_place_and_game_counts():
    state=scoring_state();state['settings'].update(dict(zip(PLACEMENT_FIELDS,[2,1,0,0,0])))
    state['rounds']=[confirmed_game(state,'ABCD','one'),confirmed_game(state,'EBFG','two')]
    rows={r['id']:r for r in standings(state)}
    assert rows['A']['completed_rounds']==1 and rows['B']['completed_rounds']==2
    assert rows['A']['placements'][0]==1 and rows['B']['placements'][0]==0
    assert [(rows[p]['score'],rows[p]['rank']) for p in 'ABE']==[(2,1)]*3
    assert rows['C']['rank']==4


def test_recalculation_skips_invalid_history_and_absent_results(rig):
    service,*_=rig;tid=placement_cup(service);round_complete(service,tid)
    with service.store.connect() as db:
        row=db.get(Tournament,tid);state=json.loads(row.state_json)
        original=state['rounds'][0]['tables'][0]
        exclusions=[]
        for index,flag in enumerate(('void','is_test','duplicate_of','cancelled')):
            table=copy.deepcopy(original);table['match_id']='excluded-'+str(index);table[flag]=True
            exclusions.append(table)
        empty=copy.deepcopy(original);empty['match_id']='empty';empty['result']=None;exclusions.append(empty)
        state['rounds'][0]['tables'].extend(exclusions)
        row.state_json=json.dumps(state)
    command(service,tid,'settings',settings={'game_participation_score':4})
    state=command(service,tid,'recalculate',reason='Reprice valid games')
    assert state['rounds'][0]['tables'][1:]==exclusions
    assert all(r['completed_rounds']==1 for r in state['standings'])
    assert next(a for a in state['audit'] if a['action']=='recalculate')['detail']['games_recalculated']==1


def test_duplicate_seats_rejected_before_scoring():
    state=scoring_state()
    with pytest.raises(Conflict,match='invalid_roster'):
        score_table(state,{'seats':['A','A','B','C']},{'A':25000,'B':25000,'C':25000})


@pytest.mark.parametrize('value',[None,True,'', 'NaN','Infinity','-Infinity',1000000001])
def test_nonfinite_boolean_or_blank_scores_are_rejected(value):
    with pytest.raises(Conflict):
        settings_value({**RULES,'first_placement_game_score':value})


def test_shared_tournament_lock_serializes_two_store_instances_and_refreshes_state(rig):
    service,*_=rig;tid=tournament(service,0)['id']
    other=Store(service.store.path);ready=Event()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with service.store.connect() as db:
                row=lock_tournament(db,tid);before=row.version;row.version+=1
                db.flush()
                def competitor():
                    with other.connect() as session:
                        ready.set()
                        return lock_tournament(session,tid).version
                future=executor.submit(competitor)
                assert ready.wait(2)
                with pytest.raises(TimeoutError):future.result(timeout=0.1)
            assert future.result(timeout=3)==before+1
    finally:
        other.close()


def test_enrolled_guest_must_leave_before_roster_removal(setup):
    from test_tournament_v10 import guest_cup
    from mahjong_api.table_models import ActiveTableMember
    from mahjong_api.guest_models import TournamentParticipant
    tables,app,state,table,guests=guest_cup(setup)
    tid=state["id"]
    result,secret=guests.join(tid,{"table_id":table["id"],"name":"Leaving Guest"},None)
    pid=result["participant"]["id"]
    with pytest.raises(Conflict,match="player_seated_leave_first"):
        command(tables.tournaments,tid,"remove_player",player_id=pid)
    assert any(p["id"]==pid for p in tables.tournaments.get(tid)["players"])
    with tables.store.connect() as db:
        assert db.get(ActiveTableMember,pid) is not None
    guests.leave(tid,secret)
    state=command(tables.tournaments,tid,"remove_player",player_id=pid)
    assert not any(p["id"]==pid for p in state["players"])
    with tables.store.connect() as db:
        assert db.get(TournamentParticipant,pid) is not None
        assert db.get(ActiveTableMember,pid) is None


def test_reserved_guest_seat_without_member_still_prevents_orphan_removal(setup):
    from test_tournament_v10 import guest_cup
    from mahjong_api.table_models import ActiveTableMember
    tables,app,state,table,guests=guest_cup(setup)
    result,secret=guests.join(state["id"],{"table_id":table["id"],"name":"Reserved Guest"},None)
    pid=result["participant"]["id"]
    with tables.store.connect() as db:
        db.delete(db.get(ActiveTableMember,pid))
    with pytest.raises(Conflict,match="player_seated_leave_first"):
        command(tables.tournaments,state["id"],"remove_player",player_id=pid)


def test_account_claim_and_tournament_writer_share_account_before_database_order(rig,tmp_path):
    from contextlib import contextmanager
    from sqlalchemy import text
    import registered_names
    service,*_=rig;tid=tournament(service,0)["id"]
    data={"version":service.get(tid)["version"],"request_id":str(uuid4()),"settings":{"bye_score":1}}
    account_path=tmp_path/"isolated-accounts.json"
    account_owned, writer_waiting = Event(), Event()
    @contextmanager
    def guard():
        writer_waiting.set()
        with registered_names.account_lock(account_path):
            yield
    service.account_guard=guard
    def approval():
        with registered_names.account_lock(account_path):
            account_owned.set()
            assert writer_waiting.wait(3)
            # Mirrors approved-account publication: account lock, then NFC write.
            with service.store.connect() as db:
                db.execute(text("PRAGMA busy_timeout=500"))
                db.execute(text("INSERT INTO nfc_metadata(key,value) VALUES('claim-lock-regression','1')"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        claim=executor.submit(approval)
        assert account_owned.wait(3)
        writer=executor.submit(service.apply,tid,"settings",data,ADMIN.id,actor_user=ADMIN)
        claim.result(timeout=4)
        assert writer.result(timeout=4)["settings"]["bye_score"]==1
