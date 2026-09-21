"""Server-only Discord settings; never expose or log credential values."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SNOWFLAKE = re.compile(r"[0-9]{15,20}\Z")
DEFAULT_GUILD_ID = "1278056421224747162"  # Existing bot/web guild.


def discord_id(value):
    value = str(value or "")
    return value if SNOWFLAKE.fullmatch(value) else ""


@dataclass(frozen=True)
class DiscordReminderConfig:
    token: str = field(default="", repr=False)
    guild_id: str = DEFAULT_GUILD_ID
    channel_id: str = ""
    enabled: bool = True

    @property
    def configured(self):
        return bool(self.token and discord_id(self.guild_id) and discord_id(self.channel_id))

    @classmethod
    def from_env(cls):
        channel = os.getenv("DISCORD_RESERVATION_REMINDER_CHANNEL_ID", "").strip()
        # Only explicitly configured channels are used, never name discovery.
        channel = channel or os.getenv("DISCORD_GAME_RECORD_CHANNEL_ID", "").strip()
        guild = os.getenv("DISCORD_GUILD_ID", DEFAULT_GUILD_ID).strip()
        enabled = os.getenv("DISCORD_RESERVATION_REMINDERS_ENABLED", "true").strip().lower() not in {"0","false","no","off"}
        if not enabled:
            return cls(guild_id=guild, channel_id=channel, enabled=False)
        if not channel:
            return cls(guild_id=guild)
        token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            path = Path(__file__).resolve().parents[1] / "DISCORD_BOT_TOKEN.env"
            if path.is_file():
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    key, _, value = line.partition("=")
                    if key.strip() == "DISCORD_BOT_TOKEN":
                        token = value.strip().strip("\"'")
                        break
        return cls(token=token, guild_id=guild, channel_id=channel)
