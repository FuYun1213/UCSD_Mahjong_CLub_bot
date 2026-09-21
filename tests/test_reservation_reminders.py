"""Reservation defaults, inclusive reminders, and live stable-ID membership reads."""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from mahjong_api.auth import get_current_user
from mahjong_api.reservation_reminders import get_next_whole_hour, reservation_default, reservation_reminders
from mahjong_api.store import Conflict
from mahjong_api.table_models import ReservationParticipant, TableReservation
from mahjong_api.tournament_models import TournamentAudit
from test_table_v3 import setup, make, data, USERS, ADMIN
from test_web_score_bridge import website


@pytest.mark.parametrize("current,expected,parts", [
    ("2026-09-20T14:03:00-07:00", "2026-09-20T22:00:00.000+00:00", (9,20,"15:00")),
    ("2026-09-20T14:59:00-07:00", "2026-09-20T22:00:00.000+00:00", (9,20,"15:00")),
    ("2026-09-20T14:00:00-07:00", "2026-09-20T22:00:00.000+00:00", (9,20,"15:00")),
    ("2026-09-20T23:20:00-07:00", "2026-09-21T07:00:00.000+00:00", (9,21,"00:00")),
    ("2026-09-30T23:20:00-07:00", "2026-10-01T07:00:00.000+00:00", (10,1,"00:00")),
    ("2026-12-31T23:20:00-08:00", "2027-01-01T08:00:00.000+00:00", (1,1,"00:00")),
    ("2028-02-28T23:20:00-08:00", "2028-02-29T08:00:00.000+00:00", (2,29,"00:00")),
    ("2026-03-08T01:30:00-08:00", "2026-03-08T10:00:00.000+00:00", (3,8,"03:00")),
    ("2026-11-01T01:30:00-07:00", "2026-11-01T09:00:00.000+00:00", (11,1,"01:00")),
    ("2026-11-01T01:30:00-08:00", "2026-11-01T10:00:00.000+00:00", (11,1,"02:00")),
])
def test_next_whole_hour_uses_site_timezone_and_real_instant(current, expected, parts):
    result = get_next_whole_hour(current, "America/Los_Angeles")
    assert result["scheduled_at"] == expected
    assert (result["local_month"], result["local_day"], result["local_time"]) == parts
    assert datetime.fromisoformat(result["scheduled_at"]) > datetime.fromisoformat(current)
    assert result["timezone"] == "America/Los_Angeles"


@pytest.mark.parametrize("zone,current,expected", [
    ("Asia/Kathmandu", "2026-09-20T09:03:00+00:00", "2026-09-20T09:15:00.000+00:00"),
    ("Australia/Lord_Howe", "2026-10-04T01:45:00+10:30", "2026-10-03T16:00:00.000+00:00"),
])
def test_fractional_iana_offsets_are_not_utc_hour_rounding(zone, current, expected):
    assert get_next_whole_hour(current, zone)["scheduled_at"] == expected


def test_default_clock_errors_are_safe():
    with pytest.raises(Conflict, match="invalid_site_timezone"):
        get_next_whole_hour("2026-09-20T00:00:00+00:00", "Not/A_Timezone")
    with pytest.raises(Conflict, match="timezone_required"):
        get_next_whole_hour("2026-09-20T00:00:00", "America/Los_Angeles")


@pytest.mark.parametrize("current", ["2026-12-31T23:20:00-08:00", "2026-11-01T01:30:00-07:00"])
def test_server_default_saves_exact_next_year_and_dst_fold_through_existing_validator(setup, current):
    service, _ = setup
    table = make(service)
    service.clock = lambda: current
    default = reservation_default(service, table["id"], USERS[0])
    saved = service.reserve(table["id"], data(scheduled_at=default["scheduled_at"]), USERS[0])
    assert saved["scheduled_at"] == default["scheduled_at"]
    assert saved["local_month"] == default["local_month"]
    assert saved["local_day"] == default["local_day"]
    assert saved["local_time"] == default["local_time"]
    with pytest.raises(Conflict, match="timezone_required"):
        service.reserve(table["id"], data(scheduled_at="2027-01-01T00:00:00"), USERS[0])


def reserve(service, table, seconds=0, people=None):
    current = datetime.fromisoformat(service.clock())
    return service.reserve(table["id"], data(
        scheduled_at=(current + timedelta(seconds=seconds)).isoformat(),
        participant_ids=people if people is not None else [USERS[0].id]), USERS[0])


def clock(service):
    service.clock = lambda: "2026-09-20T22:00:00.000+00:00"


def groups(service, table):
    return reservation_reminders(service, table["id"], USERS[0])["reminders"]


