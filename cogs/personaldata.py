import json
import math
import urllib.parse
from typing import List, Optional

import discord
import gspread
from discord import app_commands
from discord.ext import commands


SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q"
CREDENTIALS_FILE = "credentials.json"
RECENT_PERSONAL_GAMES_LIMIT = 15
TOTAL_GAMES_OPTION = "Total games"
MAX_CHART_POINTS = 25
MAX_TOTAL_CHART_POINTS = 15

PT_NAME_SCORE_COLUMNS = {1: 3, 4: 6, 7: 9, 10: 12}
QUARTER_COLUMN_INDEX = 17

_gc = None
_sh = None
_player_name_cache = []
_quarter_cache = []


def get_sheet():
    global _gc, _sh
    if _sh is None:
        _gc = gspread.service_account(filename=CREDENTIALS_FILE)
        _sh = _gc.open_by_key(SHEET_ID)
    return _sh


def safe_float(value, default=0.0):
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def format_number(value):
    if value is None:
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.1f}" if number % 1 else str(int(number))


def update_player_cache():
    global _player_name_cache
    try:
        ws = get_sheet().worksheet("Ratings")
        names = ws.col_values(1)
        _player_name_cache = [name for name in names[1:] if name.strip()]
    except Exception as e:
        print(f"PersonalData Cog: player cache failed: {e}")
        _player_name_cache = []


def update_quarter_cache():
    global _quarter_cache
    try:
        rows = get_sheet().worksheet("Games Riichi").get_all_values()
        quarters = [TOTAL_GAMES_OPTION]
        for row in rows[1:]:
            marker = row[QUARTER_COLUMN_INDEX].strip() if len(row) > QUARTER_COLUMN_INDEX else ""
            if marker and marker not in quarters:
                quarters.append(marker)
        _quarter_cache = [TOTAL_GAMES_OPTION] + list(reversed(quarters[1:]))
    except Exception as e:
        print(f"PersonalData Cog: quarter cache failed: {e}")
        _quarter_cache = []


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


async def quarter_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    if not _quarter_cache:
        update_quarter_cache()

    choices = [
        app_commands.Choice(name=quarter, value=quarter)
        for quarter in _quarter_cache
        if current.lower() in quarter.lower()
    ]
    return choices[:25]


def find_player_index(row, target_name):
    row_names = [str(name).lower().strip() for name in row[0:4]]
    for idx, name in enumerate(row_names):
        if target_name in name:
            return idx
    return None


def find_pt_change(row, target_name):
    if len(row) < 13:
        return None

    for name_idx, score_idx in PT_NAME_SCORE_COLUMNS.items():
        if len(row) > name_idx and target_name in row[name_idx].lower().strip():
            return safe_float(row[score_idx])
    return None


def find_latest_mmr(assigned_rows, target_name):
    for item in reversed(assigned_rows):
        idx = find_player_index(item["row"], target_name)
        if idx is None:
            continue

        row = item["row"]
        mmr_abs_raw = row[12 + idx] if len(row) > 12 + idx else ""
        if str(mmr_abs_raw).strip():
            return mmr_abs_raw
    return "N/A"


def assign_quarters(riichi_rows):
    current_quarter = None
    assigned_rows = []

    for row_number, row in enumerate(riichi_rows[1:], start=2):
        marker = row[QUARTER_COLUMN_INDEX].strip() if len(row) > QUARTER_COLUMN_INDEX else ""
        if marker:
            current_quarter = marker

        assigned_rows.append({
            "sheet_row": row_number,
            "row": row,
            "quarter": current_quarter,
        })

    return assigned_rows


def get_personal_stats_from_sheet(sh, target_name, sheet_name, start_row=1):
    rows = sh.worksheet(sheet_name).get_all_values()
    for row in rows[start_row:]:
        if row and row[0].strip().lower() == target_name:
            return {
                "avg_place": row[3] if len(row) > 3 else "N/A",
                "avg_point": row[6] if len(row) > 6 else "N/A",
                "count_1st": row[10] if len(row) > 10 else "N/A",
                "count_2nd": row[11] if len(row) > 11 else "N/A",
                "count_3rd": row[12] if len(row) > 12 else "N/A",
                "count_4th": row[13] if len(row) > 13 else "N/A",
                "total_games": row[14] if len(row) > 14 else "N/A",
                "source_sheet": sheet_name,
            }
    return None


