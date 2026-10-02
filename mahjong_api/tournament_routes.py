"""Tournament and configuration routes use the existing authenticated account."""
import io
import json
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote, urlsplit
from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .auth import get_current_user, check_cookie_origin
from .models import User
from .database_models import User as Account, Metadata
from .external_sync import audit, dump, server_key
from .tournament_models import ExternalDelivery
from .tournament_rules import DEFAULT_NAMES, comeback, name_key, scoring_value

router = APIRouter()
Current = Annotated[User, Depends(get_current_user)]


def administrator(user: Current):
    if user.role not in {"admin", "super_admin"}:
        raise HTTPException(403, detail={"code": "admin_required"})
    return user


Admin = Annotated[User, Depends(administrator)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1, max_length=40)
    data: dict = Field(default_factory=dict)


def catalog(request):
    service = request.app.state.service
    with service.store.connect() as db:
        rows = [{"id": p.id, "name": p.name} for p in db.scalars(select(Account))]
    known = {name_key(p["name"]) for p in rows}
    path = (request.app.state.settings.club_database_path or os.getenv("TOURNAMENT_CLUB_DATABASE_PATH")
            or os.getenv("MAHJONG_DB_FILE") or str(Path(__file__).resolve().parents[1] / "mahjong.sqlite3"))
    if path and Path(path).is_file():
        # Read only: an existing club DB is never migrated by the tournament service.
        with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
            for pid, name in db.execute("SELECT id, name FROM players"):
                if name_key(name) not in known:
                    rows.append({"id": "club-" + str(pid), "name": name})
                    known.add(name_key(name))
    return sorted(rows, key=lambda p: name_key(p["name"]))


@router.get("/api/tournament-players")
def players(request: Request, user: Current):
    return {"players": catalog(request)}


@router.get("/api/tournaments")
def tournaments(request: Request):
    return {"tournaments": request.app.state.tournaments.list()}


@router.post("/api/tournaments", dependencies=[Depends(check_cookie_origin)])
def create(request: Request, data: dict, user: Admin):
    return request.app.state.tournaments.create(data, user.id)


@router.get("/api/tournaments/{tid}")
def tournament(request: Request, tid: str):
    return public_state(request.app.state.tournaments.get(tid))


def public_state(state):
    # Public standings/seating links do not expose operator identities or audit data.
    state.pop("audit", None)
    state.pop("deliveries", None)
    state.pop("archived_by", None)
    for penalty in state.get("penalties", []):
        penalty.pop("created_by", None)
        penalty.pop("revoked_by", None)
    for table in (state.get("finals") or {}).get("tables", []):
        for hand in table["hands"]:
            hand.pop("actor_id", None)
    return state


@router.get("/api/tournaments/{tid}/admin")
def tournament_admin(request: Request, tid: str, user: Admin):
    return request.app.state.tournaments.get(tid)


@router.post("/api/tournaments/{tid}/delete", dependencies=[Depends(check_cookie_origin)])
def delete_tournament(request: Request, tid: str, data: dict, user: Admin):
    return request.app.state.tournaments.soft_delete(tid, data, user)


@router.post("/api/tournaments/{tid}/actions", dependencies=[Depends(check_cookie_origin)])
def action(request: Request, tid: str, payload: Command, user: Admin, background_tasks: BackgroundTasks):
    if payload.action == "player" and str(payload.data.get("player_id", "")).startswith("club-"):
        person = next((p for p in catalog(request) if p["id"] == payload.data["player_id"]), None)
        if not person:
            raise HTTPException(404, detail={"code": "not_found"})
        with request.app.state.service.store.connect() as db:
            if db.get(Account, person["id"]) is None:
                db.add(Account(**person))
    result = request.app.state.tournaments.apply(tid, payload.action, payload.data, user.id, actor_user=user)
    background_tasks.add_task(request.app.state.external.flush)
    return result


@router.get("/api/tournaments/{tid}/comeback")
def requirements(request: Request, tid: str, player: str, target: str):
    state = request.app.state.tournaments.get(tid)
    return comeback(state["standings"], player, target, scoring_value(state["settings"], "min_unit"))


@router.get("/api/external-config")
def external_config(request: Request, user: Admin):
    return request.app.state.external.config()


@router.post("/api/external-config", dependencies=[Depends(check_cookie_origin)])
def save_external(request: Request, data: dict, user: Admin):
    # The existing Admin dependency and cookie-origin check also guard key rotation.
    # Never echo this request body, persist it as metadata, or include it in an audit.
    if (data.get("adapter", "narts") == "narts" and data.get("enabled") is True
            and not data.get("api_key") and not server_key("narts")):
        raise HTTPException(409, detail={"code": "missing_api_key"})
    return request.app.state.external.save_config(data, user.id)


@router.post("/api/external-test", dependencies=[Depends(check_cookie_origin)])
def test_external(request: Request, user: Admin):
    return request.app.state.external.test(user.id)


@router.get("/api/external-deliveries")
def deliveries(request: Request, user: Admin):
    return {"deliveries": request.app.state.external.list()}


def authorize_delivery(request, key, user):
    with request.app.state.service.store.connect() as db:
        row = db.get(ExternalDelivery, key)
        if not row:
            raise HTTPException(404, detail={"code": "not_found"})
        if user.role not in {"admin", "super_admin"} and (row.tournament_id or row.actor_id != str(user.id)):
            raise HTTPException(403, detail={"code": "admin_required"})


@router.get("/api/external-deliveries/{key}")
def delivery_status(request: Request, key: str, user: Current):
    authorize_delivery(request, key, user)
    return request.app.state.external.get(key)


