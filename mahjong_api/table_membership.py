"""One transactional membership policy for ordinary seats and tournament check-ins."""
import json
from request_performance import TimedRLock
from uuid import uuid4, uuid5, NAMESPACE_URL
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from .database_models import TableState, SeatRecord, User as Account, ScoreDraft
from .table_models import ClubTable, ActiveTableMember, TableMembershipEvent
from .tournament_models import Tournament, TournamentTableSession
from .models import SEATS
from .store import Conflict, now

membership_lock = TimedRLock('memberLockWaitMs')


def check(condition, code):
    if not condition:
        raise Conflict(code, code)


def admin(user):
    check(user is not None and user.role in {"admin", "super_admin"}, "admin_required")


def table_open(db, table):
    check(table is not None, "table_not_found")
    check(table.status == "open", "table_closed")
    if table.tournament_id:
        tournament = db.get(Tournament, table.tournament_id)
        check(tournament is not None and not tournament.deleted_at, "tournament_deleted")
    return table


def register_ordinary(db, score_table, number=None):
    table = db.scalar(select(ClubTable).where(ClubTable.score_table_id == score_table.table_id))
    if table:
        return table
    used = set(db.scalars(select(ClubTable.number).where(ClubTable.scope == "venue:club")))
    candidate = int(score_table.table_id) if score_table.table_id.isdigit() and int(score_table.table_id) > 0 else 1
    while candidate in used:
        candidate += 1
    table = ClubTable(id=str(uuid5(NAMESPACE_URL, "mahjong:legacy-table:" + score_table.table_id)),
        scope="venue:club", score_table_id=score_table.table_id, number=number or candidate,
        display_name="", status="open", capacity=4, created_at=score_table.updated_at,
        created_by="migration", nfc_configured=0, nfc_label="")
    db.add(table)
    db.flush()
    return table


def register_tournament_table(db, tid, table, capacity=4, timestamp=None):
    row = db.get(ClubTable, table["table_id"])
    if row is None:
        row = ClubTable(id=table["table_id"], scope="tournament:" + tid, tournament_id=tid,
            number=table["number"], display_name="", status="open", capacity=capacity,
            created_at=timestamp or now(), created_by="tournament", nfc_configured=0, nfc_label="")
        db.add(row)
        db.flush()
    return row


def event(db, table_id, match_id, uid, actor, action, method, timestamp, reason="", seat=None):
    db.add(TableMembershipEvent(id=str(uuid4()), table_id=table_id, match_id=match_id,
        user_id=str(uid), actor_id=str(actor), action=action, join_method=method,
        at=timestamp, reason=reason, seat=seat))


def lock_table(db, table_id):
    """Serialize physical-table writers across workers, including SQLite."""
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(ClubTable).where(ClubTable.id == table_id).values(status=ClubTable.status))
    else:
        db.execute(select(ClubTable.id).where(ClubTable.id == table_id).with_for_update())


def assigned_tournament_seat(db, table, match_id, user_id):
    session = db.get(TournamentTableSession, match_id)
    check(session is not None, "not_assigned")
    state = json.loads(db.get(Tournament, table.tournament_id).state_json)
    player = next((p["id"] for p in state["players"] if str(p.get("account_id") or p["id"]) == str(user_id)), None)
    roster = json.loads(session.roster_json)
    check(player in roster, "not_assigned")
    index = roster.index(player)
    return SEATS[index] if index < len(SEATS) else None


