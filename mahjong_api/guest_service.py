"""Anonymous participants: scoped, random bearer identity and atomic membership."""
import copy
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import delete, select, update
from .guest_models import TournamentParticipant, GuestRecovery
from .tournament_models import Tournament, TournamentTableSession, TournamentCheckIn
from .table_models import ClubTable, ActiveTableMember
from .table_membership import membership_lock, table_open, lock_table, claim_member, release_member
from .tournament_rules import name_key, normalized_name, require
from .external_sync import audit, dump
from .store import now
from .models import User, SEATS
from .tournament_flow import lock_tournament


def hashed(token):
    return hashlib.sha256(str(token or "").encode()).hexdigest()


def expiry(days=90):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="milliseconds")


def enabled(state):
    require(state["settings"].get("allow_guest_auto_enrollment") is True, "guest_not_allowed")
    require(state["status"] not in {"ended", "locked", "swiss_finished", "finals_running"}, "invalid_state")


def create_guest(db, state, name, actor, registered=(), token=None):
    enabled(state)
    import registered_names
    try:
        name = registered_names.display_name(name)
    except ValueError:
        require(False, "invalid_name")
    key = name_key(name)
    require(not any(name_key(p["name"]) == key for p in state["players"]), "guest_name_taken")
    # Reserve current registered names, including those not yet on the roster.
    require(not any(name_key(p["name"]) == key for p in registered), "guest_registered_name_conflict")
    require(db.scalar(select(TournamentParticipant.id).where(TournamentParticipant.tournament_id == state["id"],
        TournamentParticipant.normalized_name == key)) is None, "guest_name_taken")
    pid = "guest-" + str(uuid4())
    participant = TournamentParticipant(id=pid, tournament_id=state["id"], name=name, normalized_name=key,
        participant_type="guest", session_hash=hashed(token) if token else None,
        session_expires_at=expiry() if token else None, created_at=now(), created_by=str(actor))
    db.add(participant)
    player = {"id": pid, "name": name, "permanent": False, "participant_type": "guest", "avatar": ""}
    state["players"].append(player)
    audit(db, state["id"], actor, "guest_enrolled", {"participant_id": pid, "name": name})
    db.flush()
    return participant


def participant(db, tid, token):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        return None
    return db.scalar(select(TournamentParticipant).where(TournamentParticipant.tournament_id == tid,
        TournamentParticipant.session_hash == hashed(token), TournamentParticipant.merged_into_user_id.is_(None),
        TournamentParticipant.session_expires_at > now()))


def view(p):
    return {"id": p.id, "name": p.name, "participant_type": "guest", "avatar": ""} if p else None


def mutate_state(db, row, state):
    version = row.version
    result = db.execute(update(Tournament).where(Tournament.id == row.id, Tournament.version == version)
                       .values(state_json=dump(state), version=version + 1))
    require(result.rowcount == 1, "stale_version")


