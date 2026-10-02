"""Table registry and opaque QR/NFC entry service; reuses the score Store and lock."""
import base64
from contextlib import nullcontext
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid4
from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import IntegrityError
from .database_models import TableState, SeatRecord, User as Account, ScoreDraft, MatchHistory
from .table_models import ClubTable, TableJoinToken, ActiveTableMember, TableReservation, TableCommand, ReservationParticipant
from .tournament_models import Tournament, TournamentTableSession
from .table_membership import (membership_lock, check, admin, table_open, ordinary_join,
    ordinary_leave, release_table, register_ordinary, lock_table, assigned_tournament_seat, ordinary_set_my_seat)
from .external_sync import audit, dump
from .models import User, SEATS
from .store import Conflict, now


def utc_value(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        check(dt.tzinfo is not None and dt.utcoffset() is not None, "timezone_required")
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except (ValueError, TypeError, OverflowError):
        raise Conflict("invalid_reservation_time", "invalid_reservation_time") from None


class TableService:
    def __init__(self, matches, tournaments, account_lookup=None):
        self.matches, self.tournaments, self.store = matches, tournaments, matches.store
        self.account_lookup = account_lookup
        self.tournaments.account_lookup = self.lookup_accounts
        self.tournaments.account_rows = self._account_rows
        self.tournaments.account_guard = self.account_guard
        self.timezone = os.getenv("SITE_TIMEZONE", "America/Los_Angeles")
        self.clock = now
        self._secret = None

    def account_guard(self):
        """Account directory always precedes membership and score database locks."""
        if self.account_lookup is not None:
            return nullcontext()
        from registered_names import account_lock
        path = Path(os.getenv("TABLE_ACCOUNT_FILE", str(Path(__file__).resolve().parents[1] / "web_users.json")))
        return account_lock(path)

    def _signing_secret(self):
        if self._secret is not None:
            return self._secret
        path = Path(os.getenv("TABLE_TOKEN_SECRET_FILE", str(self.store.path.parent / "table_token_secret")))
        path.parent.mkdir(parents=True, exist_ok=True)
        with membership_lock:
            if not path.exists():
                with self.store.connect() as db:
                    check(not db.scalar(select(func.count()).select_from(TableJoinToken)), "token_secret_missing")
                descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "wb") as out:
                    out.write(secrets.token_bytes(32)); out.flush(); os.fsync(out.fileno())
            secret = path.read_bytes()
            check(len(secret) == 32, "token_secret_missing")
            self._secret = secret
            return secret

    def _token_text(self, token_id):
        signature = hmac.new(self._signing_secret(), token_id.encode(), hashlib.sha256).digest()
        return token_id + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")

    @staticmethod
    def _command(db, user, action, data):
        key = data.get("request_id")
        check(isinstance(key, str) and 1 <= len(key) <= 128, "request_id_required")
        fingerprint = hashlib.sha256(dump([str(user.id), action, data]).encode()).hexdigest()
        old = db.get(TableCommand, key)
        if old:
            check(hmac.compare_digest(old.fingerprint, fingerprint), "submission_conflict")
        return key, fingerprint, old

    @staticmethod
    def _remember(db, key, fingerprint, result_id):
        db.add(TableCommand(id=key, fingerprint=fingerprint, result_id=result_id, created_at=now()))

    def _table(self, db, table_id):
        return table_open(db, db.get(ClubTable, table_id))

    def resolve_score_id(self, table_id):
        with self.store.connect() as db:
            table = db.get(ClubTable, table_id) or db.scalar(select(ClubTable).where(ClubTable.score_table_id == table_id))
            self._table(db, table.id if table else "")
            check(not table.tournament_id, "fixed_tournament_seating")
            return table.score_table_id

    def _prime_views(self, db, rows, include_admin=False):
        """Batch read projections scoped to the returned tables, never per person."""
        from .reservation_session_models import ReservationSession
        from sqlalchemy.orm import aliased
        ids=[row.id for row in rows]
        cache={"tables":{row.id:row for row in rows},"members":{},"names":{},"reservations":{},
               "sessions":{},"session_rows":{},"participants":{},"tokens":{},"scores":{}}
        if not ids:
            db.info["table_views"]=cache;return
        members=list(db.scalars(select(ActiveTableMember).where(ActiveTableMember.table_id.in_(ids))))
        for member in members:cache["members"].setdefault(member.table_id,[]).append(member)
        user_ids={member.user_id for member in members}
        if user_ids:cache["names"]={row.id:row.name for row in db.scalars(select(Account).where(Account.id.in_(user_ids)))}
        ranked=select(TableReservation,func.row_number().over(partition_by=TableReservation.table_id,
            order_by=(TableReservation.scheduled_at.desc(),TableReservation.id)).label("rn")).where(
                TableReservation.table_id.in_(ids),TableReservation.status=="active").subquery()
        reservation=aliased(TableReservation,ranked)
        records=list(db.scalars(select(reservation).where(ranked.c.rn<=100).order_by(reservation.scheduled_at.desc())))
        for row in records:cache["reservations"].setdefault(row.table_id,[]).append(row)
        if include_admin:
            cache["reservation_history"]={}
            history=list(db.scalars(select(TableReservation).where(
                TableReservation.table_id.in_(ids),TableReservation.status!="active")
                .order_by(TableReservation.updated_at.desc(),TableReservation.id.desc()).limit(100)))
            records.extend(history)
            for row in history:cache["reservation_history"].setdefault(row.table_id,[]).append(row)
        active=list(db.scalars(select(ReservationSession).where(ReservationSession.table_id.in_(ids),
            ReservationSession.status=="active").order_by(ReservationSession.start_at,ReservationSession.id)))
        for row in active:cache["sessions"].setdefault(row.table_id,[]).append(row)
        session_ids={row.session_id for row in records if row.session_id}|{row.id for row in active}
        all_sessions={row.id:row for row in active}
        if session_ids:
            all_sessions.update({row.id:row for row in db.scalars(select(ReservationSession).where(ReservationSession.id.in_(session_ids)))})
            for row in db.scalars(select(TableReservation).where(TableReservation.session_id.in_(session_ids),
                    TableReservation.status=="active").order_by(TableReservation.scheduled_at,TableReservation.id)):
                cache["session_rows"].setdefault(row.session_id,[]).append(row);records.append(row)
        cache["all_sessions"]=all_sessions
        reservation_ids={row.id for row in records}
        if reservation_ids:
            for person in db.scalars(select(ReservationParticipant).where(ReservationParticipant.reservation_id.in_(reservation_ids))
                    .order_by(ReservationParticipant.added_at,ReservationParticipant.user_id)):
                cache["participants"].setdefault(person.reservation_id,[]).append(person)
        from .reservation_queue import participant_progress
        cache["progress"]=participant_progress(db,records)
        if include_admin:
            for row in db.scalars(select(TableJoinToken).where(TableJoinToken.table_id.in_(ids)).order_by(TableJoinToken.created_at.desc())):
                cache["tokens"].setdefault(row.table_id,[]).append(row)
        cache["scores"]={row.table_id:row for row in db.scalars(select(TableState).where(TableState.table_id.in_([r.score_table_id for r in rows if r.score_table_id])))}
        db.info["table_views"]=cache

    def _view(self, db, row, include_admin=False):
        if "table_views" not in db.info:
            self._prime_views(db,[row],include_admin)
        cache=db.info["table_views"]
        people=cache["members"].get(row.id,[])
        names=cache["names"]
        reserved=cache["reservations"].get(row.id,[])
        tokens=cache["tokens"].get(row.id,[])
        value = {k: getattr(row, k) for k in ("id", "number", "display_name", "scope", "tournament_id",
            "score_table_id", "status", "capacity", "nfc_configured", "nfc_label")}
        value["members"] = [{"user_id": p.user_id, "name": names.get(p.user_id, "Unavailable player"),
            "join_method": p.join_method, "added_by_user_id": p.added_by_user_id,
            "joined_at": p.joined_at, "seat": p.seat, "status": p.status, "left_at": p.left_at} for p in people]
        value["player_count"] = sum(p.status == "active" and not p.left_at for p in people)
        value["reservations"] = [self._reservation(db, r) for r in reserved]
        from .reservation_session_models import ReservationSession
        value["reservation_sessions"] = [view for session in cache["sessions"].get(row.id,[])
            if (view:=self._reservation_session(db,session)) and view["participant_count"]>0]
        value["timezone"] = self.timezone
        if include_admin:
            value["reservation_history"]=[self._reservation(db,r) for r in
                cache.get("reservation_history",{}).get(row.id,[])]
            value["tokens"] = [self._token_view(r, row) for r in tokens]
        score = cache["scores"].get(row.score_table_id)
        value["started_at"] = score.started_at if score else None
        value["current_match_id"] = score.current_match_id if score else None
        value["can_leave"] = bool(score and not score.started_at and not score.pending_match_id)
        value["can_join"] = bool(row.status == "open" and score and not score.started_at
                                 and not score.pending_match_id and value["player_count"] < row.capacity)
        return value

    def resolve_scoring_table(self, user, requested_table=None, entry_token=None, current_table=None,
                              auto_select_full=False):
        from .scoring_table import resolve_scoring_table
        # Token identity is revalidated on every request, including after login.
        if entry_token is not None:
            info = self.token_info(entry_token)
            check(requested_table is None or requested_table in (info["table_id"], info["score_table_id"]),
                  "invalid_join_token")
            requested_table = info["table_id"]
            auto_select_full = False
        with self.store.connect() as db:
            # Selection needs only registry, occupancy and current game state.
            # Never expand reservation history, tokens or account profiles here.
            rows = list(db.scalars(select(ClubTable).where(ClubTable.tournament_id.is_(None))))
            ids = [row.id for row in rows]
            members = {}
            if ids:
                for member in db.scalars(select(ActiveTableMember).where(ActiveTableMember.table_id.in_(ids),
                        ActiveTableMember.status == "active", ActiveTableMember.left_at.is_(None))):
                    members.setdefault(member.table_id, []).append({"user_id":member.user_id,
                        "status":member.status,"left_at":member.left_at,"seat":member.seat})
            scores = {row.table_id:row for row in db.scalars(select(TableState).where(
                TableState.table_id.in_([row.score_table_id for row in rows if row.score_table_id])))} if rows else {}
            candidates = []
            for row in rows:
                score = scores.get(row.score_table_id)
                people = members.get(row.id, [])
                value = {key:getattr(row,key) for key in ("id","number","display_name","score_table_id","status","capacity")}
                value.update(members=people,player_count=len(people),started_at=score.started_at if score else None,
                    can_join=bool(row.status == "open" and score and not score.started_at and
                                  not score.pending_match_id and len(people) < row.capacity))
                candidates.append(value)
            return resolve_scoring_table(candidates, user.id,
                requested_table=requested_table, current_table=current_table, auto_select_full=auto_select_full)

    def list(self, user, include_admin=False):
        if include_admin:
            admin(user)
        with self.store.connect() as db:
            rows = list(db.scalars(select(ClubTable).order_by(ClubTable.scope, ClubTable.number)))
            self._prime_views(db,rows,include_admin)
            output = []
            for row in rows:
                if row.tournament_id and db.get(Tournament, row.tournament_id).deleted_at:
                    continue
                if not include_admin and (row.status != "open" or row.tournament_id):
                    continue
                output.append(self._view(db, row, include_admin))
            return {"tables": output, "timezone": self.timezone}

    def get(self, table_id, user, include_admin=False):
        if include_admin:
            admin(user)
        with self.store.connect() as db:
            row = db.get(ClubTable, table_id)
            check(row is not None, "table_not_found")
            if row.tournament_id:
                check(not db.get(Tournament, row.tournament_id).deleted_at, "tournament_deleted")
            return self._view(db, row, include_admin)

    def create(self, data, user):
        admin(user)
        number = data.get("number")
        check(type(number) is int and 0 < number <= 1000000000, "invalid_table_number")
        tid = data.get("tournament_id") or None
        with membership_lock, self.store.connect() as db:
            key, fingerprint, old = self._command(db, user, "table_create", data)
            if old:
                return self._view(db, db.get(ClubTable, old.result_id), True)
            if tid:
                competition = db.get(Tournament, tid)
                check(competition is not None and not competition.deleted_at, "tournament_deleted")
                capacity = json.loads(competition.state_json)["settings"]["table_size"]
            else:
                capacity = 4  # The existing photo recognizer and seat model are four-player.
            scope = "tournament:" + tid if tid else "venue:club"
            check(not db.scalar(select(ClubTable.id).where(ClubTable.scope == scope, ClubTable.number == number)), "duplicate_table_number")
            table_id = str(uuid4())
            row = ClubTable(id=table_id, scope=scope, tournament_id=tid, score_table_id=None if tid else table_id,
                number=number, display_name=str(data.get("display_name", "")).strip()[:120],
                status="open", capacity=capacity, created_at=self.clock(), created_by=str(user.id))
            db.add(row)
            if not tid:
                db.add(TableState(table_id=table_id, current_match_id=str(uuid4()), updated_at=self.clock()))
            db.flush()
            self._remember(db, key, fingerprint, table_id)
            audit(db, tid or "", user.id, "table_created", {"table_id": table_id, "number": number})
            return self._view(db, row, True)

    def update(self, table_id, data, user):
        admin(user)
        with membership_lock, self.store.connect() as db:
            row = db.get(ClubTable, table_id)
            check(row is not None, "table_not_found")
            if row.tournament_id:
                check(not db.get(Tournament, row.tournament_id).deleted_at, "tournament_deleted")
            from .reservation_sessions import lock_scope
            lock_scope(db, row.scope)
            lock_table(db, row.id)
            db.refresh(row)
            before = {k: getattr(row, k) for k in ("number", "display_name", "status", "nfc_configured", "nfc_label")}
            if "number" in data:
                number = data["number"]
                check(type(number) is int and 0 < number <= 1000000000, "invalid_table_number")
                check(not db.scalar(select(ClubTable.id).where(ClubTable.scope == row.scope, ClubTable.number == number, ClubTable.id != row.id)), "duplicate_table_number")
                row.number = number
            if "status" in data:
                check(data["status"] in {"open", "closed"}, "invalid_state")
                if data["status"] == "closed":
                    check(not db.scalar(select(ActiveTableMember.user_id).where(ActiveTableMember.table_id == row.id)), "table_has_members")
                if row.status != data["status"]:
                    from .seat_swap_state import invalidate_swaps
                    invalidate_swaps(db, row.id, reason="table_closed", actor=user.id, timestamp=self.clock())
                row.status = data["status"]
            for field in ("display_name", "nfc_label"):
                if field in data:
                    check(isinstance(data[field], str) and len(data[field]) <= 120, "invalid_name")
                    setattr(row, field, data[field].strip())
            if "nfc_configured" in data:
                check(type(data["nfc_configured"]) is bool, "invalid_config")
                row.nfc_configured = int(data["nfc_configured"])
            audit(db, row.tournament_id or "", user.id, "table_updated", {"table_id": row.id, "before": before,
                "after": {k: getattr(row, k) for k in before}})
            return self._view(db, row, True)

    def _token_view(self, token, table):
        valid = not token.revoked_at and (not token.expires_at or token.expires_at > self.clock()) and table.status == "open"
        result = {k: getattr(token, k) for k in ("id", "channel", "purpose", "seat", "created_at", "expires_at", "revoked_at", "last_used_at", "use_count")}
        result["valid"] = bool(valid)
        result["status"] = "revoked" if token.revoked_at else "active" if valid else "expired" if token.expires_at and token.expires_at <= self.clock() else "inactive"
        if valid:
            raw = self._token_text(token.id)
            check(hmac.compare_digest(hashlib.sha256(raw.encode()).hexdigest(), token.token_hash), "token_secret_missing")
            result["path"] = "/join-table/" + raw
        return result

    def issue_token(self, table_id, data, user):
        admin(user)
        channel = data.get("channel", "qr")
        purpose = data.get("purpose", "table_landing" if channel == "qr" else "table_join")
        seat = data.get("seat")
        check(purpose in {"table_landing", "seat_join", "table_join"}, "invalid_token_purpose")
        check(purpose != "table_join" or channel != "qr", "invalid_token_purpose")
        check(seat in SEATS if purpose == "seat_join" else seat is None, "invalid_seat")
        check(channel in {"qr", "nfc", "universal"}, "invalid_join_method")
        expiry = utc_value(data["expires_at"]) if data.get("expires_at") else None
        check(expiry is None or expiry > self.clock(), "token_expired")
        self._signing_secret()
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id)
            lock_table(db, table_id)
            key, fingerprint, old = self._command(db, user, "token_issue:" + table_id, data)
            if old:
                return self._token_view(db.get(TableJoinToken, old.result_id), table)
            stamp = self.clock()
            for previous in db.scalars(select(TableJoinToken).where(TableJoinToken.table_id == table_id,
                    TableJoinToken.channel == channel, TableJoinToken.purpose == purpose, TableJoinToken.seat == seat, TableJoinToken.revoked_at.is_(None))):
                previous.revoked_at = stamp
            db.flush()
            identifier = uuid4().hex
            raw = self._token_text(identifier)
            row = TableJoinToken(id=identifier, table_id=table_id, token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                channel=channel, purpose=purpose, seat=seat, created_at=stamp, created_by=str(user.id), expires_at=expiry, use_count=0)
            db.add(row); db.flush()
            self._remember(db, key, fingerprint, row.id)
            audit(db, table.tournament_id or "", user.id, "table_token_issued", {"table_id": table_id, "token_id": row.id, "channel": channel, "purpose": purpose, "seat": seat})
            return self._token_view(row, table)

    def revoke_token(self, token_id, user):
        admin(user)
        with membership_lock, self.store.connect() as db:
            row = db.get(TableJoinToken, token_id)
            check(row is not None, "invalid_join_token")
            table = db.get(ClubTable, row.table_id)
            lock_table(db, table.id)
            db.refresh(row)
            if not row.revoked_at:
                row.revoked_at = self.clock()
                audit(db, table.tournament_id or "", user.id, "table_token_revoked", {"token_id": row.id, "table_id": table.id})
            return self._token_view(row, table)

    def _resolve_token(self, db, raw):
        check(isinstance(raw, str) and 20 <= len(raw) <= 180, "invalid_join_token")
        row = db.scalar(select(TableJoinToken).where(TableJoinToken.token_hash == hashlib.sha256(raw.encode()).hexdigest()))
        check(row is not None and not row.revoked_at, "invalid_join_token")
        check(row.expires_at is None or row.expires_at > self.clock(), "token_expired")
        return row, self._table(db, row.table_id)

    @staticmethod
    def _target(table, number=None):
        return ("/?tournament=" + table.tournament_id + "&table=" + str(number or table.number)
                if table.tournament_id else "/?page=record&table=" + table.score_table_id)

    def token_info(self, raw):
        with self.store.connect() as db:
            token, table = self._resolve_token(db, raw)
            view = self._view(db, table)
            return {"table_id": table.id, "score_table_id": table.score_table_id, "number": table.number,
                    "display_name": table.display_name, "channel": token.channel, "purpose": token.purpose,
                    "seat": token.seat, "target": self._target(table), "members": view["members"],
                    "tournament_id": table.tournament_id, "capacity": table.capacity,
                    "allow_guest_auto_enrollment": bool(table.tournament_id and json.loads(db.get(Tournament, table.tournament_id).state_json)["settings"].get("allow_guest_auto_enrollment")),
                    "player_count": view["player_count"], "started_at": view["started_at"], "can_leave": view["can_leave"]}

    def join_token(self, raw, user, request_id, landing_seat=None, confirm_entry=False, expected_match_id=None):
        check(user is not None, "not_authenticated")
        check(isinstance(request_id, str) and 1 <= len(request_id) <= 128, "request_id_required")
        with self.account_guard(), membership_lock:
            with self.store.connect() as db:
                token, table = self._resolve_token(db, raw)
                if table.tournament_id:
                    from .tournament_flow import lock_tournament
                    lock_tournament(db, table.tournament_id)
                lock_table(db, table.id)
                # Re-read after the database lock so rotation/closure cannot race a scan.
                db.refresh(token); db.refresh(table)
                token, table = self._resolve_token(db, raw)
                tournament_entry = token.purpose == "table_landing" and bool(table.tournament_id) and confirm_entry is True
                if token.purpose == "table_landing" and landing_seat is None and not tournament_entry:
                    token.last_used_at, token.use_count = self.clock(), token.use_count + 1
                    return {"table_id": table.id, "target": self._target(table),
                            "purpose": token.purpose, "seat": None, "joined": False, "join_method": "qr_entry"}
                if token.purpose == "table_landing":
                    check(tournament_entry and landing_seat is None or landing_seat in SEATS, "invalid_seat")
                    method, wind = "qr_entry", landing_seat
                else:
                    # Caller-supplied winds can never modify a seat token binding.
                    method = "nfc" if token.channel == "nfc" else "qr_" + token.seat if token.seat else "qr"
                    wind = token.seat
                table_id, tid, purpose = table.id, table.tournament_id, token.purpose
                if tid:
                    state = self.tournaments._decode(db.get(Tournament, tid))
                    check(state["status"] in {"running", "round_pending", "finals_running"}, "invalid_state")
                    rid = state["finals"]["id"] if state["status"] == "finals_running" else state["rounds"][-1]["id"] if state["rounds"] else None
                    session = db.scalar(select(TournamentTableSession).where(
                        TournamentTableSession.table_id == table_id, TournamentTableSession.round_id == rid))
                    check(session is not None, "not_assigned")
                    mid, number = session.id, session.number
                    if tournament_entry:
                        check(expected_match_id is None or expected_match_id == mid, "stale_match")
                        assigned = assigned_tournament_seat(db, table, mid, user.id)
                        check(wind is None or wind == assigned, "seat_not_assigned")
                        wind = assigned
                    check(wind is None or assigned_tournament_seat(db, table, mid, user.id) == wind, "seat_not_assigned")
                    member = db.get(ActiveTableMember, str(user.id))
                    already = bool(member and member.table_id == table_id and member.match_id == mid)
                    if already and wind is not None:
                        check(member.seat == wind, "already_at_other_seat")
                    check(already or session.started_at is None, "already_started")
                    if not already:
                        from .tournament_operations import participant_action
                        participant_action(self.tournaments, membership_lock, tid, mid, "check_in", user,
                                           request_id, method, db_override=db)
                    token.last_used_at, token.use_count = self.clock(), token.use_count + 1
                    target = self._target(table, number)
                else:
                    score = db.scalar(select(TableState).where(TableState.table_id == table.score_table_id))
                    wind = ordinary_join(db, score, user, user.id, method, wind)
                    token.last_used_at, token.use_count = self.clock(), token.use_count + 1
                    target = self._target(table)
            return {"table_id": table_id, "target": target, "join_method": method,
                    "purpose": purpose, "seat": wind, "joined": True}

    def join(self, table_id, user, seat=None):
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id)
            check(not table.tournament_id, "fixed_tournament_seating")
            score = db.scalar(select(TableState).where(TableState.table_id == table.score_table_id))
            wind = ordinary_join(db, score, user, user.id, "manual", seat)
        return {"table_id": table_id, "seat": wind}

    def _ordinary_table_reference(self, db, table_id):
        table = db.get(ClubTable, table_id) or db.scalar(select(ClubTable).where(ClubTable.score_table_id == table_id))
        table_open(db, table)
        check(not table.tournament_id, "fixed_tournament_seating")
        return table

    def seat_map(self, table_id):
        """Anonymous occupancy contains no account identifiers or user names."""
        with self.store.connect() as db:
            table = self._ordinary_table_reference(db, table_id)
            score_id = table.score_table_id
        state = self.matches.table(score_id)
        check(state is not None, "table_not_found")
        return {"table": score_id, "display_name": state["display_name"], "seat_order": "ESWN",
            "players": {seat: {"occupied": True} if state["players"][seat] else None for seat in SEATS},
            "started_at": state["started_at"], "elapsed_seconds": state["elapsed_seconds"],
            "average_duration_seconds": state["average_duration_seconds"]}

    def set_my_seat(self, table_id, data, user):
        check(user is not None, "not_authenticated")
        check(isinstance(data, dict), "invalid_seat")
        with membership_lock, self.store.connect() as db:
            table = self._ordinary_table_reference(db, table_id)
            method = "seat_card"
            if data.get("entry_token") is not None:
                lock_table(db, table.id)
                db.refresh(table)
                token, token_table = self._resolve_token(db, data["entry_token"])
                check(token.purpose == "table_landing" and token_table.id == table.id, "invalid_join_token")
                method = "qr_entry"
            action, previous = ordinary_set_my_seat(db, table, user, data.get("seat"), data.get("match_id"), method)
            if method == "qr_entry" and action == "joined":
                token.last_used_at, token.use_count = self.clock(), token.use_count + 1
            score_id = table.score_table_id
        state = self.matches.table(score_id)
        state.update(seat_action=action, my_seat=data["seat"], previous_seat=previous)
        return state

    def leave(self, table_id, user, reason="voluntary", expected_match_id=None):
        check(isinstance(reason, str) and len(reason) <= 500, "invalid_reason")
        with membership_lock, self.store.connect() as db:
            table = self._ordinary_table_reference(db, table_id)
            changed = ordinary_leave(db, table, user, reason, expected_match_id)
            score_id = table.score_table_id
        return self.display_names({"table_id": table_id, "left": True, "changed": changed,
                                   "table_state": self.matches.table(score_id)})

    @staticmethod
    def parse_ids(value):
        if isinstance(value, str):
            ids = [p for p in re.split(r"[\s,，]+", value.strip()) if p]
        else:
            ids = value
        check(isinstance(ids, list) and 1 <= len(ids) <= 8 and all(isinstance(x, str) and 1 <= len(x) <= 128 for x in ids), "invalid_player_ids")
        check(len(set(ids)) == len(ids), "duplicate_player_ids")
        return ids

    def _account_rows(self, ids=None):
        if self.account_lookup:
            return self.account_lookup(ids)
        path = Path(os.getenv("TABLE_ACCOUNT_FILE", str(Path(__file__).resolve().parents[1] / "web_users.json")))
        try:
            from registered_names import account_rows
            return account_rows(path, ids=ids)
        except (OSError, ValueError):
            raise Conflict("account_directory_unavailable", "account_directory_unavailable") from None

    def display_names(self, value):
        """Project current registered names without rewriting historical identity keys."""
        from .registered_display import with_registered_names
        try:
            from .registered_display import referenced_account_ids
            profiles = self._account_rows(referenced_account_ids(value))
        except Conflict:
            profiles = []
        return with_registered_names(value, profiles)

    def available_players(self, table_id, user, query=""):
        """Only registered, enabled, unseated accounts. Never return account secrets."""
        check(isinstance(query, str) and len(query) <= 128, "invalid_player_ids")
        with self.store.connect() as db:
            table = self._table(db, table_id)
            self._can_add(db, table, user)
            active = set(db.scalars(select(ActiveTableMember.user_id)))
        from registered_names import normalize_name
        needle = normalize_name(query)
        candidates = [r for r in self._account_rows() if not r.get("disabled") and str(r["id"]) != str(user.id)
                      and str(r["id"]) not in active
                      and (not needle or needle in normalize_name(r["name"]))]
        candidates.sort(key=lambda r: (r["name"].casefold(), str(r["id"])))
        return {"players": [{"id": str(r["id"]), "name": r["name"], "avatar": r.get("avatar", "")}
                            for r in candidates[:50]], "has_more": len(candidates) > 50}

    def lookup_accounts(self, ids):
        check(isinstance(ids, list) and all(isinstance(uid, str) and 1 <= len(uid.strip()) <= 128 for uid in ids), "invalid_player_ids")
        rows = self._account_rows()
        by_id = {str(r["id"]): r for r in rows}
        normalized = [uid.strip() for uid in ids]
        check(all(uid in by_id for uid in normalized), "account_not_found")
        check(not any(by_id[uid].get("disabled") for uid in normalized), "account_disabled")
        return [{"id": str(by_id[uid]["id"]), "name": by_id[uid]["name"], "avatar": by_id[uid].get("avatar", "")} for uid in normalized]

    def _can_add(self, db, table, user):
        check(user is not None, "not_authenticated")
        check(not table.tournament_id, "fixed_tournament_seating")
        score = db.scalar(select(TableState).where(TableState.table_id == table.score_table_id))
        check(score.started_at is None, "table_already_started")
        check(not score.pending_match_id, "settlement_pending")
        return score

    def preview_players(self, table_id, value, user):
        ids = self.parse_ids(value)
        profiles = self.lookup_accounts(ids)
        ids = [person["id"] for person in profiles]
        check(len(set(ids)) == len(ids), "duplicate_player_ids")
        check(str(user.id) not in ids, "cannot_add_self")
        with self.store.connect() as db:
            self._can_add(db, self._table(db, table_id), user)
        return {"players": profiles}

    def add_players(self, table_id, data, user):
        requested = self.parse_ids(data.get("user_ids"))
        profiles = self.lookup_accounts(requested)
        ids = [person["id"] for person in profiles]
        check(len(set(ids)) == len(ids), "duplicate_player_ids")
        check(str(user.id) not in ids, "cannot_add_self")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id)
            lock_table(db, table.id)
            db.refresh(table)
            table_open(db, table)
            key, fingerprint, old = self._command(db, user, "add_players:" + table_id, data)
            if old:
                return {"table_id": table_id, "added": ids, "replayed": True}
            score = self._can_add(db, table, user)
            count = db.scalar(select(func.count()).select_from(ActiveTableMember).where(ActiveTableMember.table_id == table_id))
            check(count + len(ids) <= table.capacity, "table_full")
            for uid in ids:
                existing = db.get(ActiveTableMember, uid)
                check(existing is None or existing.table_id == table_id, "already_at_other_table")
                check(existing is None, "duplicate_player_ids")
            method = "registered_name"
            seats = data.get("seats", {})
            if data.get("seat") is not None:
                check(len(ids) == 1 and not seats, "invalid_seat")
                seats = {ids[0]: data["seat"]}
            check(isinstance(seats, dict) and set(seats).issubset(set(ids))
                  and all(wind in SEATS for wind in seats.values())
                  and len(set(seats.values())) == len(seats), "invalid_seat")
            for person in profiles:
                ordinary_join(db, score, User(id=person["id"], name=person["name"]), user.id, method, seat=seats.get(person["id"]))
            self._remember(db, key, fingerprint, table_id)
            audit(db, "", user.id, "table_players_added", {"table_id": table_id, "user_ids": ids, "join_method": method})
        return {"table_id": table_id, "added": ids, "replayed": False}

    def reset(self, table_id, data, user):
        admin(user)
        reason = str(data.get("reason", "")).strip()
        check(1 <= len(reason) <= 500, "reason_required")
        with membership_lock, self.store.connect() as db:
            table = self._table(db, table_id)
            check(not table.tournament_id, "fixed_tournament_seating")
            lock_table(db, table.id)
            db.refresh(table)
            table_open(db, table)
            key, fingerprint, old = self._command(db, user, "table_reset:" + table_id, data)
            if old:
                return {"table_id": table_id, "reset": True}
            score = db.scalar(select(TableState).where(TableState.table_id == table.score_table_id))
            check(score is not None, "table_not_found")
            from .game_flow import abort_current_ordinary_game
            abort_current_ordinary_game(db, table, score, str(user.id),
                                        reason, self.clock())
            self._remember(db, key, fingerprint, table_id)
        return {"table_id": table_id, "reset": True}

    def _reservation(self, db, row, include_session=True):
        result = {k: getattr(row, k) for k in ("id", "table_id", "user_id", "user_name", "scheduled_at",
            "created_at", "status", "note", "cancelled_at", "updated_at", "version", "updated_by", "cancelled_by", "end_at", "session_id")}
        result["planned_games"] = ("any" if row.plan_kind == "any" else
                                   row.planned_games if row.plan_kind == "finite" else None)
        result["plan_status"] = row.plan_kind
        result["created_by"] = row.user_id
        result["start_at"] = row.scheduled_at
        cache=db.info.get("table_views")
        participants=(cache["participants"].get(row.id,[]) if cache else db.scalars(select(ReservationParticipant)
            .where(ReservationParticipant.reservation_id==row.id).order_by(ReservationParticipant.added_at,ReservationParticipant.user_id)))
        from .reservation_queue import participant_progress
        counts=cache["progress"] if cache and "progress" in cache else participant_progress(db,[row])
        result["participants"]=[]
        for p in participants:
            progress=counts.get((row.id,p.user_id),{"completed":0,"occupied":0})
            remaining=(None if row.plan_kind=="any" else
                       max(0,(row.planned_games or 0)-progress["completed"]-progress["occupied"])
                       if row.plan_kind=="finite" else None)
            result["participants"].append({"id":p.user_id,"user_id":p.user_id,"name":p.user_name,
                "completed_games":progress["completed"],"occupied_games":progress["occupied"],
                "remaining_games":remaining,"queue_key":row.id+":"+p.user_id})
        local = datetime.fromisoformat(row.scheduled_at).astimezone(ZoneInfo(self.timezone))
        result.update(local_month=local.month, local_day=local.day, local_time=local.strftime("%H:%M"), timezone=self.timezone)
        end_local = datetime.fromisoformat(row.end_at).astimezone(ZoneInfo(self.timezone))
        result.update(end_local_month=end_local.month, end_local_day=end_local.day, end_local_time=end_local.strftime("%H:%M"))
        if include_session and row.session_id:
            from .reservation_session_models import ReservationSession
            result["session"] = self._reservation_session(db, cache["all_sessions"].get(row.session_id) if cache else db.get(ReservationSession, row.session_id), include_reservations=False)
        return result

    def _reservation_session(self, db, session, include_reservations=True):
        from .reservation_sessions import active_reservations, session_participants
        from .reservation_reminders import _local_fields, _zone, _utc
        if session is None:
            return None
        cache=db.info.get("table_views")
        table = cache["tables"].get(session.table_id) if cache else db.get(ClubTable, session.table_id)
        if cache and session.id in cache["session_rows"]:
            people_by_id={}
            progress=cache.get("progress",{})
            for row in cache["session_rows"][session.id]:
                persons=cache["participants"].get(row.id,[])
                for person in persons:
                    count=progress.get((row.id,person.user_id),{"completed":0,"occupied":0})
                    eligible=(row.plan_kind=="any" or row.plan_kind=="finite" and
                              row.planned_games is not None and
                              count["completed"]+count["occupied"]<row.planned_games)
                    if eligible:
                        people_by_id.setdefault(person.user_id,{"id":person.user_id,
                            "user_id":person.user_id,"name":person.user_name})
            people=list(people_by_id.values())
        else:
            people = session_participants(db, session.id)
        result = {key: getattr(session,key) for key in ("id","table_id","start_at","end_at","status","created_at","updated_at")}
        result.update(session_id=session.id, table_number=table.number, capacity=table.capacity,
            scheduled_at=session.start_at, participant_count=len(people), remaining_capacity=max(0,table.capacity-len(people)),
            participants=people, timezone=self.timezone,
            **_local_fields(_utc(session.start_at),_zone(self.timezone)),
            **{"end_"+key:value for key,value in _local_fields(_utc(session.end_at),_zone(self.timezone)).items()})
        if include_reservations:
            reservations=[]
            for row in (cache["session_rows"].get(session.id,[]) if cache else active_reservations(db,session.id)):
                detail=self._reservation(db,row,False)
                detail["participants"]=[person for person in detail["participants"]
                    if (detail["plan_status"]=="any" or
                        detail["plan_status"]=="finite" and person["remaining_games"]>0)]
                if detail["participants"]:
                    reservations.append(detail)
            result["reservations"]=reservations
        return result

    def reservation_time(self, data, previous=None):
        """Infer only current/next local year; edits retain the saved local year."""
        if not any(k in data for k in ("month", "day", "time")):
            return utc_value(data.get("scheduled_at")) if "scheduled_at" in data else previous
        try:
            month, day, clock = data.get("month"), data.get("day"), data.get("time")
            check(type(month) is int and type(day) is int and isinstance(clock, str)
                  and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock) is not None, "invalid_reservation_time")
            hour, minute = map(int, clock.split(":"))
            zone = ZoneInfo(self.timezone)
            local_now = datetime.fromisoformat(utc_value(self.clock())).astimezone(zone)
            if previous:
                year = datetime.fromisoformat(previous).astimezone(zone).year
            else:
                year = local_now.year + int((month, day, hour, minute, 0, 0) <
                    (local_now.month, local_now.day, local_now.hour, local_now.minute, local_now.second, local_now.microsecond))
            local = datetime(year, month, day, hour, minute, tzinfo=zone)
            check(local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == local.replace(tzinfo=None), "invalid_reservation_time")
            check(local.replace(fold=0).utcoffset() == local.replace(fold=1).utcoffset(), "ambiguous_reservation_time")
            return local.astimezone(timezone.utc).isoformat(timespec="milliseconds")
        except (ValueError, TypeError, OverflowError):
            raise Conflict("invalid_reservation_time", "invalid_reservation_time") from None
        except ZoneInfoNotFoundError:
            raise Conflict("invalid_site_timezone", "invalid_site_timezone") from None

    def _reservation_profiles(self, value, user):
        if value is None:
            value = [str(user.id)]
        if isinstance(value, str):
            value = [p for p in re.split(r"[\s,，]+", value) if p]
        check(isinstance(value, list) and 1 <= len(value) <= 100
              and all(isinstance(uid, str) and 1 <= len(uid.strip()) <= 128 for uid in value), "invalid_player_ids")
        ids = list(dict.fromkeys(uid.strip() for uid in value))
        profiles = self.lookup_accounts(ids)
        return list({profile["id"]: profile for profile in profiles}.values())

    @staticmethod
    def _store_participants(db, row, profiles, stamp):
        from .reservation_queue_models import ReservationGameLink
        existing={p.user_id:p for p in db.scalars(select(ReservationParticipant).where(
            ReservationParticipant.reservation_id==row.id))}
        requested={profile["id"]:profile for profile in profiles}
        for uid, person in existing.items():
            if uid not in requested:
                check(not db.scalar(select(ReservationGameLink.game_id).where(
                    ReservationGameLink.reservation_id==row.id,
                    ReservationGameLink.user_id==uid,
                    ReservationGameLink.status.in_(["started","confirmed"])).limit(1)),
                    "participant_has_games")
                db.delete(person)
        next_position=db.scalar(select(func.max(ReservationParticipant.queue_position))
            .join(TableReservation,TableReservation.id==ReservationParticipant.reservation_id)
            .where(TableReservation.table_id==row.table_id))
        next_position=0 if next_position is None else next_position+1
        for uid, profile in requested.items():
            if uid in existing:
                existing[uid].user_name=profile["name"]
            else:
                db.add(ReservationParticipant(reservation_id=row.id, user_id=uid,
                    user_name=profile["name"], added_at=stamp,queue_position=next_position))
                next_position+=1
        db.flush()

    def reserve(self, table_id, data, user):
        from .reservation_operations import reserve
        return reserve(self, table_id, data, user)

    def update_reservation(self, reservation_id, data, user):
        from .reservation_operations import update_reservation
        return update_reservation(self, reservation_id, data, user)

    def reservation_candidates(self, table_id, data, user):
        from .reservation_operations import reservation_candidates
        return reservation_candidates(self, table_id, data, user)

    def reservation_queue(self, table_id, user):
        check(user is not None, "not_authenticated")
        from .reservation_operations import resolve_table
        from .reservation_queue import queue_view
        from .reservation_sessions import lock_scope
        with membership_lock, self.store.connect() as db:
            table=resolve_table(self,db,table_id)
            lock_scope(db,table.scope); lock_table(db,table.id)
            db.refresh(table); table_open(db,table)
            return queue_view(db,table.id,self.clock(),self._queue_reorder_allowed(user))

    @staticmethod
    def _queue_reorder_allowed(user):
        return user is not None

    def reorder_reservation_queue(self, table_id, data, user):
        check(user is not None, "not_authenticated")
        check(self._queue_reorder_allowed(user), "queue_reorder_forbidden")
        from .reservation_operations import resolve_table
        from .reservation_queue import queue_view, reorder
        from .reservation_sessions import lock_scope
        with membership_lock, self.store.connect() as db:
            table=resolve_table(self,db,table_id)
            lock_scope(db,table.scope); lock_table(db,table.id)
            db.refresh(table); table_open(db,table)
            key,fingerprint,old=self._command(db,user,"queue_reorder:"+table.id,data)
            if old:
                return queue_view(db,table.id,self.clock(),True)
            result=reorder(db,table.id,user.id,data.get("version"),
                           data.get("ordered_keys"),self.clock())
            self._remember(db,key,fingerprint,table.id)
            return result
