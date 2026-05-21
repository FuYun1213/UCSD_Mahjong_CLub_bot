import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import discord
from discord import app_commands
from discord.ext import commands, tasks


WWYD_GUILD_ID = 1323725275950878840
QUIZZER_NAME = "Machitan's WWYD Quizzer"
DATA_FILE = Path("wwyd_group_stats.json")
LOCAL_TZ = dt.timezone(dt.timedelta(hours=-7))


def today_key() -> str:
    return dt.datetime.now(LOCAL_TZ).date().isoformat()


def parse_date(value: Optional[str]) -> str:
    if not value:
        return today_key()
    return dt.date.fromisoformat(value).isoformat()


def read_data() -> Dict:
    if not DATA_FILE.exists():
        return {"processed_messages": [], "days": {}}

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {"processed_messages": [], "days": {}}

    data.setdefault("processed_messages", [])
    data.setdefault("days", {})
    return data


def write_data(data: Dict) -> None:
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_quizzer_message(message: discord.Message) -> bool:
    if message.guild is None or message.guild.id != WWYD_GUILD_ID:
        return False
    if not message.author.bot:
        return False

    return message.author.name == QUIZZER_NAME or QUIZZER_NAME.lower() in message.author.name.lower()


def message_date_key(message: discord.Message) -> str:
    created_at = message.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=dt.timezone.utc)
    return created_at.astimezone(LOCAL_TZ).date().isoformat()


def member_groups(member: discord.Member) -> List[discord.Role]:
    return [
        role
        for role in member.roles
        if role.name != "@everyone" and not role.managed
    ]


class WWYDTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = read_data()
        self.midnight_report.start()

    def cog_unload(self):
        self.midnight_report.cancel()

    def save(self):
        write_data(self.data)

    def already_processed(self, message_id: int) -> bool:
        return str(message_id) in set(self.data.get("processed_messages", []))

    def mark_processed(self, message_id: int):
        processed = self.data.setdefault("processed_messages", [])
        processed.append(str(message_id))
        if len(processed) > 5000:
            del processed[:-5000]

    def record_mentions(self, message: discord.Message) -> int:
        if self.already_processed(message.id):
            return 0

        mentioned_members = [
            member
            for member in message.mentions
            if isinstance(member, discord.Member) and not member.bot
        ]
        unique_members = {member.id: member for member in mentioned_members}.values()

        if not unique_members:
            self.mark_processed(message.id)
            self.save()
            return 0

        day = message_date_key(message)
        day_data = self.data.setdefault("days", {}).setdefault(day, {"groups": {}, "users": {}})

        recorded = 0
        for member in unique_members:
            user_key = str(member.id)
            day_data["users"][user_key] = day_data["users"].get(user_key, 0) + 1

            for role in member_groups(member):
                role_key = str(role.id)
                group_data = day_data["groups"].setdefault(role_key, {"name": role.name, "count": 0})
                group_data["name"] = role.name
                group_data["count"] += 1
            recorded += 1

        self.mark_processed(message.id)
        self.save()
        return recorded

    def rank_groups(self, start_date: dt.date, end_date: dt.date) -> Counter:
        totals = Counter()
        for day_str, day_data in self.data.get("days", {}).items():
            day = dt.date.fromisoformat(day_str)
            if not (start_date <= day <= end_date):
                continue

            for role_id, group_data in day_data.get("groups", {}).items():
                name = group_data.get("name", role_id)
                totals[name] += int(group_data.get("count", 0))

        return totals

    def period_range(self, period: str, date_value: Optional[str]) -> tuple[dt.date, dt.date]:
        anchor = dt.date.fromisoformat(parse_date(date_value))
        if period == "day":
            return anchor, anchor
        if period == "week":
            start = anchor - dt.timedelta(days=anchor.weekday())
            return start, start + dt.timedelta(days=6)
        if period == "month":
            start = anchor.replace(day=1)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1) - dt.timedelta(days=1)
            else:
                end = start.replace(month=start.month + 1) - dt.timedelta(days=1)
            return start, end
        return anchor, anchor

    async def scan_channel_history(self, channel: discord.TextChannel, limit: int) -> int:
        count = 0
        async for message in channel.history(limit=limit):
            if is_quizzer_message(message):
                count += self.record_mentions(message)
        return count

    async def send_report(self, channel: discord.abc.Messageable, period: str = "day", date_value: Optional[str] = None):
        start, end = self.period_range(period, date_value)
        totals = self.rank_groups(start, end)

        if not totals:
            await channel.send(f"No WWYD correct-answer group data for {start} to {end}.")
            return

        lines = []
        for index, (group, count) in enumerate(totals.most_common(10), start=1):
            lines.append(f"`#{index}` **{group}**: `{count}` correct")

        embed = discord.Embed(
            title=f"WWYD Group Ranking ({period})",
            description="\n".join(lines),
            color=0x3498DB,
        )
        embed.set_footer(text=f"{start} to {end}")
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if is_quizzer_message(message):
            self.record_mentions(message)

    @tasks.loop(time=dt.time(hour=0, minute=0, tzinfo=LOCAL_TZ))
    async def midnight_report(self):
        guild = self.bot.get_guild(WWYD_GUILD_ID)
        if guild is None:
            return

        channel = guild.system_channel
        if channel is None:
            for candidate in guild.text_channels:
                if candidate.permissions_for(guild.me).send_messages:
                    channel = candidate
                    break

        if channel is not None:
            yesterday = (dt.datetime.now(LOCAL_TZ).date() - dt.timedelta(days=1)).isoformat()
            await self.send_report(channel, "day", yesterday)

    @midnight_report.before_loop
    async def before_midnight_report(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="wwyd_scan", description="Scan recent Machitan WWYD messages in this channel")
    @app_commands.guilds(discord.Object(id=WWYD_GUILD_ID))
    @app_commands.describe(limit="How many recent messages to scan")
    async def wwyd_scan(self, interaction: discord.Interaction, limit: int = 200):
        if interaction.guild_id != WWYD_GUILD_ID:
            await interaction.response.send_message("This command is only enabled in the WWYD server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send("Please run this in a text channel.", ephemeral=True)
            return

        limit = max(1, min(limit, 1000))
        count = await self.scan_channel_history(interaction.channel, limit)
        await interaction.followup.send(f"Scanned {limit} messages and recorded {count} correct mentions.", ephemeral=True)

    @app_commands.command(name="wwyd_groups", description="Show WWYD correct-answer ranking by group")
    @app_commands.guilds(discord.Object(id=WWYD_GUILD_ID))
    @app_commands.describe(
        period="day, week, or month",
        date="Optional date in YYYY-MM-DD. Defaults to today.",
    )
    @app_commands.choices(period=[
        app_commands.Choice(name="Day", value="day"),
        app_commands.Choice(name="Week", value="week"),
        app_commands.Choice(name="Month", value="month"),
    ])
    async def wwyd_groups(
        self,
        interaction: discord.Interaction,
        period: app_commands.Choice[str],
        date: Optional[str] = None,
    ):
        if interaction.guild_id != WWYD_GUILD_ID:
            await interaction.response.send_message("This command is only enabled in the WWYD server.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            await self.send_report(interaction.channel, period.value, date)
            await interaction.delete_original_response()
        except ValueError:
            await interaction.followup.send("Date must be `YYYY-MM-DD`.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WWYDTracker(bot))
