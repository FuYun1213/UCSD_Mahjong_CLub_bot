"""Reservation range parsing and transactional individual-record/session writes."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4
from sqlalchemy import func, select
from .table_models import ClubTable, TableReservation
from .table_membership import check, admin, table_open, lock_table, membership_lock
from .reservation_sessions import lock_scope, assign_session, recalculate_session, instant, candidates
from .external_sync import audit


def range_values(service, data, previous=None):
    source = dict(data)
    if "start_at" in source:
        source["scheduled_at"] = source["start_at"]
    start = service.reservation_time(source, previous.scheduled_at if previous else None)
    check(start is not None, "invalid_reservation_time")
    if "end_at" in data:
        from .table_service import utc_value
        end = utc_value(data["end_at"])
    elif any(key in data for key in ("end_month", "end_day", "end_time")):
        zone = ZoneInfo(service.timezone)
        local_start = instant(start).astimezone(zone)
        month, day = data.get("end_month"), data.get("end_day")
        check(type(month) is int and type(day) is int, "invalid_reservation_time")
        year = local_start.year + int((month,day) < (local_start.month,local_start.day))
        # Reuse DST and wall-time validation, with explicit local-year anchor.
        anchor = datetime(year,1,1,tzinfo=zone).astimezone(timezone.utc).isoformat()
        end = service.reservation_time({"month":month,"day":day,"time":data.get("end_time")}, anchor)
    elif previous:
        # The new form has no end-time input. When its start changes, move the
        # deprecated compatibility window too; the prior value remains in the
        # reservation update audit instead of blocking a valid edit.
        end = ((instant(start)+timedelta(hours=1)).isoformat(timespec="milliseconds")
               if instant(start) != instant(previous.scheduled_at)
               and previous.plan_kind in {"finite","any"} else previous.end_at)
    else:
        end = (instant(start)+timedelta(hours=1)).isoformat(timespec="milliseconds")
    check(instant(end) > instant(start), "invalid_reservation_end")
    return start, end


def planned_value(data, previous=None):
    if "planned_games" not in data:
        return (previous.plan_kind, previous.planned_games) if previous else ("finite", 1)
    value = data["planned_games"]
    if value == "any":
        return "any", None
    check(type(value) is int and value > 0, "invalid_planned_games")
    return "finite", value


def resolve_table(service, db, table_id):
    table = db.get(ClubTable,table_id) or db.scalar(select(ClubTable).where(ClubTable.score_table_id==table_id))
    check(table is not None,"table_not_found")
    return table


def reserve(service, table_id, data, user):
    check(user is not None,"not_authenticated")
    start, end = range_values(service,data)
    plan_kind, planned_games = planned_value(data)
    note = data.get("note","")
    check(isinstance(note,str) and len(note)<=500,"invalid_note")
    check("seat" not in data and "user_id" not in data,"invalid_reservation")
    profiles = service._reservation_profiles(data.get("participant_ids"),user)
    with membership_lock, service.store.connect() as db:
        table = resolve_table(service,db,table_id)
        lock_scope(db,table.scope); lock_table(db,table.id); db.refresh(table); table_open(db,table)
        key,fingerprint,old = service._command(db,user,"reserve:"+table_id,data)
        if old:
            return service._reservation(db,db.get(TableReservation,old.result_id))
        check(1<=len(profiles)<=table.capacity,"reservation_capacity_exceeded")
        stamp = service.clock()
        row = TableReservation(id=str(uuid4()),table_id=table.id,user_id=str(user.id),user_name=user.name,
            scheduled_at=start,end_at=end,plan_kind=plan_kind,planned_games=planned_games,
            created_at=stamp,updated_at=stamp,updated_by=str(user.id),
            status="active",note=note,version=1)
        db.add(row); db.flush()
        service._store_participants(db,row,profiles,stamp)
        assign_session(db,row,table,stamp)
        from .reservation_queue import next_batch
        next_batch(db,table.id,stamp)
        service._remember(db,key,fingerprint,row.id)
        audit(db,table.tournament_id or "",user.id,"table_reservation_created",
            {"table_id":table.id,"reservation_id":row.id,"session_id":row.session_id,
             "scheduled_at":start,"end_at":end,"planned_games":data.get("planned_games",1),
             "participant_ids":[p["id"] for p in profiles]})
        return service._reservation(db,row)


def update_reservation(service,reservation_id,data,user):
    check(user is not None,"not_authenticated")
    check("seat" not in data and "user_id" not in data,"invalid_reservation")
    profiles = service._reservation_profiles(data["participant_ids"],user) if "participant_ids" in data else None
    with membership_lock, service.store.connect() as db:
        row = db.get(TableReservation,reservation_id)
        check(row is not None,"not_found")
        original_table = resolve_table(service,db,row.table_id)
        target = resolve_table(service,db,data.get("table_id",row.table_id))
        for scope in sorted({original_table.scope,target.scope}):
            lock_scope(db,scope)
        # A concurrent edit may have moved the row to another scope before the
        # lock. Version guards reject that edit rather than touching an unlocked scope.
        db.refresh(row)
        check(row.table_id == original_table.id,"stale_version")
        for tid in sorted({original_table.id,target.id}):
            lock_table(db,tid)
        db.refresh(target)
        check(str(user.id)==row.user_id or user.role in {"admin","super_admin"},"reservation_not_owner")
        status=data.get("status",row.status)
        check(status in {"active","cancelled","completed"},"invalid_state")
        if row.status==status and status!="active" and set(data)<={"status","version"}:
            return service._reservation(db,row)
        check(row.status=="active","reservation_not_active")
        check(type(data.get("version")) is int,"reservation_version_required")
        check(data["version"]==row.version,"stale_version")
        # Completion is derived only from a confirmed linked game.
        check(status!="completed", "score_confirmation_required")
        if status=="active":
            table_open(db,target)
        start,end=range_values(service,data,row)
        if row.plan_kind == "legacy_unknown" and "planned_games" in data:
            admin(user)
        plan_kind,planned_games=planned_value(data,row)
        if plan_kind == "finite":
            from .reservation_queue import participant_progress
            counts=participant_progress(db,[row])
            from .reservation_sessions import reservation_participants
            existing_people=reservation_participants(db,[row])[row.id]
            check(all(counts.get((row.id,p["user_id"]),{}).get("completed",0)
                      +counts.get((row.id,p["user_id"]),{}).get("occupied",0)
                      <=planned_games for p in existing_people), "planned_games_below_progress")
        note=data.get("note",row.note)
        check(isinstance(note,str) and len(note)<=500,"invalid_note")
        before=service._reservation(db,row)
        if profiles is None:
            from .reservation_sessions import reservation_participants
            profiles=reservation_participants(db,[row])[row.id]
        check(1<=len(profiles)<=target.capacity,"reservation_capacity_exceeded")
        old_session_id=row.session_id
        row.scheduled_at,row.end_at,row.table_id=start,end,target.id
        row.plan_kind,row.planned_games=plan_kind,planned_games
        row.status,row.note,row.version=status,note,row.version+1
        row.updated_at,row.updated_by=service.clock(),str(user.id)
        if status=="cancelled":
            row.cancelled_at,row.cancelled_by=row.updated_at,str(user.id)
        if "participant_ids" in data:
            service._store_participants(db,row,profiles,row.updated_at)
        else:
            db.flush()
        if target.id != original_table.id:
            from .table_models import ReservationParticipant
            persons=list(db.scalars(select(ReservationParticipant).where(
                ReservationParticipant.reservation_id==row.id)
                .order_by(ReservationParticipant.queue_position,
                          ReservationParticipant.added_at,ReservationParticipant.user_id)))
            last=db.scalar(select(func.max(ReservationParticipant.queue_position))
                .join(TableReservation,TableReservation.id==ReservationParticipant.reservation_id)
                .where(TableReservation.table_id==target.id,
                       ReservationParticipant.reservation_id!=row.id))
            position=0 if last is None else last+1
            for person in persons:
                person.queue_position=position
                position+=1
            db.flush()
        if status=="active":
            assign_session(db,row,target,row.updated_at,old_session_id)
        elif old_session_id:
            recalculate_session(db,old_session_id,row.updated_at)
        from .reservation_queue import next_batch
        for affected in sorted({original_table.id,target.id}):
            next_batch(db,affected,row.updated_at)
        after=service._reservation(db,row)
        audit(db,target.tournament_id or "",user.id,"table_reservation_updated",
            {"reservation_id":row.id,"before":before,"after":after})
        return after


def reservation_candidates(service,table_id,data,user):
    check(user is not None,"not_authenticated")
    source=dict(data)
    if "start_at" in source:
        source["scheduled_at"]=source["start_at"]
    start=service.reservation_time(source,data.get("reference_start"))
    check(start is not None,"invalid_reservation_time")
    profiles=service._reservation_profiles(data.get("participant_ids"),user)
    from .reservation_reminders import _local_fields, _stamp, _zone, _utc
    end=instant(start)+timedelta(hours=1)
    with service.store.connect() as db:
        table=resolve_table(service,db,table_id)
        table_open(db,table)
        rows=candidates(db,table.scope,start,[p["id"] for p in profiles])
        result=[service._reservation_session(db,row,include_reservations=False) for row in rows]
    return {"candidates":result,"default_session_id":result[0]["id"] if result else None,
        "default_table_id":result[0]["table_id"] if result else None,
        "resolved_start_at":start,"default_end_at":_stamp(end),
        **{"end_"+key:value for key,value in _local_fields(end,_zone(service.timezone)).items()},
        "server_now":_stamp(_utc(service.clock())),"timezone":service.timezone}
