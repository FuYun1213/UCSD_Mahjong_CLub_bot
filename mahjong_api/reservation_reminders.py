"""Server-clock reservation defaults and read-only, stable-identity reminders."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from .store import Conflict
from .table_membership import check, membership_lock
from .table_models import ActiveTableMember, ClubTable, ReservationParticipant, TableReservation
from .table_service import utc_value

WINDOW_SECONDS = 3600


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise Conflict("invalid_site_timezone", "invalid_site_timezone") from None


def _utc(value):
    if isinstance(value, datetime):
        value = value.isoformat()
    return datetime.fromisoformat(utc_value(value))


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _local_fields(value, zone):
    local = value.astimezone(zone)
    return {"local_month": local.month, "local_day": local.day,
            "local_time": local.strftime("%H:%M")}


def get_next_whole_hour(now, configured_timezone):
    """First real local HH:00 strictly after now, preserving DST fold as an instant.

    Consider both folds, discard nonexistent wall times by round-trip, and compare
    in UTC. A repeated autumn hour is valid; the form submits its exact instant
    until the user edits a date field. No browser timezone or inferred year is used.
    """
    current = _utc(now)
    zone = _zone(configured_timezone)
    base = current.astimezone(zone).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    candidates = []
    # Include the current wall hour: its second fold may still be in the future.
    # Two days also cover the uncommon IANA transitions that skip an entire date.
    for hour in range(49):
        wall = base + timedelta(hours=hour)
        for fold in (0, 1):
            local = wall.replace(tzinfo=zone, fold=fold)
            instant = local.astimezone(timezone.utc)
            if (instant > current and
                    instant.astimezone(zone).replace(tzinfo=None) == wall):
                candidates.append(instant)
    check(bool(candidates), "invalid_reservation_time")
    scheduled = min(candidates)
    end = scheduled + timedelta(hours=1)
    return {"scheduled_at": _stamp(scheduled), "start_at": _stamp(scheduled), "end_at": _stamp(end),
            "server_now": _stamp(current), "timezone": configured_timezone,
            **_local_fields(scheduled, zone),
            **{"end_"+key:value for key,value in _local_fields(end,zone).items()}}



def _table(service, db, table_id):
    # The embedded Game Record retains its legacy score-table key. Both entry
    # forms resolve exactly to the same registry row, as in the seating APIs.
    table = db.get(ClubTable, table_id) or db.scalar(select(ClubTable).where(
        ClubTable.score_table_id == table_id))
    return service._table(db, table.id if table else "")


def reservation_default(service, table_id, user):
    check(user is not None, "not_authenticated")
    from .reservation_queue import batch_members, next_batch
    from .reservation_sessions import lock_scope
    from .table_membership import lock_table
    current = _utc(service.clock())
    with membership_lock, service.store.connect() as db:
        table = _table(service, db, table_id)
        lock_scope(db, table.scope); lock_table(db, table.id)
        batch = next_batch(db, table.id, current)
        count = len(batch_members(db, batch.id)) if batch else 0
        suggestion = (_utc(batch.suggested_start_at) if batch and count < 4
                      and batch.suggested_start_at else
                      _utc(batch.estimated_start_at) if batch and batch.estimated_start_at
                      else current + timedelta(hours=1) if count < 4 else None)
        missing = max(0, 4-count)
        source = batch.prediction_source if batch else "insufficient_players"
    result = {"scheduled_at": _stamp(suggestion) if suggestion else None,
              "start_at": _stamp(suggestion) if suggestion else None,
              "end_at": _stamp(suggestion + timedelta(hours=1)) if suggestion else None,
              "server_now": _stamp(current), "timezone": service.timezone,
              "missing_players": missing,
              "estimated": bool(batch and count == 4 and batch.estimated_start_at),
              "suggestion": missing > 0,
              "prediction_source": source}
    if suggestion:
        result.update(_local_fields(suggestion, _zone(service.timezone)))
        result.update({"end_"+key:value for key,value in
                       _local_fields(suggestion+timedelta(hours=1),_zone(service.timezone)).items()})
    return result


def reservation_reminders(service, table_id, user):
    """Show active session participants beginning one hour before their start."""
    from .reservation_session_models import ReservationSession
    check(user is not None, "not_authenticated")
    current = _utc(service.clock())
    window = timedelta(seconds=WINDOW_SECONDS)
    reminders, changes = [], []
    with membership_lock, service.store.connect() as db:
        table = _table(service, db, table_id)
        check(not table.tournament_id, "fixed_tournament_seating")
        table_id, score_table_id, table_number = table.id, table.score_table_id, table.number
        sessions = list(db.scalars(select(ReservationSession).join(
            TableReservation, TableReservation.session_id == ReservationSession.id).where(
            ReservationSession.table_id == table.id,
            ReservationSession.status == "active",
            TableReservation.status == "active",
            TableReservation.plan_kind.in_(["finite","any"]),
            ReservationSession.start_at <= _stamp(current + window))
            .distinct().order_by(ReservationSession.start_at, ReservationSession.id)))
        next_start = db.scalar(select(ReservationSession.start_at).where(
            ReservationSession.table_id == table.id, ReservationSession.status == "active",
            ReservationSession.start_at > _stamp(current + window))
            .order_by(ReservationSession.start_at).limit(1))
        if next_start:
            changes.append(_utc(next_start)-window)
        members = {member.user_id: member for member in db.scalars(select(ActiveTableMember).where(
            ActiveTableMember.table_id == table.id, ActiveTableMember.status == "active",
            ActiveTableMember.left_at.is_(None)))}
        for session in sessions:
            start, end = _utc(session.start_at), _utc(session.end_at)
            if start-window > current:
                changes.append(start-window)
            if start-window <= current:
                row = service._reservation_session(db, session)
                # Persisted sessions may outlive cancelled individual records;
                # no empty session is presented even during administrative repair.
                if not row["participants"]:
                    continue
                for person in row["participants"]:
                    member = members.get(person["user_id"])
                    person.update(seated=member is not None, seat=member.seat if member else None)
                row.update(expires_at=None,
                    all_seated=all(person["seated"] for person in row["participants"]))
                reminders.append(row)
    # Current registration/avatar projection happens outside the score DB read
    # transaction, preserving the existing account-store lock order.
    reminders = service.display_names(reminders)
    return {"table_id": table_id, "score_table_id": score_table_id, "table_number": table_number,
            "server_now": _stamp(current), "timezone": service.timezone,
            "window_seconds": WINDOW_SECONDS,
            "next_change_at": _stamp(min(changes)) if changes else None,
            "reminders": reminders}
