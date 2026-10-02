"""Transactional participant actions and admin-only adjustments."""
import copy
from contextlib import nullcontext
import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import select, update
from .models import User
from .external_sync import audit, dump
from .tournament_models import Tournament, TournamentRequest, TournamentTableSession, TournamentCheckIn, TournamentPenalty
from .tournament_flow import attach_penalties, penalty_dict, lock_tournament
from .tournament_rules import require, number, normalized_name, scoring_value


ADMIN_ACTIONS = {"penalty_add", "penalty_edit", "penalty_revoke", "bind_account", "reset_table", "archive"}


def require_admin(actor, user):
    # This guard is below the route layer: direct persistence calls also require
    # a server-authenticated identity, never a role/id supplied in request JSON.
    require(isinstance(user, User) and user.role in {"admin", "super_admin"}
            and str(user.id) == str(actor), "admin_required")


def admin_transition(db, state, action, data, actor, user, timestamp):
    if action not in ADMIN_ACTIONS:
        return None
    require_admin(actor, user)
    if action == "archive":
        require(state["status"] in {"ended", "locked"}, "invalid_state")
        require(not state.get("archived_at"), "already_archived")
        state["archived_at"], state["archived_by"] = timestamp, str(actor)
        return {"archived_at": timestamp}
    require(state["status"] not in {"ended", "locked"}, "invalid_state")
    tid = state["id"]
    if action == "bind_account":
        player = next((p for p in state["players"] if p["id"] == data.get("player_id")), None)
        require(player is not None, "not_found")
        account_id = data.get("account_id")
        require(isinstance(account_id, str) and 1 <= len(account_id) <= 128, "invalid_account")
        require(not any(p["id"] != player["id"] and (p.get("account_id") or p["id"]) == account_id
                        for p in state["players"]), "duplicate_account")
        for session in db.scalars(select(TournamentTableSession).where(TournamentTableSession.tournament_id == tid)):
            if player["id"] not in json.loads(session.roster_json) or session.status == "COMPLETED":
                continue
            checked = db.scalar(select(TournamentCheckIn).where(TournamentCheckIn.match_id == session.id,
                TournamentCheckIn.player_id == player["id"], TournamentCheckIn.generation == session.generation))
            require(not session.started_at and not checked, "identity_frozen")
        before = player.get("account_id")
        player["account_id"] = account_id
        return {"player_id": player["id"], "before": before, "after": account_id}
    if action == "reset_table":
        session = db.get(TournamentTableSession, data.get("match_id"))
        require(session is not None and session.tournament_id == tid, "not_found")
        require(session.status not in {"COMPLETED", "LOCKED", "SCORE_PENDING"}, "invalid_state")
        reason = normalized_name(data.get("reason", ""))
        require(1 <= len(reason) <= 500, "reason_required")
        if state.get("finals"):
            table = next((t for t in state["finals"]["tables"] if t.get("match_id") == session.id), None)
            require(not table or not any(not h["void"] for h in table["hands"]), "score_exists")
        before = {k: getattr(session, k) for k in ("started_at", "ends_at", "started_by", "status", "generation")}
        from .table_membership import release_table
        release_table(db, session.table_id, actor, "admin_reset", session.id)
        session.generation += 1
        session.started_at = session.ends_at = session.started_by = None
        session.status, session.legacy = "WAITING_FOR_CHECK_IN", 0
        session.time_limit_seconds = state["settings"].get("time_limit_seconds")
        return {"match_id": session.id, "before": before, "reason": reason}
    old = None
    if action != "penalty_add":
        old = db.get(TournamentPenalty, data.get("penalty_id"))
        require(old is not None and old.tournament_id == tid and old.status == "active", "penalty_not_active")
    reason = normalized_name(data.get("reason", ""))
    require(1 <= len(reason) <= 500, "reason_required")
    before = penalty_dict(old) if old else None
    if action == "penalty_revoke":
        old.status, old.revoked_at, old.revoked_by, old.revoke_reason = "revoked", timestamp, str(actor), reason
        db.flush()
        attach_penalties(db, state)
        if state.get("finals") and state["finals"]["status"] == "preview":
            state["finals"] = None
        return {"before": before, "after": penalty_dict(old)}
    pid = old.player_id if old else data.get("player_id")
    require(pid in {p["id"] for p in state["players"]}, "not_found")
    amount = number(data.get("amount"))
    if state["settings"].get("scoring_mode") == "placement_and_game_count":
        # New-mode rewards/deductions use their exact configured decimal value.
        # Legacy raw-point rounding units have no role in this total.
        require(amount != 0, "invalid_penalty")
    else:
        require(amount > 0 and amount % number(scoring_value(state["settings"], "min_unit")) == 0, "invalid_penalty")
    rid = old.round_id if old else data.get("round_id") or None
    mid = old.match_id if old else data.get("match_id") or None
    if rid:
        require(rid in {r["id"] for r in state["rounds"]} | ({state["finals"]["id"]} if state.get("finals") else set()), "not_found")
    if mid:
        session = db.get(TournamentTableSession, mid)
        require(session is not None and session.tournament_id == tid and (not rid or session.round_id == rid), "not_found")
        require(pid in json.loads(session.roster_json), "not_assigned")
        rid = session.round_id
    if old:
        old.status, old.revoked_at, old.revoked_by, old.revoke_reason = "replaced", timestamp, str(actor), reason
    phase = old.phase if old else ("finals" if state.get("finals") and state["finals"]["status"] == "active" else "swiss")
    row = TournamentPenalty(id=str(uuid4()), tournament_id=tid, player_id=pid, amount=str(amount),
        reason=reason, created_at=timestamp, created_by=str(actor), round_id=rid, match_id=mid,
        phase=phase, status="active", replaces=old.id if old else None)
    db.add(row); db.flush()
    attach_penalties(db, state)
    # A changed preliminary total invalidates an unstarted finals preview.
    if state.get("finals") and state["finals"]["status"] == "preview":
        state["finals"] = None
    return {"before": before, "after": penalty_dict(row)}