def get_personal_stats(sh, target_name, quarter):
    if quarter == TOTAL_GAMES_OPTION:
        return get_personal_stats_from_sheet(sh, target_name, "Personal Data", start_row=1), "Personal Data"

    if quarter:
        sheet_name = f"{quarter} Personal Data"
        return get_personal_stats_from_sheet(sh, target_name, sheet_name, start_row=1), sheet_name

    return get_personal_stats_from_sheet(sh, target_name, "Personal Data Quarter", start_row=2), "Personal Data Quarter"


def get_personal_detailed_data(player_name, quarter=None):
    try:
        sh = get_sheet()
        target_name = player_name.lower().strip()

        personal_info, stats_sheet_name = get_personal_stats(sh, target_name, quarter)

        if not personal_info:
            return None, f"In '{stats_sheet_name}' sheet, player not found."

        quarter_pt = "N/A"
        try:
            quarter_rows = sh.worksheet("Personal Data Quarter").get_all_values()
            for row in quarter_rows[2:]:
                if row and row[0].strip().lower() == target_name:
                    quarter_pt = row[2]
                    break
        except Exception as e:
            print(f"PersonalData Cog: quarter PT failed: {e}")

        pt_rows = sh.worksheet("Games/pt").get_all_values()
        riichi_rows = sh.worksheet("Games Riichi").get_all_values()
        assigned_rows = assign_quarters(riichi_rows)
        current_mmr = find_latest_mmr(assigned_rows, target_name)

        if quarter == TOTAL_GAMES_OPTION:
            selected_rows = assigned_rows
            scope_label = TOTAL_GAMES_OPTION
        elif quarter:
            selected_rows = [item for item in assigned_rows if item["quarter"] == quarter]
            scope_label = quarter
        else:
            selected_rows = list(reversed(assigned_rows))
            scope_label = f"Latest {RECENT_PERSONAL_GAMES_LIMIT}"

        pt_changes = []
        chart_data = []
        mmr_changes = []
        recent_ranks = []
        mmr_abs_values = []

        for item in selected_rows:
            row = item["row"]
            idx = find_player_index(row, target_name)
            if idx is None:
                continue

            pt_row = pt_rows[item["sheet_row"] - 1] if len(pt_rows) >= item["sheet_row"] else []
            pt_change = find_pt_change(pt_row, target_name)
            if pt_change is not None:
                pt_changes.append(pt_change)
                chart_data.append(pt_change)

            mmr_delta = safe_float(row[8 + idx] if len(row) > 8 + idx else 0)
            mmr_changes.append(mmr_delta)

            mmr_abs_raw = row[12 + idx] if len(row) > 12 + idx else ""
            if str(mmr_abs_raw).strip():
                mmr_abs_values.append(safe_float(mmr_abs_raw))

            try:
                scores = [safe_float(row[4 + i], -99999) for i in range(4)]
                rank = sum(1 for score in scores if score > scores[idx]) + 1
                recent_ranks.append(str(rank))
            except Exception:
                recent_ranks.append("?")

            if not quarter and len(mmr_changes) >= RECENT_PERSONAL_GAMES_LIMIT:
                break

        if quarter:
            recent_ranks = list(reversed(recent_ranks))
        else:
            chart_data = list(reversed(chart_data))

        if not quarter:
            mmr_abs_values = list(reversed(mmr_abs_values))

        mmr_start = mmr_abs_values[0] if mmr_abs_values else None
        mmr_end = mmr_abs_values[-1] if mmr_abs_values else None

        return {
            "info": personal_info,
            "pt_history": pt_changes,
            "mmr_history": mmr_changes,
            "rank_history": recent_ranks,
            "pt_chart_data": chart_data,
            "current_mmr": current_mmr,
            "quarter_pt": quarter_pt,
            "scope_label": scope_label,
            "stats_sheet_name": stats_sheet_name,
            "mmr_start": mmr_start,
            "mmr_end": mmr_end,
            "selected_game_count": len(mmr_changes),
        }, None
    except Exception as e:
        print(f"PersonalData Cog: personal data failed: {e}")
        return None, str(e)


