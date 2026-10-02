import hashlib
from uuid import uuid4
from urllib.parse import urlencode
from fastapi import HTTPException

import json
import logging
import threading

from .config import Settings
from .models import SEAT_NAMES, SubmitScores, User
from .scoring import calculate_match_result
from .sheets import SheetsSink
from .store import Conflict, Store, now, elapsed
from .score_mapping import display_units, map_and_normalize, relative_to_absolute
from .discord_score_notify import schedule_score_notification


logger = logging.getLogger(__name__)


class MatchService:
    def __init__(self, store: Store, sheets: SheetsSink, settings: Settings):
        self.store = store
        from .external_sync import ExternalSync
        self.external = ExternalSync(store)
        self.sheets = sheets
        self.settings = settings
        from .table_membership import membership_lock
        self.lock = membership_lock
        from .history_delivery import HistoryDispatcher
        self.history = HistoryDispatcher(store, sheets)
        store.recover_local_settlements()

    def flush(self):
        """Background-only historical delivery. Never acquire the membership lock."""
        self.history.flush(limit=10)
        remaining = self.store.pending_counts()
        remaining["history_deliveries"] = self.history.pending_counts()["history_deliveries"]
        return remaining

    def sit(self, table_id: str, seat: str, user: User):
        with self.lock:
            self.store.sit(table_id, seat, user)
            table = self.store.table(table_id)
            return {
                "status": "success",
                "message": f"成功就坐 {table_id}号桌 {SEAT_NAMES[seat]}风",
                "user": user.name, "user_id": user.id,
                "match_id": table["current_match_id"],
                "sync_status": "not_required",
            }, 200

    def submit(self, payload: SubmitScores, request_key: str | None):
        with self.lock:
            scores = payload.scores.model_dump()
            points = calculate_match_result(scores, self.settings.initial_points)
            match_id, replayed = self.store.stage_match(payload.table, scores, points, payload.match_id, request_key)
            response = self._match_response(match_id, replayed)
            if not replayed:
                schedule_score_notification(response[0]["result"])
            return response

    def table(self, table_id: str):
        with self.lock:
            table = self.store.table(table_id)
            if table is None:
                return None
            return {
                "table": table_id,
                "display_name": self.table_label(table_id),
                "round": table["round_no"],
                "match_id": table["current_match_id"],
                "seats": {seat: user["id"] if user else None for seat, user in table["seats"].items()},
                "players": table["seats"],
                "settlement_pending": bool(table["pending_match_id"]),
                "updated_at": table["updated_at"],
                "started_at": table["started_at"],
                "server_now": now(),
                "ended_at": self.store.round_end(table["current_match_id"]),
                "elapsed_seconds": elapsed(table["started_at"], self.store.round_end(table["current_match_id"]) or now()),
                "seat_order": "ESWN",
                **self.store.stats(table_id=table_id),
            }

    def table_label(self, table_id):
        from .database_models import Metadata
        from .table_models import ClubTable
        from sqlalchemy import select
        from .tournament_rules import DEFAULT_NAMES
        with self.store.connect() as db:
            registry = db.scalar(select(ClubTable).where(ClubTable.score_table_id == str(table_id)))
            if registry and (registry.display_name or registry.score_table_id==registry.id or str(registry.number)!=str(table_id)):
                return registry.display_name or str(registry.number)
            row = db.get(Metadata, "table_names_v1")
            return (json.loads(row.value) if row else {}).get(str(table_id)) or DEFAULT_NAMES.get(str(table_id), str(table_id))

    def capture_context(self, table_id, user, match_id=None, viewpoint_seat=None):
        table = self.store.table(table_id)
        if table is None:
            raise Conflict("table_not_found", "该桌尚未有人入座")
        if match_id and match_id != table["current_match_id"]:
            from .game_round_models import GameRound
            from sqlalchemy import select
            with self.store.connect() as db:
                prior = db.get(GameRound, match_id)
                if prior is None or prior.score_table_id != table_id or prior.status != "awaiting_score":
                    raise Conflict("stale_match", "对局编号已失效，请刷新桌状态")
                table = {**table, "current_match_id": prior.game_id, "round_no": prior.round_no,
                         "started_at": prior.started_at, "pending_match_id": None,
                         "seats": json.loads(prior.roster_json)}
        # The photo's bottom position belongs to a player, not necessarily its uploader.
        uploader_seat = viewpoint_seat or next((seat for seat, player in table["seats"].items()
                              if player and str(player["id"]) == str(user.id)), None)
        if uploader_seat not in SEAT_NAMES:
            raise HTTPException(422, detail={"code": "photo_viewpoint_required", "message": "请选择照片下方对应的风位"})
        missing = [seat for seat, player in table["seats"].items() if player is None]
        if missing:
            raise Conflict("incomplete_table", "请等待四位玩家入座", missing_seats=missing)
        return table, uploader_seat

    def _match_response(self, match_id, replayed=False):
        match = self.store.match(match_id)
        history = self.history.status(match_id)
        external = self.external.get("nfc-" + match_id)
        pending = history["status"] != "synced"
        return {
            "status": "pending" if pending else "success",
            "message": "本地结算完成，历史成绩正在同步" if pending else
                       ("返回已结算的对局" if replayed else "结算完成，座位已清空"),
            "sync_status": "pending" if pending else ("synced" if self.sheets.enabled else "disabled"),
            "local_saved": True, "local_completed": bool(match["local_finalized"]),
            "history_sync": history, "external_sync": external,
            "replayed": replayed, "result": match["result"],
        }, 202 if pending else 200

    def _review_response(self, draft):
        return {
            "status": "needs_review", "message": "请核对并手动修正分数",
            "draft_id": draft["id"], "table": draft["table_id"], "match_id": draft["match_id"],
            "uploader_id": draft["uploader_id"], "uploader_seat": draft["uploader_seat"],
            "raw_scores": draft["raw"], "scores": draft["normalized"],
            "normalization": display_units(draft["raw"]),
            "position_to_seat": relative_to_absolute(draft["uploader_seat"]),
            "players": draft["roster"], "issues": draft["issues"],
            "total": sum(value for value in draft["normalized"].values() if value is not None),
            "expected_total": 100000,
            "manual_url": "/score?" + urlencode({"table": draft["table_id"], "draft_id": draft["id"]}),
        }

    def _settle_draft(self, draft, user):
        if draft["status"] == "void":
            raise Conflict("stale_match", "stale_match")
        scores = draft["normalized"]
        existing = self.store.match(draft["match_id"])
        if existing:
            if existing["scores"] != scores:
                raise Conflict("submission_conflict", "该对局已经结算，不能用不同分数覆盖")
            body, status = self._match_response(draft["match_id"], True)
            body["normalization"] = display_units(draft["raw"])
            return body, status
        table, seat = self.capture_context(draft["table_id"], user, draft["match_id"], draft["uploader_seat"])
        old_ids = {wind: player["id"] for wind, player in draft["roster"].items()}
        current_ids = {wind: player["id"] for wind, player in table["seats"].items()}
        if old_ids != current_ids or seat != draft["uploader_seat"]:
            raise Conflict("stale_roster", "照片拍摄后的座位发生变化，请重新识别并确认玩家")
        points = calculate_match_result(scores, 25000)
        match_id, replayed = self.store.stage_match(
            draft["table_id"], scores, points, draft["match_id"], draft["request_key"],
            uploader_id=str(user.id), ended_at=draft["ended_at"], draft_id=draft["id"])
        body, status = self._match_response(match_id, replayed)
        body["normalization"] = display_units(draft["raw"])
        if not replayed:
            schedule_score_notification(body["result"])
        return body, status

    def submit_relative(self, payload, user, request_key=None, extra_issues=None, ended_at=None, expected_roster=None, photo_sha256=None):
        with self.lock:
            raw = payload.scores.model_dump()
            identity = [payload.table, str(user.id), raw]
            if payload.viewpoint_seat is not None:
                identity.append(payload.viewpoint_seat.value)
            fingerprint = hashlib.sha256(json.dumps(
                identity, sort_keys=True).encode()).hexdigest()
            previous = self.store.find_draft(payload.table, user.id, payload.match_id, request_key)
            if previous:
                if previous["uploader_id"] != str(user.id) or previous["table_id"] != payload.table:
                    raise Conflict("submission_conflict", "幂等键已经被其他上传任务使用")
                if payload.match_id and previous["match_id"] != payload.match_id:
                    raise Conflict("submission_conflict", "幂等键与对局编号不一致")
                if previous["fingerprint"] == fingerprint:
                    if previous["status"] == "submitted" or not previous["issues"]:
                        return self._settle_draft(previous, user)
                    return self._review_response(previous), 200
                if request_key or previous["status"] == "submitted":
                    raise Conflict("submission_conflict", "同一上传任务已提交不同分数")
            table, seat = self.capture_context(payload.table, user, payload.match_id, payload.viewpoint_seat)
            if expected_roster is not None and table["seats"] != expected_roster:
                raise Conflict("stale_roster", "识别过程中座位发生变化，请重新拍摄")
            if table["pending_match_id"]:
                raise Conflict("settlement_pending", "该桌已提交结算，请等待同步")
            normalized, mapping, issues = map_and_normalize(raw, seat)
            issues.extend(extra_issues or [])
            draft = {
                "id": str(uuid4()), "table_id": payload.table, "match_id": table["current_match_id"],
                "uploader_id": str(user.id), "uploader_seat": seat, "created_at": now(),
                "ended_at": self.store.round_end(table["current_match_id"]) or ended_at or now(),
                "roster": table["seats"], "raw": raw, "normalized": normalized, "issues": issues,
                "fingerprint": fingerprint, "request_key": request_key, "status": "review", "photo_sha256": photo_sha256,
            }
            self.store.save_draft(draft)
            if issues:
                return self._review_response(draft), 200
            return self._settle_draft(draft, user)

    def get_draft(self, draft_id, user):
        draft = self.store.draft(draft_id)
        if draft is None:
            raise HTTPException(404, detail={"code": "draft_not_found"})
        if draft["uploader_id"] != str(user.id):
            raise HTTPException(403, detail={"code": "not_draft_owner"})
        if draft["status"] == "void":
            raise Conflict("stale_match", "stale_match")
        return draft

    def confirm(self, draft_id, scores, user):
        with self.lock:
            draft = self.get_draft(draft_id, user)
            if draft["status"] == "submitted":
                if draft["normalized"] != scores:
                    raise Conflict("submission_conflict", "该对局已经结算，不能覆盖")
                return self._settle_draft(draft, user)
            total = sum(scores.values())
            issues = [] if total == 100000 else [{"code": "invalid_total", "total": total, "expected_total": 100000}]
            self.store.update_draft_scores(draft_id, scores, issues)
            draft["normalized"], draft["issues"] = scores, issues
            if issues:
                return self._review_response(draft), 200
            return self._settle_draft(draft, user)


    def photo_context(self, table, match_id, user, request_key, photo_hash, viewpoint_seat=None):
        """Run local draft checks in a worker thread, never the ASGI loop."""
        with self.lock:
            previous = self.store.find_draft(table, user.id, match_id, request_key)
            if previous and (request_key or previous.get("photo_sha256") == photo_hash):
                if (previous["uploader_id"] != str(user.id) or previous["match_id"] != match_id
                        or previous["table_id"] != table or previous.get("photo_sha256") != photo_hash):
                    raise Conflict("submission_conflict", "相同上传任务的照片或对局已改变")
                if previous["status"] == "submitted" or not previous["issues"]:
                    return None, self._settle_draft(previous, user)
                return None, (self._review_response(previous), 200)
            context, seat = self.capture_context(table, user, match_id, viewpoint_seat)
            return {**context, "photo_viewpoint_seat": seat}, None

