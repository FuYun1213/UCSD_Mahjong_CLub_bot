"""Reservation queue lifecycle, continuation precedence, manual order and time data."""
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from mahjong_api.game_round_models import GameRound
from mahjong_api.reservation_queue import (
    batch_members, link_started_game, next_batch, on_game_confirmed, on_game_voided, start_batch,
)
from mahjong_api.reservation_queue_models import (
    ReservationDurationSummary, ReservationGameLink, ReservationQueueAudit,
)
from mahjong_api.reservation_reminders import reservation_default
from mahjong_api.store import Conflict
from mahjong_api.table_models import TableReservation
from test_table_v3 import ADMIN, USERS, data, make, setup


NOW = "2026-09-20T21:20:00.000+00:00"  # 14:20 in Los Angeles


def at(minutes):
    return (datetime.fromisoformat(NOW) + timedelta(minutes=minutes)).isoformat(timespec="milliseconds")


def reserve(service, table, user, count=1, minutes=0, others=None):
    return service.reserve(table["id"], data(start_at=at(minutes),
        planned_games=count, participant_ids=others or [user.id]), user)


def test_signed_in_player_can_reserve_only_for_other_registered_players(setup):
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    creator = USERS[0]
    participants = [USERS[1].id, USERS[2].id]
    row = reserve(service, table, creator, others=participants)
    assert row["created_by"] == creator.id
    assert [person["user_id"] for person in row["participants"]] == participants
    assert service.get(table["id"], creator)["player_count"] == 0
    queue = service.reservation_queue(table["id"], creator)
    assert {person["user_id"] for person in queue["next_batch"]["participants"]} == set(participants)
    available = service.available_players(table["id"], creator)
    assert set(participants).issubset({person["id"] for person in available["players"]})
    assert all(set(person) == {"id", "name", "avatar"} for person in available["players"])
    assert service.get(table["id"], creator)["player_count"] == 0


def test_default_is_one_hour_from_current_minute_and_count_validation(setup):
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    default = reservation_default(service, table["id"], USERS[0])
    assert default["scheduled_at"] == at(60)
    assert default["local_time"] == "15:20"
    assert default["missing_players"] == 4
    assert default["estimated"] is False and default["suggestion"] is True
    row = service.reserve(table["id"], data(start_at=default["scheduled_at"]), USERS[0])
    assert row["planned_games"] == 1
    for value in (0, -1, 1.5, True, "", "2", None):
        with pytest.raises(Conflict, match="invalid_planned_games"):
            reserve(service, table, USERS[1], value)
    unlimited = reserve(service, table, USERS[1], "any")
    assert unlimited["planned_games"] == "any"


def test_started_game_occupies_slot_and_fresh_four_displace_continuations(setup, monkeypatch):
    monkeypatch.setenv("RESERVATION_GAME_DURATION_MINUTES", "90")
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    first = [reserve(service, table, user, 2) for user in USERS[:4]]
    queue = service.reservation_queue(table["id"], USERS[0])
    assert [p["user_id"] for p in queue["next_batch"]["participants"]] == [u.id for u in USERS[:4]]
    with service.store.connect() as db:
        started = start_batch(db, table["id"], queue["next_batch"]["id"], "game-1",
                              at(1), USERS[0].id, queue["next_batch"]["version"])
        assert len(started) == 4
    # Occupied, unconfirmed games are not counted as completed.
    for row in first:
        view = service.get(table["id"], USERS[0])
        own = next(r for r in view["reservations"] if r["id"] == row["id"])
        assert own["participants"][0]["completed_games"] == 0
        assert own["participants"][0]["occupied_games"] == 1
        assert own["participants"][0]["remaining_games"] == 1
    reserve(service, table, USERS[4], 1)
    reserve(service, table, USERS[5], 1)
    queue = service.reservation_queue(table["id"], USERS[0])
    assert [p["user_id"] for p in queue["next_batch"]["participants"]][:2] == [USERS[4].id, USERS[5].id]
    reserve(service, table, USERS[6], 1)
    reserve(service, table, USERS[7], 1)
    queue = service.reservation_queue(table["id"], USERS[0])
    assert {p["user_id"] for p in queue["next_batch"]["participants"]} == {u.id for u in USERS[4:8]}
    assert {p["user_id"] for p in queue["waiting"]} == {u.id for u in USERS[:4]}


