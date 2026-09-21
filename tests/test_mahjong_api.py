from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from mahjong_api.config import Settings
from mahjong_api.main import create_app
from mahjong_api.models import SEATS, SubmitScores, User
from mahjong_api.sheets import DisabledSheets


POINTS = {"east": 35000, "south": 20000, "west": 15000, "north": 30000}
YOLO = {"X-API-Key": "test-machine-key"}


class FakeSheets:
    enabled = True

    def __init__(self):
        self.current = {}
        self.history = {}
        self.fail_current = False
        self.fail_history = False
        self.lose_history_ack = False

    def write_current(self, table):
        if self.fail_current:
            raise ConnectionError("current unavailable")
        self.current[table["table_id"]] = deepcopy(table)

    def write_history(self, match):
        if self.fail_history:
            raise ConnectionError("history unavailable")
        self.history[match["sequence"]] = deepcopy(match)
        if self.lose_history_ack:
            raise TimeoutError("write succeeded but acknowledgement was lost")


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=tmp_path / "test.sqlite3", mock_auth_enabled=True, yolo_api_key=YOLO["X-API-Key"], sync_interval_seconds=3600)


@pytest.fixture
def setup(settings):
    sheets = FakeSheets()
    app = create_app(settings, sheets)
    with TestClient(app) as client:
        ensure_table(client,1)
        yield client, sheets, app.state.service


def ensure_table(client, table):
    """Seed a pre-existing admin-managed table in isolated test databases."""
    from mahjong_api.database_models import TableState
    from mahjong_api.table_membership import register_ordinary
    from sqlalchemy import select
    from uuid import uuid4
    from mahjong_api.store import now
    with client.app.state.service.store.connect() as db:
        row=db.scalar(select(TableState).where(TableState.table_id==str(table)))
        if row is None:
            row=TableState(table_id=str(table),current_match_id=str(uuid4()),updated_at=now())
            db.add(row);db.flush();register_ordinary(db,row)


def sit(client, user=1, table=1, seat="east"):
    ensure_table(client,table)
    return client.get("/api/sit", params={"table": table, "seat": seat}, headers={"Authorization": f"Bearer demo-{user}"})


def fill(client, table=1):
    result = None
    for index, seat in enumerate(SEATS, 1):
        response = sit(client, index, table, seat)
        assert response.status_code == 200, response.text
        result = response.json()["match_id"]
    return result


def submit(client, table=1, scores=None, match_id=None, key=None):
    payload = {"table": table, "scores": POINTS if scores is None else scores}
    if match_id:
        payload["match_id"] = match_id
    headers = dict(YOLO)
    if key:
        headers["Idempotency-Key"] = key
    return client.post("/api/submit_absolute_scores", json=payload, headers=headers)


def test_login_redirect_preserves_nfc_target(setup):
    client, sheets, service = setup
    response = client.get("/api/sit?table=1&seat=east&redirect_url=https://evil.invalid")
    assert response.status_code == 401
    target = response.json()["detail"]["redirect_url"]
    assert response.headers["location"] == target
    assert parse_qs(urlsplit(target).query)["redirect_url"] == ["/sit?table=1&seat=east"]
    assert not sheets.current


def test_cookie_and_bearer_precedence(setup):
    client, _, _ = setup
    client.cookies.set("session_id", "demo-1")
    response = client.post("/api/sit?table=1&seat=east")
    assert response.json()["message"] == "成功就坐 1号桌 东风"
    assert response.json()["user"] == "玩家1"
    assert client.get("/api/sit?table=1&seat=east", headers={"Authorization": "Bearer unknown"}).status_code == 401
    assert client.get("/api/sit?table=1&seat=east", headers={"Authorization": "Basic demo-1"}).status_code == 401


def test_mock_disabled_by_default(settings):
    with TestClient(create_app(replace(settings, mock_auth_enabled=False), FakeSheets())) as client:
        assert sit(client).status_code == 401


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.invalid"}, {"Origin": "http://testserver.evil.invalid"}, {"Sec-Fetch-Site": "cross-site"}])
def test_cookie_origin_rejected(setup, headers):
    client, _, _ = setup
    client.cookies.set("session_id", "demo-1")
    assert client.get("/api/sit?table=1&seat=east", headers=headers).status_code == 403


