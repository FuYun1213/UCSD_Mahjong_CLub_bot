"""Consent, expiry, stale membership, migrations, and real multi-process races."""
import copy
import json
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from multiprocessing import Manager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from mahjong_api.auth import get_current_user
from mahjong_api.database_models import Metadata, SeatRecord, TableState
from mahjong_api.models import User
from mahjong_api.seat_swap_models import SeatSwapRequest, SeatSwapClaim
from mahjong_api.seat_swap_service import SeatSwapService
from mahjong_api.store import Conflict, Store
from mahjong_api.table_models import ActiveTableMember, ClubTable, TableMembershipEvent
from mahjong_api.tournament_models import TournamentAudit
from test_table_v3 import setup, make, data, ADMIN, USERS


@pytest.fixture
def swap(setup):
    tables, app = setup
    swaps = SeatSwapService(tables)
    app.state.seat_swaps = swaps
    table = make(tables)
    for user, wind in zip(USERS[:2], ("east", "south")):
        tables.set_my_seat(table["id"], {"seat":wind}, user)
    return swaps, tables, table, app


def request(swaps, table, requester=USERS[0], target=USERS[1]):
    return swaps.create(table["id"], {"target_user_id":target.id}, requester)["request"]


def seats(tables, table):
    return tables.matches.table(table["score_table_id"])["seats"]


def assert_claims(tables, expected):
    with tables.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(SeatSwapClaim)) == expected


def test_only_consent_swaps_both_models_preserving_original_membership(swap):
    swaps, tables, table, _ = swap
    before = seats(tables, table)
    with tables.store.connect() as db:
        originals = {r.user_id:(r.membership_id,r.joined_at,r.join_method,r.seat_version) for r in db.scalars(select(ActiveTableMember))}
    row = request(swaps, table)
    assert row["status"] == "pending" and row["can_cancel"] and not row["can_accept"]
    assert row["requester"] == {"id":USERS[0].id,"name":USERS[0].name,"seat":"east"}
    assert seats(tables, table) == before
    assert_claims(tables,2)
    accepted = swaps.respond(row["id"], "accept", USERS[1])
    assert accepted["request"]["status"] == "accepted" and accepted["request"]["responded_at"]
    assert accepted["table_state"]["seats"] == {"east":USERS[1].id,"south":USERS[0].id,"west":None,"north":None}
    with tables.store.connect() as db:
        for member in db.scalars(select(ActiveTableMember)):
            assert (member.membership_id,member.joined_at,member.join_method) == originals[member.user_id][:3]
            assert member.seat_version == originals[member.user_id][3]+1
            assert db.get(SeatRecord,(table["score_table_id"],member.seat)).user_id == member.user_id
        events = list(db.scalars(select(TableMembershipEvent).where(TableMembershipEvent.action == "seat_swapped")))
        assert len(events) == 2 and all(e.actor_id == USERS[1].id for e in events)
        audit = db.scalar(select(TournamentAudit).where(TournamentAudit.action == "seat_swap_accepted"))
        detail = json.loads(audit.detail_json)
        assert detail["requester_new_seat"] == "south" and detail["target_new_seat"] == "east"
        assert detail["requested_at"] and detail["accepted_at"] and detail["status"] == "accepted"
    assert_claims(tables,0)
    repeated = swaps.respond(row["id"], "accept", USERS[1])
    assert repeated["request"]["status"] == "accepted" and repeated["table_state"]["seats"] == accepted["table_state"]["seats"]
    with tables.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TournamentAudit).where(TournamentAudit.action == "seat_swap_accepted")) == 1


@pytest.mark.parametrize("action,actor,status", [("decline",USERS[1],"declined"),("cancel",USERS[0],"cancelled")])
def test_terminal_no_exchange_responses_are_idempotent(swap, action, actor, status):
    swaps, tables, table, _ = swap
    row = request(swaps,table)
    before = seats(tables,table)
    assert swaps.respond(row["id"],action,actor)["request"]["status"] == status
    assert swaps.respond(row["id"],action,actor)["request"]["status"] == status
    assert seats(tables,table) == before
    assert_claims(tables,0)
    with pytest.raises(Conflict,match="swap_not_pending"):
        swaps.respond(row["id"],"accept",USERS[1])


