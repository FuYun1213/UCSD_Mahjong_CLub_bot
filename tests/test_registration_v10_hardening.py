"""Failure boundaries for the V10 account publication and auth compatibility."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import sqlite3
import threading
import pytest
import account_registration as reg
import account_discord as discord
import registered_names as names
import web_server as web
import mahjong_store
from test_registered_names import directory, account
from test_registration_v10 import form


def test_new_registration_recovers_after_player_commit_without_claiming_old_names(directory, monkeypatch):
    path, clubpath = directory
    original = names.write_accounts
    def fail(*args, **kwargs):
        raise OSError('simulated account publication interruption')
    monkeypatch.setattr(names, 'write_accounts', fail)
    with pytest.raises(OSError):
        reg.create_new(web, form('Crash Test'))
    with sqlite3.connect(clubpath) as db:
        player = db.execute('SELECT id FROM players').fetchone()[0]
        uid, state, digest = db.execute('SELECT account_id,status,password_hash FROM account_creation_intents').fetchone()
        assert state == 'pending' and digest.startswith('$argon2id$')
    assert not names.read_accounts(path)['users']
    monkeypatch.setattr(names, 'write_accounts', original)
    # A normal login completes the durable intent; it never registers by name.
    assert web.login_user(form('Crash Test'))[1] == 'Crash Test'
    reg.recover_creations(web)
    row = names.read_accounts(path)['users']['crash test']
    assert row['account_id'] == uid and row['club_player_id'] == player
    with sqlite3.connect(clubpath) as db:
        assert db.execute('SELECT count(*) FROM players').fetchone()[0] == 1
        assert db.execute('SELECT status,password_hash FROM account_creation_intents').fetchone() == ('published','')
    with closing(reg.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM account_registration_audit WHERE action='register_new'").fetchone()[0] == 1


def test_crash_after_account_publication_recovers_audit_once(directory, monkeypatch):
    path, clubpath = directory
    original = reg.audit
    monkeypatch.setattr(reg, 'audit', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('audit unavailable')))
    with pytest.raises(OSError): reg.create_new(web, form())
    before = names.read_accounts(path)['users']['new member'].copy()
    monkeypatch.setattr(reg, 'audit', original)
    reg.recover_creations(web); reg.recover_creations(web)
    assert names.read_accounts(path)['users']['new member'] == before
    with closing(reg.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM account_registration_audit WHERE action='register_new'").fetchone()[0] == 1


def test_player_and_registration_intent_commit_as_one_transaction(directory):
    path, clubpath = directory
    with closing(mahjong_store.connect(clubpath)) as db:
        reg.creation_schema(db)
        db.execute("CREATE TRIGGER fail_intent BEFORE INSERT ON account_creation_intents BEGIN SELECT RAISE(ABORT,'simulated intent failure'); END")
        db.commit()
    with pytest.raises(sqlite3.IntegrityError): reg.create_new(web, form())
    with sqlite3.connect(clubpath) as db:
        assert db.execute('SELECT count(*) FROM players').fetchone()[0] == 0
    assert not names.read_accounts(path)['users']


def test_new_registration_does_not_reuse_an_old_player_after_recovery(directory):
    path, clubpath = directory
    with closing(mahjong_store.connect(clubpath)) as db: old = mahjong_store.upsert_player(db, 'Legacy')
    reg.initialize(web); reg.recover_creations(web)
    with pytest.raises(ValueError, match='Claim Existing'): reg.create_new(web, form('Legacy'))
    assert not names.read_accounts(path)['users']
    with sqlite3.connect(clubpath) as db:
        assert db.execute('SELECT id,name FROM players').fetchall() == [(old['id'],'Legacy')]


def test_admin_renamed_name_can_be_used_by_a_new_account(directory):
    path, clubpath = directory
    account(path, 'Admin', role='admin')
    reg.create_new(web, form('Original'))
    uid = web.stable_account_id('Original')
    web.admin_registered_name({'user_id':uid,'expected_name':'Original','new_name':'Renamed','confirm':True}, 'Admin')
    reg.create_new(web, form('Original'))
    assert web.stable_account_id('Original') != uid and web.stable_account_id('Renamed') == uid


@pytest.mark.parametrize('value',[None, [], 42, {'username':['x'],'password':'abcdef','confirm_password':'abcdef'}])
def test_registration_form_requires_valid_object_and_string_name(directory, value):
    with pytest.raises(ValueError): reg.create_new(web, value)


def test_disabled_flag_blocks_new_session_and_oauth_binding(directory):
    path, _ = directory
    uid = account(path, 'Disabled', is_active=False)
    with pytest.raises(PermissionError): web.issue_session(SimpleNamespace(headers={}), uid)
    with pytest.raises(ValueError): discord.bind(path,uid,'123456789012345678','Discord')


def test_public_avatar_projection_uses_discord_fallback_then_upload(directory):
    path, _ = directory
    account(path,'Player',discord_avatar='https://cdn.discordapp.com/example.png')
    assert web.public_user_profiles()['Player']['avatar'].startswith('https:')
    data = names.read_accounts(path); data['users']['player']['avatar']='data:image/png;base64,aA=='
    names.write_accounts(path,data)
    assert web.public_user_profiles()['Player']['avatar'].startswith('data:')


def test_parallel_requests_cannot_exceed_configured_ip_limit(monkeypatch):
    monkeypatch.setattr(web,'_rate_limits',{})
    monkeypatch.setattr(web,'WRITE_RATE_LIMIT',3)
    handler=SimpleNamespace(headers={},client_address=('192.0.2.1',1234))
    barrier=threading.Barrier(12)
    def request(_):
        barrier.wait()
        try: web.enforce_rate_limit(handler); return True
        except PermissionError: return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(request,range(12))) == 3


def test_recovery_never_publishes_into_a_different_account_directory(directory, monkeypatch, tmp_path):
    path, _ = directory
    original = names.write_accounts
    monkeypatch.setattr(names, 'write_accounts', lambda *a, **k: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError): reg.create_new(web, form())
    monkeypatch.setattr(names, 'write_accounts', original)
    other = tmp_path / 'separate-accounts.json'
    monkeypatch.setattr(web, 'USERS_FILE', other)
    reg.recover_creations(web)
    assert not other.exists()
    monkeypatch.setattr(web, 'USERS_FILE', path)
    reg.recover_creations(web)
    assert names.read_accounts(path)['users']['new member']['club_player_id']


def interrupted_creation(directory,monkeypatch):
    path,clubpath=directory
    original=names.write_accounts
    with monkeypatch.context() as fault:
        fault.setattr(names,'write_accounts',lambda *a,**k: (_ for _ in ()).throw(OSError('interrupted publication')))
        with pytest.raises(OSError):reg.create_new(web,form('Pending Creator'))
    with closing(sqlite3.connect(clubpath)) as db:
        db.row_factory=sqlite3.Row
        return dict(db.execute("SELECT * FROM account_creation_intents WHERE status='pending'").fetchone())


def test_interrupted_new_creation_cannot_be_claimed_as_legacy(directory,monkeypatch):
    path,clubpath=directory
    intent=interrupted_creation(directory,monkeypatch)
    assert reg.is_claimed(web,{'id':intent['player_id'],'name':'Pending Creator'})
    with pytest.raises(ValueError) as error:
        reg.submit_claim(web,form('Different Claimant',legacy_id=intent['player_id']))
    assert str(error.value)==reg.ALREADY
    users=names.read_accounts(path)['users']
    assert len(users)==1 and users['pending creator']['account_id']==intent['account_id']
    assert web.login_user(form('Pending Creator'))[1]=='Pending Creator'
    assert reg.claims(web)==[]


def test_review_recovers_creation_before_rejecting_preexisting_conflicting_claim(directory,monkeypatch):
    path,clubpath=directory
    account(path,'Admin',role='admin')
    intent=interrupted_creation(directory,monkeypatch)
    # Reproduce a claim queued by the earlier draft before this recovery guard.
    with monkeypatch.context() as old_behavior:
        old_behavior.setattr(reg,'recover_creations',lambda web:None)
        old_behavior.setattr(reg,'is_claimed',lambda *a,**k:False)
        reg.submit_claim(web,form('Pending Creator',legacy_id=intent['player_id']))
    claim=reg.claims(web)[0]
    with pytest.raises(ValueError) as error:
        reg.review(web,{'claim_id':claim['id'],'decision':'approve'},'Admin')
    assert str(error.value)==reg.ALREADY
    users=names.read_accounts(path)['users']
    assert sum(a.get('club_player_id')==intent['player_id'] for a in users.values())==1
    assert users['pending creator']['account_id']==intent['account_id']
    assert reg.claims(web)[0]['status']=='pending'


def test_recovery_refuses_a_player_already_linked_to_another_account(directory,monkeypatch):
    path,clubpath=directory
    intent=interrupted_creation(directory,monkeypatch)
    other=account(path,'Existing Owner',account_id='different-identity',club_player_id=intent['player_id'])
    before=names.read_accounts(path)
    with pytest.raises(ValueError,match='administrator review'):
        reg.recover_creations(web)
    assert names.read_accounts(path)==before
    with closing(sqlite3.connect(clubpath)) as db:
        assert db.execute('SELECT status FROM account_creation_intents').fetchone()[0]=='pending'


@pytest.mark.parametrize('change',['missing','renamed'])
def test_recovery_refuses_missing_or_renamed_unpublished_source_player(directory,monkeypatch,change):
    path,clubpath=directory
    intent=interrupted_creation(directory,monkeypatch)
    with closing(sqlite3.connect(clubpath)) as db,db:
        if change=='missing':db.execute('DELETE FROM players WHERE id=?',(intent['player_id'],))
        else:db.execute("UPDATE players SET name='Changed Source',name_key='changed source' WHERE id=?",(intent['player_id'],))
    with pytest.raises(ValueError,match='original player was changed'):
        reg.recover_creations(web)
    assert not names.read_accounts(path)['users']


def test_recovery_preserves_admin_rename_after_account_was_published(directory,monkeypatch):
    path,clubpath=directory
    account(path,'Admin',role='admin')
    with monkeypatch.context() as fault:
        fault.setattr(reg,'audit',lambda *a,**k: (_ for _ in ()).throw(OSError('audit interruption')))
        with pytest.raises(OSError):reg.create_new(web,form('Published Name'))
    uid=web.stable_account_id('Published Name')
    web.admin_registered_name({'user_id':uid,'expected_name':'Published Name','new_name':'Renamed Published','confirm':True},'Admin')
    before=names.read_accounts(path)
    reg.recover_creations(web)
    assert names.read_accounts(path)==before
    assert web.login_user(form('Renamed Published'))[1]=='Renamed Published'
    with closing(sqlite3.connect(clubpath)) as db:
        assert db.execute('SELECT status,password_hash FROM account_creation_intents').fetchone()==('published','')


def test_creation_intent_cannot_publish_directly_into_another_account_directory(directory,monkeypatch,tmp_path):
    intent=interrupted_creation(directory,monkeypatch)
    other=tmp_path/'different-directory.json'
    monkeypatch.setattr(web,'USERS_FILE',other)
    with pytest.raises(ValueError,match='administrator review'):
        reg.publish_creation(web,intent)
    assert not other.exists()
