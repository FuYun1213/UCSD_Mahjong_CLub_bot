from __future__ import annotations

from typing import Dict, List, Optional

import discord
from discord.ui import View, Select, Button, Modal, TextInput

from .tile import (
    HandTiles,
    PACK_TYPE_CHOW,
    PACK_TYPE_KONG,
    PACK_TYPE_PUNG,
    TILE_E, TILE_S, TILE_W, TILE_N, TILE_C, TILE_F, TILE_P,
    ALL_TILES,
    make_pack,
    string_to_tile,
    tile_to_string,
)
from .fan_calculator import (
    CalculateParam,
    Wind,
    calculate_fan,
    FAN_NAME_EN,
    FAN_TABLE_SIZE,
    WIN_FLAG_SELF_DRAWN,
    WIN_FLAG_LAST_TILE,
    WIN_FLAG_KONG_INVOLVED,
    WIN_FLAG_WALL_LAST,
    WIN_FLAG_INITIAL,
)
from .shanten import is_waiting


_SUIT_OPTIONS = {
    "m": [f"{i}m" for i in range(1, 10)],
    "s": [f"{i}s" for i in range(1, 10)],
    "p": [f"{i}p" for i in range(1, 10)],
    "h": ["E", "S", "W", "N", "C", "F", "P"],
}


