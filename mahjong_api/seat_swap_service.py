"""Consent-based seat swaps: table-locked transactions and durable user claims."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from .database_models import SeatRecord, ScoreDraft, TableState, User as Account
from .models import SEATS
from .table_models import ActiveTableMember, ClubTable
from .seat_swap_models import SeatSwapRequest, SeatSwapClaim
from .seat_swap_state import finish_swap
from .table_membership import check, event, lock_table, membership_lock, table_open
from .external_sync import audit
from .store import Conflict, now


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class SeatSwapService:
    def __init__(self, tables):
        self.tables = tables
        self.store = tables.store
        self.clock = now

    def _stamp(self):
        return instant(self.clock()).isoformat(timespec="milliseconds")

    def _table(self, db, reference, *, for_update=True):
        row = db.get(ClubTable, reference) or db.scalar(select(ClubTable).where(ClubTable.score_table_id == reference))
        check(row is not None, "table_not_found")
        if for_update:
            lock_table(db, row.id)
            db.refresh(row)
        return row

    @staticmethod
    def _score(db, table):
        return db.scalar(select(TableState).where(TableState.table_id == table.score_table_id)) if table.score_table_id else None

    def _invalid_reason(self, db, request, table):
        if table is None or table.status != "open":
            return "table_closed"
        if table.tournament_id:
            return "fixed_tournament_seating"
        score = self._score(db, table)
        if score is None or score.current_match_id != request.match_id:
            return "match_changed"
        if score.started_at or score.pending_match_id:
            return "table_already_started"
        if db.scalar(select(ScoreDraft.id).where(ScoreDraft.match_id == request.match_id,
                ScoreDraft.status.in_(["review", "submitted"]))):
            return "score_exists"
        for role in ("requester", "target"):
            uid = getattr(request, role + "_user_id")
            member = db.get(ActiveTableMember, uid)
            seat = getattr(request, role + "_seat")
            if (member is None or member.table_id != table.id or member.match_id != request.match_id
                    or member.membership_id != getattr(request, role + "_membership_id")
                    or member.seat_version != getattr(request, role + "_seat_version") or member.seat != seat):
                return "membership_changed"
            physical = db.get(SeatRecord, (table.score_table_id, seat))
            if physical is None or physical.user_id != uid:
                return "membership_changed"
        return None

    def _reconcile(self, db, request, table, stamp):
        if request.status != "pending":
            return
        if instant(stamp) >= instant(request.expires_at):
            finish_swap(db, request, "expired", timestamp=stamp)
        else:
            reason = self._invalid_reason(db, request, table)
            if reason:
                finish_swap(db, request, "invalidated", reason=reason, timestamp=stamp)

    def _sweep(self, db, table, stamp):
        for request in db.scalars(select(SeatSwapRequest).where(SeatSwapRequest.table_id == table.id,
                SeatSwapRequest.status == "pending")):
            self._reconcile(db, request, table, stamp)
        db.flush()

    def _view(self, db, request, user, table, *, stamp=None):
        def person(role):
            uid = getattr(request, role + "_user_id")
            account = db.get(Account, uid)
            return {"id":uid, "name":account.name if account else "", "seat":getattr(request, role + "_seat")}
        # Polling projects stale requests without mutating rows or claims. The
        # accepting transaction remains authoritative and repeats these checks.
        status, reason = request.status, request.invalidated_reason
        if stamp is not None and status == "pending":
            if instant(stamp) >= instant(request.expires_at):
                status = "expired"
            else:
                reason = self._invalid_reason(db, request, table)
                if reason:
                    status = "invalidated"
        current = str(user.id)
        return {"id":request.id, "table_id":request.table_id, "score_table_id":table.score_table_id,
            "match_id":request.match_id, "status":status, "requester":person("requester"), "target":person("target"),
            "requested_at":request.requested_at, "expires_at":request.expires_at,
            "responded_at":request.responded_at, "invalidated_reason":reason,
            "can_accept":status == "pending" and current == request.target_user_id,
            "can_decline":status == "pending" and current == request.target_user_id,
            "can_cancel":status == "pending" and current == request.requester_user_id}

    def _response(self, table_id, **payload):
        return self.tables.display_names({**payload, "server_now":self._stamp(),
            "table_state":self.tables.matches.table(table_id) if table_id else None})

    def list(self, table_id, user):
        check(user is not None, "not_authenticated")
        with self.store.connect() as db:
            table = self._table(db, table_id, for_update=False)
            check(not table.tournament_id, "fixed_tournament_seating")
            stamp = self._stamp()
            recent = (instant(stamp) - timedelta(minutes=5)).isoformat(timespec="milliseconds")
            rows = db.scalars(select(SeatSwapRequest).where(SeatSwapRequest.table_id == table.id,
                or_(SeatSwapRequest.requester_user_id == str(user.id), SeatSwapRequest.target_user_id == str(user.id)),
                or_(SeatSwapRequest.status == "pending", SeatSwapRequest.responded_at >= recent))
                .order_by(SeatSwapRequest.requested_at.desc(), SeatSwapRequest.id).limit(20))
            requests = [self._view(db, row, user, table, stamp=stamp) for row in rows]
            score_id = table.score_table_id
        return self._response(score_id, requests=requests)

    def sweep_due(self, limit=50):
        """Expire a bounded batch outside GET requests, one short transaction each.

        Re-read under the same table-writer lock as accept/create so concurrent
        acceptance can never be overwritten and claims are released atomically.
        """
        limit = max(0, min(200, int(limit)))
        if not limit:
            return 0
        stamp = self._stamp()
        with self.store.connect() as db:
            due = list(db.scalars(select(SeatSwapRequest.id).where(
                SeatSwapRequest.status == "pending", SeatSwapRequest.expires_at <= stamp)
                .order_by(SeatSwapRequest.expires_at, SeatSwapRequest.id).limit(limit)))
        expired = 0
        for request_id in due:
            with membership_lock, self.store.connect() as db:
                row = db.get(SeatSwapRequest, request_id)
                if row is None or row.status != "pending":
                    continue
                self._table(db, row.table_id)
                db.refresh(row)
                if row.status == "pending" and instant(stamp) >= instant(row.expires_at):
                    expired += bool(finish_swap(db, row, "expired", timestamp=stamp))
        return expired

    def create(self, table_id, data, user):
        check(user is not None, "not_authenticated")
        target_id = data.get("target_user_id", data.get("targetUserId"))
        check(isinstance(target_id, str) and 1 <= len(target_id) <= 128, "invalid_player_ids")
        check(target_id != str(user.id), "swap_self")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id)
            stamp = self._stamp()
            self._sweep(db, table, stamp)
            table_open(db, table)
            check(not table.tournament_id, "fixed_tournament_seating")
            score = self._score(db, table)
            check(score is not None, "table_not_found")
            check(data.get("match_id") is None or data["match_id"] == score.current_match_id, "stale_match")
            check(not score.started_at, "table_already_started")
            check(not score.pending_match_id, "settlement_pending")
            check(not db.scalar(select(ScoreDraft.id).where(ScoreDraft.match_id == score.current_match_id,
                ScoreDraft.status.in_(["review", "submitted"]))), "score_exists")
            requester = db.get(ActiveTableMember, str(user.id))
            check(requester is None or requester.table_id == table.id, "already_at_other_table")
            check(requester is not None and requester.match_id == score.current_match_id, "must_join_first")
            target = db.get(ActiveTableMember, target_id)
            check(target is not None and target.table_id == table.id and target.match_id == score.current_match_id,
                  "swap_target_not_at_table")
            check(requester.seat in SEATS and target.seat in SEATS and requester.seat != target.seat, "invalid_seat")
            for member in (requester, target):
                physical = db.get(SeatRecord, (score.table_id, member.seat))
                check(physical is not None and physical.user_id == member.user_id, "swap_invalidated")
            old = db.scalar(select(SeatSwapRequest).where(SeatSwapRequest.table_id == table.id,
                SeatSwapRequest.requester_user_id == str(user.id), SeatSwapRequest.target_user_id == target_id,
                SeatSwapRequest.status == "pending"))
            if old:
                row = old
            else:
                claims = list(db.scalars(select(SeatSwapClaim).where(SeatSwapClaim.user_id.in_([str(user.id), target_id]))))
                check(not claims, "swap_pending")
                row = SeatSwapRequest(id=str(uuid4()), table_id=table.id, match_id=score.current_match_id,
                    requester_user_id=str(user.id), target_user_id=target_id,
                    pair_key=hashlib.sha256(json.dumps(sorted([str(user.id), target_id])).encode()).hexdigest(),
                    requester_seat=requester.seat, target_seat=target.seat,
                    requester_membership_id=requester.membership_id, target_membership_id=target.membership_id,
                    requester_seat_version=requester.seat_version, target_seat_version=target.seat_version,
                    status="pending", requested_at=stamp,
                    expires_at=(instant(stamp) + timedelta(seconds=60)).isoformat(timespec="milliseconds"))
                try:
                    with db.begin_nested():
                        db.add(row)
                        db.flush()
                        db.add_all([SeatSwapClaim(user_id=uid, request_id=row.id) for uid in (str(user.id), target_id)])
                        db.flush()
                        audit(db, "", user.id, "seat_swap_requested", {"request_id":row.id,"table_id":table.id,
                            "requester_user_id":str(user.id),"target_user_id":target_id,
                            "requester_seat":requester.seat,"target_seat":target.seat,"requested_at":stamp})
                except IntegrityError:
                    raise Conflict("swap_pending", "swap_pending") from None
            request = self._view(db, row, user, table)
            score_id = table.score_table_id
        return self._response(score_id, request=request)

    def _exchange(self, db, row, table, user, stamp):
        requester = db.get(ActiveTableMember, row.requester_user_id)
        target = db.get(ActiveTableMember, row.target_user_id)
        source_seat = db.get(SeatRecord, (table.score_table_id, row.requester_seat))
        target_seat = db.get(SeatRecord, (table.score_table_id, row.target_seat))
        names = {source_seat.user_id:source_seat.user_name, target_seat.user_id:target_seat.user_name}
        # Both models have immediate unique constraints. Vacating the two wind
        # keys only inside this transaction avoids transient duplicate winds;
        # other connections see the complete pre-swap or post-swap state.
        requester.seat = target.seat = None
        db.execute(delete(SeatRecord).where(SeatRecord.table_id == table.score_table_id,
            SeatRecord.user_id.in_([row.requester_user_id, row.target_user_id])))
        db.flush()
        requester.seat, target.seat = row.target_seat, row.requester_seat
        requester.seat_version += 1
        target.seat_version += 1
        db.add_all([SeatRecord(table_id=table.score_table_id,seat=member.seat,
            user_id=member.user_id,user_name=names[member.user_id]) for member in (requester,target)])
        detail = json.dumps({"request_id":row.id,"requester_user_id":row.requester_user_id,
            "target_user_id":row.target_user_id,"requester_old_seat":row.requester_seat,
            "requester_new_seat":row.target_seat,"target_old_seat":row.target_seat,
            "target_new_seat":row.requester_seat,"requested_at":row.requested_at,"accepted_at":stamp},sort_keys=True)
        for member in (requester,target):
            event(db,table.id,row.match_id,member.user_id,user.id,"seat_swapped","seat_swap",stamp,detail,seat=member.seat)
        score = self._score(db, table)
        score.updated_at, score.dirty = stamp, 0
        db.flush()

    def respond(self, request_id, action, user):
        check(user is not None, "not_authenticated")
        check(action in {"accept","decline","cancel"}, "invalid_action")
        failure = None
        with membership_lock, self.store.connect() as db:
            row = db.get(SeatSwapRequest, request_id)
            check(row is not None, "not_found")
            check(str(user.id) == (row.requester_user_id if action == "cancel" else row.target_user_id),
                  "swap_not_requester" if action == "cancel" else "swap_not_target")
            table = self._table(db, row.table_id)
            db.refresh(row)
            stamp = self._stamp()
            self._reconcile(db, row, table, stamp)
            terminal = {"accept":"accepted", "decline":"declined", "cancel":"cancelled"}[action]
            if row.status == terminal:
                pass  # Replaying an accepted request can never swap seats back.
            elif row.status != "pending":
                failure = "swap_expired" if row.status == "expired" else "swap_invalidated" if row.status == "invalidated" else "swap_not_pending"
            else:
                if action == "accept":
                    self._exchange(db, row, table, user, stamp)
                finish_swap(db, row, terminal, user.id, timestamp=stamp)
            request = self._view(db, row, user, table)
            score_id = table.score_table_id
        # Expiry/invalidations must commit even when the requested accept fails.
        if failure:
            raise Conflict(failure, failure, request=request)
        return self._response(score_id, request=request)
