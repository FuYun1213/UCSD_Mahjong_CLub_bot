"""Trusted proxy boundary shared by website cookies and its API bridge."""
import ipaddress
import os
from urllib.parse import urlsplit


def trusted_proxy(handler):
    try:
        peer = ipaddress.ip_address(handler.client_address[0])
        return any(peer in ipaddress.ip_network(value.strip()) for value in
                   os.getenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128").split(",") if value.strip())
    except ValueError:
        return False


def request_scheme(handler):
    if trusted_proxy(handler) and handler.headers.get("X-Forwarded-Proto") in {"https", "http"}:
        return handler.headers["X-Forwarded-Proto"]
    return "http"


def origin(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


def same_origin(handler):
    if handler.headers.get("Sec-Fetch-Site") == "cross-site":
        return False
    expected = origin(request_scheme(handler) + "://" + handler.headers.get("Host", ""))
    public = origin(os.getenv("PUBLIC_SITE_URL", ""))
    allowed = {x for x in (expected, public) if x}
    for name in ("Origin", "Referer"):
        if handler.headers.get(name) and origin(handler.headers[name]) not in allowed:
            return False
    return True