def test_reminder_window_is_inclusive_sorted_and_excludes_other_table_statuses(setup):
    service, _ = setup
    clock(service)
    table, other = make(service,3), make(service,4)
    upcoming = reserve(service, table, 3600)
    past = reserve(service, table, -3600)
    reserve(service, table, -7201)
    reserve(service, table, 7201)
    reserve(service, other, 0)
    cancelled, completed = reserve(service, table, 3600), reserve(service, table, 3600)
    service.update_reservation(cancelled["id"], {"version":1,"status":"cancelled"}, USERS[0])
    service.update_reservation(completed["id"], {"version":1,"status":"completed"}, ADMIN)
    result = reservation_reminders(service, table["id"], USERS[0])
    assert [row["id"] for row in result["reminders"]] == [past["session_id"],upcoming["session_id"]]
    assert result["timezone"] == "America/Los_Angeles"
    assert result["window_seconds"] == 3600
    assert result["table_number"] == 3
    assert result["next_change_at"] == "2026-09-20T22:00:00.001+00:00"
    assert all(row["table_number"] == 3 for row in result["reminders"])
    assert result["reminders"][0]["expires_at"] == result["server_now"]
    assert all(personal["status"] == "active" for row in result["reminders"] for personal in row["reservations"])
    service.clock = lambda: "2026-09-20T22:00:00.001+00:00"
    assert [row["id"] for row in groups(service, table)] == [upcoming["session_id"]]


def test_groups_dedupe_stable_ids_across_individual_reservations(setup):
    service, _ = setup
    clock(service)
    table = make(service)
    first = reserve(service, table, 0, [USERS[0].id,USERS[1].id,USERS[0].id])
    second = reserve(service, table, 30, [USERS[1].id,USERS[2].id])
    result = groups(service, table)
    assert [row["id"] for row in result] == [first["session_id"]]
    assert first["session_id"] == second["session_id"]
    assert {r["id"] for r in result[0]["reservations"]} == {first["id"],second["id"]}
    assert [[person["user_id"] for person in row["participants"]] for row in result] == [
        [USERS[0].id,USERS[1].id,USERS[2].id]]
    assert all(not row["all_seated"] for row in result)
    assert all(not person["seated"] and person["seat"] is None for row in result for person in row["participants"])


def test_seating_uses_same_table_stable_identity_refreshes_move_leave_and_names(setup):
    service, _ = setup
    clock(service)
    table, other = make(service,3), make(service,4)
    saved = reserve(service, table, 0, [USERS[0].id,USERS[1].id])
    service.join(other["id"], USERS[0], "east")
    service.join(table["id"], USERS[2], "south")
    # Same displayed name on another account must never claim the reservation.
    with service.store.connect() as db:
        db.get(ReservationParticipant, (saved["id"], USERS[1].id)).user_name = USERS[2].name
    assert not any(person["seated"] for person in groups(service, table)[0]["participants"])
    service.leave(other["id"], USERS[0])
    service.join(table["id"], USERS[0], "east")
    service.join(table["id"], USERS[1], "west")
    result = groups(service, table)[0]
    assert result["all_seated"]
    assert [(person["seated"],person["seat"]) for person in result["participants"]] == [(True,"east"),(True,"west")]
    service.join(table["id"], USERS[0], "north")
    assert groups(service, table)[0]["participants"][0]["seat"] == "north"
    previous_lookup = service.account_lookup
    service.account_lookup = lambda ids: [{**person,"name":"Current Registered Name"} if person["id"]==USERS[0].id else person for person in previous_lookup(ids)]
    assert groups(service, table)[0]["participants"][0]["name"] == "Current Registered Name"
    service.leave(table["id"], USERS[1])
    result = groups(service, table)[0]
    assert not result["all_seated"]
    assert result["participants"][1]["seated"] is False
    assert result["participants"][1]["seat"] is None
    with service.store.connect() as db:
        assert db.get(TableReservation, saved["id"]).status == "active"
        assert db.get(ReservationParticipant, (saved["id"], USERS[0].id)).user_name == USERS[0].name



def test_accepted_swap_keeps_participants_seated_and_projects_both_new_winds(setup):
    from mahjong_api.seat_swap_service import SeatSwapService
    service, _ = setup
    clock(service)
    table = make(service)
    reserve(service, table, people=[USERS[0].id,USERS[1].id])
    service.set_my_seat(table["id"], {"seat":"east"}, USERS[0])
    service.set_my_seat(table["id"], {"seat":"south"}, USERS[1])
    swaps = SeatSwapService(service)
    pending = swaps.create(table["id"], {"target_user_id":USERS[1].id}, USERS[0])["request"]
    before = groups(service, table)[0]
    assert [person["seat"] for person in before["participants"]] == ["east","south"]
    swaps.respond(pending["id"], "accept", USERS[1])
    after = groups(service, table)[0]
    assert after["all_seated"] and all(person["seated"] for person in after["participants"])
    assert [person["seat"] for person in after["participants"]] == ["south","east"]
    assert [person["user_id"] for person in after["participants"]] == [USERS[0].id,USERS[1].id]


def test_edit_and_cancel_refresh_reminders_without_mutating_history(setup):
    service, _ = setup
    clock(service)
    table = make(service)
    saved = reserve(service, table, seconds=7200)
    assert not groups(service, table)
    service.update_reservation(saved["id"], {"version":1,"scheduled_at":service.clock(),
        "participant_ids":[USERS[1].id,USERS[2].id]}, USERS[0])
    assert [person["user_id"] for person in groups(service, table)[0]["participants"]] == [USERS[1].id,USERS[2].id]
    service.update_reservation(saved["id"], {"version":2,"status":"cancelled"}, USERS[0])
    assert not groups(service, table)
    with service.store.connect() as db:
        assert db.get(TableReservation,saved["id"]).status == "cancelled"


