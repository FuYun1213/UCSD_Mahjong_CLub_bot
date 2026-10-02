"""Discord REST sender with explicit mention policy and conservative recovery.

Official contract: nonce uniqueness is only checked for the past few minutes.
https://docs.discord.com/developers/resources/message#create-message
Unknown POST outcomes therefore never cause an automatic second POST.
"""
import json
import http.client
import socket
import threading
import math
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .discord_reminder_config import discord_id


class DiscordReminderError(Exception):
    def __init__(self, code, *, retryable=False, retry_after=None, uncertain=False):
        self.code, self.retryable, self.retry_after, self.uncertain = code, retryable, retry_after, uncertain
        super().__init__(code)


def safe_registered_name(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = " ".join("".join(c for c in value if unicodedata.category(c) not in {"Cc","Cf","Cs"}).split())[:128]
    value = value.replace("@", "＠").replace("<", "＜").replace(">", "＞")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~])", r"\\\1", value) or "Registered player"


def build_message(*, table_number, start_at, end_at, capacity, participants, nonce):
    people = {str(person["id"]): person for person in participants}
    permitted, lines = [], []
    for person in people.values():
        bound = discord_id(person.get("discord_id"))
        if bound:
            lines.append("• <@" + bound + ">")
            if bound not in permitted:
                permitted.append(bound)
        else:
            lines.append("• " + safe_registered_name(person.get("name")))
    start = int(datetime.fromisoformat(start_at).timestamp())
    end = int(datetime.fromisoformat(end_at).timestamp())
    content = ("🀄 Mahjong Reservation Reminder\n\nTable: Table " + str(int(table_number)) +
        f"\nTime: <t:{start}:F> – <t:{end}:F>\nStarts: <t:{start}:R>\n\nPlayers:\n" +
        "\n".join(lines) + "\n\nPlease arrive on time.")
    missing = max(0, int(capacity) - len(people))
    if missing:
        noun = "player" if missing == 1 else "players"
        content += f"\n\n⚠️ We still need {missing} more {noun} for this table.\nPlease reserve on the website if you can join."
    else:
        content += "\n\nAll seats are reserved."
    if len(content.encode("utf-16-le")) // 2 > 2000 or len(permitted) > 100:
        raise DiscordReminderError("message_too_large")
    return {"content": content, "nonce": nonce, "enforce_nonce": True,
            "allowed_mentions": {"parse": [], "users": permitted, "roles": [], "replied_user": False}}


def _seconds(value):
    try:
        number = float(value)
        return max(1.0, number) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


