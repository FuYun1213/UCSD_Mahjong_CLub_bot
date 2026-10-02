"""Browser tests talk to the real website + private API, using only temp databases."""
import json
import os
from pathlib import Path
import subprocess
import pytest
import web_server
from test_web_score_bridge import website


def test_browser_tournament_workflow(website,monkeypatch):
    url,app,_=website
    monkeypatch.setenv("TOURNAMENT_CLUB_DATABASE_PATH",str(web_server.USERS_FILE.parent / "unused.sqlite3"))
    accounts=json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"]="admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts),encoding="utf-8")
    monkeypatch.setattr(web_server,"sheet_player_names",lambda:["photo1","photo2","photo3","photo4"])
    monkeypatch.setattr(web_server,"build_dashboard",lambda *a,**kw:{"stats":{"member_count":4},"rankings":[],"recent_yakuman":[]})
    app.state.external.transport=lambda endpoint,adapter,body,method:(201,{"match":{"id":"browser-match"}})
    env=os.environ.copy()
    env["NFC_TEST_URL"]=url
    env["NODE_PATH"]=str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result=subprocess.run(["node","tests/browser_tournament.cjs"],env=env,capture_output=True,text=True,
        encoding="utf-8",timeout=150)
    assert result.returncode==0,result.stdout+result.stderr
    print(result.stdout)


def test_browser_narts_key_setup(website, monkeypatch, tmp_path):
    url, app, _ = website
    monkeypatch.setenv("NARTS_EXTERNAL_API_KEY_FILE", str(tmp_path / "narts-private-key"))
    monkeypatch.delenv("NARTS_EXTERNAL_API_KEY", raising=False)
    accounts = json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"] = "admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts), encoding="utf-8")
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: ["photo1", "photo2"])
    monkeypatch.setattr(web_server, "build_dashboard", lambda *a, **kw: {"stats": {"member_count": 2}, "rankings": [], "recent_yakuman": []})
    calls = []
    def transport(endpoint, adapter, body, method):
        calls.append((body, method))
        return 405, {}
    app.state.external.transport = transport
    env = os.environ.copy()
    env["NFC_TEST_URL"] = url
    env["NODE_PATH"] = str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result = subprocess.run(["node", "tests/browser_narts_setup.cjs"], env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=100)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [(None, "HEAD")]
    assert (tmp_path / "narts-private-key").read_text() == "opaque_Browser.Key-AbCd123456"
    print(result.stdout)


def test_browser_table_v3_workflow(website, monkeypatch):
    url, app, _ = website
    accounts=json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"]="admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts),encoding="utf-8")
    monkeypatch.setattr(web_server,"sheet_player_names",lambda:[])
    monkeypatch.setattr(web_server,"build_dashboard",lambda *a,**kw:{"stats":{"member_count":8},"rankings":[],"recent_yakuman":[]})
    env=os.environ.copy()
    env["NFC_TEST_URL"]=url
    env["NODE_PATH"]=str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result=subprocess.run(["node","tests/browser_table_v3.cjs"],env=env,capture_output=True,text=True,encoding="utf-8",timeout=150)
    assert result.returncode==0,result.stdout+result.stderr
    print(result.stdout)


def test_browser_table_reservation_regressions(website, monkeypatch):
    url, app, _ = website
    accounts=json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"]="admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts),encoding="utf-8")
    monkeypatch.setattr(web_server,"sheet_player_names",lambda:[])
    monkeypatch.setattr(web_server,"build_dashboard",lambda *a,**kw:{"stats":{"member_count":8},"rankings":[],"recent_yakuman":[]})
    env=os.environ.copy()
    env["NFC_TEST_URL"]=url
    env["NODE_PATH"]=str(Path(os.environ.get("NODE_PATH") or ".venv-api/browser-tests/node_modules").resolve())
    result=subprocess.run(["node","tests/browser_table_v4.cjs"],env=env,capture_output=True,text=True,encoding="utf-8",timeout=150)
    assert result.returncode==0,result.stdout+result.stderr
    print(result.stdout)
