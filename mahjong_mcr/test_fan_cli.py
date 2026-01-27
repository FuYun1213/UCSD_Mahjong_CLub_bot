"""
CLI test helper for MCR fan calculation using the exact rules ported from C++.
"""

from __future__ import annotations

import argparse
from typing import List

if __package__ is None or __package__ == "":
    import os
    import sys

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

    from mahjong_mcr.fan_calculator import (
        CalculateParam,
        FAN_NAME_ZH,
        FAN_TABLE_SIZE,
        WIN_FLAG_INITIAL,
        WIN_FLAG_KONG_INVOLVED,
        WIN_FLAG_LAST_TILE,
        WIN_FLAG_SELF_DRAWN,
        WIN_FLAG_WALL_LAST,
        Wind,
        calculate_fan,
    )
    from mahjong_mcr.stringify import (
        PARSE_NO_ERROR,
        PARSE_ERROR_CANNOT_MAKE_FIXED_PACK,
        PARSE_ERROR_ILLEGAL_CHARACTER,
        PARSE_ERROR_SUFFIX,
        PARSE_ERROR_TILE_COUNT_GREATER_THAN_4,
        PARSE_ERROR_TOO_MANY_FIXED_PACKS,
        PARSE_ERROR_TOO_MANY_TILES,
        PARSE_ERROR_WRONG_TILES_COUNT_FOR_FIXED_PACK,
        string_to_tiles,
    )
    from mahjong_mcr.tile import HandTiles, string_to_tile
else:
    from .fan_calculator import (
        CalculateParam,
        FAN_NAME_ZH,
        FAN_TABLE_SIZE,
        WIN_FLAG_INITIAL,
        WIN_FLAG_KONG_INVOLVED,
        WIN_FLAG_LAST_TILE,
        WIN_FLAG_SELF_DRAWN,
        WIN_FLAG_WALL_LAST,
        Wind,
        calculate_fan,
    )
    from .stringify import (
        PARSE_NO_ERROR,
        PARSE_ERROR_CANNOT_MAKE_FIXED_PACK,
        PARSE_ERROR_ILLEGAL_CHARACTER,
        PARSE_ERROR_SUFFIX,
        PARSE_ERROR_TILE_COUNT_GREATER_THAN_4,
        PARSE_ERROR_TOO_MANY_FIXED_PACKS,
        PARSE_ERROR_TOO_MANY_TILES,
        PARSE_ERROR_WRONG_TILES_COUNT_FOR_FIXED_PACK,
        string_to_tiles,
    )
    from .tile import HandTiles, string_to_tile


_ERROR_TEXT = {
    PARSE_ERROR_ILLEGAL_CHARACTER: "非法字符",
    PARSE_ERROR_SUFFIX: "后缀错误",
    PARSE_ERROR_WRONG_TILES_COUNT_FOR_FIXED_PACK: "副露包含错误的牌数目",
    PARSE_ERROR_CANNOT_MAKE_FIXED_PACK: "无法正确解析副露",
    PARSE_ERROR_TOO_MANY_FIXED_PACKS: "过多组副露",
    PARSE_ERROR_TOO_MANY_TILES: "过多牌",
    PARSE_ERROR_TILE_COUNT_GREATER_THAN_4: "某张牌出现超过4枚",
}

_FLAG_TOKENS = {
    "自摸": WIN_FLAG_SELF_DRAWN,
    "和绝张": WIN_FLAG_LAST_TILE,
    "绝张": WIN_FLAG_LAST_TILE,
    "杠上开花": WIN_FLAG_KONG_INVOLVED | WIN_FLAG_SELF_DRAWN,
    "抢杠和": WIN_FLAG_KONG_INVOLVED,
    "海底捞月": WIN_FLAG_WALL_LAST,
    "妙手回春": WIN_FLAG_WALL_LAST | WIN_FLAG_SELF_DRAWN,
    "起手": WIN_FLAG_INITIAL,
}