def test_one_game_reservation_cannot_requeue_before_score_then_disappears(setup):
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    rows = [reserve(service, table, user) for user in USERS[:4]]
    queue = service.reservation_queue(table["id"], USERS[0])
    with service.store.connect() as db:
        start_batch(db, table["id"], queue["next_batch"]["id"], "game-2", at(1), USERS[0].id)
    assert service.reservation_queue(table["id"], USERS[0])["next_batch"] is None
    with service.store.connect() as db:
        on_game_confirmed(db, "game-2")
    assert service.get(table["id"], USERS[0])["reservations"] == []
    assert {r["id"] for r in service.get(table["id"], ADMIN, True)["reservation_history"]} == {r["id"] for r in rows}
    with service.store.connect() as db:
        assert {db.get(TableReservation, r["id"]).status for r in rows} == {"completed"}
        on_game_voided(db, "game-2")
        on_game_voided(db, "game-2")  # A repeated correction cannot add capacity twice.
    assert len(service.reservation_queue(table["id"], USERS[0])["ordered_keys"]) == 4
    with service.store.connect() as db:
        on_game_confirmed(db, "game-2")  # Accounting restore uses the same durable links.
        on_game_confirmed(db, "game-2")
    assert service.get(table["id"], USERS[0])["reservations"] == []
    with service.store.connect() as db:
        assert {db.get(TableReservation, r["id"]).status for r in rows} == {"completed"}


def test_multiplayer_progress_is_individual_and_unlimited_never_exhausts(setup):
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    shared = reserve(service, table, USERS[0], 2, others=[USERS[0].id, USERS[1].id])
    reserve(service, table, USERS[2], "any")
    reserve(service, table, USERS[3], 1)
    queue = service.reservation_queue(table["id"], USERS[0])
    with service.store.connect() as db:
        start_batch(db, table["id"], queue["next_batch"]["id"], "game-3", at(1), USERS[0].id)
        on_game_confirmed(db, "game-3")
    view = service.get(table["id"], USERS[0])
    shared_view = next(row for row in view["reservations"] if row["id"] == shared["id"])
    assert {p["remaining_games"] for p in shared_view["participants"]} == {1}
    queue = service.reservation_queue(table["id"], USERS[0])
    assert {p["user_id"] for p in queue["next_batch"]["participants"]} == {u.id for u in USERS[:3]}
    assert queue["next_batch"]["missing_players"] == 1


def test_reorder_is_persisted_version_checked_and_audited(setup):
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    [reserve(service, table, user) for user in USERS[:5]]
    old = service.reservation_queue(table["id"], USERS[0])
    assert old["can_reorder"] is True
    assert service.reservation_queue(table["id"], USERS[1])["can_reorder"] is True
    desired = list(reversed(old["ordered_keys"]))
    moved = service.reorder_reservation_queue(table["id"], data(
        version=old["version"], ordered_keys=desired), USERS[0])
    assert moved["ordered_keys"] == desired
    assert service.reservation_queue(table["id"], USERS[1])["ordered_keys"] == desired
    with pytest.raises(Conflict, match="stale_version"):
        service.reorder_reservation_queue(table["id"], data(
            version=old["version"], ordered_keys=old["ordered_keys"]), USERS[1])
    with service.store.connect() as db:
        audit = db.scalar(select(ReservationQueueAudit))
        assert json.loads(audit.before_json) == old["ordered_keys"]
        assert json.loads(audit.after_json) == desired
        assert audit.actor_id == USERS[0].id


def test_legacy_count_requires_admin_assignment(setup):
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    row = reserve(service, table, USERS[0], 1)
    with service.store.connect() as db:
        saved = db.get(TableReservation, row["id"])
        saved.plan_kind, saved.planned_games = "legacy_unknown", None
    assert service.reservation_queue(table["id"], USERS[0])["next_batch"] is None
    with pytest.raises(Conflict, match="admin_required"):
        service.update_reservation(row["id"], {"version": row["version"], "planned_games": 2}, USERS[0])
    changed = service.update_reservation(row["id"], {"version": row["version"],
        "planned_games": 2}, ADMIN)
    assert changed["planned_games"] == 2


