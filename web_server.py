import request_performance
request_performance.install()
from mahjong_api.http_security import trusted_proxy, request_scheme, same_origin
import json
import contextvars
import logging
import argparse
import base64
import hashlib
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlencode, unquote
from datetime import datetime

from bot_action_log import get_action, get_recent_actions, mark_reverted, record_action
import mahjong_store
import player_directory
import registered_names
from functools import wraps
from contextlib import closing
from mahjong_api.web_proxy import proxy_nfc_request
import account_registration
import account_discord
from account_passwords import hash_password, verify_password

ROOT = Path(__file__).resolve().parent
YAKUMAN_UPLOAD_DIR = ROOT / "yakuman_uploads"
VENDOR_DIR = ROOT / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import gspread
except ImportError:
    gspread = None


WEB_DIR = Path(os.getenv("WEB_ASSET_DIR", str(ROOT / "web")))
SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q"
GUILD_ID = "1278056421224747162"
CREDENTIALS_FILE = ROOT / "credentials.json"
USERS_FILE = Path(os.getenv("TABLE_ACCOUNT_FILE", str(ROOT / "web_users.json")))
LIVE_DB_FILE = ROOT / "live_games.sqlite3"
MAHJONG_DB_FILE = Path(os.getenv("MAHJONG_DB_FILE", str(ROOT / "mahjong.sqlite3")))
BOT_TOKEN_FILE = ROOT / "DISCORD_BOT_TOKEN.env"
DISCORD_CHANNEL_NAME = "game-record"
YAKUMAN_WINNER_INDEX = 18
YAKUMAN_DEAL_IN_INDEX = 19
YAKUMAN_NAMES_INDEX = 20
TERM_OPTIONS = {"Fall", "Winter", "Spring"}
TERM_ORDER = ["Winter", "Spring", "Fall"]
DEFAULT_ADMINS = {normalize.casefold() for normalize in ["Jin", "Kevin C", "Andy", "糸色望"]}
DEFAULT_SUPER_ADMINS = {normalize.casefold() for normalize in ["Jin", "Kevin C"]}
ROLE_ORDER = {"user": 0, "admin": 1, "super_admin": 2}
YAKUMAN_OPTIONS = mahjong_store.YAKUMAN_OPTIONS

_sheet = None
_sessions = {}
_session_account_ids = {}
_rate_limits = {}
_rate_limits_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()
_account_id_lock = threading.Lock()

BLOCKED_STATIC_SUFFIXES = {
    ".env",
    ".json",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".py",
    ".pyc",
    ".pem",
    ".key",
}
BLOCKED_STATIC_NAMES = {
    "credentials.json",
    "web_users.json",
    "bot_action_log.json",
    "replay_subscriptions.json",
    "wwyd_group_stats.json",
    "discord_bot_token.env",
}
MAX_JSON_BODY_BYTES = 16_000_000
MAX_YAKUMAN_PHOTO_BYTES = 10 * 1024 * 1024
WRITE_RATE_LIMIT = 30
WRITE_RATE_WINDOW_SECONDS = 60
SHEET_CACHE_TTL_SECONDS = 120
PLAYER_CACHE_TTL_SECONDS = 300
SESSION_MAX_AGE_SECONDS = 180 * 24 * 60 * 60


def read_json(path, fallback):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path, value):
    if Path(path) == Path(USERS_FILE):
        registered_names.write_accounts(path, value)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def account_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with registered_names.account_lock(USERS_FILE):
            return function(*args, **kwargs)
    return wrapped


def cached_value(key, ttl_seconds, loader):
    now = time.time()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached["saved_at"] < ttl_seconds:
            return cached["value"]

    try:
        value = loader()
    except Exception:
        with _cache_lock:
            cached = _cache.get(key)
            if cached:
                return cached["value"]
        raise

    with _cache_lock:
        _cache[key] = {"saved_at": now, "value": value}
    return value


def clear_sheet_cache():
    with _cache_lock:
        _cache.clear()


PUBLIC_REQUEST_ERROR = "The request could not be completed. Please retry."
PUBLIC_SYNC_WARNING = "External synchronization failed. Local changes are saved; please retry synchronization."
_logger = logging.getLogger(__name__)


def public_response_body(body, status=200):
    """Strip diagnostic strings at the response boundary, never from audit/logs."""
    def sanitize(value):
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            diagnostic = key == "error" or key.endswith("_error") or key == "sheet_errors"
            if diagnostic and item:
                _logger.error("Website internal diagnostic: %s", item)
                result[key] = [PUBLIC_SYNC_WARNING] if isinstance(item, list) else PUBLIC_REQUEST_ERROR
            else:
                result[key] = sanitize(item)
        return result
    from account_images import public_avatars
    result = public_avatars(sanitize(body))
    if status >= 500 and isinstance(result, dict):
        _logger.error("Website request failed: %s", body.get("message", "server error"), exc_info=True)
        result["message"] = PUBLIC_REQUEST_ERROR
        if "detail" in result:
            result["detail"] = {"code": "server_error"}
    return result


