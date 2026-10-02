"""Per-channel history outbox; no member/account locks surround remote I/O.

The caller enqueues in the score transaction. Workers claim with durable tokens,
release the transaction, publish, then acknowledge conditionally. A crash after a
remote write becomes delivery_unknown and must be reconciled by the adapter's
stable match marker before another append is allowed. This is not exactly-once.
"""
import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import aliased

from .database_models import MatchHistory, Metadata
from .history_delivery_models import (
    HistoryTargetLease, ScoreDelivery, ScoreProjectionJob, ScoreRecord,
    ScoreRevision, ScoreRevisionPlayer, ScoreSourceAlias,
)
from .manual_score_models import ManualScoreDraft
from .models import SEATS

logger = logging.getLogger(__name__)
WORK_MODELS = (ScoreProjectionJob, ScoreDelivery)
READY = ("pending", "retrying", "delivery_unknown")


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(dump(value).encode("utf-8")).hexdigest()


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def later(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


class HistoryDeliveryUnknown(RuntimeError):
    """A write may have reached the destination; do not blindly resend."""


class HistoryNeedsReview(ValueError):
    """A duplicate/conflicting marker or payload requires an operator to inspect."""


class HistoryDispatcher:
    def __init__(self, store, sink, *, lease_seconds=120):
        self.store, self.sink = store, sink
        self.lease_seconds = max(3, lease_seconds)
        self._flush_lock = threading.Lock()
        self._next_kind = 0
        store.history_dispatcher = self
        self.import_legacy_pending()

    def _targets(self, match):
        target_factory = getattr(self.sink, "history_targets", None)
        if target_factory:
            return target_factory(match)
        if not self.sink.enabled:
            return []
        # Compatibility for injected/local sinks. Production adapters implement
        # frozen targets and reconciliation explicitly.
        return [{"channel": "history", "target": {"adapter": "compat", "manual": match["result"].get("table") is None}}]

    def _legacy_targets(self, db, match):
        targets = self._targets(match)
        old = db.get(Metadata, "sync_target")
        if old is None:
            return targets
        if old.value == "disabled":
            # Turning Sheets on cannot turn formerly local-only scores into a
            # bulk replay. Their local club projection is still retained.
            return [item for item in targets if item.get("kind") == "projection"]
        try:
            previous_target = json.loads(old.value)
            if not isinstance(previous_target, list) or len(previous_target) != 3 or not all(isinstance(value, str) for value in previous_target):
                raise ValueError("Unknown legacy target format")
            old_book, _old_current, old_history = previous_target
            if not old_book or not old_history:
                raise ValueError("Missing legacy target")
        except (TypeError, ValueError):
            # Unknown legacy target provenance requires review, never a guess.
            if not any(item.get("kind") != "projection" for item in targets):
                targets.append({"channel": "legacy_history", "target": {
                    "adapter": "unresolved_legacy", "metadata_hash": digest(old.value)}})
            for item in targets:
                if item.get("kind") != "projection":
                    item.update(status="failed", error_code="legacy_target_requires_review")
            return targets
        native = getattr(self.sink, "nfc_sink", self.sink)
        settings = getattr(native, "settings", None)
        if settings is None and native.enabled:
            return targets  # Injected local compatibility sinks have no remote config.
        if settings is not None and settings.spreadsheet_id == old_book and settings.history_sheet == old_history and native.enabled:
            return targets
        retained = [item for item in targets if item.get("kind") == "projection"]
        manual = match["result"].get("table") is None
        frozen = [{"channel": "nfc_manual_history" if manual else "nfc_history", "target": {
            "adapter": "gspread_history", "spreadsheet_id": old_book,
            "worksheet": old_history + (" - Manual" if manual else "")}}]
        if retained:
            for channel, title, marker in (("games_riichi", "Games Riichi", 44), ("games_pt", "Games/pt", 28)):
                frozen.append({"channel": channel, "depends_on": "club", "target": {
                    "adapter": "legacy_sheet", "spreadsheet_id": old_book, "worksheet": title, "marker_column": marker}})
        for item in frozen:
            item.update(status="failed", error_code="legacy_target_requires_review")
        return retained + frozen

    def enqueue_history(self, db, match, source_kind="nfc", source_id=None, *, legacy=False):
        """No commit/network: attach to the caller's existing score transaction."""
        game_id = str(match["match_id"])
        source_id = str(source_id or game_id)
        alias = db.get(ScoreSourceAlias, (source_kind, source_id))
        if alias is not None and alias.game_id != game_id:
            raise ValueError("History source alias already belongs to another game")
        record = db.get(ScoreRecord, game_id)
        if record is not None:
            revision = db.get(ScoreRevision, (game_id, 1))
            if revision is None or revision.payload_hash != digest(match["result"]):
                raise ValueError("An initial history snapshot cannot be overwritten")
            if alias is None:
                db.add(ScoreSourceAlias(source_kind=source_kind, source_id=source_id, game_id=game_id))
            return game_id
        created = stamp()
        payload = {key: match[key] for key in ("sequence", "match_id", "result")}
        payload.update(table_id=match["result"].get("table"), round_no=match["result"].get("round"),
                       scores={wind: match["result"]["players"][wind]["final_points"] for wind in SEATS})
        targets = self._legacy_targets(db, payload) if legacy else self._targets(payload)
        db.add(ScoreRecord(game_id=game_id, created_at=created))
        db.flush()
        db.add(ScoreRevision(game_id=game_id, revision=1, snapshot_json=dump(payload),
            payload_hash=digest(match["result"]), actor_id=str(match["result"].get("uploader_id") or "") or None,
            created_at=created))
        db.add(ScoreSourceAlias(source_kind=source_kind, source_id=source_id, game_id=game_id))
        db.flush()
        for wind in SEATS:
            player = match["result"]["players"][wind]
            db.add(ScoreRevisionPlayer(game_id=game_id, revision=1, wind=wind,
                player_ref=str(player["user"]["id"]), display_name=player["user"]["name"],
                initial_points=player["initial_points"], final_points=player["final_points"]))
        for spec in targets:
            target = spec["target"]
            target_version = digest(target)
            # Adapter+destination identify the shared external target even when
            # the per-game delivery uses a distinct channel or payload.
            target_key = digest(spec.get("serial_target", target))
            if db.get(HistoryTargetLease, target_key) is None:
                db.add(HistoryTargetLease(target_key=target_key))
                db.flush()
            model = ScoreProjectionJob if spec.get("kind") == "projection" else ScoreDelivery
            db.add(model(id=str(uuid4()), game_id=game_id, revision=1, channel=spec["channel"],
                target_version=target_version, target_key=target_key, target_json=dump(target),
                payload_json=dump(payload), payload_hash=digest(payload), depends_on=spec.get("depends_on"),
                status=spec.get("status", "pending"), error_code=spec.get("error_code"), source_priority=0 if legacy else 1,
                next_attempt_at=created, created_at=created, updated_at=created))
        if not targets:
            self._mark_legacy_synced(db, game_id)
        return game_id

    def import_legacy_pending(self, limit=100):
        """Bounded, restartable import of unsent work only; no replay on renames.

        Existing successful rows stay untouched. Previously partial multi-sheet
        deliveries are reconciled by their original match IDs at each target.
        """
        imported = 0
        with self.store.connect() as db:
            missing = ~exists(select(ScoreSourceAlias.game_id).where(
                ScoreSourceAlias.source_kind == "nfc", ScoreSourceAlias.source_id == MatchHistory.match_id))
            rows = list(db.scalars(select(MatchHistory).where(MatchHistory.history_synced == 0, missing)
                                  .order_by(MatchHistory.sequence).limit(limit)))
            for row in rows:
                self.enqueue_history(db, {"sequence": row.sequence, "match_id": row.match_id,
                    "result": json.loads(row.result_json)}, "nfc", row.match_id, legacy=True)
                imported += 1
            if imported < limit:
                missing_manual = ~exists(select(ScoreSourceAlias.game_id).where(
                    ScoreSourceAlias.source_kind == "manual", ScoreSourceAlias.source_id == ManualScoreDraft.id))
                drafts = list(db.scalars(select(ManualScoreDraft).where(ManualScoreDraft.status == "submitted",
                    ManualScoreDraft.table_id.is_(None), ManualScoreDraft.history_synced == 0, missing_manual)
                    .order_by(ManualScoreDraft.sequence).limit(limit - imported)))
                for draft in drafts:
                    self.enqueue_history(db, {"sequence": draft.sequence, "match_id": draft.match_id,
                        "result": json.loads(draft.result_json)}, "manual", draft.id, legacy=True)
                    imported += 1
        return imported

    @staticmethod
    def _mark_legacy_synced(db, game_id):
        # History completion does not clear seats or advance a table. Settlement
        # already happened atomically with the score and outbox in the request.
        db.execute(update(MatchHistory).where(MatchHistory.match_id == game_id).values(history_synced=1))
        db.execute(update(ManualScoreDraft).where(ManualScoreDraft.match_id == game_id,
            ManualScoreDraft.status == "submitted").values(history_synced=1))

    def _claim(self):
        now = stamp()
        with self.store.connect() as db:
            # A channel may occur only in a later import batch (e.g. manual
            # history after NFC history). Do not let a new job get ahead of old
            # obligations whose targets have not been discovered yet.
            unimported_nfc = exists(select(MatchHistory.match_id).where(MatchHistory.history_synced == 0,
                ~exists(select(ScoreSourceAlias.game_id).where(ScoreSourceAlias.source_kind == "nfc",
                    ScoreSourceAlias.source_id == MatchHistory.match_id))))
            unimported_manual = exists(select(ManualScoreDraft.id).where(ManualScoreDraft.status == "submitted",
                ManualScoreDraft.table_id.is_(None), ManualScoreDraft.history_synced == 0,
                ~exists(select(ScoreSourceAlias.game_id).where(ScoreSourceAlias.source_kind == "manual",
                    ScoreSourceAlias.source_id == ManualScoreDraft.id))))
            legacy_waiting = bool(db.scalar(select(or_(unimported_nfc, unimported_manual))))
            for model in (WORK_MODELS[self._next_kind], WORK_MODELS[1 - self._next_kind]):
                # Expired attempts are ambiguous, never just put back as pending.
                db.execute(update(model).where(model.status == "processing", model.lease_until < now)
                    .values(status="delivery_unknown", error_code="worker_lease_expired", lease_token=None,
                            lease_until=None, next_attempt_at=now, updated_at=now))
                older = aliased(model)
                earlier_unfinished = exists(select(older.id).where(older.target_key == model.target_key,
                    older.status != "succeeded", or_(older.source_priority < model.source_priority,
                        (older.source_priority == model.source_priority) & (older.created_at < model.created_at))))
                # Club MMR/PT and the two legacy worksheets rely on source order.
                # A failed earlier row blocks later rows only at that target;
                # independent targets can still advance. Legacy pending work has
                # priority over new confirmations even when its bounded import
                # happens later, so new games cannot overtake the old backlog.
                # Filter before LIMIT so
                # a large blocked target cannot starve a healthy target's queue.
                candidates = list(db.scalars(select(model).where(model.status.in_(READY), model.next_attempt_at <= now,
                    ~earlier_unfinished, or_(not legacy_waiting, model.source_priority == 0))
                    .order_by(model.source_priority, model.created_at, model.id).limit(50)))
                for row in candidates:
                    payload = json.loads(row.payload_json)
                    if row.depends_on:
                        dependency = db.scalar(select(ScoreProjectionJob).where(ScoreProjectionJob.game_id == row.game_id,
                            ScoreProjectionJob.revision == row.revision, ScoreProjectionJob.channel == row.depends_on))
                        if dependency is None or dependency.status != "succeeded":
                            continue
                        if "projection" not in payload:
                            payload["projection"] = json.loads(dependency.result_json or "{}")
                    target = json.loads(row.target_json)
                    if target.get("requires_channel"):
                        prerequisite = db.scalar(select(ScoreDelivery.status).where(
                            ScoreDelivery.game_id == row.game_id, ScoreDelivery.revision == row.revision,
                            ScoreDelivery.channel == target["requires_channel"]))
                        if prerequisite != "succeeded":
                            continue
                    token, until = str(uuid4()), later(self.lease_seconds)
                    fenced = db.execute(update(HistoryTargetLease).where(HistoryTargetLease.target_key == row.target_key,
                        or_(HistoryTargetLease.lease_until.is_(None), HistoryTargetLease.lease_until < now))
                        .values(lease_token=token, lease_until=until)).rowcount
                    if not fenced:
                        continue
                    previous_status = row.status
                    changed = db.execute(update(model).where(model.id == row.id, model.status == previous_status)
                        .values(status="processing", lease_token=token, lease_until=until, attempts=model.attempts + 1,
                                payload_json=dump(payload), payload_hash=digest(payload), updated_at=now)).rowcount
                    if not changed:
                        db.execute(update(HistoryTargetLease).where(HistoryTargetLease.target_key == row.target_key,
                            HistoryTargetLease.lease_token == token).values(lease_token=None, lease_until=None))
                        continue
                    self._next_kind = 1 if model is ScoreProjectionJob else 0
                    return {"model": model, "id": row.id, "game_id": row.game_id, "revision": row.revision,
                        "channel": row.channel, "target_key": row.target_key, "token": token,
                        "target": json.loads(row.target_json), "payload": payload, "attempts": row.attempts,
                        "reconcile": previous_status == "delivery_unknown"}
        return None

    def _renew(self, claim, stop):
        while not stop.wait(self.lease_seconds / 3):
            try:
                with self.store.connect() as db:
                    until = later(self.lease_seconds)
                    updated = db.execute(update(claim["model"]).where(claim["model"].id == claim["id"],
                        claim["model"].status == "processing", claim["model"].lease_token == claim["token"])
                        .values(lease_until=until)).rowcount
                    if not updated:
                        return
                    db.execute(update(HistoryTargetLease).where(HistoryTargetLease.target_key == claim["target_key"],
                        HistoryTargetLease.lease_token == claim["token"]).values(lease_until=until))
            except Exception:
                logger.warning("History lease renewal failed for channel %s", claim["channel"])
                return

    def _send(self, claim):
        adapter = claim["target"].get("adapter")
        if adapter == "compat":
            if claim["reconcile"]:
                probe = getattr(self.sink, "reconcile_manual_history" if claim["target"].get("manual") else "reconcile_history", None)
                outcome = probe(claim["payload"]) if probe else None
                if outcome == "matched":
                    return {"match_id": claim["game_id"], "revision": claim["revision"]}
                if outcome != "absent":
                    raise HistoryDeliveryUnknown("Compatibility sink cannot reconcile")
            writer = getattr(self.sink, "write_manual_history", None) if claim["target"].get("manual") else self.sink.write_history
            if writer is None:
                raise HistoryNeedsReview("History sink does not support manual scores")
            writer(claim["payload"])
            return {"match_id": claim["game_id"], "revision": claim["revision"]}
        writer = getattr(self.sink, "deliver_history", None)
        if writer is None:
            raise HistoryNeedsReview("History sink does not implement frozen target delivery")
        # Each real adapter locates and verifies the stable marker even on the
        # first attempt. This also reconciles legacy partial success and lost ACKs.
        return writer(claim["target"], claim["payload"], reconcile=claim["reconcile"])

    def _ack(self, claim, result=None, error=None):
        state, code = "succeeded", None
        delay = min(300, 5 * 2 ** min(claim["attempts"], 5))
        if error is not None:
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code == 429:
                state, code = "retrying", "history_rate_limited"
                retry_after = getattr(response, "headers", {}).get("Retry-After", "")
                try:
                    delay = max(delay, min(86400, float(retry_after)))
                except (ValueError, TypeError):
                    try:
                        from email.utils import parsedate_to_datetime
                        delay = max(delay, min(86400, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()))
                    except (ValueError, TypeError, OverflowError):
                        pass
            elif status_code is not None and 400 <= status_code < 500 and status_code != 408:
                state, code = "failed", "history_remote_rejected"
            elif status_code is not None and status_code >= 500:
                state, code = "delivery_unknown", "history_acknowledgement_unknown"
            elif isinstance(error, HistoryNeedsReview) or isinstance(error, ValueError):
                state, code = "failed", "history_target_requires_review"
            elif isinstance(error, (HistoryDeliveryUnknown, TimeoutError, ConnectionError)):
                state, code = "delivery_unknown", "history_acknowledgement_unknown"
            else:
                try:
                    import requests
                    ambiguous = isinstance(error, requests.exceptions.RequestException)
                except ImportError:
                    ambiguous = False
                state, code = ("delivery_unknown", "history_acknowledgement_unknown") if ambiguous else ("retrying", "history_target_unavailable")
        with self.store.connect() as db:
            model = claim["model"]
            changed = db.execute(update(model).where(model.id == claim["id"], model.status == "processing",
                model.lease_token == claim["token"]).values(status=state, error_code=code,
                ack_revision=claim["revision"] if state == "succeeded" else None,
                result_json=dump(result or {}) if state == "succeeded" else None,
                lease_token=None, lease_until=None, next_attempt_at=later(delay),
                updated_at=stamp())).rowcount
            db.execute(update(HistoryTargetLease).where(HistoryTargetLease.target_key == claim["target_key"],
                HistoryTargetLease.lease_token == claim["token"]).values(lease_token=None, lease_until=None))
            if changed and state == "succeeded":
                remaining = sum(db.scalar(select(func.count()).select_from(kind).where(kind.game_id == claim["game_id"],
                    kind.revision == claim["revision"], kind.status != "succeeded")) for kind in WORK_MODELS)
                if not remaining:
                    self._mark_legacy_synced(db, claim["game_id"])
        return state

    def _complete_local_projections(self, limit=10):
        """Repairable local compatibility flag after every remote channel ACK.

        The successful projection row is itself the durable completion task. If
        this process dies after the club update, repeating the same flag is safe.
        Neither database transaction remains open while the other is written.
        """
        finish = getattr(self.sink, "complete_history", None)
        if finish is None:
            return
        with self.store.connect() as db:
            incomplete_delivery = exists(select(ScoreDelivery.id).where(ScoreDelivery.game_id == ScoreProjectionJob.game_id,
                ScoreDelivery.revision == ScoreProjectionJob.revision, ScoreDelivery.status != "succeeded"))
            rows = list(db.scalars(select(ScoreProjectionJob).where(ScoreProjectionJob.channel == "club",
                ScoreProjectionJob.status == "succeeded", ScoreProjectionJob.completion_synced == 0,
                ~incomplete_delivery).order_by(ScoreProjectionJob.created_at).limit(limit)))
            work = [(row.id, json.loads(row.result_json or "{}"), bool(db.scalar(select(func.count()).select_from(ScoreDelivery)
                .where(ScoreDelivery.game_id == row.game_id, ScoreDelivery.revision == row.revision)))) for row in rows]
        for job_id, projection, had_external_targets in work:
            try:
                finish(projection, had_external_targets=had_external_targets)
                with self.store.connect() as db:
                    db.execute(update(ScoreProjectionJob).where(ScoreProjectionJob.id == job_id,
                        ScoreProjectionJob.status == "succeeded").values(completion_synced=1))
            except Exception as exc:
                logger.warning("History compatibility completion pending: error_type=%s", type(exc).__name__)

    def flush(self, limit=10):
        """Bounded worker batch. Safe for overlapping callers and process restart."""
        if not self._flush_lock.acquire(blocking=False):
            return self.pending_counts()
        try:
            self.import_legacy_pending()
            for _ in range(max(0, min(int(limit), 100))):
                claim = self._claim()
                if claim is None:
                    break
                stop = threading.Event()
                heartbeat = threading.Thread(target=self._renew, args=(claim, stop), daemon=True)
                heartbeat.start()
                result, error = None, None
                try:
                    import request_performance as perf
                    metric, token = perf.start("WORKER", "/internal/history-delivery")
                    try:
                        if claim["channel"] == "club":
                            result = self._send(claim)
                        else:
                            field = {"games_riichi": "sheetsClubHistoryDurationMs", "games_pt": "sheetsPlayersDurationMs"}.get(
                                claim["channel"], "sheetsHistoryDurationMs")
                            with perf.measure("sheetsDurationMs", "sheetsCallCount"), perf.measure(field):
                                result = self._send(claim)
                        metric["status"] = 200
                    finally:
                        perf.finish(metric, token)
                except Exception as exc:
                    error = exc
                    # Exception strings can contain private upstream URLs/keys.
                    logger.warning("History delivery pending: channel=%s error_type=%s", claim["channel"], type(exc).__name__)
                finally:
                    stop.set()
                    heartbeat.join(timeout=1)
                self._ack(claim, result, error)
            self._complete_local_projections()
            return self.pending_counts()
        finally:
            self._flush_lock.release()

    def status(self, game_id):
        with self.store.connect() as db:
            record = db.get(ScoreRecord, str(game_id))
            channels = []
            for model in WORK_MODELS:
                for row in db.scalars(select(model).where(model.game_id == str(game_id)).order_by(model.channel)):
                    channels.append({"channel": row.channel, "status": row.status, "attempts": row.attempts,
                        "revision": row.revision, "ack_revision": row.ack_revision, "error_code": row.error_code})
            statuses = {row["status"] for row in channels}
            legacy_synced = False
            if record is None:
                old_match = db.scalar(select(MatchHistory.history_synced).where(MatchHistory.match_id == str(game_id)))
                old_manual = db.scalar(select(ManualScoreDraft.history_synced).where(
                    ManualScoreDraft.match_id == str(game_id), ManualScoreDraft.status == "submitted"))
                legacy_synced = bool(old_match or old_manual)
            overall = "synced" if legacy_synced or (record and not (statuses - {"succeeded"})) else "pending"
            if "failed" in statuses:
                overall = "failed"
            elif "delivery_unknown" in statuses:
                overall = "delivery_unknown"
            return {"status": overall, "revision": record.current_revision if record else None, "channels": channels, "legacy": record is None and legacy_synced}

    def pending_counts(self):
        with self.store.connect() as db:
            counts = {}
            for model in WORK_MODELS:
                for state, count in db.execute(select(model.status, func.count()).group_by(model.status)):
                    counts[state] = counts.get(state, 0) + count
            return {"history_deliveries": sum(value for key, value in counts.items() if key != "succeeded"),
                    "history_statuses": counts}

    def retry(self, game_id):
        """Schedule a retry; never perform remote work in an HTTP request."""
        with self.store.connect() as db:
            for model in WORK_MODELS:
                db.execute(update(model).where(model.game_id == str(game_id),
                    model.status.in_(("retrying", "delivery_unknown")),
                    or_(model.error_code.is_(None), model.error_code != "history_rate_limited"))
                    .values(next_attempt_at=stamp()))
                db.execute(update(model).where(model.game_id == str(game_id), model.status == "failed",
                    model.error_code == "history_remote_rejected").values(status="retrying", next_attempt_at=stamp()))
                # Marker/configuration conflicts require review; an explicit
                # retry may recheck a remote rejection after credentials change,
                # but must not bypass an upstream Retry-After deadline.
        return self.status(game_id)
