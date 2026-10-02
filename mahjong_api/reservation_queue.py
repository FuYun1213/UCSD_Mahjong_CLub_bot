"""One bounded, persistent next batch per physical table.

An unlimited reservation contributes at most one candidate to the next batch.
The already-started game is accounted for separately from confirmed games.
"""
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, select

from .database_models import TableState
from .game_round_models import GameRound
from .reservation_queue_models import (
    ReservationDurationSample, ReservationDurationSummary, ReservationGameLink,
    ReservationQueueAudit, ReservationQueueBatch, ReservationQueueBatchMember,
    ReservationQueueState,
)
from .reservation_sessions import instant, recalculate_session
from .table_membership import check
from .table_models import ClubTable, ReservationParticipant, TableReservation
from .store import now


def _stamp(value):
    return instant(value).isoformat(timespec="milliseconds")


def _key(person):
    return person["reservation_id"] + ":" + person["user_id"]


def _plan(row):
    if row.plan_kind == "any":
        return "any"
    if row.plan_kind == "finite" and row.planned_games and row.planned_games > 0:
        return row.planned_games
    return None


def _progress(db, reservation_ids):
    result = {}
    if reservation_ids:
        links = db.scalars(select(ReservationGameLink).where(
            ReservationGameLink.reservation_id.in_(reservation_ids)))
        for link in links:
            item = result.setdefault((link.reservation_id, link.user_id),
                                     {"completed": 0, "occupied": 0})
            if link.status == "confirmed":
                item["completed"] += 1
            elif link.status == "started":
                item["occupied"] += 1
    return result


def participant_progress(db, rows):
    """Progress for response projections without mutating a reservation."""
    ids = [row.id for row in rows]
    return _progress(db, ids)


def _candidates(db, table_id):
    rows = list(db.scalars(select(TableReservation).where(
        TableReservation.table_id == table_id,
        TableReservation.status == "active",
        TableReservation.plan_kind.in_(["finite", "any"]))
        .order_by(TableReservation.scheduled_at, TableReservation.created_at,
                  TableReservation.id)))
    ids = [row.id for row in rows]
    participants = list(db.scalars(select(ReservationParticipant).where(
        ReservationParticipant.reservation_id.in_(ids))
        .order_by(ReservationParticipant.added_at, ReservationParticipant.user_id))) if ids else []
    by_reservation = {}
    for person in participants:
        by_reservation.setdefault(person.reservation_id, []).append(person)
    counts = _progress(db, ids)
    by_user = {}
    for row in rows:
        plan = _plan(row)
        if plan is None:
            continue
        for person in by_reservation.get(row.id, []):
            count = counts.get((row.id, person.user_id), {"completed": 0, "occupied": 0})
            remaining = None if plan == "any" else max(0, plan - count["completed"] - count["occupied"])
            if remaining == 0:
                continue
            candidate = {
                "key": row.id + ":" + person.user_id,
                "reservation_id": row.id, "user_id": person.user_id,
                "name": person.user_name, "scheduled_at": row.scheduled_at,
                "added_at": person.added_at, "queue_position": person.queue_position,
                "planned_games": plan, "completed_games": count["completed"],
                "occupied_games": count["occupied"], "remaining_games": remaining,
                "fresh": count["completed"] + count["occupied"] == 0,
            }
            # A player may have several reservations. One person can occupy only
            # one slot; the earlier eligible reservation is consumed first.
            by_user.setdefault(person.user_id, candidate)
    return list(by_user.values())


def _roster_ids(raw):
    try:
        roster = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if isinstance(roster, dict):
        roster = list(roster.values())
    ids = []
    for person in roster if isinstance(roster, list) else []:
        if isinstance(person, (str, int)):
            ids.append(str(person))
        elif isinstance(person, dict):
            nested = person.get("user")
            uid = person.get("user_id") or person.get("id") or (
                nested.get("id") if isinstance(nested, dict) else None)
            if uid is not None:
                ids.append(str(uid))
    return list(dict.fromkeys(ids))


