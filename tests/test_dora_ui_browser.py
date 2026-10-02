"""New DORA shell, outsider seat management and eight-field scoring with isolated data."""
import os
from pathlib import Path
import subprocess
import web_server
from test_web_score_bridge import website


def test_dora_ui_member_workflow(website, monkeypatch):
    url, app, sink = website
    history = []
    sink.write_manual_history = lambda match: history.append(match)
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: [])
    monkeypatch.setattr(web_server, "build_dashboard", lambda *args, **kwargs:
                        {"stats": {"member_count": 8}, "rankings": [], "recent_yakuman": []})
    if os.environ.get("DORA_RELEASE_WEB"):
        monkeypatch.setattr(web_server, "WEB_DIR", Path(os.environ["DORA_RELEASE_WEB"]).resolve())
    env = os.environ.copy()
    env["NFC_TEST_URL"] = url
    env["NODE_PATH"] = str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_dora_ui.cjs"], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=150)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(history) == 1
    saved = history[0]["result"]
    assert saved["uploader_id"] == "photo-user-8"
    assert saved["players"]["north"]["final_points"] == -6000
    assert saved["table"] is None
