"""Self-service wind cards: authenticated identity, atomic moves, and safe occupancy."""
import json
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Manager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from mahjong_api.auth import get_current_user
from mahjong_api.database_models import SeatRecord, TableState
from mahjong_api.models import SEATS, User
from mahjong_api.store import Conflict
from mahjong_api.table_models import ActiveTableMember, ClubTable, TableMembershipEvent, TableJoinToken
from mahjong_api.tournament_models import Tournament
from test_table_v3 import setup, make, token, raw, ADMIN, USERS
from test_tournament_v2 import waiting


def set_seat(service, table, user, seat, **extra):
    return service.set_my_seat(table["id"], {"seat": seat, **extra}, user)


def members(service, table):
    with service.store.connect() as db:
        return [(row.user_id, row.seat) for row in db.scalars(select(ActiveTableMember).where(ActiveTableMember.table_id == table["id"]))]


@pytest.mark.parametrize("seat", SEATS)
def test_card_join_uses_authenticated_identity_and_returns_complete_state(setup, seat):
    s, app = setup
    table = make(s)
    app.dependency_overrides[get_current_user] = lambda: USERS[0]
    response = TestClient(app).put("/api/club-tables/" + table["id"] + "/my-seat",
        json={"seat":seat, "user_id":USERS[1].id, "name":"Forged", "role":"admin"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["seat_action"] == "joined" and result["my_seat"] == seat
    assert result["previous_seat"] is None
    assert result["players"][seat]["id"] == USERS[0].id
    assert result["match_id"] == table["current_match_id"] and result["seat_order"] == "ESWN"
    assert {"elapsed_seconds", "average_duration_seconds", "round", "display_name"} <= result.keys()
    with s.store.connect() as db:
        row = db.get(ActiveTableMember, USERS[0].id)
        assert row.seat == seat and row.join_method == "seat_card" and row.added_by_user_id == USERS[0].id
        event = db.scalar(select(TableMembershipEvent))
        assert event.action == "joined" and event.actor_id == USERS[0].id and event.join_method == "seat_card"
        assert db.get(ActiveTableMember, USERS[1].id) is None


@pytest.mark.parametrize("seat", [None, "E", "East", "east ", "", "bottom", 1, True, [], {}])
def test_card_winds_are_strict_server_enums(setup, seat):
    s, app = setup
    table = make(s)
    app.dependency_overrides[get_current_user] = lambda: USERS[0]
    result = TestClient(app).put("/api/club-tables/" + table["id"] + "/my-seat", json={"seat":seat})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "invalid_seat"
    assert members(s, table) == []


def test_same_wind_is_a_noop_and_move_preserves_one_membership_with_audit(setup):
    s, _ = setup
    table = make(s)
    set_seat(s, table, USERS[0], "east")
    with s.store.connect() as db:
        joined_at = db.get(ActiveTableMember, USERS[0].id).joined_at
        updated_at = db.scalar(select(TableState).where(TableState.table_id == table["score_table_id"])).updated_at
    repeated = set_seat(s, table, USERS[0], "east")
    assert repeated["seat_action"] == "unchanged" and repeated["updated_at"] == updated_at
    moved = set_seat(s, table, USERS[0], "north")
    assert moved["seat_action"] == "moved" and moved["previous_seat"] == "east"
    assert moved["players"]["east"] is None and moved["players"]["north"]["id"] == USERS[0].id
    with s.store.connect() as db:
        row = db.get(ActiveTableMember, USERS[0].id)
        assert row.joined_at == joined_at and row.seat == "north" and row.join_method == "seat_card"
        events = list(db.scalars(select(TableMembershipEvent).order_by(TableMembershipEvent.at)))
        assert [e.action for e in events] == ["joined", "seat_changed"]
        assert events[-1].actor_id == USERS[0].id and events[-1].join_method == "seat_card" and events[-1].at
        assert json.loads(events[-1].reason) == {"from_seat":"east", "to_seat":"north"}
        assert db.scalar(select(func.count()).select_from(ActiveTableMember)) == 1
        assert db.scalar(select(func.count()).select_from(SeatRecord)) == 1


def test_occupied_failed_move_keeps_both_original_seats(setup):
    s, _ = setup
    table = make(s)
    set_seat(s, table, USERS[0], "east")
    set_seat(s, table, USERS[1], "south")
    with pytest.raises(Conflict, match="seat_occupied"):
        set_seat(s, table, USERS[0], "south")
    assert set(members(s, table)) == {(USERS[0].id,"east"),(USERS[1].id,"south")}
    with s.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TableMembershipEvent)) == 2


