import base64
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import io
import json
import sqlite3
from pathlib import Path
import pytest
from PIL import Image

import mahjong_store
from mahjong_api.store import Store
from competition_service import CompetitionService,SLUG,game_score,DEFAULT_RULES
from competition_time import event_time,in_range,phase
import competition_images

@pytest.fixture
def api(tmp_path,monkeypatch):
    monkeypatch.setenv("SITE_TIMEZONE","America/Los_Angeles")
    club=tmp_path/"club.sqlite3";nfc=tmp_path/"nfc.sqlite3";accounts=tmp_path/"accounts.json"
    with closing(mahjong_store.connect(club)):pass
    store=Store(nfc);store.close()
    accounts.write_text(json.dumps({"users":{n:{"name":n,"account_id":"account-"+n,"club_player_id":i+1} for i,n in enumerate("ABCD")}}),encoding="utf-8")
    value=CompetitionService(club,nfc,accounts,tmp_path/"images");value.seed()
    return value

def game(api,when="2026-09-21T12:00:00-07:00",names=None,source="web",match=None):
    with closing(mahjong_store.connect(api.club_path)) as db:
        return mahjong_store.import_game(db,names or list("ABCD"),[40000,30000,20000,10000],when,source=source,nfc_match_id=match)

def board(api):
    api.sync()
    return api.view(SLUG)["leaderboard"]

def config(api):
    return api.view(SLUG,admin=True)["competition"]

@pytest.mark.parametrize("when,count",[("2026-09-20T23:59:59",0),("2026-09-21T00:00:00",4),("2026-09-25T23:59:59",4),("2026-09-26T00:00:00",0),("2026-09-21T06:59:59Z",0),("2026-09-21T07:00:00Z",4),("2026-09-26T06:59:59Z",4),("2026-09-26T07:00:00Z",0)])
def test_date_boundaries(api,when,count):
    game(api,when);assert len(board(api))==count

@pytest.mark.parametrize("placement,total",[(1,7),(2,5),(3,3),(4,2)])
def test_exact_scoring_without_old_formula(placement,total,monkeypatch):
    import mahjong_api.tournament_rules as rules
    monkeypatch.setattr(rules,"score_table",lambda *a:pytest.fail("old formula called"))
    assert tuple(map(float,game_score(placement,DEFAULT_RULES)))==(DEFAULT_RULES["placements"][placement-1],2,total)

@pytest.mark.parametrize("order,total",[(list("ABCD"),14),(list("BACD"),12)])
def test_multiple_games_accumulate(api,order,total):
    game(api);game(api,names=order);assert next(r for r in board(api) if r["name"]=="A")["total"]==total

def test_four_positions_example(api):
    for names in ("ABCD","BACD","BCAD","BCDA"):game(api,names=list(names))
    a=next(r for r in board(api) if r["name"]=="A")
    assert (a["games"],a["placements"],a["placement_score"],a["participation_score"],a["total"])==(4,[1,1,1,1],9,8,17)

@pytest.mark.parametrize("status",["draft","cancelled","canceled","void","voided","deleted","test","duplicate"])
def test_nonfinal_games_excluded(api,status):
    gid=game(api)
    with closing(api.db()) as db,db:db.execute("UPDATE games SET record_status=? WHERE id=?",(status,gid))
    assert board(api)==[]

@pytest.mark.parametrize("field,value",[("is_test",1),("duplicate_of","another")])
def test_invalid_flags(api,field,value):
    gid=game(api)
    with closing(api.db()) as db,db:db.execute("UPDATE games SET "+field+"=? WHERE id=?",(value,gid))
    assert board(api)==[]

def test_play_time_not_created_time(api):
    gid=game(api,"2026-09-25T23:59:59")
    with closing(api.db()) as db,db:db.execute("UPDATE games SET created_at='2026-09-27 00:00:00' WHERE id=?",(gid,))
    assert len(board(api))==4

def test_zero_games_not_enrolled(api):
    assert board(api)==[]
    assert len(config(api)["eligible_users"])==4

def test_repeat_sync_and_unique_constraint(api):
    game(api);before=board(api);assert board(api)==before
    with closing(api.db()) as db:
        assert db.execute("SELECT count(*) FROM competition_participants").fetchone()[0]==4
        row=db.execute("SELECT * FROM competition_scores LIMIT 1").fetchone()
        with pytest.raises(sqlite3.IntegrityError):db.execute("INSERT INTO competition_scores VALUES(?,?,?,?,?,?,?,?,?,?)",tuple(row))

