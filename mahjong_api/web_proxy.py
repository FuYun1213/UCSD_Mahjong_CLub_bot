"""Small same-origin bridge for the existing stdlib website.

Only the named player routes are forwarded. Login/session stay in web_server's
process; FastAPI verifies them through its configured account profile URL.
"""
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from .http_security import request_scheme


MAX_BODY = 9 * 1024 * 1024  # 8 MiB image plus multipart form overhead.
GET_PATHS = {"/api/club-tables", "/api/admin/club-tables", "/sit", "/score", "/score-i18n.js", "/api/sit", "/api/statistics", "/api/tournaments", "/api/tournament-players", "/api/external-config", "/api/external-deliveries", "/api/table-labels", "/api/qr.png"}
POST_PATHS = {"/api/admin/club-tables", "/api/sit", "/api/recognize_photo", "/api/submit_scores", "/api/confirm_scores", "/api/tournaments", "/api/external-config", "/api/external-test", "/api/table-labels"}
TABLE_GET = re.compile(r"/api/(?:club-tables/[A-Za-z0-9_-]{1,64}(?:/players|/seat-map|/reservation-default|/reservation-reminders|/reservation-candidates|/queue|/game-flow)?|table-join-tokens/[A-Za-z0-9_.-]{20,180}|admin/table-tokens/[A-Za-z0-9-]{1,64}/(?:qr.png|ndef.json))\Z")
TABLE_POST = re.compile(r"/api/(?:admin/club-tables/[A-Za-z0-9-]{1,64}(?:/tokens|/reset)?|admin/table-tokens/[A-Za-z0-9-]{1,64}/revoke|table-join-tokens/[A-Za-z0-9_.-]{20,180}/join|club-tables/[A-Za-z0-9-]{1,64}/(?:join|leave|all-last|cancel-game|queue/reorder|players(?:/preview)?|reservations)|table-reservations/[A-Za-z0-9-]{1,64})\Z")
REMOVE_POST = re.compile(r"/api/club-tables/[A-Za-z0-9_-]{1,64}/seats/[^/?#]{1,200}/remove\Z")
GAME_POST = re.compile(r"/api/club-tables/[A-Za-z0-9_-]{1,64}/games/[A-Za-z0-9-]{1,64}/end\Z")
TABLE_PUT = re.compile(r"/api/club-tables/[A-Za-z0-9_-]{1,64}/my-seat\Z")
SWAP_GET = re.compile(r"/api/tables/[A-Za-z0-9_-]{1,64}/seat-swap-requests\Z")
SWAP_POST = re.compile(r"/api/(?:tables/[A-Za-z0-9_-]{1,64}/seat-swap-requests|seat-swap-requests/[A-Za-z0-9-]{1,64}/(?:accept|decline|cancel))\Z")
TOURNAMENT_GET = re.compile(r"/api/(?:tournaments/[A-Za-z0-9-]{1,64}(?:/admin|/comeback|/participants)?|external-deliveries/[A-Za-z0-9-]{1,128})\Z")
TOURNAMENT_POST = re.compile(r"/api/(?:tournaments/[A-Za-z0-9-]{1,64}/(?:actions|delete|guest-recovery|guest-seat|manual-preview|tables/[A-Za-z0-9-]{1,64}/(?:check-in|start|preview-score))|external-deliveries/[A-Za-z0-9-]{1,128}/retry)\Z")
GET_PATTERN = re.compile(r"/api/(?:tables/[A-Za-z0-9_-]{1,64}|score_drafts/[A-Za-z0-9-]{1,64})\Z")
GUEST_GET = re.compile(r"/api/guest/tournaments/[A-Za-z0-9-]{1,64}\Z")
GUEST_POST = re.compile(r"/api/guest/tournaments/[A-Za-z0-9-]{1,64}/(?:join|leave|recover)\Z")
GET_PATHS.update({"/api/player-lookup", "/api/manual-score/context", "/api/scoring-table", "/api/scoring/current-table-context"})
POST_PATHS.update({"/api/player-lookup", "/api/manual-score/preview", "/api/manual-score/confirm", "/api/manual-score/upload"})
MANUAL_POST = re.compile(r"/api/manual-score/drafts/[A-Za-z0-9-]{1,64}/retry\Z")
MANUAL_GET = re.compile(r"/api/manual-score/drafts/[A-Za-z0-9-]{1,64}\Z")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _error(handler, status, code, message):
    content = json.dumps({"detail": {"code": code, "message": message}}, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)


