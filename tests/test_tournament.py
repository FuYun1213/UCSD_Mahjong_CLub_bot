import copy
import io
import json
import random
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import requests
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, func

from mahjong_api.auth import get_current_user
from mahjong_api.config import Settings
from mahjong_api.database_models import User as Account
from mahjong_api.external_sync import ExternalSync, build_payload, queue_delivery, validate_endpoint
from mahjong_api.main import create_app
from mahjong_api.models import User
from mahjong_api.sheets import DisabledSheets
from mahjong_api.store import Store, Conflict
from mahjong_api.tournament import TournamentService
from mahjong_api.tournament_models import ExternalDelivery, TournamentAudit
from mahjong_api.tournament_rules import DEFAULT_SETTINGS, DEFAULT_NAMES, comeback, pair_round, standings, table_name


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.delenv("NARTS_EXTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("NARTS_EXTERNAL_API_ENDPOINT", raising=False)
    store = Store(tmp_path / "tournaments.sqlite3")
    calls = []
    def transport(endpoint, adapter, body, method):
        calls.append(copy.deepcopy((endpoint, body, method)))
        return (201, {"match": {"id": "remote-1"}, "playerMappings": []})
    ext = ExternalSync(store, transport)
    service = TournamentService(store, ext)
    yield service, ext, store, calls
    store.close()


def command(service, tid, action, **data):
    service.apply(tid, action, {"version": service.get(tid)["version"], "request_id": str(uuid4()), **data}, "admin-1",
                  actor_user=User(id="admin-1", name="Admin", role="admin"))
    # Regression helpers advance through the new explicit player workflow.
    if action in {"confirm_seats", "start_finals"}:
        current=service.get(tid)
        tables=current["finals"]["tables"] if action=="start_finals" else current["rounds"][-1]["tables"]
        people={p["id"]:p for p in current["players"]}
        for table in tables:
            for pid in table["seats"]:
                service.participant_action(tid, table["match_id"], "check_in", User(id=pid,name=people[pid]["name"]), str(uuid4()))
            service.participant_action(tid, table["match_id"], "start_table", User(id=table["seats"][0],name=people[table["seats"][0]]["name"]), str(uuid4()))
    service.external.flush()
    return service.get(tid)


def tournament(service, count=8):
    state = service.create({"name": "Test Cup", "request_id": str(uuid4()), "settings":{"allow_guest_auto_enrollment":True}}, "admin-1")
    for i in range(count):
        state = command(service, state["id"], "player", name=f"Player {i}")
    return state


def round_complete(service, tid):
    command(service, tid, "pair")
    state = command(service, tid, "confirm_seats")
    for table in state["rounds"][-1]["tables"]:
        count = len(table["seats"])
        points = [40000, 30000, 20000, 10000] if count == 4 else [25000] * count
        state = command(service, tid, "score_table", table=table["number"], scores=dict(zip(table["seats"], points)))
    return command(service, tid, "confirm_round")


def finals(service, tid, entrants=None, **settings):
    command(service, tid, "finish_swiss")
    state = service.get(tid)
    entrants = entrants or [r["id"] for r in state["standings"]]
    command(service, tid, "preview_finals", entrants=entrants, **settings)
    return command(service, tid, "start_finals")


def test_manual_names_normalize_and_cannot_become_global_accounts(rig):
    service, _, store, _ = rig
    state = tournament(service, 0)
    state = command(service, state["id"], "player", name="  Alice   Smith ", permanent=False)
    pid = state["players"][0]["id"]
    assert state["players"][0]["name"] == "Alice Smith"
    with pytest.raises(Conflict, match="guest_name_taken"):
        command(service, state["id"], "player", name="alice smith", permanent=True)
    with store.connect() as db:
        assert db.get(Account, pid) is None
    assert not service.get(state["id"])["players"][0]["permanent"]


def test_automatic_table_ids_ignore_machine_names(rig):
    service, _, _, _ = rig
    state = tournament(service, 12);tid=state["id"]
    assert state["table_defaults"] == DEFAULT_NAMES
    command(service,tid,"settings",table_names={"3":"Historical Custom"})
    command(service,tid,"start");state=command(service,tid,"pair")
    tables=state["preview"]["tables"]
    assert [t["number"] for t in tables]==[1,2,3]
    assert len({t["table_id"] for t in tables})==3
    assert all("name" not in t for t in tables)
    state=command(service,tid,"confirm_seats")
    assert [t["table_id"] for t in state["rounds"][0]["tables"]]==[t["table_id"] for t in tables]
    assert state["table_names"]["3"]=="Historical Custom"


def test_random_first_round_and_no_rerandomize_active(rig):
    service, _, _, _ = rig
    state = tournament(service, 9)
    command(service, state["id"], "start")
    state = command(service, state["id"], "pair")
    rnd = state["preview"]
    assigned = [p for t in rnd["tables"] for p in t["seats"]] + rnd["byes"]
    assert len(set(assigned)) == 9 and len(rnd["byes"]) == 1
    command(service, state["id"], "confirm_seats")
    with pytest.raises(Conflict):
        command(service, state["id"], "pair")


def test_swiss_carries_confirmed_scores_and_rule_snapshots(rig):
    service, _, _, _ = rig
    state = tournament(service)
    command(service, state["id"], "start")
    state = round_complete(service, state["id"])
    assert sorted(r["score"] for r in state["standings"]) == [-45, -45, -15, -15, 15, 15, 45, 45]
    original = copy.deepcopy(state["rounds"][0])
    command(service, state["id"], "settings", settings={"uma": [50, 10, -10, -30]})
    state = round_complete(service, state["id"])
    assert state["rounds"][0] == original
    assert state["rounds"][1]["tables"][0]["result"]["rules"]["uma"] == [50, 10, -10, -30]
    assert sum(r["score"] for r in state["standings"]) == 0  # Winner is derived from the other three.
    assert all(r["completed_rounds"] == 2 for r in state["standings"])


def test_pairing_uses_scores_and_reduces_rematches(rig):
    service, _, _, _ = rig
    state = tournament(service, 16)
    command(service, state["id"], "start")
    state = round_complete(service, state["id"])
    rnd = pair_round(state, random.Random(9))
    totals = {r["id"]: r["score"] for r in state["standings"]}
    assert all(len({totals[p] for p in t["seats"]}) == 1 for t in rnd["tables"])
    old_pairs = {frozenset((a,b)) for t in state["rounds"][0]["tables"] for a in t["seats"] for b in t["seats"] if a != b}
    repeats = sum(frozenset((a,b)) in old_pairs for t in rnd["tables"] for a in t["seats"] for b in t["seats"] if a != b)
    assert repeats == 0


def test_pairing_rotates_previous_seats(rig):
    service, _, _, _ = rig
    state = tournament(service, 4)
    command(service, state["id"], "start")
    state = round_complete(service, state["id"])
    new = pair_round(state, random.Random(2))
    assert all(a != b for a,b in zip(state["rounds"][0]["tables"][0]["seats"], new["tables"][0]["seats"]))


def test_unconfirmed_inputs_do_not_change_rankings(rig):
    service, _, _, _ = rig
    state = tournament(service, 4)
    command(service, state["id"], "start")
    command(service, state["id"], "pair")
    state = command(service, state["id"], "confirm_seats")
    table = state["rounds"][0]["tables"][0]
    state = command(service, state["id"], "score_table", table=1, scores=dict(zip(table["seats"], [40000,30000,20000,10000])))
    assert all(r["score"] == 0 for r in state["standings"])
    assert not state["deliveries"]
    assert state["rounds"][0]["tables"][0]["draft"]["rules"]["uma"] == [30,10,-10,-30]


@pytest.mark.parametrize("count",[4,8,12])
def test_any_number_of_finals_tables_and_default_carry(rig, count):
    service, _, _, _ = rig
    state = tournament(service, count)
    command(service, state["id"], "start")
    state = round_complete(service, state["id"])
    previous = {r["id"]:r["score"] for r in state["standings"]}
    state = finals(service, state["id"])
    assert len(state["finals"]["tables"]) == count//4
    assert {r["id"]:r["score"] for r in state["standings"]} == previous


@pytest.mark.parametrize("carry,ratio", [("ratio",.5),("zero",0)])
def test_finals_other_carry_options(rig, carry, ratio):
    service, _, _, _ = rig
    state = tournament(service, 4)
    command(service, state["id"], "start")
    state = round_complete(service, state["id"])
    old = {r["id"]:r["score"] for r in state["standings"]}
    state = finals(service, state["id"], carry=carry, ratio=ratio)
    assert {r["id"]:r["score"] for r in state["standings"]} == {p:v*ratio for p,v in old.items()}


def test_finals_deltas_correction_audit_and_lock(rig):
    service, _, store, _ = rig
    state = tournament(service)
    tid = state["id"]
    command(service, tid, "start")
    round_complete(service, tid)
    state = finals(service, tid)
    before = {r["id"]:r["score"] for r in state["standings"]}
    ids = state["finals"]["tables"][0]["seats"]
    deltas = dict(zip(ids,[10,-5,-3,-2]))
    state = command(service, tid, "hand", table=1, deltas=deltas)
    assert all(r["score"] == before[r["id"]]+deltas.get(r["id"],0) for r in state["standings"])
    hand = state["finals"]["tables"][0]["hands"][-1]
    state = command(service, tid, "correct_hand", table=1, hand_id=hand["id"], deltas=dict.fromkeys(ids,1), reason="Typo")
    assert len(state["finals"]["tables"][0]["hands"]) == 2
    assert state["finals"]["tables"][0]["hands"][0]["void"] is True
    assert all(r["score"] == before[r["id"]] + (1 if r["id"] in ids else 0) for r in state["standings"])
    assert any(a["action"] == "correct_hand" and a["detail"]["before"]["deltas"] == deltas for a in state["audit"])
    command(service, tid, "finish")
    command(service, tid, "lock")
    with pytest.raises(Conflict, match="locked"):
        command(service, tid, "hand", table=1, deltas=deltas)
    command(service, tid, "unlock", reason="Review")
    command(service, tid, "resume", reason="Correction")
    state = command(service, tid, "undo_hand", table=1, hand_id=state["finals"]["tables"][0]["hands"][-1]["id"], reason="Undo")
    assert {r["id"]:r["score"] for r in state["standings"]} == before


def test_comeback_relative_net_advantage_and_unit():
    rows=[{"id":"a","score":10},{"id":"b","score":52}]
    assert comeback(rows,"a","b",1)["overtake_net"] == 43
    assert comeback(rows,"a","b",.1)["overtake_net"] == 42.1
    assert comeback(rows,"b","a",1)["overtake_net"] == 0
    assert comeback(rows,"a","b",1)["tie_net"] == 42


def test_api_configuration_persisted_and_safe(rig):
    _, ext, store, _ = rig
    value={"enabled":True,"endpoint":"https://example.com/scores","adapter":"json"}
    ext.save_config(value,"admin")
    assert ExternalSync(store).config()["endpoint"] == value["endpoint"]
    for endpoint in ["http://example.com","https://127.0.0.1","https://example.com?key=secret","https://user:pw@example.com"]:
        with pytest.raises(Conflict):
            validate_endpoint(endpoint)


def test_api_test_uses_head_without_fake_scores(rig):
    _, ext, _, calls = rig
    ext.save_config({"enabled":True,"endpoint":"https://example.com/scores","adapter":"json"},"admin")
    assert ext.test("admin")["code"] == "reachable_unverified"
    assert calls == [("https://example.com/scores",None,"HEAD")]


def test_local_commit_survives_failure_retry_exact_payload_and_no_duplicate(rig):
    service, ext, store, calls = rig
    ext.save_config({"enabled":True,"endpoint":"https://example.com/scores","adapter":"narts"},"admin")
    original=ext.transport
    def fail(*args):
        calls.append(copy.deepcopy(args))
        raise requests.Timeout("SECRET MUST NEVER LEAK")
    ext.transport=fail
    state = tournament(service,4)
    command(service,state["id"],"start")
    state=round_complete(service,state["id"])
    delivery=state["deliveries"][0]
    assert delivery["status"] == "failed" and "SECRET" not in json.dumps(delivery)
    assert any(r["score"] for r in state["standings"])
    body_before=calls[-1][2]
    ext.transport=original
    result=ext.send(delivery["request_id"],"admin",retry=True)
    assert result["status"] == "success"
    assert calls[-1][1] == body_before
    count=len(calls)
    ext.send(delivery["request_id"],"admin",retry=True)
    assert len(calls)==count
    with store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ExternalDelivery)) == 1