def test_concurrent_reconciliation(api):
    game(api)
    with ThreadPoolExecutor(3) as pool:list(pool.map(lambda _:api.sync(),range(3)))
    assert [p["total"] for p in board(api)]==[7,5,3,2]

def test_rebuild_matches_incremental(api):
    game(api);game(api,names=list("BACD"));original=board(api)
    api.sync(rebuild=SLUG,reason="verify");assert api.view(SLUG)["leaderboard"]==original

def test_correction_void_restore_audited(api):
    gid=game(api);board(api)
    key="club:"+str(gid)
    source=api.games(SLUG)[0]
    positions={p["identity_key"]:5-p["placement"] for p in source["players"]}
    api.correct_game(SLUG,{"game_key":key,"placements":positions,"reason":"rank correction"},"admin")
    assert board(api)[0]["name"]=="D"
    api.correct_game(SLUG,{"game_key":key,"status":"void","reason":"void"},"admin");assert board(api)==[]
    api.correct_game(SLUG,{"game_key":key,"status":"confirmed","reason":"restore"},"admin");assert len(board(api))==4
    with closing(api.db()) as db:assert db.execute("SELECT count(*) FROM competition_audit WHERE action='official_result_correction'").fetchone()[0]==3

def test_existing_game_revert_removes_scores(api):
    gid=game(api);board(api)
    with closing(mahjong_store.connect(api.club_path)) as db:mahjong_store.revert_game(db,gid)
    assert board(api)==[]

def test_old_rank_change_is_detected(api):
    gid=game(api);board(api)
    with closing(api.db()) as db,db:db.execute("UPDATE game_players SET placement=5-placement WHERE game_id=?",(gid,))
    assert board(api)[0]["name"]=="D"

def test_invalid_four_unique_positions(api):
    gid=game(api)
    with closing(api.db()) as db,db:db.execute("UPDATE game_players SET placement=1 WHERE game_id=?",(gid,))
    assert board(api)==[]

def test_parallel_rank_not_hidden_tiebreak(api):
    game(api);game(api,names=list("BACD"));rows=board(api)
    assert [(r["name"],r["rank"]) for r in rows]==[("A",1),("B",1),("C",3),("D",4)]

def test_public_detail_no_identity_keys(api):
    game(api);rows=board(api);body=api.view(SLUG,participant=rows[0]["key"])
    serialized=json.dumps(body)
    assert "account-A" not in serialized and "identity_key" not in serialized and "game_key" not in serialized
    assert len(body["details"])==1 and body["details"][0]["total_score"]==7

def test_search_and_home_top_ten(api):
    for index in range(4):game(api,names=["Other%d-%s"%(index,n) for n in "ABCD"])
    board(api);assert len(api.view(limit=10)["leaderboard"])==10
    assert len(api.view(SLUG)["leaderboard"])==16
    assert len(api.view(SLUG,query="Other2")["leaderboard"])==4

def test_name_change_updates_same_person(api):
    game(api);rows=board(api);key=rows[0]["key"]
    data=json.loads(api.accounts_path.read_text());data["users"]["A"]["name"]="Renamed"
    api.accounts_path.write_text(json.dumps(data),encoding="utf-8")
    renamed=next(r for r in board(api) if r["name"]=="Renamed")
    assert renamed["key"]==key and renamed["total"]==7

def test_seed_is_idempotent_and_keeps_content(api):
    first=api.seed();comp=config(api)
    api.content(SLUG,{**comp["draft"],"title":"Edited","version":comp["version"],"publish":True,"published":True,"featured":True,"leaderboard_public":True},"admin")
    assert api.seed()==first and api.view(SLUG)["competition"]["title"]=="Edited"

@pytest.mark.parametrize("clock,state",[("2026-09-21T06:59:59Z","upcoming"),("2026-09-21T07:00:00Z","live"),("2026-09-26T07:00:00Z","ended")])
def test_server_phase(clock,state):
    assert phase("2026-09-21T07:00:00+00:00","2026-09-26T07:00:00+00:00",clock)==state

def test_content_draft_and_publish_never_changes_scores(api):
    game(api);before=board(api);comp=config(api)
    data={**comp["draft"],"title":"Draft","introduction":"# Heading\n\n- list\n<script>alert(1)</script>","version":comp["version"]}
    api.content(SLUG,data,"admin")
    assert api.view(SLUG)["competition"]["title"]!="Draft"
    comp=config(api);api.content(SLUG,{**data,"version":comp["version"],"publish":True,"published":True,"featured":True,"leaderboard_public":True},"admin")
    assert "<script" not in api.view(SLUG)["competition"]["introduction"]
    assert board(api)==before