def claim_member(db, table, match_id, user, actor, method, timestamp=None, seat=None):
    table_open(db, table)
    lock_table(db, table.id)
    db.refresh(table)
    table_open(db, table)
    check(method in {"qr", "qr_entry", "qr_east", "qr_south", "qr_west", "qr_north", "nfc", "manual", "manual_id", "registered_name", "seat_card", "admin"}, "invalid_join_method")
    if table.tournament_id:
        assigned = assigned_tournament_seat(db, table, match_id, user.id)
        check(seat is None or seat == assigned, "seat_not_assigned")
        seat = assigned
        if method.startswith("qr_") and method != "qr_entry":
            check(method[3:] == assigned, "seat_not_assigned")
    check(seat is None or seat in SEATS, "invalid_seat")
    timestamp = timestamp or now()
    existing = db.get(ActiveTableMember, str(user.id))
    if existing:
        check(existing.table_id == table.id and existing.match_id == match_id, "already_at_other_table")
        if method.startswith("qr_") and seat is not None:
            check(existing.seat == seat, "already_at_other_seat")
        if seat is not None and existing.seat != seat:
            from .seat_swap_state import invalidate_swaps
            invalidate_swaps(db, table.id, user_ids=[user.id], reason="seat_changed", actor=actor, timestamp=timestamp)
            existing.seat = seat
            existing.seat_version += 1
        return existing, False
    if seat is not None:
        check(not db.scalar(select(ActiveTableMember.user_id).where(ActiveTableMember.table_id == table.id, ActiveTableMember.seat == seat)), "seat_occupied")
    count = db.scalar(select(func.count()).select_from(ActiveTableMember).where(ActiveTableMember.table_id == table.id))
    check(count < table.capacity, "table_full")
    row = ActiveTableMember(user_id=str(user.id), table_id=table.id, match_id=match_id,
        joined_at=timestamp, join_method=method, added_by_user_id=str(actor), seat=seat)
    try:
        with db.begin_nested():
            # An atomic upsert also serializes simultaneous first joins by the
            # same account across different PostgreSQL table-row locks.
            if db.get_bind().dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert
            db.execute(insert(Account).values(id=str(user.id), name=user.name)
                .on_conflict_do_update(index_elements=[Account.id], set_={"name": user.name}))
            db.add(row)
            event(db, table.id, match_id, user.id, actor, "joined", method, timestamp, seat=seat)
            db.flush()
    except IntegrityError:
        existing = db.get(ActiveTableMember, str(user.id))
        if existing:
            check(existing.table_id == table.id and existing.match_id == match_id, "already_at_other_table")
            check(existing.seat == seat, "already_at_other_seat")
            return existing, False
        raise Conflict("seat_occupied", "seat_occupied") from None
    return row, True


def release_member(db, row, actor, reason, timestamp=None, action="left"):
    from .seat_swap_state import invalidate_swaps
    invalidate_swaps(db, row.table_id, user_ids=[row.user_id], reason="member_left", actor=actor, timestamp=timestamp)
    event(db, row.table_id, row.match_id, row.user_id, actor, action, row.join_method, timestamp or now(), reason, seat=row.seat)
    db.delete(row)
    db.flush()


def release_table(db, table_id, actor, reason, match_id=None):
    query = select(ActiveTableMember).where(ActiveTableMember.table_id == table_id)
    if match_id:
        query = query.where(ActiveTableMember.match_id == match_id)
    for row in list(db.scalars(query)):
        release_member(db, row, actor, reason)


def ordinary_join(db, score_table, user, actor, method, seat=None):
    table = table_open(db, register_ordinary(db, score_table))
    lock_table(db, table.id)
    db.refresh(table)
    table_open(db, table)
    db.refresh(score_table)
    check(not score_table.pending_match_id, "settlement_pending")
    previous = db.scalar(select(SeatRecord).where(SeatRecord.user_id == str(user.id)))
    if previous:
        check(previous.table_id == score_table.table_id, "already_at_other_table")
        if method.startswith("qr_") and seat is not None:
            check(previous.seat == seat, "already_at_other_seat")
        if score_table.started_at or seat is None or seat == previous.seat:
            claim_member(db, table, score_table.current_match_id, user, actor, method, seat=previous.seat)
            return previous.seat
    if not method.startswith("qr_"):
        check(score_table.started_at is None, "table_already_started")
    occupied = {x.seat: x for x in db.scalars(select(SeatRecord).where(SeatRecord.table_id == score_table.table_id))}
    if seat is None:
        seat = next((s for s in SEATS if s not in occupied), None)
    check(seat in SEATS, "table_full")
    check(seat not in occupied or occupied[seat].user_id == str(user.id), "seat_occupied")
    check(score_table.started_at is None, "table_already_started")
    if method == "admin" or str(actor) != str(user.id):
        from .seat_swap_state import invalidate_swaps
        invalidate_swaps(db, table.id, reason="admin_membership_changed", actor=actor)
    claim_member(db, table, score_table.current_match_id, user, actor, method, seat=seat)
    if previous:
        db.delete(previous)
        db.flush()
    db.add(SeatRecord(table_id=score_table.table_id, seat=seat, user_id=str(user.id), user_name=user.name))
    db.flush()
    score_table.updated_at, score_table.dirty = now(), 0
    if db.scalar(select(func.count()).select_from(SeatRecord).where(SeatRecord.table_id == score_table.table_id)) == 4:
        score_table.started_at = score_table.updated_at
        from .seat_swap_state import invalidate_swaps
        invalidate_swaps(db, table.id, reason="table_already_started", actor=actor, timestamp=score_table.updated_at)
        from .game_flow import ensure_game_round
        ensure_game_round(db, table, score_table,
                          timestamp=score_table.started_at, actor_id=actor)
    return seat


