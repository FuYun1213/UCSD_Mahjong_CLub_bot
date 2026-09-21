"""Import explicitly ordered historical arrays, defaulting to legacy EWSN.

Run: python -m mahjong_api.import_legacy historical.json
Missing start times remain NULL and do not enter duration averages.
"""
import argparse
import json
from datetime import datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select

from .config import Settings
from .database_models import MatchHistory, MatchPlayer, TableState
from .models import Scores, User
from .runtime import single_writer
from .score_mapping import LEGACY_SEATS
from .scoring import calculate_match_result
from .store import Store, elapsed, now


def import_record(store, record):
    order = record.get("source_seat_order", "EWSN")
    if order not in {"EWSN", "ESWN"}:
        raise ValueError("Historical source order must be explicit EWSN or ESWN")
    winds = LEGACY_SEATS if order == "EWSN" else ("east", "south", "west", "north")
    players = [User.model_validate(value) for value in record["players"]]
    if len(players) != 4 or len({str(player.id) for player in players}) != 4 or len(record["scores"]) != 4:
        raise ValueError("Four distinct players and four scores required")
    scores = Scores.model_validate(dict(zip(winds, record["scores"]))).model_dump()
    points = calculate_match_result(scores)
    started_at, ended_at = record.get("started_at"), record.get("ended_at")
    for value in (started_at, ended_at):
        if value and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Historical times must include a timezone")
    if started_at and ended_at and datetime.fromisoformat(ended_at) < datetime.fromisoformat(started_at):
        raise ValueError("End time precedes start time")
    duration = elapsed(started_at, ended_at)
    match_id = str(uuid5(NAMESPACE_URL, "nfc-legacy:" + str(record["source_id"])))
    table_id = str(record["table"])
    result = {"match_id": match_id, "round": int(record["round"]), "table": table_id,
        "played_at": ended_at, "started_at": started_at, "ended_at": ended_at,
        "duration_seconds": duration, "seat_order": "ESWN", "source_seat_order": order,
        "players": {seat: {"user": {"id": str(player.id), "name": player.name}, **points[seat]}
                    for seat, player in zip(winds, players)}}
    with store.connect() as db:
        previous = db.scalar(select(MatchHistory).where(MatchHistory.match_id == match_id))
        if previous:
            if json.loads(previous.result_json) != result:
                raise ValueError("source_id already exists with different data")
            return match_id
        table = db.scalar(select(TableState).where(TableState.table_id == table_id))
        if table is None:
            table = TableState(table_id=table_id, current_match_id=str(uuid4()), updated_at=now())
            db.add(table)
            db.flush()
        elif table.started_at or table.pending_match_id:
            raise ValueError("Import only when the target table has no active round")
        table.round_no = max(table.round_no, result["round"] + 1)
        for player in players:
            store._upsert_user(db, player.id, player.name)
        db.add(MatchHistory(match_id=match_id, table_id=table_id, round_no=result["round"],
            scores_json=json.dumps(scores), result_json=json.dumps(result, ensure_ascii=False),
            started_at=started_at, ended_at=ended_at, duration_seconds=duration,
            seat_order="ESWN", source_seat_order=order))
        db.flush()
        for index, (seat, player) in enumerate(zip(winds, players)):
            db.add(MatchPlayer(match_id=match_id, seat=seat, user_id=str(player.id), user_name=player.name,
                initial_points=25000, final_points=scores[seat], delta_points=scores[seat]-25000, source_position=index))
    return match_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    args = parser.parse_args()
    settings = Settings.from_env()
    with single_writer(settings):
        store = Store(settings.database_path, settings.database_url)
        try:
            with open(args.input, encoding="utf-8") as handle:
                records = json.load(handle)
            for record in records:
                print(import_record(store, record))
        finally:
            store.close()


if __name__ == "__main__":
    main()
