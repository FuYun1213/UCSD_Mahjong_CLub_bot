"""Post a completed web-table score summary to the existing game-record channel."""
import json
import logging
import os
from pathlib import Path
import threading
import sqlite3
import time
import urllib.error
import urllib.request


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GUILD_ID = "1278056421224747162"
DEFAULT_CHANNEL_NAME = "game-record"


def _token():
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if token:
        return token
    token_file = Path(os.getenv("DISCORD_BOT_TOKEN_FILE", str(ROOT / "DISCORD_BOT_TOKEN.env")))
    try:
        for line in token_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "DISCORD_BOT_TOKEN":
                return value.strip()
    except OSError:
        pass
    return ""


def _request(token, method, path, payload=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bot {token}", "User-Agent": "UCSD-Mahjong-Web (local)"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request("https://discord.com/api/v10" + path, data=body,
                                     headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=12) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else None


def _channel_id(token):
    configured = os.getenv("DISCORD_GAME_RECORD_CHANNEL_ID", "").strip()
    if configured:
        return configured
    guild_id = os.getenv("DISCORD_GUILD_ID", DEFAULT_GUILD_ID)
    channel_name = os.getenv("DISCORD_GAME_RECORD_CHANNEL_NAME", DEFAULT_CHANNEL_NAME)
    channels = _request(token, "GET", f"/guilds/{guild_id}/channels")
    for channel in channels or []:
        if channel.get("name") == channel_name and channel.get("type") == 0:
            return channel["id"]
    raise RuntimeError("game_record_channel_missing")


def _embed(result, database_path=None, timeout=90):
    """Wait for the club calculation; publish its immutable original summary."""
    path = Path(database_path or os.getenv("NFC_CLUB_DATABASE_PATH") or
                os.getenv("MAHJONG_DB_FILE") or ROOT / "mahjong.sqlite3").resolve()
    deadline = time.monotonic() + timeout
    while True:
        try:
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
                row = db.execute("SELECT s.payload_json FROM game_score_summaries s "
                    "JOIN games g ON g.id=s.game_id WHERE g.nfc_match_id=?",
                    (result.get("match_id"),)).fetchone()
            if row:
                return json.loads(row[0])
        except sqlite3.OperationalError:
            pass  # The independent history worker may not have imported it yet.
        if time.monotonic() >= deadline:
            raise RuntimeError("club_score_summary_not_ready")
        time.sleep(0.5)


def _send(result, token):
    embed = _embed(result)
    channel_id = _channel_id(token)
    _request(token, "POST", f"/channels/{channel_id}/messages", {
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    })


def schedule_score_notification(result):
    """Send outside the score transaction so Discord latency never delays saving."""
    if os.getenv("DISCORD_SCORE_NOTIFICATIONS_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return False
    token = _token()
    if not token:
        return False

    def send():
        try:
            _send(result, token)
        except urllib.error.HTTPError as error:
            logger.warning("Discord score notification failed (HTTP %s)", error.code)
        except Exception as error:
            logger.warning("Discord score notification failed (%s)", type(error).__name__)

    threading.Thread(target=send, name="discord-score-notification", daemon=True).start()
    return True
