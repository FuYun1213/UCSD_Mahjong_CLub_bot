import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
from contextlib import closing
import web_server
import pytest
import mahjong_store
import registered_names
from mahjong_api.models import User
from test_web_score_bridge import website
from test_tournament_v10 import RULES


@pytest.mark.skipif(os.getenv("NFC_BROWSER_TESTS") != "1", reason="Set NFC_BROWSER_TESTS=1 to run the real browser")
def test_registration_guest_scoring_browser(website,tmp_path,monkeypatch):
    url,app,_=website
    monkeypatch.setattr(web_server,"MAHJONG_DB_FILE",tmp_path/"club.sqlite3")
    monkeypatch.setattr(web_server,"LIVE_DB_FILE",tmp_path/"live.sqlite3")
    monkeypatch.setattr(web_server,"record_action",lambda **kw:kw)
    for key in ("DISCORD_CLIENT_ID","DISCORD_CLIENT_SECRET","DISCORD_REDIRECT_URI"):monkeypatch.delenv(key,raising=False)
    with closing(mahjong_store.connect(web_server.MAHJONG_DB_FILE)) as db:
        legacy=mahjong_store.upsert_player(db,"Legacy Browser")
        original_player=dict(db.execute("SELECT * FROM players WHERE id=?",(legacy["id"],)).fetchone())
        mahjong_store.upsert_player(db,"Legacy Rejected")
    directory=registered_names.read_accounts(web_server.USERS_FILE);directory["users"]["photo1"]["role"]="admin"
    registered_names.write_accounts(web_server.USERS_FILE,directory)
    monkeypatch.setattr(web_server,"sheet_player_names",lambda:[])
    admin=User(id="photo-user-1",name="photo1",role="admin")
    state=app.state.tournaments.create({"name":"Browser Test Cup","settings":RULES,"request_id":str(uuid4())},admin.id)
    table=app.state.tables.create({"number":30,"tournament_id":state["id"],"request_id":str(uuid4())},admin)
    token=app.state.tables.issue_token(table["id"],{"channel":"qr","purpose":"table_landing","request_id":str(uuid4())},admin)
    env={**os.environ,"NFC_TEST_URL":url,"NODE_PATH":str(Path(os.environ.get('NODE_PATH') or '.venv-api/browser-tests/node_modules').resolve()),
         "V10_SEED":json.dumps({"tid":state["id"],"guest_path":token["path"],"legacy_id":legacy["id"]})}
    result=subprocess.run(["node","tests/browser_registration_v10.cjs"],env=env,capture_output=True,text=True,encoding="utf-8",timeout=200)
    assert result.returncode==0,result.stdout+result.stderr
    with closing(mahjong_store.connect(web_server.MAHJONG_DB_FILE)) as db:
        assert dict(db.execute("SELECT * FROM players WHERE id=?",(legacy["id"],)).fetchone()) == original_player
        assert db.execute("SELECT COUNT(*) FROM players WHERE name=?",("Legacy Browser",)).fetchone()[0] == 1
    account=registered_names.read_accounts(web_server.USERS_FILE)["users"]["legacy browser"]
    assert account["name"] == "Legacy Browser" and account["club_player_id"] == legacy["id"]
    print(result.stdout)
