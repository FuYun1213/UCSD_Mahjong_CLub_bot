"""Actual user photos: no mocked recognition, no network or production records."""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

pytest.importorskip("cv2")
from mahjong_api.database_models import MatchHistory, MatchPlayer
from mahjong_api.main import create_app
from mahjong_api.score_mapping import display_units, map_and_normalize, relative_to_absolute
from mahjong_api.vision import LCDRecognizer
from test_mahjong_api import FakeSheets, fill, settings
from test_mahjong_v2 import player_headers

FIXTURES = Path(__file__).parent / "fixtures" / "displays"
CASES = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["file"])
@pytest.mark.parametrize("seat", ["east", "south", "west", "north"])
def test_real_photo_full_pipeline(settings, case, seat):
    # Nonexistent model path proves the deployed decoder needs no weights/GPU.
    recognizer = LCDRecognizer(Path("unused-model-directory"))
    sink = FakeSheets()
    app = create_app(settings, sink, recognizer)
    with TestClient(app) as client:
        match_id = fill(client)
        user = ["east", "south", "west", "north"].index(seat) + 1
        args = dict(data={"table": "1", "match_id": match_id},
                    files={"file": (case["file"], (FIXTURES / case["file"]).read_bytes(), "image/png")},
                    headers=player_headers(user, "real-photo"))
        response = client.post("/api/recognize_photo", **args)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success", body
        assert body["recognition"]["scores"] == case["scores"]
        assert body["recognition"]["issues"] == []
        assert body["normalization"]["multiplier"] == case["multiplier"]
        result = body["result"]
        for position, wind in relative_to_absolute(seat).items():
            player = result["players"][wind]
            assert player["final_points"] == int(case["scores"][position]) * case["multiplier"]
        assert sum(p["final_points"] for p in result["players"].values()) == 100000
        assert sum(p["net_score"] for p in result["players"].values()) == pytest.approx(0)
        assert all(value is None for value in app.state.service.table("1")["seats"].values())
        assert len(sink.history) == 1
        with app.state.service.store.connect() as db:
            assert db.scalar(select(func.count()).select_from(MatchHistory)) == 1
            assert db.scalar(select(func.count()).select_from(MatchPlayer)) == 4
        assert client.post("/api/recognize_photo", **args).json()["replayed"]
        assert len(sink.history) == 1


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["file"])
def test_jpeg_and_resize_never_silently_change_a_score(case):
    original = Image.open(FIXTURES / case["file"]).convert("RGB")
    recognizer = LCDRecognizer(Path("unused"))
    for scale in (1.0, .75):
        photo = original.resize((int(original.width * scale), int(original.height * scale)))
        buffer = io.BytesIO()
        photo.save(buffer, format="JPEG", quality=85)
        result = recognizer.recognize(buffer.getvalue())
        if not result["issues"]:
            assert result["scores"] == case["scores"]


def test_mixed_units_are_not_repaired_per_player():
    raw = {"bottom": "350", "right": "20000", "top": "150", "left": "30000"}
    scores, _, issues = map_and_normalize(raw, "east")
    assert display_units(raw)["multiplier"] == 1
    assert scores == {"east": 350, "south": 20000, "west": 150, "north": 30000}
    assert any(issue["code"] == "invalid_total" for issue in issues)


def test_short_scores_ending_in_00_still_scale_with_entire_photo():
    raw = {"bottom": "300", "right": "200", "top": "100", "left": "400"}
    scores, _, issues = map_and_normalize(raw, "east")
    assert scores == {"east": 30000, "south": 20000, "west": 10000, "north": 40000}
    assert not issues


def test_blank_photo_needs_review():
    content = io.BytesIO()
    Image.new("RGB", (500, 300), "white").save(content, format="PNG")
    result = LCDRecognizer(Path("unused")).recognize(content.getvalue())
    assert result["issues"]
    assert all(value == "" for value in result["scores"].values())
