import asyncio
import base64
import json
import math
import os
import io
import urllib.parse
from pathlib import Path
from typing import List, Optional

import discord
import gspread
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

import mahjong_store
import player_directory
import registered_names


ROOT = Path(__file__).resolve().parents[1]
USERS_FILE = Path(os.getenv("TABLE_ACCOUNT_FILE", str(ROOT / "web_users.json")))


SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q"
CREDENTIALS_FILE = "credentials.json"
RECENT_PERSONAL_GAMES_LIMIT = 15
TOTAL_GAMES_OPTION = "Total games"
MAX_CHART_POINTS = 25
MAX_TOTAL_CHART_POINTS = 15
RENDER_SCALE = 2

PT_NAME_SCORE_COLUMNS = {1: 3, 4: 6, 7: 9, 10: 12}
QUARTER_COLUMN_INDEX = 17
YAKUMAN_WINNER_INDEX = 18
YAKUMAN_NAMES_INDEX = 20

_gc = None
_sh = None
_player_name_cache = []
_quarter_cache = []


def users_data():
    return registered_names.read_accounts(USERS_FILE)


def write_users_data(data):
    registered_names.write_accounts(USERS_FILE, data)


def bind_registered_discord(player_name, discord_id, discord_name, avatar=""):
    # Fetching an avatar happens outside this synchronous read/modify/write lock.
    with registered_names.account_lock(USERS_FILE):
        data = users_data()
        matches = [(key, user) for key, user in data["users"].items()
                   if registered_names.normalize_name(user.get("name", key)) == registered_names.normalize_name(player_name)]
        if len(matches) != 1:
            raise ValueError("That web account does not exist or needs administrator review.")
        key, user = matches[0]
        if user.get("disabled") or user.get("is_active") is False or user.get("status") in {"disabled", "banned", "deleted"}:
            raise ValueError("That web account is unavailable.")
        import account_discord
        registered_names.ensure_directory(USERS_FILE)
        data = users_data()
        user = data["users"][key]
        return account_discord.bind(USERS_FILE, user["account_id"], discord_id, discord_name, avatar)



def unbind_registered_discord(discord_id):
    with registered_names.account_lock(USERS_FILE):
        data = users_data()
        removed = ""
        for user in data["users"].values():
            if str(user.get("discord_id") or "") == str(discord_id):
                removed = user.get("name", "")
                import account_discord
                account_discord.unbind(user)
        write_users_data(data)
        return removed


def profile_key(value):
    return " ".join(str(value or "").casefold().split())


def web_profile_for_name(name):
    return users_data().get("users", {}).get(profile_key(name), {})


def bound_name_for_discord(discord_id):
    target = str(discord_id)
    for user in users_data().get("users", {}).values():
        if str(user.get("discord_id") or "") == target:
            return user.get("name", "")
    return ""


def image_from_data_url(data_url):
    if not data_url or "," not in data_url:
        return None
    try:
        payload = data_url.split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGB")
    except Exception:
        return None


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
        return str(value) if value not in ("", None) else "N/A"
    return str(int(number)) if number % 1 == 0 else f"{number:.2f}"


def format_signed_number(value):
    number = safe_float(value)
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}"


