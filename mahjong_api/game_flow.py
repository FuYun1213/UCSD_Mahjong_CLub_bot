"""Ordinary table game lifecycle; live seats and score snapshots are separate."""
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select

from .database_models import MatchHistory, ScoreDraft, SeatRecord, TableState
from .game_round_models import GameRound
from .models import SEATS, User
from .store import Conflict, elapsed, now
from .table_membership import (check, lock_table, membership_lock, ordinary_join,
                               release_member, release_table, table_open)
from .table_models import ActiveTableMember, ClubTable, TableMembershipEvent


def frozen_roster(db, score_table_id):
    seats = {wind: None for wind in SEATS}
    for row in db.scalars(select(SeatRecord).where(SeatRecord.table_id == score_table_id)):
        seats[row.seat] = {"id": row.user_id, "name": row.user_name}
    check(all(seats.values()) and len({person["id"] for person in seats.values()}) == 4,
          "incomplete_table")
    return seats


def ensure_game_round(db, registry, score, *, timestamp=None, actor_id=None):
    """Capture only the current live game, never infer an old game's roster."""
    row = db.get(GameRound, score.current_match_id)
    if row:
        return row
    check(score.started_at is not None, "game_not_started")
    stamp = timestamp or now()
    row = GameRound(game_id=score.current_match_id, table_id=registry.id,
        score_table_id=score.table_id, round_no=score.round_no,
        roster_json=json.dumps(frozen_roster(db, score.table_id), ensure_ascii=False),
        started_at=score.started_at, status="playing", created_at=stamp, updated_at=stamp)
    db.add(row)
    db.flush()
    if not registry.tournament_id:
        # This snapshot is the first reliable indication that the current
        # four-player game started. Claim only reservations eligible then.
        from .reservation_queue import link_started_game
        link_started_game(db, registry.id, row.game_id, json.loads(row.roster_json),
                          row.started_at, str(actor_id or registry.created_by or ""))
    return row


def game_view(row):
    if row is None:
        return None
    return {"game_id": row.game_id, "match_id": row.game_id, "table_id": row.table_id,
        "round_no": row.round_no, "players": json.loads(row.roster_json),
        "started_at": row.started_at, "actual_ended_at": row.actual_ended_at,
        "actual_end_by": row.actual_end_by,
        "status": row.status, "all_last_at": row.all_last_at,
        "all_last_by": row.all_last_by, "successor_batch_id": row.successor_batch_id}


def abort_current_ordinary_game(db, table, score, actor_id, reason, stamp,
                                *, require_started=False):
    """Discard only the current unscored game and its live seats atomically.

    The frozen round and membership audit remain; a confirmed score can never
    enter this path because its history/outbox cannot be reversed here.
    """
    check(not score.pending_match_id and not db.scalar(select(MatchHistory.match_id).where(
        MatchHistory.match_id == score.current_match_id)), "score_exists")
    game = db.get(GameRound, score.current_match_id)
    if score.started_at and game is None:
        game = ensure_game_round(db, table, score, timestamp=score.started_at,
                                 actor_id=actor_id)
    if require_started:
        check(score.started_at is not None and game is not None,
              "game_not_started")
    if game is not None:
        check(game.status == "playing", "game_already_completed")
    drafts = list(db.scalars(select(ScoreDraft).where(
        ScoreDraft.match_id == score.current_match_id)))
    check(all(draft.status != "submitted" for draft in drafts), "score_exists")
    roster = [{"id": seat.user_id, "name": seat.user_name, "seat": seat.seat}
              for seat in db.scalars(select(SeatRecord).where(
                  SeatRecord.table_id == score.table_id))]
    snapshot = {"match_id": score.current_match_id,
                "started_at": score.started_at, "roster": roster}
    for draft in drafts:
        draft.status = "void"
    if game is not None:
        game.status, game.updated_at = "void", stamp
        from .reservation_queue import on_game_voided
        on_game_voided(db, game.game_id)
        from .discord_reminder_models import DiscordReminder
        for notice in db.scalars(select(DiscordReminder).where(
                DiscordReminder.predecessor_game_id == game.game_id,
                DiscordReminder.status.in_(("pending", "retrying", "failed")))):
            notice.status, notice.last_error = "cancelled", "game_cancelled"
            notice.claim_token, notice.lease_until = None, None
            notice.updated_at = stamp
    from .seat_swap_state import invalidate_swaps
    invalidate_swaps(db, table.id, reason="game_cancelled", actor=actor_id,
                     timestamp=stamp)
    release_table(db, table.id, actor_id, reason, score.current_match_id)
    db.execute(delete(SeatRecord).where(SeatRecord.table_id == score.table_id))
    score.current_match_id, score.started_at = str(uuid4()), None
    score.round_no += 1
    score.updated_at, score.dirty = stamp, 0
    from .external_sync import audit
    audit(db, "", actor_id, "table_match_aborted", {
        "table_id": table.id, "reason": reason, "snapshot": snapshot})
    return snapshot


