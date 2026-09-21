"""Five bound QR codes, explicit winds, and multi-user reservation invariants."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from mahjong_api.auth import get_current_user
from mahjong_api.database_models import Metadata
from mahjong_api.models import SEATS, User
from mahjong_api.store import Conflict
from mahjong_api.table_models import ActiveTableMember, ReservationParticipant, TableJoinToken, TableMembershipEvent
from mahjong_api.tournament_models import TournamentAudit
from test_table_v3 import setup, make, data, token, raw, ADMIN, USERS
from test_tournament_v2 import waiting


def reserve(s, table, **fields):
    return s.reserve(table["id"], data(month=9, day=20, time="18:30", participant_ids=[USERS[0].id], **fields), USERS[0])


def seat_token(s, table, seat):
    return token(s, table, purpose="seat_join", seat=seat)


def outcome(call):
    try:
        return call()
    except Conflict as error:
        return error.detail["code"]


def test_five_independent_tokens_hashes_and_landing_never_claims(setup):
    s, _ = setup
    table = make(s)
    entries = [token(s, table)] + [seat_token(s, table, wind) for wind in SEATS]
    assert len({entry["path"] for entry in entries}) == 5
    assert s.token_info(raw(entries[0]))["purpose"] == "table_landing"
    assert s.token_info(raw(entries[0]))["members"] == []
    assert s.join_token(raw(entries[0]), USERS[0], "landing")["joined"] is False
    assert s.get(table["id"], USERS[0])["player_count"] == 0
    seat_token(s, table, "south")
    with pytest.raises(Conflict, match="invalid_join_token"):
        s.token_info(raw(entries[2]))
    for entry in [entries[0], entries[1], entries[3], entries[4]]:
        assert s.token_info(raw(entry))["table_id"] == table["id"]
    with s.store.connect() as db:
        rows = list(db.scalars(select(TableJoinToken)))
        assert len(rows) == 6
        assert all(row.token_hash == hashlib.sha256(s._token_text(row.id).encode()).hexdigest() for row in rows)


@pytest.mark.parametrize("wind", SEATS)
def test_seat_token_is_server_bound_even_with_tampered_input(setup, wind):
    s, app = setup
    table = make(s)
    entry = seat_token(s, table, wind)
    app.dependency_overrides[get_current_user] = lambda: USERS[0]
    response = TestClient(app).post("/api/table-join-tokens/" + raw(entry) + "/join?seat=east", json=data(seat="north", table_id="forged"))
    assert response.status_code == 200
    assert response.json()["seat"] == wind
    member = s.get(table["id"], USERS[0])["members"][0]
    assert member["seat"] == wind and member["join_method"] == "qr_" + wind
    assert s.join_token(raw(entry), USERS[0], "repeat")["seat"] == wind
    assert s.get(table["id"], USERS[0])["player_count"] == 1


def test_no_overwrite_no_second_wind_or_silent_table_switch(setup):
    s, _ = setup
    table, other = make(s), make(s, 8)
    east, south = seat_token(s, table, "east"), seat_token(s, table, "south")
    s.join_token(raw(east), USERS[0], "east-first")
    for entry, user, error in [(east, USERS[1], "seat_occupied"), (south, USERS[0], "already_at_other_seat"),
                               (seat_token(s, other, "north"), USERS[0], "already_at_other_table")]:
        with pytest.raises(Conflict, match=error):
            s.join_token(raw(entry), user, "blocked")
    assert s.get(table["id"], USERS[0])["members"][0]["user_id"] == USERS[0].id


def test_database_serializes_scan_races_without_process_lock(setup, monkeypatch):
    import mahjong_api.table_service as service_module
    s, _ = setup
    table = make(s)
    entry = seat_token(s, table, "east")
    monkeypatch.setattr(service_module, "membership_lock", nullcontext())
    with ThreadPoolExecutor(2) as pool:
        values = list(pool.map(lambda user: outcome(lambda: s.join_token(raw(entry), user, "race-" + user.id)), USERS[:2]))
    assert sum(isinstance(result, dict) for result in values) == 1
    assert "seat_occupied" in values
    winner = next(result for result in values if isinstance(result, dict))
    uid = s.get(table["id"], USERS[0])["members"][0]["user_id"]
    user = next(u for u in USERS if u.id == uid)
    with ThreadPoolExecutor(2) as pool:
        replay = list(pool.map(lambda i: outcome(lambda: s.join_token(raw(entry), user, "replay-" + str(i))), range(2)))
    assert all(isinstance(value, dict) for value in replay)
    assert s.get(table["id"], user)["player_count"] == 1


def test_database_serializes_cross_table_claim_without_process_lock(setup, monkeypatch):
    import mahjong_api.table_service as service_module
    s, _ = setup
    tables = [make(s), make(s, 8)]
    entries = [seat_token(s, table, "west") for table in tables]
    monkeypatch.setattr(service_module, "membership_lock", nullcontext())
    with ThreadPoolExecutor(2) as pool:
        values = list(pool.map(lambda entry: outcome(lambda: s.join_token(raw(entry), USERS[0], "cross")), entries))
    assert sum(isinstance(value, dict) for value in values) == 1
    assert "already_at_other_table" in values


@pytest.mark.parametrize("wind", [None, *SEATS])
def test_each_qr_has_own_download_and_revocation(setup, wind):
    s, app = setup
    table = make(s)
    entry = token(s, table) if wind is None else seat_token(s, table, wind)
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    response = TestClient(app).get("/api/admin/table-tokens/" + entry["id"] + "/qr.png")
    assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
    assert "table-3-" + (wind or "entry") + ".png" in response.headers["content-disposition"]
    s.revoke_token(entry["id"], ADMIN)
    with pytest.raises(Conflict, match="invalid_join_token"):
        s.join_token(raw(entry), USERS[0], "revoked")


@pytest.mark.parametrize("body", [{"purpose":"seat_join"}, {"purpose":"seat_join","seat":"E"},
                                  {"purpose":"table_landing","seat":"east"}, {"purpose":"table_join"}])
def test_invalid_qr_bindings_rejected(setup, body):
    s, _ = setup
    table = make(s)
    with pytest.raises(Conflict):
        token(s, table, **body)


def test_started_game_rejects_new_scans_but_owner_repeat_works(setup):
    s, _ = setup
    table = make(s)
    entries = [seat_token(s, table, wind) for wind in SEATS]
    for entry, user in zip(entries, USERS):
        s.join_token(raw(entry), user, "initial-" + user.id)
    assert s.get(table["id"], USERS[0])["started_at"]
    assert s.join_token(raw(entries[0]), USERS[0], "repeat-after-start")["joined"]
    with pytest.raises(Conflict):
        s.join_token(raw(entries[0]), USERS[5], "too-late")


def test_tournament_qr_respects_assigned_wind_and_shared_transaction(setup):
    s, _ = setup
    tid, match = waiting(s.tournaments)
    table = s.get(match["table_id"], ADMIN)
    east = seat_token(s, table, "east")
    with pytest.raises(Conflict, match="seat_not_assigned"):
        s.join_token(raw(east), User(id=match["seats"][1], name="South"), "wrong-wind")
    person = User(id=match["seats"][0], name="East")
    s.join_token(raw(east), person, "correct-wind")
    assert s.get(table["id"], person)["members"][0]["seat"] == "east"
    s.revoke_token(east["id"], ADMIN)
    with pytest.raises(Conflict, match="invalid_join_token"):
        s.join_token(raw(east), person, "after-revoke")


def test_reservation_local_year_inference_edit_preserves_year_and_utc(setup):
    s, _ = setup
    table = make(s)
    s.clock = lambda: "2026-09-19T20:00:00+00:00"
    first = reserve(s, table)
    assert first["scheduled_at"] == "2026-09-21T01:30:00.000+00:00"
    s.clock = lambda: "2026-12-21T04:00:00+00:00"
    next_year = s.reserve(table["id"], data(month=1, day=5, time="18:00"), USERS[0])
    assert next_year["scheduled_at"].startswith("2027-01-06T02:00")
    edited = s.update_reservation(first["id"], {"month":9,"day":20,"time":"19:00","version":first["version"]}, USERS[0])
    assert edited["scheduled_at"].startswith("2026-09-21T02:00")
    assert (edited["local_month"], edited["local_day"], edited["local_time"]) == (9, 20, "19:00")


def test_reservation_timezone_boundary_leap_day_and_dst_validation(setup):
    s, _ = setup
    s.clock = lambda: "2027-01-01T00:30:00+00:00"  # Still Dec 31 locally.
    assert s.reservation_time({"month":12,"day":31,"time":"18:00"}).startswith("2027-01-01")
    s.clock = lambda: "2027-09-19T20:00:00+00:00"
    assert s.reservation_time({"month":2,"day":29,"time":"18:00"}).startswith("2028-03-01")
    s.clock = lambda: "2026-01-01T20:00:00+00:00"
    for fields in [{"month":2,"day":29,"time":"18:00"}, {"month":4,"day":31,"time":"18:00"},
                   {"month":3,"day":8,"time":"02:30"}, {"month":9,"day":20,"time":"24:00"}]:
        with pytest.raises(Conflict, match="invalid_reservation_time"):
            s.reservation_time(fields)
    with pytest.raises(Conflict, match="ambiguous_reservation_time"):
        s.reservation_time({"month":11,"day":1,"time":"01:30"})


def test_multi_reservation_dedup_profiles_capacity_and_informational_only(setup):
    s, _ = setup
    table = make(s)
    body = data(month=9, day=20, time="18:30", participant_ids=" person-0,person-1\nperson-0  person-2 ")
    reservation = s.reserve(table["id"], body, USERS[0])
    assert {p["id"] for p in reservation["participants"]} == {u.id for u in USERS[:3]}
    assert all(p["name"] and "seat" not in p for p in reservation["participants"])
    assert s.get(table["id"], USERS[0])["player_count"] == 0
    assert s.reserve(table["id"], body, USERS[0])["id"] == reservation["id"]
    s.reserve(table["id"], data(month=9, day=20, time="18:30"), USERS[1])
    s.join(table["id"], USERS[5], "north")
    for ids, error in [([], "invalid_player_ids"), (["missing"], "account_not_found"),
                       (["disabled"], "account_disabled"), ([u.id for u in USERS[:5]], "reservation_capacity_exceeded")]:
        with pytest.raises(Conflict, match=error):
            s.reserve(table["id"], {**body,"request_id":str(ids),"participant_ids":ids}, USERS[0])
    with s.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ReservationParticipant)) == 4


def test_reservation_ownership_version_and_audit(setup):
    s, _ = setup
    table = make(s)
    reservation = reserve(s, table)
    with pytest.raises(Conflict, match="reservation_not_owner"):
        s.update_reservation(reservation["id"], {"version":1,"note":"No"}, USERS[1])
    with pytest.raises(Conflict, match="reservation_version_required"):
        s.update_reservation(reservation["id"], {"note":"No"}, USERS[0])
    updated = s.update_reservation(reservation["id"], {"version":1,"participant_ids":[USERS[1].id,USERS[2].id]}, ADMIN)
    assert updated["version"] == 2 and updated["updated_by"] == ADMIN.id
    with pytest.raises(Conflict, match="reservation_not_owner"):
        s.update_reservation(reservation["id"], {"version":2,"status":"cancelled"}, USERS[1])
    with pytest.raises(Conflict, match="stale_version"):
        s.update_reservation(reservation["id"], {"version":1,"note":"stale"}, USERS[0])
    cancelled = s.update_reservation(reservation["id"], {"version":2,"status":"cancelled"}, USERS[0])
    assert cancelled["cancelled_by"] == USERS[0].id and cancelled["cancelled_at"]
    with s.store.connect() as db:
        audits = list(db.scalars(select(TournamentAudit).where(TournamentAudit.action == "table_reservation_updated")))
        assert len(audits) == 2 and all(json.loads(row.detail_json)["after"]["updated_by"] for row in audits)


def test_reservation_concurrent_participant_edits_no_lost_update(setup, monkeypatch):
    import mahjong_api.table_service as service_module
    s, _ = setup
    reservation = reserve(s, make(s))
    monkeypatch.setattr(service_module, "membership_lock", nullcontext())
    with ThreadPoolExecutor(2) as pool:
        values = list(pool.map(lambda user: outcome(lambda: s.update_reservation(reservation["id"],
            {"version":1,"participant_ids":[user.id]}, USERS[0])), USERS[1:3]))
    assert sum(isinstance(value, dict) for value in values) == 1 and "stale_version" in values


def test_database_constraints_protect_winds_and_token_binding(setup):
    s, _ = setup
    table = make(s)
    s.join(table["id"], USERS[0], "east")
    with pytest.raises(IntegrityError):
        with s.store.connect() as db:
            db.add(ActiveTableMember(user_id=USERS[1].id, table_id=table["id"], match_id=table["current_match_id"],
                joined_at=s.clock(), join_method="manual", added_by_user_id=USERS[1].id, seat="east"))
    with pytest.raises(IntegrityError):
        with s.store.connect() as db:
            db.execute(text("UPDATE active_table_members SET seat='bogus'"))
    entry = token(s, table)
    with pytest.raises(IntegrityError):
        with s.store.connect() as db:
            db.execute(text("UPDATE table_join_tokens SET purpose='seat_join', seat=NULL WHERE id=:id"), {"id":entry["id"]})


def test_v5_migration_idempotent_backfill_preserves_old_rows(setup):
    from mahjong_api.migrations import migrate
    s, _ = setup
    table = make(s)
    s.join(table["id"], USERS[0], "south")
    reservation = reserve(s, table)
    entry = token(s, table, "nfc")
    with s.store.connect() as db:
        db.execute(text("DELETE FROM nfc_metadata WHERE key='table_v5_migrated'"))
        db.execute(text("DELETE FROM table_reservation_participants"))
        db.execute(text("UPDATE active_table_members SET seat=NULL"))
        db.execute(text("UPDATE table_join_tokens SET purpose='table_landing'"))
    migrate(s.store.engine)
    migrate(s.store.engine)
    assert s.get(table["id"], USERS[0])["members"][0]["seat"] == "south"
    assert s.get(table["id"], USERS[0])["reservations"][0]["participants"][0]["id"] == USERS[0].id
    assert s.token_info(raw(entry))["purpose"] == "table_join"


@pytest.mark.parametrize("operation", ["revoke", "rotate"])
def test_token_mutation_and_scan_have_serial_database_order(setup, monkeypatch, operation):
    import mahjong_api.table_service as service_module
    s, _ = setup
    table = make(s)
    entry = seat_token(s, table, "east")
    monkeypatch.setattr(service_module, "membership_lock", nullcontext())
    def change():
        return s.revoke_token(entry["id"], ADMIN) if operation == "revoke" else seat_token(s, table, "east")
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(lambda: outcome(lambda: s.join_token(raw(entry), USERS[0], "race")))
        second = pool.submit(change)
        joined, _ = first.result(), second.result()
    assert isinstance(joined, dict) or joined == "invalid_join_token"
    assert s.get(table["id"], USERS[0])["player_count"] == int(isinstance(joined, dict))
    with pytest.raises(Conflict, match="invalid_join_token"):
        s.join_token(raw(entry), USERS[1], "post-mutation")


def test_real_pre_v5_schema_upgrade_adds_columns_and_preserves_data(setup, tmp_path):
    import sqlite3
    from mahjong_api.store import Store
    s, _ = setup
    table = make(s)
    s.join(table["id"], USERS[0], "west")
    reservation = reserve(s, table)
    entry = token(s, table)
    target = tmp_path / "pre-v5.sqlite3"
    with sqlite3.connect(s.store.path) as source, sqlite3.connect(target) as db:
        source.backup(db)
        db.execute("PRAGMA foreign_keys=OFF")
        for name, columns, create in [
            ("table_join_tokens", "id,table_id,token_hash,channel,created_at,created_by,expires_at,revoked_at,last_used_at,use_count",
             "id VARCHAR(64) PRIMARY KEY,table_id VARCHAR(64) NOT NULL,token_hash VARCHAR(64) NOT NULL UNIQUE,channel VARCHAR(16) NOT NULL,created_at VARCHAR(40) NOT NULL,created_by VARCHAR(128) NOT NULL,expires_at VARCHAR(40),revoked_at VARCHAR(40),last_used_at VARCHAR(40),use_count INTEGER NOT NULL"),
            ("active_table_members", "user_id,table_id,match_id,joined_at,join_method,added_by_user_id",
             "user_id VARCHAR(128) PRIMARY KEY,table_id VARCHAR(64) NOT NULL,match_id VARCHAR(64) NOT NULL,joined_at VARCHAR(40) NOT NULL,join_method VARCHAR(16) NOT NULL,added_by_user_id VARCHAR(128) NOT NULL"),
            ("table_reservations", "id,table_id,user_id,user_name,scheduled_at,created_at,status,note,cancelled_at,updated_at",
             "id VARCHAR(64) PRIMARY KEY,table_id VARCHAR(64) NOT NULL,user_id VARCHAR(128) NOT NULL,user_name VARCHAR(128) NOT NULL,scheduled_at VARCHAR(40) NOT NULL,created_at VARCHAR(40) NOT NULL,status VARCHAR(16) NOT NULL,note TEXT NOT NULL,cancelled_at VARCHAR(40),updated_at VARCHAR(40) NOT NULL"),
        ]:
            rows = db.execute("SELECT " + columns + " FROM " + name).fetchall()
            db.execute("DROP TABLE " + name)
            db.execute("CREATE TABLE " + name + " (" + create + ")")
            db.executemany("INSERT INTO " + name + " (" + columns + ") VALUES (" + ",".join("?" for _ in columns.split(",")) + ")", rows)
        db.execute("DROP TABLE table_reservation_participants")
        db.execute("ALTER TABLE table_membership_events DROP COLUMN seat")
        db.execute("CREATE UNIQUE INDEX uq_active_table_token_channel ON table_join_tokens (table_id,channel) WHERE revoked_at IS NULL")
        db.execute("DELETE FROM nfc_metadata WHERE key='table_v5_migrated'")
        db.commit()
    upgraded = Store(target)
    try:
        with upgraded.connect() as db:
            assert db.get(ActiveTableMember, USERS[0].id).seat == "west"
            assert db.get(TableJoinToken, entry["id"]).purpose == "table_landing"
            assert db.get(ReservationParticipant, (reservation["id"], USERS[0].id)).user_name == USERS[0].name
            assert db.get(Metadata, "table_v5_migrated")
        with pytest.raises(IntegrityError):
            with upgraded.connect() as db:
                db.execute(text("UPDATE table_join_tokens SET purpose='seat_join',seat=NULL"))
    finally:
        upgraded.close()


@pytest.mark.parametrize("uid,error", [("disabled","account_disabled"),("missing","account_not_found")])
def test_default_creator_participation_is_also_directory_validated(setup, uid, error):
    s, _ = setup
    with pytest.raises(Conflict, match=error):
        s.reserve(make(s)["id"], data(month=9,day=20,time="18:00"), User(id=uid,name=uid))



def test_entry_qr_explicit_seat_choice_is_bound_and_audited(setup):
    s, app = setup
    table, other = make(s), make(s, 8)
    entry = token(s, table)
    assert s.join_token(raw(entry), USERS[0], "visit")["joined"] is False
    app.dependency_overrides[get_current_user] = lambda: USERS[0]
    result = TestClient(app).post("/api/table-join-tokens/" + raw(entry) + "/join",
        json=data(seat="west", table_id=other["id"]))
    assert result.status_code == 200
    assert result.json()["table_id"] == table["id"] and result.json()["join_method"] == "qr_entry"
    assert s.get(table["id"], USERS[0])["members"][0]["seat"] == "west"
    assert s.get(other["id"], USERS[0])["members"] == []
    with s.store.connect() as db:
        event = db.scalar(select(TableMembershipEvent).where(TableMembershipEvent.user_id == USERS[0].id))
        assert event.join_method == "qr_entry" and event.seat == "west"
    with pytest.raises(Conflict, match="invalid_seat"):
        s.join_token(raw(entry), USERS[1], "invalid-wind", "northeast")
    with pytest.raises(Conflict, match="seat_occupied"):
        s.join_token(raw(entry), USERS[1], "occupied", "west")



def test_tournament_entry_confirmation_uses_server_assignment_and_current_match(setup):
    s, app = setup
    tid, match = waiting(s.tournaments)
    table = s.get(match["table_id"], ADMIN)
    entry = token(s, table)
    person = User(id=match["seats"][2], name="West")
    app.dependency_overrides[get_current_user] = lambda: person
    client = TestClient(app)
    url = "/api/table-join-tokens/" + raw(entry) + "/join"
    for flag in (None, False, "true", 1):
        visit = client.post(url, json=data(confirm_entry=flag))
        assert visit.status_code == 200 and visit.json()["joined"] is False
    assert s.get(table["id"], person)["members"] == []
    stale = client.post(url, json=data(confirm_entry=True, match_id="previous-round"))
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_match"
    result = client.post(url, json=data(confirm_entry=True, match_id=match["match_id"]))
    assert result.status_code == 200
    assert result.json()["seat"] == "west" and result.json()["join_method"] == "qr_entry"
    member = s.get(table["id"], person)["members"][0]
    assert member["seat"] == "west" and member["join_method"] == "qr_entry"
    repeat = client.post(url, json=data(confirm_entry=True, match_id=match["match_id"]))
    assert repeat.status_code == 200 and s.get(table["id"], person)["player_count"] == 1
    ordinary = make(s, 8)
    ordinary_entry = token(s, ordinary)
    unchanged = client.post("/api/table-join-tokens/" + raw(ordinary_entry) + "/join", json=data(confirm_entry=True))
    assert unchanged.status_code == 200 and unchanged.json()["joined"] is False
    assert s.get(ordinary["id"], person)["members"] == []
