"""Read committed official results; no dependence on Sheets/Discord delivery success."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import unicodedata
from competition_time import event_time


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()


def read(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("BEGIN")
    return db


def rows(db, table):
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return [dict(r) for r in db.execute('SELECT * FROM "' + table + '"')] if present else []


def invalid(record):
    return any(record.get(k) for k in ("is_test", "test", "test_data", "deleted_at", "cancelled_at", "cancelled", "deleted", "void", "voided", "is_duplicate", "duplicate_of", "duplicate")) or str(record.get("status", "")).lower() in {"draft", "cancelled", "canceled", "void", "voided", "deleted", "test", "duplicate", "invalidated"}


def safe_time(value):
    try:
        return event_time(value) if value else None
    except ValueError:
        return None


def collect(club_path, nfc_path, accounts):
    """Caller holds the account lock; both database snapshots finish before writes."""
    with closing(read(club_path)) as db:
        club_players = rows(db, "players")
        club_games, game_players = rows(db, "games"), rows(db, "game_players")
        links = {r["alias"]:r["identity_key"] for r in rows(db, "competition_identity_links")}
        tombstones = {r["game_key"] for r in rows(db, "competition_game_tombstones")}
    nfc = {}
    if nfc_path:
        with closing(read(nfc_path)) as db:
            nfc = {name:rows(db,name) for name in ("nfc_matches", "manual_score_drafts", "tournaments", "tournament_table_sessions", "tournament_participants")}
    people, account_by_id, club_by_id = {}, {}, {str(p["id"]):p for p in club_players}
    club_by_name = {normalize(p["name"]):str(p["id"]) for p in club_players}
    for legacy, account in accounts.get("users", {}).items():
        uid = str(account.get("account_id") or "")
        if not uid:
            continue
        name = account.get("name") or legacy
        key = "account:" + uid
        account_by_id[uid] = key
        people[key] = {"identity_key":key,"name":name,"type":"registered", "avatar":account.get("avatar") or account.get("discord_avatar") or ""}
        cid = str(account.get("club_player_id") or "")
        # Legacy account directory predates club_player_id. Resolve its already
        # unique registered name once, then persist the relation across renames.
        if not cid:
            cid = uid[5:] if uid.startswith("club-") else club_by_name.get(normalize(name), "")
        if cid in club_by_id:
            alias = "club:" + cid
            if alias in links and links[alias] != key:
                raise ValueError("competition_identity_conflict")
            links[alias] = key
    for cid,p in club_by_id.items():
        alias = "club:"+cid
        key = links.get(alias, alias)
        people.setdefault(key, {"identity_key":key,"name":p["name"],"type":"player","avatar":""})
    guests = {str(p["id"]):p for p in nfc.get("tournament_participants",[])}
    def identity(uid, name, tid=None, roster=None):
        uid = str(uid)
        guest = guests.get(uid)
        if guest:
            target = guest.get("merged_into_user_id") or guest.get("user_id")
            if target and str(target) in account_by_id:
                return people[account_by_id[str(target)]]
            key = "guest:"+guest["tournament_id"]+":"+uid
            people[key] = {"identity_key":key,"name":guest["name"],"type":"guest","avatar":""}
            return people[key]
        bound = (roster or {}).get("account_id")
        if bound and str(bound) in account_by_id:
            return people[account_by_id[str(bound)]]
        if uid in account_by_id:
            return people[account_by_id[uid]]
        if uid.startswith("club-") and uid[5:] in club_by_id:
            alias = "club:"+uid[5:]
            return people[links.get(alias,alias)]
        key = ("guest:"+str(tid)+":"+uid) if tid else "legacy:"+uid
        people[key] = {"identity_key":key,"name":name,"type":"guest" if tid else "player","avatar":""}
        return people[key]
    for guest in guests.values():
        identity(guest["id"],guest["name"],guest["tournament_id"])
    games = {}
    def add_result(result, match_id, source, eligible=True):
        players = result.get("players",{})
        winds = ("east","south","west","north")
        if not isinstance(players,dict) or set(players)!=set(winds):
            return
        try:
            order = sorted(winds,key=lambda w:(-players[w]["final_points"],winds.index(w)))
            entries = [{**identity(players[w]["user"]["id"],players[w]["user"]["name"]),"placement":order.index(w)+1} for w in winds]
        except (KeyError,TypeError):
            return
        key = "match:"+str(match_id)
        games[key] = {"game_key":key,"played_at":safe_time(result.get("authoritative_played_at") or result.get("started_at")),
            "status":"confirmed" if eligible and not invalid(result) else "void", "source":source,"players":entries}
    for record in nfc.get("nfc_matches",[]):
        add_result(json.loads(record["result_json"]),record["match_id"],"photo")
    for record in nfc.get("manual_score_drafts",[]):
        if record["status"] == "submitted" and record.get("result_json"):
            add_result(json.loads(record["result_json"]),record["match_id"],"manual")
    sessions = {r["id"]:r for r in nfc.get("tournament_table_sessions",[])}
    for record in nfc.get("tournaments",[]):
        state = json.loads(record["state_json"])
        roster = {str(p["id"]):p for p in state.get("players",[])}
        for rnd in state.get("rounds",[]):
            for table in rnd.get("tables",[]):
                result = table.get("result")
                if not result or not table.get("match_id"):
                    continue
                entries = [{**identity(p["id"],p["name"],record["id"],roster.get(str(p["id"]))),"placement":p.get("placement")} for p in result.get("players",[])]
                key = "match:"+table["match_id"]
                session = sessions.get(table["match_id"],{})
                eligible = rnd.get("status")=="confirmed" and not any(invalid(r) for r in (record,state,rnd,table,result))
                games[key] = {"game_key":key,"played_at":safe_time(session.get("started_at")),"status":"confirmed" if eligible else "void","source":"tournament","players":entries}
    by_game = {}
    for p in game_players:
        by_game.setdefault(p["game_id"],[]).append(p)
    for record in club_games:
        key = "match:"+record["nfc_match_id"] if record.get("nfc_match_id") else "club:"+str(record["id"])
        prior = games.get(key)
        # Synced NFC rows are a projection of one result, never a second game.
        # Keep its account/Guest identity; club positions reflect admin corrections.
        entries = prior["players"] if prior else [{**people[links.get("club:"+str(p["player_id"]),"club:"+str(p["player_id"]))],"placement":p["placement"]} for p in by_game.get(record["id"],[]) if str(p["player_id"]) in club_by_id]
        if prior:
            by_name = {normalize(club_by_id[str(p["player_id"])]["name"]):p["placement"] for p in by_game.get(record["id"],[]) if str(p["player_id"]) in club_by_id}
            if len(by_name)==4 and all(normalize(p["name"]) in by_name for p in entries):
                entries = [{**p,"placement":by_name[normalize(p["name"])]} for p in entries]
        stamp = record.get("authoritative_played_at") or (prior or {}).get("played_at") or record.get("started_at")
        # Legacy web/Discord/sheet played_at is the declared Game Record time.
        # Legacy NFC/manual played_at was submission time: never use that fallback.
        if not stamp and record["source"] not in {"nfc","manual","photo"}:
            stamp = record["played_at"]
        eligible = record.get("record_status","confirmed")=="confirmed" and record["source"] not in {"test","draft","duplicate"} and not invalid(record) and (not prior or prior["status"]=="confirmed")
        games[key] = {"game_key":key,"played_at":safe_time(stamp),"status":"confirmed" if eligible else "void", "source":record["source"],"players":entries}
    for key in tombstones:
        if key in games:
            games[key]["status"]="deleted"
    return games, links, list(people.values())