def _tile_counts(tiles: List[int]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for t in tiles:
        counts[t] = counts.get(t, 0) + 1
    return counts


def _format_hand(tiles: List[int]) -> str:
    if not tiles:
        return "[]"
    return " ".join(tile_to_string(t) for t in sorted(tiles))


class _TileSelect(Select):
    def __init__(self, label: str, tokens: List[str], row: int, parent: "McrCalculatorView"):
        options = [discord.SelectOption(label=t, value=t) for t in tokens]
        super().__init__(placeholder=label, options=options, min_values=1, max_values=min(9, len(options)), row=row)
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.handle_tile_select(interaction, self.values)


class FlowerModal(Modal):
    def __init__(self, parent: "McrSettingsView"):
        super().__init__(title="Set Flower Count")
        self.parent_view = parent
        self.count_input = TextInput(label="Flower count (0-8)", placeholder="0", required=True, max_length=2)
        self.add_item(self.count_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.count_input.value.strip())
        except ValueError:
            await interaction.response.send_message("Invalid flower count.", ephemeral=True)
            return
        if count < 0 or count > 8:
            await interaction.response.send_message("Flower count must be 0-8.", ephemeral=True)
            return
        self.parent_view.parent_view.flower_count = count
        await self.parent_view.parent_view.refresh(interaction, notice="Flower count updated.")


class MeldModal(Modal):
    def __init__(self, parent: "McrSettingsView"):
        super().__init__(title="Add Meld")
        self.parent_view = parent
        self.type_input = TextInput(label="Type (chow/pung/kong)", placeholder="chow", required=True, max_length=8)
        self.tile_input = TextInput(label="Tile (e.g., 5m or E)", placeholder="5m", required=True, max_length=2)
        self.offer_input = TextInput(label="Offer (0-3, optional)", placeholder="0", required=False, max_length=1)
        self.add_item(self.type_input)
        self.add_item(self.tile_input)
        self.add_item(self.offer_input)

    async def on_submit(self, interaction: discord.Interaction):
        t_str = self.tile_input.value.strip()
        meld_type = self.type_input.value.strip().lower()
        offer = 0
        if self.offer_input.value.strip():
            try:
                offer = int(self.offer_input.value.strip())
            except ValueError:
                await interaction.response.send_message("Offer must be a number 0-3.", ephemeral=True)
                return
        tile = string_to_tile(t_str)
        if tile is None:
            await interaction.response.send_message("Invalid tile token.", ephemeral=True)
            return
        if meld_type == "chow":
            pack_type = PACK_TYPE_CHOW
        elif meld_type == "pung":
            pack_type = PACK_TYPE_PUNG
        elif meld_type == "kong":
            pack_type = PACK_TYPE_KONG
        else:
            await interaction.response.send_message("Type must be chow/pung/kong.", ephemeral=True)
            return
        parent = self.parent_view.parent_view
        if parent.pack_count >= 4:
            await interaction.response.send_message("Maximum 4 melds.", ephemeral=True)
            return
        parent.fixed_packs.append(make_pack(offer, pack_type, tile))
        parent.pack_count += 1
        await parent.refresh(interaction, notice="Meld added.")


class McrSettingsView(View):
    def __init__(self, parent_view: "McrCalculatorView"):
        super().__init__(timeout=600)
        self.parent_view = parent_view

        self.add_item(_WindSelect("Seat Wind", row=0, is_seat=True, parent=self))
        self.add_item(_WindSelect("Prevalent Wind", row=1, is_seat=False, parent=self))

        self.add_item(_ToggleButton("Self Drawn", row=2, flag=WIN_FLAG_SELF_DRAWN, parent=self))
        self.add_item(_ToggleButton("Last Tile", row=2, flag=WIN_FLAG_LAST_TILE, parent=self))
        self.add_item(_ToggleButton("Initial", row=2, flag=WIN_FLAG_INITIAL, parent=self))

        self.add_item(_ToggleButton("Kong Involved", row=3, flag=WIN_FLAG_KONG_INVOLVED, parent=self))
        self.add_item(_ToggleButton("Wall Last", row=3, flag=WIN_FLAG_WALL_LAST, parent=self))
        self.add_item(_ActionButton("Add Meld", row=3, action="meld", parent=self))

        self.add_item(_ActionButton("Flowers", row=4, action="flowers", parent=self))
        self.add_item(_ActionButton("Clear", row=4, action="clear", parent=self))
        self.add_item(_ActionButton("Back", row=4, action="back", parent=self))


class _WindSelect(Select):
    def __init__(self, label: str, row: int, is_seat: bool, parent: McrSettingsView):
        options = [
            discord.SelectOption(label="East", value="E"),
            discord.SelectOption(label="South", value="S"),
            discord.SelectOption(label="West", value="W"),
            discord.SelectOption(label="North", value="N"),
        ]
        super().__init__(placeholder=label, options=options, min_values=1, max_values=1, row=row)
        self.is_seat = is_seat
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        wind = {"E": Wind.EAST, "S": Wind.SOUTH, "W": Wind.WEST, "N": Wind.NORTH}[val]
        if self.is_seat:
            self.parent_view.parent_view.seat_wind = wind
        else:
            self.parent_view.parent_view.prevalent_wind = wind
        await self.parent_view.parent_view.refresh(interaction, notice="Wind updated.")


class _ToggleButton(Button):
    def __init__(self, label: str, row: int, flag: int, parent: McrSettingsView):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row)
        self.flag = flag
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        parent = self.parent_view.parent_view
        parent.win_flag ^= self.flag
        await parent.refresh(interaction, notice="Flags updated.")


class _ActionButton(Button):
    def __init__(self, label: str, row: int, action: str, parent: McrSettingsView):
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=row)
        self.action = action
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        parent = self.parent_view.parent_view
        if self.action == "back":
            await parent.refresh(interaction, use_settings=False)
            return
        if self.action == "clear":
            parent.reset_state()
            await parent.refresh(interaction, notice="Cleared.")
            return
        if self.action == "flowers":
            await interaction.response.send_modal(FlowerModal(self.parent_view))
            return
        if self.action == "meld":
            await interaction.response.send_modal(MeldModal(self.parent_view))
            return