def format_rate(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "N/A"

    if number <= 1:
        number *= 100
    return f"{number:.2f}%"


def normalize_name(value):
    return " ".join(str(value).replace("\xa0", " ").casefold().split())


def update_player_cache():
    global _player_name_cache
    try:
        _player_name_cache = player_directory.player_names()
    except Exception as e:
        print(f"PersonalData Cog: SQL player cache failed: {e}")
        _player_name_cache = []


def update_quarter_cache():
    global _quarter_cache
    try:
        with mahjong_store.connect() as connection:
            _quarter_cache = [TOTAL_GAMES_OPTION] + mahjong_store.quarters(connection)
    except Exception as e:
        print(f"PersonalData Cog: SQL quarter cache failed: {e}")
        _quarter_cache = []


async def player_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    await asyncio.to_thread(update_player_cache)
    return [app_commands.Choice(name=name, value=name)
            for name in player_directory.matching_names(_player_name_cache, current)]


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
    row_names = [normalize_name(name) for name in row[0:4]]
    for idx, name in enumerate(row_names):
        if target_name in name:
            return idx
    return None


def find_pt_change(row, target_name):
    if len(row) < 13:
        return None

    for name_idx, score_idx in PT_NAME_SCORE_COLUMNS.items():
        if len(row) > name_idx and target_name in normalize_name(row[name_idx]):
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
            return format_number(mmr_abs_raw)
    return "N/A"


def find_highest_mmr(assigned_rows, target_name):
    highest_mmr = None
    for item in assigned_rows:
        idx = find_player_index(item["row"], target_name)
        if idx is None:
            continue

        row = item["row"]
        mmr_abs_raw = row[12 + idx] if len(row) > 12 + idx else ""
        if not str(mmr_abs_raw).strip():
            continue

        mmr_value = safe_float(mmr_abs_raw, None)
        if mmr_value is None:
            continue
        if highest_mmr is None or mmr_value > highest_mmr:
            highest_mmr = mmr_value

    return format_number(highest_mmr) if highest_mmr is not None else "N/A"


def split_yakuman_names(value):
    names = [name.strip() for name in str(value).replace("，", ",").split(",")]
    return [name for name in names if name]


def get_rank_for_row(row, player_idx):
    scores = [safe_float(row[4 + i], -99999) for i in range(4)]
    return sum(1 for score in scores if score > scores[player_idx]) + 1


def get_yakuman_and_streak_stats(assigned_rows, pt_rows, target_name):
    yakuman_records = []
    max_first_streak = 0
    current_first_streak = 0

    for item in assigned_rows:
        row = item["row"]
        idx = find_player_index(row, target_name)
        if idx is None:
            continue

        try:
            rank = get_rank_for_row(row, idx)
            if rank == 1:
                current_first_streak += 1
                max_first_streak = max(max_first_streak, current_first_streak)
            else:
                current_first_streak = 0
        except Exception:
            current_first_streak = 0

        yakuman_winner = normalize_name(row[YAKUMAN_WINNER_INDEX]) if len(row) > YAKUMAN_WINNER_INDEX else ""
        if yakuman_winner != target_name:
            continue

        yakuman_text = row[YAKUMAN_NAMES_INDEX].strip() if len(row) > YAKUMAN_NAMES_INDEX else ""
        yakuman_names = split_yakuman_names(yakuman_text) or ["Yakuman"]
        pt_row = pt_rows[item["sheet_row"] - 1] if len(pt_rows) >= item["sheet_row"] else []
        game_time = pt_row[0] if pt_row and pt_row[0] else "Unknown time"

        yakuman_records.append({
            "time": game_time,
            "names": yakuman_names,
        })

    yakuman_count = sum(len(record["names"]) for record in yakuman_records)
    return {
        "yakuman_count": yakuman_count,
        "yakuman_records": yakuman_records,
        "max_first_streak": max_first_streak,
    }


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


def get_personal_stats_from_sheet(sh, target_name, sheet_name):
    rows = sh.worksheet(sheet_name).get_all_values()
    for row in rows:
        if row and normalize_name(row[0]) == target_name:
            return {
                "total_pt": row[2] if len(row) > 2 else "N/A",
                "avg_place": row[3] if len(row) > 3 else "N/A",
                "top2_rate": row[4] if len(row) > 4 else "N/A",
                "highest_point": row[5] if len(row) > 5 else "N/A",
                "avg_point": row[6] if len(row) > 6 else "N/A",
                "rate_1st": row[7] if len(row) > 7 else "N/A",
                "rate_2nd": row[8] if len(row) > 8 else "N/A",
                "rate_3rd": row[9] if len(row) > 9 else "N/A",
                "rate_4th": row[10] if len(row) > 10 else "N/A",
                "count_1st": row[11] if len(row) > 11 else "N/A",
                "count_2nd": row[12] if len(row) > 12 else "N/A",
                "count_3rd": row[13] if len(row) > 13 else "N/A",
                "count_4th": row[14] if len(row) > 14 else "N/A",
                "total_games": row[15] if len(row) > 15 else "N/A",
                "source_sheet": sheet_name,
            }
    return None


def get_personal_stats(sh, target_name, quarter):
    if quarter == TOTAL_GAMES_OPTION:
        return get_personal_stats_from_sheet(sh, target_name, "Personal Data"), "Personal Data"

    if quarter:
        sheet_name = f"{quarter} Personal Data"
        return get_personal_stats_from_sheet(sh, target_name, sheet_name), sheet_name

    return get_personal_stats_from_sheet(sh, target_name, "Personal Data Quarter"), "Personal Data Quarter"


def get_personal_detailed_data(player_name, quarter=None):
    try:
        with mahjong_store.connect() as connection:
            summary = mahjong_store.user_summary(connection, player_name, quarter=quarter)
        if summary and summary.get("personal_data"):
            return summary, None
        return None, "Player not found in SQLite data."
    except Exception as e:
        print(f"PersonalData Cog: SQLite personal data failed: {e}")
        return None, str(e)


def get_pt_chart_url(pt_values, title, max_points=MAX_CHART_POINTS):
    if not pt_values or len(pt_values) < 2:
        return None

    cumulative_values = []
    running_total = 0
    for value in pt_values:
        running_total += value
        cumulative_values.append(round(running_total, 2))

    match_step = max(1, math.ceil(len(cumulative_values) / max_points))
    sampled_values = cumulative_values[match_step - 1::match_step]
    sampled_labels = [str(i) for i in range(match_step, len(cumulative_values) + 1, match_step)]

    if sampled_labels and sampled_labels[-1] != str(len(cumulative_values)):
        sampled_values.append(cumulative_values[-1])
        sampled_labels.append(str(len(cumulative_values)))

    sampled_values = [round(value, 2) for value in sampled_values]

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


def format_yakuman_records(yakuman_records, max_records=5):
    if not yakuman_records:
        return "No yakuman records found."

    latest_records = list(reversed(yakuman_records))[:max_records]
    lines = []
    for record in latest_records:
        names = ", ".join(record["names"])
        lines.append(f"`{record['time']}`: {names}")

    hidden_count = len(yakuman_records) - len(latest_records)
    if hidden_count > 0:
        lines.append(f"...and `{hidden_count}` older record(s)")

    return "\n".join(lines)


def scale(value):
    return int(round(value * RENDER_SCALE))


def scale_box(values):
    return tuple(scale(value) for value in values)


def scale_points(points):
    return [(value[0] * RENDER_SCALE, value[1] * RENDER_SCALE) for value in points]


class ScaledDraw:
    def __init__(self, draw):
        self.draw = draw

    def rounded_rectangle(self, xy, radius=0, fill=None, outline=None, width=1):
        self.draw.rounded_rectangle(scale_box(xy), radius=scale(radius), fill=fill, outline=outline, width=scale(width))

    def ellipse(self, xy, fill=None, outline=None, width=1):
        self.draw.ellipse(scale_box(xy), fill=fill, outline=outline, width=scale(width))

    def text(self, xy, text, fill=None, font=None, anchor=None):
        self.draw.text((xy[0] * RENDER_SCALE, xy[1] * RENDER_SCALE), text, fill=fill, font=font, anchor=anchor)

    def polygon(self, xy, fill=None, outline=None):
        self.draw.polygon(scale_points(xy), fill=fill, outline=outline)

    def line(self, xy, fill=None, width=1, joint=None):
        kwargs = {"fill": fill, "width": scale(width)}
        if joint is not None:
            kwargs["joint"] = joint
        self.draw.line(scale_points(xy), **kwargs)


def load_font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, scale(size))
        except OSError:
            continue
    return ImageFont.load_default()