def get_pt_chart_url(pt_values, title, max_points=MAX_CHART_POINTS):
    if not pt_values or len(pt_values) < 2:
        return None

    cumulative_values = []
    running_total = 0
    for value in pt_values:
        running_total += value
        cumulative_values.append(round(running_total, 1))

    match_step = max(1, math.ceil(len(cumulative_values) / max_points))
    sampled_values = cumulative_values[match_step - 1::match_step]
    sampled_labels = [str(i) for i in range(match_step, len(cumulative_values) + 1, match_step)]

    if sampled_labels and sampled_labels[-1] != str(len(cumulative_values)):
        sampled_values.append(cumulative_values[-1])
        sampled_labels.append(str(len(cumulative_values)))

    sampled_values = [round(value, 1) for value in sampled_values]

    chart_title = title
    if match_step > 1:
        chart_title = f"{title} (1/{match_step})"

    chart_config = {
        "type": "line",
        "data": {
            "labels": sampled_labels,
            "datasets": [{
                "label": "PT",
                "data": sampled_values,
                "borderColor": "rgb(52, 152, 219)",
                "backgroundColor": "rgba(52, 152, 219, 0.2)",
                "fill": True,
                "tension": 0.3,
                "pointRadius": 3,
            }],
        },
        "options": {
            "legend": {"display": False},
            "title": {
                "display": True,
                "text": chart_title,
                "fontColor": "#333",
            },
            "scales": {
                "yAxes": [{"ticks": {"beginAtZero": False}}],
            },
        },
    }

    chart_json = json.dumps(chart_config)
    encoded_json = urllib.parse.quote(chart_json)
    return f"https://quickchart.io/chart?c={encoded_json}&w=500&h=300"


class PersonalData(commands.Cog):
    def __init__(self, client):
        self.client = client
        try:
            get_sheet()
            update_player_cache()
            update_quarter_cache()
        except Exception as e:
            print(f"PersonalData Cog: Google Sheets connection failed: {e}")

    @app_commands.command(name="personal_data", description="Query detailed personal data")
    @app_commands.describe(
        player_name="Player name",
        quarter="Optional: Total games or a quarter like 2025 Spring. Leave blank for latest 15 games.",
    )
    @app_commands.autocomplete(player_name=player_name_autocomplete, quarter=quarter_autocomplete)
    async def personal_data(
        self,
        interaction: discord.Interaction,
        player_name: str,
        quarter: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=False)

        data, error = get_personal_detailed_data(player_name, quarter)
        if data is None:
            await interaction.followup.send(content=f"Error: {error}")
            return
        info = data["info"]
        pt_list = data["pt_history"]
        mmr_list = data["mmr_history"]
        rank_list = data["rank_history"]
        chart_data = data["pt_chart_data"]
        current_mmr = data["current_mmr"]
        quarter_pt = data["quarter_pt"]
        scope_label = data["scope_label"]

        sum_pt = sum(pt_list)
        sum_mmr = sum(mmr_list)
        pt_sign = "+" if sum_pt > 0 else ""
        mmr_sign = "+" if sum_mmr > 0 else ""
        recent_game_str = "".join(rank_list)

        mmr_sentence = "MMR change: not enough MMR data in this range."
        if data["mmr_start"] is not None and data["mmr_end"] is not None:
            mmr_sentence = (
                f"MMR changed from `{format_number(data['mmr_start'])}` "
                f"to `{format_number(data['mmr_end'])}`."
            )

        embed = discord.Embed(
            title=f"Personal Data: {player_name}",
            color=0x3498DB,
        )

        embed.add_field(
            name="Current Status",
            value=f"**MMR**: `{current_mmr}`\n**Quarter PT**: `{quarter_pt}`",
            inline=False,
        )
        embed.add_field(
            name="Total Games (Overall)",
            value=(
                f"`{info['total_games']}` Games\n"
                f"[1st: `{info['count_1st']}` / 2nd: `{info['count_2nd']}` / "
                f"3rd: `{info['count_3rd']}` / 4th: `{info['count_4th']}`]"
            ),
            inline=False,
        )

        embed.add_field(
            name="Averages",
            value=f"Avg Place: `{info['avg_place']}`\nAvg Point: `{info['avg_point']}`",
            inline=True,
        )
        embed.add_field(
            name=f"Trends ({scope_label})",
            value=(
                f"Games: `{data['selected_game_count']}`\n"
                f"PT Change: `{pt_sign}{sum_pt:.1f}`\n"
                f"MMR Change: `{mmr_sign}{sum_mmr:.1f}`\n"
                f"{mmr_sentence}"
            ),
            inline=True,
        )

        if recent_game_str:
            embed.add_field(name="Recent Form (Left=Latest)", value=f"`[{recent_game_str}]`", inline=False)

        chart_title = f"{scope_label} PT Curve"
        max_chart_points = MAX_TOTAL_CHART_POINTS if quarter == TOTAL_GAMES_OPTION else MAX_CHART_POINTS
        chart_url = get_pt_chart_url(chart_data, chart_title, max_chart_points)
        if chart_url:
            embed.set_image(url=chart_url)
        else:
            embed.set_footer(text="Not enough data to generate PT chart.")

        await interaction.followup.send(embed=embed)


async def setup(client):
    await client.add_cog(PersonalData(client))
