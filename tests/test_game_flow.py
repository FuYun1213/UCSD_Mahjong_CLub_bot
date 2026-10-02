"""All Last, early next game, frozen scoring, and audited seat removal."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from mahjong_api.config import Settings
from mahjong_api.database_models import MatchHistory, SeatRecord, TableState, User as Account
from mahjong_api.discord_reminder_config import DiscordReminderConfig
from mahjong_api.discord_reminder_models import DiscordReminder
from mahjong_api.discord_reminder_service import DiscordReminderService
from mahjong_api.game_flow import GameFlowService
from mahjong_api.game_round_models import GameRound
from mahjong_api.manual_score import ManualScoreService
from mahjong_api.models import SEATS, Scores, SubmitScores, User
from mahjong_api.queue_notifications import enqueue_queue_notice
from mahjong_api.reservation_queue_models import ReservationDurationSample, ReservationGameLink
from mahjong_api.service import MatchService
from mahjong_api.sheets import DisabledSheets
from mahjong_api.store import Conflict, Store
from mahjong_api.table_models import ActiveTableMember, ClubTable, TableMembershipEvent, TableReservation
from mahjong_api.table_service import TableService
from mahjong_api.tournament import TournamentService


PEOPLE = [User(id=f"flow-{i}", name=f"Flow {i}") for i in range(9)]
EXTRA = [User(id=f"flow-extra-{i}", name=f"Extra {i}") for i in range(4)]
ADMIN = User(id="flow-admin", name="Admin", role="admin")
SCORES = dict(zip(SEATS, (35000, 20000, 15000, 30000)))


@pytest.fixture
def system(tmp_path):
    settings = Settings(database_path=tmp_path / "game-flow.sqlite3")
    store = Store(settings.database_path)
    matches = MatchService(store, DisabledSheets(), settings)
    tables = TableService(matches, TournamentService(store, matches.external),
        account_lookup=lambda ids: [{"id": person.id, "name": person.name}
                                    for person in PEOPLE + EXTRA if ids is None or person.id in ids])
    table = tables.create({"number": 1, "request_id": "create-flow-table"}, ADMIN)
    yield store, matches, tables, GameFlowService(tables), table
    store.close()


def fill(tables, table, people):
    for person, wind in zip(people, SEATS):
        tables.set_my_seat(table["id"], {"seat": wind}, person)


def reserve(tables, table, people, request_id="reserve-next-four"):
    start = (datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec="milliseconds")
    return tables.reserve(table["id"], {
        "start_at": start, "planned_games": 1,
        "participant_ids": [person.id for person in people],
        "request_id": request_id,
    }, people[0])


@pytest.mark.parametrize("send_match_id", [False, True])
def test_first_score_after_upgrade_snapshots_only_live_game_and_confirms_booking(system, send_match_id):
    store, matches, tables, flow, table = system
    reservation = reserve(tables, table, PEOPLE[:1],
                          "pre-upgrade-booking-" + str(send_match_id))
    started = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec="milliseconds")
    with store.connect() as db:
        score = db.scalar(select(TableState).where(
            TableState.table_id == table["score_table_id"]))
        game_id = score.current_match_id
        score.started_at = started
        for person in PEOPLE[:4]:
            if db.get(Account, person.id) is None:
                db.add(Account(id=person.id, name=person.name))
        db.flush()
        for wind, person in zip(SEATS, PEOPLE[:4]):
            db.add(SeatRecord(table_id=score.table_id, seat=wind,
                              user_id=person.id, user_name=person.name))
        assert db.get(GameRound, game_id) is None
    response, _ = matches.submit(SubmitScores(table=table["score_table_id"],
        scores=Scores(**SCORES), match_id=game_id if send_match_id else None),
        "pre-upgrade-score-" + str(send_match_id))
    assert response["result"]["match_id"] == game_id
    assert response["result"]["duration_seconds"] is None
    with store.connect() as db:
        game = db.get(GameRound, game_id)
        assert game.status == "completed" and game.started_at == started
        assert game.actual_ended_at is None
        assert {wind: person["id"] for wind, person in
                json.loads(game.roster_json).items()} == dict(zip(
                    SEATS, (person.id for person in PEOPLE[:4])))
        assert db.get(ReservationGameLink, (game_id, PEOPLE[0].id)).status == "confirmed"
        assert db.get(TableReservation, reservation["id"]).status == "completed"
        assert db.get(ReservationDurationSample, game_id) is None
        assert db.scalar(select(MatchHistory).where(
            MatchHistory.match_id == game_id)).duration_seconds is None


def test_score_never_reconstructs_unknown_prior_roster(system):
    store, matches, tables, flow, table = system
    current_id = matches.table(table["score_table_id"])["match_id"]
    prior_id = "pre-upgrade-unscored-prior"
    started = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec="milliseconds")
    with store.connect() as db:
        score = db.scalar(select(TableState).where(
            TableState.table_id == table["score_table_id"]))
        score.started_at = started
        for person in PEOPLE[:4]:
            if db.get(Account, person.id) is None:
                db.add(Account(id=person.id, name=person.name))
        db.flush()
        for wind, person in zip(SEATS, PEOPLE[:4]):
            db.add(SeatRecord(table_id=score.table_id, seat=wind,
                              user_id=person.id, user_name=person.name))
    with pytest.raises(Conflict) as stale:
        matches.submit(SubmitScores(table=table["score_table_id"],
            scores=Scores(**SCORES), match_id=prior_id), "unknown-prior-score")
    assert stale.value.detail["code"] == "stale_match"
    with store.connect() as db:
        assert db.get(GameRound, prior_id) is None
        assert db.get(GameRound, current_id) is None
        assert db.scalar(select(func.count()).select_from(MatchHistory)) == 0


def test_all_last_is_idempotent_and_prior_score_cannot_clear_next_game(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    old_id = matches.table(table["score_table_id"])["match_id"]
    reserve(tables, table, PEOPLE[4:8])
    first = flow.all_last(table["id"], {"match_id": old_id}, PEOPLE[0])
    assert first["current_game"]["all_last_at"] and not first["replayed"]
    batch = first["next_batch"]
    again = flow.all_last(table["id"], {"match_id": old_id}, PEOPLE[0])
    assert again["replayed"] and again["current_game"]["all_last_at"] == first["current_game"]["all_last_at"]
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(DiscordReminder).where(
            DiscordReminder.notification_type == "queue_all_last")) == 1
        assert db.scalar(select(func.count()).select_from(MatchHistory)) == 0
    seats = dict(zip(SEATS, (person.id for person in PEOPLE[4:])))
    begun = flow.start_next(table["id"], {
        "match_id": old_id, "batch_id": batch["id"],
        "batch_version": batch["version"], "seats": seats,
    }, PEOPLE[0])
    new_id = begun["current_game"]["game_id"]
    assert new_id != old_id
    assert [row["game_id"] for row in begun["pending_scores"]] == [old_id]
    assert {wind: person["id"] for wind, person in
            begun["pending_scores"][0]["players"].items()} == dict(zip(SEATS,
            (person.id for person in PEOPLE[:4])))
    prior, uploader_wind = matches.capture_context(table["score_table_id"], PEOPLE[0], old_id)
    assert uploader_wind == "east" and prior["seats"]["east"]["id"] == PEOPLE[0].id
    manual = ManualScoreService(matches, tables).context(table["id"], PEOPLE[0], old_id)
    assert manual["match_id"] == old_id
    assert manual["players"]["east"]["id"] == PEOPLE[0].id
    score, _ = matches.submit(SubmitScores(table=table["score_table_id"],
                              scores=Scores(**SCORES), match_id=old_id), "old-score")
    assert score["result"]["match_id"] == old_id
    assert score["result"]["duration_seconds"] is None
    assert [score["result"]["players"][wind]["user"]["id"] for wind in SEATS] == [
        person.id for person in PEOPLE[:4]]
    state = matches.table(table["score_table_id"])
    assert state["match_id"] == new_id
    assert store.table(table["score_table_id"])["pending_match_id"] is None
    assert [state["players"][wind]["id"] for wind in SEATS] == [
        person.id for person in PEOPLE[4:8]]
    with store.connect() as db:
        assert db.get(GameRound, old_id).status == "completed"
        assert db.get(GameRound, old_id).actual_ended_at is None
        assert db.get(ReservationDurationSample, old_id) is None
    new_score, _ = matches.submit(SubmitScores(table=table["score_table_id"],
                                  scores=Scores(**SCORES), match_id=new_id), "new-score")
    assert new_score["result"]["match_id"] == new_id


def test_late_manual_score_uses_prior_game_after_next_start(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    old_id = matches.table(table["score_table_id"])["match_id"]
    reserve(tables, table, PEOPLE[4:8])
    batch = flow.all_last(table["id"], {"match_id": old_id}, PEOPLE[0])["next_batch"]
    seats = dict(zip(SEATS, (person.id for person in PEOPLE[4:8])))
    flow.start_next(table["id"], {"match_id": old_id, "batch_id": batch["id"],
        "batch_version": batch["version"], "seats": seats}, PEOPLE[0])
    new_id = matches.table(table["score_table_id"])["match_id"]
    body, status = ManualScoreService(matches, tables).upload({
        "table_id": table["id"], "match_id": old_id,
        "request_id": "late-manual-prior-score",
        "players": dict(zip(SEATS, (person.id for person in PEOPLE[:4]))),
        "scores": SCORES,
    }, PEOPLE[0])
    assert status in {200, 202}
    assert body["result"]["match_id"] == old_id
    live = matches.table(table["score_table_id"])
    assert live["match_id"] == new_id
    assert store.table(table["score_table_id"])["pending_match_id"] is None
    with store.connect() as db:
        assert db.get(GameRound, old_id).status == "completed"
        assert db.get(GameRound, new_id).status == "playing"


def test_third_batch_anchors_to_latest_game_despite_older_pending_score(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    old_id = matches.table(table["score_table_id"])["match_id"]
    reserve(tables, table, PEOPLE[4:8])
    second = flow.all_last(table["id"], {"match_id": old_id}, PEOPLE[0])["next_batch"]
    flow.start_next(table["id"], {"match_id": old_id, "batch_id": second["id"],
        "batch_version": second["version"],
        "seats": dict(zip(SEATS, (person.id for person in PEOPLE[4:8])))}, PEOPLE[0])
    second_id = matches.table(table["score_table_id"])["match_id"]
    reserve(tables, table, EXTRA, "reserve-third-four")
    matches.submit(SubmitScores(table=table["score_table_id"],
                   scores=Scores(**SCORES), match_id=second_id), "score-second-first")
    next_batch = flow.state(table["id"], ADMIN)["next_batch"]
    assert next_batch and {person["user_id"] for person in next_batch["participants"]} == {
        person.id for person in EXTRA}
    from mahjong_api.reservation_queue_models import ReservationQueueBatch
    with store.connect() as db:
        assert db.get(ReservationQueueBatch, next_batch["id"]).predecessor_game_id == second_id
        assert db.get(GameRound, old_id).status == "awaiting_score"
    worker = DiscordReminderService(tables,
        DiscordReminderConfig(token="fake", guild_id="1278056421224747162",
                              channel_id="111111111111111111"),
        sender=QueueFakeSender(), account_lookup=lambda ids: [])
    worker.plan()
    with store.connect() as db:
        assert db.get(GameRound, second_id).successor_batch_id == next_batch["id"]
    matches.submit(SubmitScores(table=table["score_table_id"],
                   scores=Scores(**SCORES), match_id=old_id), "late-old-score")
    with store.connect() as db:
        assert db.get(GameRound, old_id).successor_batch_id == second["id"]
        assert db.get(ReservationQueueBatch, next_batch["id"]).predecessor_game_id == second_id


def test_actual_finish_is_explicit_and_can_be_recorded_after_score(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    old_id = matches.table(table["score_table_id"])["match_id"]
    finish = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(timespec="milliseconds")
    with store.connect() as db:
        game = db.get(GameRound, old_id)
        game.started_at = (datetime.fromisoformat(finish)-timedelta(hours=1)).isoformat(timespec="milliseconds")
    matches.submit(SubmitScores(table=table["score_table_id"],
                   scores=Scores(**SCORES), match_id=old_id), "score-finish")
    flow.record_end(table["id"], old_id, {"actual_ended_at": finish}, PEOPLE[0])
    with store.connect() as db:
        game = db.get(GameRound, old_id)
        match = db.scalar(select(MatchHistory).where(MatchHistory.match_id == old_id))
        assert game.actual_ended_at == finish
        assert match.duration_seconds == 3600
        assert db.get(ReservationDurationSample, old_id).duration_seconds == 3600
    with pytest.raises(Conflict, match="actual_end_conflict"):
        flow.record_end(table["id"], old_id, {"actual_ended_at": (
            datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat(timespec="milliseconds")}, PEOPLE[0])


def test_other_player_removal_needs_no_name_confirmation_and_preserves_audit(system):
    store, matches, tables, flow, table = system
    tables.set_my_seat(table["id"], {"seat": "east"}, PEOPLE[0])
    tables.set_my_seat(table["id"], {"seat": "south"}, PEOPLE[1])
    match_id = matches.table(table["score_table_id"])["match_id"]
    data = {"match_id": match_id, "seat": "south"}
    result = flow.remove_other(table["id"], PEOPLE[1].id, data, PEOPLE[8])
    assert result["removed"] and not result["replayed"]
    assert flow.remove_other(table["id"], PEOPLE[1].id, data, PEOPLE[8])["replayed"]
    with store.connect() as db:
        assert db.get(ActiveTableMember, PEOPLE[1].id) is None
        assert db.get(SeatRecord, (table["score_table_id"], "south")) is None
        events = list(db.scalars(select(TableMembershipEvent).where(
            TableMembershipEvent.action == "removed")))
        assert len(events) == 1
        assert (events[0].actor_id, events[0].user_id, events[0].seat) == (
            PEOPLE[8].id, PEOPLE[1].id, "south")


def test_running_game_rejects_other_player_removal_without_changing_snapshot(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    match_id = matches.table(table["score_table_id"])["match_id"]
    data = {"match_id": match_id, "seat": "south"}
    with pytest.raises(Conflict, match="cannot_remove_started"):
        flow.remove_other(table["id"], PEOPLE[1].id, data, PEOPLE[0])
    with store.connect() as db:
        assert db.get(SeatRecord, (table["score_table_id"], "south")).user_id == PEOPLE[1].id
        assert db.get(ActiveTableMember, PEOPLE[1].id) is not None
        assert db.get(GameRound, match_id).status == "playing"
        assert db.scalar(select(func.count()).select_from(TableMembershipEvent).where(
            TableMembershipEvent.action == "removed")) == 0



def test_seated_player_can_cancel_wrong_unscored_game_atomically(system):
    store, matches, tables, flow, table = system
    reservation = reserve(tables, table, PEOPLE[:4], "reserve-wrong-game")
    fill(tables, table, PEOPLE[:4])
    game_id = matches.table(table["score_table_id"])["match_id"]
    with store.connect() as db:
        assert db.get(GameRound, game_id).status == "playing"
        assert {row.status for row in db.scalars(select(ReservationGameLink).where(
            ReservationGameLink.game_id == game_id))} == {"started"}
    data = {"match_id": game_id, "request_id": "cancel-wrong-game",
            "reason": "wrong_players"}
    with pytest.raises(Conflict, match="must_join_first"):
        flow.cancel_game(table["id"], {**data, "request_id": "outsider-cancel"},
                         PEOPLE[8])
    first = flow.cancel_game(table["id"], data, PEOPLE[0])
    assert first == {"table_id": table["id"], "match_id": game_id,
                     "cancelled": True, "replayed": False}
    assert flow.cancel_game(table["id"], data, PEOPLE[0])["replayed"]
    new_id = matches.table(table["score_table_id"])["match_id"]
    assert new_id != game_id
    queue = tables.reservation_queue(table["id"], PEOPLE[0])
    assert {row["user_id"] for row in queue["next_batch"]["participants"]} == {
        person.id for person in PEOPLE[:4]}
    with store.connect() as db:
        game = db.get(GameRound, game_id)
        assert game.status == "void"
        assert {wind: player["id"] for wind, player in
                json.loads(game.roster_json).items()} == dict(zip(
                    SEATS, (person.id for person in PEOPLE[:4])))
        assert db.scalar(select(func.count()).select_from(SeatRecord)) == 0
        assert db.scalar(select(func.count()).select_from(ActiveTableMember)) == 0
        assert {row.status for row in db.scalars(select(ReservationGameLink).where(
            ReservationGameLink.game_id == game_id))} == {"void"}
        assert db.get(TableReservation, reservation["id"]).status == "active"
        assert db.scalar(select(func.count()).select_from(MatchHistory)) == 0
    with pytest.raises(Conflict, match="stale_match"):
        flow.cancel_game(table["id"], {**data, "request_id": "stale-cancel"},
                         ADMIN)


def test_cancel_game_cancels_unsent_all_last_notice_and_admin_reset_voids_round(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    game_id = matches.table(table["score_table_id"])["match_id"]
    reserve(tables, table, PEOPLE[4:8], "reserve-cancel-notice")
    flow.all_last(table["id"], {"match_id": game_id}, PEOPLE[0])
    flow.cancel_game(table["id"], {"match_id": game_id,
        "request_id": "cancel-all-last", "reason": "wrong_players"}, PEOPLE[0])
    with store.connect() as db:
        assert db.get(GameRound, game_id).status == "void"
        assert {row.status for row in db.scalars(select(DiscordReminder).where(
            DiscordReminder.predecessor_game_id == game_id))} == {"cancelled"}
    fill(tables, table, PEOPLE[:4])
    second_id = matches.table(table["score_table_id"])["match_id"]
    tables.reset(table["id"], {"reason": "wrong roster",
                 "request_id": "admin-reset-after-four"}, ADMIN)
    with store.connect() as db:
        assert db.get(GameRound, second_id).status == "void"
        assert db.scalar(select(func.count()).select_from(SeatRecord)) == 0



def test_all_last_keeps_original_score_before_next_game_flow(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    first_id = matches.table(table["score_table_id"])["match_id"]
    reserve(tables, table, PEOPLE[4:8], "reserve-after-all-last")
    flow.all_last(table["id"], {"match_id": first_id}, PEOPLE[0])
    assert matches.table(table["score_table_id"])["match_id"] == first_id
    assert tables.get(table["id"], PEOPLE[0])["player_count"] == 4
    matches.submit(SubmitScores(table=table["score_table_id"],
                   scores=Scores(**SCORES), match_id=first_id), "score-before-next")
    assert tables.get(table["id"], PEOPLE[0])["player_count"] == 0
    fill(tables, table, PEOPLE[4:8])
    second_id = matches.table(table["score_table_id"])["match_id"]
    assert second_id != first_id
    with store.connect() as db:
        assert db.get(GameRound, first_id).status == "completed"
        assert db.get(GameRound, second_id).status == "playing"

def test_cancel_game_rejects_confirmed_score(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    game_id = matches.table(table["score_table_id"])["match_id"]
    matches.submit(SubmitScores(table=table["score_table_id"],
                   scores=Scores(**SCORES), match_id=game_id), "confirmed-before-cancel")
    with pytest.raises(Conflict):
        flow.cancel_game(table["id"], {"match_id": game_id,
            "request_id": "cancel-confirmed", "reason": "wrong_players"}, ADMIN)
    with store.connect() as db:
        assert db.get(GameRound, game_id).status == "completed"
        assert db.scalar(select(MatchHistory).where(
            MatchHistory.match_id == game_id)) is not None

def test_forecast_shift_does_not_duplicate_queue_notice(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    reserve(tables, table, PEOPLE[4:8])
    first = flow.state(table["id"], PEOPLE[0])
    game_id = first["current_game"]["game_id"]
    with store.connect() as db:
        from mahjong_api.reservation_queue_models import ReservationQueueBatch
        game = db.get(GameRound, game_id)
        batch = db.get(ReservationQueueBatch, first["next_batch"]["id"])
        enqueue_queue_notice(db, db.get(ClubTable, table["id"]), game, batch, "queue_prepare", datetime.now(timezone.utc).isoformat())
        batch.estimated_start_at = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(timespec="milliseconds")
        enqueue_queue_notice(db, db.get(ClubTable, table["id"]), game, batch, "queue_prepare", datetime.now(timezone.utc).isoformat())
        assert db.scalar(select(func.count()).select_from(DiscordReminder).where(
            DiscordReminder.notification_type == "queue_prepare")) == 1



def test_ordinary_mixed_game_occupies_only_eligible_booking(system):
    store, matches, tables, flow, table = system
    reservation = reserve(tables, table, PEOPLE[:1], "reserve-one-current")
    fill(tables, table, PEOPLE[:4])
    game_id = matches.table(table["score_table_id"])["match_id"]
    with store.connect() as db:
        links = list(db.scalars(select(ReservationGameLink).where(
            ReservationGameLink.game_id == game_id)))
        assert [(link.user_id, link.status) for link in links] == [(PEOPLE[0].id, "started")]
        assert flow._next(db, db.get(ClubTable, table["id"])) is None
    matches.submit(SubmitScores(table=table["score_table_id"],
                   scores=Scores(**SCORES), match_id=game_id), "score-mixed")
    with store.connect() as db:
        assert db.get(ReservationGameLink, (game_id, PEOPLE[0].id)).status == "confirmed"
        assert db.get(TableReservation, reservation["id"]).status == "completed"


class QueueFakeSender:
    def __init__(self):
        self.messages = []
        self.edits = []

    def prepare(self):
        return {"channel_id": "111111111111111111", "bot_user_id": "222222222222222222"}

    def send(self, destination, payload):
        self.messages.append(payload)
        return str(555555555555555555 + len(self.messages))

    def edit(self, destination, message_id, payload):
        self.edits.append((message_id, payload))
        return message_id

    def reconcile(self, channel_id, bot_user_id, nonce, since):
        for index, payload in enumerate(self.messages, 1):
            if payload["nonce"] == nonce:
                return str(555555555555555555 + index)
        return None


def test_queue_send_rechecks_cancelled_reservation_before_discord(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    reservation = reserve(tables, table, PEOPLE[4:8])
    game_id = matches.table(table["score_table_id"])["match_id"]
    flow.all_last(table["id"], {"match_id": game_id}, PEOPLE[0])
    with store.connect() as db:
        notice = db.scalar(select(DiscordReminder).where(
            DiscordReminder.notification_type == "queue_all_last"))
        notice_id = notice.id
        # Model an out-of-band cancellation after the batch was projected.
        # The send fence must reconcile even if the normal planner has not run.
        db.get(TableReservation, reservation["id"]).status = "cancelled"
    sender = QueueFakeSender()
    worker = DiscordReminderService(tables,
        DiscordReminderConfig(token="fake", guild_id="1278056421224747162",
                              channel_id="111111111111111111"),
        sender=sender, account_lookup=lambda ids: [])
    token = worker._claim(notice_id)
    assert token is not None
    worker._process(notice_id, token)
    assert sender.messages == []
    with store.connect() as db:
        notice = db.get(DiscordReminder, notice_id)
        assert notice.status == "cancelled"
        assert notice.last_error == "stale_queue_batch"


def test_sent_all_last_roster_change_edits_and_pings_only_new_player(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    reservation = reserve(tables, table, PEOPLE[4:8])
    game_id = matches.table(table["score_table_id"])["match_id"]
    flow.all_last(table["id"], {"match_id": game_id}, PEOPLE[0])
    sender = QueueFakeSender()
    profiles = {person.id: {"id": person.id, "name": person.name,
                "discord_id": str(333333333333333333+index)}
                for index, person in enumerate(PEOPLE)}
    worker = DiscordReminderService(tables,
        DiscordReminderConfig(token="fake", guild_id="1278056421224747162",
                              channel_id="111111111111111111"),
        sender=sender, account_lookup=lambda ids: [profiles[uid] for uid in ids])
    worker.tick()
    assert len(sender.messages) == 1 and not sender.edits
    tables.update_reservation(reservation["id"], {
        "version": 1, "participant_ids": [person.id for person in PEOPLE[4:7]]}, PEOPLE[4])
    reserve(tables, table, PEOPLE[8:9], "reserve-new-player")
    worker.tick()
    assert len(sender.edits) == 1 and len(sender.messages) == 2
    assert "<@" + profiles[PEOPLE[8].id]["discord_id"] + ">" in sender.edits[0][1]["content"]
    assert sender.edits[0][1]["allowed_mentions"]["users"] == []
    assert sender.messages[-1]["allowed_mentions"]["users"] == [profiles[PEOPLE[8].id]["discord_id"]]
    worker.tick()
    assert len(sender.edits) == 1 and len(sender.messages) == 2



def test_plain_score_confirmation_links_ready_notice_to_finished_game(system):
    store, matches, tables, flow, table = system
    fill(tables, table, PEOPLE[:4])
    reserve(tables, table, PEOPLE[4:8])
    old_id = matches.table(table["score_table_id"])["match_id"]
    matches.submit(SubmitScores(table=table["score_table_id"],
                   scores=Scores(**SCORES), match_id=old_id), "plain-score")
    sender = QueueFakeSender()
    worker = DiscordReminderService(tables,
        DiscordReminderConfig(token="fake", guild_id="1278056421224747162",
                              channel_id="111111111111111111"),
        sender=sender, account_lookup=lambda ids: [
            {"id": person.id, "name": person.name, "discord_id": ""}
            for person in PEOPLE if person.id in ids])
    worker.tick()
    assert len(sender.messages) == 1
    assert "Your Table Is Ready" in sender.messages[0]["content"]
    with store.connect() as db:
        game = db.get(GameRound, old_id)
        assert game.successor_batch_id is not None
        assert db.scalar(select(func.count()).select_from(DiscordReminder).where(
            DiscordReminder.predecessor_game_id == old_id,
            DiscordReminder.notification_type == "queue_ready")) == 1