def test_target_only_and_requester_identity_is_never_from_body(swap):
    swaps, tables, table, _ = swap
    row = swaps.create(table["id"], {"targetUserId":USERS[1].id,"requester_user_id":ADMIN.id,
        "requester_seat":"north","target_seat":"west"}, USERS[0])["request"]
    assert row["requester"]["id"] == USERS[0].id and row["requester"]["seat"] == "east"
    for actor in (USERS[0],USERS[2],ADMIN):
        for action in ("accept","decline"):
            with pytest.raises(Conflict,match="swap_not_target"):
                swaps.respond(row["id"],action,actor)
    with pytest.raises(Conflict,match="swap_not_requester"):
        swaps.respond(row["id"],"cancel",USERS[1])
    assert seats(tables,table)["east"] == USERS[0].id


def test_self_unseated_other_table_and_missing_target_rejected(swap):
    swaps, tables, table, _ = swap
    for source,target,code in [(USERS[0],USERS[0],"swap_self"),(USERS[2],USERS[1],"must_join_first"),
                              (USERS[0],USERS[2],"swap_target_not_at_table")]:
        with pytest.raises(Conflict,match=code):
            request(swaps,table,source,target)
    other = make(tables,8)
    tables.set_my_seat(other["id"],{"seat":"west"},USERS[2])
    with pytest.raises(Conflict,match="already_at_other_table"):
        request(swaps,table,USERS[2],USERS[1])
    assert_claims(tables,0)


def test_pending_requests_deduplicate_and_cross_role_claims_block_conflicts(swap):
    swaps, tables, table, _ = swap
    tables.set_my_seat(table["id"],{"seat":"west"},USERS[2])
    row = request(swaps,table)
    assert request(swaps,table)["id"] == row["id"]
    for source,target in [(USERS[1],USERS[0]),(USERS[2],USERS[1]),(USERS[0],USERS[2]),(USERS[1],USERS[2])]:
        with pytest.raises(Conflict,match="swap_pending"):
            request(swaps,table,source,target)
    assert_claims(tables,2)
    with tables.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(SeatSwapRequest)) == 1


@pytest.mark.parametrize("seconds,expired", [(59.999,False),(60,True),(61,True)])
def test_server_expiry_boundary_and_released_claims(swap, seconds, expired):
    swaps, tables, table, _ = swap
    base = datetime(2026,9,19,20,tzinfo=timezone.utc)
    swaps.clock = lambda:base.isoformat()
    row = request(swaps,table)
    swaps.clock = lambda:(base+timedelta(seconds=seconds)).isoformat()
    if expired:
        with pytest.raises(Conflict,match="swap_expired"):
            swaps.respond(row["id"],"accept",USERS[1])
        with tables.store.connect() as db:
            assert db.get(SeatSwapRequest,row["id"]).status == "expired"
        assert_claims(tables,0)
        assert request(swaps,table)["id"] != row["id"]
    else:
        assert swaps.respond(row["id"],"accept",USERS[1])["request"]["status"] == "accepted"


@pytest.mark.parametrize("change", ["move_requester","move_target","move_back","leave_rejoin","legacy_move_back","reset","start","close"])
def test_old_request_invalidated_after_membership_or_table_changes(swap, change):
    swaps, tables, table, _ = swap
    row = request(swaps,table)
    if change in {"move_requester","move_target","move_back"}:
        person = USERS[1] if change == "move_target" else USERS[0]
        tables.set_my_seat(table["id"],{"seat":"west"},person)
        if change == "move_back":
            tables.set_my_seat(table["id"],{"seat":"east"},person)
    elif change == "legacy_move_back":
        tables.join(table["id"],USERS[0],"west")
        tables.join(table["id"],USERS[0],"east")
    elif change == "leave_rejoin":
        tables.leave(table["id"],USERS[0])
        tables.set_my_seat(table["id"],{"seat":"east"},USERS[0])
    elif change == "reset":
        tables.reset(table["id"],data(reason="test reset"),ADMIN)
    elif change == "start":
        tables.set_my_seat(table["id"],{"seat":"west"},USERS[2])
        tables.set_my_seat(table["id"],{"seat":"north"},USERS[3])
    elif change == "close":
        with tables.store.connect() as db:
            db.get(ClubTable,table["id"]).status = "closed"
    before = seats(tables,table)
    with pytest.raises(Conflict,match="swap_invalidated"):
        swaps.respond(row["id"],"accept",USERS[1])
    assert seats(tables,table) == before
    with tables.store.connect() as db:
        assert db.get(SeatSwapRequest,row["id"]).status == "invalidated"
    assert_claims(tables,0)


