"""M1 guarantees: transactional outbox, independent targets, restart and lost ACK."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import re
import threading

import pytest
from sqlalchemy import func, select, update

from mahjong_api.config import Settings
from mahjong_api.database_models import Metadata
from mahjong_api.history_delivery import HistoryDispatcher, HistoryNeedsReview
from mahjong_api.history_delivery_models import (
    HistoryTargetLease, ScoreDelivery, ScoreProjectionJob, ScoreRecord, ScoreRevision, ScoreRevisionPlayer,
)
from mahjong_api.models import SEATS
from mahjong_api.sheets import GSpreadSheets, HISTORY_HEADERS, publish_marked_row
from mahjong_api.store import Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "matches.sqlite3")
    yield value
    value.close()


def match(match_id="match-1", sequence=1):
    return {"sequence": sequence, "match_id": match_id, "result": {
        "match_id": match_id, "round": 1, "table": "1", "played_at": "2026-09-22T08:00:00Z",
        "uploader_id": "recorder", "players": {seat: {"user": {"id": "id-" + seat, "name": seat},
            "initial_points": 25000, "final_points": 25000, "delta_points": 0, "net_score": 0}
            for seat in SEATS}}}


class Channels:
    enabled = True

    def __init__(self, store, destination="original"):
        self.store, self.destination = store, destination
        self.calls, self.rows, self.fail_after = [], {}, set()
        self.targets = ["one", "two", "three"]

    def history_targets(self, value):
        return [{"channel": name, "target": {"adapter": "fake", "destination": self.destination, "name": name}}
                for name in self.targets]

    def deliver_history(self, target, value, *, reconcile=False):
        # Prove the source transaction has ended before any adapter executes.
        with self.store.connect() as db:
            db.merge(Metadata(key="network_started", value="1"))
        key = (target["destination"], target["name"], value["match_id"])
        self.calls.append((key, reconcile))
        if key in self.rows:
            assert self.rows[key] == value
        else:
            self.rows[key] = deepcopy(value)
        if target["name"] in self.fail_after:
            self.fail_after.remove(target["name"])
            raise TimeoutError("Stored remotely, response lost")
        return {"match_id": value["match_id"], "revision": 1}


def enqueue(dispatcher, value):
    with dispatcher.store.connect() as db:
        dispatcher.enqueue_history(db, value)


def test_outbox_and_revision_rollback_with_confirmation(store):
    sink = Channels(store)
    dispatcher = HistoryDispatcher(store, sink)
    with pytest.raises(RuntimeError):
        with store.connect() as db:
            dispatcher.enqueue_history(db, match())
            raise RuntimeError("Confirmation failed")
    with store.connect() as db:
        for model in (ScoreRecord, ScoreRevision, ScoreRevisionPlayer, ScoreDelivery):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert sink.calls == []
    enqueue(dispatcher, match())
    enqueue(dispatcher, match())
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ScoreRecord)) == 1
        assert db.scalar(select(func.count()).select_from(ScoreRevisionPlayer)) == 4
        assert db.scalar(select(func.count()).select_from(ScoreDelivery)) == 3
    assert sink.calls == []


def test_per_channel_lost_ack_does_not_repeat_success(store):
    sink = Channels(store)
    dispatcher = HistoryDispatcher(store, sink)
    sink.fail_after.add("two")
    enqueue(dispatcher, match())
    dispatcher.flush()
    states = {item["channel"]: item["status"] for item in dispatcher.status("match-1")["channels"]}
    assert states == {"one": "succeeded", "two": "delivery_unknown", "three": "succeeded"}
    dispatcher.retry("match-1")
    dispatcher.flush()
    assert dispatcher.status("match-1")["status"] == "synced"
    assert len(sink.rows) == 3
    assert len(sink.calls) == 4
    assert sink.calls[-1][0][1] == "two" and sink.calls[-1][1]


def test_restart_keeps_destination_and_payload(store):
    original = Channels(store)
    dispatcher = HistoryDispatcher(store, original)
    enqueue(dispatcher, match())
    replacement = Channels(store, destination="changed-config")
    restarted = HistoryDispatcher(store, replacement)
    restarted.flush()
    assert {key[0] for key in replacement.rows} == {"original"}
    assert restarted.status("match-1")["status"] == "synced"
    enqueue(restarted, match())
    restarted.flush()
    assert len(replacement.calls) == 3


def test_stale_ack_cannot_complete_new_claim(store):
    dispatcher = HistoryDispatcher(store, Channels(store))
    enqueue(dispatcher, match())
    old = dispatcher._claim()
    with store.connect() as db:
        db.execute(update(ScoreDelivery).where(ScoreDelivery.id == old["id"]).values(lease_until="2000-01-01"))
        db.execute(update(HistoryTargetLease).where(HistoryTargetLease.target_key == old["target_key"]).values(lease_until="2000-01-01"))
    replacement = HistoryDispatcher(store, dispatcher.sink)
    new = replacement._claim()
    assert new["id"] == old["id"] and new["token"] != old["token"] and new["reconcile"]
    dispatcher._ack(old, {"old": True})
    with store.connect() as db:
        row = db.get(ScoreDelivery, new["id"])
        assert row.status == "processing" and row.lease_token == new["token"]
    replacement._ack(new, {"new": True})
    with store.connect() as db:
        assert json.loads(db.get(ScoreDelivery, new["id"]).result_json) == {"new": True}


def test_two_workers_never_publish_same_target_in_parallel(store):
    started, release = threading.Event(), threading.Event()
    sink = Channels(store)
    sink.targets = ["one"]
    original = sink.deliver_history
    def slow(target, value, *, reconcile=False):
        started.set()
        assert release.wait(5)
        return original(target, value, reconcile=reconcile)
    sink.deliver_history = slow
    first, second = HistoryDispatcher(store, sink), HistoryDispatcher(store, sink)
    enqueue(first, match())
    enqueue(first, match("match-2", 2))
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(first.flush, 1)
        assert started.wait(5)
        # No second call or source DB lock held while the slow adapter waits.
        second.flush(1)
        assert sink.calls == []
        release.set()
        future.result(timeout=5)
    second.flush(1)
    assert len(sink.calls) == 2


class Sheet:
    def __init__(self, headers=None):
        self.rows = [list(headers or [])]
        self.col_count = len(headers or [])
        self.lost_ack = False
        self.appends = 0

    def row_values(self, number, **kwargs):
        return list(self.rows[number - 1]) if number <= len(self.rows) else []

    def col_values(self, column, **kwargs):
        return [row[column - 1] if len(row) >= column else "" for row in self.rows]

    def get_all_values(self):
        return deepcopy(self.rows)

    def add_cols(self, number):
        self.col_count += number

    def update(self, *, range_name, values, value_input_option):
        found = re.match(r"([A-Z]+)(\d+)", range_name)
        column = 0
        for letter in found[1]:
            column = column * 26 + ord(letter) - ord("A") + 1
        row_number = int(found[2])
        while len(self.rows) < row_number:
            self.rows.append([])
        row = self.rows[row_number - 1]
        row.extend([""] * max(0, column - 1 + len(values[0]) - len(row)))
        row[column - 1:column - 1 + len(values[0])] = values[0]

    def append_row(self, values, **kwargs):
        self.rows.append(list(values))
        self.appends += 1
        if self.lost_ack:
            self.lost_ack = False
            raise TimeoutError("Lost append response")
        return {"updates": {"updatedRange": f"History!A{len(self.rows)}:AJ{len(self.rows)}"}}


def test_real_sheet_adapter_recovers_lost_ack_and_sorted_row():
    sheet = Sheet(HISTORY_HEADERS)
    sink = GSpreadSheets(Settings(spreadsheet_id="book"))
    sink._book = type("Book", (), {"worksheet": lambda self, title: sheet})()
    target = sink.history_targets(match())[0]["target"]
    sheet.lost_ack = True
    with pytest.raises(TimeoutError):
        sink.deliver_history(target, match())
    # A human sorted the data: stable marker lookup still finds the real row.
    sheet.rows.insert(1, ["another-match"])
    result = sink.deliver_history(target, match(), reconcile=True)
    assert result["row"] == 3
    assert sheet.appends == 1
    assert sheet.rows[2][-2] == 1
    assert len(sheet.rows[2][-1]) == 64
    # A fresh adapter accepts the extended header after a process restart.
    restarted = GSpreadSheets(Settings(spreadsheet_id="book"))
    restarted._book = sink._book
    restarted.deliver_history(target, match(), reconcile=True)
    assert sheet.appends == 1


def test_marker_conflict_never_overwrites_remote_scores():
    sheet = Sheet(HISTORY_HEADERS)
    sink = GSpreadSheets(Settings(spreadsheet_id="book"))
    sink._book = type("Book", (), {"worksheet": lambda self, title: sheet})()
    target = sink.history_targets(match())[0]["target"]
    sink.deliver_history(target, match())
    before = deepcopy(sheet.rows)
    changed = match()
    changed["result"]["players"]["east"]["final_points"] = 30000
    with pytest.raises(HistoryNeedsReview):
        sink.deliver_history(target, changed)
    assert sheet.rows == before
    sheet.rows.append(list(sheet.rows[1]))
    with pytest.raises(HistoryNeedsReview, match="Duplicate"):
        sink.deliver_history(target, match())
    assert sheet.appends == 1


def test_legacy_columns_reconcile_and_keep_existing_other_data():
    sheet = Sheet(["Player 1", "Score"])
    sheet.rows.append(["unrelated historic row", 123])
    values = ["east", "south", "west", "north", 25000, 25000, 25000, 25000]
    sheet.lost_ack = True
    with pytest.raises(TimeoutError):
        publish_marked_row(sheet, "match-1", values, marker_column=44, revision_column=45, payload_hash="hash")
    publish_marked_row(sheet, "match-1", values, marker_column=44, revision_column=45, payload_hash="hash")
    assert sheet.appends == 1 and sheet.rows[1] == ["unrelated historic row", 123]


def test_changed_legacy_target_is_visible_and_not_silently_replayed(store):
    sink = GSpreadSheets(Settings(spreadsheet_id="new-book", history_sheet="new-history"))
    dispatcher = HistoryDispatcher(store, sink)
    with store.connect() as db:
        db.add(Metadata(key="sync_target", value=json.dumps(["old-book", "old-current", "old-history"])))
        db.flush()
        dispatcher.enqueue_history(db, match(), legacy=True)
    assert dispatcher.status("match-1")["status"] == "failed"
    with store.connect() as db:
        row = db.scalar(select(ScoreDelivery))
        assert json.loads(row.target_json)["spreadsheet_id"] == "old-book"
        assert json.loads(row.target_json)["worksheet"] == "old-history"
        assert row.error_code == "legacy_target_requires_review"
    dispatcher.flush()
    with store.connect() as db:
        assert db.scalar(select(ScoreDelivery.attempts)) == 0


def seed_legacy(store, value, *, synced=0):
    from mahjong_api.database_models import MatchHistory, TableState
    with store.connect() as db:
        table = db.scalar(select(TableState).where(TableState.table_id == "1"))
        if table is None:
            db.add(TableState(table_id="1", current_match_id="current-new-round", updated_at="now"))
            db.flush()
        row = MatchHistory(match_id=value["match_id"], table_id="1", round_no=value["sequence"],
            scores_json=json.dumps({wind: 25000 for wind in SEATS}), result_json=json.dumps(value["result"]),
            history_synced=synced, clear_synced=synced)
        db.add(row)


def test_legacy_success_is_not_requeued_when_target_changes(store):
    seed_legacy(store, match(), synced=1)
    with store.connect() as db:
        db.add(Metadata(key="sync_target", value=json.dumps(["old-book", "current", "history"])))
    dispatcher = HistoryDispatcher(store, GSpreadSheets(Settings(spreadsheet_id="new-book")))
    assert dispatcher.status("match-1") == {"status": "synced", "revision": None, "channels": [], "legacy": True}
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ScoreRecord)) == 0


def test_legacy_pending_import_is_idempotent_and_bounded(store):
    for number in range(1, 104):
        seed_legacy(store, match(f"match-{number}", number))
    sink = Channels(store)
    sink.targets = ["one"]
    dispatcher = HistoryDispatcher(store, sink)
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ScoreRecord)) == 100
    dispatcher.flush(limit=0)
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ScoreRecord)) == 103
    HistoryDispatcher(store, sink)
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ScoreDelivery)) == 103
    assert sink.calls == []


def test_disabled_sink_has_no_perpetual_pending_status(store):
    from mahjong_api.database_models import MatchHistory
    from mahjong_api.sheets import DisabledSheets
    seed_legacy(store, match())
    dispatcher = HistoryDispatcher(store, DisabledSheets())
    assert dispatcher.status("match-1")["status"] == "synced"
    with store.connect() as db:
        assert db.scalar(select(MatchHistory.history_synced)) == 1
        assert db.scalar(select(func.count()).select_from(ScoreDelivery)) == 0


def test_disabled_current_config_does_not_drop_old_sheet_obligation(store):
    from mahjong_api.sheets import DisabledSheets
    seed_legacy(store, match())
    with store.connect() as db:
        db.add(Metadata(key="sync_target", value=json.dumps(["old-book", "current", "history"])))
    dispatcher = HistoryDispatcher(store, DisabledSheets())
    assert dispatcher.status("match-1")["status"] == "failed"
    with store.connect() as db:
        row = db.scalar(select(ScoreDelivery))
        assert json.loads(row.target_json)["spreadsheet_id"] == "old-book"
        assert row.error_code == "legacy_target_requires_review"


def test_local_club_projection_recovers_without_duplicate_mmr(store, tmp_path):
    from contextlib import closing
    import mahjong_store
    from mahjong_api.club_history import ClubHistorySink
    from mahjong_api.sheets import DisabledSheets
    club = tmp_path / "club.sqlite3"
    sink = ClubHistorySink(DisabledSheets(), club)
    original = sink.deliver_history
    lost = [True]
    def lose_ack(target, value, *, reconcile=False):
        result = original(target, value, reconcile=reconcile)
        if lost[0]:
            lost[0] = False
            raise TimeoutError("Source acknowledgement lost after club committed")
        return result
    sink.deliver_history = lose_ack
    dispatcher = HistoryDispatcher(store, sink)
    enqueue(dispatcher, match())
    dispatcher.flush()
    assert dispatcher.status("match-1")["status"] == "delivery_unknown"
    dispatcher.retry("match-1")
    dispatcher.flush()
    assert dispatcher.status("match-1")["status"] == "synced"
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
        assert [row[0] for row in db.execute("SELECT games_played FROM players")] == [1, 1, 1, 1]
        assert db.execute("SELECT sync_status FROM games").fetchone()[0] == "disabled"


def test_failed_club_projection_cannot_be_overtaken(store):
    sink = Channels(store)
    sink.targets = ["club"]
    sink.history_targets = lambda value: [{"channel": "club", "kind": "projection", "target": {"adapter": "fake-club"}}]
    attempts, failure = [], [True]
    def project(target, value, *, reconcile=False):
        attempts.append(value["match_id"])
        if failure[0]:
            failure[0] = False
            raise RuntimeError("Local projection unavailable")
        return {"match_id": value["match_id"]}
    sink.deliver_history = project
    dispatcher = HistoryDispatcher(store, sink)
    enqueue(dispatcher, match())
    enqueue(dispatcher, match("match-2", 2))
    dispatcher.flush()
    assert attempts == ["match-1"]
    dispatcher.retry("match-1")
    dispatcher.flush()
    assert attempts == ["match-1", "match-1", "match-2"]


def test_rate_limit_retry_after_is_honored_even_by_explicit_retry(store):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    sink = Channels(store)
    sink.targets = ["one"]
    class RateLimited(Exception):
        response = SimpleNamespace(status_code=429, headers={"Retry-After": "120"})
    sink.deliver_history = lambda *args, **kwargs: (_ for _ in ()).throw(RateLimited())
    dispatcher = HistoryDispatcher(store, sink)
    enqueue(dispatcher, match())
    dispatcher.flush()
    with store.connect() as db:
        row = db.scalar(select(ScoreDelivery))
        due = row.next_attempt_at
        assert row.status == "retrying" and row.error_code == "history_rate_limited"
        assert (datetime.fromisoformat(due) - datetime.now(timezone.utc)).total_seconds() > 115
    dispatcher.retry("match-1")
    with store.connect() as db:
        assert db.scalar(select(ScoreDelivery.next_attempt_at)) == due


def test_remote_rejection_stays_failed_until_explicit_retry(store):
    from types import SimpleNamespace
    sink = Channels(store)
    sink.targets = ["one"]
    original = sink.deliver_history
    class Rejected(Exception):
        response = SimpleNamespace(status_code=403, headers={})
    sink.deliver_history = lambda *args, **kwargs: (_ for _ in ()).throw(Rejected())
    dispatcher = HistoryDispatcher(store, sink)
    enqueue(dispatcher, match())
    dispatcher.flush()
    assert dispatcher.status("match-1")["status"] == "failed"
    sink.deliver_history = original
    dispatcher.flush()
    assert sink.calls == []
    dispatcher.retry("match-1")
    dispatcher.flush()
    assert dispatcher.status("match-1")["status"] == "synced"


def test_sheet_target_order_survives_failure_without_blocking_other_targets(store):
    sink = Channels(store)
    sink.targets = ["riichi", "pt"]
    original = sink.deliver_history
    failed = [True]
    def unavailable(target, value, *, reconcile=False):
        if target["name"] == "riichi" and value["match_id"] == "match-1" and failed[0]:
            failed[0] = False
            raise RuntimeError("First game unavailable at this target")
        return original(target, value, reconcile=reconcile)
    sink.deliver_history = unavailable
    dispatcher = HistoryDispatcher(store, sink)
    enqueue(dispatcher, match())
    enqueue(dispatcher, match("match-2", 2))
    dispatcher.flush()
    assert [key[2] for key in sink.rows if key[1] == "pt"] == ["match-1", "match-2"]
    assert [key[2] for key in sink.rows if key[1] == "riichi"] == []
    dispatcher.retry("match-1")
    dispatcher.flush()
    assert [key[2] for key in sink.rows if key[1] == "riichi"] == ["match-1", "match-2"]


def test_headerless_metadata_column_with_data_or_formula_is_never_claimed():
    for occupied in ("unrelated-data", '=IF(A2="","","existing")'):
        sheet = Sheet(["Player"])
        sheet.col_count = 46
        sheet.rows.append([""] * 44 + [occupied])
        before = deepcopy(sheet.rows)
        with pytest.raises(HistoryNeedsReview, match="without a header"):
            publish_marked_row(sheet, "match-1", ["east"], marker_column=44, revision_column=45, payload_hash="hash")
        assert sheet.rows == before and sheet.appends == 0
        assert sheet.col_count == 46


def test_late_imported_legacy_backlog_cannot_be_overtaken_by_new_game(store):
    sink = Channels(store)
    sink.targets = ["one"]
    dispatcher = HistoryDispatcher(store, sink)
    seed_legacy(store, match("legacy-1", 1))
    seed_legacy(store, match("legacy-2", 2))
    assert dispatcher.import_legacy_pending(limit=1) == 1
    enqueue(dispatcher, match("new-confirmation", 3))
    first = dispatcher._claim()
    assert first["game_id"] == "legacy-1"
    dispatcher._ack(first, {"match_id": "legacy-1"})
    assert dispatcher.import_legacy_pending(limit=1) == 1
    next_claim = dispatcher._claim()
    assert next_claim["game_id"] == "legacy-2"


def test_undiscovered_legacy_channels_are_not_overtaken(store):
    sink = Channels(store)
    sink.targets = ["one"]
    dispatcher = HistoryDispatcher(store, sink)
    seed_legacy(store, match("unimported-old", 1))
    enqueue(dispatcher, match("new-confirmation", 2))
    assert dispatcher._claim() is None
    dispatcher.import_legacy_pending()
    assert dispatcher._claim()["game_id"] == "unimported-old"


def test_unreadable_legacy_target_is_not_falsely_completed_when_current_sink_disabled(store):
    from mahjong_api.sheets import DisabledSheets
    seed_legacy(store, match())
    with store.connect() as db:
        db.add(Metadata(key="sync_target", value="unrecognized-old-target"))
    dispatcher = HistoryDispatcher(store, DisabledSheets())
    assert dispatcher.status("match-1")["status"] == "failed"
    assert dispatcher.status("match-1")["channels"][0]["error_code"] == "legacy_target_requires_review"
