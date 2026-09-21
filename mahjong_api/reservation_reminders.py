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
    with service.store.connect() as db:
        _table(service, db, table_id)
    return get_next_whole_hour(service.clock(), service.timezone)


def reservation_reminders(service, table_id, user):
    """One row per logical session, inclusive from earliest start -1h to max end."""
    from .reservation_session_models import ReservationSession
    check(user is not None, "not_authenticated")
    current = _utc(service.clock())
    window = timedelta(seconds=WINDOW_SECONDS)
    reminders, changes = [], []
    with membership_lock, service.store.connect() as db:
        table = _table(service, db, table_id)
        check(not table.tournament_id, "fixed_tournament_seating")
        table_id, score_table_id, table_number = table.id, table.score_table_id, table.number
        sessions = list(db.scalars(select(ReservationSession).where(
            ReservationSession.table_id == table.id, ReservationSession.status == "active")
            .order_by(ReservationSession.start_at, ReservationSession.id)))
        members = {member.user_id: member for member in db.scalars(select(ActiveTableMember).where(
            ActiveTableMember.table_id == table.id, ActiveTableMember.status == "active",
            ActiveTableMember.left_at.is_(None)))}
        for session in sessions:
            start, end = _utc(session.start_at), _utc(session.end_at)
            if start-window > current:
                changes.append(start-window)
            if start-window <= current <= end:
                row = service._reservation_session(db, session)
                # Persisted sessions may outlive cancelled individual records;
                # no empty session is presented even during administrative repair.
                if not row["participants"]:
                    continue
                changes.append(end+timedelta(milliseconds=1))
                for person in row["participants"]:
                    member = members.get(person["user_id"])
                    person.update(seated=member is not None, seat=member.seat if member else None)
                row.update(expires_at=session.end_at,
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
