import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from mahjong_api.database_models import MatchHistory, MatchPlayer, SeatRecord, TableState, User
from mahjong_api.import_legacy import import_record
from mahjong_api.main import create_app
from mahjong_api.models import RelativeSubmission, User as Identity
from mahjong_api.score_mapping import map_and_normalize, normalize_display_score, relative_to_absolute
from mahjong_api.store import Store
from mahjong_api.vision import read_photo, validate_regions
from test_mahjong_api import FakeSheets, POINTS, fill, settings, setup, sit


RAW = {"bottom": "350", "right": "200", "top": "150", "left": "300"}


def player_headers(user=1, key=None):
    return {"Authorization": f"Bearer demo-{user}", **({"Idempotency-Key": key} if key else {})}


def relative(client, user=1, scores=None, match_id=None, key=None):
    body = {"table": 1, "scores": RAW if scores is None else scores}
    if match_id:
        body["match_id"] = match_id
    return client.post("/api/submit_scores", json=body, headers=player_headers(user, key))


@pytest.mark.parametrize("seat,winds", [
    ("east", ["east", "south", "west", "north"]),
    ("south", ["south", "west", "north", "east"]),
    ("west", ["west", "north", "east", "south"]),
    ("north", ["north", "east", "south", "west"]),
])
def test_rotation_all_four_directions(setup, seat, winds):
    client, sheets, service = setup
    match_id = fill(client)
    user = ["east", "south", "west", "north"].index(seat) + 1
    response = relative(client, user=user, match_id=match_id)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert [result["players"][wind]["final_points"] for wind in winds] == [35000, 20000, 15000, 30000]
    assert result["uploader_id"] == f"u{user}"
    assert result["seat_order"] == "ESWN"
    with service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(MatchPlayer)) == 4
        assert db.scalar(select(func.count()).select_from(SeatRecord)) == 0
        assert db.get(User, f"u{user}") is not None


@pytest.mark.parametrize("raw,multiplier,expected", [
    ("350", 100, 35000), ("20000", 1, 20000), ("150", 100, 15000),
    ("300", 100, 30000), ("0", 100, 0), ("-136", 100, -13600),
    ("0335", 100, 33500), ("6100", 1, 6100),
])
def test_uniform_scale(raw, multiplier, expected):
    assert normalize_display_score(raw, multiplier) == expected


def test_invalid_total_preserves_raw_scores_and_seats(setup):
    client, sheets, service = setup
    fill(client)
    raw = {**RAW, "left": "299"}
    response = relative(client, user=2, scores=raw)
    assert response.status_code == 200
    draft = response.json()
    assert draft["status"] == "needs_review"
    assert draft["raw_scores"] == raw
    assert draft["scores"]["east"] == 29900
    assert draft["total"] == 99900
    assert all(service.table("1")["seats"].values())
    assert not sheets.history
    assert client.get(f"/api/score_drafts/{draft['draft_id']}", headers=player_headers(2)).json()["raw_scores"] == raw


def test_unreadable_digit_preserves_other_predictions(setup):
    client, _, _ = setup
    fill(client)
    body = relative(client, scores={**RAW, "right": "2O000"}).json()
    assert body["status"] == "needs_review"
    assert body["scores"]["south"] is None
    assert body["scores"]["east"] == 35000
    assert any(issue.get("position") == "right" for issue in body["issues"])


def test_upload_authentication_cannot_be_forged(setup):
    client, _, _ = setup
    fill(client)
    assert client.post("/api/submit_scores", json={"table": 1, "scores": RAW}, headers={"X-API-Key": "test-machine-key"}).status_code == 401
    assert relative(client, user=5).status_code == 403
    assert client.post("/api/submit_scores", json={"table": 1, "scores": RAW, "user_id": "u1"}, headers=player_headers(5)).status_code == 422


