"""Legacy claims must never acquire a competition Guest by matching its name."""
import json
from uuid import uuid4
import pytest
from test_registered_names import directory, account
from test_registration_v10 import legacy, form
import account_registration as reg
import web_server as web
from mahjong_api.store import Store
from mahjong_api.database_models import User as ScoreUser
from mahjong_api.guest_models import TournamentParticipant
from mahjong_api.tournament_models import Tournament
from mahjong_api.tournament_rules import settings_value


@pytest.mark.parametrize('guest_id', ['guest-' + str(uuid4()), 'historical-scoped-guest'])
def test_existing_player_claim_does_not_claim_same_named_guest(directory, monkeypatch, tmp_path, guest_id):
    path,_=directory
    old=legacy(web, 'Shared Name')
    account(path, 'Admin', role='admin')
    score_path=tmp_path/'score.sqlite3';monkeypatch.setenv('NFC_DATABASE_PATH',str(score_path))
    store=Store(score_path)
    tid=str(uuid4())
    state={'id':tid,'schema_version':3,'name':'Historical Cup','settings':settings_value({}),
           'status':'registration','players':[{'id':guest_id,'name':'Shared Name','participant_type':'guest'}],
           'rounds':[],'preview':None,'finals':None}
    with store.connect() as db:
        db.add(Tournament(id=tid,version=1,state_json=json.dumps(state)))
        db.add(ScoreUser(id=guest_id,name='Shared Name'))
        db.flush()
        db.add(TournamentParticipant(id=guest_id,tournament_id=tid,participant_type='guest',name='Shared Name',
            normalized_name='shared name',session_hash='private-existing-guest-session-hash',
            created_at='2026-09-20T00:00:00+00:00',created_by='migration'))
    try:
        reg.submit_claim(web,form('Shared Name',legacy_id=old['id']))
        reg.review(web,{'claim_id':reg.claims(web)[0]['id'],'decision':'approve'},'Admin')
        assert web.stable_account_id('Shared Name') == 'club-'+str(old['id'])
        with store.connect() as db:
            guest=db.get(TournamentParticipant,guest_id)
            assert guest.merged_into_user_id is None and guest.session_hash=='private-existing-guest-session-hash'
            assert db.get(ScoreUser,guest_id).name=='Shared Name'
            assert json.loads(db.get(Tournament,tid).state_json)==state
    finally: store.close()
