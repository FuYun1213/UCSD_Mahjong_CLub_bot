"""Registered-name integration across tables, tournaments and read projections."""
import copy
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from mahjong_api.auth import get_current_user
from mahjong_api.registered_display import with_registered_names
from mahjong_api.store import Conflict
from mahjong_api.table_models import TableMembershipEvent
from test_table_v3 import setup, make, data, ADMIN, USERS


def test_registered_join_seat_actor_and_idempotency(setup):
    service, app = setup
    table = make(service)
    service.join(table['id'], USERS[0], 'east')
    body = data(user_ids=[USERS[1].id], seat='west')
    service.add_players(table['id'], body, USERS[0])
    assert service.add_players(table['id'], body, USERS[0])['replayed']
    members = service.get(table['id'], USERS[0])['members']
    member = next(p for p in members if p['user_id'] == USERS[1].id)
    assert member['seat'] == 'west'
    assert member['join_method'] == 'registered_name'
    assert member['added_by_user_id'] == USERS[0].id
    with service.store.connect() as db:
        events = list(db.scalars(select(TableMembershipEvent).where(TableMembershipEvent.user_id == USERS[1].id)))
        assert len(events) == 1 and events[0].join_method == 'registered_name'


def test_registered_join_revalidates_identity_and_empty_seat(setup):
    service, _ = setup
    table = make(service)
    service.join(table['id'], USERS[0], 'east')
    for ids, seat, error in [([USERS[0].id], 'south', 'cannot_add_self'),
                             ([USERS[1].id, USERS[1].id], None, 'duplicate_player_ids'),
                             ([USERS[1].id.upper()], 'south', 'account_not_found'),
                             ([USERS[1].id], 'east', 'seat_occupied'),
                             (['missing'], 'south', 'account_not_found'),
                             (['disabled'], 'south', 'account_disabled')]:
        with pytest.raises(Conflict, match=error):
            service.add_players(table['id'], data(user_ids=ids, **({'seat': seat} if seat else {})), USERS[0])
    assert service.get(table['id'], USERS[0])['player_count'] == 1
    with pytest.raises(Conflict, match='must_join_first'):
        service.add_players(table['id'], data(user_ids=[USERS[1].id]), USERS[2])


def test_current_registered_names_refresh_without_rewriting_relationships(setup):
    service, app = setup
    table = make(service)
    service.join(table['id'], USERS[0], 'east')
    reservation = service.reserve(table['id'], data(scheduled_at='2030-09-20T18:00:00-07:00', participant_ids=[USERS[0].id]), USERS[0])
    original = service.account_lookup
    service.account_lookup = lambda ids: [{**p, 'name': 'Renamed Player'} if p['id'] == USERS[0].id else p for p in original(ids)]
    app.dependency_overrides[get_current_user] = lambda: USERS[0]
    response = TestClient(app).get('/api/club-tables/'+table['id'])
    assert response.status_code == 200
    view = response.json()
    assert view['members'][0]['name'] == 'Renamed Player'
    assert view['members'][0]['user_id'] == USERS[0].id
    saved = next(r for r in view['reservations'] if r['id'] == reservation['id'])
    assert saved['user_name'] == saved['participants'][0]['name'] == 'Renamed Player'
    assert saved['participants'][0]['id'] == USERS[0].id


def test_tournament_selected_account_resolved_and_invalid_binding_rejected(setup):
    service, _ = setup
    tournament = service.tournaments.create(data(name='Registered Cup'), ADMIN.id)
    result = service.tournaments.apply(tournament['id'], 'player', data(version=tournament['version'], registered_user_id=USERS[0].id, name='Forged Name'), ADMIN.id, actor_user=ADMIN)
    player = result['players'][0]
    assert player['id'] == player['account_id'] == USERS[0].id
    assert player['name'] == USERS[0].name
    with pytest.raises(Conflict, match='account_not_found'):
        service.tournaments.apply(tournament['id'], 'bind_account', data(version=result['version'], player_id=player['id'], account_id='missing'), ADMIN.id, actor_user=ADMIN)
    with pytest.raises(Conflict, match='account_not_found'):
        service.tournaments.apply(tournament['id'], 'player', data(version=result['version'], registered_user_id='missing'), ADMIN.id, actor_user=ADMIN)