class GuestService:
    def __init__(self, tournaments, tables):
        self.tournaments, self.tables, self.store = tournaments, tables, tournaments.store

    def identity(self, tid, token):
        with self.store.connect() as db:
            return view(participant(db, tid, token))

    def context(self, tid, token):
        """Project explicit competition seats without exposing anonymous credentials."""
        with self.store.connect() as db:
            row = db.get(Tournament, tid)
            require(row is not None and not row.deleted_at, "not_found")
            state = self.tournaments._decode(row)
            person = participant(db, tid, token)
            member = db.get(ActiveTableMember, person.id) if person else None
            profiles = {p["id"]: p for p in state["players"]}
            members = list(db.scalars(select(ActiveTableMember).join(ClubTable,
                ClubTable.id == ActiveTableMember.table_id).where(ClubTable.tournament_id == tid)))
            rid = state["rounds"][-1]["id"] if state["rounds"] else None
            if state["status"] == "finals_running" and state.get("finals"):
                rid = state["finals"]["id"]
            tables = []
            for table in db.scalars(select(ClubTable).where(ClubTable.tournament_id == tid,
                    ClubTable.status == "open").order_by(ClubTable.number)):
                if state["status"] in {"draft", "registration"}:
                    session = db.get(TournamentTableSession, "enrollment-" + table.id)
                else:
                    session = db.scalar(select(TournamentTableSession).where(TournamentTableSession.table_id == table.id,
                        TournamentTableSession.round_id == rid)) if rid else None
                if session and session.status in {"COMPLETED", "LOCKED"}:
                    session = None
                roster = json.loads(session.roster_json) if session else []
                seats = dict.fromkeys(SEATS)
                for index, pid in enumerate(roster[:len(SEATS)]):
                    if pid:
                        seats[SEATS[index]] = profiles.get(pid, {"id": pid, "name": "Unavailable player"})
                for seated in members:
                    if seated.table_id == table.id and seated.seat in SEATS:
                        player = next((p for p in profiles.values() if str(p.get("account_id") or p["id"]) == seated.user_id), None)
                        if player:
                            seats[seated.seat] = player
                tables.append({"id": table.id, "number": table.number, "name": table.display_name,
                    "capacity": table.capacity, "started_at": session.started_at if session else None,
                    "status": session.status if session else "WAITING_FOR_CHECK_IN",
                    "seats": {seat: ({"id": p["id"], "name": p["name"],
                        "participant_type": p.get("participant_type", "registered_user"),
                        "avatar": p.get("avatar", ""), **({"account_id": p["account_id"]} if p.get("account_id") else {})} if p else None)
                        for seat, p in seats.items()}})
            result = {"enabled": state["settings"].get("allow_guest_auto_enrollment", False),
                "tables": tables, "participant": view(person), "tournament_name": state["name"],
                "current_membership": {"table_id": member.table_id, "seat": member.seat} if member else None}
        result = self.tables.display_names(result)
        # The stable account relation is used only for current name/avatar projection.
        for table in result["tables"]:
            for player in table["seats"].values():
                if player:
                    player.pop("account_id", None)
        return result

    def join(self, tid, data, token, admin_user=None):
        if admin_user is not None:
            from .table_membership import admin
            admin(admin_user)
        new_token = None
        with self.tables.account_guard(), membership_lock, self.store.connect() as db:
            row = lock_tournament(db, tid)
            require(row is not None and not row.deleted_at, "not_found")
            state = self.tournaments._decode(row)
            enabled(state)
            table = db.get(ClubTable, data.get("table_id"))
            table_open(db, table)
            require(table.tournament_id == tid, "guest_context_required")
            lock_table(db, table.id)
            db.refresh(table)
            table_open(db, table)
            method, wind = "manual", data.get("seat")
            if data.get("entry_token"):
                entry, entry_table = self.tables._resolve_token(db, data["entry_token"])
                require(entry_table.id == table.id, "invalid_join_token")
                method = "nfc" if entry.channel == "nfc" else "qr_entry" if entry.purpose == "table_landing" else "qr_" + entry.seat if entry.seat else "qr"
                require(entry.seat is None or wind is None or wind == entry.seat, "seat_not_assigned")
                wind = entry.seat or wind
            require(wind is None or wind in SEATS, "invalid_seat")
            person = participant(db, tid, token)
            if admin_user is not None and data.get("player_id"):
                person = db.get(TournamentParticipant, data["player_id"])
                require(person is not None and person.tournament_id == tid and person.merged_into_user_id is None, "not_found")
            if person is None:
                new_token = secrets.token_urlsafe(32)
                person = create_guest(db, state, data.get("name"), admin_user.id if admin_user else "anonymous", self.tables._account_rows(), None if admin_user else new_token)
                if admin_user:
                    new_token = None
            require(any(p["id"] == person.id for p in state["players"]), "not_found")
            current = db.get(ActiveTableMember, person.id)
            if current:
                require(current.table_id == table.id, "already_at_other_table")
                require(wind is None or current.seat == wind, "already_at_other_seat")
                session = db.get(TournamentTableSession, current.match_id)
                # Draft enrollment is not a playable round; promote on return.
                if session and session.round_id == "enrollment" and state["status"] not in {"draft", "registration"}:
                    release_member(db, current, person.id, "guest_enrollment_promoted")
                    current = None
            if current:
                require(session is not None and session.status not in {"COMPLETED", "LOCKED"}, "invalid_state")
                require(data.get("match_id") is None or data["match_id"] == session.id, "stale_match")
                if session and session.round_id != "enrollment" and not session.started_at and not admin_user and db.scalar(select(TournamentCheckIn.id).where(
                        TournamentCheckIn.match_id == session.id, TournamentCheckIn.player_id == person.id,
                        TournamentCheckIn.generation == session.generation)) is None:
                    from .tournament_operations import participant_action
                    participant_action(self.tournaments, membership_lock, tid, session.id, "check_in",
                        User(id=person.id,name=person.name,role="guest"), str(uuid4()), method, db_override=db)
                return {"participant": view(person), "seat": current.seat, "joined": True}, new_token
            if state["status"] in {"draft", "registration"}:
                mid = "enrollment-" + table.id
                session = db.get(TournamentTableSession, mid)
                if session is None:
                    session = TournamentTableSession(id=mid, tournament_id=tid, round_id="enrollment", table_id=table.id,
                        number=table.number, roster_json="[]", status="WAITING_FOR_CHECK_IN")
                    db.add(session); db.flush()
                group = None
            else:
                require(not state.get("preview"), "roster_frozen")
                rnd = state["rounds"][-1] if state["rounds"] else None
                if not rnd or rnd["status"] == "confirmed":
                    rnd = {"id": str(uuid4()), "number": len(state["rounds"]) + 1, "status": "active",
                           "byes": [], "bye_score": 0, "revision": 1, "tables": []}
                    state["rounds"].append(rnd)
                require(rnd["status"] == "active", "invalid_state")
                group = next((t for t in rnd["tables"] if t["table_id"] == table.id), None)
                assigned = next((t for t in rnd["tables"] if person.id in t["seats"]), None)
                require(assigned is None or assigned is group, "not_assigned")
                if group is None:
                    group = {"number": table.number, "table_id": table.id, "match_id": str(uuid4()),
                             "seats": [], "draft": None, "result": None}
                    rnd["tables"].append(group)
                mid = group["match_id"]
                session = db.get(TournamentTableSession, mid)
                if session is None:
                    session = TournamentTableSession(id=mid, tournament_id=tid, round_id=rnd["id"], table_id=table.id,
                        number=table.number, roster_json=dump(group["seats"]), status="WAITING_FOR_CHECK_IN")
                    db.add(session); db.flush()
            require(session.started_at is None and session.status in {"WAITING_FOR_CHECK_IN", "READY_TO_START"}, "already_started")
            require(data.get("match_id") is None or data["match_id"] == session.id, "stale_match")
            roster = json.loads(session.roster_json)
            if person.id in roster:
                index = roster.index(person.id)
                require(wind is None or index < len(SEATS) and wind == SEATS[index], "seat_not_assigned")
            else:
                # Empty slots are stored as nulls until filled; no identity can take an assigned seat.
                roster += [None] * (table.capacity - len(roster))
                index = SEATS.index(wind) if wind else next((i for i, p in enumerate(roster) if p is None), -1)
                require(0 <= index < len(roster) and roster[index] is None, "seat_occupied")
                roster[index] = person.id
                session.roster_json = dump(roster)
                if group is not None:
                    group["seats"] = roster
            # claim_member resolves the saved roster and stable participant identity.
            row.state_json = dump(state)
            db.flush()
            user = User(id=person.id, name=person.name, role="guest")
            seat = SEATS[index] if index < len(SEATS) else None
            claim_member(db, table, mid, user, admin_user.id if admin_user else person.id, "admin" if admin_user else method, seat=seat)
            if group is not None:
                existing_check = db.scalar(select(TournamentCheckIn).where(TournamentCheckIn.match_id == mid,
                    TournamentCheckIn.player_id == person.id, TournamentCheckIn.generation == session.generation))
                if existing_check is None and not admin_user:
                    db.add(TournamentCheckIn(id=str(uuid4()), tournament_id=tid, match_id=mid, round_id=session.round_id,
                        table_id=table.id, player_id=person.id, account_id=person.id, checked_at=now(), generation=session.generation))
                checked = set(db.scalars(select(TournamentCheckIn.player_id).where(TournamentCheckIn.match_id == mid,
                    TournamentCheckIn.generation == session.generation))) | ({person.id} if not admin_user else set())
                if None not in roster and len(roster) == table.capacity and set(roster) <= checked:
                    session.status = "READY_TO_START"
            mutate_state(db, row, state)
            return {"participant": view(person), "seat": seat, "joined": True}, new_token

    def leave(self, tid, token):
        with membership_lock, self.store.connect() as db:
            row = lock_tournament(db, tid)
            require(row is not None and not row.deleted_at, "not_found")
            p = participant(db, tid, token)
            require(p is not None, "guest_session_required")
            member = db.get(ActiveTableMember, p.id)
            if member:
                table = db.get(ClubTable, member.table_id)
                require(table.tournament_id == tid, "guest_context_required")
                lock_table(db, table.id)
                db.refresh(table)
                table_open(db, table)
                session = db.get(TournamentTableSession, member.match_id)
                require(session is None or session.started_at is None, "already_started")
                release_member(db, member, p.id, "guest_left")
                if session:
                    db.execute(delete(TournamentCheckIn).where(TournamentCheckIn.match_id == session.id,
                        TournamentCheckIn.player_id == p.id, TournamentCheckIn.generation == session.generation))
                    session.status = "WAITING_FOR_CHECK_IN"
                    if session.round_id == "enrollment":
                        session.roster_json = dump([None if pid == p.id else pid for pid in json.loads(session.roster_json)])
                row.version += 1
                audit(db, tid, p.id, "guest_left", {"participant_id":p.id})
            return {"ok": True}

    def issue_recovery(self, tid, data, user):
        from .table_membership import admin
        admin(user)
        reason = normalized_name(data.get("reason", ""))
        require(1 <= len(reason) <= 500, "reason_required")
        token = secrets.token_urlsafe(32)
        with membership_lock, self.store.connect() as db:
            row = lock_tournament(db, tid)
            require(row is not None and not row.deleted_at, "not_found")
            p = db.get(TournamentParticipant, data.get("player_id"))
            require(p is not None and p.tournament_id == tid and p.merged_into_user_id is None, "not_found")
            timestamp = now()
            # A newer administrator-issued link revokes every older unused link.
            db.execute(update(GuestRecovery).where(GuestRecovery.participant_id == p.id,
                GuestRecovery.used_at.is_(None)).values(used_at=timestamp))
            db.add(GuestRecovery(token_hash=hashed(token), participant_id=p.id,
                expires_at=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(timespec="milliseconds")))
            audit(db, tid, user.id, "guest_recovery_issued", {"participant_id": p.id, "reason": reason})
        return token

    def recover(self, tid, raw):
        require(isinstance(raw, str) and 32 <= len(raw) <= 128, "invalid_recovery")
        token = secrets.token_urlsafe(32)
        with membership_lock, self.store.connect() as db:
            row = lock_tournament(db, tid)
            require(row is not None and not row.deleted_at, "invalid_recovery")
            recovery = db.get(GuestRecovery, hashed(raw))
            timestamp = now()
            require(recovery is not None and recovery.used_at is None and recovery.expires_at > timestamp, "invalid_recovery")
            p = db.get(TournamentParticipant, recovery.participant_id)
            require(p is not None and p.tournament_id == tid and p.merged_into_user_id is None, "invalid_recovery")
            consumed = db.execute(update(GuestRecovery).where(GuestRecovery.token_hash == recovery.token_hash,
                GuestRecovery.used_at.is_(None), GuestRecovery.expires_at > timestamp).values(used_at=timestamp))
            require(consumed.rowcount == 1, "invalid_recovery")
            p.session_hash, p.session_expires_at = hashed(token), expiry()
            audit(db, tid, p.id, "guest_recovered", {"participant_id": p.id})
        return token