class McrCalculatorView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.hand_tiles: List[int] = []
        self.fixed_packs: List[int] = []
        self.pack_count = 0
        self.win_tile: Optional[int] = None
        self.mode: str = "add"
        self.win_flag = 0
        self.prevalent_wind = Wind.EAST
        self.seat_wind = Wind.EAST
        self.flower_count = 0
        self._build_selects()

    def reset_state(self) -> None:
        self.hand_tiles = []
        self.fixed_packs = []
        self.pack_count = 0
        self.win_tile = None
        self.mode = "add"
        self.win_flag = 0
        self.prevalent_wind = Wind.EAST
        self.seat_wind = Wind.EAST
        self.flower_count = 0

    def _build_selects(self) -> None:
        self.add_item(_TileSelect("Characters (m)", _SUIT_OPTIONS["m"], row=0, parent=self))
        self.add_item(_TileSelect("Bamboo (s)", _SUIT_OPTIONS["s"], row=1, parent=self))
        self.add_item(_TileSelect("Dots (p)", _SUIT_OPTIONS["p"], row=2, parent=self))
        self.add_item(_TileSelect("Honors", _SUIT_OPTIONS["h"], row=3, parent=self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    async def handle_tile_select(self, interaction: discord.Interaction, values: List[str]) -> None:
        tiles = []
        for token in values:
            t = string_to_tile(token)
            if t is not None:
                tiles.append(t)

        if self.mode == "win":
            if tiles:
                self.win_tile = tiles[0]
                self.mode = "add"
                await self.refresh(interaction, notice="Win tile set.")
                return
        elif self.mode == "remove":
            counts = _tile_counts(self.hand_tiles)
            for t in tiles:
                if counts.get(t, 0) > 0:
                    self.hand_tiles.remove(t)
            await self.refresh(interaction, notice="Tiles removed.")
            return

        max_tiles = 13 - self.pack_count * 3
        counts = _tile_counts(self.hand_tiles)
        for t in tiles:
            if len(self.hand_tiles) >= max_tiles:
                break
            if counts.get(t, 0) >= 4:
                continue
            self.hand_tiles.append(t)
            counts[t] = counts.get(t, 0) + 1
        await self.refresh(interaction, notice="Tiles added.")

    async def refresh(self, interaction: discord.Interaction, notice: Optional[str] = None, use_settings: bool = False) -> None:
        content = self.render_status()
        if notice:
            content = f"{notice}\n\n{content}"
        view = McrSettingsView(self) if use_settings else self
        if interaction.response.is_done():
            await interaction.followup.send(content=content, view=view, ephemeral=True)
        else:
            await interaction.response.edit_message(content=content, view=view)

    def render_status(self) -> str:
        max_tiles = 13 - self.pack_count * 3
        wind_map = {Wind.EAST: "East", Wind.SOUTH: "South", Wind.WEST: "West", Wind.NORTH: "North"}
        flags = []
        if self.win_flag & WIN_FLAG_SELF_DRAWN:
            flags.append("SelfDrawn")
        if self.win_flag & WIN_FLAG_LAST_TILE:
            flags.append("LastTile")
        if self.win_flag & WIN_FLAG_KONG_INVOLVED:
            flags.append("Kong")
        if self.win_flag & WIN_FLAG_WALL_LAST:
            flags.append("WallLast")
        if self.win_flag & WIN_FLAG_INITIAL:
            flags.append("Initial")
        win_tile = tile_to_string(self.win_tile) if self.win_tile else "None"
        return (
            f"Mode: {self.mode}\n"
            f"Standing tiles ({len(self.hand_tiles)}/{max_tiles}): {_format_hand(self.hand_tiles)}\n"
            f"Win tile: {win_tile}\n"
            f"Melds: {self.pack_count}\n"
            f"Winds: seat={wind_map[self.seat_wind]}, prevalent={wind_map[self.prevalent_wind]}\n"
            f"Flags: {', '.join(flags) if flags else 'None'} | Flowers: {self.flower_count}"
        )

    async def handle_action(self, interaction: discord.Interaction, action: str) -> None:
        if action == "mode_remove":
            self.mode = "remove" if self.mode != "remove" else "add"
            await self.refresh(interaction, notice=f"Mode set to {self.mode}.")
            return
        if action == "mode_win":
            self.mode = "win"
            await self.refresh(interaction, notice="Select a tile to set as win tile.")
            return
        if action == "settings":
            await self.refresh(interaction, use_settings=True)
            return
        if action == "check_wait":
            await self.handle_check_wait(interaction)
            return
        if action == "calc_fan":
            await self.handle_calc_fan(interaction)
            return

    @discord.ui.button(label="Remove Mode", style=discord.ButtonStyle.secondary, row=4)
    async def _btn_remove(self, interaction: discord.Interaction, button: Button):
        await self.handle_action(interaction, "mode_remove")

    @discord.ui.button(label="Set Win Tile", style=discord.ButtonStyle.secondary, row=4)
    async def _btn_win(self, interaction: discord.Interaction, button: Button):
        await self.handle_action(interaction, "mode_win")

    @discord.ui.button(label="Check Waiting", style=discord.ButtonStyle.primary, row=4)
    async def _btn_wait(self, interaction: discord.Interaction, button: Button):
        await self.handle_action(interaction, "check_wait")

    @discord.ui.button(label="Calculate Fan", style=discord.ButtonStyle.success, row=4)
    async def _btn_calc(self, interaction: discord.Interaction, button: Button):
        await self.handle_action(interaction, "calc_fan")

    @discord.ui.button(label="Settings", style=discord.ButtonStyle.secondary, row=4)
    async def _btn_settings(self, interaction: discord.Interaction, button: Button):
        await self.handle_action(interaction, "settings")

    async def handle_check_wait(self, interaction: discord.Interaction) -> None:
        max_tiles = 13 - self.pack_count * 3
        if len(self.hand_tiles) != max_tiles:
            await interaction.response.send_message(f"Need {max_tiles} standing tiles to check waiting.", ephemeral=True)
            return
        hand = HandTiles(self.fixed_packs, self.pack_count, list(self.hand_tiles), len(self.hand_tiles))
        useful = [False] * 0x48
        is_wait = is_waiting(hand, useful)
        if not is_wait:
            await interaction.response.send_message("Not in tenpai.", ephemeral=True)
            return
        waits = [tile_to_string(t) for t in ALL_TILES if useful[t]]
        await interaction.response.send_message(f"Waiting tiles: {' '.join(waits)}", ephemeral=True)

    async def handle_calc_fan(self, interaction: discord.Interaction) -> None:
        max_tiles = 13 - self.pack_count * 3
        if len(self.hand_tiles) != max_tiles:
            await interaction.response.send_message(f"Need {max_tiles} standing tiles.", ephemeral=True)
            return
        if self.win_tile is None:
            await interaction.response.send_message("Set a win tile first.", ephemeral=True)
            return
        hand = HandTiles(self.fixed_packs, self.pack_count, list(self.hand_tiles), len(self.hand_tiles))
        param = CalculateParam(
            hand_tiles=hand,
            win_tile=self.win_tile,
            flower_count=self.flower_count,
            win_flag=self.win_flag,
            prevalent_wind=self.prevalent_wind,
            seat_wind=self.seat_wind,
        )
        fan_table = [0] * FAN_TABLE_SIZE
        total_fan = calculate_fan(param, fan_table)
        if total_fan < 0:
            await interaction.response.send_message("Hand is not a winning hand.", ephemeral=True)
            return
        details = []
        for i in range(1, FAN_TABLE_SIZE):
            if fan_table[i]:
                name = FAN_NAME_EN[i] if i < len(FAN_NAME_EN) else f"Fan {i}"
                count = fan_table[i]
                details.append(f"{name} x{count}")
        detail_text = "\n".join(details) if details else "No fan details."
        await interaction.response.send_message(f"Total fan: {total_fan}\n{detail_text}", ephemeral=True)