def test_duration_uses_confirmed_explicit_end_and_unique_global_game(setup, monkeypatch):
    # Historical actual duration is the only allowed source, even if configured.
    monkeypatch.setenv("RESERVATION_GAME_DURATION_MINUTES", "90")
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    row = reserve(service, table, USERS[4], 1)
    first = service.reservation_queue(table["id"], USERS[0])["next_batch"]
    assert first["prediction_source"] == "needs_configuration"
    assert first["estimated_start_at"] is None
    assert first["suggested_start_at"] == at(60)
    game = GameRound(game_id="duration-game", table_id=table["id"],
        score_table_id=table["score_table_id"], round_no=1,
        roster_json=json.dumps([{"user_id": user.id} for user in USERS[:4]]),
        started_at=at(-100), actual_ended_at=at(-20), end_time_source="explicit",
        status="completed", created_at=NOW, updated_at=NOW)
    with service.store.connect() as db:
        db.add(game)
        db.flush()
        on_game_confirmed(db, game.game_id)
        on_game_confirmed(db, game.game_id)
        total = db.get(ReservationDurationSummary, ("global", ""))
        assert total.game_count == 1 and total.total_seconds == 80*60
    queue = service.reservation_queue(table["id"], USERS[0])
    assert queue["next_batch"]["duration_seconds"] == 80*60
    assert queue["next_batch"]["prediction_source"] == "history"


def test_manual_four_seat_start_occupies_only_eligible_reservations(setup):
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    eligible = reserve(service, table, USERS[0], 1)
    future = reserve(service, table, USERS[1], 1, minutes=30)
    roster = [{"user_id": user.id, "seat": seat} for user, seat in
              zip(USERS[:4], ("east", "south", "west", "north"))]
    with service.store.connect() as db:
        links = link_started_game(db, table["id"], "walk-in-game", roster, at(1), USERS[0].id)
        assert [link.user_id for link in links] == [USERS[0].id]
        again = link_started_game(db, table["id"], "walk-in-game", roster, at(1), USERS[0].id)
        assert len(again) == 1
    queue = service.reservation_queue(table["id"], USERS[0])
    assert eligible["id"] not in {key.split(":")[0] for key in queue["ordered_keys"]}
    assert future["id"] in {key.split(":")[0] for key in queue["ordered_keys"]}


def test_personal_and_global_duration_means_are_not_score_row_weighted(setup, monkeypatch):
    monkeypatch.delenv("RESERVATION_GAME_DURATION_MINUTES", raising=False)
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    with service.store.connect() as db:
        for identifier, users, minutes in (
            ("historical-a", USERS[:4], 80),
            ("historical-b", USERS[4:8], 120),
        ):
            db.add(GameRound(game_id=identifier, table_id=table["id"],
                score_table_id=table["score_table_id"], round_no=1 if minutes == 80 else 2,
                roster_json=json.dumps([{"user_id": user.id} for user in users]),
                started_at=at(-200), actual_ended_at=at(-200+minutes),
                end_time_source="explicit", status="completed",
                created_at=NOW, updated_at=NOW))
            db.flush()
            on_game_confirmed(db, identifier)
        global_mean = db.get(ReservationDurationSummary, ("global", ""))
        assert global_mean.game_count == 2 and global_mean.total_seconds == 200*60
    for user in (USERS[0], USERS[4], USERS[8], USERS[9]):
        reserve(service, table, user)
    next_up = service.reservation_queue(table["id"], USERS[0])["next_batch"]
    assert next_up["duration_seconds"] == 100*60
    assert next_up["estimated_start_at"] == NOW


def test_start_edit_without_end_moves_only_deprecated_compatibility_window(setup):
    service, _ = setup
    table = make(service)
    service.clock = lambda: NOW
    row = reserve(service, table, USERS[0], 2)
    later = "2027-09-21T01:45:00.000+00:00"
    edited = service.update_reservation(row["id"], {
        "version": row["version"], "start_at": later}, USERS[0])
    assert edited["start_at"] == later
    assert edited["end_at"] == "2027-09-21T02:45:00.000+00:00"
    assert edited["planned_games"] == 2