def test_move_failure_rolls_back_both_models_and_audit(setup, monkeypatch):
    import mahjong_api.table_membership as membership
    s, _ = setup
    table = make(s)
    set_seat(s, table, USERS[0], "east")
    def fail(*args, **kwargs):
        raise RuntimeError("audit write failed")
    monkeypatch.setattr(membership, "event", fail)
    with pytest.raises(RuntimeError, match="audit write failed"):
        set_seat(s, table, USERS[0], "west")
    assert members(s, table) == [(USERS[0].id,"east")]
    assert s.matches.table(table["score_table_id"])["seats"] == {"east":USERS[0].id,"south":None,"west":None,"north":None}


def test_cross_table_rejected_without_leave_or_silent_move(setup):
    s, _ = setup
    first, second = make(s), make(s, 8)
    set_seat(s, first, USERS[0], "south")
    with pytest.raises(Conflict, match="already_at_other_table"):
        set_seat(s, second, USERS[0], "west")
    assert members(s, first) == [(USERS[0].id,"south")] and members(s, second) == []


def test_started_table_blocks_new_or_changed_seat_but_same_wind_remains_noop(setup):
    s, _ = setup
    table = make(s)
    set_seat(s, table, USERS[0], "east")
    with s.store.connect() as db:
        db.scalar(select(TableState).where(TableState.table_id == table["score_table_id"])).started_at = s.clock()
    assert set_seat(s, table, USERS[0], "east")["seat_action"] == "unchanged"
    for user in USERS[:2]:
        with pytest.raises(Conflict, match="table_already_started"):
            set_seat(s, table, user, "south")
    assert members(s, table) == [(USERS[0].id,"east")]


def test_stale_match_and_pending_settlement_cannot_change_seats(setup):
    s, _ = setup
    table = make(s)
    with pytest.raises(Conflict, match="stale_match"):
        set_seat(s, table, USERS[0], "east", match_id="previous-match")
    with s.store.connect() as db:
        db.scalar(select(TableState).where(TableState.table_id == table["score_table_id"])).pending_match_id = "pending"
    with pytest.raises(Conflict, match="settlement_pending"):
        set_seat(s, table, USERS[0], "east")
    assert members(s, table) == []


def test_missing_closed_and_tournament_tables_rejected(setup):
    s, _ = setup
    with pytest.raises(Conflict, match="table_not_found"):
        s.set_my_seat("missing", {"seat":"east"}, USERS[0])
    table = make(s)
    s.update(table["id"], {"status":"closed"}, ADMIN)
    with pytest.raises(Conflict, match="table_closed"):
        set_seat(s, table, USERS[0], "east")
    tid, assigned = waiting(s.tournaments)
    with pytest.raises(Conflict, match="fixed_tournament_seating"):
        s.set_my_seat(assigned["table_id"], {"seat":"east"}, USERS[0])
    with s.store.connect() as db:
        db.get(Tournament, tid).deleted_at = s.clock()
    with pytest.raises(Conflict, match="tournament_deleted"):
        s.set_my_seat(assigned["table_id"], {"seat":"east"}, USERS[0])


def test_legacy_score_ids_resolve_to_existing_registry(setup):
    s, _ = setup
    s.matches.sit("legacy-card-table", "east", USERS[1])
    response = s.set_my_seat("legacy-card-table", {"seat":"south"}, USERS[0])
    assert response["table"] == "legacy-card-table" and response["players"]["south"]["id"] == USERS[0].id
    with s.store.connect() as db:
        table = db.scalar(select(ClubTable).where(ClubTable.score_table_id == "legacy-card-table"))
        assert db.get(ActiveTableMember, USERS[0].id).table_id == table.id