def test_review_owner_only_and_manual_correction(setup):
    client, sheets, service = setup
    fill(client)
    draft = relative(client, scores={**RAW, "left": "299"}).json()
    path = f"/api/score_drafts/{draft['draft_id']}"
    assert client.get(path, headers=player_headers(2)).status_code == 403
    payload = {"draft_id": draft["draft_id"], "scores": POINTS}
    assert client.post("/api/confirm_scores", json=payload, headers=player_headers(2)).status_code == 403
    bad = {"draft_id": draft["draft_id"], "scores": {**POINTS, "east": 34000}}
    assert client.post("/api/confirm_scores", json=bad, headers=player_headers()).json()["status"] == "needs_review"
    assert client.get(path, headers=player_headers()).json()["scores"]["east"] == 34000
    response = client.post("/api/confirm_scores", json=payload, headers=player_headers())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"
    assert client.post("/api/confirm_scores", json=payload, headers=player_headers()).json()["replayed"]
    assert len(sheets.history) == 1


def test_timing_freezes_at_first_submission_and_averages_exclude_unknown(setup, monkeypatch):
    client, _, service = setup
    for user, seat in enumerate(("east", "south", "west"), 1):
        sit(client, user, seat=seat)
    assert service.table("1")["started_at"] is None
    sit(client, 4, seat="north")
    start = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
    with service.store.connect() as db:
        db.scalar(select(TableState)).started_at = start.isoformat()
    monkeypatch.setattr("mahjong_api.service.now", lambda: (start + timedelta(minutes=10)).isoformat())
    draft = relative(client, scores={**RAW, "left": "299"}).json()
    monkeypatch.setattr("mahjong_api.service.now", lambda: (start + timedelta(minutes=30)).isoformat())
    response = client.post("/api/confirm_scores", json={"draft_id": draft["draft_id"], "scores": POINTS}, headers=player_headers())
    assert response.json()["result"]["duration_seconds"] == 600
    stats = client.get("/api/statistics", headers=player_headers()).json()
    assert stats["overall"]["average_duration_seconds"] == 600
    assert stats["player"]["completed_matches_with_duration"] == 1
    assert service.table("1")["started_at"] is None


def test_stale_draft_cannot_score_replacement_player(setup):
    client, sheets, _ = setup
    fill(client)
    draft = relative(client, scores={**RAW, "left": "299"}).json()
    assert sit(client,5,seat="north").json()["detail"]["code"]=="table_already_started"
    table=client.app.state.tables.list(Identity(id="admin",name="Admin",role="admin"),True)["tables"][0]
    client.app.state.tables.reset(table["id"],{"request_id":"reset-draft","reason":"Wrong roster"},Identity(id="admin",name="Admin",role="admin"))
    response = client.post("/api/confirm_scores", json={"draft_id": draft["draft_id"], "scores": POINTS}, headers=player_headers())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_match"
    assert not sheets.history


def test_player_retries_preserve_perspective_after_table_clear(setup):
    client, sheets, service = setup
    old = fill(client)
    first = relative(client, user=2, match_id=old, key="photo-1").json()
    new = fill(client)
    second = relative(client, user=2, match_id=old, key="photo-1").json()
    assert second["result"] == first["result"]
    assert second["replayed"]
    assert service.table("1")["match_id"] == new
    assert all(service.table("1")["seats"].values())
    assert len(sheets.history) == 1
    assert relative(client, user=2, match_id=old, key="photo-1", scores={**RAW, "bottom": "360", "top": "140"}).status_code == 409


def test_concurrent_player_submit_once(setup):
    client, sheets, service = setup
    match_id = fill(client)
    payload = RelativeSubmission(table=1, match_id=match_id, scores=RAW)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: service.submit_relative(payload, Identity(id="u1", name="玩家1"), "shared"), range(8)))
    assert all(status == 200 for _, status in responses)
    assert len(sheets.history) == 1


def test_draft_survives_restart(settings):
    sheets = FakeSheets()
    with TestClient(create_app(settings, sheets)) as client:
        fill(client)
        draft = relative(client, scores={**RAW, "left": "299"}).json()
    with TestClient(create_app(settings, sheets)) as client:
        result = client.post("/api/confirm_scores", json={"draft_id": draft["draft_id"], "scores": POINTS}, headers=player_headers())
        assert result.status_code == 200
        assert result.json()["result"]["players"]["east"]["user"]["id"] == "u1"