def proxy_nfc_request(handler):
    """Return False for unrelated routes, True after handling an NFC request."""
    path = urlsplit(handler.path).path
    known = GUEST_GET.fullmatch(path) or GUEST_POST.fullmatch(path) or path in GET_PATHS | POST_PATHS or GET_PATTERN.fullmatch(path) or MANUAL_GET.fullmatch(path) or MANUAL_POST.fullmatch(path) or TOURNAMENT_GET.fullmatch(path) or TOURNAMENT_POST.fullmatch(path) or TABLE_GET.fullmatch(path) or TABLE_POST.fullmatch(path) or GAME_POST.fullmatch(path) or REMOVE_POST.fullmatch(path) or TABLE_PUT.fullmatch(path) or SWAP_GET.fullmatch(path) or SWAP_POST.fullmatch(path)
    if not known:
        return False
    allowed = (handler.command == "GET" and (path in GET_PATHS or GUEST_GET.fullmatch(path) or GET_PATTERN.fullmatch(path) or MANUAL_GET.fullmatch(path) or TOURNAMENT_GET.fullmatch(path) or TABLE_GET.fullmatch(path) or SWAP_GET.fullmatch(path))
               or handler.command == "POST" and (path in POST_PATHS or GUEST_POST.fullmatch(path) or MANUAL_POST.fullmatch(path) or TOURNAMENT_POST.fullmatch(path) or TABLE_POST.fullmatch(path) or GAME_POST.fullmatch(path) or REMOVE_POST.fullmatch(path) or SWAP_POST.fullmatch(path))
               or handler.command == "PUT" and TABLE_PUT.fullmatch(path))
    if not allowed:
        _error(handler, 405, "method_not_allowed", "请求方法不支持")
        return True
    try:
        size = int(handler.headers.get("Content-Length", "0"))
        if size < 0 or size > MAX_BODY or handler.headers.get("Transfer-Encoding"):
            _error(handler, 413, "photo_too_large", "上传文件过大或格式不支持")
            return True
    except ValueError:
        _error(handler, 400, "invalid_content_length", "上传长度无效")
        return True
    upstream = os.getenv("NFC_API_URL", "http://127.0.0.1:8001").rstrip("/")
    parsed = urlsplit(upstream)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
        _error(handler, 503, "invalid_api_configuration", "登分服务地址配置无效")
        return True
    headers = {name: handler.headers[name] for name in (
        "Cookie", "Authorization", "Content-Type", "Idempotency-Key", "Origin", "Referer",
        "Sec-Fetch-Site", "Host") if name in handler.headers}
    headers["X-Forwarded-Proto"] = request_scheme(handler)
    body = handler.rfile.read(size) if handler.command in {"POST", "PUT"} else None
    request = urllib.request.Request(upstream + handler.path, data=body, headers=headers, method=handler.command)
    # Never follow a redirect while carrying a user's Cookie or Authorization.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        try:
            response = opener.open(request, timeout=90)
        except urllib.error.HTTPError as exc:
            response = exc  # Preserve FastAPI 401/409/422 and the review payload.
        with response:
            content = response.read()
            handler.send_response(response.code)
            for name in ("Set-Cookie", "Content-Type", "Location", "WWW-Authenticate", "Content-Disposition", "X-QR-Target"):
                if response.headers.get(name):
                    handler.send_header(name, response.headers[name])
            handler.send_header("Content-Length", str(len(content)))
            handler.end_headers()
            handler.wfile.write(content)
    except (urllib.error.URLError, TimeoutError, OSError):
        _error(handler, 503, "score_service_unavailable", "登分服务暂不可用，请稍后重试；不要重复创建对局")
    return True
