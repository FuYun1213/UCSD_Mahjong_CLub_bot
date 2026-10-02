from contextlib import closing
"""Same-origin club website endpoints; shares its single global session."""
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlparse,parse_qs
from competition_service import CompetitionService
import competition_images

_services={}
_lock=threading.Lock()


def service(web):
    nfc=os.getenv("NFC_DATABASE_PATH") or str(web.ROOT/"nfc_data"/"matches.sqlite3")
    key=(str(web.MAHJONG_DB_FILE),nfc,str(web.USERS_FILE),str(web.YAKUMAN_UPLOAD_DIR))
    with _lock:
        if key not in _services:
            value=CompetitionService(*key);value.initialize();_services[key]=value
        return _services[key]


def error(web,handler,exception):
    denied=isinstance(exception,PermissionError)
    status=(403 if web.current_user(handler) else 401) if denied else 400
    web.response_json(handler,{"ok":False,"code":str(exception),"message":str(exception)},status)


def get(web,handler):
    parsed=urlparse(handler.path);path=parsed.path
    if not path.startswith("/api/competitions/"):return False
    try:
        match=re.fullmatch(r"/api/competitions/([a-zA-Z0-9-]{1,100})(?:/(admin|games|jobs))?",path)
        if not match:raise ValueError("competition_not_found")
        slug,suffix=match.groups();admin=suffix in {"admin","games","jobs"} or slug=="manage"
        if admin:
            name=web.require_user(handler)
            if not web.is_admin(name):raise PermissionError("admin_required")
        api=service(web);query=parse_qs(parsed.query)
        if slug=="manage":
            from contextlib import closing
            with closing(api.db()) as db:
                result={"competitions":[dict(r) for r in db.execute("SELECT slug,title,published FROM competitions ORDER BY start_at DESC")]}
        elif suffix=="games":result={"games":api.games(slug)}
        elif suffix=="jobs":result=api.jobs(slug)
        else:result=api.view(None if slug=="featured" else slug,admin=admin,query=query.get("q",[""])[0][:128],limit=10 if slug=="featured" else (None if admin else max(1,min(100,int(query.get("limit",["50"])[0])))),offset=max(0,min(100000,int(query.get("offset",["0"])[0]))),participant=query.get("participant",[None])[0])
        web.response_json(handler,result)
    except (ValueError,PermissionError) as exc:error(web,handler,exc)
    except Exception:
        web._logger.exception("Competition read failed")
        web.response_json(handler,{"code":"competition_unavailable","message":"competition_unavailable"},503)
    return True


def post(web,handler):
    path=urlparse(handler.path).path
    if not path.startswith("/api/competitions/"):return False
    try:
        web.enforce_rate_limit(handler)
        if not web.same_origin_allowed(handler):raise PermissionError("origin_denied")
        name=web.require_user(handler)
        if not web.is_admin(name):raise PermissionError("admin_required")
        match=re.fullmatch(r"/api/competitions/([a-zA-Z0-9-]{1,100})/(content|rules|rebuild|images|image-delete|game-correction)",path)
        if not match:raise ValueError("competition_not_found")
        size=int(handler.headers.get("Content-Length","0"))
        if size<0 or size>3*1024*1024 or handler.headers.get("Transfer-Encoding"):raise ValueError("request_too_large")
        data=json.loads(handler.rfile.read(size))
        if not isinstance(data,dict):raise ValueError("invalid_request")
        slug,action=match.groups();api=service(web);actor=web.stable_account_id(name)
        if action=="content":result=api.content(slug,data,actor)
        elif action=="rules":result=api.configure(slug,data,actor,web.is_super_admin(name),background=True)
        elif action=="rebuild":
            if not str(data.get("reason","")).strip():raise ValueError("reason_required")
            with closing(api.db()) as db:
                comp=api.find(db,slug)
                if comp["pending_rules_json"]:
                    from competition_time import phase
                    if phase(comp["start_at"],comp["end_at"])=="ended" and not (web.is_super_admin(name) and data.get("unlock_ended") is True):raise PermissionError("ended_competition_locked")
                    if data.get("confirmation")!=slug:raise ValueError("rules_confirmation_required")
            result=api.queue_rebuild(slug,data,actor)
        elif action=="images":result=competition_images.upload(api,data,actor)
        elif action=="image-delete":result=competition_images.delete(api,data.get("key"),actor)
        else:result=api.correct_game(slug,data,actor,background=True)
        web.response_json(handler,{"ok":True,**result},202 if result.get("job") else 200)
    except (ValueError,PermissionError) as exc:error(web,handler,exc)
    except Exception:
        web._logger.exception("Competition write failed")
        web.response_json(handler,{"code":"competition_unavailable","message":"competition_unavailable"},503)
    return True