def test_unpublished_and_private_board(api):
    game(api);board(api);comp=config(api)
    api.content(SLUG,{**comp["draft"],"version":comp["version"],"publish":True,"published":True,"featured":False,"leaderboard_public":False},"admin")
    assert api.view()["competition"] is None and api.view(SLUG)["leaderboard"]==[]
    assert len(api.view(SLUG,admin=True)["leaderboard"])==4

def rules_data(api):
    comp=config(api)
    return {"version":comp["version"],"confirmation":SLUG,"reason":"approved","rebuild_now":False,"start_at":comp["start_at"],"end_at":comp["end_at"],"rules":{"placements":[6,3,1,0],"participation":2}}

def test_rules_pending_until_explicit_rebuild(api):
    game(api);before=board(api);api.configure(SLUG,rules_data(api),"admin")
    assert board(api)==before
    api.sync(rebuild=SLUG,reason="explicit apply");assert api.view(SLUG)["leaderboard"][0]["total"]==8

@pytest.mark.parametrize("missing",["confirmation","reason","rebuild_now"])
def test_rules_confirmation_required(api,missing):
    data=rules_data(api);data.pop(missing)
    with pytest.raises(ValueError):api.configure(SLUG,data,"admin")

def test_ended_rules_require_super_unlock(api,monkeypatch):
    monkeypatch.setattr("competition_service.phase",lambda *a:"ended")
    data=rules_data(api)
    with pytest.raises(PermissionError):api.configure(SLUG,data,"admin",True)
    api.configure(SLUG,{**data,"unlock_ended":True},"super",True)

def test_timezone_ambiguity():
    with pytest.raises(ValueError):event_time("2026-11-01T01:30:00")
    with pytest.raises(ValueError):event_time("2026-03-08T02:30:00")

def image_data():
    stream=io.BytesIO();Image.new("RGB",(1600,900),"navy").save(stream,"PNG")
    return "data:image/png;base64,"+base64.b64encode(stream.getvalue()).decode()

def test_image_upload_publish_reorder_reference_delete(api):
    first=competition_images.upload(api,{"data":image_data(),"alt":"Cover"},"admin")["image"]
    second=competition_images.upload(api,{"data":image_data(),"alt":"Details"},"admin")["image"]
    with Image.open(api.image_dir/first["src"].split("/")[-1]) as img:assert max(img.size)<=640
    comp=config(api);data={**comp["draft"],"cover":first["key"],"images":[second["key"],first["key"]],"version":comp["version"],"publish":True,"published":True,"featured":True,"leaderboard_public":True}
    api.content(SLUG,data,"admin");view=api.view(SLUG)["competition"]
    assert view["cover"]["alt"]=="Cover" and view["images"][0]["alt"]=="Details"
    with pytest.raises(ValueError,match="still_referenced"):competition_images.delete(api,first["key"],"admin")
    comp=config(api);api.content(SLUG,{**data,"cover":None,"images":[],"version":comp["version"]},"admin")
    competition_images.delete(api,first["key"],"admin")
    assert not (api.image_dir/first["src"].split("/")[-1]).exists()

@pytest.mark.parametrize("payload",["data:image/svg+xml;base64,PHN2Zz4=","data:text/html;base64,PGh0bWw+","data:image/png;base64,SGVsbG8=","data:image/jpeg;base64,AAAA"])
def test_unsafe_images_rejected(api,payload):
    with pytest.raises(ValueError):competition_images.upload(api,{"data":payload},"admin")


def test_expanding_window_rebuild_includes_newly_eligible_games_immediately(api):
    game(api,"2026-09-26T14:00:00-07:00");assert board(api)==[]
    data=rules_data(api);data.update(end_at="2026-09-27T00:00:00",rebuild_now=True,rules=DEFAULT_RULES)
    api.configure(SLUG,data,"admin")
    assert [p["total"] for p in api.view(SLUG)["leaderboard"]]==[7,5,3,2]


def test_source_read_failure_retains_existing_scores(api):
    game(api);original=board(api)
    old=api.nfc_path;api.nfc_path=api.nfc_path.parent/"does-not-exist.sqlite3"
    with pytest.raises(sqlite3.OperationalError):api.sync()
    api.nfc_path=old
    assert api.view(SLUG)["leaderboard"]==original


def test_rule_defaults_use_exact_club_utc_instants(api):
    c=api.view(SLUG)["competition"]
    assert (c["start_at"],c["end_at"],c["timezone"])==("2026-09-21T07:00:00+00:00","2026-09-26T07:00:00+00:00","America/Los_Angeles")
    assert c["published"] and c["auto_enrollment"] and c["leaderboard_public"]
