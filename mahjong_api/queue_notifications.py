"""Queue notices use the existing persisted Discord sender and recovery fence."""
import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from .discord_reminder_models import DiscordReminder
from .discord_reminder_sender import (DiscordReminderError, safe_registered_name)
from .discord_reminder_config import discord_id
from .game_round_models import GameRound
from .database_models import TableState
from .reservation_queue_models import ReservationQueueBatch
from .reservation_queue import batch_members, next_batch, _duration, _roster_ids
from .reservation_sessions import instant, lock_scope
from .table_membership import lock_table, membership_lock
from .table_models import ClubTable


KINDS = {"queue_prepare", "queue_all_last", "queue_ready"}


def _stamp(value):
    return instant(value).isoformat(timespec="milliseconds")


def enqueue_queue_notice(db, table, game, batch, kind, clock, due=None):
    """Idempotently persist one notice per batch membership version and kind."""
    if kind not in KINDS:
        raise ValueError("invalid queue notice kind")
    batch_id = batch["id"] if isinstance(batch, dict) else batch.id
    version = batch["version"] if isinstance(batch, dict) else batch.version
    members = (batch["participants"] if isinstance(batch, dict) else
               [{"user_id": row.user_id} for row in batch_members(db, batch_id)])
    ids = [member["user_id"] for member in members]
    key = "q:" + batch_id + ":" + str(version)
    # Identity is tied to the real game and roster version, never a forecast
    # that may move by a few minutes on every queue refresh.
    snapshot = _stamp(game.started_at)
    existing = db.scalar(select(DiscordReminder).where(
        DiscordReminder.session_id == key,
        DiscordReminder.start_at_snapshot == snapshot,
        DiscordReminder.notification_type == kind))
    if existing:
        if existing.status == "pending" and kind == "queue_prepare" and not existing.delivery_uncertain:
            target = _stamp(due or clock)
            if existing.scheduled_for != target:
                existing.scheduled_for = target
                existing.next_attempt_at = target
                existing.updated_at = _stamp(clock)
        return existing
    nonce = hashlib.sha256((game.game_id + "\0" + key + "\0" + kind).encode()).hexdigest()[:24]
    stamp = _stamp(clock)
    row = DiscordReminder(id=str(uuid4()), session_id=key, scope=table.scope,
        batch_id=batch_id, predecessor_game_id=game.game_id, member_version=version,
        member_ids_json=json.dumps(ids, separators=(",", ":")),
        start_at_snapshot=snapshot, notification_type=kind,
        status="pending", scheduled_for=_stamp(due or clock),
        next_attempt_at=_stamp(due or clock), nonce=nonce,
        created_at=stamp, updated_at=stamp)
    db.add(row)
    db.flush()
    return row


def plan_queue_notices(service):
    """Reconcile current batches and enqueue only due or future durable jobs."""
    with service.store.connect() as db:
        ids = list(db.scalars(select(GameRound.game_id).where(
            GameRound.status == "playing")))
        ids += list(db.scalars(select(GameRound.game_id).where(
            GameRound.status == "completed", GameRound.successor_batch_id.is_not(None))))
        # After ordinary score confirmation there may be no All Last link.
        # Only the latest finished game at an idle physical table can own the
        # next batch; an old late score cannot target a later batch.
        for score in db.scalars(select(TableState).where(TableState.started_at.is_(None))):
            latest = db.scalar(select(GameRound.game_id).where(
                GameRound.score_table_id == score.table_id,
                GameRound.status == "completed",
                GameRound.successor_batch_id.is_(None))
                .order_by(GameRound.started_at.desc(), GameRound.game_id.desc()).limit(1))
            if latest:
                ids.append(latest)
    for game_id in ids:
        with membership_lock, service.store.connect() as db:
            game = db.get(GameRound, game_id)
            if game is None or game.status not in {"playing", "completed"}:
                continue
            table = db.get(ClubTable, game.table_id)
            if table is None or table.status != "open":
                continue
            lock_scope(db, table.scope)
            lock_table(db, table.id)
            db.refresh(game)
            if game.status == "playing":
                batch = next_batch(db, table.id, service.clock())
            elif game.successor_batch_id:
                batch = db.get(ReservationQueueBatch, game.successor_batch_id)
            else:
                score = db.scalar(select(TableState).where(
                    TableState.table_id == game.score_table_id))
                newer = db.scalar(select(GameRound.game_id).where(
                    GameRound.table_id == table.id,
                    GameRound.started_at > game.started_at).limit(1))
                if score is None or score.started_at is not None or newer:
                    continue
                batch = next_batch(db, table.id, service.clock())
                if batch:
                    game.successor_batch_id = batch.id
            if batch is None or batch.status not in {"provisional", "notified"}:
                continue
            if game.status == "playing":
                game.successor_batch_id = batch.id
                if len(batch_members(db, batch.id)) == 4:
                    duration, _ = _duration(db, _roster_ids(game.roster_json))
                    if duration is not None:
                        due = instant(game.started_at) + timedelta(seconds=duration-20*60)
                        enqueue_queue_notice(db, table, game, batch,
                            "queue_prepare", service.clock(), due=due)
                if game.all_last_at:
                    enqueue_queue_notice(db, table, game, batch,
                        "queue_all_last", service.clock())
            elif game.status == "completed":
                enqueue_queue_notice(db, table, game, batch,
                    "queue_ready", service.clock())