def test_revision_snapshot_rejects_move_away_and_back_even_without_invalidation_hook(swap, monkeypatch):
    import mahjong_api.seat_swap_state as state
    swaps, tables, table, _ = swap
    row = request(swaps,table)
    monkeypatch.setattr(state,"invalidate_swaps",lambda *a,**kw:None)
    tables.set_my_seat(table["id"],{"seat":"west"},USERS[0])
    tables.set_my_seat(table["id"],{"seat":"east"},USERS[0])
    with pytest.raises(Conflict,match="swap_invalidated"):
        swaps.respond(row["id"],"accept",USERS[1])
    assert seats(tables,table)["east"] == USERS[0].id


def test_membership_identity_rejects_leave_rejoin_even_when_timestamp_unchanged(swap, monkeypatch):
    import mahjong_api.seat_swap_state as state
    swaps, tables, table, _ = swap
    row = request(swaps,table)
    with tables.store.connect() as db:
        before = db.get(ActiveTableMember,USERS[0].id).joined_at
    monkeypatch.setattr(state,"invalidate_swaps",lambda *a,**kw:None)
    tables.leave(table["id"],USERS[0])
    tables.set_my_seat(table["id"],{"seat":"east"},USERS[0])
    with tables.store.connect() as db:
        db.get(ActiveTableMember,USERS[0].id).joined_at = before
    with pytest.raises(Conflict,match="swap_invalidated"):
        swaps.respond(row["id"],"accept",USERS[1])


def test_admin_adjustment_invalidates_existing_request(swap):
    swaps, tables, table, _ = swap
    row = request(swaps,table)
    tables.add_players(table["id"],data(user_ids=[USERS[2].id]),ADMIN)
    with tables.store.connect() as db:
        assert db.get(SeatSwapRequest,row["id"]).status == "invalidated"


def test_started_and_pending_score_reject_create(swap):
    swaps, tables, table, _ = swap
    for field,code in (("started_at","table_already_started"),("pending_match_id","settlement_pending")):
        with tables.store.connect() as db:
            score = db.scalar(select(TableState).where(TableState.table_id == table["score_table_id"]))
            score.started_at = None
            score.pending_match_id = None
            setattr(score,field,"in-progress")
        with pytest.raises(Conflict,match=code):
            request(swaps,table)


