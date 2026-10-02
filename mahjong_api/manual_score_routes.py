"""Manual entry shares global authentication and the existing CSRF policy."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .auth import check_cookie_origin
from .tournament_routes import Current

router = APIRouter()
write = [Depends(check_cookie_origin)]


@router.get("/api/player-lookup")
def search_players(request: Request, user: Current, q: str = ""):
    return request.app.state.manual_scores.search_players(q)


@router.post("/api/player-lookup", dependencies=write)
def lookup_players(request: Request, data: dict, user: Current):
    return request.app.state.manual_scores.lookup_players(data.get("user_ids"))


@router.get("/api/manual-score/context")
def context(request: Request, user: Current, table: str | None = None, match_id: str | None = None):
    return request.app.state.manual_scores.context(table, user, match_id)


@router.get("/api/manual-score/drafts/{draft_id}")
def get_draft(request: Request, draft_id: str, user: Current):
    return request.app.state.manual_scores.get_draft(draft_id, user)


@router.post("/api/manual-score/preview", dependencies=write)
def preview(request: Request, data: dict, user: Current):
    return request.app.state.manual_scores.preview(data, user)


@router.post("/api/manual-score/confirm", dependencies=write)
def confirm(request: Request, data: dict, user: Current):
    body, status = request.app.state.manual_scores.confirm(data, user)
    return JSONResponse(status_code=status, content=body)


@router.post("/api/manual-score/upload", dependencies=write)
def upload(request: Request, data: dict, user: Current):
    body, status = request.app.state.manual_scores.upload(data, user)
    return JSONResponse(status_code=status, content=body)


@router.post("/api/manual-score/drafts/{draft_id}/retry", dependencies=write)
def retry(request: Request, draft_id: str, user: Current):
    body, status = request.app.state.manual_scores.retry(draft_id, user)
    return JSONResponse(status_code=status, content=body)
