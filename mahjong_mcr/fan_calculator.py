"""
Exact port of Classes/mahjong-algorithm/fan_calculator.cpp and fan_calculator.h
from ChineseOfficialMahjongHelper (MIT License).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .tile import (
    ALL_TILES,
    HandTiles,
    PACK_TYPE_CHOW,
    PACK_TYPE_KONG,
    PACK_TYPE_PAIR,
    PACK_TYPE_PUNG,
    TILE_TABLE_SIZE,
    TILE_E, TILE_S, TILE_W, TILE_N, TILE_C, TILE_F, TILE_P,
    TILE_SUIT_HONORS,
    is_dragons,
    is_green,
    is_honor,
    is_numbered_suit,
    is_numbered_suit_quick,
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
SUPPORT_BLESSINGS = 0

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

FAN_TABLE_SIZE = 83

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
    "花牌", "明暗杠",
]

FAN_VALUE_TABLE = [
    0,
    88, 88, 88, 88, 88, 88, 88,
    64, 64, 64, 64, 64, 64,
    48, 48,
    32, 32, 32,
    24, 24, 24, 24, 24, 24, 24, 24, 24,
    16, 16, 16, 16, 16, 16,
    12, 12, 12, 12, 12,
    8, 8, 8, 8, 8, 8, 8, 8, 8,
    6, 6, 6, 6, 6, 6, 6,
    4, 4, 4, 4,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1,
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


def _calculate_2_of_4_chows(tile0: int, tile1: int, tile2: int, tile3: int, fan_table: List[int]) -> None:
    all_fans = [
        _get_2_chows_fan_unordered(tile0, tile1),
        _get_2_chows_fan_unordered(tile0, tile2),
        _get_2_chows_fan_unordered(tile0, tile3),
        _get_2_chows_fan_unordered(tile1, tile2),
        _get_2_chows_fan_unordered(tile1, tile3),
        _get_2_chows_fan_unordered(tile2, tile3),
    ]
    _exclusionary_rule(all_fans, 6, 2, fan_table)


def _calculate_2_of_3_chows(tile0: int, tile1: int, tile2: int, fan_table: List[int]) -> None:
    all_fans = [
        _get_2_chows_fan_unordered(tile0, tile1),
        _get_2_chows_fan_unordered(tile0, tile2),
        _get_2_chows_fan_unordered(tile1, tile2),
    ]
    _exclusionary_rule(all_fans, 3, 1, fan_table)


def _calculate_3_of_4_pungs(tile0: int, tile1: int, tile2: int, tile_extra: int, fan_table: List[int]) -> bool:
    fan = _get_3_pungs_fan(tile0, tile1, tile2)
    if fan != FAN_NONE:
        fan_table[fan] = 1
        return True
    return False


def _calculate_2_of_4_pungs(tile0: int, tile1: int, tile2: int, tile3: int, fan_table: List[int]) -> None:
    all_fans = [
        _get_2_pungs_fan_unordered(tile0, tile1),
        _get_2_pungs_fan_unordered(tile0, tile2),
        _get_2_pungs_fan_unordered(tile0, tile3),
        _get_2_pungs_fan_unordered(tile1, tile2),
        _get_2_pungs_fan_unordered(tile1, tile3),
        _get_2_pungs_fan_unordered(tile2, tile3),
    ]
    _exclusionary_rule(all_fans, 6, 1, fan_table)


def _calculate_2_of_3_pungs(tile0: int, tile1: int, tile2: int, fan_table: List[int]) -> None:
    all_fans = [
        _get_2_pungs_fan_unordered(tile0, tile1),
        _get_2_pungs_fan_unordered(tile0, tile2),
        _get_2_pungs_fan_unordered(tile1, tile2),
    ]
    _exclusionary_rule(all_fans, 3, 1, fan_table)


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


def _is_regular_waiting_form_unique(tile_table: List[int], left_cnt: int, win_tile: int) -> bool:
    if left_cnt == 2:
        tiles = []
        for t in ALL_TILES:
            if tile_table[t] == 1:
                tiles.append(t)
        if len(tiles) != 2:
            return False
        t0, t1 = tiles
        if t0 == t1 and t0 == win_tile:
            return True
        if is_numbered_suit(t0):
            r0 = tile_get_rank(t0)
            if t1 == t0 + 1 and win_tile in (t0 - 1, t0 + 2):
                return True
            if t1 == t0 + 2 and win_tile == t0 + 1:
                return True
        return False
    for t in ALL_TILES:
        if tile_table[t] < 1:
            continue
        if tile_table[t] > 2:
            tile_table[t] -= 3
            if _is_regular_waiting_form_unique(tile_table, left_cnt - 3, win_tile):
                tile_table[t] += 3
                return True
            tile_table[t] += 3
        if is_numbered_suit(t):
            if tile_get_rank(t) < 8 and tile_table[t + 1] and tile_table[t + 2]:
                tile_table[t] -= 1
                tile_table[t + 1] -= 1
                tile_table[t + 2] -= 1
                if _is_regular_waiting_form_unique(tile_table, left_cnt - 3, win_tile):
                    tile_table[t] += 1
                    tile_table[t + 1] += 1
                    tile_table[t + 2] += 1
                    return True
                tile_table[t] += 1
                tile_table[t + 1] += 1
                tile_table[t + 2] += 1
    return False


def _is_unique_waiting(tile_table: List[int], standing_cnt: int, win_tile: int) -> bool:
    tmp_table = list(tile_table)
    tmp_table[win_tile] += 1
    return _is_regular_waiting_form_unique(tmp_table, standing_cnt + 1, win_tile)


def _adjust_by_waiting_form(packs: List[int], pack_cnt: int, win_tile: int, fan_table: List[int]) -> None:
    if pack_cnt < 2:
        return
    if pack_get_type(packs[0]) == PACK_TYPE_PAIR:
        if pack_get_tile(packs[0]) == win_tile:
            fan_table[SINGLE_WAIT] = 1
        return
    if pack_get_type(packs[1]) == PACK_TYPE_PAIR:
        if pack_get_tile(packs[1]) == win_tile:
            fan_table[SINGLE_WAIT] = 1
        return
    for i in range(pack_cnt):
        if pack_get_type(packs[i]) == PACK_TYPE_CHOW:
            t = pack_get_tile(packs[i])
            if win_tile == t - 1 and tile_get_rank(t) == 8:
                fan_table[EDGE_WAIT] = 1
            elif win_tile == t + 1 and tile_get_rank(t) == 2:
                fan_table[EDGE_WAIT] = 1
            elif win_tile == t:
                fan_table[CLOSED_WAIT] = 1


def _adjust_by_win_flag(win_flag: int, fan_table: List[int]) -> None:
    if win_flag & WIN_FLAG_SELF_DRAWN:
        fan_table[SELF_DRAWN] = 1
    if win_flag & WIN_FLAG_WALL_LAST:
        if win_flag & WIN_FLAG_SELF_DRAWN:
            fan_table[LAST_TILE_DRAW] = 1
        else:
            fan_table[LAST_TILE_CLAIM] = 1
    if win_flag & WIN_FLAG_KONG_INVOLVED:
        if win_flag & WIN_FLAG_SELF_DRAWN:
            fan_table[OUT_WITH_REPLACEMENT_TILE] = 1
        else:
            fan_table[ROBBING_THE_KONG] = 1
    if win_flag & WIN_FLAG_LAST_TILE:
        fan_table[LAST_TILE] = 1


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


def _adjust_by_tiles_hog(standing_table: List[int], fixed_cnt: int, fan_table: List[int]) -> None:
    for t in ALL_TILES:
        cnt = standing_table[t]
        if cnt >= 4:
            fan_table[TILE_HOG] += 1


def _adjust_by_suits(unique_tiles: List[int], fan_table: List[int]) -> None:
    suits = set(tile_get_suit(t) for t in unique_tiles if tile_get_suit(t) != TILE_SUIT_HONORS)
    has_honors = any(tile_get_suit(t) == TILE_SUIT_HONORS for t in unique_tiles)
    if len(suits) == 1:
        if has_honors:
            fan_table[HALF_FLUSH] = 1
        else:
            fan_table[FULL_FLUSH] = 1
    elif len(suits) == 2:
        fan_table[ONE_VOIDED_SUIT] = 1
    if not has_honors:
        fan_table[NO_HONORS] = 1
    if len(suits) == 3 and has_honors:
        fan_table[ALL_TYPES] = 1


def _adjust_by_tiles_traits(unique_tiles: List[int], fan_table: List[int]) -> None:
    if _is_all_simples(unique_tiles):
        fan_table[ALL_SIMPLES] = 1
    if _is_reversible(unique_tiles):
        fan_table[REVERSIBLE_TILES] = 1
    if _is_all_green(unique_tiles):
        fan_table[ALL_GREEN] = 1
    if _is_all_honors(unique_tiles):
        fan_table[ALL_HONORS] = 1
    if _is_all_terminals(unique_tiles):
        fan_table[ALL_TERMINALS] = 1
    if _is_all_terminals_and_honors(unique_tiles):
        fan_table[ALL_TERMINALS_AND_HONORS] = 1


def _adjust_by_rank_range(unique_tiles: List[int], fan_table: List[int]) -> None:
    max_r = 0
    min_r = 10
    for t in unique_tiles:
        if is_numbered_suit_quick(t):
            r = tile_get_rank(t)
            max_r = max(max_r, r)
            min_r = min(min_r, r)
    if max_r <= 4:
        fan_table[LOWER_FOUR] = 1
    if min_r >= 6:
        fan_table[UPPER_FOUR] = 1
    if min_r >= 6 and max_r <= 9:
        fan_table[UPPER_TILES] = 1
    if min_r >= 4 and max_r <= 6:
        fan_table[MIDDLE_TILES] = 1
    if min_r >= 1 and max_r <= 3:
        fan_table[LOWER_TILES] = 1


def _final_adjust(fan_table: List[int]) -> None:
    if fan_table[ALL_TERMINALS]:
        fan_table[ALL_TERMINALS_AND_HONORS] = 0
        fan_table[ALL_HONORS] = 0
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0
    if fan_table[ALL_HONORS]:
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0
    if fan_table[ALL_TERMINALS_AND_HONORS]:
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0
    if fan_table[FULL_FLUSH]:
        fan_table[HALF_FLUSH] = 0
        fan_table[ONE_VOIDED_SUIT] = 0
    if fan_table[HALF_FLUSH]:
        fan_table[ONE_VOIDED_SUIT] = 0
    if fan_table[ALL_PUNGS]:
        fan_table[PUNG_OF_TERMINALS_OR_HONORS] = 0
    if fan_table[SEVEN_PAIRS]:
        fan_table[DOUBLE_PUNG] = 0
    if fan_table[PURE_STRAIGHT]:
        fan_table[SHORT_STRAIGHT] = 0
    if fan_table[PURE_DOUBLE_CHOW]:
        fan_table[MIXED_DOUBLE_CHOW] = 0

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
    win_tile = calculate_param.win_tile

    chow_tiles: List[int] = []
    pung_tiles: List[int] = []
    kong_tiles: List[int] = []
    for i in range(4):
        pack = packs[i]
        pack_type = pack_get_type(pack)
        if pack_type == PACK_TYPE_CHOW:
            chow_tiles.append(pack_get_tile(pack))
        elif pack_type == PACK_TYPE_PUNG:
            pung_tiles.append(pack_get_tile(pack))
        elif pack_type == PACK_TYPE_KONG:
            kong_tiles.append(pack_get_tile(pack))

    chow_cnt = len(chow_tiles)
    pung_cnt = len(pung_tiles) + len(kong_tiles)

    for t in pung_tiles:
        fan = _get_1_pung_fan(t)
        if fan != FAN_NONE:
            fan_table[fan] += 1
    for t in kong_tiles:
        fan = _get_1_pung_fan(t)
        if fan != FAN_NONE:
            fan_table[fan] += 1

    if chow_cnt == 4:
        t0, t1, t2, t3 = sorted(chow_tiles)
        fan = _get_4_chows_fan(t0, t1, t2, t3)
        if fan != FAN_NONE:
            fan_table[fan] = 1
        else:
            if not _calculate_3_of_4_chows(t0, t1, t2, t3, fan_table):
                _calculate_3_of_4_chows(t0, t1, t3, t2, fan_table)
                _calculate_3_of_4_chows(t0, t2, t3, t1, fan_table)
                _calculate_3_of_4_chows(t1, t2, t3, t0, fan_table)
            _calculate_2_of_4_chows(t0, t1, t2, t3, fan_table)
    elif chow_cnt == 3:
        t0, t1, t2 = sorted(chow_tiles)
        fan = _get_3_chows_fan(t0, t1, t2)
        if fan != FAN_NONE:
            fan_table[fan] = 1
        else:
            _calculate_2_of_3_chows(t0, t1, t2, fan_table)
    elif chow_cnt == 2:
        t0, t1 = chow_tiles
        fan = _get_2_chows_fan_unordered(t0, t1)
        if fan != FAN_NONE:
            fan_table[fan] = 1

    if pung_cnt == 4:
        tiles = sorted(pung_tiles + kong_tiles)
        fan = _get_4_pungs_fan(tiles[0], tiles[1], tiles[2], tiles[3])
        if fan != FAN_NONE:
            fan_table[fan] = 1
    elif pung_cnt == 3:
        tiles = sorted(pung_tiles + kong_tiles)
        fan = _get_3_pungs_fan(tiles[0], tiles[1], tiles[2])
        if fan != FAN_NONE:
            fan_table[fan] = 1
        else:
            _calculate_2_of_3_pungs(tiles[0], tiles[1], tiles[2], fan_table)
    elif pung_cnt == 2:
        tiles = sorted(pung_tiles + kong_tiles)
        _calculate_2_of_4_pungs(tiles[0], tiles[1], tiles[0], tiles[1], fan_table)

    if fixed_cnt == 0 and (win_flag & WIN_FLAG_SELF_DRAWN) == 0:
        fan_table[CONCEALED_HAND] = 1
    if fixed_cnt == 4 and (win_flag & WIN_FLAG_SELF_DRAWN):
        fan_table[MELDED_HAND] = 1

    pair_tile = pack_get_tile(packs[4])
    if pair_tile == TILE_C:
        fan_table[LITTLE_THREE_DRAGONS] = 1
    if pair_tile == TILE_E:
        if calculate_param.prevalent_wind == Wind.EAST:
            fan_table[PREVALENT_WIND] = 1
        if calculate_param.seat_wind == Wind.EAST:
            fan_table[SEAT_WIND] = 1
    if pair_tile == TILE_S:
        if calculate_param.prevalent_wind == Wind.SOUTH:
            fan_table[PREVALENT_WIND] = 1
        if calculate_param.seat_wind == Wind.SOUTH:
            fan_table[SEAT_WIND] = 1
    if pair_tile == TILE_W:
        if calculate_param.prevalent_wind == Wind.WEST:
            fan_table[PREVALENT_WIND] = 1
        if calculate_param.seat_wind == Wind.WEST:
            fan_table[SEAT_WIND] = 1
    if pair_tile == TILE_N:
        if calculate_param.prevalent_wind == Wind.NORTH:
            fan_table[PREVALENT_WIND] = 1
        if calculate_param.seat_wind == Wind.NORTH:
            fan_table[SEAT_WIND] = 1

    if _is_all_even_pungs(packs):
        fan_table[ALL_EVEN_PUNGS] = 1

    all_tiles: List[int] = []
    for i in range(4):
        p = packs[i]
        t = pack_get_tile(p)
        pt = pack_get_type(p)
        if pt == PACK_TYPE_CHOW:
            all_tiles.extend([t - 1, t, t + 1])
        elif pt == PACK_TYPE_PUNG:
            all_tiles.extend([t, t, t])
        elif pt == PACK_TYPE_KONG:
            all_tiles.extend([t, t, t, t])
    all_tiles.extend([pair_tile, pair_tile])

    if _is_all_simples(all_tiles):
        fan_table[ALL_SIMPLES] = 1
    if _is_outside_hand(all_tiles):
        fan_table[OUTSIDE_HAND] = 1
    if _is_all_terminals(all_tiles):
        fan_table[ALL_TERMINALS] = 1
    if _is_all_honors(all_tiles):
        fan_table[ALL_HONORS] = 1
    if _is_all_terminals_and_honors(all_tiles):
        fan_table[ALL_TERMINALS_AND_HONORS] = 1

    _adjust_by_suits(unique_tiles, fan_table)
    _adjust_by_tiles_traits(unique_tiles, fan_table)
    _adjust_by_rank_range(unique_tiles, fan_table)
    _adjust_by_tiles_hog(standing_table, fixed_cnt, fan_table)

    concealed_pungs = _count_concealed_pungs(packs, fixed_cnt)
    if concealed_pungs == 4:
        fan_table[FOUR_CONCEALED_PUNGS] = 1
    elif concealed_pungs == 3:
        fan_table[THREE_CONCEALED_PUNGS] = 1
    elif concealed_pungs == 2:
        fan_table[TWO_CONCEALED_PUNGS] = 1

    if _has_kong(packs, fixed_cnt):
        kong_cnt = sum(1 for i in range(fixed_cnt) if pack_get_type(packs[i]) == PACK_TYPE_KONG)
        if kong_cnt == 4:
            fan_table[FOUR_KONGS] = 1
        elif kong_cnt == 3:
            fan_table[THREE_KONGS] = 1
        elif kong_cnt == 2:
            fan_table[TWO_MELDED_KONGS] = 1
        elif kong_cnt == 1:
            fan_table[MELDED_KONG] = 1

    if fixed_cnt == 0:
        fan_table[FULLY_CONCEALED_HAND] = 1

    if unique_waiting:
        _adjust_by_waiting_form(packs[3:], 2, win_tile, fan_table)

    _adjust_by_win_flag(win_flag, fan_table)
    _final_adjust(fan_table)


def _calculate_knitted_straight_fan(
    fixed_table: List[int],
    standing_table: List[int],
    calculate_param: CalculateParam,
    win_flag: int,
    fan_table: List[int],
) -> bool:
    fixed_cnt = calculate_param.hand_tiles.pack_count
    win_tile = calculate_param.win_tile

    matched_seq = None
    for seq in STANDARD_KNITTED_STRAIGHT:
        if all(standing_table[t] for t in seq):
            matched_seq = seq
            break
    if matched_seq is None:
        return False

    packs = [0] * 5
    packs[4] = make_pack(0, PACK_TYPE_PAIR, win_tile)
    remaining = list(standing_table)
    for t in matched_seq:
        remaining[t] -= 1

    idx = 0
    for t in ALL_TILES:
        while remaining[t] >= 3:
            packs[idx] = make_pack(0, PACK_TYPE_PUNG, t)
            remaining[t] -= 3
            idx += 1
        if is_numbered_suit(t) and tile_get_rank(t) < 8:
            while remaining[t] and remaining[t + 1] and remaining[t + 2]:
                packs[idx] = make_pack(0, PACK_TYPE_CHOW, t + 1)
                remaining[t] -= 1
                remaining[t + 1] -= 1
                remaining[t + 2] -= 1
                idx += 1
    if idx != 2:
        return False

    fan_table[KNITTED_STRAIGHT] = 1
    if fixed_cnt == 0:
        fan_table[FULLY_CONCEALED_HAND] = 1
    _adjust_by_win_flag(win_flag, fan_table)

    heavenly = calculate_param.seat_wind == Wind.EAST and fixed_cnt == 0 and (win_flag & (WIN_FLAG_INITIAL | WIN_FLAG_SELF_DRAWN)) == (WIN_FLAG_INITIAL | WIN_FLAG_SELF_DRAWN)
    if fixed_cnt == 0:
        if not heavenly:
            if _is_unique_waiting(standing_table, calculate_param.hand_tiles.tile_count, win_tile):
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
