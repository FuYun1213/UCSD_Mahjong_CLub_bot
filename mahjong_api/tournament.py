"""Versioned tournament transactions reuse Store, authentication and outbox."""
import copy
import hashlib
import json
import threading
from contextlib import nullcontext
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select, update
from .database_models import User as Account, Metadata
from .external_sync import audit, dump, queue_delivery
from .store import Conflict, now
from .tournament_models import Tournament, TournamentRequest, TournamentAudit, ExternalDelivery, TournamentTableSession
from .tournament_flow import attach_penalties, decorate_tables, ensure_sessions, stable_id, lock_tournament
from .tournament_operations import ADMIN_ACTIONS, require_admin, admin_transition, participant_action
from .tournament_rules import (require, normalized_name, name_key, number, rounded,
    scoring_value, settings_value, standings, pair_round, score_table, table_name, DEFAULT_NAMES,
    countable_placement_game, rescore_placement_result)

from .table_membership import membership_lock
_lock = membership_lock


class TournamentService:
    def __init__(self, store, external):
        self.store, self.external = store, external
        self.clock = now
        self.account_guard = nullcontext  # TableService injects the production account-file guard.

    @staticmethod
    def _decode(row):
        state = json.loads(row.state_json)
        state["version"] = row.version
        return state

    def list(self, include_deleted=False):
        with self.store.connect() as db:
            return [{"id": r.id, "name": json.loads(r.state_json)["name"],
                     "status": json.loads(r.state_json)["status"], "version": r.version}
                    for r in db.scalars(select(Tournament).where(Tournament.deleted_at.is_(None)) if not include_deleted else select(Tournament))]

    def get(self, tid, include_deleted=False):
        with self.store.connect() as db:
            row = db.get(Tournament, tid)
            require(row is not None, "not_found")
            require(include_deleted or not row.deleted_at, "tournament_deleted")
            state = self._decode(row)
            state["deleted_at"], state["deleted_by"], state["delete_reason"] = row.deleted_at, row.deleted_by, row.delete_reason
            attach_penalties(db, state)
            state["server_now"] = self.clock()
            decorate_tables(db, state, state["server_now"])
            state["table_defaults"] = DEFAULT_NAMES
            state["standings"], state["swiss_standings"] = standings(state), standings(state, finals=False)
            state["audit"] = [{"id": a.id, "action": a.action, "actor_id": a.actor_id,
                "at": a.created_at, "detail": json.loads(a.detail_json)} for a in db.scalars(
                select(TournamentAudit).where(TournamentAudit.tournament_id == tid).order_by(TournamentAudit.id.desc()).limit(100))]
        state["deliveries"] = self.external.list(tid)
        return state

    def create(self, data, actor):
        name, key = normalized_name(data.get("name", "")), data.get("request_id", "")
        require(1 <= len(name) <= 120, "invalid_name")
        require(isinstance(key, str) and 1 <= len(key) <= 128, "request_id_required")
        fingerprint = hashlib.sha256(dump(["create", data, actor]).encode()).hexdigest()
        with _lock, self.store.connect() as db:
            previous = db.get(TournamentRequest, key)
            if previous:
                require(previous.fingerprint == fingerprint, "submission_conflict")
                old = db.get(Tournament, previous.tournament_id)
                require(not old.deleted_at, "tournament_deleted")
                return self._decode(old)
            tid = str(uuid4())
            state = {"id": tid, "schema_version": 3, "name": name, "created_at": now(), "status": "draft",
                "settings": settings_value(data.get("settings", {})), "players": [], "rounds": [],
                "preview": None, "finals": None, "table_names": {}}
            db.add(Tournament(id=tid, version=1, state_json=dump(state)))
            db.add(TournamentRequest(id=key, tournament_id=tid, fingerprint=fingerprint))
            audit(db, tid, actor, "create", {"name": name})
            return {**state, "version": 1}

    def soft_delete(self, tid, data, user):
        from .table_membership import admin, release_table
        from .table_models import ClubTable, TableJoinToken
        admin(user)
        key = data.get("request_id", "")
        require(isinstance(key, str) and 1 <= len(key) <= 128, "request_id_required")
        with _lock, self.store.connect() as db:
            row = lock_tournament(db, tid)
            require(row is not None, "not_found")
            if row.deleted_at:
                return {"id": tid, "deleted_at": row.deleted_at}
            state = self._decode(row)
            require(data.get("confirm_name", "").strip() == state["name"], "delete_name_mismatch")
            reason = normalized_name(data.get("reason", ""))
            require(1 <= len(reason) <= 500, "reason_required")
            require(data.get("version") == row.version, "stale_version")
            timestamp = self.clock()
            row.deleted_at, row.deleted_by, row.delete_reason = timestamp, str(user.id), reason
            row.version += 1
            for table in db.scalars(select(ClubTable).where(ClubTable.tournament_id == tid)):
                release_table(db, table.id, user.id, "tournament_deleted")
                for token in db.scalars(select(TableJoinToken).where(TableJoinToken.table_id == table.id, TableJoinToken.revoked_at.is_(None))):
                    token.revoked_at = timestamp
            for delivery in db.scalars(select(ExternalDelivery).where(ExternalDelivery.tournament_id == tid, ExternalDelivery.status.in_(["pending", "failed"]))):
                delivery.status, delivery.updated_at = "cancelled", timestamp
            audit(db, tid, user.id, "tournament_deleted", {"name": state["name"], "reason": reason, "at": timestamp})
            return {"id": tid, "deleted_at": timestamp}

    def participant_action(self, tid, mid, action, user, key, join_method="manual"):
        return participant_action(self, _lock, tid, mid, action, user, key, join_method)

    def apply(self, tid, action, data, actor, *, actor_user=None):
        if action in ADMIN_ACTIONS or action in {"guest_add", "guest_merge", "recalculate", "manual_game"}:
            require_admin(actor, actor_user)
        key = data.get("request_id", "")
        require(isinstance(key, str) and 1 <= len(key) <= 128, "request_id_required")
        fingerprint = hashlib.sha256(dump([tid, action, data, actor]).encode()).hexdigest()
        deliveries = []
        with self.account_guard(), _lock, self.store.connect() as db:
            if action == "bind_account":
                lookup = getattr(self, "account_lookup", None)
                require(lookup is not None, "account_directory_unavailable")
                lookup([data.get("account_id")])
            row = lock_tournament(db, tid)
            require(row is not None, "not_found")
            require(not row.deleted_at, "tournament_deleted")
            previous = db.get(TournamentRequest, key)
            if previous:
                require(previous.fingerprint == fingerprint, "submission_conflict")
            else:
                require(type(data.get("version")) is int and data["version"] == row.version, "stale_version")
                state = self._decode(row)
                attach_penalties(db, state)
                require(state["status"] != "locked" or action == "unlock", "locked")
                from .guest_models import TournamentParticipant
                guest_binding = db.get(TournamentParticipant, data.get("player_id")) if action == "bind_account" else None
                if guest_binding is not None and guest_binding.tournament_id == tid and guest_binding.merged_into_user_id is None:
                    from .guest_service import guest_admin_action
                    detail = guest_admin_action(self, db, state, "guest_merge", {**data,"reason":data.get("reason") or "Administrator account binding"}, actor)
                else:
                    detail = admin_transition(db, state, action, data, actor, actor_user, self.clock())
                if detail is None:
                    detail = self._transition(db, state, action, data, actor, deliveries)
                state.pop("penalties", None)  # Independent SQL records, never duplicated in the aggregate.
                result = db.execute(update(Tournament).where(Tournament.id == tid, Tournament.version == row.version)
                    .values(state_json=dump(state), version=row.version + 1))
                require(result.rowcount == 1, "stale_version")
                db.add(TournamentRequest(id=key, tournament_id=tid, fingerprint=fingerprint))
                audit(db, tid, actor, action, detail)
        # A committed outbox is dispatched after the HTTP response, not while
        # a multi-table confirmation keeps the browser waiting on a provider.
        return self.get(tid)

    def _transition(self, db, state, action, data, actor, deliveries):
        status, tid = state["status"], state["id"]
        if action in {"guest_add", "guest_merge"}:
            from .guest_service import guest_admin_action
            require(status not in {"ended", "locked"}, "invalid_state")
            return guest_admin_action(self, db, state, action, data, actor)
        if action == "recalculate":
            require(state["settings"].get("scoring_mode") == "placement_and_game_count", "invalid_action")
            require(status not in {"ended", "locked"}, "invalid_state")
            reason = data.get("reason")
            require(isinstance(reason, str) and 1 <= len(normalized_name(reason)) <= 500, "reason_required")
            before = copy.deepcopy(state["rounds"])
            seen, changed = set(), 0
            for rnd in state["rounds"]:
                for table in rnd["tables"]:
                    if not countable_placement_game(rnd, table, seen):
                        continue
                    old = table["result"]
                    table.setdefault("result_revisions", []).append(copy.deepcopy(old))
                    if old.get("request_id"):
                        self._invalidate_delivery(db, old["request_id"])
                    table["result"] = rescore_placement_result(state["settings"], old)
                    table["result"]["request_id"] = old.get("request_id")
                    changed += 1
            return {"before": before, "after": state["rounds"], "reason": normalized_name(reason), "games_recalculated": changed}
        if action == "manual_game":
            require(status in {"draft", "registration", "running"} and not state["preview"]
                and all(r["status"] == "confirmed" for r in state["rounds"]), "round_incomplete")
            ids = data.get("players")
            require(isinstance(ids, list) and len(ids) == 4 and len(set(ids)) == 4 and all(isinstance(p,str) for p in ids), "invalid_roster")
            for pid in ids:
                player = next((p for p in state["players"] if p["id"] == pid), None)
                if player is None:
                    lookup = getattr(self, "account_lookup", None)
                    require(lookup is not None, "account_directory_unavailable")
                    person = lookup([pid])[0]
                    require(not any(name_key(p["name"]) == name_key(person["name"]) for p in state["players"]), "registered_player_name_conflict")
                    player = {"id":pid,"account_id":pid,"name":person["name"],"avatar":person.get("avatar", ""),"permanent":True,"participant_type":"registered_user"}
                    state["players"].append(player)
                require(player.get("participant_type") != "guest" or state["settings"].get("allow_guest_auto_enrollment"), "guest_not_allowed")
            table = {"number":1,"table_id":str(uuid4()),"match_id":str(uuid4()),"seats":ids,"draft":None,"result":None}
            table["draft"] = score_table(state, table, data.get("scores"))
            rnd = {"id":str(uuid4()),"number":len(state["rounds"])+1,"status":"pending","byes":[],"bye_score":0,"revision":1,"tables":[table],"source":"manual"}
            # A manual game has its own session without taking any occupied physical table.
            from .table_models import ClubTable
            used = list(db.scalars(select(ClubTable.number).where(ClubTable.tournament_id == tid)))
            table["number"] = max(used, default=0)+1
            state["rounds"].append(rnd)
            state["status"] = "round_pending"
            ensure_sessions(db,state)
            result = self._transition(db,state,"confirm_round",{},actor,deliveries)
            return {**result,"players":ids,"source":"manual"}
        if action == "settings":
            require(status not in {"ended", "finals_running", "locked"}, "invalid_state")
            before = state["settings"]
            value = settings_value(data.get("settings", {}), before)
            if state["rounds"] or state["preview"]:
                require(value["table_size"] == before["table_size"], "roster_frozen")
            if state["rounds"]:
                require(value["scoring_mode"] == before["scoring_mode"], "scoring_mode_frozen")
            state["settings"] = value
            state["name"] = normalized_name(data.get("name", state["name"]))[:120] or state["name"]
            names = data.get("table_names", state["table_names"])
            require(isinstance(names, dict) and all(str(k).isdigit() and int(k) > 0 and isinstance(v, str)
                    and len(v) <= 120 for k, v in names.items()), "invalid_name")
            state["table_names"] = names
            return {"before": before, "after": value, "table_names": names}
        if action in {"register", "start"}:
            require(status in ({"draft"} if action == "register" else {"draft", "registration"}), "invalid_state")
            if action == "start":
                require(len(state["players"]) >= state["settings"]["table_size"], "not_enough_players")
            state["status"] = "registration" if action == "register" else "running"
            return {}
        if action == "player":
            require(status in {"draft", "registration"}, "roster_frozen")
            if "registered_user_id" in data:
                uid = data["registered_user_id"]
                require(isinstance(uid, str) and bool(uid), "account_not_found")
                lookup = getattr(self, "account_lookup", None)
                require(lookup is not None, "account_directory_unavailable")
                person = lookup([uid])[0]
                # Stable identity wins over names, which may have changed since
                # this tournament snapshot or may match a legacy guest.
                require(not any(str(p.get("account_id") or p["id"]) == str(person["id"])
                                for p in state["players"]), "account_already_registered")
                require(not any(name_key(p["name"]) == name_key(person["name"])
                                for p in state["players"]), "registered_player_name_conflict")
                # The browser's name is never authoritative for a selected account.
                data = {**data, "player_id": person["id"], "name": person["name"], "permanent": True}
                db.merge(Account(id=person["id"], name=person["name"]))
                db.flush()
            # Anonymous names have a dedicated scoped model and cannot create login accounts.
            if not data.get("player_id") and not data.get("registered_user_id"):
                from .guest_service import guest_admin_action
                return guest_admin_action(self, db, state, "guest_add", data, actor)
            name = normalized_name(data.get("name", ""))
            require(1 <= len(name) <= 128, "invalid_name")
            existing = next((p for p in state["players"] if name_key(p["name"]) == name_key(name)), None)
            if existing:
                if data.get("permanent"):
                    db.merge(Account(id=existing["id"], name=existing["name"]))
                    existing["permanent"] = True
                return {"player": existing, "duplicate": True}
            pid = data.get("player_id")
            if pid:
                if "registered_user_id" not in data:
                    # A raw score-directory ID is not proof of a registered login identity.
                    lookup = getattr(self, "account_lookup", None)
                    require(lookup is not None, "account_directory_unavailable")
                    person = lookup([str(pid)])[0]
                    name = person["name"]
                    data = {**data, "registered_user_id":person["id"]}
                account = db.get(Account, str(pid))
                require(account is not None, "not_found")
                pid, name = account.id, account.name
                require(not any(p["id"] == pid for p in state["players"]), "duplicate_player")
            else:
                account = next((p for p in db.scalars(select(Account)) if name_key(p.name) == name_key(name)), None)
                pid = account.id if account else "guest-" + str(uuid4())
            player = {"id": pid, "name": name, "permanent": bool(data.get("permanent") or data.get("player_id"))}
            if "registered_user_id" in data:
                player["account_id"] = pid
            state["players"].append(player)
            if player["permanent"]:
                db.merge(Account(id=pid, name=name))
            return {"player": player}
        if action == "remove_player":
            require(status in {"draft", "registration"}, "roster_frozen")
            player = next((p for p in state["players"] if p["id"] == data.get("player_id")), None)
            if player:
                from .table_models import ActiveTableMember, ClubTable
                member = db.get(ActiveTableMember, str(player.get("account_id") or player["id"]))
                member_table = db.get(ClubTable, member.table_id) if member else None
                require(not member_table or member_table.tournament_id != tid, "player_seated_leave_first")
                # Reserved enrollment/round seats remain relationships even if a
                # member is temporarily absent. Do not orphan them by roster removal.
                reserved = any(player["id"] in json.loads(session.roster_json) for session in db.scalars(
                    select(TournamentTableSession).where(TournamentTableSession.tournament_id == tid,
                        TournamentTableSession.status.not_in(["COMPLETED", "LOCKED"]))))
                require(not reserved, "player_seated_leave_first")
            state["players"] = [p for p in state["players"] if p["id"] != data.get("player_id")]
            return {"player_id": data.get("player_id")}
        if action == "pair":
            require(status == "running" and all(r["status"] == "confirmed" for r in state["rounds"]), "round_incomplete")
            previous, state["preview"] = state["preview"], pair_round(state)
            from .tournament_flow import assign_registered_tables
            assign_registered_tables(db, state, state["preview"]["tables"])
            return {"previous": previous, "preview": state["preview"]}
        if action == "confirm_seats":
            require(status == "running" and state["preview"] is not None, "invalid_state")
            rnd = state["preview"]
            self._arrange(rnd["tables"], data.get("seats"))
            rnd["status"] = "active"
            from .table_membership import release_table
            for table in rnd["tables"]:
                release_table(db, table["table_id"], actor, "seating_confirmed", "enrollment-" + table["table_id"])
            state["rounds"].append(rnd)
            state["preview"] = None
            ensure_sessions(db, state)
            return {"round": rnd}
        if action == "score_table":
            require(status in {"running", "round_pending"} and state["rounds"], "invalid_state")
            rnd = state["rounds"][-1]
            require(rnd["status"] in {"active", "pending"}, "invalid_state")
            table = next((t for t in rnd["tables"] if t["number"] == data.get("table")), None)
            require(table is not None, "not_found")
            session = db.get(TournamentTableSession, table["match_id"])
            require(session is not None and (session.started_at or session.legacy), "match_not_started")
            require(session.status in {"IN_PROGRESS", "SCORE_PENDING"}, "invalid_state")
            before = table["draft"]
            table["draft"] = score_table(state, table, data.get("scores"))
            session.status = "SCORE_PENDING"
            if all(t["draft"] for t in rnd["tables"]):
                rnd["status"], state["status"] = "pending", "round_pending"
            return {"round_id": rnd["id"], "table": table["number"], "before": before, "after": table["draft"]}
        if action == "confirm_round":
            require(status == "round_pending", "round_incomplete")
            rnd = state["rounds"][-1]
            require(rnd["status"] == "pending" and all(t["draft"] for t in rnd["tables"]), "round_incomplete")
            for table in rnd["tables"]:
                if state["settings"].get("scoring_mode") == "placement_and_game_count":
                    table["result"] = rescore_placement_result(state["settings"], table["draft"])
                else:
                    table["result"] = copy.deepcopy(table["draft"])
                db.get(TournamentTableSession, table["match_id"]).status = "COMPLETED"
                from .table_membership import release_table
                release_table(db, table["table_id"], actor, "round_completed", table["match_id"])
            rnd["status"], rnd["confirmed_at"], state["status"] = "confirmed", now(), "running"
            totals = {r["id"]: r["score"] for r in standings(state, finals=False)}
            for table in rnd["tables"]:
                result = table["result"]
                canonical = {"schemaVersion": 1, "kind": "match", "requestId": str(uuid4()),
                    "tournamentId": tid, "roundId": rnd["id"], "tableNumber": table["number"], "tableId": table["table_id"],
                    "matchId": table["match_id"], "submittedAt": rnd["confirmed_at"], "rules": result["rules"],
                    "revision": rnd["revision"], "players": [{**p, "cumulativeScore": totals[p["id"]]} for p in result["players"]]}
                delivery = queue_delivery(db, canonical, actor)
                if rnd.get("revisions") and delivery.adapter == "narts":
                    delivery.status, delivery.error_code = "manual_review", "narts_correction"
                result["request_id"] = delivery.id
                deliveries.append(delivery.id)
            return {"round_id": rnd["id"], "revision": rnd["revision"]}
        if action == "reopen_round":
            require(status in {"running", "swiss_finished"} and state["rounds"] and not state["preview"]
                    and state["finals"] is None, "invalid_state")
            require(normalized_name(data.get("reason", "")), "reason_required")
            rnd = state["rounds"][-1]
            require(rnd["status"] == "confirmed", "invalid_state")
            before = copy.deepcopy(rnd)
            before.pop("revisions", None)
            rnd.setdefault("revisions", []).append(before)
            for table in rnd["tables"]:
                self._invalidate_delivery(db, table["result"]["request_id"])
                table["result"] = None
                db.get(TournamentTableSession, table["match_id"]).status = "SCORE_PENDING"
            rnd["revision"] += 1
            rnd["status"], state["status"] = "pending", "round_pending"
            return {"reason": data["reason"], "previous": before}
        if action == "finish_swiss":
            require(status == "running" and state["rounds"] and not state["preview"]
                    and all(r["status"] == "confirmed" for r in state["rounds"]), "round_incomplete")
            state["status"] = "swiss_finished"
            return {}
        if action == "preview_finals":
            require(state["settings"].get("scoring_mode") != "placement_and_game_count", "placement_finals_use_rounds")
            require(status == "swiss_finished", "invalid_state")
            entrants = data.get("entrants", [])
            require(isinstance(entrants, list) and len(set(entrants)) == len(entrants)
                    and set(entrants) <= {p["id"] for p in state["players"]}, "invalid_roster")
            size = state["settings"]["table_size"]
            require(len(entrants) >= size and len(entrants) % size == 0, "finals_full_tables")
            carry = data.get("carry", "all")
            require(carry in {"all", "ratio", "zero"}, "invalid_settings")
            ratio = number(data.get("ratio", 1)) if carry == "ratio" else Decimal(1 if carry == "all" else 0)
            require(0 <= ratio <= 1, "invalid_settings")
            preliminary = {r["id"]: r for r in standings(state, finals=False)}
            scores = {p: r["score"] for p, r in preliminary.items()}
            before = state["finals"]
            state["finals"] = {"id": str(uuid4()), "status": "preview", "entrants": entrants, "carry": carry, "ratio": float(ratio),
                "starts": {p: {"preliminary_score": scores[p], "finals_start": rounded(number(scores[p]) * ratio, state["settings"]),
                    "carried_penalty": rounded(number(preliminary[p]["penalty_total"]) * ratio, state["settings"])} for p in entrants},
                "tables": [{"number": i // size + 1, "table_id": stable_id(tid, "table:" + str(i // size + 1)), "match_id": str(uuid4()),
                    "seats": entrants[i:i + size], "hands": []} for i in range(0, len(entrants), size)]}
            from .tournament_flow import assign_registered_tables
            assign_registered_tables(db, state, state["finals"]["tables"])
            return {"before": before, "after": state["finals"]}
        if action == "start_finals":
            require(status == "swiss_finished" and state["finals"] and state["finals"]["status"] == "preview", "invalid_state")
            self._arrange(state["finals"]["tables"], data.get("seats"))
            state["finals"]["status"], state["status"] = "active", "finals_running"
            ensure_sessions(db, state)
            return {"finals": state["finals"]}
        if action in {"hand", "correct_hand", "undo_hand"}:
            require(status == "finals_running", "invalid_state")
            table = next((t for t in state["finals"]["tables"] if t["number"] == data.get("table")), None)
            require(table is not None, "not_found")
            session = db.get(TournamentTableSession, table["match_id"])
            require(session is not None and (session.started_at or session.legacy), "match_not_started")
            require(session.status == "IN_PROGRESS", "invalid_state")
            before = None
            if action != "hand":
                active = [h for h in table["hands"] if not h["void"]]
                require(active and active[-1]["id"] == data.get("hand_id"), "latest_hand_only")
                require(normalized_name(data.get("reason", "")), "reason_required")
                before = copy.deepcopy(active[-1])
                active[-1]["void"] = True
                active[-1]["void_at"], active[-1]["reason"] = now(), data["reason"]
                self._invalidate_delivery(db, active[-1]["request_id"])
            if action != "undo_hand":
                raw = data.get("deltas")
                require(isinstance(raw, dict) and set(raw) == set(table["seats"]), "invalid_roster")
                deltas = {pid: float(number(v)) for pid, v in raw.items()}
                require(all(number(v) % number(scoring_value(state["settings"], "min_unit")) == 0 for v in deltas.values()), "invalid_unit")
                hand = {"id": str(uuid4()), "number": before["number"] if before else max([h["number"] for h in table["hands"]], default=0) + 1,
                    "deltas": deltas, "at": now(), "actor_id": str(actor), "void": False,
                    "replaces": before["id"] if before else None, "request_id": str(uuid4())}
                table["hands"].append(hand)
                totals = {r["id"]: r["score"] for r in standings(state)}
                names = {p["id"]: p["name"] for p in state["players"]}
                canonical = {"schemaVersion": 1, "kind": "hand", "requestId": hand["request_id"],
                    "tournamentId": tid, "roundId": state["finals"]["id"], "tableNumber": table["number"], "tableId": table["table_id"],
                    "matchId": hand["id"], "handNumber": hand["number"], "submittedAt": hand["at"],
                    "replaces": before["id"] if before else None, "players": [
                        {"id": p, "name": names[p], "seat": "ESWN"[i] if i < 4 else str(i + 1),
                         "rawScore": None, "placement": None, "placementPoints": 0, "gameScore": deltas[p],
                         "cumulativeScore": totals[p]} for i, p in enumerate(table["seats"])]}
                deliveries.append(queue_delivery(db, canonical, actor).id)
            return {"table": table["number"], "before": before, "after": None if action == "undo_hand" else hand,
                    "reason": data.get("reason", "")}
        if action == "finish":
            require(status in {"finals_running", "swiss_finished"}, "invalid_state")
            state["status"] = "ended"
            for session in db.scalars(select(TournamentTableSession).where(TournamentTableSession.tournament_id == tid)):
                session.status = "COMPLETED"
                from .table_membership import release_table
                release_table(db, session.table_id, actor, "tournament_ended", session.id)
            return {}
        if action == "lock":
            require(status == "ended", "invalid_state")
            state["status"] = "locked"
            return {}
        if action == "unlock":
            require(status == "locked" and normalized_name(data.get("reason", "")), "reason_required")
            state["status"] = "ended"
            return {"reason": data["reason"]}
        if action == "resume":
            require(status == "ended" and normalized_name(data.get("reason", "")), "reason_required")
            state["status"] = "finals_running" if state["finals"] and state["finals"]["status"] == "active" else "swiss_finished"
            if state["status"] == "finals_running":
                for table in state["finals"]["tables"]:
                    session = db.get(TournamentTableSession, table["match_id"])
                    session.status = "IN_PROGRESS" if session.started_at or session.legacy else "WAITING_FOR_CHECK_IN"
            return {"reason": data["reason"]}
        raise Conflict("invalid_action", "invalid_action")

    @staticmethod
    def _arrange(tables, seats):
        if seats is None:
            return
        require(isinstance(seats, list) and len(seats) == len(tables) and all(isinstance(group, list)
            and len(group) == len(table["seats"]) for group, table in zip(seats, tables)), "invalid_roster")
        old, new = [p for t in tables for p in t["seats"]], [p for g in seats for p in g]
        require(len(set(new)) == len(new) and set(old) == set(new), "invalid_roster")
        for table, group in zip(tables, seats):
            table["seats"] = group

    @staticmethod
    def _invalidate_delivery(db, key):
        delivery = db.get(ExternalDelivery, key)
        if delivery:
            delivery.status = "manual_review" if delivery.attempts else "cancelled"
            delivery.error_code = "narts_correction" if delivery.adapter == "narts" else "external_correction"
            delivery.updated_at = now()