def test_failed_exchange_rolls_back_seats_revisions_audit_and_claims(swap, monkeypatch):
    import mahjong_api.seat_swap_service as module
    swaps, tables, table, _ = swap
    row = request(swaps,table)
    before = seats(tables,table)
    def fail(*args,**kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(module,"finish_swap",fail)
    with pytest.raises(RuntimeError,match="audit unavailable"):
        swaps.respond(row["id"],"accept",USERS[1])
    assert seats(tables,table) == before
    assert_claims(tables,2)
    with tables.store.connect() as db:
        assert db.get(SeatSwapRequest,row["id"]).status == "pending"
        assert all(m.seat_version == 1 for m in db.scalars(select(ActiveTableMember)))
        assert db.scalar(select(func.count()).select_from(TableMembershipEvent).where(TableMembershipEvent.action == "seat_swapped")) == 0


def test_poll_is_private_bounded_dynamic_names_and_expiry_is_swept_separately(swap):
    swaps, tables, table, _ = swap
    base = datetime.now(timezone.utc)
    for i in range(23):
        swaps.clock = lambda i=i:(base+timedelta(seconds=i)).isoformat()
        row = request(swaps,table)
        swaps.respond(row["id"],"decline",USERS[1])
    latest = request(swaps,table)
    original_lookup = tables.account_lookup
    tables.account_lookup = lambda ids:[{**p,"name":"New registered name"} if p["id"] == USERS[0].id else p for p in original_lookup(ids)]
    view = swaps.list(table["id"],USERS[1])
    assert len(view["requests"]) == 20
    assert next(r for r in view["requests"] if r["id"] == latest["id"])["requester"]["name"] == "New registered name"
    assert swaps.list(table["id"],USERS[2])["requests"] == []
    swaps.clock = lambda:(base+timedelta(minutes=10)).isoformat()
    expired = swaps.list(table["id"],USERS[0])
    assert len(expired["requests"]) == 1 and expired["requests"][0]["status"] == "expired"
    assert_claims(tables,2)
    assert swaps.sweep_due() == 1
    assert swaps.sweep_due() == 0
    assert_claims(tables,0)


def test_pending_claims_and_pair_have_database_constraints(swap):
    swaps, tables, table, _ = swap
    row = request(swaps,table)
    with pytest.raises(IntegrityError):
        with tables.store.connect() as db:
            db.add(SeatSwapClaim(user_id=USERS[0].id,request_id=row["id"]))
    with pytest.raises(IntegrityError):
        with tables.store.connect() as db:
            original = db.get(SeatSwapRequest,row["id"])
            values = {c.name:getattr(original,c.name) for c in SeatSwapRequest.__table__.columns}
            values["id"] = str(uuid4())
            db.add(SeatSwapRequest(**values))


def test_api_authorization_origin_and_real_target_only(swap):
    swaps, tables, table, app = swap
    client = TestClient(app)
    path = "/api/tables/"+table["score_table_id"]+"/seat-swap-requests"
    assert client.get(path).status_code == 401
    assert client.post(path,json={"target_user_id":USERS[1].id}).status_code == 401
    app.dependency_overrides[get_current_user] = lambda:USERS[0]
    assert client.post(path,json={"target_user_id":USERS[1].id},headers={"Origin":"https://evil.invalid"}).status_code == 403
    created = client.post(path,json={"target_user_id":USERS[1].id,"requester_user_id":ADMIN.id})
    assert created.status_code == 200,created.text
    rid = created.json()["request"]["id"]
    assert client.post("/api/seat-swap-requests/"+rid+"/accept",json={}).status_code == 403
    app.dependency_overrides[get_current_user] = lambda:USERS[1]
    assert client.post("/api/seat-swap-requests/"+rid+"/accept",json={}).status_code == 200


def _swap_process(arguments):
    from mahjong_api.config import Settings
    from mahjong_api.service import MatchService
    from mahjong_api.sheets import DisabledSheets
    from mahjong_api.table_service import TableService
    from mahjong_api.tournament import TournamentService
    path, table_id, actor, operation, value, barrier = arguments
    store = Store(Path(path))
    try:
        settings = Settings(database_path=Path(path))
        matches = MatchService(store,DisabledSheets(),settings)
        tables = TableService(matches,TournamentService(store,matches.external))
        swaps = SeatSwapService(tables)
        user = User(id=actor,name=actor,role="admin" if actor == ADMIN.id else "user")
        barrier.wait(timeout=30)
        try:
            if operation == "create":
                return swaps.create(table_id,{"target_user_id":value},user)["request"]
            if operation == "move":
                return tables.set_my_seat(table_id,{"seat":value},user)
            if operation == "reset":
                return tables.reset(table_id,data(reason="concurrent reset"),user)
            if operation == "sweep":
                swaps.clock = lambda:value
                return {"expired":swaps.sweep_due(limit=1)}
            return swaps.respond(value,operation,user)["request"]
        except Conflict as error:
            return {"error":error.detail["code"]}
    finally:
        store.close()


def race(tables,table,calls):
    with Manager() as manager:
        barrier = manager.Barrier(len(calls))
        args = [(str(tables.store.path),table["id"],user.id,operation,value,barrier) for user,operation,value in calls]
        with ProcessPoolExecutor(len(calls)) as pool:
            return list(pool.map(_swap_process,args))


@pytest.mark.parametrize("mode",["reciprocal","same_target","cross_role"])
def test_independent_processes_cannot_create_conflicting_pending_requests(swap,mode):
    swaps,tables,table,_ = swap
    tables.set_my_seat(table["id"],{"seat":"west"},USERS[2])
    other = (USERS[1],"create",USERS[0].id) if mode == "reciprocal" else (USERS[2],"create",USERS[1].id) if mode == "same_target" else (USERS[1],"create",USERS[2].id)
    result = race(tables,table,[(USERS[0],"create",USERS[1].id),other])
    assert sum(r.get("status") == "pending" for r in result) == 1
    assert sum(r.get("error") == "swap_pending" for r in result) == 1
    assert_claims(tables,2)


def test_independent_processes_accept_exactly_once(swap):
    swaps,tables,table,_ = swap
    row = request(swaps,table)
    results = race(tables,table,[(USERS[1],"accept",row["id"])]*2)
    assert all(r.get("status") == "accepted" for r in results)
    assert seats(tables,table)["east"] == USERS[1].id
    with tables.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TournamentAudit).where(TournamentAudit.action == "seat_swap_accepted")) == 1