def test_repeated_command_is_idempotent_and_stale_edit_fails(rig):
    service, _, _, _ = rig
    state=tournament(service,0)
    data={"request_id":"same-operation","version":state["version"],"name":"Alice"}
    one=service.apply(state["id"],"player",data,"admin")
    two=service.apply(state["id"],"player",data,"admin")
    assert one["version"] == two["version"] and len(two["players"]) == 1
    with pytest.raises(Conflict,match="stale_version"):
        service.apply(state["id"],"player",{**data,"request_id":"different"},"admin")
    with pytest.raises(Conflict,match="submission_conflict"):
        service.apply(state["id"],"player",{**data,"name":"Bob"},"admin")


def test_concurrent_duplicate_submit_once(rig):
    service, _, _, _ = rig
    state=tournament(service,0)
    data={"request_id":"parallel","version":state["version"],"name":"Alice"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:service.apply(state["id"],"player",data,"admin"),range(2)))
    assert results[0]["version"] == results[1]["version"]
    assert len(service.get(state["id"])["players"])==1


def test_restart_preserves_state_scores_and_audit(rig):
    service, _, store, _=rig
    state=tournament(service,4)
    command(service,state["id"],"start")
    state=round_complete(service,state["id"])
    reopened=Store(store.path)
    try:
        fresh=TournamentService(reopened,ExternalSync(reopened)).get(state["id"])
        assert fresh["standings"]==state["standings"] and fresh["rounds"]==state["rounds"]
        assert fresh["audit"]==state["audit"]
    finally:
        reopened.close()


