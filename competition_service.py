"""Deterministic materialized score ledger and editable date-window competitions."""
import hashlib
import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from filelock import FileLock
import registered_names
from competition_schema import migrate
from competition_sources import collect, normalize
from competition_time import event_time, in_range, phase, site_timezone, utc_now
from mahjong_api.tournament_rules import PLACEMENT_FIELDS, placement_game_points

SLUG = "2026-09-21-placement-challenge"
DEFAULT_RULES = {"placements":[5,3,1,0],"participation":2}


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False)


def validate_rules(value):
    if not isinstance(value,dict) or set(value)!={"placements","participation"} or not isinstance(value["placements"],list) or len(value["placements"])!=4:
        raise ValueError("invalid_competition_rules")
    numbers=[]
    for item in [*value["placements"],value["participation"]]:
        try:
            if isinstance(item,bool):raise ValueError()
            number=Decimal(str(item))
            if not number.is_finite() or abs(number)>100000 or number.as_tuple().exponent < -4:raise ValueError()
            numbers.append(float(number))
        except (ValueError,InvalidOperation):
            raise ValueError("invalid_competition_rules") from None
    return {"placements":numbers[:4],"participation":numbers[4]}


def game_score(placement, rules):
    if type(placement) is not int or placement not in {1,2,3,4}:
        raise ValueError("invalid_placement")
    settings={**dict(zip(PLACEMENT_FIELDS,rules["placements"])),
              "game_participation_score":rules["participation"]}
    p,a=placement_game_points(placement,settings)
    return str(p),str(a),str(p+a)


def eligible(game, competition):
    players=game["players"]
    return (game["status"]=="confirmed" and len(players)==4 and
        len({p["identity_key"] for p in players})==4 and
        all(type(p.get("placement")) is int for p in players) and
        {p["placement"] for p in players}=={1,2,3,4} and
        in_range(game["played_at"],competition["start_at"],competition["end_at"]))


