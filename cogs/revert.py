import asyncio
from datetime import datetime
from typing import Any, Dict, List

import discord
import gspread
from discord import app_commands
from discord.ext import commands

import mahjong_store
from bot_action_log import get_action, get_recent_actions_for_user, mark_reverted


SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q"
CREDENTIALS_FILE = "credentials.json"
DB_FILE = "mahjong.sqlite3"
RATINGS_NAME_COLUMN = 1
RATINGS_MMR_COLUMN = 2

_gc = None
_sh = None


def get_sheet():
    global _gc, _sh
    if _sh is None:
        _gc = gspread.service_account(filename=CREDENTIALS_FILE)
        _sh = _gc.open_by_key(SHEET_ID)
    return _sh


def format_action_time(created_at: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return created_at or "unknown time"


def values_match(current: List[Any], expected: List[Any]) -> bool:
    expected_strings = [str(value) for value in expected]
    return current[: len(expected_strings)] == expected_strings


def resolve_logged_row(worksheet, row_number: int, expected: List[Any], sheet_name: str) -> int:
    if row_number < 2:
        raise ValueError(f"Refusing to revert row {row_number} in {sheet_name}.")

    if values_match(worksheet.row_values(row_number), expected):
        return row_number

    for index, row in enumerate(worksheet.get_all_values(), start=1):
        if index >= 2 and values_match(row, expected):
            return index

    raise ValueError(
        f"{sheet_name} row {row_number} no longer matches the logged action, "
        "and I could not find a matching row elsewhere. Nothing was changed."
    )


def delete_logged_row(worksheet, row_number: int, expected: List[Any], sheet_name: str) -> None:
    resolved_row = resolve_logged_row(worksheet, row_number, expected, sheet_name)
    worksheet.delete_rows(resolved_row)


def revert_record_game(action: Dict[str, Any]) -> str:
    payload = action.get("payload", {})
    sh = get_sheet()

    ws_riichi = sh.worksheet("Games Riichi")
    ws_pt = sh.worksheet("Games/pt")

    riichi_row = int(payload["games_riichi_row"])
    pt_row = int(payload["games_pt_row"])
    riichi_values = payload["games_riichi_values"]
    pt_values = payload["games_pt_values"]

    resolved_riichi_row = resolve_logged_row(ws_riichi, riichi_row, riichi_values, "Games Riichi")
    resolved_pt_row = resolve_logged_row(ws_pt, pt_row, pt_values, "Games/pt")

    sql_message = ""
    sql_game_id = payload.get("sql_game_id")
    if sql_game_id:
        with mahjong_store.connect(DB_FILE) as connection:
            reverted_names = mahjong_store.revert_game(connection, int(sql_game_id))
        sql_message = f" SQL record reverted for {', '.join(reverted_names)}."

    ws_riichi.delete_rows(resolved_riichi_row)
    ws_pt.delete_rows(resolved_pt_row)

    return f"Reverted game record: {action.get('summary', 'recorded game')}.{sql_message}"


def safe_float(value: Any) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(str(value).replace("+", "").strip())
    except (TypeError, ValueError):
        return 0.0


def build_mmr_rollbacks(worksheet, players: List[Any], deltas: List[Any]) -> List[Dict[str, Any]]:
    rating_rows = worksheet.get_all_values()
    player_to_row = {
        row[0].strip().lower(): index
        for index, row in enumerate(rating_rows, start=1)
        if row and row[0].strip()
    }

    updates = []
    for player, delta in zip(players, deltas):
        player_name = str(player).strip()
        if not player_name:
            continue

        row_number = player_to_row.get(player_name.lower())
        if not row_number:
            raise ValueError(f"Could not find {player_name} in Ratings.")

        current_mmr = safe_float(worksheet.cell(row_number, RATINGS_MMR_COLUMN).value)
        mmr_delta = safe_float(delta)
        updates.append({
            "player": player_name,
            "row": row_number,
            "new_mmr": current_mmr - mmr_delta,
        })
    return updates


def apply_mmr_rollbacks(worksheet, updates: List[Dict[str, Any]]) -> None:
    for update in updates:
        worksheet.update_cell(update["row"], RATINGS_MMR_COLUMN, update["new_mmr"])


def revert_register(action: Dict[str, Any]) -> str:
    payload = action.get("payload", {})
    sh = get_sheet()
    ws = sh.worksheet("Ratings")

    row_number = int(payload["ratings_row"])
    row_values = payload["ratings_values"]
    delete_logged_row(ws, row_number, row_values, "Ratings")

    return f"Reverted registration: {action.get('summary', 'registered player')}"


def perform_revert(action_id: str, user_id: int) -> str:
    action = get_action(action_id)
    if not action:
        raise ValueError("I could not find that logged action.")
    if action.get("user_id") != str(user_id):
        raise ValueError("You can only revert actions that you created.")
    if action.get("reverted_at"):
        raise ValueError("That action was already reverted.")

    action_type = action.get("action_type")
    if action_type == "record_game":
        result = revert_record_game(action)
    elif action_type == "register":
        result = revert_register(action)
    else:
        raise ValueError(f"Revert is not supported for action type: {action_type}")

    mark_reverted(action_id, user_id)
    return result


class RevertSelect(discord.ui.Select):
    def __init__(self, actions: List[Dict[str, Any]]):
        options = []
        for action in actions:
            label = action.get("summary", "Unknown action")[:100]
            created_at = format_action_time(action.get("created_at", ""))
            description = f"{created_at} | {action.get('action_type', 'action')}"[:100]
            options.append(discord.SelectOption(label=label, description=description, value=action["id"]))

        super().__init__(
            placeholder="Choose one of your latest 5 actions to revert",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        action_id = self.values[0]

        try:
            message = await asyncio.to_thread(perform_revert, action_id, interaction.user.id)
            for child in self.view.children:
                child.disabled = True
            await interaction.edit_original_response(content=f"Done. {message}", view=self.view)
        except Exception as e:
            await interaction.followup.send(f"Could not revert this action: {e}", ephemeral=True)


class RevertView(discord.ui.View):
    def __init__(self, actions: List[Dict[str, Any]], owner_id: int):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.add_item(RevertSelect(actions))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This revert menu belongs to someone else.", ephemeral=True)
            return False
        return True


class Revert(commands.Cog):
    def __init__(self, client):
        self.client = client

    @app_commands.command(name="revert", description="Choose one of your latest 5 bot actions to undo in Google Sheets")
    async def revert(self, interaction: discord.Interaction):
        actions = get_recent_actions_for_user(interaction.user.id, limit=5)
        if not actions:
            await interaction.response.send_message(
                "I do not have any unreverted actions logged for you yet. "
                "Only actions recorded after this feature was added can be reverted.",
                ephemeral=True,
            )
            return

        lines = []
        for index, action in enumerate(actions, 1):
            lines.append(f"{index}. {format_action_time(action.get('created_at', ''))} - {action.get('summary')}")

        await interaction.response.send_message(
            "Choose what to revert:\n" + "\n".join(lines),
            view=RevertView(actions, interaction.user.id),
            ephemeral=True,
        )


async def setup(client):
    await client.add_cog(Revert(client))
