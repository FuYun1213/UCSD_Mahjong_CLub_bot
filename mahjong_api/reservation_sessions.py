"""Session grouping: bounded start span, stable ranking and one scope transaction."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select, update
from .reservation_session_models import ReservationScopeLock, ReservationSession
from .table_models import ClubTable, TableReservation, ReservationParticipant


def instant(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def lock_scope(db, scope):
    """All reservation writers and Discord senders acquire this before table locks.

    The row survives process restarts. The no-op SQLite UPDATE acquires the writer
    lock; PostgreSQL uses FOR UPDATE. No process-local lock is the correctness gate.
    """
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(ReservationScopeLock).values(scope=scope).on_conflict_do_nothing())
    if db.bind.dialect.name == "sqlite":
        db.execute(update(ReservationScopeLock).where(ReservationScopeLock.scope == scope).values(scope=scope))
    else:
        db.scalar(select(ReservationScopeLock).where(ReservationScopeLock.scope == scope).with_for_update())


def active_reservations(db, session_id, exclude_id=None):
    query = select(TableReservation).where(TableReservation.session_id == session_id,
                                           TableReservation.status == "active")
    if exclude_id:
        query = query.where(TableReservation.id != exclude_id)
    return list(db.scalars(query.order_by(TableReservation.scheduled_at, TableReservation.id)))


def reservation_participants(db, rows):
    ids = [r.id for r in rows]
    by_reservation = {}
    if ids:
        for person in db.scalars(select(ReservationParticipant).where(
                ReservationParticipant.reservation_id.in_(ids)).order_by(
                    ReservationParticipant.added_at, ReservationParticipant.user_id)):
            by_reservation.setdefault(person.reservation_id, []).append(
                {"id": person.user_id, "user_id": person.user_id, "name": person.user_name})
    return {r.id: by_reservation.get(r.id) or [{"id":r.user_id,"user_id":r.user_id,"name":r.user_name}]
            for r in rows}


def session_participants(db, session_id, exclude_id=None):
    """Stable-ID union of participants on active individual reservations only."""
    rows = active_reservations(db, session_id, exclude_id)
    from .reservation_queue import participant_progress
    progress=participant_progress(db,rows)
    groups=reservation_participants(db,rows)
    people = {}
    for row in rows:
        for person in groups[row.id]:
            count=progress.get((row.id,person["user_id"]),{"completed":0,"occupied":0})
            if row.plan_kind=="finite" and row.planned_games is not None and (
                    count["completed"]+count["occupied"] >= row.planned_games):
                continue
            if row.plan_kind=="legacy_unknown":
                # Legacy rows remain visible as history, not speculative queue slots.
                continue
            people.setdefault(person["user_id"], person)
    return list(people.values())


def recalculate_session(db, session_id, timestamp):
    session = db.get(ReservationSession, session_id)
    if not session:
        return None
    rows = active_reservations(db, session_id)
    session.status = "active" if rows else "cancelled"
    if rows:
        session.start_at = min(row.scheduled_at for row in rows)
        session.end_at = max(row.end_at for row in rows)
    session.updated_at = timestamp
    db.flush()
    return session


def fits_session(db, session, start_at, participant_ids, capacity, exclude_id=None):
    rows = active_reservations(db, session.id, exclude_id)
    starts = [instant(row.scheduled_at) for row in rows] + [instant(start_at)]
    ids = {person["user_id"] for person in session_participants(db, session.id, exclude_id)}
    ids.update(participant_ids)
    return ((max(starts) - min(starts)).total_seconds() <= 3600 and len(ids) <= capacity)


def candidates(db, scope, start_at, participant_ids, table_id=None, exclude_id=None):
    requested=instant(start_at)
    lower=(requested-timedelta(hours=1)).isoformat(timespec="milliseconds")
    upper=(requested+timedelta(hours=1)).isoformat(timespec="milliseconds")
    query = select(ReservationSession).join(ClubTable).where(ReservationSession.scope == scope,
        ReservationSession.status == "active", ReservationSession.start_at.between(lower,upper),
        ClubTable.status == "open")
    if table_id:
        query = query.where(ReservationSession.table_id == table_id)
    result = []
    for session in db.scalars(query):
        table = db.get(ClubTable, session.table_id)
        if table.tournament_id:
            from .tournament_models import Tournament
            tournament = db.get(Tournament, table.tournament_id)
            if tournament is None or tournament.deleted_at:
                continue
        if fits_session(db, session, start_at, participant_ids, table.capacity, exclude_id):
            people = session_participants(db, session.id, exclude_id)
            remaining = table.capacity - len({p["user_id"] for p in people})
            result.append((session, remaining))
    result.sort(key=lambda pair: (abs((instant(start_at)-instant(pair[0].start_at)).total_seconds()),
        -pair[1], pair[0].created_at, pair[0].id))
    return [session for session, _ in result]


def assign_session(db, row, table, timestamp, previous_session_id=None):
    """Move only this row, retaining its owner, original time and participants."""
    people = [p["user_id"] for p in reservation_participants(db, [row])[row.id]]
    previous = db.get(ReservationSession, previous_session_id) if previous_session_id else None
    if (previous and previous.table_id == table.id and previous.scope == table.scope and
            fits_session(db, previous, row.scheduled_at, people, table.capacity, row.id)):
        chosen = previous
    else:
        choices = candidates(db, table.scope, row.scheduled_at, people, table.id, row.id)
        chosen = choices[0] if choices else None
    if chosen is None:
        chosen = ReservationSession(id=str(uuid4()), scope=table.scope, table_id=table.id,
            start_at=row.scheduled_at, end_at=row.end_at, status="active",
            created_at=timestamp, updated_at=timestamp)
        db.add(chosen)
        db.flush()
    row.session_id = chosen.id
    db.flush()
    if previous_session_id and previous_session_id != chosen.id:
        recalculate_session(db, previous_session_id, timestamp)
    recalculate_session(db, chosen.id, timestamp)
    return chosen