class CompetitionService:
    def __init__(self, club_path, nfc_path, accounts_path, image_dir):
        self.club_path=Path(club_path).resolve()
        self.nfc_path=Path(nfc_path).resolve() if nfc_path else None
        self.accounts_path=Path(accounts_path).resolve()
        self.image_dir=Path(image_dir).resolve()
        self.lock_path=str(self.club_path)+".competition.lock"

    def db(self):
        db=sqlite3.connect(str(self.club_path),timeout=30)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def initialize(self):
        with FileLock(self.lock_path), closing(self.db()) as db:
            migrate(db)

    @staticmethod
    def audit(db,cid,actor,action,details):
        db.execute("INSERT INTO competition_audit(competition_id,actor,action,details_json,created_at) VALUES(?,?,?,?,?)",
                   (cid,str(actor),action,dump(details),utc_now()))

    def seed(self):
        self.initialize()
        with FileLock(self.lock_path), closing(self.db()) as db, db:
            old=db.execute("SELECT id FROM competitions WHERE slug=?",(SLUG,)).fetchone()
            if old:return old["id"]
            cid=str(uuid4()); stamp=utc_now();zone=site_timezone()
            title="9/21–9/25 Placement Challenge"
            intro="## Everyone is eligible\nNo sign-up is needed. Your first confirmed game during September 21–25 automatically enters the challenge.\n\n## Scoring\n- 1st: 5 placement points\n- 2nd: 3 placement points\n- 3rd: 1 placement point\n- 4th: 0 placement points\n- Participation: 2 points per completed game\n\nGames are counted by their actual play time in the club timezone, including games confirmed after the event."
            content={"title":title,"introduction":intro,"cover":None,"images":[]}
            db.execute("""INSERT INTO competitions(id,slug,title,introduction,timezone,start_at,end_at,scoring_mode,rules_json,
                auto_enrollment,published,featured,leaderboard_public,draft_json,published_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,'placement_and_game_count',?,1,1,1,1,?,?,?,?)""",
                (cid,SLUG,title,intro,zone,event_time("2026-09-21T00:00:00",zone),event_time("2026-09-26T00:00:00",zone),dump(DEFAULT_RULES),dump(content),dump(content),stamp,stamp))
            self.audit(db,cid,"deployment","competition_created",{"slug":SLUG,"rules":DEFAULT_RULES})
            return cid

    def sync(self, rebuild=None, actor="system", reason="source_reconciliation"):
        # Always take account -> competition -> database, never acquire account
        # locks while holding a database write lock used by identity renames.
        with registered_names.account_lock(self.accounts_path), FileLock(self.lock_path):
            accounts=json.loads(self.accounts_path.read_text(encoding="utf-8"))
            games,links,people=collect(self.club_path,self.nfc_path,accounts)
            with closing(self.db()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                stamp=utc_now()
                windows=[dict(r) for r in db.execute("SELECT id,slug,start_at,end_at,pending_rules_json FROM competitions")]
                windows += [json.loads(w["pending_rules_json"]) for w in windows if rebuild in {w["id"],w["slug"]} and w["pending_rules_json"]]
                known={r[0] for r in db.execute("SELECT game_key FROM competition_games")}
                games={key:game for key,game in games.items() if key in known or any(in_range(game["played_at"],window["start_at"],window["end_at"]) for window in windows)}
                for alias,key in links.items():
                    db.execute("INSERT OR IGNORE INTO competition_identity_links(alias,identity_key) VALUES(?,?)",(alias,key))
                for row in db.execute("SELECT * FROM competition_game_overrides"):
                    if row["game_key"] not in games:continue
                    patch=json.loads(row["patch_json"]); game=games[row["game_key"]]
                    for field in ("status","played_at"):
                        if field in patch:game[field]=patch[field]
                    if "placements" in patch:
                        for person in game["players"]:
                            person["placement"]=patch["placements"].get(person["identity_key"],person["placement"])
                for key,game in games.items():
                    fingerprint=hashlib.sha256(dump(game).encode()).hexdigest()
                    old=db.execute("SELECT fingerprint FROM competition_games WHERE game_key=?",(key,)).fetchone()
                    if old and old[0]==fingerprint:continue
                    db.execute("""INSERT INTO competition_games VALUES(?,?,?,?,?,?,?) ON CONFLICT(game_key) DO UPDATE SET
                        played_at=excluded.played_at,status=excluded.status,source=excluded.source,players_json=excluded.players_json,
                        fingerprint=excluded.fingerprint,updated_at=excluded.updated_at""",
                        (key,game["played_at"],game["status"],game["source"],dump(game["players"]),fingerprint,stamp))
                for row in db.execute("SELECT game_key,status FROM competition_games").fetchall():
                    if row[0] not in games and row[1]!="deleted":
                        db.execute("UPDATE competition_games SET status='deleted',updated_at=? WHERE game_key=?",(stamp,row[0]))
                competitions=[dict(r) for r in db.execute("SELECT * FROM competitions")]
                changed=0
                for comp in competitions:
                    cid=comp["id"]
                    if rebuild and rebuild not in {cid,comp["slug"]}:continue
                    if rebuild and comp["pending_rules_json"]:
                        config=json.loads(comp["pending_rules_json"])
                        comp.update(config);comp["rules_version"]+=1
                        db.execute("UPDATE competitions SET start_at=?,end_at=?,rules_json=?,rules_version=?,pending_rules_json=NULL,version=version+1,updated_at=? WHERE id=?",
                            (comp["start_at"],comp["end_at"],comp["rules_json"],comp["rules_version"],stamp,cid))
                    rules=json.loads(comp["rules_json"])
                    wanted={};display_changed=False
                    for game in games.values():
                        if not comp["auto_enrollment"] or not eligible(game,comp):continue
                        for person in game["players"]:
                            row=db.execute("SELECT id,name,avatar FROM competition_participants WHERE competition_id=? AND identity_key=?",(cid,person["identity_key"])).fetchone()
                            if row and (row["name"]!=person["name"] or row["avatar"]!=person.get("avatar","")):display_changed=True
                            pid=row[0] if row else str(uuid4())
                            db.execute("""INSERT INTO competition_participants VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(competition_id,identity_key)
                                DO UPDATE SET name=excluded.name,normalized_name=excluded.normalized_name,participant_type=excluded.participant_type,avatar=excluded.avatar""",
                                (pid,cid,person["identity_key"],person["name"],normalize(person["name"]),person["type"],person.get("avatar", ""),stamp))
                            wanted[(game["game_key"],pid)]=(person["placement"],*game_score(person["placement"],rules),comp["rules_version"])
                    old={(r["game_key"],r["participant_id"]):(r["placement"],r["placement_score"],r["participation_score"],r["total_score"],r["rule_version"]) for r in db.execute("SELECT * FROM competition_scores WHERE competition_id=?",(cid,))}
                    differences=[{"game":k[0],"participant":k[1],"before":old.get(k),"after":wanted.get(k)} for k in sorted(old.keys()|wanted.keys()) if old.get(k)!=wanted.get(k)]
                    if rebuild:db.execute("DELETE FROM competition_scores WHERE competition_id=?",(cid,))
                    for key in old.keys()-wanted.keys():
                        db.execute("DELETE FROM competition_scores WHERE competition_id=? AND game_key=? AND participant_id=?",(cid,*key))
                    for key,values in wanted.items():
                        if not rebuild and old.get(key)==values:continue
                        db.execute("""INSERT INTO competition_scores VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(competition_id,game_key,participant_id)
                            DO UPDATE SET placement=excluded.placement,placement_score=excluded.placement_score,participation_score=excluded.participation_score,
                            total_score=excluded.total_score,rule_version=excluded.rule_version,updated_at=excluded.updated_at""",(cid,*key,*values,stamp,stamp))
                    if differences or rebuild or display_changed:
                        changed+=len(differences)
                        self.audit(db,cid,actor,"leaderboard_rebuilt" if rebuild else "score_reconciled",{"reason":reason,"changes":differences})
                        db.execute("UPDATE competitions SET leaderboard_updated_at=? WHERE id=?",(stamp,cid))
                return {"changed_scores":changed,"games_seen":len(games),"eligible_users":len(people)}

    @staticmethod
    def find(db,slug):
        row=db.execute("SELECT * FROM competitions WHERE slug=? OR id=?",(slug,slug)).fetchone()
        if not row:raise ValueError("competition_not_found")
        return dict(row)

    def board(self,db,cid,query="",limit=None,offset=0):
        # Rules allow at most four decimals. Aggregate integer ten-thousandths
        # so tied totals and fractional corrections retain exact ranking semantics.
        sql = """WITH totals AS (
          SELECT s.participant_id,p.name,p.normalized_name,p.participant_type,p.avatar,
            count(*) AS games,
            sum(s.placement=1) AS firsts,sum(s.placement=2) AS seconds,
            sum(s.placement=3) AS thirds,sum(s.placement=4) AS fourths,
            sum(CAST(round(CAST(s.placement_score AS REAL)*10000) AS INTEGER)) AS placement_total,
            sum(CAST(round(CAST(s.participation_score AS REAL)*10000) AS INTEGER)) AS participation_total,
            sum(CAST(round(CAST(s.total_score AS REAL)*10000) AS INTEGER)) AS score_total
          FROM competition_scores s JOIN competition_participants p ON p.id=s.participant_id
          WHERE s.competition_id=? GROUP BY s.participant_id
        ), ranked AS (SELECT *,rank() OVER (ORDER BY score_total DESC) AS position FROM totals)
        SELECT * FROM ranked WHERE instr(normalized_name,?)>0
        ORDER BY score_total DESC,normalized_name,participant_id"""
        args=[cid,normalize(query)]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?";args.extend([max(0,min(int(limit),100)),max(0,int(offset))])
        return [{"key":hashlib.sha256(row["participant_id"].encode()).hexdigest()[:24],
            "name":row["name"],"type":row["participant_type"],"avatar":row["avatar"],"games":row["games"],
            "placements":[row[k] for k in ("firsts","seconds","thirds","fourths")],
            "placement_score":row["placement_total"]/10000,"participation_score":row["participation_total"]/10000,
            "total":row["score_total"]/10000,"rank":row["position"]} for row in db.execute(sql,args)]

    def image(self,db,key,original=False):
        if not key:return None
        row=db.execute("SELECT i.*,o.original_file,o.width,o.height FROM competition_images i LEFT JOIN competition_image_originals o ON o.image_id=i.id WHERE i.id=?",(key,)).fetchone()
        if not row:return None
        result={"key":row["id"],"src":"/uploads/yakuman/"+row["small_file"],"large":"/uploads/yakuman/"+row["large_file"],"alt":row["alt"],"width":row["width"],"height":row["height"]}
        if original and row["original_file"]:result["original"]="/uploads/yakuman/"+row["original_file"]
        return result

    def view(self,slug=None,admin=False,query="",limit=None,participant=None,offset=0):
        with closing(self.db()) as db:
            if slug:comp=self.find(db,slug)
            else:
                row=db.execute("SELECT * FROM competitions WHERE published=1 AND featured=1 ORDER BY CASE WHEN start_at<=? AND end_at>? THEN 0 WHEN start_at>? THEN 1 ELSE 2 END, CASE WHEN start_at>? THEN start_at END ASC,end_at DESC LIMIT 1",(utc_now(),)*4).fetchone()
                if not row:return {"competition":None,"server_now":utc_now()}
                comp=dict(row)
            if not admin and not comp["published"]:raise ValueError("competition_not_found")
            content=json.loads(comp["draft_json"] if admin else comp["published_json"])
            value={"slug":comp["slug"],"title":content.get("title",comp["title"]),"introduction":content.get("introduction",""),
                "start_at":comp["start_at"],"end_at":comp["end_at"],"timezone":comp["timezone"],"phase":phase(comp["start_at"],comp["end_at"]),
                "rules":json.loads(comp["rules_json"]),"auto_enrollment":bool(comp["auto_enrollment"]),"leaderboard_public":bool(comp["leaderboard_public"]),
                "cover":self.image(db,content.get("cover")),"images":[self.image(db,k) for k in content.get("images",[]) if self.image(db,k)],
                "updated_at":comp["leaderboard_updated_at"] or comp["created_at"],"published":bool(comp["published"])}
            visible=admin or comp["leaderboard_public"]
            leaderboard=self.board(db,comp["id"],query,limit,offset) if visible else []
            total=db.execute("SELECT count(DISTINCT participant_id) FROM competition_scores WHERE competition_id=?",(comp["id"],)).fetchone()[0] if visible else 0
            details=[]
            if participant and (admin or comp["leaderboard_public"]):
                participant=next((r[0] for r in db.execute("SELECT id FROM competition_participants WHERE competition_id=?",(comp["id"],)) if hashlib.sha256(r[0].encode()).hexdigest()[:24]==participant),"")
                for r in db.execute("SELECT s.*,g.played_at,g.source FROM competition_scores s JOIN competition_games g ON g.game_key=s.game_key WHERE s.competition_id=? AND s.participant_id=? ORDER BY g.played_at DESC",(comp["id"],participant)):
                    details.append({k:(float(r[k]) if k in {"placement_score","participation_score","total_score"} else r[k]) for k in ("played_at","source","placement","placement_score","participation_score","total_score")})
            if admin:
                value.update(version=comp["version"],featured=bool(comp["featured"]),draft=content,pending_rules=bool(comp["pending_rules_json"]))
                value["available_images"]=[self.image(db,r[0],original=True) for r in db.execute("SELECT id FROM competition_images ORDER BY created_at DESC")]
                with registered_names.account_lock(self.accounts_path):
                    accounts=json.loads(self.accounts_path.read_text(encoding="utf-8"))
                    _,_,eligible_users=collect(self.club_path,self.nfc_path,accounts)
                value["eligible_users"]=[{"name":p["name"],"type":p["type"]} for p in sorted(eligible_users,key=lambda p:normalize(p["name"]))]
                value["audit_count"]=db.execute("SELECT count(*) FROM competition_audit WHERE competition_id=?",(comp["id"],)).fetchone()[0]
            return {"competition":value,"leaderboard":leaderboard,"participant_count":total,"offset":offset,"has_more":bool(limit and len(leaderboard)==limit),"details":details,"server_now":utc_now()}

    def content(self,slug,data,actor):
        title=str(data.get("title","")).strip();intro=str(data.get("introduction",""))
        if not 1<=len(title)<=160 or len(intro)>20000:raise ValueError("invalid_competition_content")
        import re
        # HTML is not part of the supported Markdown subset; rendering also uses
        # React text nodes exclusively, never dangerouslySetInnerHTML.
        intro=re.sub(r"<[^>]*>","",intro)
        content={"title":title,"introduction":intro,"cover":data.get("cover") or None,"images":data.get("images",[])}
        if not isinstance(content["images"],list) or len(content["images"])>12 or any(not isinstance(k,str) for k in content["images"]):raise ValueError("invalid_images")
        if content["cover"] is not None and not isinstance(content["cover"],str):raise ValueError("invalid_images")
        with FileLock(self.lock_path), closing(self.db()) as db, db:
            comp=self.find(db,slug)
            if data.get("version")!=comp["version"]:raise ValueError("competition_changed_refresh")
            for key in [content["cover"],*content["images"]]:
                if key and not db.execute("SELECT 1 FROM competition_images WHERE id=?",(key,)).fetchone():raise ValueError("image_not_found")
            self.audit(db,comp["id"],actor,"content_publish" if data.get("publish") else "content_draft",{"before":json.loads(comp["draft_json"]),"after":content})
            db.execute("UPDATE competitions SET draft_json=?,version=version+1,updated_at=? WHERE id=?",(dump(content),utc_now(),comp["id"]))
            if data.get("publish"):
                for flag in ("published","featured","leaderboard_public"):
                    if type(data.get(flag)) is not bool:raise ValueError("invalid_publish_flags")
                db.execute("UPDATE competitions SET title=?,introduction=?,published_json=?,published=?,featured=?,leaderboard_public=? WHERE id=?",
                    (title,intro,dump(content),int(data["published"]),int(data["featured"]),int(data["leaderboard_public"]),comp["id"]))
        return {"ok":True}

    def configure(self,slug,data,actor,super_admin=False,background=False):
        with FileLock(self.lock_path), closing(self.db()) as db, db:
            comp=self.find(db,slug)
            if data.get("version")!=comp["version"]:raise ValueError("competition_changed_refresh")
            if data.get("confirmation")!=comp["slug"] or not str(data.get("reason","")).strip() or type(data.get("rebuild_now")) is not bool:raise ValueError("rules_confirmation_required")
            if phase(comp["start_at"],comp["end_at"])=="ended" and not (super_admin and data.get("unlock_ended") is True):raise PermissionError("ended_competition_locked")
            config={"rules_json":dump(validate_rules(data.get("rules"))),"start_at":event_time(data.get("start_at"),comp["timezone"]),"end_at":event_time(data.get("end_at"),comp["timezone"])}
            if config["start_at"]>=config["end_at"]:raise ValueError("invalid_date_range")
            self.audit(db,comp["id"],actor,"rules_change_requested",{"before":{k:comp[k] for k in config},"after":config,"reason":data["reason"],"rebuild_now":data["rebuild_now"]})
            db.execute("UPDATE competitions SET pending_rules_json=?,version=version+1,updated_at=? WHERE id=?",(dump(config),utc_now(),comp["id"]))
            if background and data["rebuild_now"]:
                return {"ok":True,"pending_rebuild":True,"job":self.enqueue(db,comp,True,actor,data["reason"],data)}
        if data["rebuild_now"]:self.sync(rebuild=slug,actor=actor,reason=data["reason"])
        return {"ok":True,"pending_rebuild":not data["rebuild_now"]}

    def correct_game(self,slug,data,actor,background=False):
        reason=str(data.get("reason","")).strip();key=data.get("game_key")
        if not reason or len(reason)>500:raise ValueError("reason_required")
        with FileLock(self.lock_path), closing(self.db()) as db, db:
            comp=self.find(db,slug);row=db.execute("SELECT * FROM competition_games WHERE game_key=?",(key,)).fetchone()
            if not row:raise ValueError("game_not_found")
            previous=db.execute("SELECT patch_json FROM competition_game_overrides WHERE game_key=?",(key,)).fetchone()
            patch=json.loads(previous[0]) if previous else {}
            if "status" in data:
                if data["status"] not in {"confirmed","void","cancelled","test","duplicate"}:raise ValueError("invalid_game_status")
                patch["status"]=data["status"]
            if "played_at" in data:patch["played_at"]=event_time(data["played_at"],comp["timezone"])
            if "placements" in data:
                positions=data["placements"];players=json.loads(row["players_json"])
                if not isinstance(positions,dict) or set(positions)!={p["identity_key"] for p in players} or any(type(v) is not int for v in positions.values()) or set(positions.values())!={1,2,3,4}:raise ValueError("invalid_placements")
                patch["placements"]=positions
            self.audit(db,comp["id"],actor,"official_result_correction",{"game":key,"before":json.loads(previous[0]) if previous else {},"after":patch,"reason":reason})
            db.execute("INSERT INTO competition_game_overrides VALUES(?,?,?,?,?) ON CONFLICT(game_key) DO UPDATE SET patch_json=excluded.patch_json,reason=excluded.reason,actor=excluded.actor,updated_at=excluded.updated_at",(key,dump(patch),reason,str(actor),utc_now()))
            if background:return {"job":self.enqueue(db,comp,False,actor,reason,data)}
        return self.sync(actor=actor,reason=reason)

    def games(self,slug):
        with closing(self.db()) as db:
            comp=self.find(db,slug)
            return [{**dict(r),"players":json.loads(r["players_json"])} for r in db.execute("SELECT * FROM competition_games WHERE played_at>=? AND played_at<? ORDER BY played_at DESC",(comp["start_at"],comp["end_at"]))]

    def enqueue(self,db,comp,rebuild,actor,reason,payload):
        key=hashlib.sha256(dump([comp["id"],comp["version"],rebuild,payload]).encode()).hexdigest()
        job=str(uuid4())
        db.execute("INSERT OR IGNORE INTO competition_jobs(id,competition_id,rebuild,actor,reason,request_key,created_at) VALUES(?,?,?,?,?,?,?)",
            (job,comp["id"],int(rebuild),str(actor),str(reason)[:500],key,utc_now()))
        return dict(db.execute("SELECT id,status FROM competition_jobs WHERE request_key=?",(key,)).fetchone())

    def queue_rebuild(self,slug,data,actor):
        with FileLock(self.lock_path),closing(self.db()) as db,db:
            return {"job":self.enqueue(db,self.find(db,slug),True,actor,data["reason"],data)}

    def jobs(self,slug):
        with closing(self.db()) as db:
            comp=self.find(db,slug)
            return {"jobs":[dict(row) for row in db.execute("SELECT id,status,attempts,error_code,created_at,finished_at FROM competition_jobs WHERE competition_id=? ORDER BY created_at DESC LIMIT 10",(comp["id"],))]}

    def process_jobs(self):
        # This process-independent worker lock outlives individual short DB transactions.
        # A crash releases it; the persisted lease makes interrupted work retryable.
        with FileLock(self.lock_path+".jobs"):
            with closing(self.db()) as db,db:
                db.execute("BEGIN IMMEDIATE")
                job=db.execute("SELECT * FROM competition_jobs WHERE (status IN ('pending','retrying') AND available_at<=?) OR (status='processing' AND lease_until<=?) ORDER BY created_at LIMIT 1",(time.time(),time.time())).fetchone()
                if job is None:return False
                job=dict(job)
                db.execute("UPDATE competition_jobs SET status='processing',attempts=attempts+1,lease_until=? WHERE id=?",(time.time()+300,job["id"]))
            try:
                self.sync(rebuild=job["competition_id"] if job["rebuild"] else None,actor=job["actor"],reason=job["reason"])
            except Exception:
                logging.getLogger(__name__).exception("Competition background job failed")
                with closing(self.db()) as db,db:
                    db.execute("UPDATE competition_jobs SET status=?,available_at=?,lease_until=NULL,error_code='rebuild_failed' WHERE id=?",
                        ("failed" if job["attempts"]>=4 else "retrying",time.time()+min(300,2**(job["attempts"]+1)),job["id"]))
            else:
                with closing(self.db()) as db,db:
                    db.execute("UPDATE competition_jobs SET status='succeeded',finished_at=?,lease_until=NULL,error_code=NULL WHERE id=?",(utc_now(),job["id"]))
            return True

    def start_worker(self,interval=10):
        stop=threading.Event()
        def run():
            while not stop.is_set():
                try:
                    self.process_jobs()
                    self.sync()
                except Exception:logging.getLogger(__name__).exception("Competition reconciliation failed; existing scores retained")
                stop.wait(interval)
        thread=threading.Thread(target=run,name="competition-reconciler",daemon=True);thread.start()
        return stop
