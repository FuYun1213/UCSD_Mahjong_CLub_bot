"""Durable server-to-server adapters. Secrets are read only from server environment or a private server file.

ADAPTER CONTRACT: change METHOD, build_payload(), headers(), success() and
error_code() for a new provider. Retries MUST keep the saved endpoint and body.
NARTS cannot update/delete matches or consume finals hand deltas.
"""
import ipaddress
import json
import os
import socket
import threading
import tempfile
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from pathlib import Path

import requests
import request_performance as perf
from sqlalchemy import select
from .database_models import Metadata
from .store import Conflict, now
from .tournament_models import ExternalDelivery, TournamentAudit

METHOD = "POST"
_send_lock = threading.RLock()


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def audit(db, tournament_id, actor, action, details):
    db.add(TournamentAudit(tournament_id=tournament_id or "", actor_id=str(actor or ""),
        created_at=now(), action=action, detail_json=dump(details)))



def server_key(adapter):
    """An explicit private file supports SSH-only rotation without a restart.
    Never return the key from HTTP endpoints, logs, audit records or exceptions.
    """
    if adapter == "narts":
        filename = os.getenv("NARTS_EXTERNAL_API_KEY_FILE", "").strip()
        if filename:
            try:
                with Path(filename).open("r", encoding="utf-8") as source:
                    value = source.read(4097).strip()
                if value and len(value) <= 4096 and not any(c.isspace() for c in value):
                    return value
            except (OSError, UnicodeError):
                pass
    return os.getenv("NARTS_EXTERNAL_API_KEY" if adapter == "narts" else "EXTERNAL_API_KEY", "").strip()



def validate_private_key(value):
    """NARTS keys are opaque: its contract specifies no prefix or minimum length.
    Only enforce our storage bound and safe single-token HTTP header transport.
    The provider, not a guessed local key pattern, determines whether it is valid.
    Preserve token case and characters exactly, apart from surrounding whitespace.
    """
    if not isinstance(value, str) or not value.strip():
        raise Conflict("invalid_api_key", "invalid_api_key")
    key = value.strip()
    if len(key) > 4096:
        raise Conflict("api_key_too_long", "api_key_too_long")
    if any(not 33 <= ord(c) <= 126 for c in key):
        raise Conflict("api_key_invalid_characters", "api_key_invalid_characters")
    return key


def _replace_private_file(target, content):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".narts-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            if hasattr(os, "fchmod"):
                os.fchmod(output.fileno(), 0o600)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def private_key_update(value):
    """Write-only rotation. Restore the previous secret if the DB commit fails.
    Neither the secret nor filesystem/driver exception text crosses the API.
    """
    if value is None:
        yield
        return
    filename = os.getenv("NARTS_EXTERNAL_API_KEY_FILE", "").strip()
    if not filename:
        raise Conflict("private_file_not_configured", "private_file_not_configured")
    target = Path(filename)
    try:
        previous = target.read_bytes() if target.exists() else None
        _replace_private_file(target, value.encode("utf-8"))
    except OSError:
        raise Conflict("key_storage_error", "key_storage_error") from None
    try:
        yield
    except BaseException:
        try:
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                _replace_private_file(target, previous)
        except OSError:
            raise Conflict("key_rollback_failed", "key_rollback_failed") from None
        raise

def config_in(db):
    row = db.get(Metadata, "external_api_v1")
    return json.loads(row.value) if row else {
        "enabled": bool(server_key("narts") and os.getenv("NARTS_EXTERNAL_API_ENDPOINT")),
        "endpoint": os.getenv("NARTS_EXTERNAL_API_ENDPOINT", ""), "adapter": "narts", "last_test": None}


def validate_endpoint(endpoint, resolve=False):
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.query or len(endpoint) > 2048):
        raise Conflict("invalid_endpoint", "invalid_endpoint")
    if parsed.hostname.lower() in {"localhost", "metadata.google.internal"}:
        raise Conflict("invalid_endpoint", "invalid_endpoint")
    try:
        addresses = [ipaddress.ip_address(parsed.hostname)]
    except ValueError:
        addresses = []
    if resolve:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)]
        except OSError:
            raise Conflict("network_error", "network_error") from None
    if any(not address.is_global for address in addresses):
        raise Conflict("invalid_endpoint", "invalid_endpoint")
    return endpoint


