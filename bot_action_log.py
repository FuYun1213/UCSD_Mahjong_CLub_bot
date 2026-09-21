import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


ACTION_LOG_FILE = "bot_action_log.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_entries() -> List[Dict[str, Any]]:
    if not os.path.exists(ACTION_LOG_FILE):
        return []

    try:
        with open(ACTION_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_entries(entries: List[Dict[str, Any]]) -> None:
    directory = os.path.dirname(os.path.abspath(ACTION_LOG_FILE)) or "."
    fd, temp_path = tempfile.mkstemp(prefix="bot_action_log_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, ACTION_LOG_FILE)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def record_action(
    *,
    user_id: int,
    user_name: str,
    action_type: str,
    summary: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    entries = _read_entries()
    entry = {
        "id": uuid.uuid4().hex,
        "created_at": utc_now_iso(),
        "user_id": str(user_id),
        "user_name": user_name,
        "action_type": action_type,
        "summary": summary,
        "payload": payload,
        "reverted_at": None,
        "reverted_by": None,
    }
    entries.append(entry)
    _write_entries(entries)
    return entry


def get_recent_actions_for_user(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    user_id_str = str(user_id)
    entries = [
        entry
        for entry in _read_entries()
        if entry.get("user_id") == user_id_str and not entry.get("reverted_at")
    ]
    entries.sort(key=lambda entry: entry.get("created_at", ""), reverse=True)
    return entries[:limit]


def get_recent_actions(limit: int = 25) -> List[Dict[str, Any]]:
    entries = _read_entries()
    entries.sort(key=lambda entry: entry.get("created_at", ""), reverse=True)
    return entries[: max(1, int(limit or 25))]


def get_action(action_id: str) -> Optional[Dict[str, Any]]:
    for entry in _read_entries():
        if entry.get("id") == action_id:
            return entry
    return None


def mark_reverted(action_id: str, reverted_by: int) -> Optional[Dict[str, Any]]:
    entries = _read_entries()
    for entry in entries:
        if entry.get("id") == action_id:
            entry["reverted_at"] = utc_now_iso()
            entry["reverted_by"] = str(reverted_by)
            _write_entries(entries)
            return entry
    return None