def rounded_box(draw, xy, fill, outline="#e5e7eb", radius=24, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_metric(draw, x, y, w, h, label, value, percent=60, note=""):
    rounded_box(draw, (x, y, x + w, y + h), "#f8fafc", "#e2e8f0", radius=18)
    draw.text((x + 18, y + 14), label, fill="#64748b", font=load_font(16, True))
    draw.text((x + 18, y + 48), str(value), fill="#0f172a", font=load_font(28, True))
    if note:
        draw.text((x + w - 70, y + 54), note, fill="#ef4444", font=load_font(18, True))
    bar_x, bar_y = x + 18, y + h - 22
    draw.rounded_rectangle((bar_x, bar_y, x + w - 18, bar_y + 8), radius=4, fill="#dbeafe")
    draw.rounded_rectangle((bar_x, bar_y, bar_x + int((w - 36) * max(0, min(100, float(percent))) / 100), bar_y + 8), radius=4, fill="#14b8a6")


def draw_radar_panel(draw, personal):
    labels = ["Strength", "PT Eff.", "Placement", "Attack", "Defense", "Recent"]
    raw_values = list((personal.get("radar") or {}).values())
    defaults = [65, 58, 62, 50, 72, 55]
    values = []
    for index in range(6):
        try:
            number = float(raw_values[index])
        except (IndexError, TypeError, ValueError):
            number = defaults[index]
        if number <= 1:
            number *= 100
        values.append(max(0, min(100, number)))

    cx, cy, radius = 385, 622, 114
    for scale in (0.33, 0.66, 1.0):
        grid = []
        for index in range(6):
            angle = -math.pi / 2 + index * math.pi * 2 / 6
            grid.append((cx + math.cos(angle) * radius * scale, cy + math.sin(angle) * radius * scale))
        draw.polygon(grid, outline="#dbeafe")

    points = []
    for index, value in enumerate(values):
        angle = -math.pi / 2 + index * math.pi * 2 / 6
        label_x = cx + math.cos(angle) * (radius + 54)
        label_y = cy + math.sin(angle) * (radius + 34)
        draw.text((label_x, label_y), labels[index], fill="#475569", font=load_font(15, True), anchor="mm")
        points.append((cx + math.cos(angle) * radius * value / 100, cy + math.sin(angle) * radius * value / 100))

    draw.polygon(points, fill="#93c5fd", outline="#4f6fca")
    draw.line(points + [points[0]], fill="#4f6fca", width=4)
    for x, y in points:
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill="#4f6fca", outline="white", width=2)


