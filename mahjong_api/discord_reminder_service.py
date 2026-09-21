"""Restartable reservation-session reminders with a durable pre-send fence.

The score DB stores intent before the POST. An uncertain attempt is reconciled
using Discord history, never posted again. The scope/table locks linearize each
send against cancellation, regrouping, table closure and capacity changes.
"""
import hashlib
import logging
import json
import sqlite3
import os
from contextlib import nullcontext, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, or_, select, update, exists, case
from sqlalchemy.orm import object_session
from sqlalchemy.exc import IntegrityError

from .discord_reminder_config import DiscordReminderConfig, discord_id
from .discord_reminder_models import DiscordReminder, DiscordReminderThrottle
from .discord_reminder_sender import DiscordReminderError, DiscordReminderSender, build_message
from .reservation_session_models import ReservationSession
from .reservation_sessions import lock_scope, session_participants
from .table_membership import lock_table
from .table_models import ClubTable, TableReservation
from .tournament_models import Tournament

logger = logging.getLogger(__name__)


def instant(value):
    result = datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.astimezone(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class DiscordReminderService:
    def __init__(self, tables, config=None, sender=None, account_path=None, account_lookup=None):
        self.tables, self.store = tables, tables.store
        self.config = config if config is not None else DiscordReminderConfig.from_env()
        self.sender = sender if sender is not None else DiscordReminderSender(self.config)
        self.account_path = Path(account_path or os.getenv("TABLE_ACCOUNT_FILE", str(Path(__file__).resolve().parents[1]/"web_users.json")))
        self.account_lookup = account_lookup
        self.clock = lambda: tables.clock()
        self.lease_seconds = 120

    def plan(self):
        """Discover all future active sessions; unique keys survive every restart."""
        current = instant(self.clock())
        created = 0
        with self.store.connect() as db:
            sessions = list(db.scalars(select(ReservationSession).where(ReservationSession.status=="active")))
            for session in sessions:
                start = instant(session.start_at)
                if start <= current:
                    continue
                snapshot = stamp(start)
                previous=db.scalar(select(DiscordReminder).where(DiscordReminder.session_id==session.id,
                    DiscordReminder.start_at_snapshot==snapshot, DiscordReminder.notification_type=="one_hour"))
                if previous:
                    if previous.status=="cancelled" and not previous.delivery_uncertain and not previous.discord_message_id:
                        db.execute(update(DiscordReminder).where(DiscordReminder.id==previous.id,
                            DiscordReminder.status=="cancelled",DiscordReminder.delivery_uncertain==0,
                            DiscordReminder.discord_message_id.is_(None)).values(status="pending",
                                next_attempt_at=stamp(start-timedelta(hours=1)),last_error=None))
                    continue
                due = stamp(start-timedelta(hours=1))
                digest = hashlib.sha256((session.id+"\0"+snapshot+"\0one_hour").encode()).hexdigest()[:24]
                try:
                    with db.begin_nested():
                        db.add(DiscordReminder(id=str(uuid4()),session_id=session.id,scope=session.scope,
                            start_at_snapshot=snapshot,scheduled_for=due,next_attempt_at=due,nonce=digest,
                            created_at=stamp(current),updated_at=stamp(current),
                            last_error=("reminders_disabled" if not self.config.enabled else
                                        "missing_configuration" if not self.config.configured else None)))
                        db.flush()
                    created += 1
                except IntegrityError:
                    # A concurrent planner already created this exact version.
                    pass
            # Stale unsent versions can be retired immediately, even before due.
            for job in db.scalars(select(DiscordReminder).where(DiscordReminder.status.in_(["pending","retrying"]),
                    DiscordReminder.delivery_uncertain==0)):
                session = db.get(ReservationSession,job.session_id)
                if (session is None or session.status!="active" or session.scope!=job.scope or
                        stamp(instant(session.start_at))!=job.start_at_snapshot or instant(session.start_at)<=current):
                    db.execute(update(DiscordReminder).where(DiscordReminder.id==job.id,
                        DiscordReminder.status.in_(["pending","retrying"]),DiscordReminder.delivery_uncertain==0)
                        .values(status="cancelled",last_error="session_no_longer_due",updated_at=stamp(current)))
        return created

    def _claim(self, identifier):
        current, token = instant(self.clock()), str(uuid4())
        due = or_(and_(DiscordReminder.status.in_(["pending","retrying"]),DiscordReminder.next_attempt_at<=stamp(current)),
                  and_(DiscordReminder.status=="processing",DiscordReminder.lease_until<=stamp(current)))
        with self.store.connect() as db:
            ready=~exists(select(DiscordReminderThrottle.key).where(DiscordReminderThrottle.not_before>stamp(current)))
            changed = db.execute(update(DiscordReminder).where(DiscordReminder.id==identifier,due,ready).values(
                status="processing",claim_token=token,lease_until=stamp(current+timedelta(seconds=self.lease_seconds)),
                last_attempt_at=stamp(current),attempt_count=DiscordReminder.attempt_count+1,updated_at=stamp(current)))
            return token if changed.rowcount==1 else None

    def _error(self, row, error):
        current = instant(self.clock())
        row.last_error, row.updated_at = error.code, stamp(current)
        if error.code=="rate_limited":
            db=object_session(row)
            if db.bind.dialect.name=="postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert
            until=stamp(current+timedelta(seconds=error.retry_after or 60))
            statement=insert(DiscordReminderThrottle).values(key="discord",not_before=until)
            db.execute(statement.on_conflict_do_update(index_elements=["key"],set_={"not_before":case(
                (DiscordReminderThrottle.not_before<until,until),else_=DiscordReminderThrottle.not_before)}))
        row.claim_token, row.lease_until = None, None
        if error.uncertain:
            row.delivery_uncertain = 1
            row.status, row.next_attempt_at = "retrying", stamp(current+timedelta(seconds=error.retry_after or 30))
        else:
            row.delivery_uncertain, row.send_started_at = 0, None
            row.status = "retrying" if error.retryable else "failed"
            delay = error.retry_after or min(900, 5*(2**min(row.attempt_count,7)))
            row.next_attempt_at = stamp(current+timedelta(seconds=delay))

    def _finish_error(self, identifier, token, error):
        with self.store.connect() as db:
            row = db.scalar(select(DiscordReminder).where(DiscordReminder.id==identifier).with_for_update())
            if row and row.claim_token==token and row.status=="processing":
                self._error(row,error)
        logger.warning("Discord reservation reminder: %s",error.code)

    def _record_sent(self, db, row, message_id):
        row.status, row.discord_message_id = "sent", message_id
        row.sent_at, row.updated_at = stamp(instant(self.clock())), stamp(instant(self.clock()))
        row.last_error, row.claim_token, row.lease_until = None, None, None
        row.delivery_uncertain = 0

    def _recover(self, identifier, token, evidence):
        # Do not revalidate current reservation here: an already delivered message
        # remains sent even if the session was cancelled after the failed commit.
        try:
            if not self.config.enabled:
                raise DiscordReminderError("reminders_disabled",retryable=True,retry_after=60,uncertain=True)
            if not self.config.configured:
                raise DiscordReminderError("missing_configuration",retryable=True,retry_after=60,uncertain=True)
            message = self.sender.reconcile(evidence["channel_id"],evidence["bot_user_id"],evidence["nonce"],evidence["send_started_at"])
            with self.store.connect() as db:
                row = db.scalar(select(DiscordReminder).where(DiscordReminder.id==identifier).with_for_update())
                if row is None or row.claim_token!=token or row.status!="processing":
                    return
                if message:
                    self._record_sent(db,row,message)
                else:
                    row.status, row.last_error = "failed", "delivery_unknown"
                    row.claim_token, row.lease_until = None, None
                    row.updated_at = stamp(instant(self.clock()))
        except DiscordReminderError as error:
            # Keep the pre-send fence even when a reconciliation GET fails.
            if error.retryable:
                error.uncertain = True
                self._finish_error(identifier,token,error)
            else:
                with self.store.connect() as db:
                    row=db.scalar(select(DiscordReminder).where(DiscordReminder.id==identifier).with_for_update())
                    if row and row.claim_token==token and row.status=="processing":
                        row.status,row.last_error="failed","delivery_unknown:"+error.code
                        row.claim_token,row.lease_until=None,None
                        row.updated_at=stamp(instant(self.clock()))

    def _profiles(self, participant_ids):
        if self.account_lookup is not None:
            return self.account_lookup(participant_ids)
        import registered_names
        if not self.account_path.is_file():
            raise DiscordReminderError("account_directory_unavailable",retryable=True)
        try:
            # This method runs under the nonblocking account lock and the score
            # gate. Never perform account recovery or wait for another database.
            if Path(str(self.account_path)+".pending").exists():
                raise DiscordReminderError("account_recovery_pending",retryable=True)
            directory=registered_names.database_path(self.account_path)
            if directory.is_file():
                with closing(sqlite3.connect(directory.resolve().as_uri()+"?mode=ro",uri=True,timeout=0)) as account_db:
                    if account_db.execute("SELECT 1 FROM pending_registered_name_changes LIMIT 1").fetchone():
                        raise DiscordReminderError("account_recovery_pending",retryable=True)
            data=json.loads(self.account_path.read_text(encoding="utf-8"))
            if not isinstance(data,dict) or not isinstance(data.get("users",{}),dict):
                raise ValueError("invalid_accounts")
        except (OSError,ValueError,sqlite3.Error):
            raise DiscordReminderError("account_directory_unavailable",retryable=True) from None
        result=[]
        for key, account in data.get("users",{}).items():
            uid=str(account.get("account_id") or "")
            if uid not in participant_ids:
                continue
            enabled=not(account.get("disabled") or account.get("is_active") is False or account.get("status") in {"disabled","banned","deleted"})
            result.append({"id":uid,"name":account.get("registeredName") or account.get("name") or "Registered player",
                           "discord_id":discord_id(account.get("discord_id")) if enabled else "", "disabled":not enabled})
        return result

    def _prepare_accounts(self):
        if self.account_lookup is not None:
            return
        import registered_names
        try:
            # Any rename/file recovery and waiting happens before taking the
            # score DB write gate. The final guarded read checks for newer work.
            if not self.account_path.is_file():
                raise ValueError("missing_accounts")
            registered_names.read_accounts(self.account_path)
        except (OSError,ValueError,sqlite3.Error):
            raise DiscordReminderError("account_directory_unavailable",retryable=True) from None

    def _send_locked(self, identifier, token, destination=None):
        with self.store.connect() as db:
            # Scope first, then tournament/table rows, then delivery row. No
            # remote mutation occurs until the exact current membership is read.
            seed = db.get(DiscordReminder,identifier)
            lock_scope(db,seed.scope)
            db.refresh(seed)
            row = db.scalar(select(DiscordReminder).where(DiscordReminder.id==identifier).with_for_update())
            if row.claim_token!=token or row.status!="processing":
                return
            session = db.get(ReservationSession,row.session_id)
            table = db.get(ClubTable,session.table_id) if session else None
            tournament = None
            if table and table.tournament_id:
                tournament=db.scalar(select(Tournament).where(Tournament.id==table.tournament_id).with_for_update())
            if table:
                lock_table(db,table.id)
                db.refresh(table)
            valid=(session is not None and session.status=="active" and session.scope==row.scope and
                   table is not None and table.scope==row.scope and table.status=="open" and
                   (not table.tournament_id or (tournament is not None and not tournament.deleted_at)) and
                   stamp(instant(session.start_at))==row.start_at_snapshot)
            current=instant(self.clock())
            if not valid or instant(row.start_at_snapshot)<=current:
                row.status,row.last_error="cancelled","session_no_longer_due"
                row.delivery_uncertain,row.send_started_at=0,None
                row.claim_token,row.lease_until=None,None
                row.updated_at=stamp(current)
                return
            if instant(row.scheduled_for)>current:
                self._error(row,DiscordReminderError("not_due",retryable=True,
                    retry_after=(instant(row.scheduled_for)-current).total_seconds()))
                return
            participants=session_participants(db,session.id)
            # Independently verify the range against the latest active records.
            reservations=list(db.scalars(select(TableReservation).where(TableReservation.session_id==session.id,
                TableReservation.status=="active",TableReservation.table_id==table.id)))
            if (not participants or not reservations or
                    stamp(min(instant(item.scheduled_at) for item in reservations))!=row.start_at_snapshot):
                row.status,row.last_error="cancelled","empty_or_changed_session"
                row.delivery_uncertain,row.send_started_at=0,None
                row.claim_token,row.lease_until=None,None
                return
            end_at=stamp(max(instant(item.end_at) for item in reservations))
            import registered_names
            guard=registered_names.account_lock(self.account_path,blocking=False) if self.account_lookup is None else nullcontext()
            try:
                with guard:
                    ids={str(person["id"]) for person in participants}
                    people={str(person["id"]):person for person in self._profiles(ids)
                            if str(person["id"]) in ids and not person.get("disabled")}
                    if not people:
                        raise DiscordReminderError("no_active_registered_participants")
                    if len(people)>table.capacity:
                        logger.warning("Discord reservation session exceeds table capacity")
                    payload=build_message(table_number=table.number,start_at=row.start_at_snapshot,end_at=end_at,
                        capacity=table.capacity,participants=list(people.values()),nonce=row.nonce)
                    if instant(self.clock())>=instant(row.start_at_snapshot):
                        row.status,row.last_error="cancelled","reservation_started"
                        row.delivery_uncertain,row.send_started_at=0,None
                        row.claim_token,row.lease_until=None,None
                        return
                    throttle=db.get(DiscordReminderThrottle,"discord")
                    if throttle and instant(throttle.not_before)>instant(self.clock()):
                        raise DiscordReminderError("rate_limited",retryable=True,
                            retry_after=(instant(throttle.not_before)-instant(self.clock())).total_seconds())
                    message_id=self.sender.send(destination or {"channel_id":row.channel_id,"bot_user_id":row.bot_user_id},payload)
                    self._record_sent(db,row,message_id)
            except (TimeoutError,BlockingIOError):
                self._error(row,DiscordReminderError("account_directory_busy",retryable=True))
            except DiscordReminderError as error:
                self._error(row,error)
                logger.warning("Discord reservation reminder: %s",error.code)

    def _process(self, identifier, token):
        with self.store.connect() as db:
            row=db.get(DiscordReminder,identifier)
            if row.claim_token!=token or row.status!="processing":
                return
            evidence={field:getattr(row,field) for field in ("channel_id","bot_user_id","nonce","send_started_at")}
            uncertain=bool(row.delivery_uncertain)
        if uncertain:
            self._recover(identifier,token,evidence)
            return
        try:
            if not self.config.enabled:
                raise DiscordReminderError("reminders_disabled",retryable=True,retry_after=60)
            if not self.config.configured:
                raise DiscordReminderError("missing_configuration",retryable=True,retry_after=60)
            self._prepare_accounts()
            destination=self.sender.prepare()
        except DiscordReminderError as error:
            self._finish_error(identifier,token,error)
            return
        try:
            # This commit is intentionally BEFORE the external mutation. A crash
            # cannot erase the fact that a send might have occurred.
            with self.store.connect() as db:
                changed=db.execute(update(DiscordReminder).where(DiscordReminder.id==identifier,
                    DiscordReminder.claim_token==token,DiscordReminder.status=="processing").values(
                        delivery_uncertain=1,send_started_at=stamp(instant(self.clock())),
                        channel_id=destination["channel_id"],bot_user_id=destination["bot_user_id"]))
                if changed.rowcount!=1:
                    return
            self._send_locked(identifier,token,destination)
        finally:
            # A cancellation or lease loss can happen after preconnection and
            # before POST. Release that socket on every path, including DB errors.
            connection=destination.get("_connection")
            if connection is not None:
                connection.close()

    def tick(self, limit=10):
        self.plan()
        current=stamp(instant(self.clock()))
        with self.store.connect() as db:
            candidates=list(db.scalars(select(DiscordReminder.id).where(or_(
                and_(DiscordReminder.status.in_(["pending","retrying"]),DiscordReminder.next_attempt_at<=current),
                and_(DiscordReminder.status=="processing",DiscordReminder.lease_until<=current)))
                .order_by(DiscordReminder.scheduled_for,DiscordReminder.id).limit(max(1,min(int(limit),100)))))
        processed=0
        for identifier in candidates:
            token=self._claim(identifier)
            if not token:
                continue
            try:
                self._process(identifier,token)
            except Exception:
                # Deliberately omit exception text/headers. The durable intent
                # remains processing until lease expiry and history recovery.
                logger.warning("Discord reminder interrupted; durable recovery will inspect delivery")
            processed+=1
        return {"processed":processed}
