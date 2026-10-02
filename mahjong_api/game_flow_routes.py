"""Authenticated ordinary game lifecycle endpoints."""
from fastapi import APIRouter, Depends, Request

from .auth import check_cookie_origin
from .tournament_routes import Current


router = APIRouter()
write = [Depends(check_cookie_origin)]


@router.get("/api/club-tables/{table_id}/game-flow")
def game_flow(request: Request, table_id: str, user: Current):
    return request.app.state.game_flow.state(table_id, user)


@router.post("/api/club-tables/{table_id}/all-last", dependencies=write)
def all_last(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.game_flow.all_last(table_id, data, user)


@router.post("/api/club-tables/{table_id}/cancel-game", dependencies=write)
def cancel_game(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.game_flow.cancel_game(table_id, data, user)


@router.post("/api/club-tables/{table_id}/games/{game_id}/end", dependencies=write)
def record_end(request: Request, table_id: str, game_id: str, data: dict, user: Current):
    return request.app.state.game_flow.record_end(table_id, game_id, data, user)


@router.post("/api/club-tables/{table_id}/seats/{target_user_id}/remove", dependencies=write)
def remove_other(request: Request, table_id: str, target_user_id: str,
                 data: dict, user: Current):
    return request.app.state.game_flow.remove_other(table_id, target_user_id, data, user)