@router.post("/api/external-deliveries/{key}/retry", dependencies=[Depends(check_cookie_origin)])
def retry(request: Request, key: str, user: Current):
    authorize_delivery(request, key, user)
    if key.startswith("nfc-"):
        return request.app.state.external.schedule_retry(key, actor=user.id)
    return request.app.state.external.send(key, user.id, retry=True)


@router.get("/api/table-labels")
def labels(request: Request):
    with request.app.state.service.store.connect() as db:
        row = db.get(Metadata, "table_names_v1")
        return {"names": {**DEFAULT_NAMES, **(json.loads(row.value) if row else {})}}


@router.post("/api/table-labels", dependencies=[Depends(check_cookie_origin)])
def save_labels(request: Request, data: dict, user: Admin):
    names = data.get("names")
    if not isinstance(names, dict) or not all(str(k).isdigit() and int(k) > 0 and isinstance(v, str) and len(v) <= 120 for k, v in names.items()):
        raise HTTPException(422, detail={"code": "invalid_name"})
    with request.app.state.service.store.connect() as db:
        db.merge(Metadata(key="table_names_v1", value=dump(names)))
        audit(db, "", user.id, "table_names", {"names": names})
    return {"names": {**DEFAULT_NAMES, **names}}


@router.get("/api/qr.png")
def qr(request: Request, user: Admin, target: str, filename: str = "mahjong-qr"):
    import qrcode
    if not target.startswith("/") or target.startswith("//") or "\\" in target or any(ord(c) < 32 for c in target) or len(target) > 2000:
        raise HTTPException(422, detail={"code": "invalid_qr"})
    parsed = urlsplit(target)
    if parsed.path not in {"/", "/score", "/sit"}:
        raise HTTPException(422, detail={"code": "invalid_qr"})
    origin = os.getenv("PUBLIC_SITE_URL", "").rstrip("/")
    if not origin:
        scheme = "https" if request.headers.get("X-Forwarded-Proto") == "https" else request.url.scheme
        origin = scheme + "://" + request.headers.get("Host", request.url.netloc)
    link = origin + target
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, box_size=16, border=4)
    code.add_data(link)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    out = io.BytesIO()
    image.save(out, format="PNG")
    safe_name = re.sub(r'[\\/:*?"<>|\r\n]', "-", filename)[:100] + ".png"
    return Response(out.getvalue(), media_type="image/png", headers={
        "Content-Disposition": "inline; filename*=UTF-8''" + quote(safe_name),
        "X-QR-Target": quote(link, safe=":/?=&")})


@router.get("/i18n.js", include_in_schema=False)
def shared_i18n():
    return FileResponse(Path(__file__).resolve().parents[1] / "web" / "i18n.js", media_type="application/javascript")


@router.get("/score-i18n.js", include_in_schema=False)
def score_i18n():
    return FileResponse(Path(__file__).with_name("static") / "score-i18n.js", media_type="application/javascript")


class ParticipantCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)


@router.post("/api/tournaments/{tid}/tables/{mid}/check-in", dependencies=[Depends(check_cookie_origin)])
def check_in(request: Request, tid: str, mid: str, data: ParticipantCommand, user: Current):
    return public_state(request.app.state.tournaments.participant_action(tid, mid, "check_in", user, data.request_id))


@router.post("/api/tournaments/{tid}/tables/{mid}/start", dependencies=[Depends(check_cookie_origin)])
def start_table(request: Request, tid: str, mid: str, data: ParticipantCommand, user: Current):
    return public_state(request.app.state.tournaments.participant_action(tid, mid, "start_table", user, data.request_id))


@router.post("/api/tournaments/{tid}/tables/{mid}/preview-score", dependencies=[Depends(check_cookie_origin)])
def preview_score(request: Request, tid: str, mid: str, data: dict, user: Admin):
    from .tournament_rules import score_table
    state = request.app.state.tournaments.get(tid)
    table = next((t for r in state["rounds"] for t in r["tables"] if t["match_id"] == mid), None)
    if table is None:
        raise HTTPException(404, detail={"code": "not_found"})
    # No write and no ranking change; saved draft uses the same authoritative function.
    return score_table(state, table, data.get("scores"))


@router.get("/api/tournaments/{tid}/participants")
def participant_search(request: Request, tid: str, user: Admin, q: str = ""):
    state = request.app.state.tournaments.get(tid)
    rows = {str(p["id"]): p for p in request.app.state.tables._account_rows() if not p.get("disabled")}
    for player in state["players"]:
        if player.get("participant_type") != "guest" or state["settings"].get("allow_guest_auto_enrollment"):
            rows[player["id"]] = player
    return {"users": [dict(p) for p in rows.values() if name_key(q) in name_key(p["name"])][:50]}


@router.post("/api/tournaments/{tid}/manual-preview", dependencies=[Depends(check_cookie_origin)])
def manual_preview(request: Request, tid: str, data: dict, user: Admin):
    from .tournament_rules import require, score_table
    state = request.app.state.tournaments.get(tid)
    ids = data.get("players")
    require(isinstance(ids,list) and len(ids)==4 and all(isinstance(p,str) for p in ids) and len(set(ids))==4, "invalid_roster")
    for pid in ids:
        existing = next((p for p in state["players"] if p["id"]==pid), None)
        if existing is None:
            person = request.app.state.tables.lookup_accounts([pid])[0]
            state["players"].append({"id":person["id"],"name":person["name"]})
        else:
            require(existing.get("participant_type") != "guest" or state["settings"].get("allow_guest_auto_enrollment"), "guest_not_allowed")
    return score_table(state,{"seats":ids},data.get("scores"))
