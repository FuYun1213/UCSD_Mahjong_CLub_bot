"""Real local website/API, isolated competition data, no bot or external notifications."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=5083);args=parser.parse_args()
    subprocess.run(["node",str(ROOT/"scripts/build_challenge_preview.cjs")],cwd=ROOT,check=True)
    data=ROOT/".local_challenge_v11/data";data.mkdir(parents=True,exist_ok=True)
    for key in list(os.environ):
        if key.startswith(("NARTS_","EXTERNAL_","NFC_","TABLE_","DISCORD_")):os.environ.pop(key,None)
    os.environ.update(TABLE_ACCOUNT_FILE=str(data/"accounts.json"),MAHJONG_DB_FILE=str(data/"club.sqlite3"),NFC_DATABASE_PATH=str(data/"scores.sqlite3"),NFC_ENV_FILE=str(data/"absent.env"),TABLE_TOKEN_SECRET_FILE=str(data/"table_token_secret"),DISCORD_RESERVATION_REMINDERS_ENABLED="false",SITE_TIMEZONE="America/Los_Angeles")
    import web_server as web
    import mahjong_store,registered_names,account_registration,competition_http,bot_action_log
    import uvicorn
    from mahjong_api.main import create_app
    from mahjong_api.config import Settings
    from mahjong_api.sheets import DisabledSheets
    web.USERS_FILE=data/"accounts.json";web.MAHJONG_DB_FILE=data/"club.sqlite3";web.LIVE_DB_FILE=data/"live.sqlite3";web.YAKUMAN_UPLOAD_DIR=data/"uploads"
    web.CREDENTIALS_FILE=data/"absent.json";web.BOT_TOKEN_FILE=data/"absent.env";bot_action_log.ACTION_LOG_FILE=str(data/"actions.json")
    names=["Alice","Bob","Carol","PreviewAdmin"]
    if not web.USERS_FILE.exists():
        users={}
        with closing(mahjong_store.connect(web.MAHJONG_DB_FILE)) as db:
            for name in names:
                player=mahjong_store.upsert_player(db,name);salt,digest=web.password_hash("LocalTest!2026")
                users[name.lower()]={"name":name,"account_id":"challenge-preview-"+name.lower(),"club_player_id":player["id"],"salt":salt,"password_hash":digest,"role":"super_admin" if name=="PreviewAdmin" else "user"}
            mahjong_store.import_game(db,names,[40000,30000,20000,10000],"2026-09-21T19:00:00-07:00",source="local_preview",nfc_match_id="challenge-preview-example")
        web.USERS_FILE.write_text(json.dumps({"users":users}),encoding="utf-8")
    registered_names.ensure_directory(web.USERS_FILE);account_registration.initialize(web)
    web.sheet_player_names=lambda:names
    # Use the real read-only history queries so the preview covers anonymous Recent Match.
    preview_read_json=web.read_json
    web.read_json=lambda path,default:default if Path(path).name in {"bot_action_log.json","replay_subscriptions.json"} else preview_read_json(path,default)
    asset_dir=ROOT/".local_challenge_v11/assets"
    class Handler(web.Handler):
        def log_message(self,*args):pass
        def do_GET(self):
            from urllib.parse import urlsplit
            path=urlsplit(self.path).path;asset=None
            if path.startswith("/preview-assets/") or path.endswith(".jsx"):asset=asset_dir/Path(path).name
            elif path in {"/","/login","/register","/registration-complete","/reservations","/manual-score"} or path.startswith("/challenges/"):asset=asset_dir/"index.html"
            if asset and asset.is_file():
                payload=asset.read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8" if asset.suffix==".html" else "text/css" if asset.suffix==".css" else "application/javascript");self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload);return
            super().do_GET()
    server=web.WebHTTPServer(("127.0.0.1",args.port),Handler);url="http://127.0.0.1:"+str(args.port)
    listener=socket.socket();listener.bind(("127.0.0.1",0));os.environ["NFC_API_URL"]="http://127.0.0.1:"+str(listener.getsockname()[1])
    settings=Settings(database_path=data/"scores.sqlite3",club_database_path=str(data/"club.sqlite3"),auth_profile_url=url+"/api/session",mock_auth_enabled=False,sheets_enabled=False)
    app=create_app(settings,DisabledSheets());asgi=uvicorn.Server(uvicorn.Config(app,log_level="warning"))
    threading.Thread(target=server.serve_forever,daemon=True).start();threading.Thread(target=asgi.run,kwargs={"sockets":[listener]},daemon=True).start()
    deadline=time.monotonic()+30
    while not asgi.started and time.monotonic()<deadline:time.sleep(.05)
    if not asgi.started:raise RuntimeError("Preview API failed to start")
    from mahjong_api.database_models import TableState
    from mahjong_api.table_membership import register_ordinary
    from mahjong_api.store import now
    from sqlalchemy import select
    from uuid import uuid4
    with app.state.service.store.connect() as db:
        if db.scalar(select(TableState).where(TableState.table_id=="1")) is None:
            row=TableState(table_id="1",current_match_id=str(uuid4()),updated_at=now())
            db.add(row);db.flush();register_ordinary(db,row)
    api=competition_http.service(web);api.seed();api.sync();stop=api.start_worker(2)
    (data.parent/"preview.json").write_text(json.dumps({"url":url,"pid":os.getpid(),"accounts":names,"password":"LocalTest!2026","production_data_used":False},indent=2),encoding="utf-8")
    print(url,flush=True)
    try:
        while True:time.sleep(.5)
    except KeyboardInterrupt:pass
    finally:stop.set();asgi.should_exit=True;server.shutdown()

if __name__=="__main__":main()