def headers(adapter):
    key = server_key(adapter)
    if adapter == "narts" and not key:
        raise Conflict("missing_api_key", "missing_api_key")
    return {"Content-Type": "application/json", **({"Authorization": "Bearer " + key} if key else {})}


def build_payload(canonical, adapter):
    if adapter == "json":
        return canonical
    players = canonical["players"]
    if canonical.get("kind") != "match" or len(players) != 4:
        raise Conflict("narts_unsupported", "narts_unsupported")
    if any(type(p.get("rawScore")) is not int or not -100000 <= p["rawScore"] <= 200000
           or not 1 <= len(p["name"]) <= 30 for p in players) or sum(p["rawScore"] for p in players) != 100000:
        raise Conflict("narts_invalid_scores", "narts_invalid_scores")
    return {"idempotencyKey": canonical["requestId"], "playedAt": canonical["submittedAt"],
        "players": [{"sourcePlayerId": p["id"], "username": p["name"],
                     "rawScore": p["rawScore"], "seatWind": p["seat"]} for p in players]}


def success(status, body, adapter):
    if adapter == "json":
        return 200 <= status < 300 and body.get("ok", True) is not False and body.get("success", True) is not False
    return status in (200, 201) and bool(body.get("matchId") or body.get("match", {}).get("id"))


def error_code(status, body):
    # Never echo remote bodies: they can contain credentials, HTML, or private data.
    return {400: "external_validation", 401: "external_auth", 403: "external_forbidden",
            429: "external_rate_limit"}.get(status, "external_server" if status >= 500 else "external_response")


def queue_delivery(db, canonical, actor=""):
    key = canonical["requestId"]
    previous = db.get(ExternalDelivery, key)
    if previous:
        if previous.canonical_json != dump(canonical):
            raise Conflict("submission_conflict", "submission_conflict")
        return previous
    config = config_in(db)
    status, error, payload = ("pending" if config["enabled"] else "disabled"), "", {}
    try:
        payload = build_payload(canonical, config["adapter"])
    except Conflict as exc:
        status, error = "unsupported", exc.detail["code"]
    row = ExternalDelivery(id=key, tournament_id=canonical.get("tournamentId") or "", actor_id=str(actor or ""),
        canonical_json=dump(canonical), payload_json=dump(payload), endpoint=config["endpoint"],
        adapter=config["adapter"], status=status, error_code=error, attempts=0, updated_at=now(), response_json="{}")
    db.add(row)
    return row


def public_delivery(row):
    return {"request_id": row.id, "status": row.status, "error_code": row.error_code,
            "attempts": row.attempts, "updated_at": row.updated_at, "response": json.loads(row.response_json)}