def test_independent_accept_and_move_never_exchange_stale_members(swap):
    swaps,tables,table,_ = swap
    row = request(swaps,table)
    results = race(tables,table,[(USERS[1],"accept",row["id"]),(USERS[1],"move","west")])
    final = seats(tables,table)
    assert final["west"] == USERS[1].id
    if results[0].get("status") == "accepted":
        assert final["south"] == USERS[0].id
    else:
        assert results[0]["error"] == "swap_invalidated" and final["east"] == USERS[0].id
    with tables.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ActiveTableMember)) == 2


def test_independent_accept_and_admin_reset_remain_atomic(swap):
    swaps,tables,table,_ = swap
    row = request(swaps,table)
    results = race(tables,table,[(USERS[1],"accept",row["id"]),(ADMIN,"reset",None)])
    assert results[0].get("status") == "accepted" or results[0].get("error") == "swap_invalidated"
    assert all(value is None for value in seats(tables,table).values())
    assert_claims(tables,0)


def test_formal_migration_preserves_pre_swap_members_and_is_idempotent(swap,tmp_path):
    swaps,tables,table,_ = swap
    target = tmp_path/"before-seat-swaps.sqlite3"
    with sqlite3.connect(tables.store.path) as source,sqlite3.connect(target) as db:
        source.backup(db)
        db.execute("PRAGMA foreign_keys=OFF")
        columns = "user_id,table_id,match_id,joined_at,join_method,added_by_user_id,seat,status,left_at"
        before = db.execute("SELECT "+columns+" FROM active_table_members ORDER BY user_id").fetchall()
        before_seats = db.execute("SELECT * FROM nfc_seats ORDER BY user_id").fetchall()
        db.execute("DROP TABLE seat_swap_claims")
        db.execute("DROP TABLE seat_swap_requests")
        db.execute("DROP TABLE active_table_members")
        db.execute("CREATE TABLE active_table_members (user_id VARCHAR(128) PRIMARY KEY,table_id VARCHAR(64) NOT NULL,match_id VARCHAR(64) NOT NULL,joined_at VARCHAR(40) NOT NULL,join_method VARCHAR(16) NOT NULL,added_by_user_id VARCHAR(128) NOT NULL,seat VARCHAR(5),status VARCHAR(16) NOT NULL,left_at VARCHAR(40),UNIQUE(table_id,seat))")
        db.executemany("INSERT INTO active_table_members ("+columns+") VALUES (?,?,?,?,?,?,?,?,?)",before)
        db.execute("DELETE FROM nfc_metadata WHERE key='seat_swap_v1_migrated'")
        db.commit()
    upgraded = Store(target)
    try:
        with upgraded.connect() as db:
            assert [tuple(row) for row in db.execute(text("SELECT "+columns+" FROM active_table_members ORDER BY user_id"))] == before
            assert [tuple(row) for row in db.execute(text("SELECT * FROM nfc_seats ORDER BY user_id"))] == before_seats
            identities = {m.user_id:m.membership_id for m in db.scalars(select(ActiveTableMember))}
            assert len(set(identities.values())) == 2
        from mahjong_api.migrations import migrate
        migrate(upgraded.engine)
        with upgraded.connect() as db:
            assert {m.user_id:m.membership_id for m in db.scalars(select(ActiveTableMember))} == identities
            assert db.get(Metadata,"seat_swap_v1_migrated")
            assert db.scalar(select(func.count()).select_from(SeatSwapRequest)) == 0
    finally:
        upgraded.close()


