"""
Port of mahjong-algorithm shanten.cpp/h from ChineseOfficialMahjongHelper.
License: MIT (see original project).
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple
import math

from .tile import (
    ALL_TILES,
    HandTiles,
    PACK_TYPE_CHOW,
    PACK_TYPE_KONG,
    PACK_TYPE_PAIR,
    PACK_TYPE_PUNG,
    TILE_TABLE_SIZE,
    is_honor,
    is_numbered_suit,
    is_numbered_suit_quick,
    make_eigen,
    pack_get_tile,
    pack_get_type,
    tile_get_rank,
)
from .standard_tiles import STANDARD_KNITTED_STRAIGHT, STANDARD_THIRTEEN_ORPHANS


def _new_tile_table() -> List[int]:
    return [0] * TILE_TABLE_SIZE


def _new_useful_table() -> List[bool]:
    return [False] * TILE_TABLE_SIZE


def packs_to_tiles(packs: List[int], pack_cnt: int, tile_cnt: int) -> List[int]:
    tiles: List[int] = []
    for i in range(pack_cnt):
        tile = pack_get_tile(packs[i])
        pack_type = pack_get_type(packs[i])
        if pack_type == PACK_TYPE_CHOW:
            tiles.extend([tile - 1, tile, tile + 1])
        elif pack_type == PACK_TYPE_PUNG:
            tiles.extend([tile, tile, tile])
        elif pack_type == PACK_TYPE_KONG:
            tiles.extend([tile, tile, tile, tile])
        elif pack_type == PACK_TYPE_PAIR:
            tiles.extend([tile, tile])
        else:
            raise ValueError("Invalid pack type")
        if len(tiles) >= tile_cnt:
            return tiles[:tile_cnt]
    return tiles[:tile_cnt]


def map_tiles(tiles: List[int]) -> List[int]:
    table = _new_tile_table()
    for t in tiles:
        table[t] += 1
    return table


def map_hand_tiles(hand_tiles: HandTiles) -> Optional[List[int]]:
    if hand_tiles.tile_count <= 0 or hand_tiles.pack_count < 0 or hand_tiles.pack_count > 4:
        return None
    if hand_tiles.pack_count * 3 + hand_tiles.tile_count != 13:
        return None
    if hand_tiles.pack_count == 0:
        return map_tiles(hand_tiles.standing_tiles[:13])
    tiles = packs_to_tiles(hand_tiles.fixed_packs, hand_tiles.pack_count, 18)
    tiles.extend(hand_tiles.standing_tiles[: hand_tiles.tile_count])
    return map_tiles(tiles)


def table_to_tiles(tile_table: List[int], max_cnt: int) -> List[int]:
    tiles: List[int] = []
    for t in ALL_TILES:
        cnt = tile_table[t]
        if cnt:
            tiles.extend([t] * cnt)
            if len(tiles) >= max_cnt:
                return tiles[:max_cnt]
    return tiles


def _regular_shanten_recursively(
    tile_table: List[int],
    has_pair: bool,
    pack_cnt: int,
    partner_cnt: int,
    fixed_cnt: int,
    pack_eigen: int,
    partner_eigen: int,
) -> int:
    if fixed_cnt == 4:
        for t in ALL_TILES:
            if tile_table[t] > 1:
                return -1
        return 0
    if pack_cnt == 4:
        return -1 if has_pair else 0

    partner_need = 4 - pack_cnt - partner_cnt
    if partner_need > 0:
        max_ret = partner_cnt + partner_need * 2 - (1 if has_pair else 0)
    else:
        max_ret = (3 if has_pair else 4) - pack_cnt

    result = max_ret
    if pack_cnt + partner_cnt > 4:
        return max_ret

    for t in ALL_TILES:
        if tile_table[t] < 1:
            continue

        if (not has_pair) and tile_table[t] > 1:
            tile_table[t] -= 2
            ret = _regular_shanten_recursively(tile_table, True, pack_cnt, partner_cnt, fixed_cnt, pack_eigen, partner_eigen)
            result = min(ret, result)
            tile_table[t] += 2

        if tile_table[t] > 2:
            eigen = make_eigen(t, t, t)
            if eigen > pack_eigen:
                tile_table[t] -= 3
                ret = _regular_shanten_recursively(tile_table, has_pair, pack_cnt + 1, partner_cnt, fixed_cnt, eigen, partner_eigen)
                result = min(ret, result)
                tile_table[t] += 3

        if is_numbered_suit(t) and tile_get_rank(t) < 8 and tile_table[t + 1] and tile_table[t + 2]:
            eigen = make_eigen(t, t + 1, t + 2)
            if eigen >= pack_eigen:
                tile_table[t] -= 1
                tile_table[t + 1] -= 1
                tile_table[t + 2] -= 1
                ret = _regular_shanten_recursively(tile_table, has_pair, pack_cnt + 1, partner_cnt, fixed_cnt, eigen, partner_eigen)
                result = min(ret, result)
                tile_table[t] += 1
                tile_table[t + 1] += 1
                tile_table[t + 2] += 1

        if result < max_ret:
            continue

        if tile_table[t] > 1:
            eigen = make_eigen(t, t, 0)
            if eigen > partner_eigen:
                tile_table[t] -= 2
                ret = _regular_shanten_recursively(tile_table, has_pair, pack_cnt, partner_cnt + 1, fixed_cnt, pack_eigen, eigen)
                result = min(ret, result)
                tile_table[t] += 2

        if is_numbered_suit(t):
            if tile_get_rank(t) < 9 and tile_table[t + 1]:
                eigen = make_eigen(t, t + 1, 0)
                if eigen >= partner_eigen:
                    tile_table[t] -= 1
                    tile_table[t + 1] -= 1
                    ret = _regular_shanten_recursively(tile_table, has_pair, pack_cnt, partner_cnt + 1, fixed_cnt, pack_eigen, eigen)
                    result = min(ret, result)
                    tile_table[t] += 1
                    tile_table[t + 1] += 1
            if tile_get_rank(t) < 8 and tile_table[t + 2]:
                eigen = make_eigen(t, t + 2, 0)
                if eigen >= partner_eigen:
                    tile_table[t] -= 1
                    tile_table[t + 2] -= 1
                    ret = _regular_shanten_recursively(tile_table, has_pair, pack_cnt, partner_cnt + 1, fixed_cnt, pack_eigen, eigen)
                    result = min(ret, result)
                    tile_table[t] += 1
                    tile_table[t + 2] += 1

    return result


def _numbered_tile_has_partner(tile_table: List[int], t: int) -> bool:
    r = tile_get_rank(t)
    if r < 9 and tile_table[t + 1]:
        return True
    if r < 8 and tile_table[t + 2]:
        return True
    if r > 1 and tile_table[t - 1]:
        return True
    if r > 2 and tile_table[t - 2]:
        return True
    return False


def _regular_shanten_from_table(tile_table: List[int], fixed_cnt: int, useful_table: Optional[List[bool]]) -> int:
    result = _regular_shanten_recursively(tile_table, False, fixed_cnt, 0, fixed_cnt, 0, 0)

    if useful_table is None:
        return result

    for t in ALL_TILES:
        if tile_table[t] == 4 and result > 0:
            continue
        if tile_table[t] == 0:
            if is_honor(t) or (not _numbered_tile_has_partner(tile_table, t)):
                continue
        tile_table[t] += 1
        temp = _regular_shanten_recursively(tile_table, False, fixed_cnt, 0, fixed_cnt, 0, 0)
        if temp < result:
            useful_table[t] = True
        tile_table[t] -= 1
    return result


def regular_shanten(standing_tiles: List[int], standing_cnt: int, useful_table: Optional[List[bool]] = None) -> int:
    if standing_tiles is None or standing_cnt not in (13, 10, 7, 4, 1):
        return math.inf
    tile_table = map_tiles(standing_tiles[:standing_cnt])
    if useful_table is not None:
        for i in range(TILE_TABLE_SIZE):
            useful_table[i] = False
    return _regular_shanten_from_table(tile_table, (13 - standing_cnt) // 3, useful_table)


def _is_regular_wait_1(tile_table: List[int], waiting_table: Optional[List[bool]]) -> bool:
    for t in ALL_TILES:
        if tile_table[t] != 1:
            continue
        tile_table[t] = 0
        if all(n == 0 for n in tile_table):
            tile_table[t] = 1
            if waiting_table is not None:
                waiting_table[t] = True
            return True
        tile_table[t] = 1
    return False


def _is_regular_wait_2(tile_table: List[int], waiting_table: Optional[List[bool]]) -> bool:
    ret = False
    for t in ALL_TILES:
        if tile_table[t] < 1:
            continue
        if tile_table[t] > 1:
            if waiting_table is not None:
                waiting_table[t] = True
                ret = True
                continue
            return True
        if is_numbered_suit_quick(t):
            r = tile_get_rank(t)
            if r > 1 and tile_table[t - 1]:
                if waiting_table is not None:
                    if r < 9:
                        waiting_table[t + 1] = True
                    if r > 2:
                        waiting_table[t - 2] = True
                    ret = True
                    continue
                return True
            if r > 2 and tile_table[t - 2]:
                if waiting_table is not None:
                    waiting_table[t - 1] = True
                    ret = True
                    continue
                return True
    return ret


def _is_regular_wait_4(tile_table: List[int], waiting_table: Optional[List[bool]]) -> bool:
    ret = False
    for t in ALL_TILES:
        if tile_table[t] < 2:
            continue
        tile_table[t] -= 2
        if _is_regular_wait_2(tile_table, waiting_table):
            ret = True
        tile_table[t] += 2
        if ret and waiting_table is None:
            return True
    return ret


def _is_regular_wait_recursively(tile_table: List[int], left_cnt: int, prev_eigen: int, waiting_table: Optional[List[bool]]) -> bool:
    if left_cnt == 1:
        return _is_regular_wait_1(tile_table, waiting_table)
    ret = False
    if left_cnt == 4:
        ret = _is_regular_wait_4(tile_table, waiting_table)
        if ret and waiting_table is None:
            return True

    for t in ALL_TILES:
        if tile_table[t] < 1:
            continue
        if tile_table[t] > 2:
            eigen = make_eigen(t, t, t)
            if eigen > prev_eigen:
                tile_table[t] -= 3
                if _is_regular_wait_recursively(tile_table, left_cnt - 3, eigen, waiting_table):
                    ret = True
                tile_table[t] += 3
                if ret and waiting_table is None:
                    return True
        if is_numbered_suit(t):
            if tile_get_rank(t) < 8 and tile_table[t + 1] and tile_table[t + 2]:
                eigen = make_eigen(t, t + 1, t + 2)
                if eigen >= prev_eigen:
                    tile_table[t] -= 1
                    tile_table[t + 1] -= 1
                    tile_table[t + 2] -= 1
                    if _is_regular_wait_recursively(tile_table, left_cnt - 3, eigen, waiting_table):
                        ret = True
                    tile_table[t] += 1
                    tile_table[t + 1] += 1
                    tile_table[t + 2] += 1
                    if ret and waiting_table is None:
                        return True
    return ret


def is_regular_wait(standing_tiles: List[int], standing_cnt: int, waiting_table: Optional[List[bool]] = None) -> bool:
    tile_table = map_tiles(standing_tiles[:standing_cnt])
    if waiting_table is not None:
        for i in range(TILE_TABLE_SIZE):
            waiting_table[i] = False
    return _is_regular_wait_recursively(tile_table, standing_cnt, 0, waiting_table)


def _is_regular_win_2(tile_table: List[int]) -> bool:
    tiles = []
    for t in ALL_TILES:
        if tile_table[t] == 1:
            tiles.append(t)
    if len(tiles) != 2:
        return False
    t0, t1 = tiles
    if t0 == t1:
        return True
    if is_numbered_suit(t0):
        r0 = tile_get_rank(t0)
        if t1 == t0 + 1 and r0 < 9:
            return True
        if t1 == t0 + 2 and r0 < 8:
            return True
    return False


def _is_regular_win_recursively(tile_table: List[int], left_cnt: int, prev_eigen: int) -> bool:
    if left_cnt == 2:
        return _is_regular_win_2(tile_table)
    for t in ALL_TILES:
        if tile_table[t] < 1:
            continue
        if tile_table[t] > 2:
            eigen = make_eigen(t, t, t)
            if eigen > prev_eigen:
                tile_table[t] -= 3
                if _is_regular_win_recursively(tile_table, left_cnt - 3, eigen):
                    tile_table[t] += 3
                    return True
                tile_table[t] += 3
        if is_numbered_suit(t):
            if tile_get_rank(t) < 8 and tile_table[t + 1] and tile_table[t + 2]:
                eigen = make_eigen(t, t + 1, t + 2)
                if eigen >= prev_eigen:
                    tile_table[t] -= 1
                    tile_table[t + 1] -= 1
                    tile_table[t + 2] -= 1
                    if _is_regular_win_recursively(tile_table, left_cnt - 3, eigen):
                        tile_table[t] += 1
                        tile_table[t + 1] += 1
                        tile_table[t + 2] += 1
                        return True
                    tile_table[t] += 1
                    tile_table[t + 1] += 1
                    tile_table[t + 2] += 1
    return False


def is_regular_win(standing_tiles: List[int], standing_cnt: int, test_tile: int) -> bool:
    tile_table = map_tiles(standing_tiles[:standing_cnt])
    tile_table[test_tile] += 1
    ret = _is_regular_win_recursively(tile_table, standing_cnt + 1, 0)
    tile_table[test_tile] -= 1
    return ret


def seven_pairs_shanten(standing_tiles: List[int], standing_cnt: int, useful_table: Optional[List[bool]] = None) -> int:
    if standing_tiles is None or standing_cnt != 13:
        return math.inf
    tile_table = map_tiles(standing_tiles[:standing_cnt])
    pair_cnt = 0
    unique_cnt = 0
    for t in ALL_TILES:
        if tile_table[t]:
            unique_cnt += 1
            if tile_table[t] >= 2:
                pair_cnt += 1
    ret = 6 - pair_cnt + max(0, 7 - unique_cnt)
    if useful_table is not None:
        for i in range(TILE_TABLE_SIZE):
            useful_table[i] = False
        for t in ALL_TILES:
            if tile_table[t] == 0:
                useful_table[t] = True
            elif tile_table[t] == 1 and unique_cnt < 7:
                useful_table[t] = True
            elif tile_table[t] == 1 and pair_cnt < 7:
                useful_table[t] = True
    return ret


def is_seven_pairs_wait(standing_tiles: List[int], standing_cnt: int, waiting_table: Optional[List[bool]] = None) -> bool:
    if waiting_table is None:
        return seven_pairs_shanten(standing_tiles, standing_cnt, None) == 0
    useful = _new_useful_table()
    if seven_pairs_shanten(standing_tiles, standing_cnt, useful) == 0:
        for i in range(TILE_TABLE_SIZE):
            waiting_table[i] = useful[i]
        return True
    return False


def is_seven_pairs_win(standing_tiles: List[int], standing_cnt: int, test_tile: int) -> bool:
    useful = _new_useful_table()
    return seven_pairs_shanten(standing_tiles, standing_cnt, useful) == 0 and useful[test_tile]


def thirteen_orphans_shanten(standing_tiles: List[int], standing_cnt: int, useful_table: Optional[List[bool]] = None) -> int:
    if standing_tiles is None or standing_cnt != 13:
        return math.inf
    tile_table = map_tiles(standing_tiles[:standing_cnt])
    has_pair = False
    cnt = 0
    for t in STANDARD_THIRTEEN_ORPHANS:
        n = tile_table[t]
        if n > 0:
            cnt += 1
            if n > 1:
                has_pair = True
    ret = 12 - cnt if has_pair else 13 - cnt
    if useful_table is not None:
        for i in range(TILE_TABLE_SIZE):
            useful_table[i] = False
        for t in STANDARD_THIRTEEN_ORPHANS:
            useful_table[t] = True
        if has_pair:
            for t in STANDARD_THIRTEEN_ORPHANS:
                if tile_table[t] > 0:
                    useful_table[t] = False
    return ret


def is_thirteen_orphans_wait(standing_tiles: List[int], standing_cnt: int, waiting_table: Optional[List[bool]] = None) -> bool:
    if waiting_table is None:
        return thirteen_orphans_shanten(standing_tiles, standing_cnt, None) == 0
    useful = _new_useful_table()
    if thirteen_orphans_shanten(standing_tiles, standing_cnt, useful) == 0:
        for i in range(TILE_TABLE_SIZE):
            waiting_table[i] = useful[i]
        return True
    return False


def is_thirteen_orphans_win(standing_tiles: List[int], standing_cnt: int, test_tile: int) -> bool:
    useful = _new_useful_table()
    return thirteen_orphans_shanten(standing_tiles, standing_cnt, useful) == 0 and useful[test_tile]


def _is_knitted_straight_wait_from_table(tile_table: List[int], left_cnt: int, waiting_table: Optional[List[bool]]) -> bool:
    matched_seq = None
    missing_tiles: List[int] = []
    missing_cnt = 0
    for seq in STANDARD_KNITTED_STRAIGHT:
        missing_tiles = []
        for t in seq:
            if tile_table[t] == 0:
                missing_tiles.append(t)
        missing_cnt = len(missing_tiles)
        if missing_cnt < 2:
            matched_seq = seq
            break
    if matched_seq is None or missing_cnt > 2:
        return False
    if waiting_table is not None:
        for i in range(TILE_TABLE_SIZE):
            waiting_table[i] = False
    temp_table = list(tile_table)
    for t in matched_seq:
        if temp_table[t]:
            temp_table[t] -= 1
    if missing_cnt == 1:
        if left_cnt == 10:
            if _is_regular_win_recursively(temp_table, 2, 0):
                if waiting_table is not None:
                    waiting_table[missing_tiles[0]] = True
                return True
        else:
            if _is_regular_win_recursively(temp_table, 5, 0):
                if waiting_table is not None:
                    waiting_table[missing_tiles[0]] = True
                return True
    elif missing_cnt == 0:
        if left_cnt == 10:
            return _is_regular_wait_1(temp_table, waiting_table)
        return _is_regular_wait_recursively(temp_table, 4, 0, waiting_table)
    return False


def knitted_straight_shanten(standing_tiles: List[int], standing_cnt: int, useful_table: Optional[List[bool]] = None) -> int:
    if standing_tiles is None or standing_cnt not in (13, 10):
        return math.inf
    tile_table = map_tiles(standing_tiles[:standing_cnt])
    ret = math.inf
    if useful_table is not None:
        for i in range(TILE_TABLE_SIZE):
            useful_table[i] = False
        temp_table = _new_useful_table()
        for seq in STANDARD_KNITTED_STRAIGHT:
            fixed_cnt = (13 - standing_cnt) // 3
            st = _regular_shanten_specified(tile_table, seq, 9, fixed_cnt, temp_table)
            if st < ret:
                ret = st
                for i in range(TILE_TABLE_SIZE):
                    useful_table[i] = temp_table[i]
            elif st == ret:
                for i in range(TILE_TABLE_SIZE):
                    useful_table[i] = useful_table[i] or temp_table[i]
    else:
        for seq in STANDARD_KNITTED_STRAIGHT:
            fixed_cnt = (13 - standing_cnt) // 3
            st = _regular_shanten_specified(tile_table, seq, 9, fixed_cnt, None)
            if st < ret:
                ret = st
    return ret


def is_knitted_straight_wait(standing_tiles: List[int], standing_cnt: int, waiting_table: Optional[List[bool]] = None) -> bool:
    if standing_tiles is None or standing_cnt not in (13, 10):
        return False
    tile_table = map_tiles(standing_tiles[:standing_cnt])
    return _is_knitted_straight_wait_from_table(tile_table, standing_cnt, waiting_table)


def is_knitted_straight_win(standing_tiles: List[int], standing_cnt: int, test_tile: int) -> bool:
    waiting = _new_useful_table()
    return is_knitted_straight_wait(standing_tiles, standing_cnt, waiting) and waiting[test_tile]


def _regular_shanten_specified(
    tile_table: List[int],
    main_tiles: List[int],
    main_cnt: int,
    fixed_cnt: int,
    useful_table: Optional[List[bool]],
) -> int:
    temp_table = list(tile_table)
    exist_cnt = 0
    for i in range(main_cnt):
        t = main_tiles[i]
        if tile_table[t] > 0:
            exist_cnt += 1
            temp_table[t] -= 1
    if useful_table is not None:
        for i in range(TILE_TABLE_SIZE):
            useful_table[i] = False
        for i in range(main_cnt):
            t = main_tiles[i]
            if tile_table[t] <= 0:
                useful_table[t] = True
    result = _regular_shanten_from_table(temp_table, fixed_cnt + main_cnt // 3, useful_table)
    return (main_cnt - exist_cnt) + result


def _honors_and_knitted_tiles_shanten_1(
    standing_tiles: List[int],
    standing_cnt: int,
    which_seq: int,
    useful_table: Optional[List[bool]],
) -> int:
    if standing_tiles is None or standing_cnt != 13:
        return math.inf
    tile_table = map_tiles(standing_tiles[:standing_cnt])
    cnt = 0
    seq = STANDARD_KNITTED_STRAIGHT[which_seq]
    for t in seq:
        if tile_table[t] > 0:
            cnt += 1
    for t in STANDARD_THIRTEEN_ORPHANS[6:]:
        if tile_table[t] > 0:
            cnt += 1
    if useful_table is not None:
        for i in range(TILE_TABLE_SIZE):
            useful_table[i] = False
        for t in seq:
            if tile_table[t] <= 0:
                useful_table[t] = True
        for t in STANDARD_THIRTEEN_ORPHANS[6:]:
            if tile_table[t] <= 0:
                useful_table[t] = True
    return 13 - cnt


def honors_and_knitted_tiles_shanten(
    standing_tiles: List[int],
    standing_cnt: int,
    useful_table: Optional[List[bool]] = None,
) -> int:
    ret = math.inf
    if useful_table is not None:
        for i in range(TILE_TABLE_SIZE):
            useful_table[i] = False
        temp_table = _new_useful_table()
        for i in range(6):
            st = _honors_and_knitted_tiles_shanten_1(standing_tiles, standing_cnt, i, temp_table)
            if st < ret:
                ret = st
                for k in range(TILE_TABLE_SIZE):
                    useful_table[k] = temp_table[k]
            elif st == ret:
                for k in range(TILE_TABLE_SIZE):
                    useful_table[k] = useful_table[k] or temp_table[k]
    else:
        for i in range(6):
            st = _honors_and_knitted_tiles_shanten_1(standing_tiles, standing_cnt, i, None)
            if st < ret:
                ret = st
    return ret


def is_honors_and_knitted_tiles_wait(standing_tiles: List[int], standing_cnt: int, waiting_table: Optional[List[bool]] = None) -> bool:
    if waiting_table is None:
        return honors_and_knitted_tiles_shanten(standing_tiles, standing_cnt, None) == 0
    useful = _new_useful_table()
    if honors_and_knitted_tiles_shanten(standing_tiles, standing_cnt, useful) == 0:
        for i in range(TILE_TABLE_SIZE):
            waiting_table[i] = useful[i]
        return True
    return False


def is_honors_and_knitted_tiles_win(standing_tiles: List[int], standing_cnt: int, test_tile: int) -> bool:
    useful = _new_useful_table()
    if honors_and_knitted_tiles_shanten(standing_tiles, standing_cnt, useful) == 0:
        return useful[test_tile]
    return False


def is_waiting(hand_tiles: HandTiles, useful_table: Optional[List[bool]] = None) -> bool:
    special_waiting = False
    basic_waiting = False
    table_special = _new_useful_table()
    table_basic = _new_useful_table()

    if hand_tiles.tile_count == 13:
        if is_thirteen_orphans_wait(hand_tiles.standing_tiles, 13, table_special):
            special_waiting = True
        elif is_honors_and_knitted_tiles_wait(hand_tiles.standing_tiles, 13, table_special):
            special_waiting = True
        elif is_seven_pairs_wait(hand_tiles.standing_tiles, 13, table_special):
            special_waiting = True
        elif is_knitted_straight_wait(hand_tiles.standing_tiles, 13, table_special):
            special_waiting = True
    elif hand_tiles.tile_count == 10:
        if is_knitted_straight_wait(hand_tiles.standing_tiles, 10, table_special):
            special_waiting = True

    if is_regular_wait(hand_tiles.standing_tiles, hand_tiles.tile_count, table_basic):
        basic_waiting = True

    if useful_table is not None:
        if special_waiting and basic_waiting:
            for i in range(TILE_TABLE_SIZE):
                useful_table[i] = table_special[i] or table_basic[i]
        elif basic_waiting:
            for i in range(TILE_TABLE_SIZE):
                useful_table[i] = table_basic[i]
        elif special_waiting:
            for i in range(TILE_TABLE_SIZE):
                useful_table[i] = table_special[i]
        else:
            for i in range(TILE_TABLE_SIZE):
                useful_table[i] = False
    return special_waiting or basic_waiting


FORM_FLAG_REGULAR = 0x01
FORM_FLAG_SEVEN_PAIRS = 0x02
FORM_FLAG_THIRTEEN_ORPHANS = 0x04
FORM_FLAG_HONORS_AND_KNITTED_TILES = 0x08
FORM_FLAG_KNITTED_STRAIGHT = 0x10
FORM_FLAG_ALL = 0xFF


class EnumResult:
    def __init__(self, discard_tile: int, form_flag: int, shanten: int, useful_table: List[bool]):
        self.discard_tile = discard_tile
        self.form_flag = form_flag
        self.shanten = shanten
        self.useful_table = useful_table


EnumCallback = Callable[[object, EnumResult], bool]


def _enum_discard_tile_1(hand_tiles: HandTiles, discard_tile: int, form_flag: int, context: object, enum_callback: EnumCallback) -> bool:
    useful = _new_useful_table()
    result = EnumResult(discard_tile, FORM_FLAG_REGULAR, regular_shanten(hand_tiles.standing_tiles, hand_tiles.tile_count, useful), useful)
    if result.shanten == 0 and result.useful_table[discard_tile]:
        result.shanten = -1
    if not enum_callback(context, result):
        return False

    if hand_tiles.tile_count == 13:
        if form_flag | FORM_FLAG_SEVEN_PAIRS:
            useful = _new_useful_table()
            result = EnumResult(discard_tile, FORM_FLAG_SEVEN_PAIRS, seven_pairs_shanten(hand_tiles.standing_tiles, hand_tiles.tile_count, useful), useful)
            if result.shanten == 0 and result.useful_table[discard_tile]:
                result.shanten = -1
            if not enum_callback(context, result):
                return False
        if form_flag | FORM_FLAG_THIRTEEN_ORPHANS:
            useful = _new_useful_table()
            result = EnumResult(discard_tile, FORM_FLAG_THIRTEEN_ORPHANS, thirteen_orphans_shanten(hand_tiles.standing_tiles, hand_tiles.tile_count, useful), useful)
            if result.shanten == 0 and result.useful_table[discard_tile]:
                result.shanten = -1
            if not enum_callback(context, result):
                return False
        if form_flag | FORM_FLAG_HONORS_AND_KNITTED_TILES:
            useful = _new_useful_table()
            result = EnumResult(discard_tile, FORM_FLAG_HONORS_AND_KNITTED_TILES, honors_and_knitted_tiles_shanten(hand_tiles.standing_tiles, hand_tiles.tile_count, useful), useful)
            if result.shanten == 0 and result.useful_table[discard_tile]:
                result.shanten = -1
            if not enum_callback(context, result):
                return False

    if hand_tiles.tile_count in (13, 10):
        if form_flag | FORM_FLAG_KNITTED_STRAIGHT:
            useful = _new_useful_table()
            result = EnumResult(discard_tile, FORM_FLAG_KNITTED_STRAIGHT, knitted_straight_shanten(hand_tiles.standing_tiles, hand_tiles.tile_count, useful), useful)
            if result.shanten == 0 and result.useful_table[discard_tile]:
                result.shanten = -1
            if not enum_callback(context, result):
                return False

    return True


def enum_discard_tile(hand_tiles: HandTiles, serving_tile: int, form_flag: int, context: object, enum_callback: EnumCallback) -> None:
    if not _enum_discard_tile_1(hand_tiles, serving_tile, form_flag, context, enum_callback):
        return
    if serving_tile == 0:
        return
    tile_table = map_tiles(hand_tiles.standing_tiles[: hand_tiles.tile_count])
    temp = HandTiles(list(hand_tiles.fixed_packs), hand_tiles.pack_count, list(hand_tiles.standing_tiles), hand_tiles.tile_count)
    for t in ALL_TILES:
        if tile_table[t] and t != serving_tile and tile_table[serving_tile] < 4:
            tile_table[t] -= 1
            tile_table[serving_tile] += 1
            temp.standing_tiles = table_to_tiles(tile_table, temp.tile_count)
            if not _enum_discard_tile_1(temp, t, form_flag, context, enum_callback):
                return
            tile_table[serving_tile] -= 1
            tile_table[t] += 1