def test_projection_updates_linked_standings_and_audit_without_changing_stored_snapshot():
    original = {'players': [{'id': 'legacy-player', 'account_id': 'account-uuid', 'name': 'Old'}],
                'standings': [{'id': 'legacy-player', 'name': 'Old', 'score': 12}],
                'audit': [{'actor_id': 'account-uuid', 'detail': {'reason': 'review'}}]}
    snapshot = copy.deepcopy(original)
    projected = with_registered_names(original, [{'id': 'account-uuid', 'name': 'New Name'}])
    assert original == snapshot
    assert projected['players'][0]['name'] == projected['standings'][0]['name'] == 'New Name'
    assert projected['audit'][0]['actor_name'] == 'New Name'
    assert projected['players'][0]['id'] == 'legacy-player'


def test_case_distinct_opaque_ids_remain_distinct_in_lookup_and_reservations(setup):
    service, _ = setup
    original = service.account_lookup
    extras = [{"id":"opaque-A","name":"Case One"},{"id":"opaque-a","name":"Case Two"}]
    service.account_lookup = lambda ids: original(ids) + [p for p in extras if ids is None or p["id"] in ids]
    assert [p["name"] for p in service.lookup_accounts(["opaque-A", "opaque-a"])] == ["Case One","Case Two"]
    table = make(service)
    reservation = service.reserve(table["id"], data(scheduled_at="2030-09-20T18:00:00-07:00", participant_ids=["opaque-A","opaque-a"]), ADMIN)
    assert {p["id"] for p in reservation["participants"]} == {"opaque-A","opaque-a"}
    service.add_players(table["id"], data(user_ids=["opaque-A", "opaque-a"]), ADMIN)
    assert {p["user_id"] for p in service.get(table["id"],ADMIN)["members"]} == {"opaque-A","opaque-a"}


def test_registered_tournament_choice_never_silently_uses_same_named_legacy_player(setup):
    service, _ = setup
    tournament = service.tournaments.create(data(name="Legacy Cup",settings={"allow_guest_auto_enrollment":True}),ADMIN.id)
    # Simulate a historical unregistered player before this registered account existed.
    saved_lookup = service.account_lookup
    service.account_lookup = lambda ids: []
    legacy = service.tournaments.apply(tournament["id"], "player", data(version=tournament["version"], name=USERS[0].name),ADMIN.id,actor_user=ADMIN)
    service.account_lookup = saved_lookup
    legacy_id = legacy["players"][0]["id"]
    with pytest.raises(Conflict,match="registered_player_name_conflict"):
        service.tournaments.apply(tournament["id"], "player", data(version=legacy["version"],registered_user_id=USERS[0].id),ADMIN.id,actor_user=ADMIN)
    bound = service.tournaments.apply(tournament["id"],"bind_account",data(version=legacy["version"],player_id=legacy_id,account_id=USERS[0].id),ADMIN.id,actor_user=ADMIN)
    assert bound["players"][0]["id"] == legacy_id
    assert bound["players"][0]["account_id"] == USERS[0].id
    with pytest.raises(Conflict,match="account_already_registered"):
        service.tournaments.apply(tournament["id"], "player", data(version=bound["version"],registered_user_id=USERS[0].id),ADMIN.id,actor_user=ADMIN)


def test_registered_tournament_duplicate_uses_stable_identity_after_rename(setup):
    service, _ = setup
    tournament = service.tournaments.create(data(name="Name Change Cup"),ADMIN.id)
    entered = service.tournaments.apply(tournament["id"],"player",data(version=tournament["version"],registered_user_id=USERS[0].id),ADMIN.id,actor_user=ADMIN)
    original = service.account_lookup
    service.account_lookup = lambda ids: [{**p,"name":"Current Registered Name"} if p["id"]==USERS[0].id else p for p in original(ids)]
    with pytest.raises(Conflict,match="account_already_registered"):
        service.tournaments.apply(tournament["id"],"player",data(version=entered["version"],registered_user_id=USERS[0].id),ADMIN.id,actor_user=ADMIN)
    assert len(service.tournaments.get(tournament["id"])["players"]) == 1