def test_narts_mapping_and_correction_not_reimported(rig):
    service,ext,_,calls=rig
    ext.save_config({"enabled":True,"endpoint":"https://example.com/scores","adapter":"narts"},"admin")
    state=tournament(service,4)
    command(service,state["id"],"start")
    state=round_complete(service,state["id"])
    assert calls[-1][1]["idempotencyKey"] == state["deliveries"][0]["request_id"]
    assert sum(p["rawScore"] for p in calls[-1][1]["players"])==100000
    assert set(calls[-1][1]) == {"idempotencyKey","playedAt","players"}
    count=len(calls)
    command(service,state["id"],"reopen_round",reason="Review")
    state=command(service,state["id"],"confirm_round")
    assert len(calls)==count
    assert all(d["status"]=="manual_review" for d in state["deliveries"])


def test_invalid_hand_rolls_back_prior_void(rig):
    service,_,_,_=rig
    state=tournament(service,4);tid=state["id"]
    command(service,tid,"start");round_complete(service,tid);state=finals(service,tid)
    ids=state["finals"]["tables"][0]["seats"]
    state=command(service,tid,"hand",table=1,deltas=dict.fromkeys(ids,1))
    last=state["finals"]["tables"][0]["hands"][-1]
    with pytest.raises(Conflict):
        command(service,tid,"correct_hand",table=1,hand_id=last["id"],deltas={},reason="invalid")
    assert service.get(tid)["finals"]["tables"][0]["hands"][-1]["void"] is False


