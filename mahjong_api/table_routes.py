"""Authenticated table management; QR and NFC use the same membership service."""
import io
import json
import os
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from .auth import check_cookie_origin
from .tournament_routes import Current, Admin
from .table_models import TableJoinToken
from .table_membership import check

router = APIRouter()
write = [Depends(check_cookie_origin)]


@router.get("/api/club-tables")
def tables(request: Request, user: Current):
    return request.app.state.tables.list(user)


@router.get("/api/admin/club-tables")
def admin_tables(request: Request, user: Admin):
    return request.app.state.tables.list(user, True)


@router.post("/api/admin/club-tables", dependencies=write)
def create_table(request: Request, data: dict, user: Admin):
    return request.app.state.tables.create(data, user)


@router.get("/api/club-tables/{table_id}")
def table(request: Request, table_id: str, user: Current):
    return request.app.state.tables.get(table_id, user)


@router.post("/api/admin/club-tables/{table_id}", dependencies=write)
def update_table(request: Request, table_id: str, data: dict, user: Admin):
    return request.app.state.tables.update(table_id, data, user)


@router.post("/api/admin/club-tables/{table_id}/tokens", dependencies=write)
def issue_token(request: Request, table_id: str, data: dict, user: Admin):
    return request.app.state.tables.issue_token(table_id, data, user)


@router.post("/api/admin/table-tokens/{token_id}/revoke", dependencies=write)
def revoke_token(request: Request, token_id: str, user: Admin):
    return request.app.state.tables.revoke_token(token_id, user)


def token_link(request, token_id):
    service = request.app.state.tables
    with service.store.connect() as db:
        token = db.get(TableJoinToken, token_id)
        check(token is not None, "invalid_join_token")
        table = service._table(db, token.table_id)
        view = service._token_view(token, table)
        check(view["valid"], "invalid_join_token")
        origin = os.getenv("PUBLIC_SITE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
        return origin + view["path"], table.number, token.channel, token.seat or ("entry" if token.purpose == "table_landing" else token.channel)


@router.get("/api/admin/table-tokens/{token_id}/qr.png")
def token_qr(request: Request, token_id: str, user: Admin):
    import qrcode
    link, number, channel, label = token_link(request, token_id)
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, box_size=16, border=4)
    code.add_data(link); code.make(fit=True)
    out = io.BytesIO(); code.make_image(fill_color="black", back_color="white").save(out, format="PNG")
    return Response(out.getvalue(), media_type="image/png", headers={
        "Content-Disposition": 'inline; filename="table-' + str(number) + '-' + label + '.png"',
        "Cache-Control": "no-store", "X-QR-Target": quote(link, safe=":/.-_")})


@router.get("/api/admin/table-tokens/{token_id}/ndef.json")
def token_ndef(request: Request, token_id: str, user: Admin):
    link, number, channel, label = token_link(request, token_id)
    return Response(json.dumps({"table_number": number, "channel": channel,
        "records": [{"recordType": "url", "data": link}]}, ensure_ascii=False),
        media_type="application/json", headers={"Content-Disposition": 'attachment; filename="Table-' + str(number) + '-NFC.json"', "Cache-Control": "no-store"})


@router.get("/api/table-join-tokens/{token}")
def token_info(request: Request, token: str):
    return request.app.state.tables.token_info(token)


@router.post("/api/table-join-tokens/{token}/join", dependencies=write)
def token_join(request: Request, token: str, data: dict, user: Current):
    return request.app.state.tables.join_token(token, user, data.get("request_id"), data.get("seat"),
                                               data.get("confirm_entry") is True, data.get("match_id"))


@router.post("/api/club-tables/{table_id}/join", dependencies=write)
def manual_join(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.tables.join(table_id, user, data.get("seat"))


@router.get("/api/club-tables/{table_id}/seat-map")
def public_seat_map(request: Request, table_id: str):
    return request.app.state.tables.seat_map(table_id)


@router.put("/api/club-tables/{table_id}/my-seat", dependencies=write)
def set_my_seat(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.tables.set_my_seat(table_id, data, user)


@router.post("/api/club-tables/{table_id}/leave", dependencies=write)
def leave(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.tables.leave(table_id, user, data.get("reason", "voluntary"), data.get("match_id"))


@router.get("/api/club-tables/{table_id}/players")
def available_players(request: Request, table_id: str, user: Current, q: str = ""):
    return request.app.state.tables.available_players(table_id, user, q)


@router.post("/api/club-tables/{table_id}/players/preview", dependencies=write)
def preview(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.tables.preview_players(table_id, data.get("user_ids"), user)


@router.post("/api/club-tables/{table_id}/players", dependencies=write)
def add_players(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.tables.add_players(table_id, data, user)


@router.post("/api/admin/club-tables/{table_id}/reset", dependencies=write)
def reset(request: Request, table_id: str, data: dict, user: Admin):
    return request.app.state.tables.reset(table_id, data, user)


@router.post("/api/club-tables/{table_id}/reservations", dependencies=write)
def reserve(request: Request, table_id: str, data: dict, user: Current):
    return request.app.state.tables.reserve(table_id, data, user)


@router.post("/api/table-reservations/{reservation_id}", dependencies=write)
def update_reservation(request: Request, reservation_id: str, data: dict, user: Current):
    return request.app.state.tables.update_reservation(reservation_id, data, user)
