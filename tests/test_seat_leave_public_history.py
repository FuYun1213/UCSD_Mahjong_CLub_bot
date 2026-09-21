"""Self-service leave and public history: real database, sessions and browser."""
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import pytest
import requests
from sqlalchemy import select
import mahjong_store
import web_server
from mahjong_api.database_models import TableState, SeatRecord
from mahjong_api.table_models import ActiveTableMember, TableMembershipEvent
from mahjong_api.store import Conflict
from test_table_v3 import setup, make, USERS
from test_web_score_bridge import website, login


def test_leave_returns_fresh_state_and_replays_without_another_event(setup):
    tables,_=setup;table=make(tables)
    state=tables.set_my_seat(table['id'],{'seat':'east'},USERS[0])
    tables.set_my_seat(table['id'],{'seat':'south'},USERS[1])
    result=tables.leave(table['id'],USERS[0],'seat_card',state['match_id'])
    assert result['changed'] and result['table_state']['players']['east'] is None
    assert result['table_state']['players']['south']['id']==USERS[1].id
    repeated=tables.leave(table['id'],USERS[0],'seat_card',state['match_id'])
    assert repeated['left'] and not repeated['changed']
    with tables.store.connect() as db:
        assert db.get(ActiveTableMember,USERS[0].id) is None
        assert db.get(SeatRecord,(table['score_table_id'],'east')) is None
        events=list(db.scalars(select(TableMembershipEvent).where(TableMembershipEvent.user_id==USERS[0].id,TableMembershipEvent.action=='left')))
        assert len(events)==1 and events[0].actor_id==USERS[0].id and events[0].reason=='seat_card'


@pytest.mark.parametrize('locked,error',[('stale','stale_match'),('started','cannot_leave_started'),('pending','score_exists')])
def test_leave_rejects_stale_or_unsettled_game_and_keeps_both_seat_models(setup,locked,error):
    tables,_=setup;table=make(tables);state=tables.set_my_seat(table['id'],{'seat':'east'},USERS[0])
    expected='obsolete-match' if locked=='stale' else state['match_id']
    with tables.store.connect() as db:
        row=db.scalar(select(TableState).where(TableState.table_id==table['score_table_id']))
        if locked=='started':row.started_at=tables.clock()
        if locked=='pending':row.pending_match_id='pending'
    with pytest.raises(Conflict,match=error):tables.leave(table['id'],USERS[0],'leave_button',expected)
    with tables.store.connect() as db:
        assert db.get(ActiveTableMember,USERS[0].id).seat=='east'
        assert db.get(SeatRecord,(table['score_table_id'],'east')).user_id==USERS[0].id


def test_leave_auth_origin_and_authenticated_identity(website):
    url,app,_=website;route=url+'/api/club-tables/web/leave'
    assert requests.post(route,json={}).status_code==401
    actor,peer=login(url,1),login(url,2)
    try:
        joined=actor.put(url+'/api/club-tables/web/my-seat',json={'seat':'east'}).json()
        assert actor.post(route,json={},headers={'Origin':url+'.evil.invalid'}).status_code==403
        response=peer.post(route,json={'user_id':'photo-user-1'},headers={'Origin':url});assert response.status_code==200,response.text
        assert response.json()['changed'] is False
        assert actor.get(url+'/api/tables/web').json()['players']['east']['id']=='photo-user-1'
        stale=actor.post(route,json={'match_id':'old'},headers={'Origin':url});assert stale.status_code==409 and stale.json()['detail']['code']=='stale_match'
        result=actor.post(route,json={'reason':'leave_button','match_id':joined['match_id']},headers={'Origin':url})
        assert result.status_code==200 and result.json()['table_state']['players']['east'] is None
    finally:actor.close();peer.close()


@pytest.fixture
def history_website(website,monkeypatch):
    url,app,sink=website
    monkeypatch.setattr(web_server,'sheet_player_names',web_server.sql_player_names)
    original_read=web_server.read_json
    monkeypatch.setattr(web_server,'read_json',lambda path,default:default if Path(path).name in {'bot_action_log.json','replay_subscriptions.json'} else original_read(path,default))
    monkeypatch.setattr(web_server,'sql_quarter_context',lambda:{'current_quarter':'2026 Fall','quarters':['2026 Fall']})
    with closing(mahjong_store.connect(web_server.MAHJONG_DB_FILE)) as db:
        mahjong_store.import_game(db,['photo1','photo2','photo3','photo4'],[40000,30000,20000,10000],'2026-09-19 18:00:00',quarter='2026 Fall',source='web')
        mahjong_store.import_game(db,['Legacy Visitor','photo2','photo3','photo5'],[40000,30000,20000,10000],'2026-09-20 18:00:00',quarter='2026 Fall',source='web')
    return website


def test_anonymous_history_filters_work_but_reservation_and_account_search_stay_private(history_website):
    url,_,_=history_website
    for params,count in [({},2),({'match_player':'Legacy Visitor'},1),({'table_players':'photo1 / photo2'},1)]:
        response=requests.get(url+'/api/dashboard',params=params,timeout=15)
        assert response.status_code==200,response.text
        assert len(response.json()['recent_games'])==count
    for method,path,body in [('get','/api/registered-users',None),('get','/api/club-tables',None),('get','/api/club-tables/web',None),('post','/api/club-tables/web/reservations',{})]:
        assert getattr(requests,method)(url+path,json=body,timeout=10).status_code==401


def test_public_recent_match_and_private_reservations_in_real_browser(history_website):
    url,_,_=history_website
    env=os.environ.copy();env['NFC_TEST_URL']=url;env['NODE_PATH']=str(Path('.venv-api/browser-tests/node_modules').resolve())
    result=subprocess.run(['node','tests/browser_public_history.cjs'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=100)
    assert result.returncode==0,result.stdout+result.stderr