def test_admin_permissions_api_qr_and_public_data(tmp_path,monkeypatch):
    monkeypatch.delenv("NARTS_EXTERNAL_API_ENDPOINT",raising=False)
    app=create_app(Settings(database_path=tmp_path/"api.sqlite3"),DisabledSheets())
    identity=User(id="admin",name="Admin",role="admin")
    app.dependency_overrides[get_current_user]=lambda:identity
    with TestClient(app) as client:
        created=client.post("/api/tournaments",json={"name":"QR Cup","request_id":"create-qr"})
        assert created.status_code==200
        tid=created.json()["id"]
        qr=client.get("/api/qr.png",params={"target":"/?tournament="+tid,"filename":"QR Cup-table-3"})
        assert qr.headers["content-type"]=="image/png"
        assert Image.open(io.BytesIO(qr.content)).width>500
        assert "QR%20Cup-table-3.png" in qr.headers["content-disposition"]
        import cv2,numpy as np
        qr_pixels=cv2.imdecode(np.frombuffer(qr.content,np.uint8),0)
        # OpenCV occasionally fails at the 16 px/module print resolution.
        # Decode at 4 px/module, retaining the exact modules and quiet zone.
        scan=cv2.resize(qr_pixels,None,fx=.25,fy=.25,interpolation=cv2.INTER_NEAREST)
        decoded,_,_=cv2.QRCodeDetector().detectAndDecode(scan)
        assert decoded=="http://testserver/?tournament="+tid
        assert client.get("/api/table-labels").json()["names"]["1"]==DEFAULT_NAMES["1"]
        assert client.post("/api/table-labels",json={"names":{"3":"Custom"}}).status_code==200
        assert client.get("/api/table-labels").json()["names"]["3"]=="Custom"
        assert client.get("/i18n.js").status_code==200
        assert "audit" not in client.get("/api/tournaments/"+tid).json()
        identity.role="user"
        assert client.post("/api/tournaments",json={"name":"No","request_id":"no"}).status_code==403
        assert client.get("/api/external-config").status_code==403
        assert client.get("/api/tournaments/"+tid+"/admin").status_code==403
        assert client.get("/api/qr.png",params={"target":"//evil.example"}).status_code==403
