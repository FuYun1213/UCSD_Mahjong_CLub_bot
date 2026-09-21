"""Compatibility bridge for the optional pre-photo website recording endpoint."""
import json
from pathlib import Path
from sqlalchemy import select
from .config import Settings
from .store import Store
from .external_sync import ExternalSync, queue_delivery
from .tournament_models import ExternalDelivery


def sync_legacy(game_id, played_at, entries, club_path, actor=""):
    # Keep the old website route using the same adapter/configuration as NFC.
    # Re-read its immutable SQL game rather than relying on mutable player names.
    import sqlite3
    with sqlite3.connect(Path(club_path).resolve().as_uri()+"?mode=ro", uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute("""SELECT p.id,p.name,gp.final_score,gp.placement,gp.pt_delta,
            gp.seat_wind FROM game_players gp JOIN players p ON p.id=gp.player_id
            WHERE gp.game_id=?""",(game_id,)).fetchall()
        totals={r["id"]:db.execute("SELECT COALESCE(SUM(pt_delta),0) FROM game_players WHERE player_id=? AND game_id<=?",
            (r["id"],game_id)).fetchone()[0] for r in rows}
    canonical={"schemaVersion":1,"kind":"match","requestId":f"legacy-sql-{game_id}",
        "tournamentId":None,"roundId":None,"tableNumber":None,"matchId":f"sql-{game_id}",
        "submittedAt":played_at,"players":[{"id":f"club-{r['id']}","name":r["name"],
            "seat":r["seat_wind"][0].upper(),"rawScore":r["final_score"],"placement":r["placement"],
            "placementPoints":round(r["pt_delta"]-(r["final_score"]-30000)/1000,6),
            "gameScore":r["pt_delta"],"cumulativeScore":totals[r["id"]]} for r in rows]}
    settings=Settings.from_env()
    store=Store(settings.database_path,settings.database_url)
    try:
        with store.connect() as db:
            existing=db.get(ExternalDelivery,canonical["requestId"])
            if existing is None:
                queue_delivery(db,canonical,actor)
        result=ExternalSync(store).send(canonical["requestId"],actor)
        return {**result,"enabled":result["status"]!="disabled","ok":result["status"]=="success"}
    finally:
        store.close()