def test_cookie_auth_global_return_and_csrf(setup):
    s, app = setup
    table = make(s)
    url = "/api/club-tables/" + table["id"] + "/my-seat"
    client = TestClient(app)
    response = client.put(url, json={"seat":"east"}, headers={"Referer":"http://testserver/score?table="+table["id"]})
    assert response.status_code == 401 and "login" in response.headers["location"]
    assert table["id"] in response.headers["location"]
    client.cookies.set("session_id", "demo-1")
    for headers in ({"Origin":"https://evil.invalid"}, {"Referer":"https://evil.invalid/x"}, {"Sec-Fetch-Site":"cross-site"}):
        blocked = client.put(url, json={"seat":"east"}, headers=headers)
        assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "untrusted_origin"
    assert members(s, table) == []
    assert client.put(url, json={"seat":"east"}, headers={"Authorization":"Bearer forged"}).status_code == 401
    accepted = client.put(url, json={"seat":"east","user_id":"victim"}, headers={"Origin":"http://testserver"})
    assert accepted.status_code == 200 and accepted.json()["players"]["east"]["id"] == "u1"


def test_anonymous_map_has_real_occupancy_without_account_data(setup):
    s, app = setup
    table = make(s)
    set_seat(s, table, USERS[0], "west")
    client = TestClient(app)
    assert client.get("/api/tables/"+table["score_table_id"]).status_code == 401
    result = client.get("/api/club-tables/"+table["id"]+"/seat-map")
    assert result.status_code == 200
    public = result.json()
    assert set(public) == {"table","display_name","seat_order","players","started_at","elapsed_seconds","average_duration_seconds"}
    assert public["players"] == {"east":None,"south":None,"west":{"occupied":True},"north":None}
    assert USERS[0].id not in result.text and USERS[0].name not in result.text
    assert "match_id" not in public and "seats" not in public
    with s.store.connect() as db:
        db.get(ClubTable, table["id"]).status = "closed"
    assert client.get("/api/club-tables/"+table["id"]+"/seat-map").status_code == 409
    assert client.get("/api/club-tables/missing/seat-map").status_code == 409


def test_valid_entry_qr_source_preserved_and_other_token_bindings_rejected(setup):
    s, _ = setup
    table, other = make(s), make(s,8)
    entry = token(s, table)
    for invalid in [token(s, other), token(s, table, purpose="seat_join", seat="north")]:
        with pytest.raises(Conflict, match="invalid_join_token"):
            set_seat(s, table, USERS[0], "east", entry_token=raw(invalid))
    set_seat(s, table, USERS[0], "east", entry_token=raw(entry))
    with s.store.connect() as db:
        joined_at = db.get(ActiveTableMember, USERS[0].id).joined_at
        assert db.get(TableJoinToken, entry["id"]).use_count == 1
    set_seat(s, table, USERS[0], "south", entry_token=raw(entry))
    with s.store.connect() as db:
        member = db.get(ActiveTableMember, USERS[0].id)
        assert member.join_method == "qr_entry" and member.joined_at == joined_at
        assert db.get(TableJoinToken, entry["id"]).use_count == 1
        changed = db.scalar(select(TableMembershipEvent).where(TableMembershipEvent.action == "seat_changed"))
        assert changed.join_method == "seat_card"
    s.revoke_token(entry["id"], ADMIN)
    with pytest.raises(Conflict, match="invalid_join_token"):
        set_seat(s, table, USERS[0], "west", entry_token=raw(entry))
    assert members(s, table) == [(USERS[0].id,"south")]


def test_seat_card_claims_still_have_database_unique_constraints(setup):
    s, _ = setup
    table, other = make(s), make(s,8)
    set_seat(s, table, USERS[0], "east")
    with pytest.raises(IntegrityError):
        with s.store.connect() as db:
            db.add(ActiveTableMember(user_id=USERS[1].id, table_id=table["id"], match_id=table["current_match_id"],
                joined_at=s.clock(), join_method="seat_card", added_by_user_id=USERS[1].id, seat="east"))
    with pytest.raises(IntegrityError):
        with s.store.connect() as db:
            db.add(ActiveTableMember(user_id=USERS[0].id, table_id=other["id"], match_id=other["current_match_id"],
                joined_at=s.clock(), join_method="seat_card", added_by_user_id=USERS[0].id, seat="west"))
    with pytest.raises(IntegrityError):
        with s.store.connect() as db:
            db.add(SeatRecord(table_id=table["score_table_id"], seat="south", user_id=USERS[0].id, user_name=USERS[0].name))