def test_seats_cannot_overwrite_or_silently_move(setup):
    client, sheets, service = setup
    assert sit(client,1).status_code==200
    assert sit(client,2).json()["detail"]["code"]=="seat_occupied"
    assert sit(client,1,"A-2","north").json()["detail"]["code"]=="already_at_other_table"
    assert service.table("1")["seats"]["east"]=="u1"
    assert sit(client,1,1,"south").status_code==200
    assert service.table("1")["seats"]["east"] is None


def test_complete_round_and_next_round(setup):
    client, sheets, service = setup
    match_id = fill(client)
    response = submit(client, match_id=match_id, key="capture-1")
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["round"] == 1
    assert [result["players"][seat]["user"]["id"] for seat in SEATS] == ["u1", "u2", "u3", "u4"]
    assert [result["players"][seat]["net_score"] for seat in SEATS] == [10, -5, -10, 5]
    assert all(result["players"][seat]["initial_points"] == 25000 for seat in SEATS)
    assert not any(service.table("1")["seats"].values())
    assert not any(sheets.current["1"]["seats"].values())
    assert len(sheets.history) == 1
    next_id = fill(client)
    assert next_id != match_id
    response = submit(client, match_id=next_id, key="capture-2")
    assert response.json()["result"]["round"] == 2
    assert len(sheets.history) == 2


def test_missing_seats_no_side_effects(setup):
    client, sheets, service = setup
    sit(client)
    response = submit(client)
    assert response.status_code == 409
    assert response.json()["detail"]["missing_seats"] == ["south", "west", "north"]
    assert not sheets.history
    assert service.table("1")["seats"]["east"] == "u1"


def test_yolo_key_is_separate_from_player_login(setup):
    client, _, _ = setup
    payload = {"table": 1, "scores": POINTS}
    assert client.post("/api/submit_absolute_scores", json=payload).status_code == 401
    assert client.post("/api/submit_absolute_scores", json=payload, headers={"Authorization": "Bearer demo-1"}).status_code == 401
    assert client.get("/api/machine/tables/1").status_code == 401
    assert client.post("/api/sync").status_code == 401


@pytest.mark.parametrize("value", [True, 35000.5, "35000", 35001, 10000100, None])
def test_invalid_points_rejected(setup, value):
    client, _, _ = setup
    response = submit(client, scores={**POINTS, "east": value})
    assert response.status_code == 422


@pytest.mark.parametrize("payload", [
    {"table": 1, "scores": {"east": 100000}},
    {"table": 1, "scores": {**POINTS, "center": 0}},
    {"table": True, "scores": POINTS},
    {"table": "../1", "scores": POINTS},
    {"table": 1, "scores": POINTS, "unexpected": 1},
])
def test_invalid_payloads(setup, payload):
    client, _, _ = setup
    assert client.post("/api/submit_absolute_scores", json=payload, headers=YOLO).status_code == 422


def test_bad_total_and_wind(setup):
    client, sheets, service = setup
    fill(client)
    assert sit(client, seat="East").status_code == 422
    assert submit(client, scores={**POINTS, "east": 34000}).status_code == 422
    assert not sheets.history
    assert all(service.table("1")["seats"].values())


def test_negative_scores_are_supported(setup):
    client, _, _ = setup
    fill(client)
    assert submit(client, scores={"east": -5000, "south": 60000, "west": 15000, "north": 30000}).status_code == 200


def test_configurable_initial_points(settings):
    with TestClient(create_app(replace(settings, initial_points=30000), FakeSheets())) as client:
        fill(client)
        result = submit(client, scores=dict.fromkeys(SEATS, 30000)).json()["result"]
        assert all(p["net_score"] == 0 and p["initial_points"] == 30000 for p in result["players"].values())


def test_retries_do_not_score_new_occupants(setup):
    client, sheets, service = setup
    old_id = fill(client)
    first = submit(client, match_id=old_id, key="same-capture").json()
    new_id = fill(client)
    assert new_id != old_id
    retry = submit(client, key="same-capture")
    assert retry.json()["replayed"] is True
    assert retry.json()["result"] == first["result"]
    retry_by_id = submit(client, match_id=old_id, key="another-key")
    assert retry_by_id.json()["replayed"] is True
    assert service.table("1")["match_id"] == new_id
    assert all(service.table("1")["seats"].values())
    assert len(sheets.history) == 1
    assert submit(client, scores={**POINTS, "east": 36000, "south": 19000}, key="same-capture").status_code == 409
    assert submit(client, match_id="unknown-old-id").status_code == 409


def test_minimal_payload_supported_and_empty_table_blocks_immediate_repeat(setup):
    client, sheets, _ = setup
    fill(client)
    assert submit(client).status_code == 200
    assert submit(client).status_code == 409
    assert len(sheets.history) == 1


