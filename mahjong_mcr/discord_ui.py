from __future__ import annotations

from typing import Dict, List, Optional

import discord
from discord.ui import View, Button, Modal, TextInput

from .tile import (
    HandTiles,
    PACK_TYPE_CHOW,
    PACK_TYPE_KONG,
    PACK_TYPE_PUNG,
    ALL_TILES,
    make_pack,
    string_to_tile,
    tile_to_string,
    pack_get_offer,
    pack_get_tile,
    pack_get_type,
    tile_get_rank,
    is_numbered_suit,
)
from .fan_calculator import (
    CalculateParam,
    Wind,
    calculate_fan,
    FAN_NAME_ZH,
    FAN_TABLE_SIZE,
    WIN_FLAG_SELF_DRAWN,
    WIN_FLAG_LAST_TILE,
    WIN_FLAG_KONG_INVOLVED,
    WIN_FLAG_WALL_LAST,
    WIN_FLAG_INITIAL,
)
from .shanten import is_waiting


_TILE_PAGE = {
    "m": [(f"{i}m", f"{i}m") for i in range(1, 10)],
    "s": [(f"{i}s", f"{i}s") for i in range(1, 10)],
    "p": [(f"{i}p", f"{i}p") for i in range(1, 10)],
    "h": [("东", "E"), ("南", "S"), ("西", "W"), ("北", "N"), ("白", "P"), ("发", "F"), ("中", "C")],
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


def _tile_display(token: str) -> str:
    honor_map = {"E": "东", "S": "南", "W": "西", "N": "北", "P": "白", "F": "发", "C": "中"}
    return honor_map.get(token, token)


def _pack_tiles(pack: int) -> List[int]:
    tile = pack_get_tile(pack)
    pack_type = pack_get_type(pack)
    if pack_type == PACK_TYPE_CHOW:
        return [tile - 1, tile, tile + 1]
    if pack_type == PACK_TYPE_PUNG:
        return [tile, tile, tile]
    if pack_type == PACK_TYPE_KONG:
        return [tile, tile, tile, tile]
    return []


def _tiles_to_pack_string(tiles: List[int]) -> str:
    if not tiles:
        return ""
    token = tile_to_string(tiles[0])
    if len(token) == 1:
        return "".join(tile_to_string(t) for t in tiles)
    suit = token[1]
    ranks = "".join(tile_to_string(t)[0] for t in tiles)
    return f"{ranks}{suit}"


def _format_packs(packs: List[int]) -> str:
    if not packs:
        return "[]"
    groups = []
    for pack in packs:
        tiles = _pack_tiles(pack)
        pack_type = pack_get_type(pack)
        offer = pack_get_offer(pack)
        text = _tiles_to_pack_string(tiles)
        if pack_type in (PACK_TYPE_CHOW, PACK_TYPE_PUNG):
            if offer != 1:
                text = f"{text}{offer}"
        elif pack_type == PACK_TYPE_KONG:
            if offer != 0:
                text = f"{text}{offer}"
        groups.append(f"[{text}]")
    return " ".join(groups)


class FlowerModal(Modal):
    def __init__(self, parent: "McrSettingsView"):
        super().__init__(title="设置花牌数")
        self.parent_view = parent
        self.count_input = TextInput(label="花牌数 (0-8)", placeholder="0", required=True, max_length=2)
        self.add_item(self.count_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.count_input.value.strip())
        except ValueError:
            await interaction.response.send_message("花牌数无效。", ephemeral=True)
            return
        if count < 0 or count > 8:
            await interaction.response.send_message("花牌数范围 0-8。", ephemeral=True)
            return
        self.parent_view.parent_view.flower_count = count
        await self.parent_view.parent_view.refresh(interaction, notice="花牌数已更新。", use_settings=True)


class McrSettingsView(View):
    def __init__(self, parent_view: "McrCalculatorView"):
        super().__init__(timeout=600)
        self.parent_view = parent_view

        self.add_item(_WindSelect("门风", row=0, is_seat=True, parent=self))
        self.add_item(_WindSelect("圈风", row=1, is_seat=False, parent=self))

        flags = self.parent_view.win_flag
        self.add_item(_ToggleButton("自摸", row=2, flag=WIN_FLAG_SELF_DRAWN, parent=self, active=bool(flags & WIN_FLAG_SELF_DRAWN)))
        self.add_item(_ToggleButton("绝张", row=2, flag=WIN_FLAG_LAST_TILE, parent=self, active=bool(flags & WIN_FLAG_LAST_TILE)))
        self.add_item(_ToggleButton("起手", row=2, flag=WIN_FLAG_INITIAL, parent=self, active=bool(flags & WIN_FLAG_INITIAL)))

        self.add_item(_ToggleButton("杠相关", row=3, flag=WIN_FLAG_KONG_INVOLVED, parent=self, active=bool(flags & WIN_FLAG_KONG_INVOLVED)))
        self.add_item(_ToggleButton("海底", row=3, flag=WIN_FLAG_WALL_LAST, parent=self, active=bool(flags & WIN_FLAG_WALL_LAST)))

        self.add_item(_ActionButton("花牌", row=4, action="flowers", parent=self))
        self.add_item(_ActionButton("清空", row=4, action="clear", parent=self))
        self.add_item(_ActionButton("返回", row=4, action="back", parent=self))


class _WindSelect(discord.ui.Select):
    def __init__(self, label: str, row: int, is_seat: bool, parent: McrSettingsView):
        options = [
            discord.SelectOption(label="东", value="E"),
            discord.SelectOption(label="南", value="S"),
            discord.SelectOption(label="西", value="W"),
            discord.SelectOption(label="北", value="N"),
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
        await self.parent_view.parent_view.refresh(interaction, notice="风位已更新。", use_settings=True)


class _ToggleButton(Button):
    def __init__(self, label: str, row: int, flag: int, parent: McrSettingsView, active: bool):
        style = discord.ButtonStyle.danger if active else discord.ButtonStyle.secondary
        super().__init__(label=label, style=style, row=row)
        self.flag = flag
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        parent = self.parent_view.parent_view
        parent.win_flag ^= self.flag
        await parent.refresh(interaction, notice="标记已更新。", use_settings=True)


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
            await parent.refresh(interaction, notice="已清空。", use_settings=True)
            return
        if self.action == "flowers":
            await interaction.response.send_modal(FlowerModal(self.parent_view))
            return


class _TileButton(Button):
    def __init__(self, label: str, token: str, row: int, parent: "McrCalculatorView"):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row)
        self.token = token
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.handle_tile_click(interaction, self.token)


class _PageButton(Button):
    def __init__(self, label: str, page: str, row: int, parent: "McrCalculatorView"):
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=row)
        self.page = page
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.page = self.page
        self.parent_view.rebuild_items()
        await self.parent_view.refresh(interaction)