def response_json(handler, body, status=200):
    payload = json.dumps(public_response_body(body, status), ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def client_ip(handler):
    forwarded = handler.headers.get("X-Forwarded-For", "")
    if forwarded and trusted_proxy(handler):
        return forwarded.split(",")[0].strip()
    return handler.client_address[0]


def enforce_rate_limit(handler):
    now = time.time()
    key = client_ip(handler)
    with _rate_limits_lock:
        history = [stamp for stamp in _rate_limits.get(key, []) if now - stamp < WRITE_RATE_WINDOW_SECONDS]
        if len(history) >= WRITE_RATE_LIMIT:
            raise PermissionError("Too many requests. Please wait a minute and try again.")
        history.append(now)
        _rate_limits[key] = history
        if len(_rate_limits) > 1024:
            for expired in [ip for ip, stamps in _rate_limits.items() if not stamps or now - stamps[-1] >= WRITE_RATE_WINDOW_SECONDS]:
                _rate_limits.pop(expired, None)


def same_origin_allowed(handler):
    return same_origin(handler)


def secure_cookie_suffix(handler):
    secure = "; Secure" if request_scheme(handler) == "https" or os.getenv("PUBLIC_SITE_URL", "").startswith("https://") else ""
    return f"; HttpOnly; SameSite=Lax{secure}; Path=/"


def persistent_session_cookie_suffix(handler):
    return f"; Max-Age={SESSION_MAX_AGE_SECONDS}" + secure_cookie_suffix(handler)


def is_blocked_static_path(path):
    clean = path.strip("/").lower()
    if not clean:
        return False
    name = Path(clean).name
    suffix = Path(clean).suffix
    if name in BLOCKED_STATIC_NAMES:
        return True
    return suffix in BLOCKED_STATIC_SUFFIXES


def safe_float(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return 999


def format_number(value):
    number = safe_float(value)
    if number is None:
        return str(value) if value not in (None, "") else ""
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def local_now_string():
    from zoneinfo import ZoneInfo
    from competition_time import site_timezone
    return datetime.now(ZoneInfo(site_timezone())).strftime("%Y-%m-%d %H:%M:%S")


def parse_web_time(value):
    value = (value or "").strip()
    if not value:
        return local_now_string()
    if "T" in value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            from zoneinfo import ZoneInfo
            from competition_time import site_timezone
            parsed = parsed.astimezone(ZoneInfo(site_timezone()))
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return value


WIND_FIELDS = [
    ("E", "east", "East Wind"),
    ("S", "south", "South Wind"),
    ("W", "west", "West Wind"),
    ("N", "north", "North Wind"),
]


def normalize_source_player_id(name):
    normalized = re.sub(r"[^a-z0-9]+", "-", name.strip().casefold()).strip("-")
    return f"ucsd-{normalized or 'player'}"


def game_entries_from_payload(data):
    if any(data.get(f"{wind_key}_name") or data.get(f"{wind_key}_score") for _, wind_key, _ in WIND_FIELDS):
        entries = []
        for seat_wind, wind_key, label in WIND_FIELDS:
            entries.append(
                {
                    "seatWind": seat_wind,
                    "label": label,
                    "name": (data.get(f"{wind_key}_name") or "").strip(),
                    "score": data.get(f"{wind_key}_score", ""),
                }
            )
        return entries

    legacy_keys = ["rank1", "rank2", "rank3", "rank4"]
    entries = []
    for index, key in enumerate(legacy_keys):
        seat_wind, _, label = WIND_FIELDS[(0, 2, 1, 3)[index]]  # Legacy arrays: E, W, S, N
        entries.append(
            {
                "seatWind": seat_wind,
                "label": label,
                "name": (data.get(f"{key}_name") or "").strip(),
                "score": data.get(f"{key}_score", ""),
            }
        )
    return entries


def ordered_game_from_entries(entries):
    players = [entry["name"] for entry in entries]
    if any(not player for player in players):
        raise ValueError("Please enter all four player names.")
    if len({player.casefold() for player in players}) != 4:
        raise ValueError("Player names must be unique.")

    try:
        scores = [int(entry["score"]) for entry in entries]
    except (TypeError, ValueError):
        raise ValueError("Scores must be whole numbers.")

    if any(score % 100 != 0 for score in scores):
        raise ValueError("Riichi scores must end in 00.")
    if sum(scores) != 100000:
        raise ValueError(f"Total score is {sum(scores)}, expected 100000.")

    for entry, score in zip(entries, scores):
        entry["score"] = score

    wind_order = {seat_wind: index for index, (seat_wind, _, _) in enumerate(WIND_FIELDS)}
    ranked_entries = sorted(entries, key=lambda entry: (-entry["score"], wind_order[entry["seatWind"]]))
    return [entry["name"] for entry in ranked_entries], [entry["score"] for entry in ranked_entries], ranked_entries, entries


def narts_played_at(final_time):
    from competition_time import event_time, utc_now
    try:
        return event_time(str(final_time))
    except (TypeError, ValueError):
        return utc_now()


def submit_narts_match(sql_game_id, final_time, wind_entries, actor=""):
    from mahjong_api.legacy_external import sync_legacy
    try:
        return sync_legacy(sql_game_id, narts_played_at(final_time), wind_entries, MAHJONG_DB_FILE, actor)
    except Exception:
        # The local game is already committed. Never leak provider bodies or keys.
        return {"enabled": True, "ok": False, "status": "failed", "error_code": "network_error",
                "request_id": f"legacy-sql-{sql_game_id}"}


def get_sheet():
    global _sheet
    if gspread is None:
        raise RuntimeError("gspread is not installed in this Python environment")
    if _sheet is None:
        client = gspread.service_account(filename=str(CREDENTIALS_FILE))
        _sheet = client.open_by_key(SHEET_ID)
    return _sheet


def get_discord_token():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token:
        return token
    if not BOT_TOKEN_FILE.exists():
        return ""
    for line in BOT_TOKEN_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "DISCORD_BOT_TOKEN":
            return value.strip()
    return ""


def discord_request(method, path, payload=None):
    token = get_discord_token()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")

    data = None
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "UCSD-Mahjong-Web (local)",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else None


def find_game_record_channel_id():
    configured = os.getenv("DISCORD_GAME_RECORD_CHANNEL_ID")
    if configured:
        return configured

    channels = discord_request("GET", f"/guilds/{GUILD_ID}/channels")
    for channel in channels:
        if channel.get("name") == DISCORD_CHANNEL_NAME and channel.get("type") == 0:
            return channel["id"]
    raise RuntimeError(f"Could not find #{DISCORD_CHANNEL_NAME} in guild {GUILD_ID}")


def sorted_player_names(names):
    return sorted(names, key=lambda name: name.casefold())


RANKING_TYPES = {
    "quarter_games": {"label": "Quarter Games", "worksheet": "Ranking Quarter",
        "fallback_name_index": 6, "fallback_value_index": 7, "value_headers": ["games played", "games"]},
    "total_games": {"label": "Total Games", "worksheet": "Ranking",
        "fallback_name_index": 6, "fallback_value_index": 7, "value_headers": ["total games", "games"]},
    "quarter_pt": {
        "label": "Quarter PT",
        "worksheet": "Ranking Quarter",
        "fallback_name_index": 3,
        "fallback_value_index": 4,
        "value_headers": ["quarter pt", "pt", "points"],
    },
    "quarter_mmr": {
        "label": "Quarter MMR",
        "worksheet": "Ranking Quarter",
        "fallback_name_index": 0,
        "fallback_value_index": 1,
        "value_headers": ["quarter mmr", "mmr"],
    },
    "total_mmr": {
        "label": "Total MMR",
        "worksheet": "Ranking",
        "fallback_name_index": 0,
        "fallback_value_index": 1,
        "value_headers": ["total mmr", "mmr", "rating"],
    },
    "total_pt": {
        "label": "Total PT",
        "worksheet": "Ranking",
        "fallback_name_index": 0,
        "fallback_value_index": 2,
        "value_headers": ["total pt", "pt", "points"],
    },
    "history_highest_mmr": {
        "label": "History Highest MMR",
        "worksheet": "Ranking",
        "fallback_name_index": 0,
        "fallback_value_index": 3,
        "value_headers": ["history highest mmr", "highest mmr", "max mmr", "best mmr"],
    },
}


def find_header_index(headers, candidates):
    normalized_headers = [normalize_name(header) for header in headers]
    for candidate in candidates:
        normalized_candidate = normalize_name(candidate)
        for index, header in enumerate(normalized_headers):
            if header == normalized_candidate or normalized_candidate in header:
                return index
    return None


def sheet_rankings(kind="quarter_pt", limit=25):
    sheet = get_sheet()
    if sheet is None:
        return []

    config = RANKING_TYPES.get(kind, RANKING_TYPES["quarter_pt"])
    rows = sheet.worksheet(config["worksheet"]).get_all_values()
    headers = rows[0] if rows else []
    name_index = config["fallback_name_index"] if kind in {"quarter_games", "total_games"} else find_header_index(headers, ["name", "player"])
    value_index = find_header_index(headers, config["value_headers"])
    if name_index is None:
        name_index = config["fallback_name_index"]
    if value_index is None:
        value_index = config["fallback_value_index"]
    label = config["label"]

    players = []
    for row in rows[1:]:
        if len(row) <= max(name_index, value_index):
            continue
        name = row[name_index].strip()
        ranking_value = row[value_index]
        if not name:
            name = next((cell.strip() for cell in row if cell.strip() and safe_float(cell) is None), "")
        numeric_values = [safe_float(cell) for cell in row]
        numeric_values = [value for value in numeric_values if value is not None]
        value = safe_float(ranking_value)
        if value is None and numeric_values:
            value = numeric_values[0]
            ranking_value = value
        if not name or value is None:
            continue
        players.append(
            {
                "name": name,
                "value": format_number(ranking_value),
                "label": label,
                "avatar": avatar_for_name(name),
                "raw_value": value,
            }
        )

    players.sort(key=lambda player: player["raw_value"], reverse=True)
    for index, player in enumerate(players, start=1):
        player["rank"] = index
        player.pop("raw_value", None)
    return players[:limit]


def cached_rankings(kind="quarter_pt", limit=500):
    return cached_value(
        ("rankings", kind, limit),
        SHEET_CACHE_TTL_SECONDS,
        lambda: sheet_rankings(kind=kind, limit=limit),
    )


def sql_available():
    try:
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            return mahjong_store.has_games(connection)
    except Exception as error:
        print(f"Web dashboard: SQLite unavailable: {error}")
        return False


def sql_rankings(kind="quarter_pt", limit=500, quarter=None):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        rows = mahjong_store.ranking(connection, kind=kind, limit=limit, quarter=quarter)
    for row in rows:
        row["avatar"] = avatar_for_name(row["name"])
        row["icon"] = icon_for_name(row["name"])
    return rows


def sql_recent_games(limit=12):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        games, _ = mahjong_store.recent_games(connection, limit=limit)
    return games


def sql_recent_games_for_player(player_name, limit=5, quarter=None):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.recent_games(connection, limit=limit, player_name=player_name, quarter=quarter)


def sql_recent_games_for_players(player_names, limit=50, quarter=None):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.games_with_players(connection, player_names, limit=limit, quarter=quarter)


def sql_quarter_pt_history(player_name, limit=200, quarter=None):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.quarter_pt_history(connection, player_name, quarter=quarter, limit=limit)


def sql_quarter_context():
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return {
            "current_quarter": mahjong_store.latest_quarter(connection),
            "quarters": mahjong_store.quarters(connection),
        }


def sql_player_names():
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.player_names(connection)


def sql_user_rank_summary(username, quarter=None):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        summary = mahjong_store.user_summary(connection, username, quarter=quarter)
    if summary:
        summary["avatar"] = avatar_for_name(username)
        summary["icon"] = icon_for_name(username)
    return summary


def sql_annual_summary(username, school_year=None):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.annual_summary(connection, username, school_year=school_year)


def sql_player_stats(limit=500):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.player_stats(connection, limit=limit)


def sql_recent_yakuman(limit=12):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.recent_yakuman(connection, limit=limit)


def sql_revert_candidates(limit=12):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.recent_revert_candidates(connection, limit=limit)


def sql_admin_game_rows(page=1, per_page=10, played_at="", player_names=None):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.admin_game_rows(connection, page=page, per_page=per_page, played_at=played_at, player_names=player_names)


def sql_yakuman_leaders(limit=10):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.yakuman_leaders(connection, limit=limit)


def sql_match_candidates(player_names, played_at="", limit=12):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        rows = mahjong_store.games_with_players(connection, player_names, limit=limit)
    if played_at:
        target_date = mahjong_store.date_key(played_at)
        if target_date:
            dated = [row for row in rows if mahjong_store.date_key(row.get("date", "")) == target_date]
            rows = dated or rows
    return rows


def sql_player_status(player_names):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.player_status_map(connection, player_names)


def sql_game_mmr_deltas(game_id):
    if not game_id:
        return []
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        return mahjong_store.game_mmr_deltas(connection, game_id)


def result_emoji(rank):
    emojis = ["\U0001f436", "\U0001f948", "\U0001f949", "\U0001faa6"]
    return emojis[rank - 1] if 1 <= rank <= 4 else "\U0001f004"


def move_emoji(diff):
    if diff > 0:
        return "??"
    if diff < 0:
        return "??"
    return "?"


def build_game_result(players, scores, pre_status, post_status, mmr_deltas, action_id=None):
    rows = []
    for index, name in enumerate(players):
        pre = pre_status.get(name, {})
        post = post_status.get(name, {})
        mmr_delta = safe_float(mmr_deltas[index] if index < len(mmr_deltas) else 0) or 0
        pt_delta = (safe_float(post.get("pt", 0)) or 0) - (safe_float(pre.get("pt", 0)) or 0)
        pre_mmr_rank = safe_int(pre.get("mmr_rank", 999))
        post_mmr_rank = safe_int(post.get("mmr_rank", 999))
        pre_pt_rank = safe_int(pre.get("pt_rank", 999))
        post_pt_rank = safe_int(post.get("pt_rank", 999))
        rows.append(
            {
                "name": name,
                "rank": index + 1,
                "emoji": result_emoji(index + 1),
                "score": scores[index],
                "mmr": round(safe_float(post.get("mmr", 1500)) or 1500, 2),
                "mmr_delta": round(mmr_delta, 4),
                "mmr_rank": post_mmr_rank if post_mmr_rank != 999 else None,
                "mmr_rank_change": pre_mmr_rank - post_mmr_rank if pre_mmr_rank != 999 and post_mmr_rank != 999 else 0,
                "pt": round(safe_float(post.get("pt", 0)) or 0, 1),
                "pt_delta": round(pt_delta, 1),
                "pt_rank": post_pt_rank if post_pt_rank != 999 else None,
                "pt_rank_change": pre_pt_rank - post_pt_rank if pre_pt_rank != 999 and post_pt_rank != 999 else 0,
            }
        )
    return {
        "action_id": action_id,
        "title": "Game recorded",
        "players": rows,
    }


def normalize_quarter_payload(data):
    year = str(data.get("year") or "").strip()
    term = str(data.get("term") or "").strip().title()
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError("Year must be a four-digit year, for example 2026.")
    if term not in TERM_OPTIONS:
        raise ValueError("Term must be Fall, Winter, or Spring.")
    return f"{year} {term}", year, term


def parse_quarter_label(quarter):
    match = re.fullmatch(r"\s*(\d{4})\s+(Fall|Winter|Spring)\s*", str(quarter or ""), re.IGNORECASE)
    if not match:
        return None, None
    return int(match.group(1)), match.group(2).title()


def next_quarter_label(current):
    year, term = parse_quarter_label(current)
    if not year or term not in TERM_ORDER:
        now = datetime.now()
        return f"{now.year} Fall"
    if term == "Winter":
        return f"{year} Spring"
    if term == "Spring":
        return f"{year} Fall"
    return f"{year + 1} Winter"


def append_quarter_marker_to_sheet(quarter):
    sheet = get_sheet()
    ws_riichi = sheet.worksheet("Games Riichi")
    row_number = len(ws_riichi.get_all_values()) + 1
    ws_riichi.update_cell(row_number, 18, quarter)
    clear_sheet_cache()
    return row_number


def change_current_quarter(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can change quarter.")
    action = str(data.get("action") or "next").strip()
    sheet_row = None
    sheet_error = ""
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        previous_quarter = mahjong_store.latest_quarter(connection)
        if action == "undo":
            quarter = mahjong_store.get_config(connection, "previous_current_quarter", "")
            if not quarter:
                raise ValueError("No previous quarter is available to restore.")
        elif data.get("year") or data.get("term"):
            quarter, year, term = normalize_quarter_payload(data)
        else:
            quarter = next_quarter_label(previous_quarter)
        if quarter == previous_quarter:
            raise ValueError("Quarter is already set to that value.")
        mahjong_store.set_config(connection, "previous_current_quarter", previous_quarter or "")
        mahjong_store.set_current_quarter(connection, quarter)

    if action != "undo":
        try:
            sheet_row = append_quarter_marker_to_sheet(quarter)
        except Exception as error:
            sheet_error = str(error)
            print(f"Web dashboard: Google Sheet quarter marker failed: {sheet_error}")

    record_action(
        user_id=0,
        user_name=username,
        action_type="undo_quarter" if action == "undo" else "change_quarter",
        summary=f"Changed current quarter from {previous_quarter or 'None'} to {quarter}",
        payload={"quarter": quarter, "previous_quarter": previous_quarter, "games_riichi_row": sheet_row, "sheet_error": sheet_error},
    )
    return {
        "ok": True,
        "quarter": quarter,
        "message": f"Current quarter changed to {quarter}.",
        "warning": PUBLIC_SYNC_WARNING if sheet_error else "",
    }


def values_match(current, expected):
    expected_strings = [str(value) for value in expected]
    return current[: len(expected_strings)] == expected_strings


def resolve_logged_row(worksheet, row_number, expected, sheet_name):
    row_number = int(row_number) if row_number else 0
    if row_number >= 2 and values_match(worksheet.row_values(row_number), expected):
        return row_number
    for index, row in enumerate(worksheet.get_all_values(), start=1):
        if index >= 2 and values_match(row, expected):
            return index
    raise ValueError(f"{sheet_name} row no longer matches the logged action.")


class NFCScoreRevertBlocked(ValueError):
    code = "nfc_score_revert_blocked"


def revert_web_record(data, username):
    game_id = safe_int(data.get("game_id")) if data.get("game_id") not in (None, "") else 0
    if game_id:
        if not is_admin(username):
            raise PermissionError("Only admins can revert game rows.")
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            # An NFC-linked game also lives in the score ledger, reservation
            # accounting, and external history. This legacy SQL-only revert
            # cannot reverse those projections together.
            connection.execute("BEGIN IMMEDIATE")
            game = connection.execute(
                "SELECT id, sheet_row, played_at, nfc_match_id FROM games WHERE id = ?",
                (game_id,),
            ).fetchone()
            if not game:
                raise ValueError("Could not find that SQL game record.")
            if game["nfc_match_id"]:
                raise NFCScoreRevertBlocked("NFC scores cannot be reverted here. Contact an administrator for coordinated score correction.")
            player_rows = connection.execute(
                """
                SELECT p.name, gp.final_score
                FROM game_players gp
                JOIN players p ON p.id = gp.player_id
                WHERE gp.game_id = ?
                ORDER BY gp.rank_order ASC
                """,
                (game_id,),
            ).fetchall()
            players = [row["name"] for row in player_rows]
            scores = [row["final_score"] for row in player_rows]
            sheet_row = game["sheet_row"]
            played_at = game["played_at"]
            pre_status = get_players_status(players)
            mahjong_store.revert_game(connection, game_id, recompute_following=True)

        sheet_error = ""
        try:
            sh = get_sheet()
            ws_riichi = sh.worksheet("Games Riichi")
            ws_pt = sh.worksheet("Games/pt")
            riichi_row = resolve_logged_row(ws_riichi, sheet_row, players + scores, "Games Riichi")
            ws_riichi.delete_rows(riichi_row)
            pt_row = resolve_logged_row(ws_pt, sheet_row, [played_at], "Games/pt")
            ws_pt.delete_rows(pt_row)
            clear_sheet_cache()
        except Exception as error:
            sheet_error = str(error)
            print(f"Web dashboard: Google Sheet row revert failed: {sheet_error}")

        post_status = get_players_status(players)
        result_rows = []
        for name in players:
            pre = pre_status.get(name, {})
            post = post_status.get(name, {})
            result_rows.append(
                {
                    "name": name,
                    "mmr": round(safe_float(post.get("mmr", 1500)) or 1500, 2),
                    "mmr_delta": round((safe_float(post.get("mmr", 1500)) or 1500) - (safe_float(pre.get("mmr", 1500)) or 1500), 4),
                    "pt": round(safe_float(post.get("pt", 0)) or 0, 1),
                    "pt_delta": round((safe_float(post.get("pt", 0)) or 0) - (safe_float(pre.get("pt", 0)) or 0), 1),
                }
            )
        record_action(
            user_id=0,
            user_name=username,
            action_type="revert_game_row",
            summary=f"Reverted SQL game #{game_id}",
            payload={"sql_game_id": game_id, "players": players, "scores": scores, "sheet_row": sheet_row, "sheet_error": sheet_error},
        )
        return {
            "ok": True,
            "message": "Record reverted and later SQL games recalculated.",
            "warning": PUBLIC_SYNC_WARNING if sheet_error else "",
            "result": {"title": "Record reverted", "players": result_rows},
        }

    action_id = (data.get("action_id") or "").strip()
    if not action_id:
        raise ValueError("Action id is required.")
    action = get_action(action_id)
    if not action:
        raise ValueError("Could not find that recorded action.")
    if action.get("reverted_at"):
        raise ValueError("That action was already reverted.")
    if action.get("action_type") != "record_game":
        raise ValueError("Only game records can be reverted here.")
    if action.get("user_name") != username and not is_admin(username):
        raise PermissionError("Only admins can revert other people's records.")

    payload = action.get("payload") or {}
    players = (payload.get("games_riichi_values") or [])[:4]
    pre_status = get_players_status(players)

    sql_game_id = payload.get("sql_game_id")
    if sql_game_id:
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            connection.execute("BEGIN IMMEDIATE")
            linked = connection.execute("SELECT nfc_match_id FROM games WHERE id=?",
                                        (int(sql_game_id),)).fetchone()
            if linked and linked["nfc_match_id"]:
                raise NFCScoreRevertBlocked("NFC scores cannot be reverted here. Contact an administrator for coordinated score correction.")
            mahjong_store.revert_game(connection, int(sql_game_id))

    sheet_error = ""
    try:
        sh = get_sheet()
        ws_riichi = sh.worksheet("Games Riichi")
        ws_pt = sh.worksheet("Games/pt")
        riichi_row = resolve_logged_row(ws_riichi, payload.get("games_riichi_row"), payload.get("games_riichi_values") or [], "Games Riichi")
        pt_row = resolve_logged_row(ws_pt, payload.get("games_pt_row"), payload.get("games_pt_values") or [], "Games/pt")
        ws_riichi.delete_rows(riichi_row)
        ws_pt.delete_rows(pt_row)
        clear_sheet_cache()
    except Exception as error:
        sheet_error = str(error)
        print(f"Web dashboard: Google Sheet revert failed: {sheet_error}")

    mark_reverted(action_id, 0)
    post_status = get_players_status(players)
    result_rows = []
    for name in players:
        pre = pre_status.get(name, {})
        post = post_status.get(name, {})
        result_rows.append(
            {
                "name": name,
                "mmr": round(safe_float(post.get("mmr", 1500)) or 1500, 2),
                "mmr_delta": round((safe_float(post.get("mmr", 1500)) or 1500) - (safe_float(pre.get("mmr", 1500)) or 1500), 4),
                "pt": round(safe_float(post.get("pt", 0)) or 0, 1),
                "pt_delta": round((safe_float(post.get("pt", 0)) or 0) - (safe_float(pre.get("pt", 0)) or 0), 1),
            }
        )
    return {
        "ok": True,
        "message": "Record reverted.",
        "warning": PUBLIC_SYNC_WARNING if sheet_error else "",
        "result": {"title": "Record reverted", "players": result_rows},
    }


@account_mutation
def update_user_role(data, username):
    if not is_super_admin(username):
        raise PermissionError("Only super admins can change user roles.")
    target_name = (data.get("username") or "").strip()
    role = (data.get("role") or "").strip()
    if role not in {"user", "admin", "super_admin"}:
        raise ValueError("Role must be user, admin, or super_admin.")

    player_lookup = {normalize_name(name): name for name in sheet_player_names()}
    canonical_name = player_lookup.get(normalize_name(target_name))
    if not canonical_name:
        raise ValueError("Target user must be an existing player name.")

    data_file = users_data()
    try:
        target_key, _ = resolve_registered_account(data_file, canonical_name)
    except ValueError:
        target_key = None
    if target_key not in data_file["users"]:
        raise ValueError("Target player must register an account before a role can be assigned.")

    old_role = data_file["users"][target_key].get("role", "user")
    data_file["users"][target_key]["role"] = role
    write_json(USERS_FILE, data_file)
    record_action(
        user_id=0,
        user_name=username,
        action_type="update_role",
        summary=f"Set {canonical_name} role to {role}",
        payload={"target": canonical_name, "role": role, "old_role": old_role},
    )
    return {"ok": True, "message": f"{canonical_name} is now {role}.", "target": canonical_name, "role": role}


def discord_score_state(username):
    if not is_admin(username):
        raise PermissionError("Only administrators can manage Discord scoring.")
    with closing(mahjong_store.connect(MAHJONG_DB_FILE)) as connection:
        return {"ok": True, "paused": mahjong_store.discord_score_paused(connection)}


def update_discord_score_state(data, username):
    if not is_admin(username):
        raise PermissionError("Only administrators can manage Discord scoring.")
    paused = data.get("paused")
    if type(paused) is not bool:
        raise ValueError("paused must be a boolean")
    with closing(mahjong_store.connect(MAHJONG_DB_FILE)) as connection:
        mahjong_store.set_discord_score_paused(connection, paused)
    return {"ok": True, "paused": paused}


def resolve_registered_account(data_file, target_name):
    target_key = normalize_name(target_name)
    if not target_key:
        raise ValueError("Please select a registered user.")
    users = data_file.get("users", {})
    # Exact old keys keep legacy logins working during collision remediation.
    legacy_key = " ".join(str(target_name).casefold().split())
    if legacy_key in users:
        return legacy_key, users[legacy_key].get("name", target_name)
    matches = [(key, user.get("name", key)) for key, user in users.items()
               if normalize_name(user.get("name", key)) == target_key]
    if len(matches) == 1:
        return matches[0]
    raise ValueError("Target account is not registered or needs administrator review.")


class PasswordResetError(ValueError):
    def __init__(self, message, code="invalid_reset_code"):
        super().__init__(message)
        self.code = code


def recovery_account_enabled(account):
    # History sync creates placeholder accounts without ownership proof. Only
    # an approved existing-ID claim clears this marker; a reset code must not.
    return not (account.get("auto_registered") is True or account.get("disabled")
                or account.get("is_active") is False
                or account.get("status") in {"disabled", "banned", "deleted", "pending_claim"})


def revoke_account_sessions(account, display_name):
    account_id = str(account.get("account_id") or "")
    for token, session_name in list(_sessions.items()):
        if ((account_id and _session_account_ids.get(token) == account_id)
                or normalize_name(session_name) == normalize_name(display_name)):
            _sessions.pop(token, None)
            _session_account_ids.pop(token, None)
    if account_id:
        registered_names.revoke_sessions(USERS_FILE, account_id)


@account_mutation
def reset_user_password(data, username):
    """Issue a code without changing the user's existing password or sessions."""
    if not is_admin(username):
        raise PermissionError("Only admins can issue password reset codes.")
    if any(key in data for key in ("password", "new_password", "confirm_password")):
        raise PasswordResetError("Administrators can only generate a reset code. Refresh this page.", "admin_password_reset_disabled")
    target_name = data.get("username")
    if not isinstance(target_name, str):
        raise ValueError("Please select a registered user.")
    registered_names.ensure_directory(USERS_FILE)
    data_file = users_data()
    target_key, display_name = resolve_registered_account(data_file, target_name)
    account = data_file["users"][target_key]
    if not recovery_account_enabled(account):
        raise ValueError("This account is unavailable.")
    if role_for_user(display_name) != "user" and not is_super_admin(username):
        raise PermissionError("Only super admins can issue reset codes for administrator accounts.")
    if data.get("user_id") is not None and str(data["user_id"]) != str(account.get("account_id")):
        raise PasswordResetError("This player's name changed. Select the player again.", "stale_reset_account")
    raw = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(12))
    issued_at = int(time.time())
    account["password_reset"] = {
        "digest": hashlib.sha256(raw.encode("ascii")).hexdigest(),
        "issued_at": issued_at, "expires_at": issued_at + 30 * 60,
        "issued_by": stable_account_id(username), "failed_attempts": 0,
    }
    write_json(USERS_FILE, data_file)
    record_action(user_id=0, user_name=username, action_type="issue_password_reset_code",
                  summary=f"Issued password reset code for {display_name}",
                  payload={"target": display_name, "expires_at": issued_at + 30 * 60})
    return {"ok": True, "message": "Reset code generated. The user must choose their own new password.",
            "target": display_name, "reset_code": "-".join(raw[i:i+4] for i in range(0, 12, 4)),
            "expires_at": issued_at + 30 * 60, "expires_in": 1800, "reset_url": "/login#reset-password"}


def _admin_account(account):
    role = account.get("role") or default_role_for_name(account.get("name", ""))
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER["admin"]


def prepare_admin_password_setup():
    """Remove legacy admin passwords once a bound self-service route is available."""
    changed = 0
    with registered_names.account_lock(USERS_FILE):
        directory = users_data()
        for account in directory.get("users", {}).values():
            display_name = str(account.get("name", ""))
            if (not _admin_account(account) or normalize_name(display_name) == "fuyun"
                    or account.get("admin_password_setup_required_v1")):
                continue
            discord_id = str(account.get("discord_id") or "")
            if not re.fullmatch(r"\d{15,22}", discord_id):
                continue
            account.pop("password_hash", None)
            account.pop("salt", None)
            account.pop("password_reset", None)
            account["admin_password_setup_required_v1"] = True
            changed += 1
        if changed:
            write_json(USERS_FILE, directory)
    return changed


def start_admin_password_setup(data):
    username = data.get("username")
    if not isinstance(username, str) or not username.strip() or len(username) > 128:
        raise ValueError("Enter your administrator username first.")
    directory = users_data()
    try:
        key, _ = resolve_registered_account(directory, username)
    except ValueError:
        raise ValueError("This administrator account cannot start password setup. Check the name or use password recovery.") from None
    account = directory["users"][key]
    if (not _admin_account(account) or account.get("password_hash")
            or account.get("disabled") or account.get("is_active") is False
            or account.get("status") in {"pending_claim", "disabled", "deleted", "banned"}):
        raise ValueError("This administrator account cannot start password setup. Check the name or use password recovery.")
    return {"ok": True, "url": account_discord.start_admin_password_setup(
        account.get("account_id"), account.get("discord_id"))}


def set_admin_password_from_verified_setup(data, grant_token):
    new_password = data.get("new_password")
    if not isinstance(new_password, str) or not 6 <= len(new_password) <= 1024:
        raise PasswordResetError("Password must contain 6–1024 characters.", "invalid_reset_password")
    if new_password != data.get("confirm_password"):
        raise PasswordResetError("Please enter the new password twice.", "reset_password_mismatch")
    grant = account_discord.take_admin_password_setup_grant(grant_token)
    if not grant:
        raise PermissionError("Administrator verification expired. Start password setup again.")
    with registered_names.account_lock(USERS_FILE):
        directory = users_data()
        account = next((item for item in directory["users"].values()
                        if str(item.get("account_id")) == grant["account_id"]), None)
        if (not account or not _admin_account(account) or account.get("password_hash")
                or str(account.get("discord_id") or "") != grant["discord_id"]
                or account.get("disabled") or account.get("is_active") is False
                or account.get("status") in {"pending_claim", "disabled", "deleted", "banned"}):
            raise PermissionError("This administrator account changed. Start password setup again.")
        salt, hashed = password_hash(new_password)
        account.update(salt=salt, password_hash=hashed, password_changed_at=int(time.time()))
        account.pop("password_reset", None)
        write_json(USERS_FILE, directory)
        revoke_account_sessions(account, account["name"])
        token, display_name = create_account_session(account)
    record_action(user_id=grant["account_id"], user_name=display_name,
                  action_type="admin_password_setup",
                  summary=f"Administrator set a password after Discord verification: {display_name}",
                  payload={"target": display_name})
    return token, display_name


@account_mutation
def redeem_password_reset(data):
    """Consume the code and publish the new hash in the same locked account write."""
    new_password = data.get("new_password")
    if not isinstance(new_password, str) or not 6 <= len(new_password) <= 1024:
        raise PasswordResetError("Password must contain 6–1024 characters.", "invalid_reset_password")
    if new_password != data.get("confirm_password"):
        raise PasswordResetError("Please enter the new password twice.", "reset_password_mismatch")
    invalid = PasswordResetError("The reset code is invalid or expired. Ask an administrator for a new code.")
    username, code = data.get("username"), data.get("reset_code")
    if not isinstance(username, str) or len(username) > 128 or not isinstance(code, str) or len(code) > 64:
        raise invalid
    directory = users_data()
    try:
        key, display_name = resolve_registered_account(directory, username)
    except ValueError:
        raise invalid from None
    account = directory["users"][key]
    pending = account.get("password_reset")
    if not recovery_account_enabled(account) or not isinstance(pending, dict):
        raise invalid
    if time.time() >= pending.get("expires_at", 0) or pending.get("failed_attempts", 0) >= 5:
        account.pop("password_reset", None)
        write_json(USERS_FILE, directory)
        raise invalid
    normalized = re.sub(r"[\s-]", "", code).upper()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(digest, pending.get("digest", "")):
        pending["failed_attempts"] = pending.get("failed_attempts", 0) + 1
        if pending["failed_attempts"] >= 5:
            account.pop("password_reset", None)
        write_json(USERS_FILE, directory)
        raise invalid
    salt, hashed = password_hash(new_password)
    account.update(salt=salt, password_hash=hashed, password_changed_at=int(time.time()))
    account.pop("password_reset", None)
    write_json(USERS_FILE, directory)
    revoke_account_sessions(account, display_name)
    record_action(user_id=0, user_name=display_name, action_type="redeem_password_reset_code",
                  summary=f"User reset their own password: {display_name}", payload={"target": display_name})
    return {"ok": True, "message": "Password updated. Log in with your new password."}


@account_mutation
def delete_user_account(data, username):
    if not is_super_admin(username):
        raise PermissionError("Only super admins can delete accounts.")
    target_name = (data.get("username") or "").strip()
    data_file = users_data()
    target_key, display_name = resolve_registered_account(data_file, target_name)
    if normalize_name(display_name) == normalize_name(username):
        raise ValueError("You cannot delete your own account from here.")

    deleted_account = dict(data_file["users"][target_key])
    revoke_account_sessions(deleted_account, display_name)
    data_file["users"].pop(target_key, None)
    write_json(USERS_FILE, data_file)
    record_action(
        user_id=0,
        user_name=username,
        action_type="delete_account",
        summary=f"Deleted account for {display_name}",
        payload={"target": display_name},
    )
    return {"ok": True, "message": f"{display_name}'s account has been deleted.", "target": display_name}


@account_mutation
def admin_registered_name(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can change registered names.")
    if data.get("confirm") is not True:
        raise ValueError("Please confirm the registered-name change.")
    registered_names.ensure_directory(USERS_FILE)
    data_file = users_data()
    target_id = str(data.get("user_id") or "")
    found = [(key, account) for key, account in data_file["users"].items()
             if str(account.get("account_id")) == target_id]
    if len(found) != 1:
        raise ValueError("Please select an existing registered user.")
    old_key, account = found[0]
    old_name = account.get("name", old_key)
    if data.get("expected_name") != old_name:
        raise registered_names.RegisteredNameError("The registered name has changed. Refresh and confirm again.", "stale_name")
    new_name = registered_names.display_name(data.get("new_name"))
    new_key = normalize_name(new_name)
    reason = str(data.get("reason") or "").strip()
    if len(reason) > 500:
        raise ValueError("The reason must be 500 characters or fewer.")
    if any(other.get("account_id") != target_id and normalize_name(other.get("name", key)) == new_key
           for key, other in data_file["users"].items()):
        raise registered_names.RegisteredNameError("This registered name is already in use.", "registered_name_taken")
    if new_key in data_file["users"] and data_file["users"][new_key].get("account_id") != target_id:
        raise registered_names.RegisteredNameError("This registered name is already in use.", "registered_name_taken")
    admin_id = stable_account_id(username)
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        source = connection.execute("SELECT * FROM players WHERE name_key=?", (mahjong_store.normalize_name(old_name),)).fetchone()
        existing = next((row for row in connection.execute("SELECT id,name FROM players")
                         if normalize_name(row["name"]) == new_key and (not source or row["id"] != source["id"])), None)
        if existing:
            raise registered_names.RegisteredNameError("This registered name is already used by an existing player.", "registered_name_taken")
        club_player_id = source["id"] if source else None
    # Associate legacy live records before publishing the new name; callers hold
    # account_lock throughout, so the old spelling cannot be reused in between.
    with closing(live_db()):
        pass
    registered_names.rename_account(USERS_FILE, account_id=target_id, old_name=old_name, new_name=new_name,
        club_database=MAHJONG_DB_FILE, club_player_id=club_player_id,
        old_role=account.get("role") or default_role_for_name(old_name),
        admin_id=admin_id, admin_name=username, reason=reason)
    for token, session_name in list(_sessions.items()):
        if session_name == old_name:
            _sessions[token] = new_name
    clear_sheet_cache()
    result = {"old_name": old_name, "new_name": new_name, "reason": reason}
    record_action(user_id=admin_id, user_name=username, action_type="rename_registered_name",
                  summary=f"Changed registered name from {old_name} to {new_name}", payload=result)
    return {"ok": True, "message": f"Registered name changed to {new_name}.",
            "user": {"id": target_id, "name": new_name}, **result}


@account_mutation
def admin_rename_player(data, username):
    """Compatibility wrapper: old callers retain the route and use confirmation."""
    if not is_admin(username):
        raise PermissionError("Only admins can rename players.")
    old_name = (data.get("old_name") or "").strip()
    registered_names.ensure_directory(USERS_FILE)
    directory = users_data()
    try:
        key, canonical_name = resolve_registered_account(directory, old_name)
    except ValueError:
        key = None
    if key:
        return admin_registered_name({**data, "user_id": directory["users"][key]["account_id"]}, username)
    if data.get("confirm") is not True or data.get("expected_name") != old_name:
        raise ValueError("Please confirm the player-name change.")
    new_name = registered_names.display_name(data.get("new_name"))
    if any(normalize_name(account.get("name", key)) == normalize_name(new_name)
           for key, account in directory["users"].items()):
        raise registered_names.RegisteredNameError("This registered name is already in use.", "registered_name_taken")
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        result = mahjong_store.rename_player(connection, old_name, new_name)
    record_action(user_id=stable_account_id(username), user_name=username, action_type="rename_player",
                  summary=f"Renamed {result['old_name']} to {result['new_name']}", payload=result)
    clear_sheet_cache()
    return {"ok": True, "message": f"Renamed {result['old_name']} to {result['new_name']}.", **result}


def active_merge_references(account_id):
    """Find mutable scoring state that would be orphaned by deleting an account."""
    account_id = str(account_id or "")
    if not account_id:
        return []
    found = []
    live_path = Path(LIVE_DB_FILE)
    if live_path.exists():
        try:
            with closing(sqlite3.connect(live_path)) as db:
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if "live_games" in tables:
                    columns = {row[1] for row in db.execute("PRAGMA table_info(live_games)")}
                    player_columns = [f"player{i}_user_id" for i in range(1, 5)
                                      if f"player{i}_user_id" in columns]
                    if player_columns and db.execute(
                        "SELECT 1 FROM live_games WHERE status='active' AND ("
                        + " OR ".join(column + "=?" for column in player_columns)
                        + ") LIMIT 1", (account_id,) * len(player_columns)
                    ).fetchone():
                        found.append("an active live game")
        except sqlite3.Error:
            _logger.exception("Could not verify live-game references before player merge")
            found.append("unverified live-game data")

    score_path = Path(os.getenv("NFC_DATABASE_PATH", "data/nfc_matches.sqlite3"))
    if score_path.exists():
        try:
            with closing(sqlite3.connect(score_path)) as db:
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                checks = []
                if "active_table_members" in tables:
                    checks.append(("an active table seat",
                                   "SELECT 1 FROM active_table_members WHERE user_id=? LIMIT 1"))
                if "table_reservations" in tables:
                    checks.append(("an active table reservation",
                                   "SELECT 1 FROM table_reservations WHERE status='active' AND user_id=? LIMIT 1"))
                if {"table_reservations", "table_reservation_participants"} <= tables:
                    checks.append(("an active reservation roster",
                                   """SELECT 1 FROM table_reservation_participants p
                                      JOIN table_reservations r ON r.id=p.reservation_id
                                      WHERE r.status='active' AND p.user_id=? LIMIT 1"""))
                if "seat_swap_claims" in tables:
                    checks.append(("a pending seat swap",
                                   "SELECT 1 FROM seat_swap_claims WHERE user_id=? LIMIT 1"))
                if {"manual_score_players", "manual_score_drafts"} <= tables:
                    checks.append(("a score awaiting confirmation",
                                   """SELECT 1 FROM manual_score_players p
                                      JOIN manual_score_drafts d ON d.id=p.draft_id
                                      WHERE d.status='review' AND p.user_id=? LIMIT 1"""))
                if {"tournament_check_ins", "tournament_table_sessions"} <= tables:
                    checks.append(("an active tournament check-in",
                                   """SELECT 1 FROM tournament_check_ins c
                                      JOIN tournament_table_sessions s ON s.id=c.match_id
                                      WHERE s.status NOT IN ('COMPLETED','LOCKED')
                                        AND c.account_id=? LIMIT 1"""))
                for label, query in checks:
                    if db.execute(query, (account_id,)).fetchone():
                        found.append(label)
        except sqlite3.Error:
            _logger.exception("Could not verify score-service references before player merge")
            found.append("unverified active score data")
    return list(dict.fromkeys(found))


@account_mutation
def admin_merge_players(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can merge players.")
    actor_id = stable_account_id(username)
    source_value = data.get("source_player_id")
    target_value = data.get("target_player_id")
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        if source_value is None or target_value is None:
            # Compatibility for older administrative clients. Resolve names
            # once, then run the same stable-ID path.
            source_name = (data.get("source_name") or "").strip()
            target_name = (data.get("target_name") or "").strip()
            source_row = connection.execute("SELECT * FROM players WHERE name_key=?", (mahjong_store.normalize_name(source_name),)).fetchone()
            target_row = connection.execute("SELECT * FROM players WHERE name_key=?", (mahjong_store.normalize_name(target_name),)).fetchone()
            if not source_row or not target_row:
                raise ValueError("Select both players by ID.")
        else:
            source_id = account_registration.player_id(source_value)
            target_id = account_registration.player_id(target_value)
            source_row = connection.execute("SELECT * FROM players WHERE id=?", (source_id,)).fetchone()
            target_row = connection.execute("SELECT * FROM players WHERE id=?", (target_id,)).fetchone()
            if not source_row or not target_row:
                raise ValueError("One of the selected player IDs no longer exists. Search again.")
        source, target = dict(source_row), dict(target_row)
    account_plan = account_registration.inspect_player_account_merge(
        sys.modules[__name__], source, target)
    source_account = account_plan.get("source_account")
    target_account = account_plan.get("target_account")
    sensitive_accounts = [account for account in (source_account, target_account) if account]
    if any(ROLE_ORDER.get(account.get("role") or default_role_for_name(account.get("name", "")), 0)
           >= ROLE_ORDER["admin"] for account in sensitive_accounts) and not is_super_admin(username):
        raise PermissionError("Only super admins can merge a player linked to an administrator account.")
    if account_plan.get("deletes_source") and source_account:
        source_account_id = str(source_account.get("account_id") or "")
        if source_account_id and source_account_id == actor_id:
            raise ValueError("You cannot remove your own login account through a player merge.")
        source_role = source_account.get("role") or default_role_for_name(source_account.get("name", ""))
        if source_role == "super_admin":
            directory = users_data()
            remaining = [account for account in directory.get("users", {}).values()
                         if str(account.get("account_id") or "") != source_account_id
                         and recovery_account_enabled(account)
                         and (account.get("role") or default_role_for_name(account.get("name", ""))) == "super_admin"]
            if not remaining:
                raise ValueError("The last super admin account cannot be removed through a player merge.")
        active_references = active_merge_references(source_account_id)
        if active_references:
            raise ValueError(
                "Finish or leave this player's active scoring activity before merging: "
                + ", ".join(active_references) + ".")
    operation_id = registered_names.stage_player_merge(
        USERS_FILE, source, target,
        source_account_id=(source_account or {}).get("account_id"),
        target_account_id=(target_account or {}).get("account_id"),
        delete_source_account=account_plan.get("deletes_source", False))
    try:
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            result = mahjong_store.merge_player_ids(connection, source["id"], target["id"])
    except Exception as error:
        registered_names.update_player_merge(USERS_FILE, operation_id, "failed", error)
        raise
    try:
        registered_names.update_player_merge(USERS_FILE, operation_id, "club_merged")
        account_result = account_registration.merge_player_accounts(sys.modules[__name__], source, target)
    except Exception as error:
        registered_names.update_player_merge(USERS_FILE, operation_id, "account_error", error)
        raise
    registered_names.update_player_merge(USERS_FILE, operation_id, "completed")
    result.update(account_result)
    result["operation_id"] = operation_id
    for token, session_name in list(_sessions.items()):
        session_id = _session_account_ids.get(token)
        if (account_result.get("source_sessions_revoked")
                and (session_id == account_result.get("source_account_id")
                     or (not session_id and normalize_name(session_name) == normalize_name(result["source"])))):
            _sessions.pop(token, None)
            _session_account_ids.pop(token, None)
        elif session_id == account_result.get("target_account_id") or normalize_name(session_name) == normalize_name(result["source"]):
            _sessions[token] = result["target"]
    record_action(
        user_id=actor_id,
        user_name=username,
        action_type="merge_players",
        summary=f"Merged player ID {result['source_player_id']} ({result['source']}) into ID {result['target_player_id']} ({result['target']})",
        payload=result,
    )
    clear_sheet_cache()
    if result.get("source_sessions_revoked"):
        account_message = "the old player and login were removed"
    elif result.get("source_account_id"):
        account_message = "the old player was removed and its login was moved to the target ID"
    else:
        account_message = "the old player was removed"
    return {"ok": True, "message": f"Merged ID {result['source_player_id']} ({result['source']}) into ID {result['target_player_id']} ({result['target']}); {account_message}.", **result}


@account_mutation
def recover_confirmed_player_merge_accounts():
    """Finish confirmed legacy player merges and their account publication.

    Old action/static evidence may describe a merge whose source player is still
    physically present. Revalidate destructive preconditions, persist a journal,
    then reuse the normal club/account merge operations. Pending journals remain
    the stronger evidence and make every post-stage crash replayable.
    """
    def positive_id(value):
        try:
            result = int(value)
            return result if result > 0 else None
        except (TypeError, ValueError):
            return None

    def receipt_key(origin, *, action_id="", source_id=None, target_id=None,
                    source="", target=""):
        # The durable key deliberately contains no player names or action data.
        # An action UUID is its strongest stable identity; older name-only
        # actions and static confirmations use a canonical, hashed payload.
        if origin == "action" and action_id:
            identity = {"action_id": str(action_id)}
        else:
            identity = {
                "source_player_id": positive_id(source_id) or "",
                "target_player_id": positive_id(target_id) or "",
                "source_name": normalize_name(source),
                "target_name": normalize_name(target),
            }
        canonical = json.dumps(
            {"version": 1, "origin": origin, "identity": identity},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return "player-merge-evidence-v1:" + hashlib.sha256(canonical).hexdigest()

    pending_intents = registered_names.pending_player_merges(USERS_FILE)
    receipts = registered_names.player_merge_evidence_receipts(USERS_FILE)
    active_receipt_keys = {
        str(intent.get("evidence_key") or "") for intent in pending_intents
        if intent.get("evidence_key")
    }

    evidence = [
        {
            "source_id": intent["source_player_id"],
            "target_id": intent["target_player_id"],
            "source": intent["source_name"],
            "target": intent["target_name"],
            "operation_id": intent["operation_id"],
            "source_account_id": intent.get("source_account_id", ""),
            "target_account_id": intent.get("target_account_id", ""),
            "delete_source_account": bool(intent.get("delete_source_account")),
            "evidence_key": intent.get("evidence_key", ""),
            "evidence_origin": intent.get("evidence_origin", ""),
            "operation_kind": intent.get("operation_kind", "merge"),
            "origin": "journal",
        }
        for intent in pending_intents
    ]

    def legacy_evidence_available(key):
        receipt = receipts.get(key) or {}
        if receipt.get("status") in {"completed", "blocked"}:
            return False
        # A linked pending intent is already first in the evidence list. A
        # receipt without an operation belongs to interrupted account-only
        # cleanup and must be replayed from its legacy source.
        return not (receipt.get("status") == "pending" and key in active_receipt_keys)

    for action in get_recent_actions(100000):
        if action.get("action_type") != "merge_players" or action.get("reverted_at"):
            continue
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        key = receipt_key(
            "action", action_id=action.get("id"),
            source_id=payload.get("source_player_id"),
            target_id=payload.get("target_player_id"),
            source=payload.get("source"), target=payload.get("target"),
        )
        evidence.append({
            "source_id": payload.get("source_player_id"), "target_id": payload.get("target_player_id"),
            "source": payload.get("source"), "target": payload.get("target"),
            "origin": "action", "evidence_origin": "action", "evidence_key": key,
            "suppressed": not legacy_evidence_available(key),
        })
    try:
        from apply_confirmed_name_merges import MERGES
        for source, target in MERGES:
            key = receipt_key("static", source=source, target=target)
            evidence.append({
                "source": source, "target": target, "origin": "static",
                "evidence_origin": "static", "evidence_key": key,
                "suppressed": not legacy_evidence_available(key),
            })
    except (ImportError, OSError):
        pass

    # Conflicting historical evidence must never be resolved by list order.
    id_choices = {}
    name_choices = {}
    for item in evidence:
        source_id = positive_id(item.get("source_id"))
        target_id = positive_id(item.get("target_id"))
        if source_id and target_id and source_id != target_id:
            id_choices.setdefault(source_id, set()).add(target_id)
        source_name = normalize_name(item.get("source"))
        target_name = normalize_name(item.get("target"))
        if source_name and target_name and source_name != target_name:
            name_choices.setdefault(source_name, set()).add(target_name)
    id_redirects = {source: next(iter(targets)) for source, targets in id_choices.items()
                    if len(targets) == 1}
    name_redirects = {source: next(iter(targets)) for source, targets in name_choices.items()
                      if len(targets) == 1}
    ambiguous_ids = {source for source, targets in id_choices.items() if len(targets) != 1}
    ambiguous_names = {source for source, targets in name_choices.items() if len(targets) != 1}

    def terminal(value, redirects):
        visited = set()
        while value in redirects:
            if value in visited:
                return None
            visited.add(value)
            value = redirects[value]
        return value

    def current_players():
        with closing(mahjong_store.connect(MAHJONG_DB_FILE)) as db:
            return [dict(row) for row in db.execute("SELECT id,name FROM players")]

    def unique_name_player(players, value):
        key = normalize_name(value)
        matches = [player for player in players if normalize_name(player["name"]) == key]
        return matches[0] if key and len(matches) == 1 else None

    def resolve_target(item, players):
        direct_id = positive_id(item.get("target_id"))
        direct_name = normalize_name(item.get("target"))
        # A journal's exact target wins while it exists. Legacy evidence follows
        # every confirmed redirect to its surviving chain endpoint.
        if item.get("operation_id"):
            if direct_id:
                exact = next((p for p in players if int(p["id"]) == direct_id), None)
                if exact:
                    return exact
            if direct_name:
                exact = unique_name_player(players, direct_name)
                if exact:
                    return exact
        if direct_id:
            resolved_id = terminal(direct_id, id_redirects)
            if resolved_id:
                match = next((p for p in players if int(p["id"]) == resolved_id), None)
                if match:
                    return match
        if direct_name:
            resolved_name = terminal(direct_name, name_redirects)
            if resolved_name:
                return unique_name_player(players, resolved_name)
        return None

    def same_game_conflicts(source_id, target_id):
        with closing(mahjong_store.connect(MAHJONG_DB_FILE)) as db:
            return [int(row["game_id"]) for row in db.execute(
                """SELECT game_id FROM game_players
                   WHERE player_id IN (?,?) GROUP BY game_id
                   HAVING COUNT(DISTINCT player_id)>1 ORDER BY game_id LIMIT 10""",
                (source_id, target_id))]

    def account_preflight(item, source, target):
        plan = account_registration.inspect_player_account_merge(
            sys.modules[__name__], source, target)
        source_account = plan.get("source_account") or {}
        if not item.get("operation_id") and plan.get("deletes_source"):
            source_role = source_account.get("role") or default_role_for_name(
                source_account.get("name", source["name"]))
            if ROLE_ORDER.get(source_role, 0) >= ROLE_ORDER["admin"]:
                _logger.warning("Skipping automatic legacy merge for privileged source account %s",
                                source_account.get("account_id"))
                return None
        if plan.get("deletes_source") and source_account.get("account_id"):
            references = active_merge_references(source_account["account_id"])
            if references:
                if item.get("operation_id"):
                    registered_names.update_player_merge(
                        USERS_FILE, item["operation_id"], "account_error",
                        "Active scoring activity still references the source account.")
                _logger.warning("Skipping confirmed merge while active scoring references %s: %s",
                                source_account.get("account_id"), ", ".join(references))
                return None
        return plan

    def finish_sessions(item, source, target, account_result):
        captured_source_id = str(item.get("source_account_id") or "")
        source_account_id = str(account_result.get("source_account_id") or captured_source_id)
        target_account_id = str(account_result.get("target_account_id")
                                or item.get("target_account_id") or "")
        revoke_source = bool(account_result.get("source_sessions_revoked")
                             or (item.get("delete_source_account") and captured_source_id))
        if revoke_source and source_account_id:
            registered_names.revoke_sessions(USERS_FILE, source_account_id)
        for token, session_name in list(_sessions.items()):
            session_id = str(_session_account_ids.get(token) or "")
            if revoke_source and (session_id == source_account_id
                                  or (not session_id and normalize_name(session_name)
                                      == normalize_name(source["name"]))):
                _sessions.pop(token, None)
                _session_account_ids.pop(token, None)
            elif (target_account_id and session_id == target_account_id) or (
                    not session_id and normalize_name(session_name) == normalize_name(source["name"])):
                _sessions[token] = target["name"]

    def settle_legacy_evidence(item, status, operation_id=""):
        key = str(item.get("evidence_key") or "")
        if key and not item.get("operation_id"):
            registered_names.update_player_merge_evidence_receipt(
                USERS_FILE, key, item.get("evidence_origin") or item.get("origin") or "legacy",
                status, operation_id=operation_id)

    def recover_static_rename(item, player, players):
        """Replay the original static rename-as-target rule by stable player ID."""
        operation_id = item.get("operation_id")
        try:
            if player is None:
                raise ValueError("The rename source no longer exists.")
            target_name = registered_names.display_name(item.get("target"))
            legacy_source = {
                "id": int(player["id"]),
                "name": item.get("source") or player["name"],
            }
            renamed_target = {"id": int(player["id"]), "name": target_name}
            allowed_player_names = {
                normalize_name(legacy_source["name"]), normalize_name(target_name)
            }
            if normalize_name(player["name"]) not in allowed_player_names:
                raise ValueError("The rename source ID now belongs to another player name.")
            if any(int(other["id"]) != int(player["id"])
                   and normalize_name(other["name"]) == normalize_name(target_name)
                   for other in players):
                raise ValueError("The rename target is already used by another player.")

            plan = account_registration.inspect_player_account_merge(
                sys.modules[__name__], legacy_source, renamed_target)
            if plan.get("deletes_source"):
                raise ValueError("The source and target names belong to different website accounts.")
            allowed_accounts = {
                str(account.get("account_id") or "")
                for account in (plan.get("source_account"), plan.get("target_account"))
                if account
            }
            directory = users_data()
            if any(normalize_name(account.get("name", key)) == normalize_name(target_name)
                   and str(account.get("account_id") or "") not in allowed_accounts
                   for key, account in directory.get("users", {}).items()):
                raise ValueError("The rename target is already used by another website account.")
        except ValueError as error:
            if operation_id:
                registered_names.update_player_merge(
                    USERS_FILE, operation_id, "account_error", error)
            else:
                settle_legacy_evidence(item, "blocked")
            _logger.warning("Skipping unsafe confirmed rename-as-target: %s", error)
            return 0
        except Exception as error:
            if operation_id:
                registered_names.update_player_merge(
                    USERS_FILE, operation_id, "account_error", error)
            else:
                settle_legacy_evidence(item, "failed")
            _logger.exception("Could not validate confirmed rename-as-target")
            return 0

        if not operation_id:
            try:
                operation_id = registered_names.stage_player_rename(
                    USERS_FILE, legacy_source, target_name,
                    source_account_id=(plan.get("source_account") or {}).get("account_id"),
                    target_account_id=(plan.get("target_account") or {}).get("account_id"),
                    evidence_key=item.get("evidence_key", ""),
                    evidence_origin=item.get("evidence_origin", "static"))
            except Exception:
                _logger.exception("Could not journal confirmed rename-as-target")
                return 0
            item = {
                **item, "operation_id": operation_id, "operation_kind": "rename",
                "source_id": int(player["id"]), "target_id": int(player["id"]),
                "source_account_id": (plan.get("source_account") or {}).get("account_id", ""),
                "target_account_id": (plan.get("target_account") or {}).get("account_id", ""),
            }

        try:
            with closing(mahjong_store.connect(MAHJONG_DB_FILE)) as db:
                current = db.execute(
                    "SELECT id,name FROM players WHERE id=?", (int(player["id"]),)
                ).fetchone()
                if not current:
                    raise ValueError("The rename source no longer exists.")
                if normalize_name(current["name"]) not in allowed_player_names:
                    raise ValueError("The rename source ID changed unexpectedly.")
                if current["name"] != target_name:
                    mahjong_store.rename_player(db, current["name"], target_name)
        except Exception as error:
            try:
                registered_names.update_player_merge(USERS_FILE, operation_id, "failed", error)
            except Exception:
                _logger.exception("Could not mark failed rename-as-target")
            _logger.exception("Could not finish confirmed rename-as-target in the club database")
            return 0

        # The club rename commits inside rename_player. If only the cross-store
        # marker write fails, leave the intent pending rather than marking the
        # already-committed rename failed; the stable ID makes replay idempotent.
        try:
            registered_names.update_player_merge(USERS_FILE, operation_id, "club_merged")
        except Exception:
            _logger.exception("Could not mark committed rename-as-target for account recovery")
            return 0

        try:
            account_result = account_registration.merge_player_accounts(
                sys.modules[__name__], legacy_source, renamed_target)
            finish_sessions(item, legacy_source, renamed_target, account_result)
            registered_names.update_player_merge(USERS_FILE, operation_id, "completed")
            clear_sheet_cache()
            return 1
        except Exception as error:
            try:
                registered_names.update_player_merge(
                    USERS_FILE, operation_id, "account_error", error)
            except Exception:
                _logger.exception("Could not mark rename-as-target account recovery error")
            _logger.exception("Could not publish confirmed rename-as-target account name")
            return 0

    completed = 0
    for item in evidence:
        if item.get("suppressed"):
            continue
        players = current_players()
        source_id = positive_id(item.get("source_id"))
        source_name = normalize_name(item.get("source"))
        if (not item.get("operation_id")
                and ((source_id and source_id in ambiguous_ids)
                     or (source_name and source_name in ambiguous_names))):
            _logger.warning("Skipping ambiguous legacy player-merge evidence for %s",
                            item.get("source") or source_id)
            settle_legacy_evidence(item, "blocked")
            continue
        source = None
        if source_id:
            source = next((p for p in players if int(p["id"]) == source_id), None)
        elif item.get("source"):
            source_candidates = [
                player for player in players
                if normalize_name(player["name"]) == normalize_name(item["source"])
            ]
            if len(source_candidates) > 1:
                settle_legacy_evidence(item, "blocked")
                continue
            source = source_candidates[0] if source_candidates else None
        target = resolve_target(item, players)
        direct_target_name = normalize_name(item.get("target"))
        terminal_static_target_missing = (
            direct_target_name
            and direct_target_name not in name_redirects
            and direct_target_name not in ambiguous_names
        )
        if item.get("operation_kind") == "rename" or (
                not item.get("operation_id") and item.get("origin") == "static"
                and source is not None and target is None
                and terminal_static_target_missing):
            completed += recover_static_rename(item, source, players)
            continue
        if target is None:
            if item.get("operation_id"):
                registered_names.update_player_merge(
                    USERS_FILE, item["operation_id"], "failed",
                    "The merge target no longer exists.")
            else:
                settle_legacy_evidence(item, "blocked")
            continue
        if source is not None:
            if int(source["id"]) == int(target["id"]):
                if item.get("operation_id"):
                    registered_names.update_player_merge(
                        USERS_FILE, item["operation_id"], "failed",
                        "Source and target resolve to the same player.")
                else:
                    settle_legacy_evidence(item, "completed")
                continue
            try:
                plan = account_preflight(item, source, target)
            except ValueError as error:
                if item.get("operation_id"):
                    registered_names.update_player_merge(
                        USERS_FILE, item["operation_id"], "failed", error)
                else:
                    settle_legacy_evidence(item, "blocked")
                _logger.exception("Could not safely validate confirmed player merge")
                continue
            except Exception as error:
                if item.get("operation_id"):
                    registered_names.update_player_merge(
                        USERS_FILE, item["operation_id"], "failed", error)
                else:
                    settle_legacy_evidence(item, "failed")
                _logger.exception("Could not validate confirmed player merge")
                continue
            if plan is None:
                settle_legacy_evidence(item, "blocked")
                continue
            conflicts = same_game_conflicts(source["id"], target["id"])
            if conflicts:
                if item.get("operation_id"):
                    registered_names.update_player_merge(
                        USERS_FILE, item["operation_id"], "failed",
                        "Both players occur in the same game(s): "
                        + ", ".join(str(game_id) for game_id in conflicts))
                _logger.warning("Skipping confirmed player merge %s -> %s; shared games %s",
                                source["id"], target["id"], conflicts)
                settle_legacy_evidence(item, "blocked")
                continue
            operation_id = item.get("operation_id")
            if not operation_id:
                try:
                    operation_id = registered_names.stage_player_merge(
                        USERS_FILE, source, target,
                        source_account_id=(plan.get("source_account") or {}).get("account_id"),
                        target_account_id=(plan.get("target_account") or {}).get("account_id"),
                        delete_source_account=plan.get("deletes_source", False),
                        evidence_key=item.get("evidence_key", ""),
                        evidence_origin=item.get("evidence_origin", ""))
                except Exception:
                    _logger.exception("Could not journal confirmed legacy player merge")
                    continue
                item = {
                    **item,
                    "operation_id": operation_id,
                    "source_id": int(source["id"]),
                    "target_id": int(target["id"]),
                    "source": source["name"],
                    "target": target["name"],
                    "source_account_id": (plan.get("source_account") or {}).get("account_id", ""),
                    "target_account_id": (plan.get("target_account") or {}).get("account_id", ""),
                    "delete_source_account": bool(plan.get("deletes_source")),
                }
            try:
                with closing(mahjong_store.connect(MAHJONG_DB_FILE)) as db:
                    mahjong_store.merge_player_ids(db, source["id"], target["id"])
            except Exception as error:
                try:
                    registered_names.update_player_merge(
                        USERS_FILE, operation_id, "failed", error)
                except Exception:
                    _logger.exception("Could not mark failed confirmed player merge")
                _logger.exception("Could not physically finish confirmed player merge")
                continue
            try:
                registered_names.update_player_merge(USERS_FILE, operation_id, "club_merged")
                account_result = account_registration.merge_player_accounts(
                    sys.modules[__name__], source, target)
                finish_sessions(item, source, target, account_result)
                registered_names.update_player_merge(USERS_FILE, operation_id, "completed")
                clear_sheet_cache()
                completed += 1
            except Exception as error:
                try:
                    registered_names.update_player_merge(
                        USERS_FILE, operation_id, "account_error", error)
                except Exception:
                    _logger.exception("Could not mark account recovery error")
                _logger.exception("Could not publish confirmed player-merge account cleanup")
            continue

        directory = users_data()
        accounts = list(directory.get("users", {}).items())
        exact_source_matches = [
            (key, account) for key, account in accounts
            if source_id is not None and str(account.get("club_player_id")) == str(source_id)
        ]
        name_source_matches = [
            (key, account) for key, account in accounts
            if item.get("source")
            and normalize_name(account.get("name", key)) == normalize_name(item["source"])
        ]
        source_matches = exact_source_matches or name_source_matches
        # A staged merge is sufficient recovery evidence even when no source
        # login ever existed or account publication already completed. The
        # directory merge is idempotent and also finishes pending-claim cleanup.
        if not item.get("operation_id"):
            if not source_matches:
                # Confirming the old source is already absent consumes this
                # name-only evidence, so a future player may safely reuse it.
                settle_legacy_evidence(item, "completed")
                continue
            if len(source_matches) != 1:
                settle_legacy_evidence(item, "blocked")
                continue

        recovery_source_id = source_id
        if not recovery_source_id and source_matches:
            linked_id = positive_id(source_matches[0][1].get("club_player_id"))
            if linked_id:
                if any(int(player["id"]) == linked_id for player in players):
                    # This same-name account belongs to a current, different
                    # identity and is never legacy cleanup evidence.
                    settle_legacy_evidence(item, "blocked")
                    continue
                recovery_source_id = linked_id
        source = {"id": recovery_source_id or -1,
                  "name": item.get("source") or (source_matches[0][1].get("name", source_matches[0][0])
                                                    if source_matches else "club-" + str(source_id or "unknown"))}
        try:
            recovery_plan = account_preflight(item, source, target)
            if recovery_plan is None:
                settle_legacy_evidence(item, "blocked")
                continue
            if not item.get("operation_id") and not recovery_plan.get("source_account"):
                # A same-name account linked to another identity must not be
                # rewritten merely because an old player row is gone.
                settle_legacy_evidence(item, "blocked")
                continue
            if not item.get("operation_id"):
                settle_legacy_evidence(item, "pending")
            source_account = recovery_plan.get("source_account") or {}
            if recovery_plan.get("deletes_source") and source_account.get("account_id"):
                # Revoke before the directory write. If publication then fails,
                # the intact source account can be retried without leaving a
                # durable cookie for an account that no longer exists.
                registered_names.revoke_sessions(USERS_FILE, source_account["account_id"])
            account_result = account_registration.merge_player_accounts(
                sys.modules[__name__], source, target)
            finish_sessions(item, source, target, account_result)
            if item.get("operation_id"):
                registered_names.update_player_merge(
                    USERS_FILE, item["operation_id"], "completed")
            else:
                settle_legacy_evidence(item, "completed")
            completed += 1
        except ValueError as error:
            if item.get("operation_id"):
                try:
                    registered_names.update_player_merge(
                        USERS_FILE, item["operation_id"], "account_error", error)
                except Exception:
                    _logger.exception("Could not mark account recovery error")
            else:
                settle_legacy_evidence(item, "blocked")
            _logger.exception("Could not safely recover confirmed player-merge account cleanup")
        except Exception as error:
            if item.get("operation_id"):
                try:
                    registered_names.update_player_merge(
                        USERS_FILE, item["operation_id"], "account_error", error)
                except Exception:
                    _logger.exception("Could not mark account recovery error")
            else:
                settle_legacy_evidence(item, "failed")
            _logger.exception("Could not recover confirmed player-merge account cleanup")
    return completed


@account_mutation
def admin_player_icon(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can set player icons.")
    target_name = (data.get("username") or "").strip()
    label = (data.get("icon_label") or "").strip()
    image = (data.get("icon_image") or "").strip()
    if not target_name:
        raise ValueError("Please enter a player name.")
    if image and not (image.startswith("data:image/jpeg;base64,") or image.startswith("data:image/png;base64,")):
        raise ValueError("Icon image must be JPG or PNG.")
    if len(image) > 1_450_000:
        raise ValueError("Icon image is too large. Please use an image under 1MB.")
    if len(label) > 12:
        raise ValueError("Icon label must be 12 characters or fewer.")
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        player = mahjong_store.upsert_player(connection, target_name)
        canonical_name = player["name"]
    data_file = users_data()
    key = normalize_name(canonical_name)
    if label or image:
        data_file["player_icons"][key] = {"label": label, "image": image}
        message = f"Icon updated for {canonical_name}."
    else:
        data_file["player_icons"].pop(key, None)
        message = f"Icon removed for {canonical_name}."
    write_json(USERS_FILE, data_file)
    record_action(
        user_id=0,
        user_name=username,
        action_type="set_player_icon",
        summary=message,
        payload={"target": canonical_name, "label": label, "has_image": bool(image)},
    )
    return {"ok": True, "message": message, "target": canonical_name}


def admin_create_player(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can create players.")
    player_name = (data.get("player_name") or data.get("name") or "").strip()
    if not player_name:
        raise ValueError("Player name is required.")
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        player = mahjong_store.upsert_player(connection, player_name, initial_mmr=1500)
    record_action(
        user_id=0,
        user_name=username,
        action_type="create_player",
        summary=f"Created player {player['name']}",
        payload={"player_name": player["name"]},
    )
    return {"ok": True, "message": f"Created player {player['name']}. They can now register a web account.", "player": player["name"]}


def add_admin_yakuman(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can add yakuman records.")
    winner = (data.get("winner") or "").strip()
    deal_in = (data.get("deal_in") or "").strip()
    played_at = (data.get("played_at") or "").strip()
    attach_latest = str(data.get("attach_latest_game") or "").lower() in {"1", "true", "on", "yes"}
    raw_other_players = data.get("other_players") or []
    if isinstance(raw_other_players, str):
        raw_other_players = [raw_other_players]
    raw_names = data.get("yakuman_names") or []
    if isinstance(raw_names, str):
        raw_names = [raw_names]
    yakuman_names = [name for name in raw_names if name in YAKUMAN_OPTIONS]
    note = (data.get("note") or "").strip()
    photo_caption = (data.get("photo_caption") or "").strip()
    photo_path = save_yakuman_photo(data.get("photo_data", ""))
    selected_game_id = safe_int(data.get("game_id")) if data.get("game_id") not in (None, "") else 0
    if not winner:
        raise ValueError("Winner is required.")
    if not yakuman_names:
        raise ValueError("Choose at least one yakuman.")
    if not selected_game_id:
        raise ValueError("Admin yakuman entry must be attached to a specific game. Choose a game from Match Management.")

    player_lookup = {normalize_name(name): name for name in sheet_player_names()}
    winner = player_lookup.get(normalize_name(winner), winner)
    deal_in = player_lookup.get(normalize_name(deal_in), deal_in) if deal_in else ""
    other_players = []
    for name in raw_other_players:
        clean = str(name or "").strip()
        if clean:
            other_players.append(player_lookup.get(normalize_name(clean), clean))
    match_players = []
    for name in [winner, deal_in, *other_players]:
        if name and name not in match_players:
            match_players.append(name)
    game_id = selected_game_id or None
    players = match_players or [winner]
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        if game_id:
            selected_game = connection.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
            if not selected_game:
                raise ValueError("Selected game was not found.")
            players = [
                row["name"]
                for row in connection.execute(
                    """
                    SELECT p.name
                    FROM game_players gp
                    JOIN players p ON p.id = gp.player_id
                    WHERE gp.game_id = ?
                    ORDER BY gp.rank_order ASC
                    """,
                    (game_id,),
                )
            ]
            if not played_at:
                played_at = selected_game["played_at"]
        elif played_at:
            matched = mahjong_store.find_game_for_yakuman(connection, played_at, winner, match_players)
            if matched:
                game_id = matched["id"]
                players = matched["players"]
    if not played_at:
        played_at = local_now_string()

    created = []
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        for yakuman_name in yakuman_names:
            record_id = mahjong_store.record_yakuman(
                connection,
                played_at=played_at,
                winner=winner,
                yakuman_name=yakuman_name,
                note=note,
                players=players,
                game_id=game_id,
                source="admin-web",
                source_key=f"admin-web:{played_at}:{winner}:{yakuman_name}:{game_id or 'standalone'}",
                deal_in=deal_in,
                photo_path=photo_path,
                photo_caption=photo_caption,
            )
            created.append(record_id)
    sheet_error = ""
    if game_id:
        try:
            update_sheet_yakuman_for_game(game_id, winner, yakuman_names, deal_in=deal_in)
        except Exception as error:
            sheet_error = str(error)
            print(f"Web dashboard: Google Sheet yakuman update failed: {sheet_error}")
    record_action(
        user_id=0,
        user_name=username,
        action_type="add_yakuman",
        summary=f"Added yakuman for {winner}: {', '.join(yakuman_names)}",
        payload={"winner": winner, "deal_in": deal_in, "other_players": other_players, "played_at": played_at, "yakuman_names": yakuman_names, "created_yakuman_ids": created, "note": note, "photo_path": photo_path, "photo_caption": photo_caption, "game_id": game_id, "sheet_error": sheet_error},
    )
    linked = " Linked to matched game." if game_id else ""
    warning = " " + PUBLIC_SYNC_WARNING if sheet_error else ""
    return {
        "ok": True,
        "message": f"Added {len(created)} yakuman record(s) for {winner}.{linked}{warning}",
        "records": created,
        "game_id": game_id,
        "warning": PUBLIC_SYNC_WARNING if sheet_error else "",
        "recent_yakuman": sql_recent_yakuman(500),
        "yakuman_leaders": sql_yakuman_leaders(),
    }


def update_sheet_yakuman_for_game(game_id, winner, yakuman_names, deal_in=""):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        game = connection.execute("SELECT sheet_row FROM games WHERE id = ?", (game_id,)).fetchone()
    if not game or not game["sheet_row"]:
        return
    row_number = int(game["sheet_row"])
    if row_number < 2:
        return
    sheet = get_sheet()
    ws_riichi = sheet.worksheet("Games Riichi")
    row = ws_riichi.row_values(row_number)
    existing = row[20] if len(row) > 20 else ""
    names = [part.strip() for part in str(existing or "").replace("，", ",").split(",") if part.strip()]
    for yakuman_name in yakuman_names:
        if yakuman_name not in names:
            names.append(yakuman_name)
    existing_deal_in = row[19] if len(row) > 19 else ""
    deal_ins = [part.strip() for part in str(existing_deal_in or "").replace("，", ",").split(",") if part.strip()]
    if deal_in and deal_in not in deal_ins:
        deal_ins.append(deal_in)
    ws_riichi.update(values=[[winner, ", ".join(deal_ins), ", ".join(names)]], range_name=f"S{row_number}:U{row_number}")
    clear_sheet_cache()


def save_yakuman_photo(photo_data):
    photo_data = str(photo_data or "").strip()
    if not photo_data:
        return ""
    match = re.fullmatch(r"data:image/(jpeg|png);base64,(.+)", photo_data, re.DOTALL)
    if not match:
        raise ValueError("Yakuman photo must be a JPG or PNG image.")
    extension = "jpg" if match.group(1) == "jpeg" else "png"
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except Exception as error:
        raise ValueError("Could not decode yakuman photo.") from error
    if len(content) > MAX_YAKUMAN_PHOTO_BYTES:
        raise ValueError("Yakuman photo must be 10MB or smaller.")
    YAKUMAN_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time())}-{secrets.token_hex(10)}.{extension}"
    path = YAKUMAN_UPLOAD_DIR / filename
    path.write_bytes(content)
    return f"/uploads/yakuman/{filename}"


def delete_runtime_upload(public_path):
    public_path = str(public_path or "")
    prefix = "/uploads/yakuman/"
    if not public_path.startswith(prefix):
        return
    filename = Path(public_path[len(prefix):]).name
    target = (YAKUMAN_UPLOAD_DIR / filename).resolve()
    if target.parent == YAKUMAN_UPLOAD_DIR.resolve() and target.exists():
        try:
            target.unlink()
        except OSError:
            pass


def sync_sheet_yakuman_from_sql(game_id):
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        game = connection.execute("SELECT sheet_row, yakuman_winner, yakuman_deal_in, yakuman_text FROM games WHERE id = ?", (game_id,)).fetchone()
    if not game or not game["sheet_row"]:
        return
    row_number = int(game["sheet_row"])
    if row_number < 2:
        return
    sheet = get_sheet()
    ws_riichi = sheet.worksheet("Games Riichi")
    ws_riichi.update(values=[[game["yakuman_winner"] or "", game["yakuman_deal_in"] or "", game["yakuman_text"] or ""]], range_name=f"S{row_number}:U{row_number}")
    clear_sheet_cache()


def delete_admin_yakuman(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can delete yakuman records.")
    yakuman_id = safe_int(data.get("yakuman_id")) if data.get("yakuman_id") not in (None, "") else 0
    delete_matching = str(data.get("delete_matching") or "").lower() in {"1", "true", "yes", "on"}
    if not yakuman_id and not delete_matching:
        raise ValueError("Yakuman id is required.")
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        if delete_matching:
            deleted_rows = mahjong_store.delete_yakuman_matching(
                connection,
                data.get("played_at", ""),
                data.get("winner", ""),
                data.get("yakuman", ""),
            )
            if not deleted_rows:
                raise ValueError("No matching yakuman records were found.")
            deleted = deleted_rows[0]
        else:
            deleted_rows = [mahjong_store.delete_yakuman(connection, yakuman_id)]
            deleted = deleted_rows[0]
    for item in deleted_rows:
        delete_runtime_upload(item.get("photo_path", ""))
    sheet_error = ""
    game_ids = sorted({item.get("game_id") for item in deleted_rows if item.get("game_id")})
    for game_id in game_ids:
        try:
            sync_sheet_yakuman_from_sql(game_id)
        except Exception as error:
            sheet_error = str(error)
            print(f"Web dashboard: Google Sheet yakuman delete sync failed: {sheet_error}")
    record_action(
        user_id=0,
        user_name=username,
        action_type="delete_yakuman",
        summary=f"Deleted {len(deleted_rows)} yakuman record(s): {deleted['winner']} {deleted['yakuman']}",
        payload={"deleted": deleted_rows, "sheet_error": sheet_error},
    )
    warning = " " + PUBLIC_SYNC_WARNING if sheet_error else ""
    try:
        fresh_yakuman = sql_recent_yakuman(500)
        fresh_leaders = sql_yakuman_leaders()
    except Exception:
        fresh_yakuman = []
        fresh_leaders = []
    return {
        "ok": True,
        "message": f"Deleted {len(deleted_rows)} yakuman record(s) for {deleted['winner']}: {deleted['yakuman']}.{warning}",
        "deleted": deleted,
        "deleted_rows": deleted_rows,
        "warning": PUBLIC_SYNC_WARNING if sheet_error else "",
        "recent_yakuman": fresh_yakuman,
        "yakuman_leaders": fresh_leaders,
    }


def hard_delete_yakuman_by_display(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can delete yakuman records.")
    winner = (data.get("winner") or "").strip()
    yakuman_name = (data.get("yakuman") or "").strip()
    played_at = (data.get("played_at") or data.get("date") or "").strip()
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        deleted_rows = mahjong_store.delete_yakuman_matching(connection, played_at, winner, yakuman_name)
    if not deleted_rows:
        raise ValueError("No matching yakuman records were found.")
    for item in deleted_rows:
        delete_runtime_upload(item.get("photo_path", ""))
    record_action(
        user_id=0,
        user_name=username,
        action_type="hard_delete_yakuman",
        summary=f"Hard deleted {len(deleted_rows)} yakuman record(s): {winner} {yakuman_name} {played_at}",
        payload={"deleted": deleted_rows},
    )
    return {
        "ok": True,
        "message": f"Deleted {len(deleted_rows)} matching yakuman record(s).",
        "deleted_rows": deleted_rows,
        "recent_yakuman": sql_recent_yakuman(500),
        "yakuman_leaders": sql_yakuman_leaders(),
    }


def update_admin_yakuman_photo(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can update yakuman photos.")
    yakuman_id = safe_int(data.get("yakuman_id")) if data.get("yakuman_id") not in (None, "") else 0
    if not yakuman_id:
        raise ValueError("Yakuman id is required.")
    photo_caption = (data.get("photo_caption") or "").strip()
    photo_path = save_yakuman_photo(data.get("photo_data", ""))
    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        updated = mahjong_store.update_yakuman_photo(connection, yakuman_id, photo_path=photo_path, photo_caption=photo_caption)
    if photo_path and updated.get("old_photo_path"):
        delete_runtime_upload(updated["old_photo_path"])
    record_action(
        user_id=0,
        user_name=username,
        action_type="update_yakuman_photo",
        summary=f"Updated yakuman photo #{yakuman_id}",
        payload={"yakuman_id": yakuman_id, "old_photo_path": updated.get("old_photo_path", ""), "photo_path": updated.get("photo_path", ""), "photo_caption": photo_caption},
    )
    return {"ok": True, "message": "Yakuman photo updated.", "updated": updated}


def update_admin_yakuman(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can edit yakuman records.")
    yakuman_id = safe_int(data.get("yakuman_id")) if data.get("yakuman_id") not in (None, "") else 0
    if not yakuman_id:
        raise ValueError("Yakuman id is required.")
    winner = (data.get("winner") or "").strip()
    yakuman_name = (data.get("yakuman") or data.get("yakuman_name") or "").strip()
    played_at = (data.get("played_at") or data.get("date") or "").strip()
    deal_in = (data.get("deal_in") or "").strip()
    note = (data.get("note") or "").strip()
    selected_game_id = safe_int(data.get("game_id")) if data.get("game_id") not in (None, "") else None
    if yakuman_name and yakuman_name not in YAKUMAN_OPTIONS:
        raise ValueError("Choose a valid yakuman.")
    player_lookup = {normalize_name(name): name for name in sheet_player_names()}
    if winner:
        winner = player_lookup.get(normalize_name(winner), winner)
    if deal_in:
        deal_in = player_lookup.get(normalize_name(deal_in), deal_in)

    with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
        updated = mahjong_store.update_yakuman(
            connection,
            yakuman_id,
            played_at=played_at,
            winner=winner,
            yakuman_name=yakuman_name,
            deal_in=deal_in,
            note=note,
            game_id=selected_game_id,
        )
    sheet_errors = []
    for game_id in sorted({updated["old"].get("game_id"), updated["new"].get("game_id")}):
        if game_id:
            try:
                sync_sheet_yakuman_from_sql(game_id)
            except Exception as error:
                sheet_errors.append(str(error))
                print(f"Web dashboard: Google Sheet yakuman edit sync failed: {error}")
    record_action(
        user_id=0,
        user_name=username,
        action_type="update_yakuman",
        summary=f"Edited yakuman #{yakuman_id}: {updated['old']['winner']} {updated['old']['yakuman']} -> {updated['new']['winner']} {updated['new']['yakuman']}",
        payload={"old": updated["old"], "new": updated["new"], "sheet_errors": sheet_errors},
    )
    warning = " " + PUBLIC_SYNC_WARNING if sheet_errors else ""
    return {
        "ok": True,
        "message": f"Yakuman #{yakuman_id} updated.{warning}",
        "updated": updated,
        "recent_yakuman": sql_recent_yakuman(500),
        "yakuman_leaders": sql_yakuman_leaders(),
    }


def admin_recent_actions(username, limit=30):
    if not is_admin(username):
        raise PermissionError("Only admins can view recent admin actions.")
    actions = []
    for action in get_recent_actions(limit):
        action_type = action.get("action_type", "")
        can_revert = action_type in {"add_yakuman", "delete_yakuman", "hard_delete_yakuman", "update_yakuman", "update_role"}
        if action.get("reverted_at"):
            can_revert = False
        actions.append(
            {
                "id": action.get("id"),
                "created_at": action.get("created_at"),
                "user_name": action.get("user_name"),
                "action_type": action_type,
                "summary": action.get("summary"),
                "reverted_at": action.get("reverted_at"),
                "can_revert": can_revert,
            }
        )
    return {"ok": True, "actions": actions}


@account_mutation
def revert_admin_action(data, username):
    if not is_admin(username):
        raise PermissionError("Only admins can revert admin actions.")
    action_id = (data.get("action_id") or "").strip()
    if not action_id:
        raise ValueError("Action id is required.")
    action = get_action(action_id)
    if not action:
        raise ValueError("Could not find that admin action.")
    if action.get("reverted_at"):
        raise ValueError("That action was already reverted.")

    action_type = action.get("action_type")
    payload = action.get("payload") or {}
    message = "Admin action reverted."
    sheet_errors = []

    if action_type == "add_yakuman":
        ids = [safe_int(item) for item in payload.get("created_yakuman_ids", []) if safe_int(item)]
        if not ids:
            raise ValueError("This add-yakuman action does not contain record ids, so it cannot be auto-reverted.")
        deleted_rows = []
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            for yakuman_id in ids:
                try:
                    deleted_rows.append(mahjong_store.delete_yakuman(connection, yakuman_id))
                except ValueError:
                    pass
        for item in deleted_rows:
            game_id = item.get("game_id")
            if game_id:
                try:
                    sync_sheet_yakuman_from_sql(game_id)
                except Exception as error:
                    sheet_errors.append(str(error))
        message = f"Reverted add-yakuman action; deleted {len(deleted_rows)} yakuman record(s)."
    elif action_type in {"delete_yakuman", "hard_delete_yakuman"}:
        deleted_rows = payload.get("deleted") or []
        if not deleted_rows:
            raise ValueError("This delete action does not contain deleted rows, so it cannot be auto-restored.")
        restored = []
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            for row in deleted_rows:
                restored.append(mahjong_store.restore_yakuman(connection, row))
        game_ids = sorted({row.get("game_id") for row in deleted_rows if row.get("game_id")})
        for game_id in game_ids:
            try:
                sync_sheet_yakuman_from_sql(game_id)
            except Exception as error:
                sheet_errors.append(str(error))
        message = f"Restored {len(restored)} deleted yakuman record(s)."
    elif action_type == "update_role":
        if not is_super_admin(username):
            raise PermissionError("Only super admins can revert role changes.")
        target = payload.get("target", "")
        old_role = payload.get("old_role", "user")
        if old_role not in {"user", "admin", "super_admin"}:
            old_role = "user"
        data_file = users_data()
        target_key = normalize_name(target)
        if target_key not in data_file["users"]:
            raise ValueError("Target account no longer exists.")
        data_file["users"][target_key]["role"] = old_role
        write_json(USERS_FILE, data_file)
        message = f"Restored {target}'s role to {old_role}."
    elif action_type == "update_yakuman":
        old = payload.get("old") or {}
        if not old.get("id"):
            raise ValueError("This yakuman edit cannot be auto-reverted.")
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            updated = mahjong_store.update_yakuman(
                connection,
                int(old["id"]),
                played_at=old.get("played_at", ""),
                winner=old.get("winner", ""),
                yakuman_name=old.get("yakuman", ""),
                deal_in=old.get("deal_in", ""),
                note=old.get("note", ""),
                game_id=old.get("game_id"),
            )
        for game_id in sorted({updated["old"].get("game_id"), updated["new"].get("game_id")}):
            if game_id:
                try:
                    sync_sheet_yakuman_from_sql(game_id)
                except Exception as error:
                    sheet_errors.append(str(error))
        message = f"Restored yakuman #{old['id']} to the previous values."
    else:
        raise ValueError("This action type cannot be auto-reverted safely.")

    mark_reverted(action_id, 0)
    record_action(
        user_id=0,
        user_name=username,
        action_type="revert_admin_action",
        summary=f"Reverted admin action {action_id}: {action.get('summary', '')}",
        payload={"action_id": action_id, "action_type": action_type, "sheet_errors": sheet_errors},
    )
    warning = " " + PUBLIC_SYNC_WARNING if sheet_errors else ""
    return {
        "ok": True,
        "message": message + warning,
        "recent_yakuman": sql_recent_yakuman(500),
        "yakuman_leaders": sql_yakuman_leaders(),
        "actions": admin_recent_actions(username).get("actions", []),
    }


def get_players_status(player_names):
    try:
        return sql_player_status(player_names)
    except Exception as error:
        print(f"Web dashboard: SQLite player status failed: {error}")
        return {
            name: {"mmr": 1500, "mmr_rank": "Unranked", "pt": 0, "pt_rank": "Unranked"}
            for name in player_names
        }


def user_rank_summary(username):
    if not username:
        return None
    normalized = normalize_name(username)
    summary = {"name": username}
    summary["avatar"] = avatar_for_name(username)
    for kind in ["quarter_pt", "quarter_mmr", "total_mmr", "total_pt", "history_highest_mmr"]:
        for player in cached_rankings(kind=kind, limit=500):
            if normalize_name(player["name"]) == normalized:
                summary[kind] = {"rank": player["rank"], "value": player["value"], "label": player["label"]}
                break
    return summary


def sheet_recent_yakuman(limit=12):
    sheet = get_sheet()
    if sheet is None:
        return []

    game_rows = sheet.worksheet("Games Riichi").get_all_values()
    try:
        date_rows = sheet.worksheet("Games/pt").get_all_values()
    except Exception:
        date_rows = []

    records = []
    for row_index in range(len(game_rows) - 1, 0, -1):
        row = game_rows[row_index]
        winner = row[YAKUMAN_WINNER_INDEX].strip() if len(row) > YAKUMAN_WINNER_INDEX else ""
        yakuman_names = row[YAKUMAN_NAMES_INDEX].strip() if len(row) > YAKUMAN_NAMES_INDEX else ""
        if not winner and not yakuman_names:
            continue

        deal_in = row[YAKUMAN_DEAL_IN_INDEX].strip() if len(row) > YAKUMAN_DEAL_IN_INDEX else ""
        date = ""
        if row_index < len(date_rows) and date_rows[row_index]:
            date = date_rows[row_index][0]

        records.append(
            {
                "date": date,
                "winner": winner,
                "deal_in": deal_in,
                "yakuman": yakuman_names,
                "players": [name for name in row[:4] if name],
            }
        )
        if len(records) >= limit:
            break
    return records


def pt_delta_for_player(pt_row, player_name):
    columns = [(1, 3), (4, 6), (7, 9), (10, 12)]
    target = normalize_name(player_name)
    for name_index, value_index in columns:
        if len(pt_row) > value_index and normalize_name(pt_row[name_index]) == target:
            return pt_row[value_index]
    return ""


def resolve_sheet_player_name(player_name):
    target = normalize_name(player_name)
    if not target:
        return ""

    try:
        names = sheet_player_names()
    except Exception:
        names = []

    for name in names:
        if normalize_name(name) == target:
            return name

    partial_matches = [name for name in names if target in normalize_name(name)]
    if len(partial_matches) == 1:
        return partial_matches[0]

    return player_name


def sheet_recent_games(limit=12):
    sheet = get_sheet()
    game_rows = sheet.worksheet("Games Riichi").get_all_values()
    pt_rows = sheet.worksheet("Games/pt").get_all_values()
    games = []

    for row_index in range(len(game_rows) - 1, 0, -1):
        row = game_rows[row_index]
        if len(row) < 8 or not any(cell.strip() for cell in row[:4]):
            continue

        pt_row = pt_rows[row_index] if row_index < len(pt_rows) else []
        date = pt_row[0] if pt_row else ""
        players = []
        for index in range(4):
            name = row[index]
            players.append(
                {
                    "name": name,
                    "score": row[4 + index] if len(row) > 4 + index else "",
                    "delta": row[8 + index] if len(row) > 8 + index else "",
                    "pt_delta": pt_delta_for_player(pt_row, name),
                }
            )

        games.append(
            {
                "id": f"sheet-{row_index}",
                "created_at": date,
                "date": date,
                "user_name": "Google Sheet",
                "players": players,
                "reverted": False,
            }
        )
        if len(games) >= limit:
            break

    return games


def sheet_recent_games_for_player(player_name, limit=5):
    resolved_player_name = resolve_sheet_player_name(player_name)
    target = normalize_name(resolved_player_name)
    if not target:
        return [], ""

    sheet = get_sheet()
    game_rows = sheet.worksheet("Games Riichi").get_all_values()
    pt_rows = sheet.worksheet("Games/pt").get_all_values()
    games = []

    for row_index in range(len(game_rows) - 1, 0, -1):
        row = game_rows[row_index]
        if len(row) < 8:
            continue
        row_names = [normalize_name(name) for name in row[:4]]
        if target not in row_names:
            continue

        pt_row = pt_rows[row_index] if row_index < len(pt_rows) else []
        date = pt_row[0] if pt_row else ""
        players = []
        for index in range(4):
            name = row[index]
            players.append(
                {
                    "name": name,
                    "score": row[4 + index] if len(row) > 4 + index else "",
                    "delta": row[8 + index] if len(row) > 8 + index else "",
                    "pt_delta": pt_delta_for_player(pt_row, name),
                }
            )

        games.append(
            {
                "id": f"sheet-{row_index}",
                "created_at": date,
                "date": date,
                "user_name": "Google Sheet",
                "players": players,
                "target_player": resolved_player_name,
                "reverted": False,
            }
        )
        if len(games) >= limit:
            break

    return games, resolved_player_name


def load_sheet_player_names():
    sheet = get_sheet()
    rows = sheet.worksheet("Ratings").col_values(1)
    return sorted_player_names([name.strip() for name in rows[1:] if name.strip()])


def sheet_player_names():
    return sql_player_names()


@account_mutation
def live_db():
    registered_names.ensure_directory(USERS_FILE)
    candidates = {}
    for row in registered_names.account_rows(USERS_FILE):
        candidates.setdefault(row["name"], []).append(row["id"])
    unique = {name: ids[0] for name, ids in candidates.items() if len(ids) == 1}
    connection = sqlite3.connect(LIVE_DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS live_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            dealer_index INTEGER NOT NULL,
            honba INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            player1 TEXT NOT NULL,
            player2 TEXT NOT NULL,
            player3 TEXT NOT NULL,
            player4 TEXT NOT NULL,
            score1 INTEGER NOT NULL,
            score2 INTEGER NOT NULL,
            score3 INTEGER NOT NULL,
            score4 INTEGER NOT NULL,
            created_by TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS live_hands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            hand_type TEXT NOT NULL,
            dealer_index INTEGER NOT NULL,
            honba_before INTEGER NOT NULL,
            honba_after INTEGER NOT NULL,
            winner TEXT,
            deal_in TEXT,
            win_points INTEGER,
            deal_in_points INTEGER,
            yaku TEXT,
            dealer_tenpai INTEGER NOT NULL,
            dealer_continued INTEGER NOT NULL,
            notes TEXT,
            recorded_by TEXT NOT NULL,
            FOREIGN KEY(game_id) REFERENCES live_games(id)
        )
        """
    )
    for field in [*(f"player{i}_user_id" for i in range(1, 5)), "created_by_user_id"]:
        mahjong_store.ensure_column(connection, "live_games", field, "TEXT")
    mahjong_store.ensure_column(connection, "live_games", "identity_version", "INTEGER NOT NULL DEFAULT 0")
    for field in ("winner_user_id", "deal_in_user_id", "recorded_by_user_id"):
        mahjong_store.ensure_column(connection, "live_hands", field, "TEXT")
    mahjong_store.ensure_column(connection, "live_hands", "identity_version", "INTEGER NOT NULL DEFAULT 0")
    # Freeze legacy associations once, while holding the account lock and before
    # any registered name changes. Unregistered/ambiguous names remain unlinked;
    # a future registration reusing that spelling cannot claim these old rows.
    for game in connection.execute("SELECT * FROM live_games WHERE identity_version=0").fetchall():
        ids = [unique.get(game[f"player{i}"]) for i in range(1, 5)]
        connection.execute("UPDATE live_games SET player1_user_id=?,player2_user_id=?,player3_user_id=?,player4_user_id=?,created_by_user_id=?,identity_version=1 WHERE id=?",
                           (*ids, unique.get(game["created_by"]), game["id"]))
    for hand in connection.execute("SELECT * FROM live_hands WHERE identity_version=0").fetchall():
        game = connection.execute("SELECT * FROM live_games WHERE id=?", (hand["game_id"],)).fetchone()
        roster = {game[f"player{i}"]: game[f"player{i}_user_id"] for i in range(1, 5)} if game else {}
        connection.execute("UPDATE live_hands SET winner_user_id=?,deal_in_user_id=?,recorded_by_user_id=?,identity_version=1 WHERE id=?",
                           (roster.get(hand["winner"]), roster.get(hand["deal_in"]), unique.get(hand["recorded_by"]), hand["id"]))
    connection.commit()
    return connection


def row_to_dict(row):
    return dict(row) if row else None


def _live_account(value, profiles, *, user_id=None):
    if user_id is not None:
        matches = [person for person in profiles if person["id"] == user_id]
    else:
        matches = [person for person in profiles if normalize_name(person["name"]) == normalize_name(value)]
    if len(matches) != 1 or matches[0].get("disabled"):
        raise ValueError("Please select an available registered user.")
    return matches[0]


def project_live_record(record, profiles):
    result = dict(record)
    names = {person["id"]: person["name"] for person in profiles}
    for field in [*(f"player{i}" for i in range(1, 5)), "created_by", "winner", "deal_in", "recorded_by"]:
        uid = result.get(field + "_user_id")
        if field in result and uid in names:
            result[field] = names[uid]
    return result


@account_mutation
def create_live_game(data, username):
    profiles = registered_names.account_rows(USERS_FILE)
    selected = [_live_account(data.get(f"player{i}"), profiles, user_id=data.get(f"player{i}_user_id")) for i in range(1,5)]
    if len({person["id"] for person in selected}) != 4:
        raise ValueError("Live-game players must be unique.")
    creator = _live_account(username, profiles)
    with closing(live_db()) as connection:
        cursor = connection.execute("""
            INSERT INTO live_games (created_at,status,dealer_index,honba,round_number,
              player1,player2,player3,player4,score1,score2,score3,score4,created_by,
              player1_user_id,player2_user_id,player3_user_id,player4_user_id,created_by_user_id,identity_version)
            VALUES (?,'active',0,0,1,?,?,?,?,25000,25000,25000,25000,?,?,?,?,?,?,1)
            """, [local_now_string(),*[person["name"] for person in selected],creator["name"],
                  *[person["id"] for person in selected],creator["id"]])
        connection.commit()
        game = row_to_dict(connection.execute("SELECT * FROM live_games WHERE id=?",[cursor.lastrowid]).fetchone())
    return project_live_record(game, profiles)


@account_mutation
def active_live_games():
    with closing(live_db()) as connection:
        rows = connection.execute("SELECT * FROM live_games WHERE status='active' ORDER BY id DESC LIMIT 5").fetchall()
    profiles = registered_names.account_rows(USERS_FILE)
    return [project_live_record(row, profiles) for row in rows]


def _live_hand_player(data, field, profiles, game):
    supplied_id = data.get(field + "_user_id")
    raw_name = str(data.get(field) or "")
    # A legacy unregistered seat stays playable without inventing an account.
    # Never use this fallback when any current account owns that spelling or
    # when an explicit (possibly forged) ID was provided.
    if supplied_id is None and raw_name.strip() and game.get("identity_version") == 1:
        registered = any(normalize_name(person["name"]) == normalize_name(raw_name) for person in profiles)
        legacy = [i for i in range(1,5) if game[f"player{i}_user_id"] is None and game[f"player{i}"] == raw_name]
        if not registered and len(legacy) == 1:
            return {"id": None, "name": raw_name, "index": legacy[0] - 1}
    person = _live_account(raw_name, profiles, user_id=supplied_id)
    indices = [i for i in range(1,5) if game[f"player{i}_user_id"] == person["id"]]
    if len(indices) != 1:
        raise ValueError("Selected player is not linked to this live game. Ask an administrator to review ambiguous legacy names.")
    return {**person, "index": indices[0] - 1}


@account_mutation
def record_live_hand(data, username):
    game_id = int(data.get("game_id") or 0)
    hand_type = data.get("hand_type") or "win"
    if hand_type not in {"win", "draw"}:
        raise ValueError("Hand type must be win or draw.")
    profiles = registered_names.account_rows(USERS_FILE)
    recorder = _live_account(username, profiles)
    with closing(live_db()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        game = row_to_dict(connection.execute("SELECT * FROM live_games WHERE id=?",[game_id]).fetchone())
        if not game:
            raise ValueError("Live game not found.")
        scores = [int(game[f"score{i}"]) for i in range(1,5)]
        dealer_index = int(game["dealer_index"])
        honba_before = int(data.get("honba") or game["honba"])
        winner = deal_in = ""
        winner_id = deal_in_id = None
        win_points = int(data.get("win_points") or 0)
        deal_in_points = int(data.get("deal_in_points") or 0)
        yaku = (data.get("yaku") or "").strip()
        notes = (data.get("notes") or "").strip()
        dealer_tenpai = bool(data.get("dealer_tenpai"))
        if hand_type == "win":
            selected = _live_hand_player(data, "winner", profiles, game)
            winner_id, winner = selected["id"], selected["name"]
            winner_index = selected["index"]
            dealer_continued = winner_index == dealer_index
            if data.get("deal_in") or data.get("deal_in_user_id"):
                selected = _live_hand_player(data, "deal_in", profiles, game)
                deal_in_id, deal_in = selected["id"], selected["name"]
                deal_in_index = selected["index"]
                if deal_in_index == winner_index:
                    raise ValueError("Winner and deal-in player cannot be the same.")
                scores[winner_index] += win_points
                scores[deal_in_index] -= deal_in_points or win_points
            elif win_points:
                for index in range(4):
                    scores[index] += win_points * 3 if index == winner_index else -win_points
        else:
            dealer_continued = dealer_tenpai
        honba_after = honba_before + 1 if dealer_continued or hand_type == "draw" else 0
        next_dealer = dealer_index if dealer_continued else (dealer_index + 1) % 4
        next_round = int(game["round_number"]) + (0 if dealer_continued else 1)
        connection.execute("""
            INSERT INTO live_hands (game_id,created_at,hand_type,dealer_index,honba_before,honba_after,
              winner,deal_in,win_points,deal_in_points,yaku,dealer_tenpai,dealer_continued,notes,recorded_by,
              winner_user_id,deal_in_user_id,recorded_by_user_id,identity_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
            """, [game_id,local_now_string(),hand_type,dealer_index,honba_before,honba_after,winner,deal_in,
                  win_points,deal_in_points,yaku,int(dealer_tenpai),int(dealer_continued),notes,recorder["name"],
                  winner_id,deal_in_id,recorder["id"]])
        connection.execute("""UPDATE live_games SET dealer_index=?,honba=?,round_number=?,
                           score1=?,score2=?,score3=?,score4=? WHERE id=?""",
                           [next_dealer,honba_after,next_round,*scores,game_id])
        connection.commit()
        updated = row_to_dict(connection.execute("SELECT * FROM live_games WHERE id=?",[game_id]).fetchone())
    return project_live_record(updated, profiles)


def normalize_name(value):
    return registered_names.normalize_name(value)


_request_accounts = contextvars.ContextVar("request_accounts", default=None)


def users_data():
    cache = _request_accounts.get()
    version = (str(USERS_FILE), registered_names._file_version(USERS_FILE),
               registered_names._file_version(registered_names.database_path(USERS_FILE)))
    if cache is not None and cache.get("version") == version and not Path(str(USERS_FILE)+".pending").exists():
        return cache["data"]
    data = registered_names.read_accounts(USERS_FILE)
    if cache is not None:
        cache.update(version=version, data=data)
    if not isinstance(data, dict):
        data = {}
    users = data.get("users")
    if not isinstance(users, dict):
        data["users"] = {}
    player_icons = data.get("player_icons")
    if not isinstance(player_icons, dict):
        data["player_icons"] = {}
    return data


def default_role_for_name(name):
    key = normalize_name(name)
    if key in {normalize_name(item) for item in DEFAULT_SUPER_ADMINS}:
        return "super_admin"
    if key in {normalize_name(item) for item in DEFAULT_ADMINS}:
        return "admin"
    return "user"


def role_for_user(name):
    key = normalize_name(name)
    data = users_data()
    try:
        actual_key, _ = resolve_registered_account(data, name)
        user = data["users"][actual_key]
    except ValueError:
        return "user"
    role = user.get("role") or default_role_for_name(name)
    return role if role in ROLE_ORDER else "user"


def is_admin(name):
    return ROLE_ORDER.get(role_for_user(name), 0) >= ROLE_ORDER["admin"]


def is_super_admin(name):
    return ROLE_ORDER.get(role_for_user(name), 0) >= ROLE_ORDER["super_admin"]


def avatar_for_name(name):
    data = users_data()
    try:
        key, _ = resolve_registered_account(data, name)
        return account_discord.avatar(data["users"][key])
    except ValueError:
        return ""


def icon_for_name(name):
    icon = users_data().get("player_icons", {}).get(normalize_name(name), {})
    if not isinstance(icon, dict):
        return {}
    return {
        "label": str(icon.get("label") or "").strip(),
        "image": str(icon.get("image") or "").strip(),
    }


def public_user_profiles():
    data_file = users_data()
    users = data_file.get("users", {})
    profiles = {
        data.get("name", key): {"name": data.get("name", key), "avatar": account_discord.avatar(data), "discord_name": data.get("discord_name", "")}
        for key, data in users.items()
    }
    for key, icon in data_file.get("player_icons", {}).items():
        display_name = users.get(key, {}).get("name", key)
        profiles.setdefault(display_name, {"name": display_name, "avatar": ""})
        profiles[display_name]["icon"] = icon
    return profiles


def move_user_account(data_file, old_name, new_name):
    old_key = normalize_name(old_name)
    new_key = normalize_name(new_name)
    users = data_file.get("users", {})
    if old_key in users:
        user = users.pop(old_key)
        user["name"] = new_name
        users[new_key] = user
    icons = data_file.get("player_icons", {})
    if old_key in icons and new_key not in icons:
        icons[new_key] = icons.pop(old_key)


def current_user_profile(handler):
    username = current_user(handler)
    if not username:
        return None
    profile = current_user_profile_from_name(username)
    profile["session_mode"] = "member" if session_cookie(handler).startswith("member.") else "verified"
    return profile


def stable_account_id(username):
    """Keep existing opaque IDs while adding the unique registered-name directory."""
    with registered_names.account_lock(USERS_FILE):
        data = users_data()
        try:
            key, _ = resolve_registered_account(data, username)
        except ValueError:
            raise PermissionError("Account no longer exists.") from None
        if not data["users"][key].get("account_id") or not registered_names.database_path(USERS_FILE).exists():
            registered_names.ensure_directory(USERS_FILE)
            data = users_data()
            key, _ = resolve_registered_account(data, username)
        return data["users"][key]["account_id"]


def current_user_profile_from_name(username):
    role = role_for_user(username)
    account_id = stable_account_id(username)
    directory = users_data()
    key, current_name = resolve_registered_account(directory, username)
    account = directory["users"][key]
    return {
        "id": account_id,
        "name": current_name,
        "avatar": avatar_for_name(current_name),
        "icon": icon_for_name(current_name),
        "discord_id": account.get("discord_id", ""),
        "discord_name": account.get("discord_name", ""),
        "has_password": bool(account.get("password_hash")),
        "role": role,
        "is_admin": ROLE_ORDER.get(role, 0) >= ROLE_ORDER["admin"],
        "is_super_admin": ROLE_ORDER.get(role, 0) >= ROLE_ORDER["super_admin"],
    }


@account_mutation
def update_user_avatar(username, avatar):
    if not (avatar.startswith("data:image/jpeg;base64,") or avatar.startswith("data:image/png;base64,")):
        raise ValueError("Please upload a JPG or PNG image.")
    if len(avatar) > 1_450_000:
        raise ValueError("Avatar image is too large. Please use an image under 1MB.")
    data_file = users_data()
    user_key, _ = resolve_registered_account(data_file, username)
    if user_key not in data_file.get("users", {}):
        raise ValueError("User account not found.")
    data_file["users"][user_key]["avatar"] = avatar
    write_json(USERS_FILE, data_file)
    return {"name": data_file["users"][user_key]["name"], "avatar": avatar}


@account_mutation
def unbind_discord_account(username):
    data_file = users_data()
    user_key, _ = resolve_registered_account(data_file, username)
    if user_key not in data_file.get("users", {}):
        raise ValueError("User account not found.")
    account_discord.unbind(data_file["users"][user_key])
    write_json(USERS_FILE, data_file)
    return current_user_profile_from_name(data_file["users"][user_key]["name"])


def password_hash(password, salt=None):
    if salt is None:
        return hash_password(password)
    # Compatibility for existing tools that explicitly verify old PBKDF2 salts.
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return salt, digest.hex()


def session_cookie(handler):
    from http.cookies import SimpleCookie
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie", ""))
    except Exception:
        return ""
    return cookie["mahjong_session"].value if "mahjong_session" in cookie else ""


def unverified_historical_account(account):
    return (account.get("auto_registered") is True
            and not account.get("password_hash") and not account.get("discord_id"))


def create_account_session(account, *, member_only=False):
    account_id = str(account.get("account_id") or "")
    if not account_id:
        raise ValueError("Account identity is unavailable.")
    token = ("member." if member_only else "") + secrets.token_urlsafe(32)
    _sessions[token], _session_account_ids[token] = account["name"], account_id
    try:
        registered_names.remember_session(
            USERS_FILE, token, account_id, int(time.time()) + SESSION_MAX_AGE_SECONDS)
    except Exception:
        _sessions.pop(token, None)
        _session_account_ids.pop(token, None)
        raise
    return token, account["name"]


def issue_session(handler, account_id):
    directory = users_data()
    account = next((a for a in directory["users"].values() if a.get("account_id") == account_id), None)
    if not account or account.get("disabled") or account.get("is_active") is False or account.get("status") in {"pending_claim", "disabled", "deleted", "banned"}:
        raise PermissionError("This account is unavailable.")
    old = session_cookie(handler)
    _sessions.pop(old, None); _session_account_ids.pop(old, None)
    registered_names.forget_session(USERS_FILE, old)
    return create_account_session(account)


def authenticated_response(handler, token, body):
    from account_images import public_avatars
    payload = json.dumps(public_avatars(body), ensure_ascii=False).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Set-Cookie", f"mahjong_session={token}{persistent_session_cookie_suffix(handler)}")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers(); handler.wfile.write(payload)


def current_user(handler):
    token = session_cookie(handler)
    if not token:
        return None
    cached_id = _session_account_ids.get(token)
    durable_id = registered_names.session_account_id(USERS_FILE, token)
    if cached_id:
        # The durable row is authoritative for expiry and cross-worker
        # revocation; an in-process cache must never resurrect it.
        if durable_id != cached_id:
            _sessions.pop(token, None)
            _session_account_ids.pop(token, None)
            return None
    elif durable_id:
        directory = users_data()
        matches = [(account_key, account) for account_key, account in directory["users"].items()
                   if str(account.get("account_id")) == durable_id]
        if len(matches) == 1:
            account_key, account = matches[0]
            _sessions[token] = account.get("name", account_key)
            _session_account_ids[token] = durable_id
    if token in _sessions:
        username = _sessions[token]
        directory = users_data()
        try:
            session_id = _session_account_ids.get(token)
            if session_id:
                matches = [(account_key, account) for account_key, account in directory["users"].items()
                           if str(account.get("account_id")) == session_id]
                if len(matches) != 1:
                    registered_names.forget_session(USERS_FILE, token)
                    _sessions.pop(token, None)
                    _session_account_ids.pop(token, None)
                    return None
                account_key, account = matches[0]
                name = account.get("name", account_key)
            else:
                account_key, name = resolve_registered_account(directory, username)
                account = directory["users"][account_key]
            if (account.get("disabled") or account.get("is_active") is False
                    or account.get("status") in {"disabled", "banned", "deleted", "pending_claim"}
                    or (token.startswith("member.") and is_admin(name))):
                registered_names.forget_session(USERS_FILE, token)
                _sessions.pop(token, None)
                _session_account_ids.pop(token, None)
                return None
            _sessions[token] = name
            return name
        except ValueError:
            registered_names.forget_session(USERS_FILE, token)
            _sessions.pop(token, None)
            _session_account_ids.pop(token, None)
            return None
    return None


def require_user(handler):
    user = current_user(handler)
    if not user:
        raise PermissionError("Please log in before recording games.")
    return user


def require_verified_user(handler):
    username = require_user(handler)
    if session_cookie(handler).startswith("member."):
        raise PermissionError("Sign in with your account password to change account settings.")
    return username


@account_mutation
def register_user(data):
    # Internal callers retain compatibility; the HTTP handler requires confirmation.
    return account_registration.create_new(sys.modules[__name__], data, confirmation=False)


class WebsiteRegistrationRequired(ValueError):
    code = "website_registration_required"


class PasswordRequired(ValueError):
    code = "password_required"


class AdminPasswordSetupRequired(ValueError):
    code = "admin_password_setup_required"


def login_player(data):
    player = account_registration.legacy_player(sys.modules[__name__], data.get("player_id"))
    account = account_registration.ensure_player_account(sys.modules[__name__], player)
    if account.get("disabled") or account.get("is_active") is False or account.get("status") in {"disabled", "banned", "deleted", "pending_claim"}:
        raise PermissionError("This account is unavailable.")
    if is_admin(account.get("name", player["name"])):
        if not account.get("password_hash"):
            raise AdminPasswordSetupRequired("You are an administrator. Please register a password.")
        raise PermissionError("Administrators must use the separate administrator sign-in.")
    return create_account_session(account, member_only=True)


@account_mutation
def login_user(data):
    if isinstance(data, dict) and "player_id" in data:
        return login_player(data)
    if not isinstance(data, dict) or not isinstance(data.get("username"), str):
        raise ValueError("Please enter your username.")
    if data.get("password") is not None and not isinstance(data.get("password"), str):
        raise ValueError("Invalid password.")
    account_registration.recover_creations(sys.modules[__name__])
    raw_username = data.get("username") or ""
    username = normalize_name(raw_username)
    password = data.get("password") or ""
    directory = users_data()
    try:
        account_key, _ = resolve_registered_account(directory, raw_username)
        user = directory["users"][account_key]
    except ValueError:
        user = None
    if not user:
        try:
            known_player = any(normalize_name(name) == username
                               for name in player_directory.player_names(MAHJONG_DB_FILE))
        except (OSError, sqlite3.Error):
            known_player = False
        if known_player:
            raise WebsiteRegistrationRequired(
                "This player has no website account. Select the player's name to continue; existing results stay linked.")
        raise ValueError("Incorrect username or password.")
    if user.get("disabled") or user.get("is_active") is False or user.get("status") in {"disabled", "banned", "deleted", "pending_claim"}:
        raise PermissionError("This account is unavailable.")
    if is_admin(user.get("name", raw_username)) and not user.get("password_hash"):
        raise AdminPasswordSetupRequired("You are an administrator. Please register a password.")
    if not password:
        raise PasswordRequired("Select your player name to sign in, or enter your password.")
    if not verify_password(password, user):
        raise ValueError("Incorrect username or password.")
    return create_account_session(user)


@account_mutation
def change_password(username, data):
    if not isinstance(data, dict):
        raise ValueError("Invalid password form.")
    old_password = data.get("old_password")
    new_password = data.get("new_password")
    if new_password != data.get("confirm_password"):
        raise ValueError("Please enter the new password twice.")
    salt, new_hash = password_hash(new_password)

    data_file = users_data()
    user_key, _ = resolve_registered_account(data_file, username)
    user = data_file.get("users", {}).get(user_key)
    if not user:
        raise ValueError("User account not found.")
    if unverified_historical_account(user):
        raise PermissionError("Complete a verified account claim before setting a password.")
    if user.get("password_hash") and not verify_password(old_password, user):
        raise ValueError("Current password is incorrect.")
    user["salt"] = salt
    user["password_hash"] = new_hash
    user["password_changed_at"] = int(time.time())
    user.pop("password_reset", None)
    write_json(USERS_FILE, data_file)
    return True


def request_password_reset(data):
    """Notify the established Discord recovery channel; admins deliver codes privately."""
    username = data.get("username")
    if not isinstance(username, str) or not username.strip() or len(username) > 128:
        raise PasswordResetError("Please enter your player name.", "reset_name_required")
    response = {"ok": True, "message": "If this player has an active website account, an administrator has been notified. Ask them for your reset code."}
    marker = secrets.token_hex(16)
    with registered_names.account_lock(USERS_FILE):
        registered_names.ensure_directory(USERS_FILE)
        directory = users_data()
        try:
            key, display_name = resolve_registered_account(directory, username)
        except ValueError:
            return response
        account = directory["users"][key]
        if not recovery_account_enabled(account):
            return response
        previous = account.get("password_reset_request") or {}
        if time.time() - previous.get("requested_at", 0) < 10 * 60:
            return response
        account_id = str(account["account_id"])
        account["password_reset_request"] = {"request_id": marker, "requested_at": time.time()}
        write_json(USERS_FILE, directory)
    from urllib.parse import urlencode
    origin = os.getenv("PUBLIC_SITE_URL", "https://doramj.org").rstrip("/") or "https://doramj.org"
    link = origin + "/?" + urlencode({"page": "admin", "recovery_user": account_id}) + "#account-recovery"
    # Keep the established channel notice code-free; the user sets their own password.
    payload = {"content": "Password reset request / 密码重置申请", "allowed_mentions": {"parse": []},
               "embeds": [{"title": "Generate reset code / 生成重置码", "url": link,
                           "description": "核实玩家身份后，打开链接生成一次性重置码并私下交给本人。玩家自行设置新密码。",
                           "fields": [{"name": "Player / 玩家", "value": display_name[:128]}]}]}
    try:
        discord_request("POST", "/channels/1488771447915544586/messages", payload)
    except Exception:
        with registered_names.account_lock(USERS_FILE):
            directory = users_data()
            for account in directory["users"].values():
                if str(account.get("account_id")) == account_id and (account.get("password_reset_request") or {}).get("request_id") == marker:
                    account.pop("password_reset_request", None)
                    write_json(USERS_FILE, directory)
                    break
        # Provider exceptions can contain private configuration; never reflect them.
        raise PasswordResetError("Could not notify the administrator. Please try again later.", "reset_notification_failed") from None
    return response


def validate_record_payload(data):
    players, scores, ranked_entries, wind_entries = ordered_game_from_entries(game_entries_from_payload(data))

    player_names = {player.casefold() for player in players}
    yakuman_winner = (data.get("yakuman_winner") or "").strip()
    yakuman_deal_in = (data.get("yakuman_deal_in") or "").strip()
    raw_yakuman_names = data.get("yakuman_names") or []
    if isinstance(raw_yakuman_names, str):
        raw_yakuman_names = [raw_yakuman_names]
    yakuman_names = [name for name in raw_yakuman_names if name in YAKUMAN_OPTIONS]
    yakuman_text = ", ".join(yakuman_names)

    if yakuman_winner and yakuman_winner.casefold() not in player_names:
        raise ValueError("Yakuman winner must be one of the four players.")
    if yakuman_deal_in and yakuman_deal_in.casefold() not in player_names:
        raise ValueError("Yakuman deal-in player must be one of the four players.")
    if yakuman_names and not yakuman_winner:
        raise ValueError("Please choose a yakuman winner when recording yakuman.")

    manual_time = (data.get("manual_time") or "").strip()
    final_time = parse_web_time(manual_time)

    recorder = (data.get("recorder") or "web").strip() or "web"
    return players, scores, final_time, yakuman_winner, yakuman_deal_in, yakuman_text, yakuman_names, recorder, ranked_entries, wind_entries


def append_game_record(data):
    players, scores, final_time, yakuman_winner, yakuman_deal_in, yakuman_text, yakuman_names, recorder, ranked_entries, wind_entries = validate_record_payload(data)
    pre_status = get_players_status(players)
    sql_game_id = None
    mmr_deltas = []
    mmr_afters = []
    current_quarter = ""
    sheet_error = ""
    narts_result = {"enabled": False, "message": "NARTS sync skipped: NARTS_EXTERNAL_API_KEY is not set."}
    pt_row = None
    riichi_row = None
    pt_values = [final_time]
    riichi_values = players + scores
    try:
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            current_quarter = mahjong_store.latest_quarter(connection)
            sql_game_id = mahjong_store.import_game(
                connection,
                players,
                scores,
                final_time,
                source="web",
                created_by=recorder,
                yakuman={
                    "winner": yakuman_winner,
                    "deal_in": yakuman_deal_in,
                    "text": yakuman_text,
                    "names": yakuman_names,
                },
                quarter=current_quarter,
                seat_winds=[{"E": "east", "S": "south", "W": "west", "N": "north"}[entry["seatWind"]] for entry in ranked_entries],
                source_seat_order="ESWN" if any(data.get(f"{wind}_name") for wind in ("east", "south", "west", "north")) else "EWSN",
            )
            mmr_deltas = mahjong_store.game_mmr_deltas(connection, sql_game_id)
            mmr_afters = mahjong_store.game_mmr_afters(connection, sql_game_id)
        clear_sheet_cache()
    except Exception as error:
        raise RuntimeError(f"SQLite game write failed, so Google Sheet was not changed: {error}") from error

    try:
        sheet = get_sheet()
        from legacy_sheet_sync import append_game
        riichi_row = append_game(sheet, final_time, players, scores, mmr_deltas,
            mmr_afters, current_quarter, yakuman_winner, yakuman_deal_in, yakuman_text, record_id=sql_game_id)
        pt_row = riichi_row
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            connection.execute("UPDATE games SET sheet_row=?, sync_status='synced' WHERE id=?",
                               (riichi_row, sql_game_id))
            connection.commit()
    except Exception as error:
        sheet_error = str(error)
        print(f"Web dashboard: Google Sheet game write failed: {sheet_error}")

    if sql_game_id:
        narts_result = submit_narts_match(sql_game_id, final_time, wind_entries, recorder)
        if narts_result.get("enabled") and not narts_result.get("ok"):
            print("Web dashboard: external sync pending; local game retained.")

    action = record_action(
        user_id=0,
        user_name=recorder,
        action_type="record_game",
        summary=f"Recorded game at {final_time}: {', '.join(players)}",
        payload={
            "games_pt_row": pt_row,
            "games_pt_values": pt_values,
            "games_riichi_row": riichi_row,
            "games_riichi_values": riichi_values,
            "mmr_deltas": mmr_deltas,
            "mmr_afters": mmr_afters,
            "quarter": current_quarter,
            "yakuman_winner": yakuman_winner,
            "yakuman_deal_in": yakuman_deal_in,
            "yakuman_text": yakuman_text,
            "yakuman_names": yakuman_names,
            "sql_game_id": sql_game_id,
            "sheet_error": sheet_error,
            "wind_entries": wind_entries,
            "ranked_entries": ranked_entries,
            "narts_result": narts_result,
        },
    )
    post_status = get_players_status(players)
    result = build_game_result(players, scores, pre_status, post_status, mmr_deltas, action_id=action["id"])
    clear_sheet_cache()
    schedule_discord_game_summary(
        {
            "players": players,
            "scores": scores,
            "final_time": final_time,
            "yakuman_winner": yakuman_winner,
            "yakuman_deal_in": yakuman_deal_in,
            "yakuman_text": yakuman_text,
            "yakuman_names": yakuman_names,
            "mmr_deltas": mmr_deltas,
            "pre_status": pre_status,
            "post_status": post_status,
            "recorder": recorder,
        }
    )

    warnings = []
    if sheet_error:
        warnings.append(PUBLIC_SYNC_WARNING)
    if narts_result.get("enabled") and not narts_result.get("ok"):
        status = narts_result.get("status") or "network"
        warnings.append("External score upload failed. Local results are saved; please retry upload.")

    if warnings:
        message = "Game recorded locally."
    elif narts_result.get("enabled"):
        message = "Game recorded. MMR was calculated locally, synced to Google Sheet, and sent to NARTS."
    else:
        message = "Game recorded. MMR was calculated locally and synced to Google Sheet."

    return {
        "ok": True,
        "message": message,
        "warning": " ".join(warnings),
        "action": action,
        "result": result,
    }


def build_discord_game_embed(context, mmr_deltas, post_status):
    from game_summary import build_game_summary
    return build_game_summary(context["players"], context["scores"], context["final_time"],
        context["pre_status"], post_status, context.get("yakuman_winner", ""),
        context.get("yakuman_deal_in", ""), context.get("yakuman_text", ""))


def send_discord_game_summary(context):
    if os.getenv("DISCORD_SCORE_NOTIFICATIONS_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return
    try:
        mmr_deltas = context.get("mmr_deltas") or []
        post_status = context["post_status"]
        channel_id = find_game_record_channel_id()
        discord_request(
            "POST",
            f"/channels/{channel_id}/messages",
            {"embeds": [build_discord_game_embed(context, mmr_deltas, post_status)]},
        )
    except Exception as error:
        print(f"Web dashboard: Discord game summary failed: {error}")


def schedule_discord_game_summary(context):
    thread = threading.Thread(target=send_discord_game_summary, args=(context,), daemon=True)
    thread.start()


def record_games_from_actions(actions, match_player="", limit=12):
    target = normalize_name(match_player)
    games = []
    for action in reversed(actions):
        if action.get("action_type") != "record_game":
            continue

        payload = action.get("payload") or {}
        values = payload.get("games_riichi_values") or []
        deltas = payload.get("mmr_deltas") or []
        if len(values) < 8:
            continue
        if target and target not in [normalize_name(name) for name in values[:4]]:
            continue

        players = []
        for index in range(4):
            players.append(
                {
                    "name": values[index],
                    "score": values[index + 4],
                    "delta": deltas[index] if index < len(deltas) else "",
                }
            )

        games.append(
            {
                "id": action.get("id"),
                "created_at": action.get("created_at"),
                "user_name": action.get("user_name"),
                "summary": action.get("summary"),
                "players": players,
                "reverted": bool(action.get("reverted_at")),
            }
        )
        if len(games) >= limit:
            break
    return games


def yakuman_from_actions(actions, limit=12):
    records = []
    for action in reversed(actions):
        payload = action.get("payload") or {}
        winner = payload.get("yakuman_winner") or ""
        yakuman = payload.get("yakuman_text") or ""
        if not winner and not yakuman:
            continue

        values = payload.get("games_riichi_values") or []
        records.append(
            {
                "date": (payload.get("games_pt_values") or [""])[0],
                "winner": winner,
                "deal_in": payload.get("yakuman_deal_in") or "",
                "yakuman": yakuman,
                "players": values[:4],
            }
        )
        if len(records) >= limit:
            break
    return records


def build_dashboard(ranking_type="quarter_pt", user=None, match_player="", view_quarter="", table_players=None, profile_quarter=None, profile_player=""):
    actions = read_json(ROOT / "bot_action_log.json", [])
    subscriptions = read_json(ROOT / "replay_subscriptions.json", {})
    requested_match_player = (match_player or "").strip()
    # The match-history page defaults to the full recent list when no player is selected.
    resolved_match_player = requested_match_player
    players = sql_player_names()
    try:
        quarter_context = sql_quarter_context()
    except Exception as error:
        print(f"Web dashboard: SQLite quarter context failed: {error}")
        quarter_context = {"current_quarter": "", "quarters": []}

    selected_quarter = view_quarter if view_quarter in quarter_context.get("quarters", []) else quarter_context.get("current_quarter", "")

    table_players = [str(name or "").strip() for name in (table_players or []) if str(name or "").strip()]
    try:
        if table_players:
            record_games = sql_recent_games_for_players(table_players, 500, quarter=selected_quarter)
            resolved_match_player = " / ".join(table_players)
        elif requested_match_player:
            record_games, resolved_match_player = sql_recent_games_for_player(resolved_match_player, 500, quarter=selected_quarter)
        else:
            with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
                record_games, _ = mahjong_store.recent_games(connection, limit=100, quarter=selected_quarter)
    except Exception as error:
        print(f"Web dashboard: SQLite recent games failed: {error}")
        record_games = record_games_from_actions(actions, resolved_match_player, 5 if resolved_match_player else 12)
    active_actions = [action for action in actions if not action.get("reverted_at")]
    ranking_error = ""
    yakuman_error = ""

    try:
        rankings = sql_rankings(kind=ranking_type, quarter=selected_quarter)
    except Exception as error:
        rankings = []
        ranking_error = str(error)

    try:
        recent_yakuman = sql_recent_yakuman(500)
    except Exception as error:
        recent_yakuman = []
        yakuman_error = str(error)
    try:
        yakuman_leaders = sql_yakuman_leaders()
    except Exception as error:
        yakuman_leaders = []
        yakuman_error = yakuman_error or str(error)

    current_user_rank = None
    profile_target = (profile_player or user or "").strip()
    annual_summary = None
    if profile_target:
        try:
            current_user_rank = sql_user_rank_summary(profile_target, quarter=profile_quarter)
        except Exception as error:
            ranking_error = ranking_error or str(error)
    if user:
        try:
            annual_summary = sql_annual_summary(user)
        except Exception as error:
            print(f"Web dashboard: SQLite annual summary failed: {error}")

    try:
        chart_player = resolved_match_player or user or ""
        quarter_pt_history, _ = sql_quarter_pt_history(chart_player, limit=200, quarter=selected_quarter) if chart_player else ([], "")
    except Exception as error:
        print(f"Web dashboard: SQLite quarter PT history failed: {error}")
        quarter_pt_history = []

    try:
        revert_candidates = sql_revert_candidates(15)
    except Exception as error:
        print(f"Web dashboard: SQLite revert candidates failed: {error}")
        revert_candidates = []

    return {
        "stats": {
            "recorded_games": len(record_games_from_actions(actions)) if len(actions) <= 12 else len(
                [action for action in actions if action.get("action_type") == "record_game"]
            ),
            "active_actions": len(active_actions),
            "replay_subscriptions": len(subscriptions),
            "ranking_players": len(rankings),
            "member_count": len(players),
            "recent_yakuman": len(recent_yakuman),
            "current_quarter": quarter_context.get("current_quarter", ""),
            "view_quarter": selected_quarter,
        },
        "rankings": rankings,
        "player_stats": safe_sql_player_stats(),
        "ranking_type": ranking_type,
        "ranking_options": [{"value": key, "label": value["label"]} for key, value in RANKING_TYPES.items()],
        "yakuman_leaders": yakuman_leaders,
        "ranking_error": ranking_error,
        "current_user_rank": current_user_rank,
        "annual_summary": annual_summary,
        "current_user_profile": current_user_profile_from_name(user) if user else None,
        "view_profile_player": profile_target,
        "profiles": public_user_profiles(),
        "recent_match_player": resolved_match_player,
        "recent_match_count": len(record_games),
        "quarter_pt_history": quarter_pt_history,
        "quarters": quarter_context.get("quarters", []),
        "recent_yakuman": recent_yakuman,
        "yakuman_error": yakuman_error,
        "recent_games": record_games,
        "recent_actions": list(reversed(actions))[:10],
        "revert_candidates": revert_candidates,
        "subscriptions": list(subscriptions.values()),
        "live_games": active_live_games(),
    }


def safe_sql_player_stats():
    try:
        return sql_player_stats()
    except Exception as error:
        print(f"Web dashboard: SQLite player stats failed: {error}")
        return []


def public_player_history(raw_player_id):
    """Public historical results for one canonical club ID, with no account data."""
    player = account_registration.legacy_player(sys.modules[__name__], raw_player_id)
    with closing(mahjong_store.connect(MAHJONG_DB_FILE)) as db:
        row = db.execute(
            "SELECT id, name, current_mmr, total_pt, games_played, wins FROM players WHERE id = ?",
            (player["id"],),
        ).fetchone()
        if row is None:
            raise ValueError("Player ID not found.")
        games, _ = mahjong_store.recent_games(db, limit=30, player_name=row["name"])
    return {
        "ok": True,
        "player": {"id": f"club-{row['id']}", "name": row["name"]},
        "summary": {
            "games_played": row["games_played"],
            "wins": row["wins"],
            "current_mmr": round(float(row["current_mmr"]), 2),
            "total_pt": round(float(row["total_pt"]), 2),
        },
        "recent_games": [
            {
                "date": game["date"],
                "players": [
                    {
                        "name": seat["name"],
                        "score": seat["score"],
                        "mmr_delta": seat["delta"],
                        "pt_delta": seat["pt_delta"],
                    }
                    for seat in game["players"]
                ],
            }
            for game in games
        ],
    }


class WebHTTPServer(ThreadingHTTPServer):
    # Python 3.14 defaults to five queued sockets. Concurrent browser assets
    # overflow that queue on Windows before handler threads can accept them.
    request_queue_size = 128


class Handler(SimpleHTTPRequestHandler):
    def handle_one_request(self):
        token = _request_accounts.set({})
        self._perf = None
        try:
            return super().handle_one_request()
        finally:
            if getattr(self,"_perf",None):
                request_performance.finish(*self._perf)
            _request_accounts.reset(token)

    def parse_request(self):
        parsed = super().parse_request()
        if parsed:
            self._perf = request_performance.start(self.command, self.path)
        return parsed

    def send_response(self, code, message=None):
        if getattr(self,"_perf",None):
            self._perf[0]["status"] = code
        return super().send_response(code, message)

    def send_header(self, keyword, value):
        if getattr(self,"_perf",None) and keyword.lower() == "content-length":
            self._perf[0]["responseSize"] = int(value)
        return super().send_header(keyword, value)

    def log_message(self, format, *args):
        from mahjong_api.logging_filters import redact_table_token as redact
        args = tuple(re.sub(r"(/api/discord/callback)\?[^ ]+", r"\1?[redacted]", v) if isinstance(v, str) else v for v in args)
        super().log_message(redact(format), *(redact(v) if isinstance(v, str) else v for v in args))

    def send_error(self, code, message=None, explain=None):
        # Reuse the generated legal copy for HTML errors outside the application
        # shell. The standard renderer still escapes messages, calculates the
        # final byte length, and omits the body for HEAD and bodyless statuses.
        if urlparse(getattr(self, "path", "")).path.startswith("/api/"):
            return super().send_error(code, message, explain)
        try:
            footer = (WEB_DIR / "footer.html").read_text(encoding="utf-8")
        except OSError:
            return super().send_error(code, message, explain)
        original = self.error_message_format
        self.error_message_format = original.replace("</body>", footer.replace("%", "%%") + "\n</body>")
        try:
            return super().send_error(code, message, explain)
        finally:
            self.error_message_format = original

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self):
        for name, value in request_performance.headers().items():
            self.send_header(name, value)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if urlparse(self.path).path == "/score" else "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cache-Control", "no-store" if getattr(self,"_application_document",False) or self.path.startswith(("/api/", "/score", "/sit")) else ("public, max-age=31536000, immutable" if self.path.startswith(("/avatars/","/dist/")) else "public, max-age=300"))
        super().end_headers()

    def guard_application_page(self):
        self._application_document = False
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        if path.lower() == "/index.html":
            path = "/index.html"
        query = parse_qs(parsed.query)
        if path == "/player-history":
            self._application_document = True
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        public = path in {"/login", "/register", "/auth/callback", "/discord/callback"}
        application = (path in {"/", "/index.html", "/registration-complete", "/reservations",
            "/manual-score", "/score", "/sit", "/account", "/admin", "/record", "/ranking", "/tournament"}
            or path.startswith(("/join/", "/join-table/", "/challenges/", "/tables/", "/tournaments/")))
        if not (public or application):
            return False
        self._application_document = True
        user = current_user(self)
        destination = None
        if path in {"/login", "/register"} and user:
            destination = "/"
        elif application and not user:
            destination = "/login?" + urlencode({"returnTo": account_registration.safe_return(self.path)})
        elif application and (path == "/admin" or (query.get("page") or [""])[0] == "admin") and not is_admin(user):
            self.send_error(403, "Administrator access required")
            return True
        if destination is None:
            return False
        self.send_response(302)
        self.send_header("Location", destination)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def do_GET(self):
        if self.guard_application_page():
            return
        import competition_http
        if competition_http.get(sys.modules[__name__], self):
            return
        if proxy_nfc_request(self):
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path.startswith("/avatars/"):
            from account_images import thumbnail
            match=re.fullmatch(r"/avatars/([a-f0-9]{64})\.webp",path)
            image=thumbnail(match[1],USERS_FILE,YAKUMAN_UPLOAD_DIR,MAHJONG_DB_FILE) if match else None
            if not image:
                self.send_error(404);return
            content=image.read_bytes();self.send_response(200)
            self.send_header("Content-Type","image/webp");self.send_header("Content-Length",str(len(content)))
            self.end_headers();self.wfile.write(content);return
        if self.account_get(path, query):
            return
        if path == "/api/public-player-history":
            response_json(self, {"ok": False, "code": "feature_removed"}, 410)
            return
        if path == "/api/dashboard":
            if not current_user(self):
                response_json(self, {"ok": False, "code": "not_authenticated"}, 401)
                return
            try:
                ranking_type = (query.get("ranking") or ["mmr"])[0]
                match_player = (query.get("match_player") or [""])[0]
                view_quarter = (query.get("quarter") or [""])[0]
                raw_table_players = (query.get("table_players") or [""])[0]
                profile_quarter = (query.get("profile_quarter") or [None])[0]
                profile_player = (query.get("profile_player") or [""])[0]
                if profile_quarter == "__total__":
                    profile_quarter = "Total games"
                table_players = [name.strip() for name in re.split(r"[,/]", raw_table_players) if name.strip()]
                response_json(self, build_dashboard(ranking_type=ranking_type, user=current_user(self), match_player=match_player, view_quarter=view_quarter, table_players=table_players, profile_quarter=profile_quarter, profile_player=profile_player))
            except Exception as error:
                print(f"Web dashboard: dashboard API failed: {error}")
                response_json(self, {"ok": False, "message": str(error), "rankings": [], "recent_games": [], "player_stats": []}, 500)
            return
        if path == "/api/match-candidates":
            try:
                raw_players = (query.get("players") or [""])[0]
                played_at = (query.get("played_at") or [""])[0]
                players = [name.strip() for name in re.split(r"[,/]", raw_players) if name.strip()]
                response_json(self, {"ok": True, "matches": sql_match_candidates(players, played_at=played_at, limit=20)})
            except Exception as error:
                response_json(self, {"ok": False, "message": str(error), "matches": []}, 500)
            return
        if path == "/api/annual-summary":
            try:
                username = current_user(self)
                if not username:
                    raise PermissionError("Please log in first.")
                school_year = (query.get("year") or [""])[0]
                response_json(self, {"ok": True, "summary": sql_annual_summary(username, school_year=school_year)})
            except Exception as error:
                response_json(self, {"ok": False, "message": str(error), "summary": None}, 500)
            return
        if path == "/api/admin/discord-score":
            username = current_user(self)
            if not username:
                response_json(self, {"ok": False, "code": "not_authenticated"}, 401)
            elif not is_admin(username):
                response_json(self, {"ok": False, "code": "admin_required"}, 403)
            else:
                try:
                    response_json(self, discord_score_state(username))
                except Exception:
                    _logger.exception("Discord score setting read failed")
                    response_json(self, {"ok": False, "code": "server_error"}, 500)
            return
        if path == "/api/admin/matches":
            try:
                username = current_user(self)
                if not username or not is_admin(username):
                    raise PermissionError("Only admins can view match management.")
                page = safe_int((query.get("page") or ["1"])[0]) or 1
                played_at = (query.get("date") or [""])[0]
                raw_players = (query.get("players") or [""])[0]
                players = [name.strip() for name in re.split(r"[,/]", raw_players) if name.strip()]
                response_json(self, {"ok": True, **sql_admin_game_rows(page=page, per_page=10, played_at=played_at, player_names=players)})
            except PermissionError as error:
                response_json(self, {"ok": False, "message": str(error), "rows": []}, 401)
            except Exception as error:
                response_json(self, {"ok": False, "message": str(error), "rows": []}, 500)
            return
        if path == "/api/admin/actions":
            try:
                username = current_user(self)
                if not username:
                    raise PermissionError("Log in before viewing admin actions.")
                limit = safe_int((query.get("limit") or ["30"])[0]) or 30
                response_json(self, admin_recent_actions(username, limit=limit))
            except PermissionError as error:
                response_json(self, {"ok": False, "message": str(error), "actions": []}, 401)
            except Exception as error:
                response_json(self, {"ok": False, "message": str(error), "actions": []}, 500)
            return
        if path == "/api/login-players":
            try:
                body = account_registration.search_players(
                    sys.modules[__name__], query=(query.get("q") or [""])[0],
                    cursor=(query.get("cursor") or [""])[0],
                    limit=(query.get("limit") or [10])[0], played_only=False)
                # Administrators use a separate password sign-in and are never
                # issued an ordinary member-selection session.
                body["users"] = [entry for entry in body.get("users", []) if not is_admin(entry["name"])]
                response_json(self, body)
            except ValueError as error:
                response_json(self, {"message": str(error), "users": [], "next_cursor": None}, 400)
            except Exception:
                response_json(self, {"message": "Player ID search is unavailable. Please retry.", "users": [], "next_cursor": None}, 503)
            return
        if path == "/api/registered-users":
            if not current_user(self):
                response_json(self, {"detail": {"code": "not_authenticated"}}, 401)
                return
            try:
                raw_ids = (query.get("ids") or [None])[0]
                body = registered_names.search_accounts(USERS_FILE,
                    query=(query.get("q") or [""])[0], cursor=(query.get("cursor") or [""])[0],
                    limit=(query.get("limit") or [10])[0],
                    ids=raw_ids.split(",") if raw_ids is not None else None)
                response_json(self, body)
            except ValueError as error:
                response_json(self, {"message": str(error), "users": [], "code": "invalid_search"}, 400)
            except Exception:
                response_json(self, {"message": "User search is unavailable. Please retry.", "users": [], "code": "search_unavailable"}, 503)
            return
        if path == "/api/admin/registered-name-conflicts":
            username = current_user(self)
            if not username or not is_admin(username):
                response_json(self, {"detail": {"code": "admin_required"}}, 403)
                return
            try:
                report = registered_names.ensure_directory(USERS_FILE)
                response_json(self, {"conflicts": [{"normalized_name": group["normalized_name"], "names": group["users"]}
                                                  for group in report["duplicates"]],
                    "unique_index_ready": report["unique_constraint"], "invalid": report["invalid"],
                    "account_count": report["account_count"]})
            except Exception:
                response_json(self, {"message": "The name report is unavailable. Please retry."}, 503)
            return
        if path == "/api/history-players":
            try:
                body = account_registration.search_players(
                    sys.modules[__name__], query=(query.get("q") or [""])[0],
                    cursor=(query.get("cursor") or [""])[0], limit=(query.get("limit") or [10])[0])
                for player in body["users"]:
                    player["id"] = "historical:" + player["display_id"]
                response_json(self, body)
            except ValueError as error:
                response_json(self, {"message": str(error), "users": [], "next_cursor": None}, 400)
            return
        if path == "/api/players":
            try:
                body = {"players": sheet_player_names(), "error": ""}
            except Exception as error:
                body = {"players": [], "error": str(error)}
            response_json(self, body)
            return
        if path == "/api/tournament-accounts":
            username = current_user(self)
            if not username or not is_admin(username):
                response_json(self, {"detail": {"code": "admin_required"}}, 403)
                return
            accounts = [{"id": stable_account_id(account.get("name", key)), "name": account.get("name", key)}
                        for key, account in users_data().get("users", {}).items()]
            response_json(self, {"accounts": accounts})
            return
        if path == "/api/session":
            try:
                response_json(self, {"user": current_user(self), "profile": current_user_profile(self)})
            except Exception as error:
                response_json(self, {"user": None, "profile": None, "error": str(error)})
            return
        if path == "/api/live-games":
            try:
                response_json(self, {"games": active_live_games()})
            except Exception as error:
                response_json(self, {"games": [], "error": str(error)})
            return
        if path == "/api/yakuman-options":
            response_json(self, {"options": YAKUMAN_OPTIONS})
            return
        if path.startswith("/uploads/yakuman/"):
            filename = Path(path.removeprefix("/uploads/yakuman/")).name
            if re.fullmatch(r"competition-[a-f0-9-]+-original\.(png|jpg|webp)",filename):
                self._application_document=True
                user=current_user(self)
                if not user or not is_admin(user):
                    self.send_error(403);return
            target = (YAKUMAN_UPLOAD_DIR / filename).resolve()
            if target.parent != YAKUMAN_UPLOAD_DIR.resolve() or not target.exists():
                self.send_error(404)
                return
            content = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path.startswith(("/challenges/", "/tables/", "/tournaments/")) or path in {"/", "/login", "/register", "/registration-complete", "/reservations", "/manual-score", "/account", "/admin", "/record", "/ranking", "/tournament"} or re.fullmatch(r"/(?:join-table|join)/[A-Za-z0-9_.-]+", path):
            self.path = "/index.html"
        elif is_blocked_static_path(path):
            self.send_error(403)
            return
        return super().do_GET()

    def account_get(self, path, query):
        if path not in {"/api/register/players", "/api/admin/account-claims", "/api/discord/callback", "/api/discord/config"}:
            return False
        try:
            if path == "/api/register/players":
                response_json(self, {"ok": False, "code": "feature_removed"}, 410)
            elif path == "/api/discord/config":
                response_json(self, {"available": account_discord.configured()})
            elif path == "/api/admin/account-claims":
                user = require_user(self)
                if not is_admin(user):
                    raise PermissionError("Only administrators can view claims.")
                response_json(self, {"claims": account_registration.claims(sys.modules[__name__])})
            else:
                state = (query.get("state") or [""])[0]
                if account_discord.is_admin_password_setup_state(state):
                    grant = account_discord.complete_admin_password_setup(
                        USERS_FILE, {k:v[0] for k,v in query.items()}, _admin_account)
                    secure = "; Secure" if request_scheme(self) == "https" or os.getenv("PUBLIC_SITE_URL", "").startswith("https://") else ""
                    self.send_response(302)
                    self.send_header("Location", "/login#admin-password-setup")
                    self.send_header("Set-Cookie", f"mahjong_admin_setup={grant}; Max-Age=600; HttpOnly; SameSite=Lax{secure}; Path=/api/admin/password-setup")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return True
                user = require_user(self)
                destination, linked = account_discord.complete(USERS_FILE, {k:v[0] for k,v in query.items()}, stable_account_id(user), session_cookie(self))
                from urllib.parse import urlencode
                self.send_response(302)
                self.send_header("Location", "/registration-complete?" + urlencode({"redirect_url":destination,"discord":"bound" if linked else "failed"}))
                self.end_headers()
        except (ValueError, PermissionError) as error:
            response_json(self, {"message": str(error), "code": getattr(error, "code", "invalid_request")}, 400)
        except Exception:
            logging.exception("Account API request failed")
            response_json(self, {"message": PUBLIC_REQUEST_ERROR, "code": "server_error"}, 500)
        return True

    def do_PUT(self):
        # Only the exact current-user seat route is forwarded; authentication
        # and same-origin checks remain in the existing API session bridge.
        if proxy_nfc_request(self):
            return
        self.send_error(404)

    def do_POST(self):
        import competition_http
        if competition_http.post(sys.modules[__name__], self):
            return
        if proxy_nfc_request(self):
            clear_sheet_cache()
            return
        path = urlparse(self.path).path
        if path in {"/api/register/claim", "/api/register/resume"}:
            response_json(self, {"ok": False, "code": "feature_removed"}, 410)
            return
        if path == "/api/record-game" and os.getenv("NFC_REPLACE_RECORDING", "true").lower() == "true":
            response_json(self, {"ok": False, "message": "请刷新网页，使用拍照登分或人工确认。", "score_url": "/score"}, 410)
            return
        if path not in {"/api/admin/account-claims/review", "/api/register/claim", "/api/register/resume", "/api/discord/start", "/api/admin/password-setup/start", "/api/admin/password-setup", "/api/record-game", "/api/register", "/api/login", "/api/logout", "/api/live-games", "/api/live-hands", "/api/profile/avatar", "/api/profile/discord-unbind", "/api/change-password", "/api/forgot-password", "/api/reset-password", "/api/quarter", "/api/admin/role", "/api/admin/discord-score", "/api/admin/password-reset", "/api/admin/account-delete", "/api/admin/player-create", "/api/admin/player-rename", "/api/admin/registered-name", "/api/admin/player-merge", "/api/admin/player-icon", "/api/admin/yakuman", "/api/admin/yakuman-update", "/api/admin/yakuman-delete", "/api/admin/yakuman-hard-delete", "/api/admin/yakuman-photo", "/api/admin/action-revert", "/api/revert"}:
            self.send_error(404)
            return

        try:
            enforce_rate_limit(self)
            if not same_origin_allowed(self):
                raise PermissionError("Request origin is not allowed.")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_JSON_BODY_BYTES or self.headers.get("Transfer-Encoding"):
                raise ValueError("Request body is too large.")
            raw_body = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw_body) if raw_body else {}
            if not isinstance(data, dict):
                raise ValueError("Request body must be a JSON object.")
            if path == "/api/register":
                name = account_registration.create_new(sys.modules[__name__], data)
                token, name = issue_session(self, stable_account_id(name))
                authenticated_response(self, token, {"ok": True, "user": name, "redirect_url": account_registration.safe_return(data.get("redirect_url"))})
                return
            elif path == "/api/admin/account-claims/review":
                body = account_registration.review(sys.modules[__name__], data, require_user(self))
            elif path == "/api/discord/start":
                user = require_verified_user(self)
                body = {"url": account_discord.start(stable_account_id(user), session_cookie(self), data.get("redirect_url"))}
            elif path == "/api/admin/password-setup/start":
                body = start_admin_password_setup(data)
            elif path == "/api/admin/password-setup":
                from http.cookies import SimpleCookie
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                grant = cookies["mahjong_admin_setup"].value if "mahjong_admin_setup" in cookies else ""
                token, name = set_admin_password_from_verified_setup(data, grant)
                response_body = json.dumps({"ok": True, "user": name, "redirect_url": "/"}, ensure_ascii=False).encode("utf-8")
                secure = "; Secure" if request_scheme(self) == "https" or os.getenv("PUBLIC_SITE_URL", "").startswith("https://") else ""
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"mahjong_session={token}{persistent_session_cookie_suffix(self)}")
                self.send_header("Set-Cookie", f"mahjong_admin_setup=; Max-Age=0; HttpOnly; SameSite=Lax{secure}; Path=/api/admin/password-setup")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
                return
            elif path == "/api/login":
                token, name = login_user(data)
                old = session_cookie(self)
                _sessions.pop(old, None); _session_account_ids.pop(old, None)
                if old and old != token:
                    registered_names.forget_session(USERS_FILE, old)
                body = {"ok": True, "user": name, "redirect_url": account_registration.safe_return(data.get("returnTo", data.get("redirect_url")))}
                payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"mahjong_session={token}{persistent_session_cookie_suffix(self)}")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            elif path == "/api/logout":
                user = current_user(self)
                cookie = self.headers.get("Cookie", "")
                for part in cookie.split(";"):
                    key, _, value = part.strip().partition("=")
                    if key == "mahjong_session":
                        _sessions.pop(value, None)
                        _session_account_ids.pop(value, None)
                        registered_names.forget_session(USERS_FILE, value)
                body = {"ok": True, "user": user}
                payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"mahjong_session=; Max-Age=0{secure_cookie_suffix(self)}")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            elif path == "/api/live-games":
                username = require_user(self)
                body = {"ok": True, "game": create_live_game(data, username)}
            elif path == "/api/live-hands":
                username = require_user(self)
                body = {"ok": True, "game": record_live_hand(data, username)}
            elif path == "/api/profile/avatar":
                username = require_verified_user(self)
                body = {"ok": True, "profile": update_user_avatar(username, data.get("avatar", ""))}
            elif path == "/api/profile/discord-unbind":
                username = require_verified_user(self)
                body = {"ok": True, "profile": unbind_discord_account(username), "message": "Discord account unbound."}
            elif path == "/api/change-password":
                username = require_verified_user(self)
                current_token = session_cookie(self)
                account_id = stable_account_id(username)
                change_password(username, data)
                for token, session_id in list(_session_account_ids.items()):
                    if session_id == account_id and token != current_token:
                        _sessions.pop(token, None)
                        _session_account_ids.pop(token, None)
                registered_names.revoke_sessions(USERS_FILE, account_id)
                if current_token:
                    registered_names.remember_session(
                        USERS_FILE, current_token, account_id,
                        int(time.time()) + SESSION_MAX_AGE_SECONDS)
                body = {"ok": True, "message": "Password updated."}
            elif path == "/api/forgot-password":
                body = request_password_reset(data)
            elif path == "/api/reset-password":
                body = redeem_password_reset(data)
            elif path == "/api/quarter":
                username = require_user(self)
                body = change_current_quarter(data, username)
            elif path == "/api/admin/role":
                username = require_user(self)
                body = update_user_role(data, username)
            elif path == "/api/admin/discord-score":
                username = require_user(self)
                body = update_discord_score_state(data, username)
            elif path == "/api/admin/password-reset":
                username = require_user(self)
                body = reset_user_password(data, username)
            elif path == "/api/admin/account-delete":
                username = require_user(self)
                body = delete_user_account(data, username)
            elif path == "/api/admin/player-create":
                username = require_user(self)
                body = admin_create_player(data, username)
            elif path == "/api/admin/registered-name":
                username = require_user(self)
                body = admin_registered_name(data, username)
            elif path == "/api/admin/player-rename":
                username = require_user(self)
                body = admin_rename_player(data, username)
            elif path == "/api/admin/player-merge":
                username = require_user(self)
                body = admin_merge_players(data, username)
            elif path == "/api/admin/player-icon":
                username = require_user(self)
                body = admin_player_icon(data, username)
            elif path == "/api/admin/yakuman":
                username = require_user(self)
                body = add_admin_yakuman(data, username)
            elif path == "/api/admin/yakuman-update":
                username = require_user(self)
                body = update_admin_yakuman(data, username)
            elif path == "/api/admin/yakuman-delete":
                username = require_user(self)
                body = delete_admin_yakuman(data, username)
            elif path == "/api/admin/yakuman-hard-delete":
                username = require_user(self)
                body = hard_delete_yakuman_by_display(data, username)
            elif path == "/api/admin/yakuman-photo":
                username = require_user(self)
                body = update_admin_yakuman_photo(data, username)
            elif path == "/api/admin/action-revert":
                username = require_user(self)
                body = revert_admin_action(data, username)
            elif path == "/api/revert":
                username = require_user(self)
                body = revert_web_record(data, username)
            else:
                username = require_user(self)
                data["recorder"] = username
                body = append_game_record(data)
            status = 200
        except ValueError as error:
            body = {"ok": False, "message": str(error), "code": getattr(error, "code", "invalid_request")}
            status = 400
        except PermissionError as error:
            body = {"ok": False, "message": str(error), "code": "request_denied"}
            status = 403 if current_user(self) else 401
        except Exception as error:
            _logger.exception("Website write request failed")
            body = {"ok": False, "message": PUBLIC_REQUEST_ERROR, "code": "server_error"}
            status = 500

        if path in {"/api/login", "/api/register"}:
            # Record failure categories only, never passwords, cookies or body data.
            self.log_message("account_request path=%s status=%s code=%s", path, status, body.get("code", "ok"))
        response_json(self, body, status)


def main():
    parser = argparse.ArgumentParser(description="Run the Mahjong club web dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()

    # Complete interrupted name publications before accepting requests.
    registered_names.ensure_directory(USERS_FILE)
    account_registration.initialize(sys.modules[__name__])
    recover_confirmed_player_merge_accounts()
    account_registration.sync_historical_accounts(sys.modules[__name__])
    cleared_admin_passwords = prepare_admin_password_setup()
    if cleared_admin_passwords:
        print(f"Enabled self-service password setup for {cleared_admin_passwords} linked administrator account(s).")
    import competition_http
    competition_http.service(sys.modules[__name__]).start_worker()
    server = WebHTTPServer((args.host, args.port), Handler)
    print(f"Mahjong club web dashboard: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