def ordinary_set_my_seat(db, table, user, seat, expected_match_id=None, join_method="seat_card"):
    """Claim or move only the authenticated user, committing both seat models together.

    No leave is performed. The table lock serializes wind claims across workers;
    existing relational unique constraints also protect direct database writes.
    """
    check(isinstance(seat, str) and seat in SEATS, "invalid_seat")
    table_open(db, table)
    lock_table(db, table.id)
    db.refresh(table)
    table_open(db, table)
    check(not table.tournament_id, "fixed_tournament_seating")
    score = db.scalar(select(TableState).where(TableState.table_id == table.score_table_id))
    check(score is not None, "table_not_found")
    check(expected_match_id is None or expected_match_id == score.current_match_id, "stale_match")
    uid = str(user.id)
    member = db.get(ActiveTableMember, uid)
    previous = db.scalar(select(SeatRecord).where(SeatRecord.user_id == uid))
    check(member is None or member.table_id == table.id and member.match_id == score.current_match_id, "already_at_other_table")
    check(previous is None or previous.table_id == score.table_id, "already_at_other_table")
    target = db.get(SeatRecord, (score.table_id, seat))
    check(target is None or target.user_id == uid, "seat_occupied")
    if previous is not None and previous.seat == seat:
        # Same-wind clicks are true no-ops, including after the game has begun.
        # Preserve original joined_at/source and never emit a leave/join pair.
        return "unchanged", seat
    check(score.started_at is None, "table_already_started")
    check(not score.pending_match_id, "settlement_pending")
    check(not db.scalar(select(ScoreDraft.id).where(ScoreDraft.match_id == score.current_match_id,
        ScoreDraft.status.in_(["review", "submitted"]))), "score_exists")
    if previous is None:
        ordinary_join(db, score, user, uid, join_method, seat)
        return "joined", None
    old_seat = previous.seat
    check(member is not None and member.seat == old_seat, "membership_conflict")
    stamp = now()
    # Updating the existing rows keeps one membership and preserves its source.
    # Both wind changes and their audit event roll back if any constraint fails.
    try:
        with db.begin_nested():
            from .seat_swap_state import invalidate_swaps
            invalidate_swaps(db, table.id, user_ids=[uid], reason="seat_changed", actor=uid, timestamp=stamp)
            member.seat = seat
            member.seat_version += 1
            previous.seat = seat
            event(db, table.id, score.current_match_id, uid, uid, "seat_changed", "seat_card", stamp,
                  json.dumps({"from_seat": old_seat, "to_seat": seat}, sort_keys=True), seat=seat)
            db.flush()
    except IntegrityError:
        raise Conflict("seat_occupied", "seat_occupied") from None
    score.updated_at, score.dirty = stamp, 0
    return "moved", old_seat


def ordinary_leave(db, table, user, reason="voluntary", expected_match_id=None):
    table_open(db, table)
    check(not table.tournament_id, "fixed_tournament_seating")
    lock_table(db, table.id)
    db.refresh(table)
    table_open(db, table)
    score = db.scalar(select(TableState).where(TableState.table_id == table.score_table_id))
    row = db.get(ActiveTableMember, str(user.id))
    if row is None or row.table_id != table.id:
        return False
    check(score is not None, "table_not_found")
    check(expected_match_id is None or expected_match_id == score.current_match_id, "stale_match")
    check(score.started_at is None, "cannot_leave_started")
    check(not score.pending_match_id and not db.scalar(select(ScoreDraft.id).where(
        ScoreDraft.match_id == score.current_match_id, ScoreDraft.status.in_(["review", "submitted"]))), "score_exists")
    seat = db.scalar(select(SeatRecord).where(SeatRecord.user_id == str(user.id), SeatRecord.table_id == table.score_table_id))
    if seat:
        db.delete(seat)
    release_member(db, row, user.id, reason)
    score.updated_at, score.dirty = now(), 0
    return True