class _ModeButton(Button):
    def __init__(self, label: str, mode: str, row: int, parent: "McrCalculatorView"):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row)
        self.mode = mode
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.mode = self.mode
        await self.parent_view.refresh(interaction, notice=f"模式：{self.parent_view.mode_label()}")


class _MainActionButton(Button):
    def __init__(self, label: str, action: str, row: int, parent: "McrCalculatorView"):
        super().__init__(label=label, style=discord.ButtonStyle.success, row=row)
        self.action = action
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        if self.action == "settings":
            await self.parent_view.refresh(interaction, use_settings=True)
        elif self.action == "clear":
            self.parent_view.reset_state()
            await self.parent_view.refresh(interaction, notice="已清空。")


class McrCalculatorView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.hand_tiles: List[int] = []
        self.fixed_packs: List[int] = []
        self.pack_count = 0
        self.win_tile: Optional[int] = None
        self.mode: str = "add"
        self.page: str = "m"
        self.win_flag = 0
        self.prevalent_wind = Wind.EAST
        self.seat_wind = Wind.EAST
        self.flower_count = 0
        self._waits_cache_key: Optional[tuple] = None
        self._waits_cache_text: str = ""
        self.rebuild_items()

    def reset_state(self) -> None:
        self.hand_tiles = []
        self.fixed_packs = []
        self.pack_count = 0
        self.win_tile = None
        self.mode = "add"
        self.page = "m"
        self.win_flag = 0
        self.prevalent_wind = Wind.EAST
        self.seat_wind = Wind.EAST
        self.flower_count = 0
        self._waits_cache_key = None
        self._waits_cache_text = ""
        self.rebuild_items()

    def rebuild_items(self) -> None:
        self.clear_items()
        tiles = _TILE_PAGE[self.page]
        row0 = tiles[:5]
        row1 = tiles[5:]
        for label, token in row0:
            self.add_item(_TileButton(label, token, row=0, parent=self))
        for label, token in row1:
            self.add_item(_TileButton(label, token, row=1, parent=self))

        self.add_item(_PageButton("万", "m", row=2, parent=self))
        self.add_item(_PageButton("条", "s", row=2, parent=self))
        self.add_item(_PageButton("饼", "p", row=2, parent=self))
        self.add_item(_PageButton("字", "h", row=2, parent=self))

        self.add_item(_ModeButton("添加", "add", row=3, parent=self))
        self.add_item(_ModeButton("删除", "remove", row=3, parent=self))
        self.add_item(_ModeButton("吃", "chi", row=3, parent=self))
        self.add_item(_ModeButton("碰", "pon", row=3, parent=self))
        self.add_item(_ModeButton("杠", "kang", row=3, parent=self))

        self.add_item(_MainActionButton("设置", "settings", row=4, parent=self))
        self.add_item(_MainActionButton("清空", "clear", row=4, parent=self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    def _all_tile_counts(self) -> Dict[int, int]:
        counts = _tile_counts(self.hand_tiles)
        for pack in self.fixed_packs:
            for t in _pack_tiles(pack):
                counts[t] = counts.get(t, 0) + 1
        return counts

    def _can_add_tiles(self, tiles: List[int]) -> bool:
        counts = self._all_tile_counts()
        for t in tiles:
            if counts.get(t, 0) >= 4:
                return False
            counts[t] = counts.get(t, 0) + 1
        return True

    async def handle_tile_click(self, interaction: discord.Interaction, token: str) -> None:
        tile = string_to_tile(token)
        if tile is None:
            await interaction.response.send_message("无效牌。", ephemeral=True)
            return

        if self.mode == "remove":
            if tile in self.hand_tiles:
                self.hand_tiles.remove(tile)
                await self.refresh(interaction, notice="已删除。")
            else:
                await self.refresh(interaction, notice="手牌里没有该牌。")
            return

        if self.mode in ("chi", "pon", "kang"):
            if self.pack_count >= 4:
                await interaction.response.send_message("副露已满。", ephemeral=True)
                return
            if self.mode == "chi":
                if not is_numbered_suit(tile):
                    await interaction.response.send_message("字牌不能吃。", ephemeral=True)
                    return
                r = tile_get_rank(tile)
                if r > 7:
                    await interaction.response.send_message("吃需要起始牌<=7。", ephemeral=True)
                    return
                tiles = [tile, tile + 1, tile + 2]
                if not self._can_add_tiles(tiles):
                    await interaction.response.send_message("该牌超过4张限制。", ephemeral=True)
                    return
                if len(self.hand_tiles) > 13 - (self.pack_count + 1) * 3:
                    await interaction.response.send_message("立牌过多，请先删除。", ephemeral=True)
                    return
                self.fixed_packs.append(make_pack(1, PACK_TYPE_CHOW, tile + 1))
                self.pack_count += 1
                await self.refresh(interaction, notice="已吃。")
                return
            if self.mode == "pon":
                tiles = [tile, tile, tile]
                if not self._can_add_tiles(tiles):
                    await interaction.response.send_message("该牌超过4张限制。", ephemeral=True)
                    return
                if len(self.hand_tiles) > 13 - (self.pack_count + 1) * 3:
                    await interaction.response.send_message("立牌过多，请先删除。", ephemeral=True)
                    return
                self.fixed_packs.append(make_pack(1, PACK_TYPE_PUNG, tile))
                self.pack_count += 1
                await self.refresh(interaction, notice="已碰。")
                return
            if self.mode == "kang":
                tiles = [tile, tile, tile, tile]
                if not self._can_add_tiles(tiles):
                    await interaction.response.send_message("该牌超过4张限制。", ephemeral=True)
                    return
                if len(self.hand_tiles) > 13 - (self.pack_count + 1) * 3:
                    await interaction.response.send_message("立牌过多，请先删除。", ephemeral=True)
                    return
                self.fixed_packs.append(make_pack(1, PACK_TYPE_KONG, tile))
                self.pack_count += 1
                await self.refresh(interaction, notice="已杠。")
                return

        max_tiles = 13 - self.pack_count * 3
        if len(self.hand_tiles) == max_tiles:
            if not self._can_add_tiles([tile]):
                await interaction.response.send_message("该牌超过4张限制。", ephemeral=True)
                return
            self.win_tile = tile
            await self._auto_calculate(interaction)
            return

        if not self._can_add_tiles([tile]):
            await interaction.response.send_message("该牌超过4张限制。", ephemeral=True)
            return
        self.hand_tiles.append(tile)
        await self.refresh(interaction, notice="已添加。")

    async def _auto_calculate(self, interaction: discord.Interaction) -> None:
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
            await interaction.response.send_message("诈和", ephemeral=True)
            return
        details = []
        for i in range(1, FAN_TABLE_SIZE):
            if fan_table[i]:
                name = FAN_NAME_ZH[i] if i < len(FAN_NAME_ZH) else f"番种{i}"
                count = fan_table[i]
                details.append(f"{name}×{count}")
        detail_text = "\n".join(details) if details else "无番种详情。"
        await interaction.response.send_message(f"总计：{total_fan}番\n{detail_text}", ephemeral=True)

    def _waits_with_fan(self) -> str:
        max_tiles = 13 - self.pack_count * 3
        if len(self.hand_tiles) != max_tiles:
            return ""
        key = (
            tuple(sorted(self.hand_tiles)),
            tuple(self.fixed_packs),
            self.pack_count,
            self.win_flag,
            self.prevalent_wind,
            self.seat_wind,
            self.flower_count,
        )
        if key == self._waits_cache_key:
            return self._waits_cache_text
        hand = HandTiles(self.fixed_packs, self.pack_count, list(self.hand_tiles), len(self.hand_tiles))
        useful = [False] * 0x48
        if not is_waiting(hand, useful):
            self._waits_cache_key = key
            self._waits_cache_text = "听牌：未听牌"
            return self._waits_cache_text
        parts = []
        for t in ALL_TILES:
            if not useful[t]:
                continue
            param = CalculateParam(
                hand_tiles=hand,
                win_tile=t,
                flower_count=self.flower_count,
                win_flag=self.win_flag,
                prevalent_wind=self.prevalent_wind,
                seat_wind=self.seat_wind,
            )
            fan_table = [0] * FAN_TABLE_SIZE
            total_fan = calculate_fan(param, fan_table)
            label = _tile_display(tile_to_string(t))
            if total_fan < 0:
                continue
            parts.append(f"{label}({total_fan}番)")
        if not parts:
            self._waits_cache_key = key
            self._waits_cache_text = "听牌：未听牌"
            return self._waits_cache_text
        self._waits_cache_key = key
        self._waits_cache_text = "听牌：" + " ".join(parts)
        return self._waits_cache_text

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
        wind_map = {Wind.EAST: "东", Wind.SOUTH: "南", Wind.WEST: "西", Wind.NORTH: "北"}
        flags = []
        if self.win_flag & WIN_FLAG_SELF_DRAWN:
            flags.append("自摸")
        if self.win_flag & WIN_FLAG_LAST_TILE:
            flags.append("绝张")
        if self.win_flag & WIN_FLAG_KONG_INVOLVED:
            flags.append("杠")
        if self.win_flag & WIN_FLAG_WALL_LAST:
            flags.append("海底")
        if self.win_flag & WIN_FLAG_INITIAL:
            flags.append("起手")
        win_tile = tile_to_string(self.win_tile) if self.win_tile else "无"
        waits_text = self._waits_with_fan()
        return (
            f"模式: {self.mode_label()}\n"
            f"当前页: {self.page}\n"
            f"立牌 ({len(self.hand_tiles)}/{max_tiles}): {_format_hand(self.hand_tiles)}\n"
            f"和牌: {win_tile}\n"
            f"副露 ({self.pack_count}): {_format_packs(self.fixed_packs)}\n"
            f"风位: 门风={wind_map[self.seat_wind]}, 圈风={wind_map[self.prevalent_wind]}\n"
            f"标记: {', '.join(flags) if flags else '无'} | 花牌: {self.flower_count}\n"
            f"{waits_text}"
        )

    def mode_label(self) -> str:
        return {
            "add": "添加",
            "remove": "删除",
            "chi": "吃",
            "pon": "碰",
            "kang": "杠",
        }.get(self.mode, self.mode)