def test_seat_sync_failure_is_persisted_and_retried(setup):
    client, sheets, service = setup
    sheets.fail_current = True
    response = sit(client)
    assert response.status_code == 202
    assert response.json()["sync_status"] == "pending"
    assert service.table("1")["seats"]["east"] == "u1"
    sheets.fail_current = False
    assert client.post("/api/sync", headers=YOLO).json()["status"] == "success"
    assert sheets.current["1"]["seats"]["east"]["id"] == "u1"


@pytest.mark.parametrize("lose_ack", [False, True])
def test_history_failure_freezes_snapshot_until_retry(setup, lose_ack):
    client, sheets, service = setup
    match_id = fill(client)
    sheets.fail_history = not lose_ack
    sheets.lose_history_ack = lose_ack
    assert submit(client, match_id=match_id, key="retry").status_code == 202
    assert all(service.table("1")["seats"].values())
    assert service.table("1")["settlement_pending"]
    assert sit(client, 5).status_code == 409
    assert sit(client, 1, 2, "west").status_code == 409
    assert submit(client, scores={**POINTS, "east": 36000, "south": 19000}).status_code == 409
    sheets.fail_history = sheets.lose_history_ack = False
    response = submit(client, match_id=match_id, key="retry")
    assert response.status_code == 200
    assert response.json()["replayed"] is True
    assert len(sheets.history) == 1
    assert not any(service.table("1")["seats"].values())


def test_failed_sheet_clear_then_new_seat_is_not_lost(setup):
    client, sheets, service = setup
    match_id = fill(client)
    sheets.fail_current = True
    assert submit(client, match_id=match_id).status_code == 202
    assert not any(service.table("1")["seats"].values())
    assert sit(client, 5, 1, "east").status_code == 202
    sheets.fail_current = False
    assert submit(client, match_id=match_id).status_code == 200
    assert service.table("1")["seats"]["east"] == "u5"
    assert sheets.current["1"]["seats"]["east"]["id"] == "u5"
    assert len(sheets.history) == 1


def test_restart_recovers_pending_history(settings):
    sheets = FakeSheets()
    sheets.fail_history = True
    with TestClient(create_app(settings, sheets)) as client:
        match_id = fill(client)
        assert submit(client, key="restart").status_code == 202
    sheets.fail_history = False
    with TestClient(create_app(settings, sheets)) as client:
        state = client.get("/api/machine/tables/1", headers=YOLO).json()
        assert not any(state["seats"].values())
        assert state["round"] == 2
        assert submit(client, key="restart").json()["result"]["match_id"] == match_id
    assert len(sheets.history) == 1


def test_concurrent_submits_settle_once(setup):
    client, sheets, service = setup
    match_id = fill(client)
    payload = SubmitScores(table=1, scores=POINTS, match_id=match_id)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.submit(payload, "concurrent"), range(12)))
    assert all(status == 200 for _, status in results)
    assert sum(not body["replayed"] for body, _ in results) == 1
    assert len(sheets.history) == 1
    assert service.table("1")["round"] == 2


def test_concurrent_moves_keep_one_seat(setup):
    _, _, service = setup
    user = User(id="one", name="同一人")
    with ThreadPoolExecutor(max_workers=8) as pool:
        def attempt(table):
            from mahjong_api.store import Conflict
            try:return service.sit(str(table),"east",user)
            except Conflict:return None
        results=list(pool.map(attempt,range(8)))
        assert sum(r is not None for r in results)==1
    assert sum(bool(service.table(str(table)) and service.table(str(table))["seats"]["east"] == user.id) for table in range(8)) == 1


def test_second_process_for_same_database_is_rejected(settings):
    with TestClient(create_app(settings, FakeSheets())):
        with pytest.raises(RuntimeError, match="workers 1"):
            with TestClient(create_app(settings, FakeSheets())):
                pass


def test_enabling_sheets_replays_local_history_without_clearing_new_round(settings):
    with TestClient(create_app(settings, DisabledSheets())) as client:
        fill(client)
        assert submit(client).json()["sync_status"] == "disabled"
        sit(client, 5)
    sheets = FakeSheets()
    with TestClient(create_app(settings, sheets)) as client:
        state = client.get("/api/machine/tables/1", headers=YOLO).json()
        assert state["round"] == 2
        assert state["seats"]["east"] == "u5"
        assert len(sheets.history) == 1
        assert sheets.current["1"]["seats"]["east"]["id"] == "u5"
