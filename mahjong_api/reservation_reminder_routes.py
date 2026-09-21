"""Authenticated reservation clock defaults and current-table reminders."""
from fastapi import APIRouter, Request

from .reservation_reminders import reservation_default, reservation_reminders
from .tournament_routes import Current

router = APIRouter()


@router.get("/api/club-tables/{table_id}/reservation-default")
def default_time(request: Request, table_id: str, user: Current):
    return reservation_default(request.app.state.tables, table_id, user)


@router.get("/api/club-tables/{table_id}/reservation-reminders")
def reminders(request: Request, table_id: str, user: Current):
    return reservation_reminders(request.app.state.tables, table_id, user)


@router.get("/api/club-tables/{table_id}/reservation-candidates")
def candidates(request: Request, table_id: str, user: Current):
    data = dict(request.query_params)
    for field in ("month", "day"):
        if field in data:
            try:
                data[field] = int(data[field])
            except (TypeError, ValueError):
                from .store import Conflict
                raise Conflict("invalid_reservation_time", "invalid_reservation_time") from None
    return request.app.state.tables.display_names(
        request.app.state.tables.reservation_candidates(table_id, data, user))
