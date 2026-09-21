from typing import Dict, List, Optional, Tuple

import discord
import gspread
from discord import app_commands
from discord.ext import commands


SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q"
CREDENTIALS_FILE = "credentials.json"

AUTO_WIN_MOST = "__win_most__"
AUTO_LOSE_MOST = "__lose_most__"

_gc = None
_sh = None
_player_name_cache = []


def get_sheet():
    global _gc, _sh
    if _sh is None:
        _gc = gspread.service_account(filename=CREDENTIALS_FILE)
        _sh = _gc.open_by_key(SHEET_ID)
    return _sh


def update_player_cache():
    global _player_name_cache
    try:
        names = get_sheet().worksheet("Ratings").col_values(1)
        _player_name_cache = [name for name in names[1:] if name.strip()]
    except Exception as e:
        print(f"Versus Cog: player cache failed: {e}")
        _player_name_cache = []


async def player_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    if not _player_name_cache:
        update_player_cache()

    choices = [
        app_commands.Choice(name=name, value=name)
        for name in _player_name_cache
        if current.lower() in name.lower()
    ]
    return choices[:25]


async def opponent_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    base_choices = [
        app_commands.Choice(name="You win most", value=AUTO_WIN_MOST),
        app_commands.Choice(name="You lose most", value=AUTO_LOSE_MOST),
    ]

    if not _player_name_cache:
        update_player_cache()

    player_choices = [
        app_commands.Choice(name=name, value=name)
        for name in _player_name_cache
        if current.lower() in name.lower()
    ]

    if current:
        mode_choices = [choice for choice in base_choices if current.lower() in choice.name.lower()]
    else:
        mode_choices = base_choices

    return (mode_choices + player_choices)[:25]