def _duration(db, user_ids):
    query = select(ReservationDurationSummary).where(
        (ReservationDurationSummary.scope == "global") |
        ((ReservationDurationSummary.scope == "player") &
         ReservationDurationSummary.user_id.in_(list(user_ids) or [""])))
    summaries = {(row.scope, row.user_id): row for row in db.scalars(query)}
    global_row = summaries.get(("global", ""))
    global_average = (global_row.total_seconds / global_row.game_count
                      if global_row and global_row.game_count > 0 else None)
    if global_average is None:
        return None, "needs_configuration"
    source = "history"
    averages = []
    for user_id in user_ids:
        row = summaries.get(("player", str(user_id)))
        averages.append(row.total_seconds / row.game_count
                        if row and row.game_count > 0 else global_average)
    return round(sum(averages) / len(averages)) if averages else round(global_average), source


def _current_game(db, table_id):
    # The latest real game anchors the next batch even when an earlier game's
    # score is still pending. Round number is monotonic within a physical table.
    return db.scalar(select(GameRound).where(
        GameRound.table_id == table_id,
        GameRound.status.in_(["playing", "awaiting_score", "completed"]))
        .order_by(GameRound.round_no.desc(), GameRound.started_at.desc(),
                  GameRound.game_id.desc()).limit(1))


def _base_time(db, table_id, current):
    game = _current_game(db, table_id)
    if game is None:
        return current, None, None
    if game.actual_ended_at:
        return max(current, instant(game.actual_ended_at)), game.game_id, "actual_end"
    if game.status == "completed":
        return current, game.game_id, "confirmed_end_unknown"
    if game.status == "awaiting_score":
        return current, game.game_id, "end_unknown"
    seconds, source = _duration(db, _roster_ids(game.roster_json))
    if seconds is None:
        return None, game.game_id, source
    return max(current, instant(game.started_at) + timedelta(seconds=seconds)), game.game_id, source


def _rank(candidate, base):
    scheduled = instant(candidate["scheduled_at"])
    # Availability is a hard boundary; four currently available fresh players
    # displace continuations, while future players cannot displace today's game.
    return (
        0 if base is not None and scheduled <= base else 1,
        0 if candidate["fresh"] else 1,
        0 if candidate["queue_position"] is not None else 1,
        candidate["queue_position"] if candidate["queue_position"] is not None else 0,
        candidate["scheduled_at"], candidate["added_at"], candidate["key"],
    )


def _state(db, table_id, stamp):
    row = db.get(ReservationQueueState, table_id)
    if row is None:
        row = ReservationQueueState(table_id=table_id, version=1,
                                    ordering_json="[]", updated_at=stamp)
        db.add(row)
        db.flush()
    return row


def batch_members(db, batch_id):
    return list(db.scalars(select(ReservationQueueBatchMember).where(
        ReservationQueueBatchMember.batch_id == batch_id)
        .order_by(ReservationQueueBatchMember.position)))


