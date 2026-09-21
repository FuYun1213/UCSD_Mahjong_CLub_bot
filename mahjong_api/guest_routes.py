"""Guest cookies are accepted only by these competition-scoped endpoints."""
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from .auth import check_cookie_origin
from .guest_service import GuestService, hashed
from .table_membership import membership_lock
from .tournament_routes import Admin

router = APIRouter()
_limits = defaultdict(list)


def rate_limit(request: Request):
    key, stamp = request.client.host if request.client else "unknown", time.monotonic()
    with membership_lock:
        history = [t for t in _limits[key] if stamp - t < 60]
        if len(history) >= 30:
            raise HTTPException(429, detail={"code": "guest_rate_limited"})
        _limits[key] = history + [stamp]


def check_guest_origin(request: Request):
    # Guest identity comes only from cookies, so a stray Authorization header
    # must never bypass the existing browser-origin defense.
    scope = dict(request.scope)
    scope["headers"] = [(key, value) for key, value in scope["headers"] if key.lower() != b"authorization"]
    check_cookie_origin(Request(scope))


write = [Depends(check_guest_origin), Depends(rate_limit)]


def service(request):
    return GuestService(request.app.state.tournaments, request.app.state.tables)


def cookie(tid):
    return "mahjong_guest_" + hashed(tid)[:16]


def set_cookie(request, response, tid, token):
    response.set_cookie(cookie(tid), token, max_age=90*86400, httponly=True, samesite="lax",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https", path="/")


@router.get("/api/guest/tournaments/{tid}")
def context(request: Request, tid: str):
    return service(request).context(tid, request.cookies.get(cookie(tid)))


@router.post("/api/guest/tournaments/{tid}/join", dependencies=write)
def join(request: Request, response: Response, tid: str, data: dict):
    result, token = service(request).join(tid, data, request.cookies.get(cookie(tid)))
    if token:
        set_cookie(request, response, tid, token)
    return result


@router.post("/api/guest/tournaments/{tid}/leave", dependencies=write)
def leave(request: Request, tid: str):
    return service(request).leave(tid, request.cookies.get(cookie(tid)))


@router.post("/api/guest/tournaments/{tid}/recover", dependencies=write)
def recover(request: Request, response: Response, tid: str, data: dict):
    token = service(request).recover(tid, data.get("token"))
    set_cookie(request, response, tid, token)
    return {"ok": True}


@router.post("/api/tournaments/{tid}/guest-recovery", dependencies=write)
def issue_recovery(request: Request, tid: str, data: dict, user: Admin):
    token = service(request).issue_recovery(tid, data, user)
    return {"url": "/?tournament=" + tid + "#guest_recovery=" + token}


@router.post("/api/tournaments/{tid}/guest-seat", dependencies=write)
def admin_guest_seat(request: Request, tid: str, data: dict, user: Admin):
    result, _ = service(request).join(tid, data, None, admin_user=user)
    return result