class ExternalSync:
    def __init__(self, store, transport=None):
        self.store, self.transport = store, transport

    def config(self):
        with self.store.connect() as db:
            result = config_in(db)
            result["key_configured"] = bool(server_key(result["adapter"]))
            return result

    def save_config(self, data, actor):
        endpoint = str(data.get("endpoint", "")).strip()
        adapter = data.get("adapter", "narts")
        if adapter not in {"narts", "json"} or type(data.get("enabled")) is not bool:
            raise Conflict("invalid_config", "invalid_config")
        if endpoint:
            validate_endpoint(endpoint)
        if data["enabled"] and not endpoint:
            raise Conflict("invalid_endpoint", "invalid_endpoint")
        value = data.get("api_key")
        key = None
        if value not in (None, ""):
            if adapter != "narts":
                raise Conflict("invalid_config", "invalid_config")
            key = validate_private_key(value)
        # Same process lock as delivery sending: never send with half-updated settings.
        with _send_lock:
            try:
                with private_key_update(key), self.store.connect() as db:
                    config = {"endpoint": endpoint, "enabled": data["enabled"], "adapter": adapter,
                              "last_test": None, "saved_at": now()}
                    db.merge(Metadata(key="external_api_v1", value=dump(config)))
                    audit(db, "", actor, "api_config", {"enabled": data["enabled"], "adapter": adapter})
                    if key is not None:
                        audit(db, "", actor, "api_key_configured", {"configured": True})
            except Conflict:
                raise
            except Exception:
                raise Conflict("config_save_failed", "config_save_failed") from None
            return self.config()

    def request(self, endpoint, adapter, payload=None, method=METHOD):
        # HTTP callers contribute to their request. The background worker has no
        # request context, so create a fixed-label metric without endpoint/body/ID.
        metric, token = (None, None)
        if perf.current.get() is None:
            metric, token = perf.start("WORKER", "/internal/narts-request" if adapter == "narts" else "/internal/external-request")
        try:
            stage = perf.measure("nartsDurationMs", "nartsCallCount") if adapter == "narts" else nullcontext()
            with stage:
                status, body = self._request(endpoint, adapter, payload, method)
            if metric is not None:
                metric["status"] = status
            return status, body
        finally:
            if metric is not None:
                perf.finish(metric, token)

    def _request(self, endpoint, adapter, payload=None, method=METHOD):
        if self.transport:
            return self.transport(endpoint, adapter, payload, method)
        validate_endpoint(endpoint, resolve=True)
        with requests.Session() as session:
            session.trust_env = False
            with session.request(method, endpoint, headers=headers(adapter), json=payload,
                    timeout=(5, 12), allow_redirects=False, stream=True) as response:
                chunks, size = [], 0
                for chunk in response.iter_content(8192):
                    size += len(chunk)
                    if size > 131072:
                        raise Conflict("external_response", "external_response")
                    chunks.append(chunk)
                try:
                    body = json.loads(b"".join(chunks)) if chunks else {}
                except ValueError:
                    body = {}
                return response.status_code, body if isinstance(body, dict) else {}

    def test(self, actor):
        config = self.config()
        try:
            status, _ = self.request(config["endpoint"], config["adapter"], method="HEAD")
            code = "reachable_unverified" if status < 400 or status == 405 else error_code(status, {})
        except Conflict as exc:
            code = exc.detail["code"]
        except (requests.RequestException, OSError, ValueError):
            code = "network_error"
        result = {"code": code, "at": now()}
        with self.store.connect() as db:
            current = config_in(db)
            if all(current[k] == config[k] for k in ("endpoint", "adapter", "enabled")):
                current["last_test"] = result
                db.merge(Metadata(key="external_api_v1", value=dump(current)))
            audit(db, "", actor, "api_test", result)
        return result

    def get(self, key):
        with self.store.connect() as db:
            row = db.get(ExternalDelivery, key)
            return public_delivery(row) if row else None

    def list(self, tournament_id=None, limit=100):
        with self.store.connect() as db:
            query = select(ExternalDelivery).order_by(ExternalDelivery.updated_at.desc()).limit(limit)
            if tournament_id is not None:
                query = query.where(ExternalDelivery.tournament_id == tournament_id)
            return [public_delivery(row) for row in db.scalars(query)]

    def schedule_retry(self, key, actor=""):
        """Only queue the existing frozen request; never send on an interactive path."""
        with self.store.connect() as db:
            row = db.get(ExternalDelivery, key)
            if not row:
                raise Conflict("not_found", "not_found")
            if row.status == "failed":
                row.status, row.updated_at = "pending", now()
                audit(db, row.tournament_id, actor or row.actor_id, "external_retry_queued",
                      {"request_id": key, "attempt": row.attempts})
            return public_delivery(row)

    def send(self, key, actor="", retry=False):
        with _send_lock:
            with self.store.connect() as db:
                row = db.get(ExternalDelivery, key)
                if not row:
                    raise Conflict("not_found", "not_found")
                if row.status in {"success", "unsupported", "disabled", "manual_review", "cancelled"}:
                    return public_delivery(row)
                if not config_in(db)["enabled"] or row.status == "failed" and not retry:
                    return public_delivery(row)
                if row.status == "sending" and row.updated_at > (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat():
                    return public_delivery(row)
                row.status, row.updated_at = "sending", now()
                row.attempts += 1
                endpoint, adapter, payload = row.endpoint, row.adapter, json.loads(row.payload_json)
                audit(db, row.tournament_id, actor or row.actor_id, "external_retry" if retry else "external_sync",
                      {"request_id": key, "attempt": row.attempts})
            # Local score and queue have committed before network I/O.
            try:
                status, body = self.request(endpoint, adapter, payload)
                ok = success(status, body, adapter)
                code = "" if ok else error_code(status, body)
                safe = {"match_id": str(body.get("matchId") or body.get("match", {}).get("id") or "")[:128],
                        "playerMappings": [{k: str(p.get(k, ""))[:128] for k in ("sourcePlayerId", "inputName", "outputName", "renamed")}
                            for p in body.get("playerMappings", [])[:4] if isinstance(p, dict)]} if ok else {}
            except Conflict as exc:
                ok, code, safe = False, exc.detail["code"], {}
            except (requests.RequestException, OSError, ValueError, TypeError):
                ok, code, safe = False, "network_error", {}
            with self.store.connect() as db:
                row = db.get(ExternalDelivery, key)
                # A simultaneous correction can mark the delivery for manual reconciliation.
                if row.status == "sending":
                    row.status, row.error_code = "success" if ok else "failed", code
                row.updated_at, row.response_json = now(), dump(safe)
                audit(db, row.tournament_id, actor or row.actor_id, "external_result",
                      {"request_id": key, "status": row.status, "error_code": row.error_code})
                return public_delivery(row)

    def flush(self):
        with self.store.connect() as db:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
            keys = list(db.scalars(select(ExternalDelivery.id).where(
                (ExternalDelivery.status == "pending") | ((ExternalDelivery.status == "sending") & (ExternalDelivery.updated_at < cutoff))).limit(10)))
        for key in keys:
            self.send(key)


def queue_free_match(db, result):
    from .database_models import MatchPlayer
    from .manual_score_models import ManualScoreDraft, ManualScorePlayer
    from sqlalchemy import func
    players = list(result["players"].items())
    ordered = sorted(players, key=lambda item: -item[1]["final_points"])
    rank = {seat: i + 1 for i, (seat, _) in enumerate(ordered)}
    canonical = {"schemaVersion": 1, "kind": "match", "requestId": "nfc-" + result["match_id"],
        "tournamentId": None, "roundId": str(result["round"]) if result["round"] is not None else None, "tableNumber": result["table"],
        "matchId": result["match_id"], "submittedAt": result["played_at"], "players": []}
    for seat, player in players:
        uid = str(player["user"]["id"])
        total = db.scalar(select(func.sum(MatchPlayer.delta_points)).where(MatchPlayer.user_id == uid)) or 0
        # Table-linked manual scores are already in MatchPlayer. Only generic
        # confirmed manual games contribute through their explicit user/wind rows.
        # Read the stored delta so a historical custom initial-point rule remains
        # correct when the current configuration changes.
        manual = db.execute(select(ManualScoreDraft.result_json, ManualScorePlayer.seat)
            .join(ManualScorePlayer, ManualScorePlayer.draft_id == ManualScoreDraft.id)
            .where(ManualScoreDraft.table_id.is_(None), ManualScoreDraft.status == "submitted",
                   ManualScorePlayer.user_id == uid))
        total += sum(json.loads(snapshot)["players"][wind]["delta_points"] for snapshot, wind in manual)
        canonical["players"].append({"id": uid, "name": player["user"]["name"], "seat": seat[0].upper(),
            "placement": rank[seat], "rawScore": player["final_points"], "placementPoints": 0,
            "gameScore": player["net_score"], "cumulativeScore": total / 1000})
    queue_delivery(db, canonical, result.get("uploader_id"))