def next_batch(db, table_id, now_value=None):
    """Reconcile only the next unstarted batch. Caller holds scope/table locks."""
    stamp = _stamp(now_value or now())
    current = instant(stamp)
    table = db.get(ClubTable, table_id)
    check(table is not None and table.status == "open", "table_not_found")
    state = _state(db, table_id, stamp)
    base, predecessor, base_source = _base_time(db, table_id, current)
    candidates = sorted(_candidates(db, table_id), key=lambda item: _rank(item, base))
    keys = [_key(item) for item in candidates]
    if json.loads(state.ordering_json or "[]") != keys:
        state.ordering_json = json.dumps(keys, separators=(",", ":"))
        state.version += 1
        state.updated_at = stamp
    chosen = candidates[:4]
    active = db.scalar(select(ReservationQueueBatch).where(
        ReservationQueueBatch.table_id == table_id,
        ReservationQueueBatch.status.in_(["provisional", "notified"]))
        .order_by(ReservationQueueBatch.created_at, ReservationQueueBatch.id).limit(1))
    if not chosen:
        if active is not None:
            active.status, active.updated_at = "cancelled", stamp
        db.flush()
        return None
    if active is None:
        active = ReservationQueueBatch(
            id=str(uuid4()), table_id=table_id, status="provisional", version=1,
            predecessor_game_id=predecessor, created_at=stamp, updated_at=stamp)
        db.add(active)
        db.flush()
    if predecessor is None and active.predecessor_game_id is not None:
        # Settlement may happen after All Last. Keep the already-bound
        # predecessor until a newer active game explicitly supersedes it.
        predecessor = active.predecessor_game_id
    old = [(member.reservation_id, member.user_id) for member in batch_members(db, active.id)]
    new = [(item["reservation_id"], item["user_id"]) for item in chosen]
    if old != new:
        db.execute(delete(ReservationQueueBatchMember).where(
            ReservationQueueBatchMember.batch_id == active.id))
        db.flush()
        for position, item in enumerate(chosen):
            db.add(ReservationQueueBatchMember(
                batch_id=active.id, position=position,
                reservation_id=item["reservation_id"], user_id=item["user_id"],
                user_name=item["name"],
                remaining_games_snapshot=item["remaining_games"]))
        active.version += 1
        # The notification worker uses the batch version to update/cancel stale
        # unsent recipients. A previously notified batch remains editable.
    if active.predecessor_game_id != predecessor:
        active.predecessor_game_id = predecessor
        active.version += 1
    if base is None:
        start = None
    elif len(chosen) < 4:
        start = max(base, current + timedelta(hours=1),
                    *(instant(item["scheduled_at"]) for item in chosen))
    else:
        start = max(base, *(instant(item["scheduled_at"]) for item in chosen))
    seconds, duration_source = _duration(db, [item["user_id"] for item in chosen])
    active.suggested_start_at = (start.isoformat(timespec="milliseconds")
                                 if start and len(chosen) < 4 else None)
    estimated_start = (start.isoformat(timespec="milliseconds")
                       if start and seconds is not None and len(chosen) == 4 else None)
    estimated_end = ((start + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")
                     if estimated_start else None)
    active.estimated_start_at = estimated_start
    active.estimated_end_at = estimated_end
    active.duration_seconds = seconds
    active.prediction_source = (duration_source if base_source not in
                                {"needs_configuration", "invalid_configuration"}
                                else base_source)
    active.updated_at = stamp
    db.flush()
    return active


def _summary_update(db, scope, user_id, delta_seconds, delta_count, timestamp):
    row = db.get(ReservationDurationSummary, (scope, user_id))
    if row is None:
        check(delta_count > 0, "duration_summary_missing")
        row = ReservationDurationSummary(scope=scope, user_id=user_id,
            game_count=0, total_seconds=0, updated_at=timestamp)
        db.add(row)
    row.game_count += delta_count
    row.total_seconds += delta_seconds
    check(row.game_count >= 0 and row.total_seconds >= 0, "duration_summary_corrupt")
    row.updated_at = timestamp


def _record_duration(db, game_id, timestamp):
    game = db.get(GameRound, game_id)
    if (not game or game.status != "completed" or not game.actual_ended_at
            or not game.started_at or db.get(ReservationDurationSample, game_id)):
        return
    seconds = int((instant(game.actual_ended_at) - instant(game.started_at)).total_seconds())
    if seconds <= 0:
        return
    ids = _roster_ids(game.roster_json)
    if len(ids) != 4:
        return
    db.add(ReservationDurationSample(game_id=game_id, duration_seconds=seconds,
                                     recorded_at=timestamp))
    _summary_update(db, "global", "", seconds, 1, timestamp)
    for uid in ids:
        _summary_update(db, "player", uid, seconds, 1, timestamp)


def _remove_duration(db, game_id, timestamp):
    sample = db.get(ReservationDurationSample, game_id)
    if sample is None:
        return
    game = db.get(GameRound, game_id)
    ids = _roster_ids(game.roster_json) if game else []
    _summary_update(db, "global", "", -sample.duration_seconds, -1, timestamp)
    for uid in ids:
        _summary_update(db, "player", uid, -sample.duration_seconds, -1, timestamp)
    db.delete(sample)


def _refresh_completion(db, reservation_ids, timestamp):
    rows = [db.get(TableReservation, rid) for rid in set(reservation_ids)]
    counts = _progress(db, [row.id for row in rows if row])
    affected_sessions = set()
    for row in rows:
        if row is None or row.plan_kind != "finite" or not row.planned_games:
            continue
        persons = list(db.scalars(select(ReservationParticipant).where(
            ReservationParticipant.reservation_id == row.id)))
        finished = bool(persons) and all(
            counts.get((row.id, person.user_id), {}).get("completed", 0)
            >= row.planned_games for person in persons)
        if finished and row.status == "active":
            row.status, row.updated_by, row.updated_at = "completed", "system:game", timestamp
            row.version += 1
            affected_sessions.add(row.session_id)
        elif not finished and row.status == "completed" and row.updated_by == "system:game":
            row.status, row.updated_by, row.updated_at = "active", "system:game", timestamp
            row.version += 1
            affected_sessions.add(row.session_id)
    db.flush()
    for session_id in affected_sessions:
        if session_id:
            recalculate_session(db, session_id, timestamp)


def start_batch(db, table_id, batch_id, game_id, started_at, actor_id, expected_version=None):
    """Allocate four seats to a distinct game; caller owns the encompassing transaction."""
    previous = db.get(ReservationQueueBatch, batch_id)
    if previous and previous.table_id == table_id and previous.status == "started":
        check(previous.started_game_id == game_id, "batch_already_started")
        return batch_members(db, previous.id)
    batch = next_batch(db, table_id, started_at)
    check(batch is not None and batch.id == batch_id, "stale_batch")
    check(batch.status in {"provisional", "notified"}, "batch_not_startable")
    check(expected_version is None or expected_version == batch.version, "stale_version")
    members = batch_members(db, batch.id)
    check(len(members) == 4 and len({member.user_id for member in members}) == 4,
          "batch_needs_four_players")
    counts = _progress(db, [member.reservation_id for member in members])
    for member in members:
        row = db.get(TableReservation, member.reservation_id)
        check(row is not None and row.status == "active" and row.table_id == table_id,
              "stale_batch")
        check(instant(row.scheduled_at) <= instant(started_at), "player_not_available")
        count = counts.get((row.id, member.user_id), {"completed": 0, "occupied": 0})
        check(row.plan_kind == "any" or (
            row.plan_kind == "finite" and row.planned_games is not None and
            count["completed"] + count["occupied"] < row.planned_games),
            "no_remaining_games")
        check(db.get(ReservationGameLink, (game_id, member.user_id)) is None,
              "game_already_linked")
    stamp = _stamp(started_at)
    for member in members:
        db.add(ReservationGameLink(game_id=game_id, user_id=member.user_id,
            reservation_id=member.reservation_id, batch_id=batch.id,
            status="started", linked_at=stamp, updated_at=stamp))
    batch.status, batch.started_at, batch.started_game_id = "started", stamp, game_id
    batch.updated_at = stamp
    db.flush()
    return members


def link_started_game(db, table_id, game_id, roster, started_at, actor_id):
    """Occupy matching reservations when an ordinary game starts by QR/manual joins.

    Walk-ins need no reservation. A future reservation is not consumed merely
    because its owner joined an earlier unreserved game.
    """
    ids = _roster_ids(json.dumps(roster))
    check(len(ids) == 4, "invalid_game_roster")
    stamp = _stamp(started_at)
    existing = list(db.scalars(select(ReservationGameLink).where(
        ReservationGameLink.game_id == game_id)))
    if existing:
        check({link.user_id for link in existing} <= set(ids), "game_roster_conflict")
        return existing
    batch = next_batch(db, table_id, stamp)
    members = batch_members(db, batch.id) if batch else []
    exact_batch = bool(batch and len(members) == 4 and
                       {member.user_id for member in members} == set(ids))
    candidates = {item["user_id"]: item for item in _candidates(db, table_id)}
    batch_id = batch.id if exact_batch else None
    links = []
    for uid in ids:
        item = candidates.get(uid)
        if not item or instant(item["scheduled_at"]) > instant(stamp):
            continue
        link = ReservationGameLink(game_id=game_id, user_id=uid,
            reservation_id=item["reservation_id"], batch_id=batch_id,
            status="started", linked_at=stamp, updated_at=stamp)
        db.add(link)
        links.append(link)
    if exact_batch and len(links) == 4:
        batch.status, batch.started_at, batch.started_game_id = "started", stamp, game_id
        batch.updated_at = stamp
    else:
        for link in links:
            link.batch_id = None
    db.flush()
    # The old provisional batch is reshaped against the occupied reservations
    # on the next read or worker pass. It never mutates the active game.
    return links


def on_game_confirmed(db, game_id):
    """Idempotent confirmed-game accounting, independent of upload retries."""
    stamp = now()
    links = list(db.scalars(select(ReservationGameLink).where(
        ReservationGameLink.game_id == game_id)))
    for link in links:
        link.status, link.updated_at = "confirmed", stamp
    for batch_id in {link.batch_id for link in links if link.batch_id}:
        batch=db.get(ReservationQueueBatch,batch_id)
        if batch and batch.started_game_id==game_id:
            batch.status,batch.updated_at="completed",stamp
    db.flush()
    _refresh_completion(db, [link.reservation_id for link in links], stamp)
    _record_duration(db, game_id, stamp)


def on_game_voided(db, game_id):
    """A void restores slots without deleting the game-to-reservation history."""
    stamp = now()
    links = list(db.scalars(select(ReservationGameLink).where(
        ReservationGameLink.game_id == game_id)))
    for link in links:
        link.status, link.updated_at = "void", stamp
    for batch_id in {link.batch_id for link in links if link.batch_id}:
        batch=db.get(ReservationQueueBatch,batch_id)
        if batch and batch.started_game_id==game_id:
            batch.status,batch.updated_at="cancelled",stamp
    db.flush()
    _refresh_completion(db, [link.reservation_id for link in links], stamp)
    _remove_duration(db, game_id, stamp)


def _entry(candidate):
    return {key: candidate[key] for key in (
        "key", "reservation_id", "user_id", "name", "scheduled_at",
        "planned_games", "completed_games", "occupied_games",
        "remaining_games", "fresh")}


def queue_view(db, table_id, now_value=None, can_reorder=False):
    batch = next_batch(db, table_id, now_value)
    state = db.get(ReservationQueueState, table_id)
    base, _, _ = _base_time(db, table_id, instant(now_value or now()))
    candidates = sorted(_candidates(db, table_id), key=lambda item: _rank(item, base))
    by_key = {item["key"]: item for item in candidates}
    members = batch_members(db, batch.id) if batch else []
    next_entries = [_entry(by_key[m.reservation_id + ":" + m.user_id]) for m in members
                    if m.reservation_id + ":" + m.user_id in by_key]
    next_keys = {item["key"] for item in next_entries}
    table = db.get(ClubTable, table_id)
    return {
        "table_id": table_id, "table_number": table.number, "version": state.version,
        "server_now": _stamp(now_value or now()), "can_reorder": can_reorder,
        "ordered_keys": [item["key"] for item in candidates],
        "next_batch": ({
            "id": batch.id, "status": batch.status, "version": batch.version,
            "predecessor_game_id": batch.predecessor_game_id,
            "estimated_start_at": batch.estimated_start_at,
            "suggested_start_at": batch.suggested_start_at,
            "estimated_end_at": batch.estimated_end_at,
            "duration_seconds": batch.duration_seconds,
            "prediction_source": batch.prediction_source,
            "missing_players": max(0, 4 - len(next_entries)),
            "participants": next_entries,
        } if batch else None),
        "waiting": [_entry(item) for item in candidates if item["key"] not in next_keys],
        "batches": [],
    }


def reorder(db, table_id, actor_id, expected_version, ordered_keys, now_value=None):
    """Version checked full permutation; no seat or started-game mutation."""
    stamp = _stamp(now_value or now())
    before_view = queue_view(db, table_id, stamp, True)
    check(type(expected_version) is int and expected_version == before_view["version"],
          "stale_version")
    old = before_view["ordered_keys"]
    check(isinstance(ordered_keys, list) and len(ordered_keys) == len(old) and
          all(isinstance(key, str) for key in ordered_keys) and
          len(set(ordered_keys)) == len(old) and set(ordered_keys) == set(old),
          "invalid_queue_order")
    if ordered_keys == old:
        return before_view
    # The planner's hard availability and fresh-player priorities are checked
    # after assigning manual positions; invalid cross-boundary moves roll back.
    people = list(db.scalars(select(ReservationParticipant).where(
        ReservationParticipant.reservation_id.in_([key.split(":", 1)[0]
                                                   for key in ordered_keys]))))
    lookup = {person.reservation_id + ":" + person.user_id: person for person in people}
    for position, key in enumerate(ordered_keys):
        lookup[key].queue_position = position
    db.flush()
    view = queue_view(db, table_id, stamp, True)
    check(view["ordered_keys"] == ordered_keys, "invalid_queue_order")
    state = db.get(ReservationQueueState, table_id)
    # queue_view already increments on changed ordering.
    db.add(ReservationQueueAudit(id=str(uuid4()), table_id=table_id,
        actor_id=str(actor_id), before_json=json.dumps(old), after_json=json.dumps(ordered_keys),
        at=stamp))
    db.flush()
    return view
