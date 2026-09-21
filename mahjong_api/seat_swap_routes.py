"""Authenticated consent requests; requester identity always comes from session."""
from fastapi import APIRouter, Depends, Request
from .auth import check_cookie_origin
from .tournament_routes import Current

router = APIRouter()
write = [Depends(check_cookie_origin)]


@router.get("/api/tables/{table_id}/seat-swap-requests")
def swap_requests(request: Request, table_id: str, user: Current):
    return request.app.state.seat_swaps.list(table_id, user)


@router.post("/api/tables/{table_id}/seat-swap-requests", dependencies=write)
def create_swap(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.seat_swaps.create(table_id, data, user)


@router.post("/api/seat-swap-requests/{request_id}/{action}", dependencies=write)
def respond_to_swap(request: Request, request_id: str, action: str, user: Current):
    return request.app.state.seat_swaps.respond(request_id, action, user)