def build_queue_message(*, kind, table_number, start_at, participants, nonce,
                        mention_ids=None):
    allowed = []
    lines = []
    mention_ids = set(mention_ids) if mention_ids is not None else None
    for person in participants:
        bound = discord_id(person.get("discord_id"))
        if bound:
            lines.append("• <@" + bound + ">")
            if mention_ids is None or person["id"] in mention_ids:
                if bound not in allowed:
                    allowed.append(bound)
        else:
            lines.append("• " + safe_registered_name(person.get("name")))
    label = "Table " + str(int(table_number))
    count = len(participants)
    missing = max(0, 4-count)
    if kind == "queue_prepare":
        start = int(instant(start_at).timestamp()) if start_at else None
        body = ("Mahjong Queue Reminder\n\nYou are next for " + label + ".\n" +
                (f"Estimated start: <t:{start}:F>\n" if start else "") +
                "The current game is expected to finish in about 20 minutes.\nPlease get ready.")
    elif kind == "queue_all_last":
        body = ("All Last — You're Next\n\nThe current game at " + label +
                " is in its final stage.\n" +
                ("You are the next players. Please come to the table and get ready." if not missing else
                 "You are in the next group. Please get ready while we fill the remaining seats."))
    else:
        body = (("Your Table Is Ready" if not missing else "Previous Game Finished — Waiting for Players") +
                "\n\nThe previous game at " + label + " has finished.\n" +
                ("You are the next four players. Please take your seats." if not missing else
                 "You are in the next group. Please wait for the remaining players before starting."))
    body += "\n\nPlayers:\n" + "\n".join(lines)
    if missing:
        body += f"\n\nWe still need {missing} more {'player' if missing == 1 else 'players'}."
    if len(body.encode("utf-16-le")) // 2 > 2000:
        raise DiscordReminderError("message_too_large")
    return {"content": body, "nonce": nonce, "enforce_nonce": True,
        "allowed_mentions": {"parse": [], "users": allowed,
                             "roles": [], "replied_user": False}}


def build_additions_message(*, table_number, participants, nonce):
    permitted, lines = [], []
    for person in participants:
        bound = discord_id(person.get("discord_id"))
        if bound:
            lines.append("• <@" + bound + ">")
            if bound not in permitted:
                permitted.append(bound)
        else:
            lines.append("• " + safe_registered_name(person.get("name")))
    content = ("Mahjong Queue Update\n\nYou have joined the next group for Table " +
               str(int(table_number)) + ". Please come to the table and get ready.\n\n" +
               "\n".join(lines))
    if len(content.encode("utf-16-le")) // 2 > 2000:
        raise DiscordReminderError("message_too_large")
    return {"content": content, "nonce": nonce, "enforce_nonce": True,
            "allowed_mentions": {"parse": [], "users": permitted,
                                 "roles": [], "replied_user": False}}