class DiscordReminderSender:
    def __init__(self, config, opener=None, connection_factory=None, deadline_seconds=5):
        self.config = config
        self._open = opener or urllib.request.urlopen
        self.deadline_seconds = max(.01, min(float(deadline_seconds), 5))
        # Injected openers remain a unit-test transport. Production preconnects
        # outside the database gate; the final POST cannot perform DNS/TLS work.
        self._connection_factory = connection_factory or (
            (lambda: http.client.HTTPSConnection("discord.com", timeout=8)) if opener is None else None)

    def _request(self, method, path, payload=None):
        request = urllib.request.Request("https://discord.com/api/v10" + path,
            data=json.dumps(payload,ensure_ascii=False).encode("utf-8") if payload is not None else None,
            headers={"Authorization":"Bot " + self.config.token,
                     "Content-Type":"application/json", "User-Agent":"DiscordBot (https://doramj.org, 1.0)"}, method=method)
        try:
            with self._open(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            status = error.code
            retry = _seconds(error.headers.get("Retry-After"))
            if status == 429:
                try:
                    retry = _seconds(json.loads(error.read().decode("utf-8")).get("retry_after")) or retry
                except (ValueError, UnicodeError, AttributeError):
                    pass
                raise DiscordReminderError("rate_limited",retryable=True,retry_after=retry or 60) from None
            if status >= 500:
                raise DiscordReminderError("discord_server_error", retryable=True, uncertain=method=="POST") from None
            codes = {401:"invalid_bot_token",403:"missing_channel_permissions",404:"channel_not_found"}
            raise DiscordReminderError(codes.get(status,"discord_request_rejected")) from None
        except (OSError, ValueError, UnicodeError):
            # A lost response may follow an accepted POST. Never assume absence.
            raise DiscordReminderError("discord_network_error",retryable=True,uncertain=method=="POST") from None

    def prepare(self):
        if not self.config.enabled:
            raise DiscordReminderError("reminders_disabled",retryable=True,retry_after=60)
        if not self.config.configured:
            raise DiscordReminderError("missing_configuration",retryable=True,retry_after=60)
        channel = self._request("GET", "/channels/" + self.config.channel_id)
        if str(channel.get("guild_id")) != self.config.guild_id:
            raise DiscordReminderError("channel_guild_mismatch")
        if channel.get("type") not in {0,5}:
            raise DiscordReminderError("unsupported_channel_type")
        me = self._request("GET", "/users/@me")
        bot_id = discord_id(me.get("id"))
        if not bot_id or not me.get("bot"):
            raise DiscordReminderError("invalid_bot_identity")
        member = self._request("GET", f"/guilds/{self.config.guild_id}/members/{bot_id}")
        roles = self._request("GET", f"/guilds/{self.config.guild_id}/roles")
        selected = {self.config.guild_id, *map(str, member.get("roles", []))}
        permissions = 0
        for role in roles:
            if str(role.get("id")) in selected:
                permissions |= int(role.get("permissions", 0))
        if not permissions & 8:  # Administrator bypasses channel overwrites.
            overwrites = channel.get("permission_overwrites", [])
            for overwrite in overwrites:
                if str(overwrite.get("id")) == self.config.guild_id:
                    permissions = (permissions & ~int(overwrite.get("deny",0))) | int(overwrite.get("allow",0))
            deny, allow = 0, 0
            for overwrite in overwrites:
                if overwrite.get("type") == 0 and str(overwrite.get("id")) in selected - {self.config.guild_id}:
                    deny |= int(overwrite.get("deny",0)); allow |= int(overwrite.get("allow",0))
            permissions = (permissions & ~deny) | allow
            for overwrite in overwrites:
                if overwrite.get("type") == 1 and str(overwrite.get("id")) == bot_id:
                    permissions = (permissions & ~int(overwrite.get("deny",0))) | int(overwrite.get("allow",0))
            if permissions & (1024 | 2048) != (1024 | 2048):
                raise DiscordReminderError("missing_channel_permissions")
        destination = {"channel_id":self.config.channel_id, "bot_user_id":bot_id}
        if self._connection_factory is not None:
            connection = self._connection_factory()
            try:
                connection.connect()
                connection.auto_open = 0  # Never reconnect while holding the DB gate.
            except (OSError, http.client.HTTPException):
                connection.close()
                raise DiscordReminderError("discord_connect_error",retryable=True) from None
            destination["_connection"] = connection
        return destination

    def _post_connected(self, connection, channel_id, payload):
        """Hard wall-clock POST deadline, including a slow streaming response.

        The watchdog only shuts down this already-connected socket. HTTP I/O
        stays on the calling thread, so no background send survives cancellation.
        The production five-second budget is below Store's 30-second busy wait.
        """
        sock = connection.sock
        if sock is None:
            raise DiscordReminderError("discord_transport_not_prepared",retryable=True)
        expired = threading.Event()
        def abort():
            expired.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        timer = threading.Timer(self.deadline_seconds, abort)
        timer.daemon = True
        sock.settimeout(self.deadline_seconds)
        timer.start()
        try:
            connection.request("POST", "/api/v10/channels/" + channel_id + "/messages",
                body=json.dumps(payload,ensure_ascii=False).encode("utf-8"),
                headers={"Authorization":"Bot " + self.config.token,"Content-Type":"application/json",
                         "User-Agent":"DiscordBot (https://doramj.org, 1.0)"})
            response = connection.getresponse()
            raw = response.read(65537)
            if expired.is_set():
                raise DiscordReminderError("discord_send_deadline",retryable=True,uncertain=True)
            if len(raw)>65536:
                raise DiscordReminderError("discord_response_too_large",uncertain=True)
            if response.status==429:
                retry=_seconds(response.getheader("Retry-After"))
                try:
                    retry=_seconds(json.loads(raw).get("retry_after")) or retry
                except (ValueError,AttributeError):
                    pass
                raise DiscordReminderError("rate_limited",retryable=True,retry_after=retry or 60)
            if response.status>=500:
                raise DiscordReminderError("discord_server_error",retryable=True,uncertain=True)
            if not 200<=response.status<300:
                codes={401:"invalid_bot_token",403:"missing_channel_permissions",404:"channel_not_found"}
                raise DiscordReminderError(codes.get(response.status,"discord_request_rejected"))
            return json.loads(raw)
        except (OSError,http.client.HTTPException,ValueError):
            code="discord_send_deadline" if expired.is_set() else "discord_network_error"
            raise DiscordReminderError(code,retryable=True,uncertain=True) from None
        finally:
            timer.cancel()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def send(self, destination, payload):
        if self._connection_factory is not None:
            connection=destination.get("_connection")
            if connection is None:
                raise DiscordReminderError("discord_transport_not_prepared",retryable=True)
            result=self._post_connected(connection,destination["channel_id"],payload)
        else:
            result = self._request("POST", "/channels/" + destination["channel_id"] + "/messages", payload)
        message_id = discord_id(result.get("id"))
        if not message_id:
            raise DiscordReminderError("invalid_message_response",uncertain=True)
        return message_id

    def edit(self, destination, message_id, payload):
        """Idempotent content update; edits carry no allowed user mentions."""
        channel_id = discord_id(destination.get("channel_id"))
        message_id = discord_id(message_id)
        if not channel_id or not message_id:
            raise DiscordReminderError("invalid_message_id")
        value = {key: item for key, item in payload.items()
                 if key not in {"nonce", "enforce_nonce"}}
        value["allowed_mentions"] = {"parse": [], "users": [],
                                     "roles": [], "replied_user": False}
        result = self._request("PATCH", "/channels/" + channel_id +
                               "/messages/" + message_id, value)
        if discord_id(result.get("id")) != message_id:
            raise DiscordReminderError("invalid_message_response")
        return message_id

    def reconcile(self, channel_id, bot_user_id, nonce, since):
        """Only positive, bot-owned nonce evidence is accepted; absence is unknown.

        Discord can omit history when READ_MESSAGE_HISTORY is missing and nonce
        is optional on message objects. An empty/missing result never permits a
        resend. Bounded scans avoid unbounded API load after long downtime.
        """
        before = None
        threshold = datetime.fromisoformat(since).astimezone(timezone.utc)
        for _ in range(10):
            query = {"limit":100, **({"before":before} if before else {})}
            rows = self._request("GET", "/channels/" + channel_id + "/messages?" + urllib.parse.urlencode(query))
            if not isinstance(rows,list):
                raise DiscordReminderError("invalid_history_response")
            for row in rows:
                if (str(row.get("nonce")) == nonce and str(row.get("author",{}).get("id")) == bot_user_id
                        and discord_id(row.get("id"))):
                    return str(row["id"])
            if not rows:
                return None
            oldest = rows[-1]
            stamp = oldest.get("timestamp")
            if stamp and datetime.fromisoformat(stamp.replace("Z","+00:00")) < threshold:
                return None
            before = discord_id(oldest.get("id"))
            if not before or len(rows)<100:
                return None
        return None
