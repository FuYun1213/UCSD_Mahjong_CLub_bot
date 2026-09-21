import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks


SUBSCRIPTIONS_FILE = Path("replay_subscriptions.json")

RIICHI_CITY_API_URL = "https://dunu5s1vzgz6j.cloudfront.net/record/paiPuRoomUsers"
RIICHI_CITY_USER_GAMES_URL = "https://dunu5s1vzgz6j.cloudfront.net/record/paiPuRoomUserStageGames"
RIICHI_CITY_SEARCH_URL = "https://mahjong-jp.com/loglibrary/search"
RIICHI_CITY_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://mahjong-jp.com",
    "Referer": RIICHI_CITY_SEARCH_URL,
    "User-Agent": "Mozilla/5.0",
}
MAHJONG_SOUL_START_TS = 1262304000000
MAHJONG_SOUL_API_BASE = "https://5-data.amae-koromo.com/api/v2/pl4"
MAHJONG_SOUL_MODE = "16.12.9.15.11.8"
MAHJONG_SOUL_TAG = "494058"


def read_subscriptions() -> Dict[str, Dict[str, Any]]:
    if not SUBSCRIPTIONS_FILE.exists():
        return {}

    try:
        return json.loads(SUBSCRIPTIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_subscriptions(subscriptions: Dict[str, Dict[str, Any]]) -> None:
    SUBSCRIPTIONS_FILE.write_text(
        json.dumps(subscriptions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_first_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]

    if not isinstance(value, dict):
        return []

    for key in ("list", "records", "data", "rows", "result"):
        nested = value.get(key)
        found = find_first_list(nested)
        if found:
            return found

    for nested in value.values():
        found = find_first_list(nested)
        if found:
            return found

    return []


def first_present(data: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def extract_display_name(data: Dict[str, Any], fallback: str) -> str:
    value = first_present(
        data,
        ["nickname", "name", "username", "player_name", "playerName", "nickName"],
    )
    if value:
        return str(value)

    for key in ("player", "account", "profile", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            nested_value = first_present(
                nested,
                ["nickname", "name", "username", "player_name", "playerName", "nickName"],
            )
            if nested_value:
                return str(nested_value)

    return fallback


def extract_game_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    for path in (
        ("list",),
        ("data", "list"),
        ("records",),
        ("data", "records"),
    ):
        value: Any = data
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)

        if isinstance(value, list):
            games = [item for item in value if isinstance(item, dict)]
            if games:
                return games

    return find_first_list(data)


def find_player_result(game: Dict[str, Any], player_key: str) -> Dict[str, Any]:
    player_key_lower = player_key.lower()
    candidates = []

    for key in ("users", "players", "playerList", "userList", "scores", "results"):
        value = game.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))

    for candidate in candidates:
        names = [
            str(candidate.get(key, "")).lower()
            for key in ("nickname", "name", "userName", "playerName", "nickName")
        ]
        ids = [
            str(candidate.get(key, "")).lower()
            for key in ("accountId", "account_id", "userID", "userId", "uid", "playerId")
        ]
        if player_key_lower in names or player_key_lower in ids:
            return candidate

    return game


def normalize_rank(value: Any) -> str:
    try:
        rank = int(value)
        return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(rank, str(rank))
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "?"


def normalize_pt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"

    sign = "+" if number > 0 else ""
    if number.is_integer():
        return f"{sign}{int(number)}pt"
    return f"{sign}{number:.1f}pt"


class ReplayMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.subscriptions = read_subscriptions()
        self.check_replays.start()

    def cog_unload(self):
        self.check_replays.cancel()

    async def fetch_riichi_city_user(
        self,
        session: aiohttp.ClientSession,
        query: str,
    ) -> Optional[Dict[str, Any]]:
        # The public search page first resolves a nickname or UID to a Riichi City user.
        payload = {"content": query, "skip": 0, "limit": 1}
        async with session.post(
            RIICHI_CITY_API_URL,
            json=payload,
            headers=RIICHI_CITY_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                print(f"ReplayMonitor: Riichi City user status {response.status} for {query}")
                return None

            data = await response.json(content_type=None)
            users = find_first_list(data)
            return users[0] if users else None

    async def fetch_riichi_city_latest(
        self,
        session: aiohttp.ClientSession,
        query: str,
        user_id: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        user = None
        if user_id is None:
            user = await self.fetch_riichi_city_user(session, query)
            if not user:
                return None
            user_id = first_present(user, ["userID", "userId", "uid"])

        if user_id is None:
            return None

        try:
            user_id_int = int(user_id)
        except (TypeError, ValueError):
            return None

        # The current log library returns matches from this second endpoint.
        payload = {
            "uid": user_id_int,
            "playCount": 4,
            "round": [1, 2],
            "stageTypes": [3, 4],
            "startTime": 0,
            "endTime": 0,
            "skip": 0,
            "limit": 1,
        }
        async with session.post(
            RIICHI_CITY_USER_GAMES_URL,
            json=payload,
            headers=RIICHI_CITY_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                print(f"ReplayMonitor: Riichi City games status {response.status} for {query}")
                return None

            data = await response.json(content_type=None)
            games = find_first_list(data)
            if not games:
                return None

            latest_game = games[0]
            latest_game["_player_uid"] = str(user_id)
            if user:
                latest_game["_display_name"] = extract_display_name(user, query)
            return latest_game

    async def fetch_mahjong_soul_latest(
        self,
        session: aiohttp.ClientSession,
        internal_id: str,
    ) -> Optional[Dict[str, Any]]:
        current_ts = int(time.time() * 1000)
        api_url = f"{MAHJONG_SOUL_API_BASE}/player_records/{internal_id}/{MAHJONG_SOUL_START_TS}/{current_ts}"
        params = {
            "mode": MAHJONG_SOUL_MODE,
            "tag": MAHJONG_SOUL_TAG,
            "limit": 1,
        }

        async with session.get(
            api_url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                print(f"ReplayMonitor: Mahjong Soul status {response.status} for {internal_id}")
                return None

            data = await response.json(content_type=None)
            games = extract_game_list(data if isinstance(data, dict) else {"data": data})
            if not games:
                return None

            latest_game = games[0]
            if isinstance(data, dict):
                latest_game["_display_name"] = extract_display_name(data, internal_id)
            return latest_game

    async def fetch_mahjong_soul_profile(
        self,
        session: aiohttp.ClientSession,
        internal_id: str,
    ) -> Optional[Dict[str, Any]]:
        current_ts = int(time.time() * 1000)
        api_url = f"{MAHJONG_SOUL_API_BASE}/player_stats/{internal_id}/{MAHJONG_SOUL_START_TS}/{current_ts}"
        params = {
            "mode": MAHJONG_SOUL_MODE,
            "tag": MAHJONG_SOUL_TAG,
        }

        async with session.get(
            api_url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                print(f"ReplayMonitor: Mahjong Soul profile status {response.status} for {internal_id}")
                return None

            data = await response.json(content_type=None)
            return data if isinstance(data, dict) else {"data": data}

    async def fetch_latest_game(
        self,
        session: aiohttp.ClientSession,
        platform: str,
        game_name: str,
        player_uid: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        if platform == "riichi_city":
            return await self.fetch_riichi_city_latest(session, game_name, player_uid)

        if platform == "mahjong_soul":
            return await self.fetch_mahjong_soul_latest(session, game_name)

        return None

    def get_record_id(self, game: Dict[str, Any]) -> Optional[str]:
        record_id = first_present(
            game,
            [
                "id",
                "recordId",
                "record_id",
                "uuid",
                "paipuId",
                "paipu_id",
                "paiPuID",
                "paiPuNotID",
                "logId",
                "log_id",
            ],
        )
        return str(record_id) if record_id is not None else None

    def build_announcement(self, subscription: Dict[str, Any], game: Dict[str, Any]) -> discord.Embed:
        platform_name = "Riichi City" if subscription["platform"] == "riichi_city" else "Mahjong Soul"
        game_name = subscription.get("display_name") or game.get("_display_name") or subscription["game_name"]
        player_key = str(subscription.get("player_uid") or subscription["game_name"])
        player_result = find_player_result(game, player_key)

        rank = first_present(player_result, ["rank", "ranking", "place", "seatRank", "finalRank"], "?")
        if subscription["platform"] == "mahjong_soul":
            pt = first_present(player_result, ["diff", "pt", "delta", "gradingPoint", "gradingScore"], "?")
        else:
            pt = first_present(player_result, ["pt", "delta", "gradingPoint", "gradingScore"], "?")
        score = first_present(player_result, ["score", "points", "point"], None)
        room = first_present(game, ["modeName", "roomName", "room", "levelName", "contestName"], "Unknown room")
        if subscription["platform"] == "riichi_city":
            room = f"{'Galaxy' if game.get('stageType') == 4 else 'Sun'} {'South' if game.get('round') == 2 else 'East'}"
        record_id = self.get_record_id(game)
        if subscription["platform"] == "riichi_city" and pt == "?" and score is not None:
            result_text = f"{game_name} got **{normalize_rank(rank)}** with `{score}` points."
        else:
            result_text = f"{game_name} got **{normalize_rank(rank)}**, `{normalize_pt(pt)}`."

        embed = discord.Embed(
            title=f"{game_name} finished a {platform_name} match",
            description=result_text,
            color=0xF1C40F,
        )
        embed.add_field(name="Room", value=str(room), inline=True)
        if score is not None:
            embed.add_field(name="Score", value=str(score), inline=True)
        if record_id:
            embed.add_field(name="Replay", value=f"`{record_id}`", inline=True)
            if subscription["platform"] == "riichi_city":
                embed.url = f"https://mahjong-jp.com/loglibrary/detail/{record_id}"
            elif subscription["platform"] == "mahjong_soul":
                embed.url = f"https://amae-koromo.sapk.ch/player/{subscription['game_name']}/16"

        return embed

    @tasks.loop(minutes=5)
    async def check_replays(self):
        await self.bot.wait_until_ready()

        if not self.subscriptions:
            return

        async with aiohttp.ClientSession() as session:
            for key, subscription in list(self.subscriptions.items()):
                latest_game = await self.fetch_latest_game(
                    session,
                    subscription["platform"],
                    subscription["game_name"],
                    subscription.get("player_uid"),
                )
                if not latest_game:
                    continue

                record_id = self.get_record_id(latest_game)
                if not record_id:
                    continue

                if not subscription.get("last_record_id"):
                    subscription["last_record_id"] = record_id
                    write_subscriptions(self.subscriptions)
                    continue

                if record_id == subscription.get("last_record_id"):
                    continue

                subscription["last_record_id"] = record_id
                write_subscriptions(self.subscriptions)

                channel = self.bot.get_channel(int(subscription["channel_id"]))
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(int(subscription["channel_id"]))
                    except discord.HTTPException:
                        continue

                await channel.send(embed=self.build_announcement(subscription, latest_game))

    @check_replays.before_loop
    async def before_check_replays(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="subscribe", description="Subscribe to completed replay alerts")
    @app_commands.describe(
        platform="Replay archive to monitor",
        game_name="Riichi City nickname, or Mahjong Soul Amae-Koromo internal player ID",
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="Riichi City", value="riichi_city"),
        app_commands.Choice(name="Mahjong Soul", value="mahjong_soul"),
    ])
    async def subscribe(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        game_name: str,
    ):
        await interaction.response.defer(ephemeral=False)
        game_name = game_name.strip()

        key = f"{interaction.guild_id}:{interaction.channel_id}:{platform.value}:{game_name.casefold()}"
        subscription = {
            "platform": platform.value,
            "game_name": game_name,
            "channel_id": interaction.channel_id,
            "subscriber_id": interaction.user.id,
            "last_record_id": None,
        }

        async with aiohttp.ClientSession() as session:
            latest_game = await self.fetch_latest_game(session, platform.value, game_name)
            if latest_game:
                subscription["last_record_id"] = self.get_record_id(latest_game)
                if platform.value == "riichi_city":
                    subscription["player_uid"] = latest_game.get("_player_uid")
                    subscription["display_name"] = latest_game.get("_display_name", game_name)
                if platform.value == "mahjong_soul" and latest_game.get("_display_name"):
                    subscription["display_name"] = latest_game["_display_name"]
            elif platform.value == "mahjong_soul":
                profile = await self.fetch_mahjong_soul_profile(session, game_name)
                if profile:
                    subscription["display_name"] = extract_display_name(profile, game_name)
                else:
                    await interaction.followup.send(
                        "I could not find that Mahjong Soul player on Amae-Koromo. "
                        "Use the internal player ID from the player page URL.",
                        ephemeral=False,
                    )
                    return
            elif platform.value == "riichi_city":
                user = await self.fetch_riichi_city_user(session, game_name)
                if not user:
                    await interaction.followup.send(
                        "I could not find that Riichi City player in the Log Library. "
                        "Only Galaxy/Sun ranked players are searchable there.",
                        ephemeral=False,
                    )
                    return
                subscription["player_uid"] = first_present(user, ["userID", "userId", "uid"])
                subscription["display_name"] = extract_display_name(user, game_name)

        self.subscriptions[key] = subscription
        write_subscriptions(self.subscriptions)

        display_name = subscription.get("display_name", game_name)
        await interaction.followup.send(
            f"Subscribed this channel to {platform.name} completed-match alerts for `{display_name}`.",
            ephemeral=False,
        )

    @app_commands.command(name="ms_profile", description="Look up a Mahjong Soul Amae-Koromo internal player ID")
    @app_commands.describe(internal_id="Amae-Koromo internal player ID from the player page URL")
    async def ms_profile(self, interaction: discord.Interaction, internal_id: str):
        await interaction.response.defer(ephemeral=True)

        async with aiohttp.ClientSession() as session:
            profile = await self.fetch_mahjong_soul_profile(session, internal_id)

        if not profile:
            await interaction.followup.send(
                "Could not find that Mahjong Soul ID on Amae-Koromo. "
                "Use the number from a URL like `https://amae-koromo.sapk.ch/player/75293431/16`.",
                ephemeral=True,
            )
            return

        display_name = extract_display_name(profile, internal_id)
        await interaction.followup.send(
            f"Mahjong Soul ID `{internal_id}` appears to be `{display_name}`.\n"
            f"https://amae-koromo.sapk.ch/player/{internal_id}/16",
            ephemeral=True,
        )

    @app_commands.command(name="unsubscribe", description="Remove a replay alert subscription")
    @app_commands.describe(
        platform="Replay archive",
        game_name="In-game name to stop monitoring",
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="Riichi City", value="riichi_city"),
        app_commands.Choice(name="Mahjong Soul", value="mahjong_soul"),
    ])
    async def unsubscribe(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        game_name: str,
    ):
        game_name = game_name.strip()
        key = f"{interaction.guild_id}:{interaction.channel_id}:{platform.value}:{game_name.casefold()}"
        if key in self.subscriptions:
            del self.subscriptions[key]
            write_subscriptions(self.subscriptions)
            await interaction.response.send_message(f"Unsubscribed `{game_name}`.", ephemeral=False)
        else:
            await interaction.response.send_message("No matching subscription found in this channel.", ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReplayMonitor(bot))