def _seat_in_process(args):
    """Independent interpreters cannot share membership_lock."""
    from mahjong_api.config import Settings
    from mahjong_api.service import MatchService
    from mahjong_api.sheets import DisabledSheets
    from mahjong_api.store import Store
    from mahjong_api.table_service import TableService
    from mahjong_api.tournament import TournamentService
    path, table_id, uid, seat, barrier = args
    settings = Settings(database_path=Path(path))
    store = Store(settings.database_path)
    try:
        matches = MatchService(store, DisabledSheets(), settings)
        tables = TableService(matches, TournamentService(store, matches.external))
        barrier.wait(timeout=30)
        try:
            result = tables.set_my_seat(table_id, {"seat":seat}, User(id=uid,name=uid))
            return {"action":result["seat_action"], "seat":seat}
        except Conflict as error:
            return {"error":error.detail["code"]}
    finally:
        store.close()


def race(service, calls):
    with Manager() as manager:
        barrier = manager.Barrier(len(calls))
        arguments = [(str(service.store.path),table_id,user.id,seat,barrier) for table_id,user,seat in calls]
        with ProcessPoolExecutor(len(calls)) as pool:
            return list(pool.map(_seat_in_process, arguments))


@pytest.mark.parametrize("prefill", [0,3])
def test_processes_claim_same_empty_wind_only_one_wins(setup, prefill):
    s, _ = setup
    table = make(s)
    for user, wind in zip(USERS[2:2+prefill], ("south","west","north")):
        set_seat(s, table, user, wind)
    results = race(s, [(table["id"],u,"east") for u in USERS[:2]])
    assert sum(r.get("action") == "joined" for r in results) == 1
    assert sum(r.get("error") == "seat_occupied" for r in results) == 1
    assert len(members(s, table)) == prefill + 1


def test_processes_move_to_same_free_wind_loser_keeps_original(setup):
    s, _ = setup
    table = make(s)
    for user, seat in zip(USERS[:2], ("east","south")):
        set_seat(s, table, user, seat)
    results = race(s, [(table["id"],u,"west") for u in USERS[:2]])
    assert sum(r.get("action") == "moved" for r in results) == 1
    assert sum(r.get("error") == "seat_occupied" for r in results) == 1
    winds = dict(members(s, table))
    assert len(winds) == 2 and len(set(winds.values())) == 2 and "west" in winds.values()
    loser = next(i for i,r in enumerate(results) if "error" in r)
    assert winds[USERS[loser].id] == ("east","south")[loser]


def test_processes_same_user_can_claim_only_one_table(setup):
    s, _ = setup
    tables = [make(s),make(s,8)]
    results = race(s, [(t["id"],USERS[0],"north") for t in tables])
    assert sum(r.get("action") == "joined" for r in results) == 1
    assert sum(r.get("error") == "already_at_other_table" for r in results) == 1
    assert sum(len(members(s,t)) for t in tables) == 1


def test_processes_same_user_same_wind_is_idempotent(setup):
    s, _ = setup
    table = make(s)
    results = race(s, [(table["id"],USERS[0],"south")]*2)
    assert {r.get("action") for r in results} == {"joined","unchanged"}
    with s.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TableMembershipEvent)) == 1
        assert db.scalar(select(func.count()).select_from(SeatRecord)) == 1


def test_processes_one_user_moves_without_duplicate_or_left_members(setup):
    s, _ = setup
    table = make(s)
    set_seat(s, table, USERS[0], "east")
    results = race(s, [(table["id"],USERS[0],wind) for wind in ("west","north")])
    assert all(r.get("action") == "moved" for r in results)
    with s.store.connect() as db:
        active = db.get(ActiveTableMember, USERS[0].id)
        seat = db.scalar(select(SeatRecord).where(SeatRecord.user_id == USERS[0].id))
        assert active.seat == seat.seat and seat.seat in {"west","north"}
        assert db.scalar(select(func.count()).select_from(ActiveTableMember)) == 1
        assert db.scalar(select(func.count()).select_from(SeatRecord)) == 1
        assert db.scalar(select(func.count()).select_from(TableMembershipEvent).where(TableMembershipEvent.action == "left")) == 0