@pytest.mark.parametrize("expired", [False, True])
def test_polling_issues_no_sql_writes_and_never_reconciles_rows(swap, expired, monkeypatch):
    from sqlalchemy import event
    swaps, tables, table, app = swap
    # Isolate the GET from the app's independent scheduled workers. A reminder
    # tick can legitimately update queue rows while this SQL trace is active.
    monkeypatch.setattr(swaps, "sweep_due", lambda limit=50: 0)
    monkeypatch.setattr(app.state.discord_reminders, "tick", lambda limit=10: 0)
    monkeypatch.setattr(app.state.manual_scores, "flush", lambda: None)
    monkeypatch.setattr(app.state.service.external, "flush", lambda: None)
    base = datetime.now(timezone.utc)
    swaps.clock = lambda:base.isoformat()
    row = request(swaps, table)
    if expired:
        swaps.clock = lambda:(base + timedelta(seconds=61)).isoformat()
    statements = []
    def trace(conn, cursor, statement, parameters, context, many):
        statements.append(statement.strip().split(None, 1)[0].upper())
    event.listen(tables.store.engine, "before_cursor_execute", trace)
    try:
        app.dependency_overrides[get_current_user] = lambda:USERS[1]
        result = TestClient(app).get("/api/tables/" + table["score_table_id"] + "/seat-swap-requests")
    finally:
        event.remove(tables.store.engine, "before_cursor_execute", trace)
    assert result.status_code == 200, result.text
    assert statements and not set(statements) & {"UPDATE", "INSERT", "DELETE", "REPLACE"}
    projected = result.json()["requests"][0]
    assert projected["status"] == ("expired" if expired else "pending")
    assert projected["can_accept"] is not expired
    with tables.store.connect() as db:
        assert db.get(SeatSwapRequest, row["id"]).status == "pending"
    assert_claims(tables, 2)
    if expired:
        before = seats(tables, table)
        with pytest.raises(Conflict, match="swap_expired"):
            swaps.respond(row["id"], "accept", USERS[1])
        assert seats(tables, table) == before
        assert_claims(tables, 0)


def test_background_expiry_is_bounded_and_cannot_undo_accepted_swaps(swap):
    swaps, tables, table, _ = swap
    base = datetime.now(timezone.utc)
    swaps.clock = lambda:base.isoformat()
    accepted = request(swaps, table)
    swaps.respond(accepted["id"], "accept", USERS[1])
    pending = request(swaps, table)
    other = make(tables, 42)
    tables.set_my_seat(other["id"], {"seat":"east"}, USERS[2])
    tables.set_my_seat(other["id"], {"seat":"south"}, USERS[3])
    second = request(swaps, other, USERS[2], USERS[3])
    swaps.clock = lambda:(base + timedelta(seconds=61)).isoformat()
    before = seats(tables, table)
    assert swaps.sweep_due(limit=0) == 0
    assert swaps.sweep_due(limit=1) == 1
    assert_claims(tables, 2)
    assert swaps.sweep_due(limit=1) == 1
    assert swaps.sweep_due(limit=1) == 0
    assert seats(tables, table) == before
    assert_claims(tables, 0)
    with tables.store.connect() as db:
        assert db.get(SeatSwapRequest, accepted["id"]).status == "accepted"
        assert all(db.get(SeatSwapRequest, rid).status == "expired" for rid in (pending["id"], second["id"]))


def test_swap_accept_does_not_invoke_history_or_current_sync(swap, monkeypatch):
    swaps, tables, table, _ = swap
    row = request(swaps, table)
    def forbidden_sync():
        raise AssertionError("Seat swaps must not wait for historical deliveries")
    monkeypatch.setattr(tables.matches, "flush", forbidden_sync)
    result = swaps.respond(row["id"], "accept", USERS[1])
    assert result["request"]["status"] == "accepted"
    with tables.store.connect() as db:
        state = db.scalar(select(TableState).where(TableState.table_id == table["score_table_id"]))
        assert state.dirty == 0



def test_independent_expiry_worker_and_accept_have_one_terminal_result(swap):
    swaps, tables, table, _ = swap
    row = request(swaps, table)
    later = (datetime.fromisoformat(row["expires_at"]) + timedelta(seconds=1)).isoformat()
    results = race(tables, table, [(USERS[1], "accept", row["id"]), (ADMIN, "sweep", later)])
    with tables.store.connect() as db:
        terminal = db.get(SeatSwapRequest, row["id"]).status
        assert terminal in {"accepted", "expired"}
        assert db.scalar(select(func.count()).select_from(TournamentAudit).where(
            TournamentAudit.action.in_(["seat_swap_accepted", "seat_swap_expired"]))) == 1
    assert_claims(tables, 0)
    if terminal == "accepted":
        assert results[0]["status"] == "accepted" and results[1]["expired"] == 0
        assert seats(tables, table)["east"] == USERS[1].id
    else:
        assert results[0]["error"] == "swap_expired" and results[1]["expired"] == 1
        assert seats(tables, table)["east"] == USERS[0].id