class GameFlowService:
    def __init__(self, tables):
        self.tables, self.matches, self.store = tables, tables.matches, tables.store
        self.clock = now

    def _table(self, db, reference, *, writable=False):
        row = db.get(ClubTable, reference) or db.scalar(select(ClubTable).where(
            ClubTable.score_table_id == reference))
        table_open(db, row)
        check(not row.tournament_id, "fixed_tournament_seating")
        if writable:
            from .reservation_sessions import lock_scope
            lock_scope(db, row.scope)
            lock_table(db, row.id)
            db.refresh(row)
            table_open(db, row)
        return row

    @staticmethod
    def _score(db, table):
        score = db.scalar(select(TableState).where(TableState.table_id == table.score_table_id))
        check(score is not None, "table_not_found")
        return score

    @staticmethod
    def _operator(db, table, score, user):
        check(user is not None, "not_authenticated")
        if user.role in {"admin", "super_admin"}:
            return
        member = db.get(ActiveTableMember, str(user.id))
        check(member is not None and member.table_id == table.id and
              member.match_id == score.current_match_id, "must_join_first")

    def _next(self, db, table):
        from .reservation_queue import next_batch, batch_members
        batch = next_batch(db, table.id, now_value=self.clock())
        if batch is None:
            return None
        members = batch_members(db, batch.id)
        return {"id": batch.id, "version": batch.version, "status": batch.status,
            "estimated_start_at": batch.estimated_start_at,
            "estimated_end_at": batch.estimated_end_at,
            "missing_players": max(0, 4-len(members)),
            "participants": [{"user_id": member.user_id, "name": member.user_name,
                "remaining_games": member.remaining_games_snapshot,
                "reservation_id": member.reservation_id} for member in members]}

    def _state(self, db, table, user):
        score = self._score(db, table)
        current = db.get(GameRound, score.current_match_id)
        if current is None and score.started_at and not db.scalar(select(MatchHistory.match_id).where(MatchHistory.match_id == score.current_match_id)):
            current = ensure_game_round(db, table, score)
        pending = list(db.scalars(select(GameRound).where(GameRound.table_id == table.id,
            GameRound.status == "awaiting_score").order_by(GameRound.started_at, GameRound.game_id)))
        return {"table_id": table.id, "score_table_id": table.score_table_id,
            "current_game": game_view(current),
            "current_match_id": score.current_match_id,
            "pending_scores": [game_view(row) for row in pending],
            "next_batch": self._next(db, table), "server_now": self.clock()}

    def state(self, table_id, user):
        check(user is not None, "not_authenticated")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id, writable=True)
            return self.tables.display_names(self._state(db, table, user))

    def all_last(self, table_id, data, user):
        check(isinstance(data, dict), "invalid_request")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id, writable=True)
            score = self._score(db, table)
            self._operator(db, table, score, user)
            check(data.get("match_id") == score.current_match_id, "stale_match")
            check(score.started_at and not score.pending_match_id, "game_not_started")
            check(not db.scalar(select(MatchHistory.match_id).where(
                MatchHistory.match_id == score.current_match_id)), "game_already_completed")
            game = ensure_game_round(db, table, score)
            check(game.status == "playing" and game.actual_ended_at is None,
                  "game_already_completed")
            first = game.all_last_at is None
            if first:
                game.all_last_at, game.all_last_by, game.updated_at = self.clock(), str(user.id), self.clock()
            batch = self._next(db, table)
            if batch:
                game.successor_batch_id = batch["id"]
                from .queue_notifications import enqueue_queue_notice
                enqueue_queue_notice(db, table, game, batch, "queue_all_last", self.clock())
            value = self._state(db, table, user)
            value["replayed"] = not first
            return self.tables.display_names(value)

    @staticmethod
    def _record_end(game, value, actor, stamp):
        check(game.status in {"playing", "awaiting_score", "completed"}, "game_already_completed")
        check(isinstance(value, str), "invalid_actual_end")
        try:
            ended = datetime.fromisoformat(value.replace("Z", "+00:00"))
            started = datetime.fromisoformat(game.started_at.replace("Z", "+00:00"))
            current = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            raise Conflict("invalid_actual_end", "invalid_actual_end") from None
        check(ended.tzinfo is not None and started < ended <= current, "invalid_actual_end")
        normalized = ended.astimezone(timezone.utc).isoformat(timespec="milliseconds")
        check(game.actual_ended_at is None or game.actual_ended_at == normalized,
              "actual_end_conflict")
        if game.actual_ended_at is None:
            game.actual_ended_at = normalized
            game.end_time_source = "player_reported"
            game.actual_end_by = str(actor)
            game.updated_at = stamp
        return normalized

    def record_end(self, table_id, game_id, data, user):
        check(user is not None and isinstance(data, dict), "not_authenticated")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id, writable=True)
            game = db.get(GameRound, game_id)
            check(game is not None and game.table_id == table.id, "game_not_found")
            roster = json.loads(game.roster_json)
            check(user.role in {"admin", "super_admin"} or
                  str(user.id) in {person["id"] for person in roster.values()},
                  "must_join_first")
            ended = self._record_end(game, data.get("actual_ended_at"), user.id, self.clock())
            if game.status == "completed":
                history = db.scalar(select(MatchHistory).where(MatchHistory.match_id == game.game_id))
                if history is not None:
                    duration = elapsed(game.started_at, ended)
                    history.ended_at, history.duration_seconds = ended, duration
                    result = json.loads(history.result_json)
                    result["ended_at"], result["duration_seconds"] = ended, duration
                    history.result_json = json.dumps(result, ensure_ascii=False)
                from .reservation_queue import on_game_confirmed
                on_game_confirmed(db, game.game_id)
            return self.tables.display_names(self._state(db, table, user))

    def remove_other(self, table_id, target_user_id, data, user):
        check(user is not None and isinstance(data, dict), "not_authenticated")
        check(isinstance(target_user_id, str) and target_user_id and
              target_user_id != str(user.id), "invalid_player_ids")
        wind = data.get("seat")
        check(wind in SEATS, "invalid_seat")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id, writable=True)
            score = self._score(db, table)
            check(data.get("match_id") == score.current_match_id, "stale_match")
            target = db.get(ActiveTableMember, target_user_id)
            if target is None or target.table_id != table.id:
                previous = db.scalar(select(TableMembershipEvent.id).where(
                    TableMembershipEvent.table_id == table.id,
                    TableMembershipEvent.match_id == score.current_match_id,
                    TableMembershipEvent.user_id == target_user_id,
                    TableMembershipEvent.actor_id == str(user.id),
                    TableMembershipEvent.action == "removed",
                    TableMembershipEvent.seat == wind).limit(1))
                check(previous is not None, "target_not_at_table")
                value = self._state(db, table, user)
                value.update(removed=False, replayed=True)
                return self.tables.display_names(value)
            check(target.match_id == score.current_match_id and target.seat == wind,
                  "stale_target_seat")
            seat = db.get(SeatRecord, (score.table_id, wind))
            check(seat is not None and seat.user_id == target_user_id,
                  "stale_target_seat")
            # Any signed-in member can manage forming tables. Running games
            # keep their seats and immutable scoring roster protected.
            check(score.started_at is None, "cannot_remove_started")
            check(not score.pending_match_id and not db.scalar(select(ScoreDraft.id).where(
                ScoreDraft.match_id == score.current_match_id,
                ScoreDraft.status.in_(["review", "submitted"]))), "score_exists")
            stamp = self.clock()
            db.delete(seat)
            release_member(db, target, user.id, "removed_by_player", stamp,
                           action="removed")
            score.updated_at, score.dirty = stamp, 0
            from .external_sync import audit
            audit(db, "", user.id, "table_player_removed", {
                "table_id": table.id, "match_id": score.current_match_id,
                "target_user_id": target_user_id, "target_name": seat.user_name,
                "seat": wind, "at": stamp})
            value = self._state(db, table, user)
            value.update(removed=True, replayed=False)
            return self.tables.display_names(value)

    def cancel_game(self, table_id, data, user):
        check(user is not None and isinstance(data, dict), "not_authenticated")
        reason = str(data.get("reason", "wrong_players")).strip()
        check(1 <= len(reason) <= 500, "reason_required")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id, writable=True)
            key, fingerprint, old = self.tables._command(
                db, user, "game_cancel:" + table.id, data)
            if old:
                return {"table_id": table.id, "match_id": old.result_id,
                        "cancelled": True, "replayed": True}
            score = self._score(db, table)
            self._operator(db, table, score, user)
            check(data.get("match_id") == score.current_match_id, "stale_match")
            snapshot = abort_current_ordinary_game(
                db, table, score, str(user.id), reason, self.clock(),
                require_started=True)
            self.tables._remember(db, key, fingerprint, snapshot["match_id"])
            return {"table_id": table.id, "match_id": snapshot["match_id"],
                    "cancelled": True, "replayed": False}

    def start_next(self, table_id, data, user):
        check(isinstance(data, dict), "invalid_request")
        seats = data.get("seats")
        check(isinstance(seats, dict) and set(seats) == set(SEATS) and
              all(isinstance(uid, str) and uid for uid in seats.values()) and
              len(set(seats.values())) == 4, "invalid_seat")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id, writable=True)
            score = self._score(db, table)
            self._operator(db, table, score, user)
            check(data.get("match_id") == score.current_match_id, "stale_match")
            current = ensure_game_round(db, table, score)
            check(current.status == "playing" and current.all_last_at is not None,
                  "all_last_required")
            check(not score.pending_match_id, "settlement_pending")
            batch = self._next(db, table)
            check(batch is not None and batch["id"] == data.get("batch_id"), "stale_batch")
            check(batch["version"] == data.get("batch_version"), "queue_version_conflict")
            members = batch["participants"]
            check(len(members) == 4 and set(seats.values()) == {p["user_id"] for p in members},
                  "invalid_batch_players")
            from .reservation_queue import start_batch
            new_id, stamp = str(uuid4()), self.clock()
            if data.get("previous_actual_ended_at") is not None:
                self._record_end(current, data["previous_actual_ended_at"], user.id, stamp)
            # Reservation claims, live seat transfer, and two game-state changes
            # commit together. The old GameRound keeps its original wind map.
            started = start_batch(db, table.id, batch["id"], new_id, stamp,
                                  str(user.id), expected_version=batch["version"])
            check({p.user_id for p in started} == set(seats.values()), "stale_batch")
            release_table(db, table.id, str(user.id), "next_game", score.current_match_id)
            db.execute(delete(SeatRecord).where(SeatRecord.table_id == score.table_id))
            current.status, current.successor_batch_id, current.updated_at = (
                "awaiting_score", batch["id"], stamp)
            score.current_match_id, score.round_no = new_id, score.round_no + 1
            score.started_at, score.pending_match_id = None, None
            score.updated_at, score.dirty = stamp, 0
            people = {member.user_id: member.user_name for member in started}
            for wind in SEATS:
                uid = seats[wind]
                ordinary_join(db, score, User(id=uid, name=people[uid]), str(user.id),
                              "registered_name", wind)
            score.started_at = stamp
            created = db.get(GameRound, new_id)
            check(created is not None, "game_snapshot_missing")
            created.started_at, created.updated_at = stamp, stamp
            return self.tables.display_names(self._state(db, table, user))