def safe_float(value, default=-999999.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def empty_pair_stats():
    return {
        "total_matches": 0,
        "p1_stats": {"wins": 0, "big_wins": 0, "stomps": 0, "weighted_score": 0},
        "p2_stats": {"wins": 0, "big_wins": 0, "stomps": 0, "weighted_score": 0},
        "p1_pt_diff": 0.0,
        "recent_record": [],
    }


def add_match_to_stats(stats, player_a, player_b, rank_1, rank_2, pt_1, pt_2):
    stats["total_matches"] += 1
    stats["p1_pt_diff"] += pt_1 - pt_2

    winner = "Draw"
    rank_diff = abs(rank_1 - rank_2)

    if rank_1 < rank_2:
        winner = player_a
        stats["p1_stats"]["wins"] += 1
        if rank_diff == 3:
            stats["p1_stats"]["stomps"] += 1
            stats["p1_stats"]["weighted_score"] += 3
        elif rank_diff == 2:
            stats["p1_stats"]["big_wins"] += 1
            stats["p1_stats"]["weighted_score"] += 2
        else:
            stats["p1_stats"]["weighted_score"] += 1
    elif rank_2 < rank_1:
        winner = player_b
        stats["p2_stats"]["wins"] += 1
        if rank_diff == 3:
            stats["p2_stats"]["stomps"] += 1
            stats["p2_stats"]["weighted_score"] += 3
        elif rank_diff == 2:
            stats["p2_stats"]["big_wins"] += 1
            stats["p2_stats"]["weighted_score"] += 2
        else:
            stats["p2_stats"]["weighted_score"] += 1

    stats["recent_record"].append(winner)
    if len(stats["recent_record"]) > 5:
        stats["recent_record"].pop(0)


def iter_unique_games(rows):
    last_game_signature = ""
    for row in rows[1:]:
        if len(row) < 8:
            continue

        current_signature = "".join(str(value).strip().lower() for value in row[0:8])
        if current_signature == last_game_signature:
            continue
        last_game_signature = current_signature
        yield row


def get_versus_data(player_a, player_b):
    try:
        rows = get_sheet().worksheet("Games Riichi").get_all_values()
        p1 = player_a.lower().strip()
        p2 = player_b.lower().strip()

        if p1 == p2:
            return None, "Please enter two different players."

        stats = empty_pair_stats()

        for row in iter_unique_games(rows):
            current_players = [name.lower().strip() for name in row[0:4]]
            if p1 not in current_players or p2 not in current_players:
                continue

            scores_for_rank = [safe_float(row[4 + i]) for i in range(4)]
            idx_1 = current_players.index(p1)
            idx_2 = current_players.index(p2)
            score_val_1 = scores_for_rank[idx_1]
            score_val_2 = scores_for_rank[idx_2]
            rank_1 = sum(1 for score in scores_for_rank if score > score_val_1) + 1
            rank_2 = sum(1 for score in scores_for_rank if score > score_val_2) + 1

            add_match_to_stats(stats, player_a, player_b, rank_1, rank_2, score_val_1, score_val_2)

        if stats["total_matches"] == 0:
            return None, f"No shared table records found for {player_a} and {player_b}."

        return stats, None
    except Exception as e:
        print(f"Versus Cog: versus error: {e}")
        return None, str(e)


def find_auto_opponent(player_a: str, mode: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        rows = get_sheet().worksheet("Games Riichi").get_all_values()
        p1 = player_a.lower().strip()
        pair_stats: Dict[str, Dict] = {}
        display_names: Dict[str, str] = {}

        for row in iter_unique_games(rows):
            current_players = [name.lower().strip() for name in row[0:4]]
            if p1 not in current_players:
                continue

            scores_for_rank = [safe_float(row[4 + i]) for i in range(4)]
            idx_1 = current_players.index(p1)
            score_val_1 = scores_for_rank[idx_1]
            rank_1 = sum(1 for score in scores_for_rank if score > score_val_1) + 1

            for idx_2, opponent_key in enumerate(current_players):
                if idx_2 == idx_1 or not opponent_key:
                    continue

                if opponent_key not in pair_stats:
                    display_names[opponent_key] = row[idx_2]
                    pair_stats[opponent_key] = empty_pair_stats()

                score_val_2 = scores_for_rank[idx_2]
                rank_2 = sum(1 for score in scores_for_rank if score > score_val_2) + 1
                add_match_to_stats(
                    pair_stats[opponent_key],
                    player_a,
                    display_names[opponent_key],
                    rank_1,
                    rank_2,
                    score_val_1,
                    score_val_2,
                )

        if not pair_stats:
            return None, f"No shared table records found for {player_a}."

        def win_margin(item):
            stats = item[1]
            return (
                stats["p1_stats"]["wins"] - stats["p2_stats"]["wins"],
                stats["p1_stats"]["weighted_score"] - stats["p2_stats"]["weighted_score"],
                stats["total_matches"],
            )

        if mode == AUTO_WIN_MOST:
            opponent_key, _ = max(pair_stats.items(), key=win_margin)
        else:
            opponent_key, _ = min(pair_stats.items(), key=win_margin)

        return display_names[opponent_key], None
    except Exception as e:
        print(f"Versus Cog: auto opponent error: {e}")
        return None, str(e)


def build_versus_embed(player_a, player_b, data):
    s1 = data["p1_stats"]
    s2 = data["p2_stats"]
    total = data["total_matches"]
    draws = total - s1["wins"] - s2["wins"]

    score1 = s1["weighted_score"]
    score2 = s2["weighted_score"]
    total_score = score1 + score2
    if total_score > 0:
        rate_a = (score1 / total_score) * 100
        rate_b = (score2 / total_score) * 100
    else:
        rate_a = 50
        rate_b = 50

    bar_len = 12
    num_a = int((rate_a / 100) * bar_len)
    num_b = int((rate_b / 100) * bar_len)
    if num_a + num_b < bar_len and total_score > 0:
        if rate_a >= rate_b:
            num_a += 1
        else:
            num_b += 1

    bar_str = "🟦" * num_a + "🟥" * num_b
    while len(bar_str) < bar_len:
        bar_str += "⬜"

    diff_rate = abs(rate_a - rate_b)
    leader = player_a if rate_a > rate_b else player_b
    loser = player_b if rate_a > rate_b else player_a

    comment = "势均力敌!"
    if total < 5:
        comment = "刚开始较量..."
    elif diff_rate > 40:
        comment = f"{leader} 正在对 {loser} 进行降维打击! 💥"
    elif diff_rate > 20:
        comment = f"{leader} 掌握了绝对的统治力!"
    elif diff_rate > 10:
        comment = f"{leader} 稍占上风。"

    embed = discord.Embed(
        title=f"⚔️: {player_a} 🆚 {player_b}",
        description=f"Total **{total}** Games | {comment}",
        color=0xFF4500,
    )

    embed.add_field(
        name="📊 总胜场",
        value=f"**{player_a}**: `{s1['wins']}` 胜\n**{player_b}**: `{s2['wins']}` 胜\n(平: {draws})",
        inline=True,
    )

    diff = data["p1_pt_diff"]
    sign = "+" if diff > 0 else ""
    embed.add_field(
        name="Head-to-Head Score",
        value=f"**{player_a}** 对 **{player_b}**:\n`{sign}{diff:.1f}` pts",
        inline=True,
    )

    stomp_text_a = (
        f"**大胜** (+2): `{s1['big_wins']}` 次\n"
        f"**踩头** (+3): `{s1['stomps']}` 次"
    )
    embed.add_field(name=f"🟦 {player_a} 战绩详情", value=stomp_text_a, inline=False)

    stomp_text_b = (
        f"**大胜** (+2): `{s2['big_wins']}` 次\n"
        f"**踩头** (+3): `{s2['stomps']}` 次"
    )
    embed.add_field(name=f"🟥 {player_b} 战绩详情", value=stomp_text_b, inline=False)

    embed.add_field(
        name="⚖️ 统治力 (基于积分权重)",
        value=f"{bar_str}\n`{rate_a:.1f}%` ◀── 积分占比 ──▶ `{rate_b:.1f}%`",
        inline=False,
    )

    recent_str = " -> ".join(data["recent_record"])
    embed.set_footer(text=f"最近5场胜者: {recent_str}")
    return embed


class Versus(commands.Cog):
    def __init__(self, client):
        self.client = client
        try:
            get_sheet()
            update_player_cache()
        except Exception as e:
            print(f"Versus Cog: Google Sheets connection failed: {e}")

    @app_commands.command(name="versus", description="Query head-to-head match history")
    @app_commands.describe(
        player_a="Player A",
        player_b="Player B, or choose You win most / You lose most",
    )
    @app_commands.autocomplete(player_a=player_name_autocomplete, player_b=opponent_autocomplete)
    async def versus(self, interaction: discord.Interaction, player_a: str, player_b: str):
        await interaction.response.defer()

        if player_b in (AUTO_WIN_MOST, AUTO_LOSE_MOST):
            resolved, error = find_auto_opponent(player_a, player_b)
            if resolved is None:
                await interaction.followup.send(f"❌ {error}")
                return
            player_b = resolved

        data, error = get_versus_data(player_a, player_b)
        if data is None:
            await interaction.followup.send(f"❌ {error}")
            return

        await interaction.followup.send(embed=build_versus_embed(player_a, player_b, data))


async def setup(client):
    await client.add_cog(Versus(client))
