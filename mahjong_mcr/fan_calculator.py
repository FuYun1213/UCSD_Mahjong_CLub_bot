"""
Exact port of Classes/mahjong-algorithm/fan_calculator.cpp and fan_calculator.h
from ChineseOfficialMahjongHelper (MIT License).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .tile import (
    ALL_TILES,
    HandTiles,
    PACK_TYPE_CHOW,
    PACK_TYPE_KONG,
    PACK_TYPE_PAIR,
    PACK_TYPE_PUNG,
    TILE_TABLE_SIZE,
    TILE_1s, TILE_5s, TILE_7s, TILE_9s,
    TILE_E, TILE_S, TILE_W, TILE_N, TILE_C, TILE_F, TILE_P,
    TILE_SUIT_HONORS,
    is_dragons,
    is_green,
    is_honor,
    is_numbered_suit,
    is_numbered_suit_quick,
    is_pack_melded,
    is_reversible,
    is_terminal,
    is_terminal_or_honor,
    is_winds,
    make_eigen,
    make_pack,
    make_tile,
    pack_get_offer,
    pack_get_tile,
    pack_get_type,
    tile_get_rank,
    tile_get_suit,
)
from .standard_tiles import STANDARD_KNITTED_STRAIGHT, STANDARD_THIRTEEN_ORPHANS

SUPPORT_CONCEALED_KONG_AND_MELDED_KONG = 1
KNITTED_STRAIGHT_BODY_WITH_ECS = 1
DISTINGUISH_PURE_SHIFTED_CHOWS = 0
NINE_GATES_WHEN_BLESSING_OF_HEAVEN = 1
SUPPORT_BLESSINGS = 1

FAN_NONE = 0
BIG_FOUR_WINDS = 1
BIG_THREE_DRAGONS = 2
ALL_GREEN = 3
NINE_GATES = 4
FOUR_KONGS = 5
SEVEN_SHIFTED_PAIRS = 6
THIRTEEN_ORPHANS = 7

ALL_TERMINALS = 8
LITTLE_FOUR_WINDS = 9
LITTLE_THREE_DRAGONS = 10
ALL_HONORS = 11
FOUR_CONCEALED_PUNGS = 12
PURE_TERMINAL_CHOWS = 13

QUADRUPLE_CHOW = 14
FOUR_PURE_SHIFTED_PUNGS = 15
FOUR_PURE_SHIFTED_CHOWS = 16
THREE_KONGS = 17
ALL_TERMINALS_AND_HONORS = 18

SEVEN_PAIRS = 19
GREATER_HONORS_AND_KNITTED_TILES = 20
ALL_EVEN_PUNGS = 21
FULL_FLUSH = 22
PURE_TRIPLE_CHOW = 23
PURE_SHIFTED_PUNGS = 24
UPPER_TILES = 25
MIDDLE_TILES = 26
LOWER_TILES = 27

PURE_STRAIGHT = 28
THREE_SUITED_TERMINAL_CHOWS = 29
PURE_SHIFTED_CHOWS = 30
ALL_FIVE = 31
TRIPLE_PUNG = 32
THREE_CONCEALED_PUNGS = 33

LESSER_HONORS_AND_KNITTED_TILES = 34
KNITTED_STRAIGHT = 35
UPPER_FOUR = 36
LOWER_FOUR = 37
BIG_THREE_WINDS = 38

MIXED_STRAIGHT = 39
REVERSIBLE_TILES = 40
MIXED_TRIPLE_CHOW = 41
MIXED_SHIFTED_PUNGS = 42
CHICKEN_HAND = 43
LAST_TILE_DRAW = 44
LAST_TILE_CLAIM = 45
OUT_WITH_REPLACEMENT_TILE = 46
ROBBING_THE_KONG = 47

ALL_PUNGS = 48
HALF_FLUSH = 49
MIXED_SHIFTED_CHOWS = 50
ALL_TYPES = 51
MELDED_HAND = 52
TWO_CONCEALED_KONGS = 53
TWO_DRAGONS_PUNGS = 54

OUTSIDE_HAND = 55
FULLY_CONCEALED_HAND = 56
TWO_MELDED_KONGS = 57
LAST_TILE = 58

DRAGON_PUNG = 59
PREVALENT_WIND = 60
SEAT_WIND = 61
CONCEALED_HAND = 62
ALL_CHOWS = 63
TILE_HOG = 64
DOUBLE_PUNG = 65
TWO_CONCEALED_PUNGS = 66
CONCEALED_KONG = 67
ALL_SIMPLES = 68

PURE_DOUBLE_CHOW = 69
MIXED_DOUBLE_CHOW = 70
SHORT_STRAIGHT = 71
TWO_TERMINAL_CHOWS = 72
PUNG_OF_TERMINALS_OR_HONORS = 73
MELDED_KONG = 74
ONE_VOIDED_SUIT = 75
NO_HONORS = 76
EDGE_WAIT = 77
CLOSED_WAIT = 78
SINGLE_WAIT = 79
SELF_DRAWN = 80

FLOWER_TILES = 81
CONCEALED_KONG_AND_MELDED_KONG = 82

BLESSING_OF_HEAVEN = 83
BLESSING_OF_EARTH = 84
BLESSING_OF_HUMAN_1 = 85
BLESSING_OF_HUMAN_2 = 86
TWICE_PURE_DOUBLE_CHOWS = 87
MIRROR_HAND = 88
RED_PEACOCK = 89
LITTLE_THREE_WINDS = 90

FAN_TABLE_SIZE = 91

FAN_NAME_ZH = [
    "无",
    "大四喜", "大三元", "绿一色", "九莲宝灯", "四杠", "连七对", "十三幺",
    "清幺九", "小四喜", "小三元", "字一色", "四暗刻", "一色双龙会",
    "一色四同顺", "一色四节高", "一色四步高",
    "三杠", "混幺九",
    "七对", "七星不靠", "全双刻", "清一色", "一色三同顺", "一色三节高", "全大", "全中", "全小",
    "清龙", "三色双龙会", "一色三步高", "全带五", "三同刻", "三暗刻",
    "全不靠", "组合龙", "大于五", "小于五", "三风刻",
    "花龙", "推不倒", "三色三同顺", "三色三节高", "无番和", "妙手回春", "海底捞月", "杠上开花", "抢杠和",
    "碰碰和", "混一色", "三色三步高", "五门齐", "全求人", "双暗杠", "双箭刻",
    "全带幺", "不求人", "双明杠", "和绝张",
    "箭刻", "圈风刻", "门风刻", "门前清", "平和", "四归一", "双同刻", "双暗刻", "暗杠", "断幺",
    "一般高", "喜相逢", "连六", "老少副", "幺九刻", "明杠", "缺一门", "无字", "独听・边张", "独听・嵌张", "独听・单钓", "自摸",
    "花牌", "明暗杠", "天和", "地和", "人和I", "人和II",
    "两般高", "镜同和", "红孔雀", "小三风",
]

FAN_VALUE_TABLE = [
    0,
    88, 88, 88, 88, 88, 88, 88,
    64, 64, 64, 64, 64, 64,
    48, 48,
    32, 32, 32,
    24, 24, 24, 24, 24, 24, 24, 24, 24,
    16, 32, 16, 16, 16, 16,
    12, 12, 12, 12, 12,
    8, 8, 8, 8, 8, 8, 8, 8, 8,
    6, 6, 6, 6, 6, 6, 6,
    4, 4, 4, 4,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1,
    5,
    8, 8, 8, 8,
    16, 12, 88, 8,
]


class Wind:
    EAST = 0
    SOUTH = 1
    WEST = 2
    NORTH = 3


WIN_FLAG_DISCARD = 0
WIN_FLAG_SELF_DRAWN = 1
WIN_FLAG_LAST_TILE = 2
WIN_FLAG_KONG_INVOLVED = 4
WIN_FLAG_WALL_LAST = 8
WIN_FLAG_INITIAL = 16

ERROR_WRONG_TILES_COUNT = -1
ERROR_TILE_MORE_THAN_4 = -2
ERROR_NOT_WIN = -3


@dataclass
class CalculateParam:
    hand_tiles: HandTiles
    win_tile: int
    flower_count: int
    win_flag: int
    prevalent_wind: int
    seat_wind: int


def _new_tile_table() -> List[int]:
    return [0] * TILE_TABLE_SIZE


def _map_tiles(tiles: List[int], cnt: int, tile_table: List[int]) -> None:
    for i in range(cnt):
        tile_table[tiles[i]] += 1


def _map_packs(packs: List[int], cnt: int, tile_table: List[int]) -> None:
    for i in range(cnt):
        tile = pack_get_tile(packs[i])
        pack_type = pack_get_type(packs[i])
        if pack_type == PACK_TYPE_CHOW:
            tile_table[tile - 1] += 1
            tile_table[tile] += 1
            tile_table[tile + 1] += 1
        elif pack_type == PACK_TYPE_PUNG:
            tile_table[tile] += 3
        elif pack_type == PACK_TYPE_KONG:
            tile_table[tile] += 4
        elif pack_type == PACK_TYPE_PAIR:
            tile_table[tile] += 2
        else:
            raise ValueError("Invalid pack type")


def _table_unique(fixed_table: List[int], standing_table: List[int]) -> List[int]:
    unique_tiles: List[int] = []
    for t in ALL_TILES:
        if fixed_table[t] or standing_table[t]:
            unique_tiles.append(t)
    return unique_tiles


class Division:
    def __init__(self) -> None:
        self.packs: List[int] = [0] * 5


class DivisionResult:
    def __init__(self) -> None:
        self.divisions: List[Division] = []


def _divide_tail_add_division(fixed_cnt: int, work_division: Division, result: DivisionResult) -> None:
    temp = Division()
    temp.packs = list(work_division.packs)
    temp.packs[fixed_cnt:4] = sorted(temp.packs[fixed_cnt:4])
    for d in result.divisions:
        if d.packs[fixed_cnt:4] == temp.packs[fixed_cnt:4]:
            return
    result.divisions.append(temp)


def _divide_tail(tile_table: List[int], fixed_cnt: int, work_division: Division, result: DivisionResult) -> bool:
    for t in ALL_TILES:
        if tile_table[t] < 2:
            continue
        tile_table[t] -= 2
        if all(n == 0 for n in tile_table):
            tile_table[t] += 2
            work_division.packs[4] = make_pack(0, PACK_TYPE_PAIR, t)
            _divide_tail_add_division(fixed_cnt, work_division, result)
            return True
        tile_table[t] += 2
    return False


def _divide_recursively(
    tile_table: List[int],
    fixed_cnt: int,
    step: int,
    prev_eigen: int,
    work_division: Division,
    result: DivisionResult,
) -> bool:
    idx = step + fixed_cnt
    if idx == 4:
        return _divide_tail(tile_table, fixed_cnt, work_division, result)

    ret = False
    for t in ALL_TILES:
        if tile_table[t] < 1:
            continue

        if tile_table[t] > 2:
            eigen = make_eigen(t, t, t)
            if eigen > prev_eigen:
                work_division.packs[idx] = make_pack(0, PACK_TYPE_PUNG, t)
                tile_table[t] -= 3
                if _divide_recursively(tile_table, fixed_cnt, step + 1, eigen, work_division, result):
                    ret = True
                tile_table[t] += 3

        if is_numbered_suit(t):
            if tile_get_rank(t) < 8 and tile_table[t + 1] and tile_table[t + 2]:
                eigen = make_eigen(t, t + 1, t + 2)
                if eigen >= prev_eigen:
                    work_division.packs[idx] = make_pack(0, PACK_TYPE_CHOW, t + 1)
                    tile_table[t] -= 1
                    tile_table[t + 1] -= 1
                    tile_table[t + 2] -= 1
                    if _divide_recursively(tile_table, fixed_cnt, step + 1, eigen, work_division, result):
                        ret = True
                    tile_table[t] += 1
                    tile_table[t + 1] += 1
                    tile_table[t + 2] += 1

    return ret


def _has_pair(tile_table: List[int]) -> bool:
    for t in ALL_TILES:
        if tile_table[t] > 1:
            return True
    return False


def _divide_win_hand(standing_table: List[int], fixed_packs: List[int], fixed_cnt: int) -> DivisionResult:
    result = DivisionResult()
    if not _has_pair(standing_table):
        return result
    work = Division()
    work.packs[:fixed_cnt] = fixed_packs[:fixed_cnt]
    _divide_recursively(standing_table, fixed_cnt, 0, 0, work, result)
    return result

def _is_four_shifted_1(r0: int, r1: int, r2: int, r3: int) -> bool:
    return r0 + 1 == r1 and r1 + 1 == r2 and r2 + 1 == r3


def _is_four_shifted_2(r0: int, r1: int, r2: int, r3: int) -> bool:
    return r0 + 2 == r1 and r1 + 2 == r2 and r2 + 2 == r3


def _is_shifted_1(r0: int, r1: int, r2: int) -> bool:
    return r0 + 1 == r1 and r1 + 1 == r2


def _is_shifted_2(r0: int, r1: int, r2: int) -> bool:
    return r0 + 2 == r1 and r1 + 2 == r2


def _is_mixed(s0: int, s1: int, s2: int) -> bool:
    return s0 != s1 and s0 != s2 and s1 != s2


def _is_shifted_1_unordered(r0: int, r1: int, r2: int) -> bool:
    return (
        _is_shifted_1(r1, r0, r2) or _is_shifted_1(r2, r0, r1) or _is_shifted_1(r0, r1, r2)
        or _is_shifted_1(r2, r1, r0) or _is_shifted_1(r0, r2, r1) or _is_shifted_1(r1, r2, r0)
    )


def _get_4_chows_fan(t0: int, t1: int, t2: int, t3: int) -> int:
    if _is_four_shifted_2(t0, t1, t2, t3):
        return FOUR_PURE_SHIFTED_CHOWS
    if _is_four_shifted_1(t0, t1, t2, t3):
        return FOUR_PURE_SHIFTED_CHOWS
    if t0 == t1 and t0 == t2 and t0 == t3:
        return QUADRUPLE_CHOW
    return FAN_NONE


def _get_3_chows_fan(t0: int, t1: int, t2: int) -> int:
    s0 = tile_get_suit(t0)
    s1 = tile_get_suit(t1)
    s2 = tile_get_suit(t2)

    r0 = tile_get_rank(t0)
    r1 = tile_get_rank(t1)
    r2 = tile_get_rank(t2)

    if _is_mixed(s0, s1, s2):
        if _is_shifted_1_unordered(r1, r0, r2):
            return MIXED_SHIFTED_CHOWS
        if r0 == r1 and r1 == r2:
            return MIXED_TRIPLE_CHOW
        if ((r0 == 2 and r1 == 5 and r2 == 8) or (r0 == 2 and r1 == 8 and r2 == 5)
            or (r0 == 5 and r1 == 2 and r2 == 8) or (r0 == 5 and r1 == 8 and r2 == 2)
            or (r0 == 8 and r1 == 2 and r2 == 5) or (r0 == 8 and r1 == 5 and r2 == 2)):
            return MIXED_STRAIGHT
    else:
        if t0 + 3 == t1 and t1 + 3 == t2:
            return PURE_STRAIGHT
        if _is_shifted_2(t0, t1, t2):
            return PURE_SHIFTED_CHOWS
        if _is_shifted_1(t0, t1, t2):
            return PURE_SHIFTED_CHOWS
        if t0 == t1 and t0 == t2:
            return PURE_TRIPLE_CHOW
    return FAN_NONE


def _get_2_chows_fan_unordered(t0: int, t1: int) -> int:
    if not ((t0 & 0xF0) == (t1 & 0xF0)):
        if (t0 & 0xCF) == (t1 & 0xCF):
            return MIXED_DOUBLE_CHOW
    else:
        if t0 + 3 == t1 or t1 + 3 == t0:
            return SHORT_STRAIGHT
        r0 = tile_get_rank(t0)
        r1 = tile_get_rank(t1)
        if (r0 == 2 and r1 == 8) or (r0 == 8 and r1 == 2):
            return TWO_TERMINAL_CHOWS
        if t0 == t1:
            return PURE_DOUBLE_CHOW
    return FAN_NONE


def _get_4_pungs_fan(t0: int, t1: int, t2: int, t3: int) -> int:
    if is_numbered_suit_quick(t0) and t0 + 1 == t1 and t1 + 1 == t2 and t2 + 1 == t3:
        return FOUR_PURE_SHIFTED_PUNGS
    if t0 == TILE_E and t1 == TILE_S and t2 == TILE_W and t3 == TILE_N:
        return BIG_FOUR_WINDS
    return FAN_NONE


def _get_3_pungs_fan(t0: int, t1: int, t2: int) -> int:
    if is_numbered_suit_quick(t0) and is_numbered_suit_quick(t1) and is_numbered_suit_quick(t2):
        s0 = tile_get_suit(t0)
        s1 = tile_get_suit(t1)
        s2 = tile_get_suit(t2)

        r0 = tile_get_rank(t0)
        r1 = tile_get_rank(t1)
        r2 = tile_get_rank(t2)

        if _is_mixed(s0, s1, s2):
            if _is_shifted_1_unordered(r1, r0, r2):
                return MIXED_SHIFTED_PUNGS
            if r0 == r1 and r1 == r2:
                return TRIPLE_PUNG
        else:
            if t0 + 1 == t1 and t1 + 1 == t2:
                return PURE_SHIFTED_PUNGS
    else:
        if ((t0 == TILE_E and t1 == TILE_S and t2 == TILE_W)
            or (t0 == TILE_E and t1 == TILE_S and t2 == TILE_N)
            or (t0 == TILE_E and t1 == TILE_W and t2 == TILE_N)
            or (t0 == TILE_S and t1 == TILE_W and t2 == TILE_N)):
            return BIG_THREE_WINDS
        if t0 == TILE_C and t1 == TILE_F and t2 == TILE_P:
            return BIG_THREE_DRAGONS

    return FAN_NONE


def _get_2_pungs_fan_unordered(t0: int, t1: int) -> int:
    if is_numbered_suit_quick(t0) and is_numbered_suit_quick(t1):
        if (t0 & 0xCF) == (t1 & 0xCF):
            return DOUBLE_PUNG
    else:
        if is_dragons(t0) and is_dragons(t1):
            return TWO_DRAGONS_PUNGS
    return FAN_NONE


def _get_1_pung_fan(mid_tile: int) -> int:
    if is_dragons(mid_tile):
        return DRAGON_PUNG
    if is_terminal(mid_tile) or is_winds(mid_tile):
        return PUNG_OF_TERMINALS_OR_HONORS
    return FAN_NONE


def _get_1_chow_extra_fan(tile0: int, tile1: int, tile2: int, tile_extra: int) -> int:
    fan0 = _get_2_chows_fan_unordered(tile0, tile_extra)
    fan1 = _get_2_chows_fan_unordered(tile1, tile_extra)
    fan2 = _get_2_chows_fan_unordered(tile2, tile_extra)

    if fan0 == PURE_DOUBLE_CHOW or fan1 == PURE_DOUBLE_CHOW or fan2 == PURE_DOUBLE_CHOW:
        return PURE_DOUBLE_CHOW
    if fan0 == MIXED_DOUBLE_CHOW or fan1 == MIXED_DOUBLE_CHOW or fan2 == MIXED_DOUBLE_CHOW:
        return MIXED_DOUBLE_CHOW
    if fan0 == SHORT_STRAIGHT or fan1 == SHORT_STRAIGHT or fan2 == SHORT_STRAIGHT:
        return SHORT_STRAIGHT
    if fan0 == TWO_TERMINAL_CHOWS or fan1 == TWO_TERMINAL_CHOWS or fan2 == TWO_TERMINAL_CHOWS:
        return TWO_TERMINAL_CHOWS

    return FAN_NONE


def _exclusionary_rule(all_fans: List[int], fan_cnt: int, max_cnt: int, fan_table: List[int]) -> None:
    table = [0, 0, 0, 0]
    cnt = 0
    for i in range(fan_cnt):
        if all_fans[i] != FAN_NONE:
            cnt += 1
            table[all_fans[i] - PURE_DOUBLE_CHOW] += 1

    limit_cnt = 1
    while cnt > max_cnt and limit_cnt >= 0:
        idx = 4
        while cnt > max_cnt and idx > 0:
            idx -= 1
            while table[idx] > limit_cnt and cnt > max_cnt:
                table[idx] -= 1
                cnt -= 1
        limit_cnt -= 1

    fan_table[PURE_DOUBLE_CHOW] = table[0]
    fan_table[MIXED_DOUBLE_CHOW] = table[1]
    fan_table[SHORT_STRAIGHT] = table[2]
    fan_table[TWO_TERMINAL_CHOWS] = table[3]


def _calculate_3_of_4_chows(tile0: int, tile1: int, tile2: int, tile_extra: int, fan_table: List[int]) -> bool:
    fan = _get_3_chows_fan(tile0, tile1, tile2)
    if fan != FAN_NONE:
        fan_table[fan] = 1
        fan = _get_1_chow_extra_fan(tile0, tile1, tile2, tile_extra)
        if fan != FAN_NONE:
            fan_table[fan] = 1
        return True
    return False


def _calculate_4_chows(mid_tiles: List[int], fan_table: List[int]) -> None:
    fan = _get_4_chows_fan(mid_tiles[0], mid_tiles[1], mid_tiles[2], mid_tiles[3])
    if fan != FAN_NONE:
        fan_table[fan] = 1
        return

    if (
        _calculate_3_of_4_chows(mid_tiles[0], mid_tiles[1], mid_tiles[2], mid_tiles[3], fan_table)
        or _calculate_3_of_4_chows(mid_tiles[0], mid_tiles[1], mid_tiles[3], mid_tiles[2], fan_table)
        or _calculate_3_of_4_chows(mid_tiles[0], mid_tiles[2], mid_tiles[3], mid_tiles[1], fan_table)
        or _calculate_3_of_4_chows(mid_tiles[1], mid_tiles[2], mid_tiles[3], mid_tiles[0], fan_table)
    ):
        return

    all_fans = [
        _get_2_chows_fan_unordered(mid_tiles[0], mid_tiles[1]),
        _get_2_chows_fan_unordered(mid_tiles[0], mid_tiles[2]),
        _get_2_chows_fan_unordered(mid_tiles[0], mid_tiles[3]),
        _get_2_chows_fan_unordered(mid_tiles[1], mid_tiles[2]),
        _get_2_chows_fan_unordered(mid_tiles[1], mid_tiles[3]),
        _get_2_chows_fan_unordered(mid_tiles[2], mid_tiles[3]),
    ]

    max_cnt = 3
    if all_fans[0] == FAN_NONE and all_fans[1] == FAN_NONE and all_fans[2] == FAN_NONE:
        max_cnt -= 1
    if all_fans[0] == FAN_NONE and all_fans[3] == FAN_NONE and all_fans[4] == FAN_NONE:
        max_cnt -= 1
    if all_fans[1] == FAN_NONE and all_fans[3] == FAN_NONE and all_fans[5] == FAN_NONE:
        max_cnt -= 1
    if all_fans[2] == FAN_NONE and all_fans[4] == FAN_NONE and all_fans[5] == FAN_NONE:
        max_cnt -= 1

    if max_cnt > 0:
        _exclusionary_rule(all_fans, 6, max_cnt, fan_table)


def _calculate_3_chows(mid_tiles: List[int], fan_table: List[int]) -> None:
    fan = _get_3_chows_fan(mid_tiles[0], mid_tiles[1], mid_tiles[2])
    if fan != FAN_NONE:
        fan_table[fan] = 1
        return

    all_fans = [
        _get_2_chows_fan_unordered(mid_tiles[0], mid_tiles[1]),
        _get_2_chows_fan_unordered(mid_tiles[0], mid_tiles[2]),
        _get_2_chows_fan_unordered(mid_tiles[1], mid_tiles[2]),
    ]
    _exclusionary_rule(all_fans, 3, 2, fan_table)


def _calculate_2_chows_unordered(mid_tiles: List[int], fan_table: List[int]) -> None:
    fan = _get_2_chows_fan_unordered(mid_tiles[0], mid_tiles[1])
    if fan != FAN_NONE:
        fan_table[fan] += 1


def _calculate_kongs(concealed_pung_cnt: int, melded_kong_cnt: int, concealed_kong_cnt: int, fan_table: List[int]) -> None:
    kong_cnt = melded_kong_cnt + concealed_kong_cnt
    if kong_cnt == 0:
        if concealed_pung_cnt == 2:
            fan_table[TWO_CONCEALED_PUNGS] = 1
        elif concealed_pung_cnt == 3:
            fan_table[THREE_CONCEALED_PUNGS] = 1
        elif concealed_pung_cnt == 4:
            fan_table[FOUR_CONCEALED_PUNGS] = 1
        return

    if kong_cnt == 1:
        if melded_kong_cnt == 1:
            fan_table[MELDED_KONG] = 1
            if concealed_pung_cnt == 2:
                fan_table[TWO_CONCEALED_PUNGS] = 1
            elif concealed_pung_cnt == 3:
                fan_table[THREE_CONCEALED_PUNGS] = 1
        else:
            fan_table[CONCEALED_KONG] = 1
            if concealed_pung_cnt == 1:
                fan_table[TWO_CONCEALED_PUNGS] = 1
            elif concealed_pung_cnt == 2:
                fan_table[THREE_CONCEALED_PUNGS] = 1
            elif concealed_pung_cnt == 3:
                fan_table[FOUR_CONCEALED_PUNGS] = 1
        return

    if kong_cnt == 2:
        if concealed_kong_cnt == 0:
            fan_table[TWO_MELDED_KONGS] = 1
            if concealed_pung_cnt == 2:
                fan_table[TWO_CONCEALED_PUNGS] = 1
        elif concealed_kong_cnt == 1:
            if SUPPORT_CONCEALED_KONG_AND_MELDED_KONG:
                fan_table[CONCEALED_KONG_AND_MELDED_KONG] = 1
            else:
                fan_table[MELDED_KONG] = 1
                fan_table[CONCEALED_KONG] = 1
            if concealed_pung_cnt == 1:
                fan_table[TWO_CONCEALED_PUNGS] = 1
            elif concealed_pung_cnt == 2:
                fan_table[THREE_CONCEALED_PUNGS] = 1
        elif concealed_kong_cnt == 2:
            fan_table[TWO_CONCEALED_KONGS] = 1
            if concealed_pung_cnt == 1:
                fan_table[THREE_CONCEALED_PUNGS] = 1
            elif concealed_pung_cnt == 2:
                fan_table[FOUR_CONCEALED_PUNGS] = 1
        return

    if kong_cnt == 3:
        fan_table[THREE_KONGS] = 1
        if concealed_kong_cnt == 1:
            if concealed_pung_cnt > 0:
                fan_table[TWO_CONCEALED_PUNGS] = 1
        elif concealed_kong_cnt == 2:
            if concealed_pung_cnt == 0:
                fan_table[TWO_CONCEALED_PUNGS] = 1
            else:
                fan_table[THREE_CONCEALED_PUNGS] = 1
        elif concealed_kong_cnt == 3:
            if concealed_pung_cnt == 0:
                fan_table[THREE_CONCEALED_PUNGS] = 1
            else:
                fan_table[FOUR_CONCEALED_PUNGS] = 1
        return

    if kong_cnt == 4:
        fan_table[FOUR_KONGS] = 1
        if concealed_kong_cnt == 2:
            fan_table[TWO_CONCEALED_PUNGS] = 1
        elif concealed_kong_cnt == 3:
            fan_table[THREE_CONCEALED_PUNGS] = 1
        elif concealed_kong_cnt == 4:
            fan_table[FOUR_CONCEALED_PUNGS] = 1
        return


def _calculate_4_pungs(mid_tiles: List[int], fan_table: List[int]) -> None:
    fan = _get_4_pungs_fan(mid_tiles[0], mid_tiles[1], mid_tiles[2], mid_tiles[3])
    if fan != FAN_NONE:
        fan_table[fan] = 1
        return

    has_3_pungs_fan = False
    free_pack_idx = -1
    fan = _get_3_pungs_fan(mid_tiles[0], mid_tiles[1], mid_tiles[2])
    if fan != FAN_NONE:
        fan_table[fan] = 1
        free_pack_idx = 3
        has_3_pungs_fan = True
    else:
        fan = _get_3_pungs_fan(mid_tiles[0], mid_tiles[1], mid_tiles[3])
        if fan != FAN_NONE:
            fan_table[fan] = 1
            free_pack_idx = 2
            has_3_pungs_fan = True
        else:
            fan = _get_3_pungs_fan(mid_tiles[0], mid_tiles[2], mid_tiles[3])
            if fan != FAN_NONE:
                fan_table[fan] = 1
                free_pack_idx = 1
                has_3_pungs_fan = True
            else:
                fan = _get_3_pungs_fan(mid_tiles[1], mid_tiles[2], mid_tiles[3])
                if fan != FAN_NONE:
                    fan_table[fan] = 1
                    free_pack_idx = 0
                    has_3_pungs_fan = True

    if has_3_pungs_fan:
        for i in range(4):
            if i == free_pack_idx:
                continue
            fan = _get_2_pungs_fan_unordered(mid_tiles[i], mid_tiles[free_pack_idx])
            if fan != FAN_NONE:
                fan_table[fan] += 1
                break
        return

    for i in range(4):
        for j in range(i + 1, 4):
            fan = _get_2_pungs_fan_unordered(mid_tiles[i], mid_tiles[j])
            if fan != FAN_NONE:
                fan_table[fan] += 1


def _calculate_3_pungs(mid_tiles: List[int], fan_table: List[int]) -> None:
    fan = _get_3_pungs_fan(mid_tiles[0], mid_tiles[1], mid_tiles[2])
    if fan != FAN_NONE:
        fan_table[fan] = 1
        return

    for i in range(3):
        for j in range(i + 1, 3):
            fan = _get_2_pungs_fan_unordered(mid_tiles[i], mid_tiles[j])
            if fan != FAN_NONE:
                fan_table[fan] += 1


def _calculate_2_pungs_unordered(mid_tiles: List[int], fan_table: List[int]) -> None:
    fan = _get_2_pungs_fan_unordered(mid_tiles[0], mid_tiles[1])
    if fan != FAN_NONE:
        fan_table[fan] += 1


def _is_pure_terminal_chows(chow_packs: List[int], pair_pack: int) -> bool:
    if tile_get_rank(pack_get_tile(pair_pack)) != 5:
        return False

    cnt_123 = 0
    cnt_789 = 0
    pair_suit = tile_get_suit(pack_get_tile(pair_pack))
    for i in range(4):
        suit = tile_get_suit(pack_get_tile(chow_packs[i]))
        if suit != pair_suit:
            return False
        rank = tile_get_rank(pack_get_tile(chow_packs[i]))
        if rank == 2:
            cnt_123 += 1
        elif rank == 8:
            cnt_789 += 1
        else:
            return False
    return cnt_123 == 2 and cnt_789 == 2


def _is_three_suited_terminal_chows(chow_packs: List[int], pair_pack: int) -> bool:
    if tile_get_rank(pack_get_tile(pair_pack)) != 5:
        return False

    suit_table_123 = [0, 0, 0, 0, 0]
    suit_table_789 = [0, 0, 0, 0, 0]
    pair_suit = tile_get_suit(pack_get_tile(pair_pack))
    for i in range(4):
        suit = tile_get_suit(pack_get_tile(chow_packs[i]))
        if suit == pair_suit:
            return False
        rank = tile_get_rank(pack_get_tile(chow_packs[i]))
        if rank == 2:
            suit_table_123[suit] += 1
        elif rank == 8:
            suit_table_789[suit] += 1
        else:
            return False

    if pair_suit == 1:
        return suit_table_123[2] and suit_table_123[3] and suit_table_789[2] and suit_table_789[3]
    if pair_suit == 2:
        return suit_table_123[1] and suit_table_123[3] and suit_table_789[1] and suit_table_789[3]
    if pair_suit == 3:
        return suit_table_123[1] and suit_table_123[2] and suit_table_789[1] and suit_table_789[2]
    return False


def _is_outside_hand(tiles: List[int]) -> bool:
    return all(is_terminal_or_honor(t) for t in tiles)


def _is_all_simples(tiles: List[int]) -> bool:
    return all(is_numbered_suit_quick(t) and not is_terminal(t) for t in tiles)


def _is_all_honors(tiles: List[int]) -> bool:
    return all(is_honor(t) for t in tiles)


def _is_all_terminals(tiles: List[int]) -> bool:
    return all(is_terminal(t) for t in tiles)


def _is_all_terminals_and_honors(tiles: List[int]) -> bool:
    return all(is_terminal_or_honor(t) for t in tiles)


def _is_all_green(tiles: List[int]) -> bool:
    return all(is_green(t) for t in tiles)


def _is_reversible(tiles: List[int]) -> bool:
    return all(is_reversible(t) for t in tiles)


def _is_red_peacock(tiles: List[int]) -> bool:
    allowed = {TILE_1s, TILE_5s, TILE_7s, TILE_9s, TILE_C}
    return all(t in allowed for t in tiles)


def _max_double_chows_for_suit(pair_counts: List[int]) -> int:
    memo: Dict[tuple, int] = {}

    def dfs(counts: List[int]) -> int:
        key = tuple(counts)
        if key in memo:
            return memo[key]
        best = 0
        for r in range(1, 8):
            if counts[r] > 0 and counts[r + 1] > 0 and counts[r + 2] > 0:
                counts[r] -= 1
                counts[r + 1] -= 1
                counts[r + 2] -= 1
                best = max(best, 1 + dfs(counts))
                counts[r] += 1
                counts[r + 1] += 1
                counts[r + 2] += 1
        memo[key] = best
        return best

    return dfs(pair_counts[:])


def _is_twice_pure_double_chows(tile_table: List[int]) -> bool:
    total = 0
    for suit in (1, 2, 3):
        counts = [0] * 10
        for r in range(1, 10):
            counts[r] = tile_table[make_tile(suit, r)] // 2
        total += _max_double_chows_for_suit(counts)
        if total >= 2:
            return True
    return False


def _is_mirror_hand(packs: List[int], pair_pack: int) -> bool:
    suit_map: Dict[int, List[tuple]] = {}
    for pack in packs:
        pack_type = pack_get_type(pack)
        if pack_type == PACK_TYPE_PAIR:
            continue
        tile = pack_get_tile(pack)
        if is_honor(tile):
            return False
        suit = tile_get_suit(tile)
        if pack_type == PACK_TYPE_CHOW:
            sig = ("c", tile_get_rank(tile))
        else:
            sig = ("p", tile_get_rank(tile))
        suit_map.setdefault(suit, []).append(sig)

    if len(suit_map) != 2:
        return False
    if any(len(v) != 2 for v in suit_map.values()):
        return False

    suits = list(suit_map.keys())
    if sorted(suit_map[suits[0]]) != sorted(suit_map[suits[1]]):
        return False

    pair_suit = tile_get_suit(pack_get_tile(pair_pack))
    if pair_suit in suit_map:
        return False
    return True

def _is_all_even_pungs(packs: List[int]) -> bool:
    for p in packs[:4]:
        if pack_get_type(p) == PACK_TYPE_CHOW:
            return False
        t = pack_get_tile(p)
        if tile_get_rank(t) % 2 == 1:
            return False
    return True


def _has_kong(packs: List[int], fixed_cnt: int) -> bool:
    return any(pack_get_type(packs[i]) == PACK_TYPE_KONG for i in range(fixed_cnt))


def _count_concealed_pungs(packs: List[int], fixed_cnt: int) -> int:
    cnt = 0
    for i in range(fixed_cnt):
        pack = packs[i]
        if pack_get_type(pack) in (PACK_TYPE_PUNG, PACK_TYPE_KONG) and pack_get_offer(pack) == 0:
            cnt += 1
    return cnt


def _check_seven_pairs_waiting(standing_table: List[int], waiting_table: List[int]) -> None:
    pairs = 0
    for t in ALL_TILES:
        cnt = standing_table[t]
        if cnt == 2 or cnt == 3:
            pairs += 1
        elif cnt == 4:
            pairs += 2

    if pairs == 6:
        for t in ALL_TILES:
            cnt = standing_table[t]
            if cnt == 1 or cnt == 3:
                waiting_table[t] = 1
                break


def _get_regular_pack_waiting(tile_table: List[int], waiting_table: List[int]) -> None:
    for t in ALL_TILES:
        if tile_table[t] < 1:
            continue
        if tile_table[t] > 1:
            waiting_table[t] = 1
            return
        if is_numbered_suit_quick(t):
            r = tile_get_rank(t)
            if r > 1 and tile_table[t - 1]:
                if r < 9:
                    waiting_table[t + 1] = 1
                if r > 2:
                    waiting_table[t - 2] = 1
                return
            if r > 2 and tile_table[t - 2]:
                waiting_table[t - 1] = 1
                return


def _check_regular_waiting(tile_table: List[int], tile_cnt: int, prev_eigen: int, waiting_table: List[int]) -> None:
    if tile_cnt == 1:
        for t in ALL_TILES:
            if tile_table[t] == 1:
                waiting_table[t] = 1
                break
        return

    if tile_cnt == 4:
        for t in ALL_TILES:
            if tile_table[t] < 2:
                continue
            tile_table[t] -= 2
            _get_regular_pack_waiting(tile_table, waiting_table)
            tile_table[t] += 2

    for t in ALL_TILES:
        if tile_table[t] < 1:
            continue
        if tile_table[t] > 2:
            eigen = make_eigen(t, t, t)
            if eigen > prev_eigen:
                tile_table[t] -= 3
                _check_regular_waiting(tile_table, tile_cnt - 3, eigen, waiting_table)
                tile_table[t] += 3
        if is_numbered_suit(t):
            if tile_get_rank(t) < 8 and tile_table[t + 1] and tile_table[t + 2]:
                eigen = make_eigen(t, t + 1, t + 2)
                if eigen >= prev_eigen:
                    tile_table[t] -= 1
                    tile_table[t + 1] -= 1
                    tile_table[t + 2] -= 1
                    _check_regular_waiting(tile_table, tile_cnt - 3, eigen, waiting_table)
                    tile_table[t] += 1
                    tile_table[t + 1] += 1
                    tile_table[t + 2] += 1


def _is_unique_waiting(standing_table: List[int], tile_cnt: int, win_tile: int) -> bool:
    waiting_table = [0] * TILE_TABLE_SIZE
    standing_table[win_tile] -= 1

    if tile_cnt == 13:
        _check_seven_pairs_waiting(standing_table, waiting_table)

    _check_regular_waiting(standing_table, tile_cnt, 0, waiting_table)

    standing_table[win_tile] += 1

    waiting = False
    for t in ALL_TILES:
        if waiting_table[t]:
            if waiting:
                return False
            waiting = True
    return waiting


def _adjust_by_waiting_form(concealed_packs: List[int], pack_cnt: int, win_tile: int, fan_table: List[int]) -> None:
    if fan_table[MELDED_HAND] or fan_table[FOUR_KONGS]:
        return

    pos_flag = 0
    for i in range(pack_cnt):
        pack = concealed_packs[i]
        pack_type = pack_get_type(pack)
        if pack_type == PACK_TYPE_CHOW:
            mid_tile = pack_get_tile(pack)
            if mid_tile == win_tile:
                pos_flag |= 0x02
            elif mid_tile + 1 == win_tile or mid_tile - 1 == win_tile:
                pos_flag |= 0x01
        elif pack_type == PACK_TYPE_PAIR:
            mid_tile = pack_get_tile(pack)
            if mid_tile == win_tile:
                pos_flag |= 0x04

    if pos_flag & 0x01:
        fan_table[EDGE_WAIT] = 1
    elif pos_flag & 0x02:
        fan_table[CLOSED_WAIT] = 1
    elif pos_flag & 0x04:
        fan_table[SINGLE_WAIT] = 1


def _adjust_by_win_flag(win_flag: int, fan_table: List[int]) -> None:
    if win_flag & WIN_FLAG_LAST_TILE:
        fan_table[LAST_TILE] = 1
    if win_flag & WIN_FLAG_SELF_DRAWN:
        fan_table[SELF_DRAWN] = 1
        if win_flag & WIN_FLAG_WALL_LAST:
            fan_table[LAST_TILE_DRAW] = 1
            fan_table[SELF_DRAWN] = 0
        if win_flag & WIN_FLAG_KONG_INVOLVED:
            fan_table[OUT_WITH_REPLACEMENT_TILE] = 1
            fan_table[SELF_DRAWN] = 0
    else:
        if win_flag & WIN_FLAG_WALL_LAST:
            fan_table[LAST_TILE_CLAIM] = 1
        if win_flag & WIN_FLAG_KONG_INVOLVED:
            fan_table[ROBBING_THE_KONG] = 1
            fan_table[LAST_TILE] = 0


def _adjust_by_initial_hands(is_dealer: bool, win_flag: int, fan_table: List[int]) -> None:
    if not (win_flag & WIN_FLAG_INITIAL):
        return
    if win_flag & WIN_FLAG_SELF_DRAWN:
        if is_dealer:
            fan_table[BLESSING_OF_HEAVEN] = 1
        else:
            fan_table[BLESSING_OF_HUMAN_2] = 1
    else:
        if is_dealer:
            fan_table[BLESSING_OF_EARTH] = 1
        else:
            fan_table[BLESSING_OF_HUMAN_1] = 1


def _adjust_by_self_drawn(packs: List[int], fixed_cnt: int, self_drawn: bool, fan_table: List[int]) -> None:
    melded_cnt = 0
    for i in range(fixed_cnt):
        if is_pack_melded(packs[i]):
            melded_cnt += 1

    if melded_cnt == 0:
        fan_table[FULLY_CONCEALED_HAND if self_drawn else CONCEALED_HAND] = 1
    elif melded_cnt == 4:
        fan_table[SELF_DRAWN if self_drawn else MELDED_HAND] = 1
    else:
        if self_drawn:
            fan_table[SELF_DRAWN] = 1


def _adjust_by_pair_tile(pair_tile: int, chow_cnt: int, fan_table: List[int]) -> None:
    if chow_cnt == 4:
        if is_numbered_suit_quick(pair_tile):
            fan_table[ALL_CHOWS] = 1
        return

    if fan_table[TWO_DRAGONS_PUNGS]:
        if is_dragons(pair_tile):
            fan_table[LITTLE_THREE_DRAGONS] = 1
            fan_table[TWO_DRAGONS_PUNGS] = 0
        return

    if fan_table[BIG_THREE_WINDS]:
        if is_winds(pair_tile):
            fan_table[LITTLE_FOUR_WINDS] = 1
            fan_table[BIG_THREE_WINDS] = 0
        return


def _adjust_by_suits(tiles: List[int], fan_table: List[int]) -> None:
    suit_flag = 0
    for t in tiles:
        suit_flag |= 1 << tile_get_suit(t)

    if not (suit_flag & 0xF1):
        fan_table[NO_HONORS] = 1

    if not (suit_flag & 0xE3):
        fan_table[ONE_VOIDED_SUIT] += 1
    if not (suit_flag & 0xE5):
        fan_table[ONE_VOIDED_SUIT] += 1
    if not (suit_flag & 0xE9):
        fan_table[ONE_VOIDED_SUIT] += 1

    if fan_table[ONE_VOIDED_SUIT] == 2:
        fan_table[ONE_VOIDED_SUIT] = 0
        if fan_table[NO_HONORS] == 0:
            fan_table[HALF_FLUSH] = 1
        else:
            fan_table[FULL_FLUSH] = 1
            fan_table[NO_HONORS] = 0

    if suit_flag == 0x1E:
        if any(is_winds(t) for t in tiles) and any(is_dragons(t) for t in tiles):
            fan_table[ALL_TYPES] = 1


def _adjust_by_rank_range(tiles: List[int], fan_table: List[int]) -> None:
    rank_flag = 0
    for t in tiles:
        if not is_numbered_suit_quick(t):
            return
        rank_flag |= 1 << tile_get_rank(t)

    if not (rank_flag & 0xFFE1):
        fan_table[LOWER_FOUR if (rank_flag & 0x0010) else LOWER_TILES] = 1
        return
    if not (rank_flag & 0xFC3F):
        fan_table[UPPER_FOUR if (rank_flag & 0x0040) else UPPER_TILES] = 1
        return
    if not (rank_flag & 0xFF8F):
        fan_table[MIDDLE_TILES] = 1


def _adjust_by_packs_traits(packs: List[int], fan_table: List[int]) -> None:
    terminal_pack = 0
    honor_pack = 0
    five_pack = 0
    even_pack = 0
    for i in range(5):
        tile = pack_get_tile(packs[i])
        if is_numbered_suit_quick(tile):
            rank = tile_get_rank(tile)
            if pack_get_type(packs[i]) == PACK_TYPE_CHOW:
                if rank in (2, 8):
                    terminal_pack += 1
                elif rank in (4, 5, 6):
                    five_pack += 1
            else:
                if rank in (1, 9):
                    terminal_pack += 1
                elif rank == 5:
                    five_pack += 1
                elif rank in (2, 4, 6, 8):
                    even_pack += 1
        else:
            honor_pack += 1

    if terminal_pack + honor_pack == 5:
        fan_table[OUTSIDE_HAND] = 1
        return
    if five_pack == 5:
        fan_table[ALL_FIVE] = 1
        return
    if even_pack == 5:
        fan_table[ALL_EVEN_PUNGS] = 1


def _adjust_by_tiles_traits(tiles: List[int], fan_table: List[int]) -> None:
    if all(not is_terminal_or_honor(t) for t in tiles):
        fan_table[ALL_SIMPLES] = 1

    if all(is_reversible(t) for t in tiles):
        fan_table[REVERSIBLE_TILES] = 1

    if all(is_green(t) for t in tiles):
        fan_table[ALL_GREEN] = 1

    if _is_red_peacock(tiles):
        fan_table[RED_PEACOCK] = 1

    if fan_table[ALL_SIMPLES]:
        return

    if all(is_honor(t) for t in tiles):
        fan_table[ALL_HONORS] = 1
        return
    if all(is_terminal(t) for t in tiles):
        fan_table[ALL_TERMINALS] = 1
        return
    if all(is_terminal_or_honor(t) for t in tiles):
        fan_table[ALL_TERMINALS_AND_HONORS] = 1


def _adjust_by_tiles_hog(tile_table: List[int], kong_cnt: int, fan_table: List[int]) -> None:
    cnt = sum(1 for v in tile_table if v == 4)
    fan_table[TILE_HOG] = cnt - kong_cnt


def _final_adjust(fan_table: List[int]) -> None:
    if fan_table[BIG_FOUR_WINDS]:
        fan_table[ALL_PUNGS] = 0
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0
    if fan_table[BIG_THREE_DRAGONS]:
        fan_table[DRAGON_PUNG] = 0
    if fan_table[ALL_GREEN]:
        fan_table[HALF_FLUSH] = 0
        fan_table[ONE_VOIDED_SUIT] = 0
    if fan_table[RED_PEACOCK]:
        fan_table[ALL_PUNGS] = 0
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0
        fan_table[DRAGON_PUNG] = 0
        fan_table[HALF_FLUSH] = 0
    if fan_table[FOUR_KONGS]:
        fan_table[SINGLE_WAIT] = 0

    if fan_table[ALL_TERMINALS]:
        fan_table[ALL_PUNGS] = 0
        fan_table[OUTSIDE_HAND] = 0
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0
        fan_table[NO_HONORS] = 0
        fan_table[DOUBLE_PUNG] = 0
    if fan_table[SEVEN_PAIRS] or fan_table[TWICE_PURE_DOUBLE_CHOWS]:
        fan_table[DOUBLE_PUNG] = 0
    if fan_table[TWICE_PURE_DOUBLE_CHOWS]:
        fan_table[PURE_DOUBLE_CHOW] = 0
        if fan_table[MIXED_DOUBLE_CHOW] > 1:
            fan_table[MIXED_DOUBLE_CHOW] = 1
        if fan_table[SHORT_STRAIGHT] > 1:
            fan_table[SHORT_STRAIGHT] = 1
        if fan_table[TWO_TERMINAL_CHOWS] > 1:
            fan_table[TWO_TERMINAL_CHOWS] = 1
        fan_table[CONCEALED_HAND] = 0
        fan_table[FULLY_CONCEALED_HAND] = 0

    if fan_table[LITTLE_FOUR_WINDS]:
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0

    if fan_table[LITTLE_THREE_DRAGONS]:
        fan_table[DRAGON_PUNG] = 0

    if fan_table[ALL_HONORS]:
        fan_table[ALL_PUNGS] = 0
        fan_table[OUTSIDE_HAND] = 0
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0
        fan_table[ONE_VOIDED_SUIT] = 0
    if fan_table[FOUR_CONCEALED_PUNGS]:
        fan_table[ALL_PUNGS] = 0
        fan_table[CONCEALED_HAND] = 0
        if fan_table[FULLY_CONCEALED_HAND]:
            fan_table[FULLY_CONCEALED_HAND] = 0
            fan_table[SELF_DRAWN] = 1
    if fan_table[PURE_TERMINAL_CHOWS]:
        fan_table[FULL_FLUSH] = 0
        fan_table[ALL_CHOWS] = 0
        fan_table[NO_HONORS] = 0
    if fan_table[FOUR_PURE_SHIFTED_PUNGS]:
        fan_table[ALL_PUNGS] = 0

    if fan_table[ALL_TERMINALS_AND_HONORS]:
        fan_table[ALL_PUNGS] = 0
        fan_table[OUTSIDE_HAND] = 0
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0

    if fan_table[ALL_EVEN_PUNGS]:
        fan_table[ALL_PUNGS] = 0
        fan_table[ALL_SIMPLES] = 0
        fan_table[NO_HONORS] = 0
    if fan_table[UPPER_TILES]:
        fan_table[NO_HONORS] = 0
    if fan_table[MIDDLE_TILES]:
        fan_table[ALL_SIMPLES] = 0
        fan_table[NO_HONORS] = 0
    if fan_table[LOWER_TILES]:
        fan_table[NO_HONORS] = 0

    if fan_table[THREE_SUITED_TERMINAL_CHOWS]:
        fan_table[ALL_CHOWS] = 0
        fan_table[NO_HONORS] = 0
        fan_table[MIRROR_HAND] = 0
    if fan_table[ALL_FIVE]:
        fan_table[ALL_SIMPLES] = 0
        fan_table[NO_HONORS] = 0

    if fan_table[UPPER_FOUR]:
        fan_table[NO_HONORS] = 0
    if fan_table[LOWER_FOUR]:
        fan_table[NO_HONORS] = 0
    if fan_table[BIG_THREE_WINDS]:
        if not fan_table[ALL_HONORS] and not fan_table[ALL_TERMINALS_AND_HONORS]:
            fan_table[PUNG_OF_TERMINALS_OR_HONORS] -= 3

    if fan_table[REVERSIBLE_TILES]:
        fan_table[ONE_VOIDED_SUIT] = 0
    if fan_table[LAST_TILE_DRAW]:
        fan_table[SELF_DRAWN] = 0
    if fan_table[OUT_WITH_REPLACEMENT_TILE]:
        fan_table[SELF_DRAWN] = 0

    if fan_table[MELDED_HAND]:
        fan_table[SINGLE_WAIT] = 0
    if fan_table[TWO_DRAGONS_PUNGS]:
        fan_table[DRAGON_PUNG] = 0

    if fan_table[FULLY_CONCEALED_HAND]:
        fan_table[SELF_DRAWN] = 0

    if fan_table[ALL_CHOWS]:
        fan_table[NO_HONORS] = 0
    if fan_table[ALL_SIMPLES]:
        fan_table[NO_HONORS] = 0

    if fan_table[BLESSING_OF_HEAVEN] or fan_table[BLESSING_OF_HUMAN_2]:
        fan_table[SELF_DRAWN] = 0


def _adjust_by_winds(tile: int, prevalent_wind: int, seat_wind: int, fan_table: List[int]) -> None:
    is_deducted = (
        fan_table[BIG_THREE_WINDS]
        or fan_table[ALL_TERMINALS_AND_HONORS]
        or fan_table[ALL_HONORS]
        or fan_table[LITTLE_FOUR_WINDS]
    )

    delta = tile - TILE_E
    if delta == prevalent_wind - Wind.EAST:
        fan_table[PREVALENT_WIND] = 1
        if not is_deducted:
            fan_table[PUNG_OF_TERMINALS_OR_HONORS] -= 1
    if delta == seat_wind - Wind.EAST:
        fan_table[SEAT_WIND] = 1
        if seat_wind != prevalent_wind and not is_deducted:
            fan_table[PUNG_OF_TERMINALS_OR_HONORS] -= 1

def _adjust_by_win_flag_4_special_form(seat_wind: int, win_flag: int, fan_table: List[int]) -> None:
    _adjust_by_win_flag(win_flag, fan_table)
    if SUPPORT_BLESSINGS:
        if win_flag & WIN_FLAG_INITIAL:
            _adjust_by_initial_hands(seat_wind == Wind.EAST, win_flag, fan_table)


def _is_seven_pairs(tile_table: List[int]) -> bool:
    for t in ALL_TILES:
        if tile_table[t] & 1:
            return False
    return True


def _is_seven_shifted_pairs(tile_table: List[int], suit: int) -> bool:
    if suit == TILE_SUIT_HONORS:
        return False
    t3 = make_tile(suit, 3)
    if tile_table[t3] == 2 and tile_table[t3 + 1] == 2 and tile_table[t3 + 2] == 2 and tile_table[t3 + 3] == 2 and tile_table[t3 + 4] == 2:
        if tile_table[t3 - 1] == 2:
            return tile_table[t3 - 2] == 2 or tile_table[t3 + 5] == 2
        return tile_table[t3 + 5] == 2 and tile_table[t3 + 6] == 2
    return False


def _is_thirteen_orphans(unique_tiles: List[int]) -> bool:
    return len(unique_tiles) == 13 and unique_tiles == STANDARD_THIRTEEN_ORPHANS


def _calculate_honors_and_knitted_tiles(unique_tiles: List[int], fan_table: List[int]) -> bool:
    if len(unique_tiles) != 14:
        return False

    honor_begin = None
    for i, t in enumerate(unique_tiles):
        if is_honor(t):
            honor_begin = i
            break
    if honor_begin is None:
        honor_begin = len(unique_tiles)

    numbered_cnt = honor_begin
    if numbered_cnt > 9 or numbered_cnt < 7:
        return False

    if not any(all(t in seq for t in unique_tiles[:honor_begin]) for seq in STANDARD_KNITTED_STRAIGHT):
        return False

    if numbered_cnt == 7 and unique_tiles[7:] == STANDARD_THIRTEEN_ORPHANS[6:]:
        fan_table[GREATER_HONORS_AND_KNITTED_TILES] = 1
        return True
    if set(unique_tiles[honor_begin:]).issubset(set(STANDARD_THIRTEEN_ORPHANS[6:])):
        fan_table[LESSER_HONORS_AND_KNITTED_TILES] = 1
        if numbered_cnt == 9:
            fan_table[KNITTED_STRAIGHT] = 1
        return True

    return False


def _calculate_special_form_fan(
    standing_table: List[int],
    win_tile: int,
    unique_tiles: List[int],
    seat_wind: int,
    win_flag: int,
    fan_table: List[int],
) -> bool:
    if _is_seven_pairs(standing_table):
        s = tile_get_suit(win_tile)
        if _is_seven_shifted_pairs(standing_table, s):
            fan_table[SEVEN_SHIFTED_PAIRS] = 1
            if standing_table[make_tile(s, 1)] == 0 and standing_table[make_tile(s, 9)] == 0:
                fan_table[ALL_SIMPLES] = 1
            _adjust_by_win_flag_4_special_form(seat_wind, win_flag, fan_table)
        else:
            fan_table[SEVEN_PAIRS] = 1
            _adjust_by_suits(unique_tiles, fan_table)
            _adjust_by_tiles_traits(unique_tiles, fan_table)
            _adjust_by_rank_range(unique_tiles, fan_table)
            _adjust_by_tiles_hog(standing_table, 0, fan_table)
            _adjust_by_win_flag_4_special_form(seat_wind, win_flag, fan_table)
            _final_adjust(fan_table)

            temp_table = list(standing_table)
            result = _divide_win_hand(temp_table, [], 0)
            for div in result.divisions:
                chow_packs = [p for p in div.packs[:4] if pack_get_type(p) == PACK_TYPE_CHOW]
                if len(chow_packs) == 4:
                    mid_tiles = sorted(pack_get_tile(p) for p in chow_packs)
                    if mid_tiles[0] == mid_tiles[1] and mid_tiles[2] == mid_tiles[3] and mid_tiles[0] != mid_tiles[2]:
                        fan_table[TWICE_PURE_DOUBLE_CHOWS] = 1
                        break
        return True

    if _calculate_honors_and_knitted_tiles(unique_tiles, fan_table):
        _adjust_by_win_flag_4_special_form(seat_wind, win_flag, fan_table)
        return True

    if _is_thirteen_orphans(unique_tiles):
        fan_table[THIRTEEN_ORPHANS] = 1
        _adjust_by_win_flag_4_special_form(seat_wind, win_flag, fan_table)
        return True

    return False


def _calculate_nine_gates_fan(
    standing_table: List[int],
    win_tile: int,
    seat_wind: int,
    win_flag: int,
    fan_table: List[int],
) -> bool:
    if not is_numbered_suit_quick(win_tile):
        return False
    s = None
    r = None
    heavenly = seat_wind == Wind.EAST and (win_flag & (WIN_FLAG_INITIAL | WIN_FLAG_SELF_DRAWN)) == (WIN_FLAG_INITIAL | WIN_FLAG_SELF_DRAWN)
    if heavenly:
        if not NINE_GATES_WHEN_BLESSING_OF_HEAVEN:
            return False
        s = tile_get_suit(win_tile)
        win_tile2 = 0
        for i in range(2, 9):
            tmp = make_tile(s, i)
            cnt = standing_table[tmp]
            if cnt == 0:
                return False
            if cnt == 2:
                win_tile2 = tmp
        if win_tile2 != 0:
            if standing_table[make_tile(s, 1)] == 3 and standing_table[make_tile(s, 9)] == 3:
                r = tile_get_rank(win_tile2)
            else:
                return False
        else:
            if standing_table[make_tile(s, 1)] == 4 and standing_table[make_tile(s, 9)] == 3:
                r = 1
            elif standing_table[make_tile(s, 1)] == 3 and standing_table[make_tile(s, 9)] == 4:
                r = 2
            else:
                return False
    else:
        s = tile_get_suit(win_tile)
        r = tile_get_rank(win_tile)
        if r == 1:
            if standing_table[win_tile] != 4 or standing_table[make_tile(s, 9)] != 3:
                return False
            for i in range(2, 9):
                if standing_table[make_tile(s, i)] != 1:
                    return False
        elif r == 9:
            if standing_table[win_tile] != 4 or standing_table[make_tile(s, 1)] != 3:
                return False
            for i in range(2, 9):
                if standing_table[make_tile(s, i)] != 1:
                    return False
        else:
            if standing_table[win_tile] != 2:
                return False
            if standing_table[make_tile(s, 1)] != 3 or standing_table[make_tile(s, 9)] != 3:
                return False
            for i in range(2, r):
                if standing_table[make_tile(s, i)] != 1:
                    return False
            for i in range(r + 1, 9):
                if standing_table[make_tile(s, i)] != 1:
                    return False

    fan_table[NINE_GATES] = 1

    if r in (1, 9):
        fan_table[PURE_STRAIGHT] = 1
        fan_table[TILE_HOG] = 1
    elif r in (2, 8):
        fan_table[TWO_CONCEALED_PUNGS] = 1
        fan_table[SHORT_STRAIGHT] = 1
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 1
    elif r == 5:
        fan_table[TWO_CONCEALED_PUNGS] = 1
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 1
    elif r in (3, 4, 6, 7):
        fan_table[SHORT_STRAIGHT] = 1

    _adjust_by_win_flag_4_special_form(seat_wind, win_flag, fan_table)

    return True


def _get_fan_by_table(fan_table: List[int]) -> int:
    fan = 0
    for i in range(1, FAN_TABLE_SIZE):
        if fan_table[i] == 0:
            continue
        fan += FAN_VALUE_TABLE[i] * fan_table[i]
    return fan

def _calculate_regular_fan(
    packs: List[int],
    fixed_table: List[int],
    standing_table: List[int],
    unique_tiles: List[int],
    calculate_param: CalculateParam,
    unique_waiting: bool,
    win_flag: int,
    fan_table: List[int],
) -> None:
    fixed_cnt = calculate_param.hand_tiles.pack_count
    pair_pack = 0
    chow_packs: List[int] = []
    pung_packs: List[int] = []
    chow_cnt = 0
    pung_cnt = 0
    concealed_pung_cnt = 0
    melded_kong_cnt = 0
    concealed_kong_cnt = 0

    for i in range(5):
        pack = packs[i]
        pack_type = pack_get_type(pack)
        if pack_type == PACK_TYPE_CHOW:
            chow_packs.append(pack)
            chow_cnt += 1
        elif pack_type == PACK_TYPE_PUNG:
            pung_packs.append(pack)
            pung_cnt += 1
            if not is_pack_melded(pack):
                concealed_pung_cnt += 1
        elif pack_type == PACK_TYPE_KONG:
            pung_packs.append(pack)
            pung_cnt += 1
            if is_pack_melded(pack):
                melded_kong_cnt += 1
            else:
                concealed_kong_cnt += 1
        elif pack_type == PACK_TYPE_PAIR:
            pair_pack = pack
        else:
            return

    if pair_pack == 0 or chow_cnt + pung_cnt != 4:
        return

    win_tile = calculate_param.win_tile

    _adjust_by_win_flag(win_flag, fan_table)

    if (win_flag & WIN_FLAG_SELF_DRAWN) == 0:
        if not any(
            (not is_pack_melded(pack))
            and (pack_get_tile(pack) - 1 == win_tile or pack_get_tile(pack) == win_tile or pack_get_tile(pack) + 1 == win_tile)
            for pack in chow_packs
        ):
            for i in range(pung_cnt):
                if pack_get_tile(pung_packs[i]) == win_tile and not is_pack_melded(pung_packs[i]):
                    concealed_pung_cnt -= 1

    if pung_cnt != 0:
        _calculate_kongs(concealed_pung_cnt, melded_kong_cnt, concealed_kong_cnt, fan_table)

        if pung_cnt == 4:
            if fan_table[FOUR_KONGS] == 0 and fan_table[FOUR_CONCEALED_PUNGS] == 0:
                fan_table[ALL_PUNGS] = 1

        for i in range(pung_cnt):
            fan = _get_1_pung_fan(pack_get_tile(pung_packs[i]))
            if fan != FAN_NONE:
                fan_table[fan] += 1

    if chow_cnt == 4:
        if _is_three_suited_terminal_chows(chow_packs, pair_pack):
            fan_table[THREE_SUITED_TERMINAL_CHOWS] = 1
        elif _is_pure_terminal_chows(chow_packs, pair_pack):
            fan_table[PURE_TERMINAL_CHOWS] = 1
        else:
            mid_tiles = sorted(pack_get_tile(p) for p in chow_packs)
            _calculate_4_chows(mid_tiles, fan_table)
            if mid_tiles[0] == mid_tiles[1] and mid_tiles[2] == mid_tiles[3] and mid_tiles[0] != mid_tiles[2]:
                fan_table[TWICE_PURE_DOUBLE_CHOWS] = 1
    elif chow_cnt == 3:
        mid_tiles = sorted(pack_get_tile(p) for p in chow_packs)
        _calculate_3_chows(mid_tiles, fan_table)
    elif chow_cnt == 2:
        mid_tiles_chow = [pack_get_tile(chow_packs[0]), pack_get_tile(chow_packs[1])]
        mid_tiles_pung = [pack_get_tile(pung_packs[0]), pack_get_tile(pung_packs[1])]
        _calculate_2_chows_unordered(mid_tiles_chow, fan_table)
        _calculate_2_pungs_unordered(mid_tiles_pung, fan_table)
    elif chow_cnt == 1:
        mid_tiles = sorted(pack_get_tile(p) for p in pung_packs[:3])
        _calculate_3_pungs(mid_tiles, fan_table)
    elif chow_cnt == 0:
        mid_tiles = sorted(pack_get_tile(p) for p in pung_packs)
        _calculate_4_pungs(mid_tiles, fan_table)

    if fan_table[TWICE_PURE_DOUBLE_CHOWS] == 0:
        if _is_mirror_hand(packs, pair_pack):
            fan_table[MIRROR_HAND] = 1

    _adjust_by_self_drawn(packs, fixed_cnt, (win_flag & WIN_FLAG_SELF_DRAWN) != 0, fan_table)

    if SUPPORT_BLESSINGS:
        if fixed_cnt == 0 and (win_flag & WIN_FLAG_INITIAL):
            _adjust_by_initial_hands(calculate_param.seat_wind == Wind.EAST, win_flag, fan_table)

    _adjust_by_pair_tile(pack_get_tile(pair_pack), chow_cnt, fan_table)
    _adjust_by_packs_traits(packs, fan_table)

    merged_table = [standing_table[i] + fixed_table[i] for i in range(TILE_TABLE_SIZE)]

    _adjust_by_suits(unique_tiles, fan_table)
    _adjust_by_tiles_traits(unique_tiles, fan_table)
    _adjust_by_rank_range(unique_tiles, fan_table)
    if fan_table[QUADRUPLE_CHOW] == 0:
        _adjust_by_tiles_hog(merged_table, melded_kong_cnt + concealed_kong_cnt, fan_table)

    if unique_waiting:
        _adjust_by_waiting_form(packs[fixed_cnt:], 5 - fixed_cnt, win_tile, fan_table)

    _final_adjust(fan_table)

    little_three_winds_deduct = 0
    has_prev_wind_pung = False
    has_seat_wind_pung = False
    if is_winds(pack_get_tile(pair_pack)):
        wind_pung_cnt = 0
        for i in range(pung_cnt):
            wtile = pack_get_tile(pung_packs[i])
            if is_winds(wtile):
                wind_pung_cnt += 1
                if (wtile - TILE_E) == calculate_param.prevalent_wind:
                    has_prev_wind_pung = True
                if (wtile - TILE_E) == calculate_param.seat_wind:
                    has_seat_wind_pung = True
        if wind_pung_cnt == 2:
            fan_table[LITTLE_THREE_WINDS] = 1
            little_three_winds_deduct = 2

    if fan_table[BIG_FOUR_WINDS] == 0:
        prevalent_wind = calculate_param.prevalent_wind
        seat_wind = calculate_param.seat_wind
        for i in range(pung_cnt):
            tile = pack_get_tile(pung_packs[i])
            if is_winds(tile):
                _adjust_by_winds(tile, prevalent_wind, seat_wind, fan_table)

    if fan_table[LITTLE_THREE_WINDS] and little_three_winds_deduct > 0:
        deducted_by_winds = 0
        if has_prev_wind_pung:
            deducted_by_winds += 1
        if has_seat_wind_pung and calculate_param.seat_wind != calculate_param.prevalent_wind:
            deducted_by_winds += 1
        remaining = little_three_winds_deduct - deducted_by_winds
        if remaining > 0 and fan_table[PUNG_OF_TERMINALS_OR_HONORS] >= remaining:
            fan_table[PUNG_OF_TERMINALS_OR_HONORS] -= remaining

    if all(v == 0 for v in fan_table):
        fan_table[CHICKEN_HAND] = 1


def _calculate_knitted_straight_fan(
    fixed_table: List[int],
    standing_table: List[int],
    calculate_param: CalculateParam,
    win_flag: int,
    fan_table: List[int],
) -> bool:
    hand_tiles = calculate_param.hand_tiles
    fixed_packs = hand_tiles.fixed_packs
    win_tile = calculate_param.win_tile

    if not _has_pair(standing_table):
        return False

    matched_seq = None
    for seq in STANDARD_KNITTED_STRAIGHT:
        if all(standing_table[t] > 0 for t in seq):
            matched_seq = seq
            break
    if matched_seq is None:
        return False

    tile_table = list(standing_table)
    for t in matched_seq:
        tile_table[t] -= 1

    result = DivisionResult()
    work = Division()

    fixed_cnt = hand_tiles.pack_count
    if fixed_cnt == 1:
        work.packs[3] = fixed_packs[0]
    _divide_recursively(tile_table, fixed_cnt + 3, 0, 0, work, result)
    if len(result.divisions) != 1:
        return False

    packs = result.divisions[0].packs
    involved_pack = packs[3]
    pair_tile = pack_get_tile(packs[4])

    fan_table[KNITTED_STRAIGHT] = 1

    involved_type = pack_get_type(involved_pack)
    if involved_type == PACK_TYPE_CHOW:
        if is_numbered_suit_quick(pair_tile):
            fan_table[ALL_CHOWS] = 1
        if fixed_table[pair_tile] + standing_table[pair_tile] == 4:
            fan_table[TILE_HOG] = 1
    else:
        involved_tile = pack_get_tile(involved_pack)
        if is_honor(involved_tile):
            if is_winds(involved_tile):
                fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 1
                _adjust_by_winds(involved_tile, calculate_param.prevalent_wind, calculate_param.seat_wind, fan_table)
                if is_dragons(pair_tile):
                    fan_table[ALL_TYPES] = 1
            else:
                fan_table[DRAGON_PUNG] = 1
                if is_winds(pair_tile):
                    fan_table[ALL_TYPES] = 1
        else:
            if is_terminal(involved_tile):
                fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 1
            if not is_honor(pair_tile):
                fan_table[NO_HONORS] = 1
            if involved_type != PACK_TYPE_KONG and fixed_table[involved_tile] + standing_table[involved_tile] == 4:
                fan_table[TILE_HOG] = 1

    _adjust_by_win_flag(win_flag, fan_table)

    if is_pack_melded(involved_pack):
        if involved_type == PACK_TYPE_KONG:
            fan_table[MELDED_KONG] = 1
    else:
        if involved_type == PACK_TYPE_KONG:
            fan_table[CONCEALED_KONG] = 1
        if win_flag & WIN_FLAG_SELF_DRAWN:
            fan_table[FULLY_CONCEALED_HAND] = 1
            fan_table[SELF_DRAWN] = 0
        else:
            fan_table[CONCEALED_HAND] = 1

    if SUPPORT_BLESSINGS:
        if fixed_cnt == 0 and (win_flag & WIN_FLAG_INITIAL):
            _adjust_by_initial_hands(calculate_param.seat_wind == Wind.EAST, win_flag, fan_table)

    heavenly = calculate_param.seat_wind == Wind.EAST and fixed_cnt == 0 and (win_flag & (WIN_FLAG_INITIAL | WIN_FLAG_SELF_DRAWN)) == (WIN_FLAG_INITIAL | WIN_FLAG_SELF_DRAWN)

    if fixed_cnt == 0:
        if not heavenly:
            if _is_unique_waiting(tile_table, 4, win_tile):
                _adjust_by_waiting_form(packs[3:], 2, win_tile, fan_table)
    else:
        if all(win_tile != t for t in matched_seq):
            fan_table[SINGLE_WAIT] = 1
        else:
            if standing_table[win_tile] == 3:
                fan_table[SINGLE_WAIT] = 1

    _final_adjust(fan_table)
    return True


def calculate_fan(calculate_param: CalculateParam, fan_table: Optional[List[int]] = None) -> int:
    hand_tiles = calculate_param.hand_tiles
    fixed_cnt = hand_tiles.pack_count
    standing_cnt = hand_tiles.tile_count

    if standing_cnt <= 0 or fixed_cnt < 0 or fixed_cnt > 4 or fixed_cnt * 3 + standing_cnt != 13:
        return ERROR_WRONG_TILES_COUNT

    win_tile = calculate_param.win_tile

    fixed_table = _new_tile_table()
    standing_table = _new_tile_table()
    _map_packs(hand_tiles.fixed_packs, fixed_cnt, fixed_table)
    _map_tiles(hand_tiles.standing_tiles, standing_cnt, standing_table)
    standing_table[win_tile] += 1

    unique_tiles = _table_unique(fixed_table, standing_table)

    win_flag = calculate_param.win_flag

    if standing_table[win_tile] != 1:
        win_flag &= ~WIN_FLAG_LAST_TILE
    if fixed_table[win_tile] == 3:
        win_flag |= WIN_FLAG_LAST_TILE

    if win_flag & WIN_FLAG_KONG_INVOLVED:
        if win_flag & WIN_FLAG_SELF_DRAWN:
            if not any(pack_get_type(p) == PACK_TYPE_KONG for p in hand_tiles.fixed_packs[:fixed_cnt]):
                win_flag &= ~WIN_FLAG_KONG_INVOLVED
        else:
            if fixed_table[win_tile] != 0 or standing_table[win_tile] != 1:
                win_flag &= ~WIN_FLAG_KONG_INVOLVED

    max_fan = 0
    tmp_table = [0] * FAN_TABLE_SIZE

    if fixed_cnt == 0:
        if (_calculate_special_form_fan(standing_table, win_tile, unique_tiles, calculate_param.seat_wind, win_flag, tmp_table)
            or _calculate_knitted_straight_fan(fixed_table, standing_table, calculate_param, win_flag, tmp_table)
            or _calculate_nine_gates_fan(standing_table, win_tile, calculate_param.seat_wind, win_flag, tmp_table)):
            max_fan = _get_fan_by_table(tmp_table)
    elif fixed_cnt == 1:
        if _calculate_knitted_straight_fan(fixed_table, standing_table, calculate_param, win_flag, tmp_table):
            max_fan = _get_fan_by_table(tmp_table)

    if max_fan == 0 or tmp_table[SEVEN_PAIRS] == 1:
        heavenly = calculate_param.seat_wind == Wind.EAST and fixed_cnt == 0 and (win_flag & (WIN_FLAG_INITIAL | WIN_FLAG_SELF_DRAWN)) == (WIN_FLAG_INITIAL | WIN_FLAG_SELF_DRAWN)
        unique_waiting = (not heavenly) and _is_unique_waiting(standing_table, standing_cnt, win_tile)

        result = _divide_win_hand(standing_table, hand_tiles.fixed_packs, fixed_cnt)
        if result.divisions:
            selected: Optional[List[int]] = None
            for div in result.divisions:
                current_table = [0] * FAN_TABLE_SIZE
                _calculate_regular_fan(div.packs, fixed_table, standing_table, unique_tiles, calculate_param, unique_waiting, win_flag, current_table)
                current_fan = _get_fan_by_table(current_table)
                if current_fan > max_fan:
                    max_fan = current_fan
                    selected = current_table
                elif current_fan == max_fan:
                    if current_table[PURE_TRIPLE_CHOW] == 1 or tmp_table[SEVEN_PAIRS] == 1 or current_table[TRIPLE_PUNG]:
                        selected = current_table
            if fan_table is not None and selected is not None:
                tmp_table = selected

    if max_fan == 0:
        return ERROR_NOT_WIN

    max_fan += calculate_param.flower_count

    if fan_table is not None:
        for i in range(FAN_TABLE_SIZE):
            fan_table[i] = tmp_table[i]
        fan_table[FLOWER_TILES] = calculate_param.flower_count

    return max_fan

"""
TODO: Add a match count mode. In this mode, the hand will be counted in the player's database, which can show how many
 fan they roned in their lifetime based on their hand. This should include buttons: pass, ting pai (a switch), fangchong,
 ron (which will count fan based on their current setting), zimo-ed. 
"""
