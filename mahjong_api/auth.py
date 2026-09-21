"""Replace get_current_user (or override its dependency) with your real auth."""

import secrets
import requests
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException, Request

from .models import User


MOCK_USERS = {
    f"demo-{index}": User(id=f"u{index}", name=f"玩家{index}")
    for index in range(1, 6)
}


def get_current_user(request: Request) -> User:
    """Mock-only credential lookup; arbitrary token values are never identities.

    In production validate session expiry/revocation or the bearer signature,
    issuer, audience and expiry against the existing account system, then return
    an immutable account ID and current display name. Mock auth is off by default.
    An explicitly supplied invalid Authorization header never falls back to a cookie.
    """
    authorization = request.headers.get("Authorization")
    if authorization is not None:
        parts = authorization.split()
        credential = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None
    else:
        credential = request.cookies.get("session_id")

    settings = request.app.state.settings
    user = MOCK_USERS.get(credential) if settings.mock_auth_enabled else None
    if user is not None:
        return user
    if settings.auth_profile_url:
        # Trusted server-configured endpoint only. The browser cannot choose it.
        # Never fall back to a cookie if an explicit Authorization header is invalid.
        forwarded = ({"Authorization": authorization} if authorization is not None
                     else {"Cookie": request.headers.get("Cookie", "")})
        try:
            response = requests.get(settings.auth_profile_url, headers=forwarded,
                                    timeout=5, allow_redirects=False)
            if response.status_code >= 500:
                raise requests.RequestException("account service unavailable")
            if response.status_code == 200:
                payload = response.json()
                profile = payload.get("profile", payload)
                if profile and profile.get("id") is not None and profile.get("name"):
                    return User(id=profile["id"], name=profile["name"], role=profile.get("role", "user"))
        except (requests.RequestException, ValueError) as exc:
            raise HTTPException(503, detail={"code": "account_service_unavailable"}) from exc

    # Construct a local return target ourselves, never reflect a supplied redirect URL.
    query = urlencode({key: request.query_params[key] for key in ("table", "seat") if key in request.query_params})
    return_path = settings.frontend_sit_path if request.url.path == "/api/sit" else "/score"
    return_url = return_path + (f"?{query}" if query else "")
    if request.url.path.startswith("/api/table-join-tokens/"):
        return_url = "/join/" + request.path_params.get("token", "")
    elif request.url.path.startswith("/api/manual-score") or request.url.path == "/api/player-lookup":
        return_url = "/manual-score" + (f"?{query}" if query else "")
    elif "reservation" in request.url.path:
        return_url = "/reservations"
    # The existing global login is the only authentication UI. Preserve a trusted
    # same-origin page (including table/draft query) when an operation requires it.
    source = urlsplit(request.headers.get("Referer", ""))
    page_paths = {"/", "/score", "/sit", "/manual-score", "/reservations"}
    trusted_origins = {str(request.base_url).rstrip("/"), *settings.allowed_origins}
    if (f"{source.scheme}://{source.netloc}" in trusted_origins
            and (source.path in page_paths or source.path.startswith(("/join/", "/join-table/")))):
        return_url = source.path + ("?" + source.query if source.query else "")
    separator = "&" if "?" in settings.login_url else "?"
    login_url = settings.login_url + separator + urlencode({"redirect_url": return_url})
    raise HTTPException(
        401,
        detail={"code": "not_authenticated", "message": "请先登录", "redirect_url": login_url},
        headers={"WWW-Authenticate": "Bearer", "Location": login_url},
    )


def require_yolo_key(request: Request) -> None:
    """Machine credential, separate from player cookies or bearer tokens."""
    expected = request.app.state.settings.yolo_api_key
    if not expected:
        raise HTTPException(503, detail={"code": "yolo_not_configured", "message": "尚未配置 YOLO API Key"})
    supplied = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, detail={"code": "invalid_yolo_key", "message": "YOLO API Key 无效"})


def check_cookie_origin(request: Request) -> None:
    """Reject known cross-site cookie writes, including cross-site GET navigation.

    For production prefer POST from your /sit page and add your existing CSRF
    dependency. Requests without browser origin metadata (e.g. curl) are allowed.
    """
    if request.headers.get("Authorization"):
        return
    origin = request.headers.get("Origin")
    if not origin and request.headers.get("Referer"):
        parsed = urlsplit(request.headers["Referer"])
        origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = {str(request.base_url).rstrip("/"), *request.app.state.settings.allowed_origins}
    if origin is not None and origin not in allowed:
        raise HTTPException(403, detail={"code": "untrusted_origin"})
    if origin is None and request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HTTPException(403, detail={"code": "untrusted_origin"})
