import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import discord
import gspread
from discord import app_commands
from discord.ext import commands

from bot_action_log import record_action


SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q"
CREDENTIALS_FILE = "credentials.json"

YAKUMAN_CHOICES = [
    app_commands.Choice(name="天和", value="天和"),
    app_commands.Choice(name="地和", value="地和"),
    app_commands.Choice(name="人和", value="人和"),
    app_commands.Choice(name="石上三年", value="石上三年"),
    app_commands.Choice(name="大七星", value="大七星"),
    app_commands.Choice(name="连七对", value="连七对"),
    app_commands.Choice(name="绿一色", value="绿一色"),
    app_commands.Choice(name="九莲宝灯", value="九莲宝灯"),
    app_commands.Choice(name="纯正九莲宝灯", value="纯正九莲宝灯"),
    app_commands.Choice(name="四暗刻", value="四暗刻"),
    app_commands.Choice(name="四暗刻单骑", value="四暗刻单骑"),
    app_commands.Choice(name="国士无双", value="国士无双"),
    app_commands.Choice(name="国士无双十三面", value="国士无双十三面"),
    app_commands.Choice(name="字一色", value="字一色"),
    app_commands.Choice(name="大四喜", value="大四喜"),
    app_commands.Choice(name="大三元", value="大三元"),
    app_commands.Choice(name="小四喜", value="小四喜"),
    app_commands.Choice(name="一色双龙会", value="一色双龙会"),
    app_commands.Choice(name="四杠子", value="四杠子"),
    app_commands.Choice(name="清老头", value="清老头"),
]

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
        print(f"RecordGame Cog: player cache failed: {e}")
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


def safe_float(value):
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return 0.0


def safe_int(value):
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return 999


def get_players_status(player_names):
    status = {
        name: {"mmr": 0, "mmr_rank": "Unranked", "pt": 0, "pt_rank": "Unranked"}
        for name in player_names
    }

    try:
        sh = get_sheet()

        try:
            rows_rank = sh.worksheet("Ranking").get_all_values()
            mmr_list = []
            for row in rows_rank[1:]:
                if len(row) < 2 or not row[0]:
                    continue
                try:
                    mmr_list.append({"name": row[0].strip().lower(), "val": float(row[1])})
                except ValueError:
                    continue

            mmr_list.sort(key=lambda item: item["val"], reverse=True)
            for rank, item in enumerate(mmr_list, 1):
                for target in player_names:
                    if item["name"] == target.lower():
                        status[target]["mmr"] = item["val"]
                        status[target]["mmr_rank"] = rank
        except Exception as e:
            print(f"RecordGame Cog: Ranking read failed: {e}")

        try:
            rows_quarter = sh.worksheet("Ranking Quarter").get_all_values()
            pt_list = []
            name_col = 3
            pt_col = 4
            for row in rows_quarter[1:]:
                if len(row) <= pt_col or not row[name_col]:
                    continue
                try:
                    pt_list.append({"name": row[name_col].strip().lower(), "val": float(row[pt_col])})
                except ValueError:
                    continue

            pt_list.sort(key=lambda item: item["val"], reverse=True)
            for rank, item in enumerate(pt_list, 1):
                for target in player_names:
                    if item["name"] == target.lower():
                        status[target]["pt"] = item["val"]
                        status[target]["pt_rank"] = rank
        except Exception as e:
            print(f"RecordGame Cog: Ranking Quarter read failed: {e}")

        return status
    except Exception as e:
        print(f"RecordGame Cog: status lookup failed: {e}")
        return status


def collect_yakuman(*yakuman_values):
    selected = []
    for value in yakuman_values:
        if value and value not in selected:
            selected.append(value)
    return selected


