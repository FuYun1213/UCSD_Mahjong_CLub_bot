import asyncio
import json
import os
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from typing import List, Optional

import discord
import gspread
from discord import app_commands
from discord.ext import commands

from bot_action_log import record_action
import mahjong_store
import player_directory


SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q"
CREDENTIALS_FILE = "credentials.json"
MAHJONG_DB_FILE = os.getenv("MAHJONG_DB_FILE") or mahjong_store.DEFAULT_DB_FILE

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

WIND_FIELDS = [
    ("E", "east", "East Wind"),
    ("S", "south", "South Wind"),
    ("W", "west", "West Wind"),
    ("N", "north", "North Wind"),
]


def normalize_source_player_id(name):
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in name.strip())
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return f"ucsd-{normalized.strip('-') or 'player'}"


def narts_played_at(final_time):
    from competition_time import event_time, utc_now
    try:
        return event_time(str(final_time))
    except (TypeError, ValueError):
        return utc_now()


def submit_narts_match(sql_game_id, final_time, wind_entries):
    api_key = os.getenv("NARTS_EXTERNAL_API_KEY", "").strip()
    if not api_key:
        return {"enabled": False, "message": "NARTS sync skipped: NARTS_EXTERNAL_API_KEY is not set."}

    endpoint = os.getenv("NARTS_EXTERNAL_API_ENDPOINT", "https://riichi.one/api/external/v1/matches").strip()
    payload = {
        "idempotencyKey": f"ucsd-sql-game-{sql_game_id}",
        "playedAt": narts_played_at(final_time),
        "players": [
            {
                "sourcePlayerId": normalize_source_player_id(entry["name"]),
                "username": entry["name"],
                "rawScore": entry["score"],
                "seatWind": entry["seatWind"],
            }
            for entry in wind_entries
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            return {"enabled": True, "ok": True, "status": response.status, "response": response_text}
    except urllib.error.HTTPError as error:
        response_text = error.read().decode("utf-8", errors="replace")
        return {"enabled": True, "ok": False, "status": error.code, "response": response_text}
    except Exception as error:
        return {"enabled": True, "ok": False, "status": None, "response": str(error)}


def get_sheet():
    global _gc, _sh
    if _sh is None:
        _gc = gspread.service_account(filename=CREDENTIALS_FILE)
        _sh = _gc.open_by_key(SHEET_ID)
    return _sh


def update_player_cache():
    global _player_name_cache
    try:
        _player_name_cache = player_directory.player_names(MAHJONG_DB_FILE)
    except Exception as e:
        print(f"RecordGame Cog: player cache failed: {e}")
        _player_name_cache = []


def add_player_to_cache(player_name: str):
    normalized_name = player_name.strip()
    if normalized_name and not any(
        name.lower() == normalized_name.lower()
        for name in _player_name_cache
    ):
        _player_name_cache.append(normalized_name)


async def player_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    await asyncio.to_thread(update_player_cache)
    return [app_commands.Choice(name=name, value=name)
            for name in player_directory.matching_names(_player_name_cache, current)]


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
    try:
        with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
            return mahjong_store.player_status_map(connection, player_names)
    except Exception as e:
        print(f"RecordGame Cog: SQL status lookup failed: {e}")

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
        east_name="East Wind player",
        east_score="East Wind score",
        south_name="South Wind player",
        south_score="South Wind score",
        west_name="West Wind player",
        west_score="West Wind score",
        north_name="North Wind player",
        north_score="North Wind score",
        manual_time="可选: 手动输入时间, 留空则为当前时间",
        yakuman_winner="可选: 役满和牌者, 写入 Games Riichi S 列",
        yakuman_deal_in="可选: 役满放铳者, 写入 Games Riichi T 列",
        yakuman_1="可选: 役满名称, 写入 Games Riichi U 列",
        yakuman_2="可选: 第二个役满",
        yakuman_3="可选: 第三个役满",
        yakuman_4="可选: 第四个役满",
    )
    @app_commands.autocomplete(
        east_name=player_name_autocomplete,
        south_name=player_name_autocomplete,
        west_name=player_name_autocomplete,
        north_name=player_name_autocomplete,
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
        east_name: str,
        east_score: int,
        south_name: str,
        south_score: int,
        west_name: str,
        west_score: int,
        north_name: str,
        north_score: int,
        manual_time: Optional[str] = None,
        yakuman_winner: Optional[str] = None,
        yakuman_deal_in: Optional[str] = None,
        yakuman_1: Optional[app_commands.Choice[str]] = None,
        yakuman_2: Optional[app_commands.Choice[str]] = None,
        yakuman_3: Optional[app_commands.Choice[str]] = None,
        yakuman_4: Optional[app_commands.Choice[str]] = None,
    ):
        await interaction.response.defer()

        wind_entries = [
            {"seatWind": "E", "label": "East Wind", "name": east_name.strip(), "score": east_score},
            {"seatWind": "S", "label": "South Wind", "name": south_name.strip(), "score": south_score},
            {"seatWind": "W", "label": "West Wind", "name": west_name.strip(), "score": west_score},
            {"seatWind": "N", "label": "North Wind", "name": north_name.strip(), "score": north_score},
        ]
        wind_order = {seat_wind: index for index, (seat_wind, _, _) in enumerate(WIND_FIELDS)}
        ranked_entries = sorted(wind_entries, key=lambda entry: (-entry["score"], wind_order[entry["seatWind"]]))
        players_ordered = [entry["name"] for entry in ranked_entries]
        scores_ordered = [entry["score"] for entry in ranked_entries]
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
                from zoneinfo import ZoneInfo
                from competition_time import site_timezone
                local_time = datetime.now(ZoneInfo(site_timezone()))
                final_time_str = local_time.strftime("%Y-%m-%d %H:%M:%S")

            status_msg = await interaction.followup.send("Reading current rankings...", wait=True)
            pre_status = get_players_status(players_ordered)

            await status_msg.edit(content="Writing game record to Google Sheets...")
            pre_status = get_players_status(players_ordered)
            yakuman_text = ", ".join(yakuman_values)
            current_quarter = ""
            sql_game_id = None
            mmr_deltas = []
            mmr_afters = []
            with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
                current_quarter = mahjong_store.latest_quarter(connection)
                sql_game_id = mahjong_store.import_game(
                    connection,
                    players_ordered,
                    scores_ordered,
                    final_time_str,
                    source="discord",
                    sheet_row=None,
                    created_by=str(interaction.user),
                    quarter=current_quarter,
                    yakuman={
                        "winner": yakuman_winner or "",
                        "deal_in": yakuman_deal_in or "",
                        "text": yakuman_text,
                        "names": yakuman_values,
                    },
                )
                mmr_deltas = mahjong_store.game_mmr_deltas(connection, sql_game_id)
                mmr_afters = mahjong_store.game_mmr_afters(connection, sql_game_id)

            sh = get_sheet()

            ws_pt = sh.worksheet("Games/pt")
            pt_row = len(ws_pt.get_all_values()) + 1
            pt_values = [final_time_str]
            ws_pt.append_row(pt_values)

            ws_riichi = sh.worksheet("Games Riichi")
            new_row = len(ws_riichi.get_all_values()) + 1
            riichi_values = players_ordered + scores_ordered
            ws_riichi.append_row(riichi_values)

            if yakuman_winner or yakuman_deal_in or yakuman_text:
                ws_riichi.update(
                    values=[[yakuman_winner or "", yakuman_deal_in or "", yakuman_text]],
                    range_name=f"S{new_row}:U{new_row}",
                )

            if len(mmr_deltas) == 4 and len(mmr_afters) == 4:
                ws_riichi.update(
                    values=[[*mmr_deltas, *mmr_afters, "✅ Calculated", current_quarter]],
                    range_name=f"I{new_row}:R{new_row}",
                )
                with mahjong_store.connect(MAHJONG_DB_FILE) as connection:
                    connection.execute(
                        "UPDATE games SET sheet_row = ?, sync_status = 'synced' WHERE id = ?",
                        (new_row, sql_game_id),
                    )
                    connection.commit()

            narts_result = await asyncio.to_thread(submit_narts_match, sql_game_id, final_time_str, wind_entries)
            narts_note = ""
            if narts_result.get("enabled") and not narts_result.get("ok"):
                narts_note = f" NARTS sync failed ({narts_result.get('status') or 'network'})."
            elif narts_result.get("enabled"):
                narts_note = " Sent to NARTS."

            await status_msg.edit(content=f"Recorded at {final_time_str}. MMR calculated locally and synced.{narts_note}")

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
                    "mmr_afters": mmr_afters,
                    "sql_game_id": sql_game_id,
                    "quarter": current_quarter,
                    "yakuman_winner": yakuman_winner or "",
                    "yakuman_deal_in": yakuman_deal_in or "",
                    "yakuman_text": yakuman_text,
                    "wind_entries": wind_entries,
                    "ranked_entries": ranked_entries,
                    "narts_result": narts_result,
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