def send_queue_locked(service, identifier, token, destination=None):
    """Validate latest membership under existing pre-send fence, then POST."""
    dispatch = None
    edit_target = None
    edit_only_id = None
    with service.store.connect() as db:
        seed = db.get(DiscordReminder, identifier)
        if seed is None or not seed.batch_id:
            return
        lock_scope(db, seed.scope)
        batch = db.get(ReservationQueueBatch, seed.batch_id)
        table = db.get(ClubTable, batch.table_id) if batch else None
        if table:
            lock_table(db, table.id)
            # The persisted batch can lag a cancellation or account change.
            # Recompute eligibility while the scope and table are locked so a
            # stale projected member list cannot become a Discord recipient.
            next_batch(db, table.id, service.clock())
        row = db.scalar(select(DiscordReminder).where(DiscordReminder.id == identifier).with_for_update())
        if row is None or row.claim_token != token or row.status != "processing":
            return
        game = db.get(GameRound, row.predecessor_game_id)
        valid = (batch is not None and table is not None and table.status == "open" and
                 game is not None and game.successor_batch_id == batch.id and
                 batch.status in {"provisional", "notified"} and
                 row.member_version == batch.version and
                 row.scope == table.scope)
        current = instant(service.clock())
        if not valid:
            row.status, row.last_error = "cancelled", "stale_queue_batch"
            row.claim_token, row.lease_until = None, None
            row.delivery_uncertain, row.send_started_at = 0, None
            return
        if row.notification_type == "queue_prepare" and (
                game.status != "playing" or game.all_last_at is not None):
            valid = False
        elif row.notification_type == "queue_all_last" and (
                game.status != "playing" or game.all_last_at is None):
            valid = False
        elif row.notification_type == "queue_ready" and game.status != "completed":
            valid = False
        if not valid:
            row.status, row.last_error = "cancelled", "game_state_changed"
            row.claim_token, row.lease_until = None, None
            row.delivery_uncertain, row.send_started_at = 0, None
            return
        if instant(row.scheduled_for) > current:
            service._error(row, DiscordReminderError("not_due", retryable=True,
                retry_after=(instant(row.scheduled_for)-current).total_seconds()))
            return
        members = batch_members(db, batch.id)
        ids = [member.user_id for member in members]
        if ids != json.loads(row.member_ids_json or "[]"):
            row.status, row.last_error = "cancelled", "roster_changed"
            row.claim_token, row.lease_until = None, None
            row.delivery_uncertain, row.send_started_at = 0, None
            return
        earlier = list(db.scalars(select(DiscordReminder).where(
            DiscordReminder.batch_id == batch.id,
            DiscordReminder.predecessor_game_id == game.game_id,
            DiscordReminder.notification_type == "queue_all_last",
            DiscordReminder.status == "sent")))
        if row.notification_type == "queue_ready" and any(
                json.loads(previous.member_ids_json or "[]") == ids for previous in earlier):
            row.status, row.last_error = "cancelled", "already_notified_all_last"
            row.claim_token, row.lease_until = None, None
            row.delivery_uncertain, row.send_started_at = 0, None
            return
        # If an earlier All Last reached a subset, only newly added people get
        # another ping. Text still shows the complete current lineup.
        if row.notification_type == "queue_all_last":
            earlier += list(db.scalars(select(DiscordReminder).where(
                DiscordReminder.batch_id == batch.id,
                DiscordReminder.predecessor_game_id == game.game_id,
                DiscordReminder.notification_type == "queue_all_last",
                DiscordReminder.status == "sent",
                DiscordReminder.id != row.id)))
        prior_ids = set().union(*(json.loads(previous.member_ids_json or "[]")
                                  for previous in earlier)) if earlier else set()
        mention_ids = (set(ids)-prior_ids if row.notification_type in
                       {"queue_ready", "queue_all_last"} and earlier else None)
        profiles = {str(person["id"]): person for person in service._profiles(set(ids))
                    if not person.get("disabled")}
        people = [profiles.get(member.user_id, {"id": member.user_id,
                  "name": member.user_name}) for member in members]
        payload = build_queue_message(kind=row.notification_type,
            table_number=table.number, start_at=batch.estimated_start_at,
            participants=people, nonce=row.nonce, mention_ids=mention_ids)
        target = destination or {"channel_id": row.channel_id,
                                 "bot_user_id": row.bot_user_id}
        if earlier and row.notification_type in {"queue_all_last", "queue_ready"}:
            original = next((item for item in earlier if item.discord_message_id), None)
            if original:
                edit_payload = {**payload, "allowed_mentions": {
                    "parse": [], "users": [], "roles": [], "replied_user": False}}
                edit_target = ({"channel_id": original.channel_id or target["channel_id"]},
                               original.discord_message_id, edit_payload)
                additions = [person for person in people if person["id"] in set(ids)-prior_ids]
                if additions:
                    dispatch = (target, build_additions_message(
                        table_number=table.number, participants=additions, nonce=row.nonce))
                else:
                    edit_only_id = original.discord_message_id
                    row.discord_message_id = edit_only_id
        if edit_target is None:
            dispatch = (target, payload)
    try:
        if edit_target is not None:
            service.sender.edit(*edit_target)
        message_id = service.sender.send(*dispatch) if dispatch else edit_only_id
        if message_id:
            with service.store.connect() as db:
                row = db.get(DiscordReminder, identifier)
                if row and row.claim_token == token and row.status == "processing":
                    service._record_sent(db, row, message_id)
                    batch = db.get(ReservationQueueBatch, row.batch_id)
                    if batch and batch.status == "provisional":
                        batch.status = "notified"
    except DiscordReminderError as error:
        service._finish_error(identifier, token, error)