class RecordGame(commands.Cog):
    def __init__(self, client):
        self.client = client
        try:
            get_sheet()
            update_player_cache()
        except Exception as e:
            print(f"RecordGame Cog: Google Sheets connection failed: {e}")

    @app_commands.command(name="record_game", description="录入成绩并显示变动")
    @app_commands.describe(
        rank1_name="第1名名字",
        rank1_score="第1名分数",
        rank2_name="第2名名字",
        rank2_score="第2名分数",
        rank3_name="第3名名字",
        rank3_score="第3名分数",
        rank4_name="第4名名字",
        rank4_score="第4名分数",
        manual_time="可选: 手动输入时间, 留空则为当前时间",
        yakuman_winner="可选: 役满和牌者, 写入 Games Riichi S 列",
        yakuman_deal_in="可选: 役满放铳者, 写入 Games Riichi T 列",
        yakuman_1="可选: 役满名称, 写入 Games Riichi U 列",
        yakuman_2="可选: 第二个役满",
        yakuman_3="可选: 第三个役满",
        yakuman_4="可选: 第四个役满",
    )
    @app_commands.autocomplete(
        rank1_name=player_name_autocomplete,
        rank2_name=player_name_autocomplete,
        rank3_name=player_name_autocomplete,
        rank4_name=player_name_autocomplete,
        yakuman_winner=player_name_autocomplete,
        yakuman_deal_in=player_name_autocomplete,
    )
    @app_commands.choices(
        yakuman_1=YAKUMAN_CHOICES,
        yakuman_2=YAKUMAN_CHOICES,
        yakuman_3=YAKUMAN_CHOICES,
        yakuman_4=YAKUMAN_CHOICES,
    )
    async def record_game(
        self,
        interaction: discord.Interaction,
        rank1_name: str,
        rank1_score: int,
        rank2_name: str,
        rank2_score: int,
        rank3_name: str,
        rank3_score: int,
        rank4_name: str,
        rank4_score: int,
        manual_time: Optional[str] = None,
        yakuman_winner: Optional[str] = None,
        yakuman_deal_in: Optional[str] = None,
        yakuman_1: Optional[app_commands.Choice[str]] = None,
        yakuman_2: Optional[app_commands.Choice[str]] = None,
        yakuman_3: Optional[app_commands.Choice[str]] = None,
        yakuman_4: Optional[app_commands.Choice[str]] = None,
    ):
        await interaction.response.defer()

        players_ordered = [rank1_name, rank2_name, rank3_name, rank4_name]
        scores_ordered = [rank1_score, rank2_score, rank3_score, rank4_score]
        player_names_lower = {name.lower() for name in players_ordered}
        yakuman_values = collect_yakuman(
            yakuman_1.value if yakuman_1 else None,
            yakuman_2.value if yakuman_2 else None,
            yakuman_3.value if yakuman_3 else None,
            yakuman_4.value if yakuman_4 else None,
        )

        if len(set(players_ordered)) != 4:
            await interaction.followup.send("Name duplicated. Please check the four players.")
            return
        if sum(scores_ordered) != 100000:
            await interaction.followup.send(f"Total score is {sum(scores_ordered)}, expected 100000.")
            return
        if yakuman_winner and yakuman_winner.lower() not in player_names_lower:
            await interaction.followup.send("Yakuman winner must be one of the four players.")
            return
        if yakuman_deal_in and yakuman_deal_in.lower() not in player_names_lower:
            await interaction.followup.send("Yakuman deal-in player must be one of the four players.")
            return
        if yakuman_values and not yakuman_winner:
            await interaction.followup.send("Please choose yakuman_winner when recording a yakuman.")
            return

        try:
            if manual_time:
                final_time_str = manual_time
            else:
                local_time = datetime.now(timezone.utc) - timedelta(hours=8)
                final_time_str = local_time.strftime("%Y-%m-%d %H:%M:%S")

            status_msg = await interaction.followup.send("Reading current rankings...", wait=True)
            pre_status = get_players_status(players_ordered)

            await status_msg.edit(content="Writing game record to Google Sheets...")
            sh = get_sheet()

            ws_pt = sh.worksheet("Games/pt")
            pt_row = len(ws_pt.get_all_values()) + 1
            pt_values = [final_time_str]
            ws_pt.append_row(pt_values)

            ws_riichi = sh.worksheet("Games Riichi")
            new_row = len(ws_riichi.get_all_values()) + 1
            riichi_values = players_ordered + scores_ordered
            ws_riichi.append_row(riichi_values)

            yakuman_text = ", ".join(yakuman_values)
            if yakuman_winner or yakuman_deal_in or yakuman_text:
                ws_riichi.update(
                    values=[[yakuman_winner or "", yakuman_deal_in or "", yakuman_text]],
                    range_name=f"S{new_row}:U{new_row}",
                )

            await status_msg.edit(content=f"Recorded at {final_time_str}. Waiting for Google Sheet calculation...")
            await asyncio.sleep(60)

            calculated_row = ws_riichi.row_values(new_row)
            mmr_deltas = calculated_row[8:12] if len(calculated_row) >= 12 else []

            record_action(
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action_type="record_game",
                summary=f"Recorded game at {final_time_str}: {', '.join(players_ordered)}",
                payload={
                    "games_pt_row": pt_row,
                    "games_pt_values": pt_values,
                    "games_riichi_row": new_row,
                    "games_riichi_values": riichi_values,
                    "mmr_deltas": mmr_deltas,
                    "yakuman_winner": yakuman_winner or "",
                    "yakuman_deal_in": yakuman_deal_in or "",
                    "yakuman_text": yakuman_text,
                },
            )

            post_status = get_players_status(players_ordered)
            embed = discord.Embed(title="✅ 结算完成 (Game Summary)", color=0x00FF00)
            embed.description = f"**Time Recorded:** {final_time_str}"

            if yakuman_text:
                yakuman_line = f"Winner: `{yakuman_winner}`"
                if yakuman_deal_in:
                    yakuman_line += f"\nDeal-in: `{yakuman_deal_in}`"
                yakuman_line += f"\nYakuman: `{yakuman_text}`"
                embed.add_field(name="Yakuman", value=yakuman_line, inline=False)

            rank_emojis = ["🐶", "🥈", "🥉", "🪦"]
            for i, name in enumerate(players_ordered):
                score = scores_ordered[i]
                pre = pre_status.get(name, {})
                post = post_status.get(name, {})

                post_mmr = safe_float(post.get("mmr", 0))
                pre_mmr = safe_float(pre.get("mmr", 0))
                mmr_diff = post_mmr - pre_mmr
                mmr_sign = "+" if mmr_diff >= 0 else ""
                mmr_str = f"{post_mmr:.1f} ({mmr_sign}{mmr_diff:.1f})"

                pre_mmr_rank = safe_int(pre.get("mmr_rank", 999))
                post_mmr_rank = safe_int(post.get("mmr_rank", 999))
                mmr_rank_diff = pre_mmr_rank - post_mmr_rank
                if mmr_rank_diff > 0:
                    mmr_rank_icon = f"🔺{mmr_rank_diff}"
                elif mmr_rank_diff < 0:
                    mmr_rank_icon = f"🔻{abs(mmr_rank_diff)}"
                else:
                    mmr_rank_icon = "➖"
                mmr_rank = post_mmr_rank if post_mmr_rank != 999 else "??"

                post_pt = safe_float(post.get("pt", 0))
                pre_pt = safe_float(pre.get("pt", 0))
                pt_diff = post_pt - pre_pt
                pt_sign = "+" if pt_diff >= 0 else ""
                pt_str = f"{post_pt:.1f} ({pt_sign}{pt_diff:.1f})"

                pre_pt_rank = safe_int(pre.get("pt_rank", 999))
                post_pt_rank = safe_int(post.get("pt_rank", 999))
                pt_rank_diff = pre_pt_rank - post_pt_rank
                if pt_rank_diff > 0:
                    pt_rank_icon = f"🔺{pt_rank_diff}"
                elif pt_rank_diff < 0:
                    pt_rank_icon = f"🔻{abs(pt_rank_diff)}"
                else:
                    pt_rank_icon = "➖"
                pt_rank = post_pt_rank if post_pt_rank != 999 else "??"

                field_val = (
                    f"**MMR**: `{mmr_str}` | Rank #{mmr_rank} ({mmr_rank_icon})\n"
                    f"**PT**: `{pt_str}` | Rank #{pt_rank} ({pt_rank_icon})"
                )
                embed.add_field(name=f"{rank_emojis[i]} {name} ({score})", value=field_val, inline=False)

            await status_msg.edit(content="", embed=embed)
        except Exception as e:
            traceback.print_exc()
            error_text = f"Unknown error: {e}"
            if "status_msg" in locals():
                await status_msg.edit(content=error_text)
            else:
                await interaction.followup.send(error_text)


async def setup(client):
    await client.add_cog(RecordGame(client))