def test_legacy_ewsn_import_and_unknown_duration(settings):
    store = Store(settings.database_path)
    record = {"source_id": "old-1", "table": "old", "round": 1,
        "players": [{"id": str(i), "name": name} for i, name in enumerate(["东玩家", "西玩家", "南玩家", "北玩家"])],
        "scores": [35000, 15000, 20000, 30000]}
    try:
        match_id = import_record(store, record)
        assert import_record(store, record) == match_id
        result = store.match(match_id)["result"]
        assert result["source_seat_order"] == "EWSN"
        assert result["players"]["west"]["user"]["name"] == "西玩家"
        assert result["players"]["south"]["final_points"] == 20000
        assert store.stats()["average_duration_seconds"] is None
        with store.connect() as db:
            assert db.get(MatchPlayer, (match_id, "west")).source_position == 1
    finally:
        store.close()


class FakeVision:
    def __init__(self, issues=None, callback=None):
        self.issues, self.callback = issues or [], callback

    def recognize(self, content, regions):
        read_photo(content)
        if self.callback:
            self.callback()
        return {"scores": RAW, "issues": self.issues, "model": "fake"}


def photo():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("low_confidence", [False, True])
def test_photo_pipeline(settings, low_confidence):
    vision = FakeVision([{"code": "low_confidence"}] if low_confidence else [])
    with TestClient(create_app(settings, FakeSheets(), vision)) as client:
        match_id = fill(client)
        result = client.post("/api/recognize_photo", data={"table": "1", "match_id": match_id}, files={"file": ("score.png", photo(), "image/png")}, headers=player_headers(2))
        assert result.status_code == 200, result.text
        assert result.json()["status"] == ("needs_review" if low_confidence else "success")
        if low_confidence:
            assert result.json()["total"] == 100000
        else:
            assert result.json()["result"]["players"]["south"]["final_points"] == 35000


def test_photo_stale_roster_after_inference(settings):
    vision = FakeVision()
    app = create_app(settings, FakeSheets(), vision)
    with TestClient(app) as client:
        match_id = fill(client)
        def reset_during_inference():
            admin=Identity(id="admin",name="Admin",role="admin")
            table=app.state.tables.list(admin,True)["tables"][0]
            app.state.tables.reset(table["id"],{"request_id":"reset-inference","reason":"Wrong roster"},admin)
        vision.callback = reset_during_inference
        result = client.post("/api/recognize_photo", data={"table": "1", "match_id": match_id}, files={"file": ("score.png", photo(), "image/png")}, headers=player_headers())
        assert result.status_code == 409
        assert result.json()["detail"]["code"] == "stale_match"


def test_invalid_photo_and_region_validation():
    with pytest.raises(ValueError):
        read_photo(b"not an image")
    with pytest.raises(ValueError):
        validate_regions({})
    with pytest.raises(ValueError):
        validate_regions(dict.fromkeys(("bottom", "right", "top", "left"), {"box": [0, 0, float("nan"), 1]}))


def test_existing_account_introspection(settings, monkeypatch):
    from dataclasses import replace
    import mahjong_api.auth as auth

    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return type("Response", (), {"status_code": 200, "json": lambda _: {"profile": {"id": 123, "name": "现有用户"}}})()
    monkeypatch.setattr(auth.requests, "get", get)
    with TestClient(create_app(replace(settings, mock_auth_enabled=False, auth_profile_url="http://127.0.0.1:5000/api/session"), FakeSheets())) as client:
        from test_mahjong_api import ensure_table
        ensure_table(client,1)
        client.cookies.set("mahjong_session", "existing-session")
        response = client.post("/api/sit?table=1&seat=east")
        assert response.json()["user_id"] == 123
        assert response.json()["message"] == "成功就坐 1号桌 东风"
        assert calls[0][1]["headers"] == {"Cookie": "mahjong_session=existing-session"}
        assert calls[0][1]["allow_redirects"] is False


def test_photo_retry_after_settlement_returns_original_result(settings):
    vision = FakeVision()
    app = create_app(settings, FakeSheets(), vision)
    with TestClient(app) as client:
        match_id = fill(client)
        params = {"data": {"table": "1", "match_id": match_id},
                  "files": {"file": ("score.png", photo(), "image/png")},
                  "headers": player_headers(2, "same-photo")}
        first = client.post("/api/recognize_photo", **params)
        assert first.status_code == 200
        fill(client)
        again = client.post("/api/recognize_photo", **params)
        assert again.status_code == 200
        assert again.json()["result"] == first.json()["result"]
        assert again.json()["replayed"]
        assert all(app.state.service.table("1")["seats"].values())