def participant_action(service, lock, tid, mid, action, user, key, join_method="manual", db_override=None):
    require(isinstance(user, User), "not_authenticated")
    require(action in {"check_in", "start_table"}, "invalid_action")
    require(isinstance(key, str) and 1 <= len(key) <= 128, "request_id_required")
    actor = str(user.id)
    fingerprint = hashlib.sha256(dump([tid, mid, action, actor]).encode()).hexdigest()
    with lock, (nullcontext(db_override) if db_override is not None else service.store.connect()) as db:
        row = lock_tournament(db, tid)
        require(row is not None, "not_found")
        require(not row.deleted_at, "tournament_deleted")
        state = service._decode(row)
        session = db.get(TournamentTableSession, mid)
        require(session is not None and session.tournament_id == tid, "not_found")
        pid = next((p["id"] for p in state["players"] if str(p.get("account_id") or p["id"]) == actor), None)
        roster = json.loads(session.roster_json)
        assigned = pid is not None and pid in roster
        require(assigned or (action == "start_table" and user.role in {"admin", "super_admin"}), "not_assigned")
        previous = db.get(TournamentRequest, key)
        if previous:
            require(previous.fingerprint == fingerprint, "submission_conflict")
        else:
            require(state["status"] in {"running", "round_pending", "finals_running"}, "invalid_state")
            current_rid = state["finals"]["id"] if state["status"] == "finals_running" else state["rounds"][-1]["id"] if state["rounds"] else None
            require(session.round_id == current_rid and session.status not in {"COMPLETED", "LOCKED"}, "invalid_state")
            checked = list(db.scalars(select(TournamentCheckIn).where(TournamentCheckIn.match_id == mid,
                TournamentCheckIn.generation == session.generation)))
            changed, detail = False, {}
            timestamp = service.clock()
            if action == "check_in":
                require(session.started_at is None and session.status in {"WAITING_FOR_CHECK_IN", "READY_TO_START"}, "already_started")
                from .table_membership import claim_member
                from .table_models import ClubTable
                claim_member(db, db.get(ClubTable, session.table_id), mid, user, actor, join_method, timestamp)
                if pid not in {c.player_id for c in checked}:
                    db.add(TournamentCheckIn(id=str(uuid4()), tournament_id=tid, match_id=mid, round_id=session.round_id,
                        table_id=session.table_id, player_id=pid, account_id=actor, checked_at=timestamp, generation=session.generation))
                    if len(checked) + 1 == len(roster):
                        session.status = "READY_TO_START"
                    changed, detail = True, {"player_id": pid, "table_id": session.table_id, "round_id": session.round_id, "at": timestamp}
            elif session.started_at is None:
                require(session.status == "READY_TO_START" and set(roster) == {c.player_id for c in checked}, "check_in_incomplete")
                require(assigned and pid in {c.player_id for c in checked} or user.role in {"admin", "super_admin"}, "not_assigned")
                # Snapshot the current rule at the actual start, never change it afterwards.
                session.time_limit_seconds = state["settings"].get("time_limit_seconds") or None
                session.started_at, session.started_by, session.status = timestamp, actor, "IN_PROGRESS"
                session.ends_at = ((datetime.fromisoformat(timestamp) + timedelta(seconds=session.time_limit_seconds)).isoformat(timespec="milliseconds")
                                   if session.time_limit_seconds else None)
                changed, detail = True, {"table_id": session.table_id, "round_id": session.round_id, "started_at": timestamp, "ends_at": session.ends_at}
            if changed:
                changed_row = db.execute(update(Tournament).where(Tournament.id == tid, Tournament.version == row.version).values(version=row.version + 1))
                require(changed_row.rowcount == 1, "stale_version")
                audit(db, tid, actor, action, {"match_id": mid, **detail})
            db.add(TournamentRequest(id=key, tournament_id=tid, fingerprint=fingerprint))
    return service.get(tid) if db_override is None else None