def guest_admin_action(service, db, state, action, data, actor):
    if action == "guest_add":
        rows = service.account_rows() if hasattr(service, "account_rows") else []
        p = create_guest(db, state, data.get("name"), actor, rows)
        return {"participant_id": p.id, "name": p.name}
    if action == "guest_merge":
        p = db.get(TournamentParticipant, data.get("player_id"))
        require(p is not None and p.tournament_id == state["id"] and p.merged_into_user_id is None, "not_found")
        lookup = getattr(service, "account_lookup", None)
        require(lookup is not None, "account_directory_unavailable")
        person = lookup([data.get("account_id")])[0]
        require(not any(x["id"] != p.id and str(x.get("account_id") or x["id"]) == str(person["id"]) for x in state["players"]), "duplicate_account")
        require(not data.get("reason") is None and bool(normalized_name(data.get("reason", ""))), "reason_required")
        require(db.get(ActiveTableMember, p.id) is None, "identity_frozen")
        for session in db.scalars(select(TournamentTableSession).where(TournamentTableSession.tournament_id == state["id"])):
            if p.id in json.loads(session.roster_json) and session.status not in {"COMPLETED", "LOCKED"}:
                checked = db.scalar(select(TournamentCheckIn.id).where(TournamentCheckIn.match_id == session.id,
                    TournamentCheckIn.player_id == p.id, TournamentCheckIn.generation == session.generation))
                require(not session.started_at and checked is None, "identity_frozen")
        player = next((x for x in state["players"] if x["id"] == p.id), None)
        require(player is not None, "not_found")
        require(not any(x["id"] != p.id and name_key(x["name"]) == name_key(person["name"]) for x in state["players"]), "registered_player_name_conflict")
        before = copy.deepcopy(player)
        player.update(name=person["name"], account_id=person["id"], participant_type="registered_user", permanent=True, avatar=person.get("avatar", ""))
        p.merged_into_user_id, p.merged_at, p.merged_by = person["id"], now(), actor
        p.session_hash = None
        return {"before": before, "after": player, "reason": data["reason"]}
    return None