def render_personal_data_image(summary):
    personal = summary.get("personal_data") or {}
    name = summary.get("name", "Player")
    W, H = 1600 * RENDER_SCALE, 900 * RENDER_SCALE
    image = Image.new("RGB", (W, H), "#f1f5f9")
    draw = ScaledDraw(ImageDraw.Draw(image))
    big_font = load_font(64, True)
    normal = load_font(22)

    rounded_box(draw, (40, 36, 730, 350), "#ffffff", "#e5e7eb", radius=24)
    draw.ellipse((70, 76, 260, 266), fill="#cffafe", outline="#64748b", width=3)
    avatar = image_from_data_url((summary.get("profile") or {}).get("avatar", ""))
    if avatar:
        avatar = avatar.resize((scale(190), scale(190)), Image.Resampling.LANCZOS)
        mask = Image.new("L", (scale(190), scale(190)), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, scale(190), scale(190)), fill=255)
        image.paste(avatar, (scale(70), scale(76)), mask)
    else:
        initials = "".join(part[:1] for part in name.split()[:2]).upper()[:2] or "MJ"
        draw.text((165, 171), initials, fill="#0d9488", font=big_font, anchor="mm")
    draw.rounded_rectangle((284, 74, 535, 116), radius=10, fill="#0d9488")
    draw.text((305, 82), f"MMR {personal.get('mmr_value', '--')}", fill="white", font=load_font(26, True))
    draw.rounded_rectangle((545, 74, 712, 116), radius=10, fill="#0d9488")
    draw.text((565, 82), str(personal.get("scope", "Current")), fill="white", font=load_font(23, True))
    draw.text((284, 142), name, fill="#1f2937", font=load_font(46, True))
    stat_items = [
        ("MMR rank", f"#{personal.get('mmr_rank', '--')} / {personal.get('mmr_rank_total', '--')}"),
        ("PT rank", f"#{personal.get('pt_rank', '--')} / {personal.get('pt_rank_total', '--')}"),
        ("Games", personal.get("selected_game_count", "--")),
        ("Yakuman", personal.get("yakuman_count", 0)),
    ]
    for stat_x, (stat_label, stat_value) in zip((284, 410, 536, 642), stat_items):
        draw.text((stat_x, 260), stat_label, fill="#64748b", font=load_font(15, True))
        draw.text((stat_x, 286), str(stat_value), fill="#1f2937", font=load_font(21, True))

    rounded_box(draw, (758, 36, 1560, 350), "#ffffff", "#e5e7eb", radius=24)
    draw.text((790, 58), "Key Metrics", fill="#1f2937", font=load_font(28, True))
    draw_metric(draw, 790, 106, 230, 100, "MMR", personal.get("mmr_value", "--"), 75, f"#{personal.get('mmr_rank', '--')}")
    draw_metric(draw, 1040, 106, 230, 100, "PT", f"{personal.get('pt_value', '--')}", 70, f"#{personal.get('pt_rank', '--')}")
    draw_metric(draw, 1290, 106, 230, 100, "Avg place", personal.get("avg_place", "--"), 60)
    draw_metric(draw, 790, 226, 230, 100, "Top 2 rate", f"{personal.get('top2_rate', '--')}%", personal.get("top2_rate", 0))
    draw_metric(draw, 1040, 226, 230, 100, "Avoid 4th", f"{personal.get('avoid_last_rate', '--')}%", personal.get("avoid_last_rate", 0))
    draw_metric(draw, 1290, 226, 230, 100, "High score", personal.get("highest_point", "--"), 100)

    rounded_box(draw, (40, 388, 730, 838), "#ffffff", "#e5e7eb", radius=24)
    draw.text((76, 420), "Six-Dimension Radar", fill="#1f2937", font=load_font(28, True))
    draw_radar_panel(draw, personal)

    rounded_box(draw, (758, 388, 1560, 838), "#ffffff", "#e5e7eb", radius=24)
    draw.text((790, 420), "Record Trend", fill="#1f2937", font=load_font(28, True))
    history = personal.get("history") or []
    if len(history) >= 2:
        values = [float(item.get("cumulative_pt") or 0) for item in history]
        mn, mx = min(values), max(values)
        span = mx - mn or 1
        pts = []
        for idx, value in enumerate(values):
            x = 805 + idx / max(1, len(values) - 1) * 700
            y = 780 - (value - mn) / span * 290
            pts.append((x, y))
        draw.line(pts, fill="#14b8a6", width=5, joint="curve")
        for x, y in pts[::max(1, len(pts)//18)]:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#0f766e")
        draw.text((805, 790), f"PT {values[0]:+.1f} -> {values[-1]:+.1f}", fill="#475569", font=normal)
    else:
        draw.text((805, 520), "Not enough games for a trend chart.", fill="#64748b", font=normal)

    yakuman = personal.get("yakuman_records") or []
    draw.text((76, 760), "Recent Yakuman", fill="#1f2937", font=load_font(26, True))
    if yakuman:
        text = " | ".join(f"{item.get('time', '')}: {', '.join(item.get('names', []))}" for item in yakuman[-3:])
    else:
        text = "No yakuman in this scope."
    draw.text((76, 800), text[:78], fill="#475569", font=load_font(18))

    output = io.BytesIO()
    image = image.resize((1600, 900), Image.Resampling.LANCZOS)
    image.save(output, "PNG")
    output.seek(0)
    return output


class PersonalData(commands.Cog):
    def __init__(self, client):
        self.client = client
        try:
            update_player_cache()
            update_quarter_cache()
        except Exception as e:
            print(f"PersonalData Cog: SQL cache failed: {e}")

    @app_commands.command(name="personal_data", description="Query detailed personal data")
    @app_commands.describe(
        player_name="Optional player name. Leave blank to use your bound web account.",
        quarter="Optional: Total games or a quarter like 2025 Spring. Leave blank for latest 15 games.",
    )
    @app_commands.autocomplete(player_name=player_name_autocomplete, quarter=quarter_autocomplete)
    async def personal_data(
        self,
        interaction: discord.Interaction,
        player_name: Optional[str] = None,
        quarter: Optional[str] = None,
    ):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False)

        if not player_name:
            player_name = bound_name_for_discord(interaction.user.id)
            if not player_name:
                await interaction.followup.send("No web account is bound to your Discord yet. Use `/bind_web_account player_name:<your web account name>` first.", ephemeral=True)
                return

        data, error = await asyncio.to_thread(get_personal_detailed_data, player_name, quarter)
        if data is None:
            await interaction.followup.send(content=f"Error: {error}")
            return
        data["profile"] = web_profile_for_name(data.get("name", player_name))
        image = await asyncio.to_thread(render_personal_data_image, data)
        file = discord.File(image, filename="personal_data.png")
        personal = data.get("personal_data") or {}
        await interaction.followup.send(
            content=f"Personal data for **{data.get('name', player_name)}** · {personal.get('scope', 'Current quarter')}",
            file=file,
        )

    @app_commands.command(name="bind_web_account", description="Bind your Discord account to a UCSD Mahjong web account")
    @app_commands.describe(player_name="Your web account/player name")
    @app_commands.autocomplete(player_name=player_name_autocomplete)
    async def bind_web_account(self, interaction: discord.Interaction, player_name: str):
        await interaction.response.defer(ephemeral=True)
        player_name = (player_name or "").strip()
        if not player_name:
            await interaction.followup.send("Please enter a player name.", ephemeral=True)
            return
        avatar = ""
        try:
            avatar_bytes = await interaction.user.display_avatar.with_size(256).read()
            avatar = "data:image/png;base64," + base64.b64encode(avatar_bytes).decode("ascii")
        except Exception as error:
            print(f"PersonalData Cog: Discord avatar sync failed: {error}")
        try:
            name = bind_registered_discord(player_name, interaction.user.id, str(interaction.user), avatar)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await interaction.followup.send(f"Bound Discord account to web player `{name}`.", ephemeral=True)

    @app_commands.command(name="unbind_web_account", description="Unbind your Discord account from the web dashboard")
    async def unbind_web_account(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        removed = unbind_registered_discord(interaction.user.id)
        await interaction.followup.send(f"Unbound `{removed}`." if removed else "No bound web account was found.", ephemeral=True)


async def setup(client):
    await client.add_cog(PersonalData(client))
