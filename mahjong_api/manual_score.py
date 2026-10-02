"""Manual scoring without a photo, using the existing account and score rules."""
import json
from contextlib import nullcontext
import logging
import re
import unicodedata
from uuid import NAMESPACE_URL, uuid4, uuid5
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .database_models import User as Account, MatchHistory
from .external_sync import audit, dump, queue_free_match
from .discord_score_notify import schedule_score_notification
from .manual_score_models import ManualScoreDraft, ManualScorePlayer, ManualScoreRequest
from .models import SEATS, Scores, SCORE_STEP, SCORE_MAX_ABSOLUTE
from .scoring import calculate_match_result
from .store import Conflict, now
from .table_membership import membership_lock, check, table_open, lock_table
from .table_models import ClubTable
from .tournament_models import ExternalDelivery

from competition_time import event_time, site_timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

def declared_time(data):
    value=data.get("played_at")
    if value is None:return None  # Legacy clients have no authoritative event time.
    try:return event_time(value)
    except ValueError:field_error({"played_at":"invalid_played_at"})


def field_error(errors, code="invalid_manual_score", totals=None):
    detail = {"code": code, "field_errors": errors}
    if totals is not None:
        detail["score_totals"] = totals
    raise HTTPException(422, detail=detail)


class ManualScoreService:
    def __init__(self, matches, tables):
        self.matches, self.tables, self.store = matches, tables, matches.store

    def rules(self):
        return {"step": SCORE_STEP, "max_absolute": SCORE_MAX_ABSOLUTE,
                "expected_total": self.matches.settings.initial_points * 4}

    def search_players(self, query=""):
        check(isinstance(query, str) and len(query) <= 128, "invalid_player_ids")
        normalize = lambda value: " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()
        needle = normalize(query)
        rows = [r for r in self.tables._account_rows() if not r.get("disabled")
                and (not needle or needle in normalize(r.get("name", "")))]
        rows.sort(key=lambda r: (r["name"].casefold(), str(r["id"])))
        return {"players": [{"id": str(r["id"]), "name": r["name"], "avatar": r.get("avatar", "")}
                            for r in rows[:50]], "has_more": len(rows) > 50}

    def lookup_players(self, value):
        values = re.split(r"[\s,，]+", value.strip()) if isinstance(value, str) else value
        check(isinstance(values, list) and 1 <= len(values) <= 50, "invalid_player_ids")
        unique = {}
        for uid in values:
            check(isinstance(uid, str) and 1 <= len(uid.strip()) <= 128, "invalid_player_ids")
            unique.setdefault(uid.strip(), uid.strip())
        return {"players": self.tables.lookup_accounts(list(unique.values()))}

    def _context(self, table_id, user, writable=False, session=None, match_id=None):
        if not table_id:
            return {"table_id": None, "table": None, "match_id": None,
                    "players": dict.fromkeys(SEATS), "score_rules": self.rules(), "timezone": site_timezone(), "played_at_default": datetime.now(ZoneInfo(site_timezone())).strftime("%Y-%m-%dT%H:%M")}
        check(isinstance(table_id, str) and len(table_id) <= 64, "invalid_table_id")
        with (nullcontext(session) if session is not None else self.store.connect()) as db:
            registered = db.get(ClubTable, table_id) or db.scalar(select(ClubTable).where(ClubTable.score_table_id == table_id))
            if writable and registered is not None:
                lock_table(db, registered.id)
                db.refresh(registered)
            table_open(db, registered)
            check(not registered.tournament_id, "fixed_tournament_seating")
            table = self.store._table(db, registered.score_table_id)
            check(table is not None, "table_not_found")
            if match_id and match_id != table["current_match_id"]:
                from .game_round_models import GameRound
                prior = db.get(GameRound, match_id)
                check(prior is not None and prior.table_id == registered.id and
                      prior.status == "awaiting_score", "stale_match")
                table = {**table, "current_match_id": prior.game_id,
                         "seats": json.loads(prior.roster_json), "pending_match_id": None}
            if writable:
                check(not table["pending_match_id"], "settlement_pending")
            return {"table_id": registered.id, "table": registered.score_table_id,
                    "match_id": table["current_match_id"], "players": table["seats"], "table_name": registered.display_name,
                    "score_rules": self.rules(), "timezone": site_timezone(), "played_at_default": datetime.now(ZoneInfo(site_timezone())).strftime("%Y-%m-%dT%H:%M")}

    def context(self, table_id, user, match_id=None):
        with membership_lock:
            return self._context(table_id, user, match_id=match_id)

    def validate(self, players, scores):
        errors, normalized, seen = {}, {}, set()
        if not isinstance(players, dict) or set(players) != set(SEATS):
            field_error({"players": "four_players_required"})
        for seat in SEATS:
            uid = players[seat]
            if not isinstance(uid, str) or not 1 <= len(uid.strip()) <= 128:
                errors["players." + seat] = "invalid_player_ids"
                continue
            key = uid.strip()
            if key in seen:
                errors["players." + seat] = "duplicate_player_ids"
                for earlier in SEATS:
                    if isinstance(players[earlier], str) and players[earlier].strip() == key:
                        errors["players." + earlier] = "duplicate_player_ids"
                continue
            seen.add(key)
            try:
                normalized[seat] = self.tables.lookup_accounts([uid.strip()])[0]
            except Conflict as exc:
                errors["players." + seat] = exc.detail["code"]
        if len(normalized) == 4 and len({p["id"] for p in normalized.values()}) != 4:
            for seat in SEATS:
                if sum(p["id"] == normalized[seat]["id"] for p in normalized.values()) > 1:
                    errors["players." + seat] = "duplicate_player_ids"
        try:
            checked_scores = Scores.model_validate(scores).model_dump()
        except ValidationError as exc:
            checked_scores = None
            for item in exc.errors():
                path = ".".join(str(part) for part in item["loc"])
                errors["scores" + ("." + path if path else "")] = "invalid_score"
        if checked_scores is not None:
            try:
                calculate_match_result(checked_scores, self.matches.settings.initial_points)
            except ValueError:
                errors["scores"] = "invalid_score_total"
        if errors:
            field_error(errors, "invalid_score_total" if errors == {"scores": "invalid_score_total"} else "invalid_manual_score",
                {"current": sum(checked_scores.values()), "expected": self.rules()["expected_total"],
                 "difference": sum(checked_scores.values()) - self.rules()["expected_total"]} if checked_scores is not None else None)
        return normalized, checked_scores

    def _view(self, draft):
        return {"draft_id": draft.id, "status": "needs_confirmation" if draft.status == "review" else draft.status,
                "table_id": draft.table_id, "table": draft.score_table_id,
                "players": json.loads(draft.players_json), "scores": json.loads(draft.scores_json), "played_at": draft.played_at,
                "score_rules": self.rules(), "timezone": site_timezone(), "played_at_default": datetime.now(ZoneInfo(site_timezone())).strftime("%Y-%m-%dT%H:%M")}

    def _draft(self, db, draft_id, user):
        draft = db.scalar(select(ManualScoreDraft).where(ManualScoreDraft.id == draft_id))
        if draft is None:
            raise HTTPException(404, detail={"code": "draft_not_found"})
        if draft.uploader_id != str(user.id):
            raise HTTPException(403, detail={"code": "not_draft_owner"})
        return draft

    def get_draft(self, draft_id, user):
        with self.store.connect() as db:
            draft = self._draft(db, draft_id, user)
            view, submitted = self._view(draft), draft.status == "submitted"
        if submitted:
            view["submission"] = self._response(draft_id, True)[0]
        return view

    def preview(self, data, user):
        players, scores = self.validate(data.get("players"), data.get("scores"))
        with membership_lock:
            context = self._context(data.get("table_id"), user, writable=True, match_id=data.get("match_id"))
            errors = {"players." + seat: "seat_player_mismatch" for seat in SEATS
                      if context["players"][seat] and context["players"][seat]["id"] != players[seat]["id"]}
            if errors:
                field_error(errors)
            with self.store.connect() as db:
                draft = ManualScoreDraft(id=str(uuid4()), table_id=context["table_id"], score_table_id=context["table"],
                    match_id=context["match_id"] or "manual-" + str(uuid4()), uploader_id=str(user.id), created_at=now(), played_at=declared_time(data),
                    players_json=dump(players), scores_json=dump(scores), roster_json=dump(context["players"]), status="review")
                db.add(draft)
                db.flush()
                return self._view(draft)

    @staticmethod
    def _same_upload(draft, data, user):
        # An idempotency key permanently identifies one immutable submission.
        # Compare stored stable account keys, never mutable display names.
        supplied = data.get("players")
        saved = json.loads(draft.players_json)
        same_players = isinstance(supplied, dict) and set(supplied) == set(SEATS) and all(
            isinstance(supplied[s], str) and supplied[s].strip() == str(saved[s]["id"])
            for s in SEATS)
        supplied_scores = data.get("scores")
        same_scores = isinstance(supplied_scores, dict) and set(supplied_scores) == set(SEATS) and all(
            type(supplied_scores[s]) is int and supplied_scores[s] == json.loads(draft.scores_json)[s] for s in SEATS)
        table = data.get("table_id") or None
        check(draft.uploader_id == str(user.id) and same_players and same_scores and
              table in {draft.table_id, draft.score_table_id} and declared_time(data) == draft.played_at, "submission_conflict")

    def upload(self, data, user):
        request_id = data.get("request_id")
        check(isinstance(request_id, str) and 1 <= len(request_id) <= 128, "request_id_required")
        # The stable draft exists before confirmation. A crash or lost HTTP
        # response at either boundary resumes this draft instead of making one.
        draft_id = str(uuid5(NAMESPACE_URL, dump(["manual-score-upload-v1", str(user.id), request_id])))
        with self.tables.account_guard(), membership_lock:
            with self.store.connect() as db:
                previous = db.get(ManualScoreRequest, request_id)
                check(previous is None or previous.draft_id == draft_id and previous.uploader_id == str(user.id), "submission_conflict")
                draft = db.scalar(select(ManualScoreDraft).where(ManualScoreDraft.id == draft_id))
                if draft is not None:
                    self._same_upload(draft, data, user)
            if draft is None:
                try:
                    players, scores = self.validate(data.get("players"), data.get("scores"))
                    with self.store.connect() as db:
                        context = self._context(data.get("table_id"), user, writable=True, session=db, match_id=data.get("match_id"))
                        errors = {"players." + seat: "seat_player_mismatch" for seat in SEATS
                                  if context["players"][seat] and context["players"][seat]["id"] != players[seat]["id"]}
                        if errors:
                            field_error(errors)
                        db.add(ManualScoreDraft(id=draft_id, table_id=context["table_id"], score_table_id=context["table"],
                            match_id=context["match_id"] or "manual-" + str(uuid4()), uploader_id=str(user.id), created_at=now(), played_at=declared_time(data),
                            players_json=dump(players), scores_json=dump(scores), roster_json=dump(context["players"]), status="review"))
                        db.flush()
                except (IntegrityError, HTTPException, Conflict) as exc:
                    # Another process can finish while this one waits for the
                    # table write lock. Its completion may have cleared seats;
                    # recover the winning draft before applying current seating.
                    with self.store.connect() as db:
                        draft = db.scalar(select(ManualScoreDraft).where(ManualScoreDraft.id == draft_id))
                        if draft is None:
                            raise exc
                        self._same_upload(draft, data, user)
        return self.confirm({"draft_id": draft_id, "request_id": request_id}, user)

    def retry(self, draft_id, user):
        with self.store.connect() as db:
            draft = self._draft(db, draft_id, user)
            check(draft.status == "submitted", "submission_not_saved")
            key = "nfc-" + draft.match_id
        # Reuse the durable endpoint/body/idempotency key from ExternalSync.
        self.matches.history.retry(draft.match_id)
        if self.matches.external.get(key):
            self.matches.external.schedule_retry(key, actor=str(user.id))
        return self._response(draft_id, True)

    def confirm(self, data, user):
        request_id, draft_id = data.get("request_id"), data.get("draft_id")
        check(isinstance(request_id, str) and 1 <= len(request_id) <= 128, "request_id_required")
        check(isinstance(draft_id, str) and 1 <= len(draft_id) <= 64, "invalid_draft_id")
        try:
            with self.tables.account_guard(), membership_lock, self.store.connect() as db:
                # Serialize this draft before reading its status. SQLite acquires
                # its write lock with the UPDATE; PostgreSQL locks the row.
                if db.bind.dialect.name == "sqlite":
                    db.execute(update(ManualScoreDraft).where(ManualScoreDraft.id == draft_id)
                               .values(status=ManualScoreDraft.status))
                else:
                    db.execute(select(ManualScoreDraft.id).where(ManualScoreDraft.id == draft_id).with_for_update())
                draft = self._draft(db, draft_id, user)
                previous = db.get(ManualScoreRequest, request_id)
                check(previous is None or previous.draft_id == draft_id and previous.uploader_id == str(user.id), "submission_conflict")
                if previous is None:
                    db.add(ManualScoreRequest(request_id=request_id, draft_id=draft_id,
                                              uploader_id=str(user.id), created_at=now()))
                    db.flush()
                replayed = draft.status == "submitted"
                if not replayed:
                    saved_players = json.loads(draft.players_json)
                    players, scores = self.validate({s: saved_players[s]["id"] for s in SEATS}, json.loads(draft.scores_json))
                    points = calculate_match_result(scores, self.matches.settings.initial_points)
                    if draft.table_id:
                        context = self._context(draft.table_id, user, writable=True, session=db, match_id=draft.match_id)
                        check(context["match_id"] == draft.match_id, "stale_match")
                        old_roster = json.loads(draft.roster_json)
                        check({s: p["id"] if p else None for s, p in context["players"].items()} ==
                              {s: p["id"] if p else None for s, p in old_roster.items()}, "stale_roster")
                        self.store.stage_match(draft.score_table_id, scores, points, draft.match_id, None,
                            uploader_id=str(user.id), ended_at=draft.created_at, roster=players, session=db, authoritative_played_at=draft.played_at)
                        result = self.store._match(db.scalar(select(MatchHistory).where(MatchHistory.match_id == draft.match_id)))["result"]
                    else:
                        result = {"match_id": draft.match_id, "round": None, "table": None, "table_name": "",
                                  "played_at": draft.played_at or draft.created_at, "started_at": None, "ended_at": draft.created_at,
                                  "authoritative_played_at": draft.played_at, "played_at_source": "declared_game_time" if draft.played_at else None,
                                  "duration_seconds": None, "seat_order": "ESWN", "source_seat_order": "ESWN",
                                  "uploader_id": str(user.id), "uploader_name": user.name, "draft_id": draft_id,
                                  "source": "manual", "players": {s: {"user": players[s], **points[s]} for s in SEATS}}
                    draft.status, draft.confirmed_at, draft.result_json = "submitted", now(), dump(result)
                    draft.players_json = dump(players)
                    for seat in SEATS:
                        person = players[seat]
                        account = db.get(Account, person["id"])
                        if account is None:
                            db.add(Account(id=person["id"], name=person["name"]))
                        else:
                            account.name = person["name"]
                    db.flush()
                    for seat in SEATS:
                        db.add(ManualScorePlayer(draft_id=draft_id, seat=seat, user_id=players[seat]["id"],
                                                user_name=players[seat]["name"], final_points=scores[seat]))
                    audit(db, "", user.id, "manual_score_submitted", {"draft_id": draft_id, "request_id": request_id,
                          "match_id": result["match_id"], "table_id": draft.table_id, "players": players, "scores": scores})
                    if not draft.table_id:
                        queue_free_match(db, result)
                    # Bound manual scores and NFC submissions share one game and
                    # one set of delivery tasks, with both source aliases retained.
                    self.matches.history.enqueue_history(db, {
                        "sequence": draft.sequence, "match_id": draft.match_id,
                        "table_id": draft.score_table_id, "round_no": result.get("round"),
                        "scores": scores, "result": result,
                    }, source_kind="manual", source_id=draft.id)
        except IntegrityError:
            # Two different drafts may race for one request ID. Its unique key
            # rolls back the entire losing transaction, including any scores.
            with self.store.connect() as db:
                previous = db.get(ManualScoreRequest, request_id)
                if not previous or previous.draft_id != draft_id or previous.uploader_id != str(user.id):
                    raise Conflict("submission_conflict", "submission_conflict") from None
                check(self._draft(db, draft_id, user).status == "submitted", "submission_conflict")
                replayed = True
        if not replayed:
            schedule_score_notification(result)
        return self._response(draft_id, replayed)

    def flush(self):
        # Compatibility worker entry: history delivery is independent of seat locks.
        self.matches.history.flush(limit=10)

        # The existing background worker calls flush(). Retry only transient
        # manual delivery failures, with bounded exponential backoff; permanent
        # validation/auth failures remain visible for an explicit retry.
        with self.store.connect() as db:
            failed = list(db.execute(select(ExternalDelivery.id, ExternalDelivery.attempts, ExternalDelivery.updated_at)
                .join(ManualScoreDraft, ExternalDelivery.id == "nfc-" + ManualScoreDraft.match_id)
                .where(ManualScoreDraft.status == "submitted", ExternalDelivery.status == "failed",
                       ExternalDelivery.error_code.in_(["network_error", "external_server", "external_rate_limit"]),
                       ExternalDelivery.attempts < 5).limit(10)))
        for key, attempts, updated_at in failed:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=min(300, 15 * 2 ** min(attempts, 4)))
            if updated_at < cutoff.isoformat():
                self.matches.external.send(key, retry=True)

    def _response(self, draft_id, replayed):
        with self.store.connect() as db:
            draft = db.scalar(select(ManualScoreDraft).where(ManualScoreDraft.id == draft_id))
            table, match_id = draft.table_id, draft.match_id
        if table:
            body, status = self.matches._match_response(match_id, replayed)
        else:
            history = self.matches.history.status(match_id)
            external = self.matches.external.get("nfc-" + match_id)
            with self.store.connect() as db:
                draft = db.scalar(select(ManualScoreDraft).where(ManualScoreDraft.id == draft_id))
                pending = history["status"] != "synced"
                body = {"status": "pending" if pending else "success", "local_saved": True, "local_completed": True,
                        "history_sync": history,
                        "sync_status": "pending" if pending else ("synced" if self.matches.sheets.enabled else "disabled"),
                        "replayed": replayed, "result": json.loads(draft.result_json), "external_sync": external}
                status = 202 if pending else 200
        body["draft_id"] = draft_id
        return body, status
