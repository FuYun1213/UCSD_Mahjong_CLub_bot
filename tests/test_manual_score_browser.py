"""Real website/global session and manual score form against isolated data."""
import json
import os
from pathlib import Path
import subprocess
import web_server
from test_web_score_bridge import website


def test_browser_manual_score(website,monkeypatch):
    url,app,sink=website
    history=[]
    deliveries=[]
    app.state.service.external.save_config({"enabled": True, "adapter": "json", "endpoint": "https://example.com/scores"}, "admin")
    def transport(endpoint, adapter, payload, method):
        deliveries.append(payload)
        return (503, {}) if len(deliveries) == 1 else (200, {"ok": True})
    app.state.service.external.transport=transport
    sink.write_manual_history=lambda match: history.append(match)
    accounts=json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"]="admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts),encoding="utf-8")
    monkeypatch.setattr(web_server,"sheet_player_names",lambda:[])
    monkeypatch.setattr(web_server,"build_dashboard",lambda *a,**kw:{"stats":{"member_count":8},"rankings":[],"recent_yakuman":[]})
    environment=os.environ.copy()
    environment["NFC_TEST_URL"]=url
    environment["NODE_PATH"]=str(Path(".venv-api/browser-tests/node_modules").resolve())
    result=subprocess.run(["node","tests/browser_manual_score.cjs"],env=environment,capture_output=True,text=True,encoding="utf-8",timeout=150)
    assert result.returncode==0,result.stdout+result.stderr
    assert len(history)==2
    assert history[0]["match_id"] != history[1]["match_id"]
    assert history[1]["result"]["players"]["east"]["final_points"] == 35000
    assert len(deliveries)==3 and deliveries[0]==deliveries[1]
    assert deliveries[2]["requestId"] != deliveries[0]["requestId"]
    assert history[0]["result"]["table"] is None
    assert history[0]["result"]["round"] is None
    print(result.stdout)