def _parse_wind(value: str) -> int:
    value = value.strip().upper()
    if value in ("E", "东"):
        return Wind.EAST
    if value in ("S", "南"):
        return Wind.SOUTH
    if value in ("W", "西"):
        return Wind.WEST
    if value in ("N", "北"):
        return Wind.NORTH
    raise ValueError(f"Invalid wind: {value}")


def _parse_flags(flag_text: str) -> int:
    win_flag = 0
    if not flag_text:
        return win_flag
    for raw in flag_text.replace("|", ",").replace("，", ",").split(","):
        token = raw.strip()
        if not token:
            continue
        if token in _FLAG_TOKENS:
            win_flag |= _FLAG_TOKENS[token]
        else:
            raise ValueError(f"Unknown flag token: {token}")
    return win_flag


def _format_fan_table(fan_table: List[int]) -> str:
    lines = []
    for i in range(1, FAN_TABLE_SIZE):
        cnt = fan_table[i]
        if cnt:
            name = FAN_NAME_ZH[i]
            if cnt == 1:
                lines.append(name)
            else:
                lines.append(f"{name} x{cnt}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="MCR fan calculator test CLI")
    parser.add_argument("tiles", help="Hand string, e.g. [123m1][789p]45sESWNCFP1m")
    parser.add_argument("--flags", default="", help="Comma-separated flags, e.g. 自摸,和绝张,杠上开花")
    parser.add_argument("--self-drawn", action="store_true", help="Set 自摸")
    parser.add_argument("--last-tile", action="store_true", help="Set 和绝张")
    parser.add_argument("--kong-involved", action="store_true", help="Set 杠相关")
    parser.add_argument("--wall-last", action="store_true", help="Set 牌墙最后一张")
    parser.add_argument("--initial", action="store_true", help="Set 起手")
    parser.add_argument("--win", default="", help="Win tile when not provided in tiles, e.g. 5m or E")
    parser.add_argument("--seat", default="E", help="Seat wind: E/S/W/N or 东/南/西/北")
    parser.add_argument("--prevalent", default="E", help="Prevalent wind: E/S/W/N or 东/南/西/北")
    parser.add_argument("--flowers", type=int, default=0, help="Flower count")
    args = parser.parse_args()

    err, hand_tiles, serving_tile = string_to_tiles(args.tiles.strip())
    if err != PARSE_NO_ERROR:
        print(f"解析失败: {_ERROR_TEXT.get(err, err)}")
        return

    win_tile = serving_tile
    if win_tile == 0 and args.win:
        tile = string_to_tile(args.win)
        if tile is None:
            print("Win tile 格式错误")
            return
        win_tile = tile

    if win_tile == 0:
        print("未提供和牌张，请在输入中包含第14张，或使用 --win 指定。")
        return

    win_flag = _parse_flags(args.flags)
    if args.self_drawn:
        win_flag |= WIN_FLAG_SELF_DRAWN
    if args.last_tile:
        win_flag |= WIN_FLAG_LAST_TILE
    if args.kong_involved:
        win_flag |= WIN_FLAG_KONG_INVOLVED
    if args.wall_last:
        win_flag |= WIN_FLAG_WALL_LAST
    if args.initial:
        win_flag |= WIN_FLAG_INITIAL

    param = CalculateParam(
        hand_tiles=hand_tiles,
        win_tile=win_tile,
        flower_count=args.flowers,
        win_flag=win_flag,
        prevalent_wind=_parse_wind(args.prevalent),
        seat_wind=_parse_wind(args.seat),
    )

    fan_table = [0] * FAN_TABLE_SIZE
    total_fan = calculate_fan(param, fan_table)
    if total_fan < 0:
        print(f"算番失败: {total_fan}")
        return

    print(f"总番: {total_fan}")
    detail = _format_fan_table(fan_table)
    if detail:
        print(detail)


if __name__ == "__main__":
    main()
