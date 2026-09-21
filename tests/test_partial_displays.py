import io
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

pytest.importorskip("cv2")
from mahjong_api.main import create_app
from mahjong_api.vision import LCDRecognizer
from test_mahjong_api import FakeSheets, fill, settings
from test_mahjong_v2 import player_headers


def test_incomplete_photo_preserves_unlocated_readings_in_draft(settings):
    source = Path(__file__).parent / "fixtures/displays/photo_1.png"
    photo = Image.open(source)
    buffer = io.BytesIO()
    # Exclude the bottom score; the remaining reads must not disappear.
    photo.crop((0, 0, photo.width, 540)).save(buffer, format="PNG")
    sink = FakeSheets()
    app = create_app(settings, sink, LCDRecognizer(Path("unused")))
    with TestClient(app) as client:
        match_id = fill(client)
        response = client.post("/api/recognize_photo", data={"table": "1", "match_id": match_id},
                               files={"file": ("incomplete.png", buffer.getvalue(), "image/png")},
                               headers=player_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "needs_review"
        candidates = [item["raw"] for issue in body["issues"] for item in issue.get("candidates", [])]
        assert "18000" in candidates
        assert not sink.history
        assert all(app.state.service.table("1")["seats"].values())
        saved = client.get("/api/score_drafts/" + body["draft_id"], headers=player_headers()).json()
        assert saved["issues"] == body["issues"]