def test_all_seated_is_read_only_no_start_completion_or_history_mutation(setup):
    service, _ = setup
    clock(service)
    table = make(service)
    saved = reserve(service, table, people=[USERS[0].id,USERS[1].id])
    service.join(table["id"], USERS[0], "east")
    service.join(table["id"], USERS[1], "south")
    with service.store.connect() as db:
        audits = db.scalar(select(func.count()).select_from(TournamentAudit))
    assert groups(service, table)[0]["all_seated"]
    assert groups(service, table)[0]["all_seated"]
    assert service.get(table["id"], USERS[0])["started_at"] is None
    with service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(TournamentAudit)) == audits
        assert db.get(TableReservation, saved["id"]).status == "active"


@pytest.mark.parametrize("field,value", [("status", "left"), ("left_at", "2026-09-20T22:00:00+00:00")])
def test_legacy_invalid_activity_is_never_shown_as_seated(setup, field, value):
    service, _ = setup
    clock(service)
    table = make(service)
    reserve(service, table)
    service.join(table["id"], USERS[0], "east")
    with service.store.connect() as db:
        # Simulate a legacy import lacking V5 activity constraints, only in this
        # fixture's private temporary database. Production still enforces them.
        triggers = db.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='active_table_members'")).scalars().all()
        for trigger in triggers:
            db.execute(text('DROP TRIGGER "' + trigger.replace('"','""') + '"'))
        db.execute(text("PRAGMA ignore_check_constraints=ON"))
        db.execute(text("UPDATE active_table_members SET " + field + "=:value WHERE user_id=:uid"), {"value":value,"uid":USERS[0].id})
        db.execute(text("PRAGMA ignore_check_constraints=OFF"))
    assert not groups(service, table)[0]["participants"][0]["seated"]


def test_reminders_http_auth_and_ordinary_scope_and_future_change(setup):
    service, app = setup
    clock(service)
    table = make(service)
    client = TestClient(app)
    for suffix in ("reservation-default", "reservation-reminders"):
        assert client.get(f"/api/club-tables/{table['id']}/{suffix}").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: USERS[0]
    result = client.get(f"/api/club-tables/{table['id']}/reservation-reminders")
    assert result.status_code == 200
    assert result.json()["reminders"] == [] and result.json()["next_change_at"] is None
    reserve(service, table, 7200)
    assert client.get(f"/api/club-tables/{table['id']}/reservation-reminders").json()["next_change_at"] == "2026-09-20T23:00:00.000+00:00"
    result = client.get(f"/api/club-tables/{table['id']}/reservation-default")
    assert result.status_code == 200
    assert result.json()["scheduled_at"] == "2026-09-20T23:00:00.000+00:00"
    # The embedded Game Record still supplies a legacy score-table alias.
    alias = table["score_table_id"]
    default_alias = client.get(f"/api/club-tables/{alias}/reservation-default")
    assert default_alias.status_code == 200 and default_alias.json() == result.json()
    reminder_alias = client.get(f"/api/club-tables/{alias}/reservation-reminders")
    assert reminder_alias.status_code == 200
    assert reminder_alias.json()["table_id"] == table["id"]
    assert reminder_alias.json()["score_table_id"] == alias
    assert reminder_alias.json() == client.get(f"/api/club-tables/{table['id']}/reservation-reminders").json()
    tournament = service.tournaments.create(data(name="Reminder exclusion"), ADMIN.id)
    event_table = make(service, 3, tournament["id"])
    with pytest.raises(Conflict, match="fixed_tournament_seating"):
        reservation_reminders(service,event_table["id"],USERS[0])
    with pytest.raises(Conflict, match="not_authenticated"):
        reservation_reminders(service,table["id"],None)
    service.update(table["id"], {"status":"closed"}, ADMIN)
    with pytest.raises(Conflict, match="table_closed"):
        reservation_reminders(service,table["id"],USERS[0])


def test_reservation_date_javascript_preserves_user_changes_and_existing_year():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the frontend state contract")
    result = subprocess.run([node,"tests/reservation_time.cjs"], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True,text=True,encoding="utf-8",timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.getenv("NFC_BROWSER_TESTS") != "1", reason="Set NFC_BROWSER_TESTS=1 with Playwright installed to run browser tests")
def test_reservation_time_browser_real_form(website, monkeypatch):
    import web_server
    url, app, _ = website
    app.state.tables.clock = lambda: "2026-12-31T23:20:00-08:00"
    accounts = json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"] = "admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts),encoding="utf-8")
    monkeypatch.setattr(web_server,"sheet_player_names",lambda: [])
    environment = os.environ.copy()
    environment["NFC_TEST_URL"] = url
    environment["NODE_PATH"] = str(Path(".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node","tests/browser_reservation_time.cjs"],env=environment,
                            capture_output=True,text=True,encoding="utf-8",timeout=75)
    assert result.returncode == 0, result.stdout + result.stderr
