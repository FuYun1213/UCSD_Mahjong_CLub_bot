"""SQLAlchemy persistence. Network I/O happens only after database commits."""
import json
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, delete, event, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from .database_models import (
    IdempotencyRecord, MatchHistory, MatchPlayer, Metadata, ScoreDraft,
    SeatRecord, TableState, User as Account,
)
from .migrations import migrate
from .models import SEATS, User


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def elapsed(start, end):
    if not start or not end:
        return None
    return max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))


class Conflict(Exception):
    def __init__(self, code, message, **extra):
        self.detail = {"code": code, "message": message, **extra}
        super().__init__(message)


class Store:
    def __init__(self, path: Path, database_url: str = ""):
        self.path = path
        if not database_url:
            path.parent.mkdir(parents=True, exist_ok=True)
            database_url = "sqlite:///" + path.resolve().as_posix()
        url = make_url(database_url)
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 30} if url.get_backend_name() == "sqlite" else {})
        if url.get_backend_name() == "sqlite":
            @event.listens_for(self.engine, "connect")
            def configure_sqlite(connection, record):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        migrate(self.engine)

    @contextmanager
    def connect(self):
        with self.sessions() as db, db.begin():
            yield db

    def close(self):
        self.engine.dispose()

    @staticmethod
    def _table(db, table_id):
        table = db.scalar(select(TableState).where(TableState.table_id == table_id))
        if table is None:
            return None
        result = {name: getattr(table, name) for name in (
            "slot", "table_id", "round_no", "current_match_id", "pending_match_id", "updated_at", "started_at", "dirty")}
        result["seats"] = dict.fromkeys(SEATS)
        for seat in db.scalars(select(SeatRecord).where(SeatRecord.table_id == table_id)):
            result["seats"][seat.seat] = {"id": seat.user_id, "name": seat.user_name}
        return result

    def table(self, table_id):
        with self.connect() as db:
            return self._table(db, table_id)

    @staticmethod
    def _upsert_user(db, uid, name):
        user = db.get(Account, str(uid))
        if user is None:
            user = Account(id=str(uid), name=name)
            db.add(user)
        else:
            user.name = name
        db.flush()

    def sit(self, table_id, seat, user: User):
        from .table_membership import membership_lock, ordinary_join
        with membership_lock, self.connect() as db:
            table = db.scalar(select(TableState).where(TableState.table_id == table_id))
            if table is None:
                # Legacy internal callers retain the creation path. Public routes
                # require an admin-created registry entry before calling this.
                table = TableState(table_id=table_id, current_match_id=str(uuid4()), updated_at=now())
                db.add(table)
                db.flush()
            ordinary_join(db, table, user, user.id, "manual", seat)
            return {table_id}

    @staticmethod
    def _match(row):
        if row is None:
            return None
        return {
            "sequence": row.sequence, "match_id": row.match_id, "table_id": row.table_id,
            "round_no": row.round_no, "scores": json.loads(row.scores_json),
            "result": json.loads(row.result_json), "history_synced": row.history_synced,
            "clear_synced": row.clear_synced,
        }

    def match(self, match_id):
        with self.connect() as db:
            return self._match(db.scalar(select(MatchHistory).where(MatchHistory.match_id == match_id)))

    def stage_match(self, table_id, scores, points, expected_match_id, request_key,
                    uploader_id=None, ended_at=None, draft_id=None, roster=None, session=None, authoritative_played_at=None):
        with (nullcontext(session) if session is not None else self.connect()) as db:
            existing = None
            if request_key:
                key = db.get(IdempotencyRecord, request_key)
                if key:
                    existing = db.scalar(select(MatchHistory).where(MatchHistory.match_id == key.match_id))
            if existing is None and expected_match_id:
                existing = db.scalar(select(MatchHistory).where(MatchHistory.match_id == expected_match_id))
            table = self._table(db, table_id)
            if existing is None and table and table["pending_match_id"]:
                existing = db.scalar(select(MatchHistory).where(MatchHistory.match_id == table["pending_match_id"]))
            if existing is not None:
                match = self._match(existing)
                if match["table_id"] != table_id or match["scores"] != scores or (expected_match_id and match["match_id"] != expected_match_id):
                    raise Conflict("submission_conflict", "同一对局或幂等键已提交不同数据，请人工核对")
                if roster is not None and ({s: match["result"]["players"][s]["user"]["id"] for s in SEATS} !=
                                           {s: roster[s]["id"] for s in SEATS}):
                    raise Conflict("submission_conflict", "submission_conflict")
                if request_key and db.get(IdempotencyRecord, request_key) is None:
                    db.add(IdempotencyRecord(request_key=request_key, match_id=match["match_id"]))
                return match["match_id"], True
            if expected_match_id and (table is None or table["current_match_id"] != expected_match_id):
                raise Conflict("stale_match", "对局编号已失效，请重新读取当前桌状态")
            if roster is not None:
                if table is None or set(roster) != set(SEATS) or len({str(p["id"]) for p in roster.values()}) != 4:
                    raise Conflict("incomplete_table", "incomplete_table")
                for seat in SEATS:
                    occupied = table["seats"][seat]
                    if occupied and occupied["id"] != roster[seat]["id"]:
                        raise Conflict("stale_roster", "stale_roster")
                    person = db.get(Account, str(roster[seat]["id"]))
                    if person is None:
                        db.add(Account(id=str(roster[seat]["id"]), name=roster[seat]["name"]))
                    else:
                        person.name = roster[seat]["name"]
                table["seats"] = roster
                db.flush()
            missing = [seat for seat in SEATS if table is None or table["seats"][seat] is None]
            if missing:
                raise Conflict("incomplete_table", "座位未满，请等待四位玩家入座", missing_seats=missing)
            end = ended_at or now()
            duration = elapsed(table["started_at"], end)
            match_id = table["current_match_id"]
            from .tournament_rules import DEFAULT_NAMES
            labels = db.get(Metadata, "table_names_v1")
            table_label = (json.loads(labels.value) if labels else {}).get(str(table_id)) or DEFAULT_NAMES.get(str(table_id), str(table_id))
            from .table_models import ClubTable
            registry = db.scalar(select(ClubTable).where(ClubTable.score_table_id == str(table_id)))
            if registry and (registry.display_name or registry.score_table_id == registry.id or str(registry.number) != str(table_id)):
                table_label = registry.display_name or str(registry.number)
            result = {
                "match_id": match_id, "round": table["round_no"], "table": table_id, "table_name": table_label,
                "played_at": end, "started_at": table["started_at"], "ended_at": end,
                "authoritative_played_at": authoritative_played_at or table["started_at"],
                "played_at_source": "declared_game_time" if authoritative_played_at else "table_started_at",
                "duration_seconds": duration, "seat_order": "ESWN", "source_seat_order": "ESWN",
                "uploader_id": uploader_id, "draft_id": draft_id,
                "players": {seat: {"user": table["seats"][seat], **points[seat]} for seat in SEATS},
            }
            match = MatchHistory(match_id=match_id, table_id=table_id, round_no=table["round_no"],
                scores_json=json.dumps(scores), result_json=json.dumps(result, ensure_ascii=False),
                started_at=table["started_at"], ended_at=end, duration_seconds=duration,
                uploader_id=uploader_id, seat_order="ESWN", source_seat_order="ESWN")
            db.add(match)
            db.flush()
            for index, seat in enumerate(SEATS):
                player = result["players"][seat]
                db.add(MatchPlayer(match_id=match_id, seat=seat, user_id=str(player["user"]["id"]),
                    user_name=player["user"]["name"], initial_points=player["initial_points"],
                    final_points=player["final_points"], delta_points=player["delta_points"], source_position=index))
            db.flush()
            from .external_sync import queue_free_match
            queue_free_match(db, result)
            state = db.scalar(select(TableState).where(TableState.table_id == table_id))
            state.pending_match_id = match_id
            if request_key:
                db.add(IdempotencyRecord(request_key=request_key, match_id=match_id))
            if draft_id:
                db.get(ScoreDraft, draft_id).status = "submitted"
            return match_id, False

    def pending_matches(self):
        with self.connect() as db:
            return [self._match(row) for row in db.scalars(select(MatchHistory).where(MatchHistory.history_synced == 0).order_by(MatchHistory.sequence))]

    def finish_history(self, match_id):
        with self.connect() as db:
            state = db.scalar(select(TableState).where(TableState.pending_match_id == match_id))
            if state:
                from .table_models import ClubTable
                from .table_membership import release_table
                registered = db.scalar(select(ClubTable).where(ClubTable.score_table_id == state.table_id))
                if registered:
                    release_table(db, registered.id, "settlement", "completed", match_id)
                db.execute(delete(SeatRecord).where(SeatRecord.table_id == state.table_id))
                state.pending_match_id = None
                state.current_match_id = str(uuid4())
                state.round_no += 1
                state.started_at = None
                state.dirty, state.updated_at = 1, now()
            db.execute(update(MatchHistory).where(MatchHistory.match_id == match_id).values(history_synced=1))

    def dirty_tables(self):
        with self.connect() as db:
            return [self._table(db, row.table_id) for row in db.scalars(select(TableState).where(TableState.dirty == 1).order_by(TableState.slot))]

    def finish_current(self, table_id):
        with self.connect() as db:
            db.execute(update(TableState).where(TableState.table_id == table_id).values(dirty=0))
            db.execute(update(MatchHistory).where(MatchHistory.table_id == table_id, MatchHistory.history_synced == 1).values(clear_synced=1))

    def pending_counts(self):
        with self.connect() as db:
            return {
                "tables": db.scalar(select(func.count()).select_from(TableState).where(TableState.dirty == 1)),
                "matches": db.scalar(select(func.count()).select_from(MatchHistory).where((MatchHistory.history_synced == 0) | (MatchHistory.clear_synced == 0))),
            }

    def configure_sync_target(self, target):
        with self.connect() as db:
            old = db.get(Metadata, "sync_target")
            if old is not None and old.value != target:
                db.execute(update(TableState).values(dirty=1))
                db.execute(update(MatchHistory).values(history_synced=0, clear_synced=0))
            if old is None:
                db.add(Metadata(key="sync_target", value=target))
            else:
                old.value = target

    def stats(self, table_id=None, user_id=None):
        with self.connect() as db:
            query = select(func.count(MatchHistory.duration_seconds), func.avg(MatchHistory.duration_seconds)).where(MatchHistory.duration_seconds.is_not(None))
            if table_id:
                query = query.where(MatchHistory.table_id == table_id)
            if user_id:
                query = query.where(MatchHistory.match_id.in_(select(MatchPlayer.match_id).where(MatchPlayer.user_id == str(user_id))))
            count, average = db.execute(query).one()
            return {"completed_matches_with_duration": count,
                "average_duration_seconds": round(float(average), 2) if average is not None else None}

    @staticmethod
    def _draft(row):
        if row is None:
            return None
        value = {column.name: getattr(row, column.name) for column in ScoreDraft.__table__.columns}
        for field in ("roster", "raw", "normalized", "issues"):
            value[field] = json.loads(value.pop(field + "_json"))
        return value

    def draft(self, draft_id):
        with self.connect() as db:
            return self._draft(db.get(ScoreDraft, draft_id))

    def find_draft(self, table_id, user_id, match_id=None, request_key=None):
        with self.connect() as db:
            if request_key:
                row = db.scalar(select(ScoreDraft).where(ScoreDraft.request_key == request_key))
                if row:
                    return self._draft(row)
            if match_id:
                row = db.scalar(select(ScoreDraft).where(ScoreDraft.table_id == table_id,
                    ScoreDraft.uploader_id == str(user_id), ScoreDraft.match_id == match_id).order_by(ScoreDraft.created_at.desc()))
                return self._draft(row)

    def save_draft(self, value):
        with self.connect() as db:
            record = dict(value)
            for field in ("roster", "raw", "normalized", "issues"):
                record[field + "_json"] = json.dumps(record.pop(field), ensure_ascii=False)
            db.add(ScoreDraft(**record))

    def update_draft_scores(self, draft_id, scores, issues):
        with self.connect() as db:
            draft = db.get(ScoreDraft, draft_id)
            draft.normalized_json = json.dumps(scores)
            draft.issues_json = json.dumps(issues, ensure_ascii=False)


    def round_end(self, match_id):
        with self.connect() as db:
            return db.scalar(select(func.min(ScoreDraft.ended_at)).where(ScoreDraft.match_id == match_id))
