"""
Port of mahjong-algorithm/stringify.cpp for parsing hand strings.
"""

from __future__ import annotations

from typing import List, Tuple

from .tile import (
    HandTiles,
    PACK_TYPE_CHOW,
    PACK_TYPE_KONG,
    PACK_TYPE_PUNG,
    TILE_E,
    TILE_TABLE_SIZE,
    is_honor,
    make_pack,
)

PARSE_NO_ERROR = 0
PARSE_ERROR_ILLEGAL_CHARACTER = -1
PARSE_ERROR_SUFFIX = -2
PARSE_ERROR_WRONG_TILES_COUNT_FOR_FIXED_PACK = -3
PARSE_ERROR_CANNOT_MAKE_FIXED_PACK = -4
PARSE_ERROR_TOO_MANY_FIXED_PACKS = -5
PARSE_ERROR_TOO_MANY_TILES = -6
PARSE_ERROR_TILE_COUNT_GREATER_THAN_4 = -7

_DIGIT_CHARS = "123456789"
_SUFFIX_CHARS = "msp"
_HONOR_CHARS = "ESWNCFP"


def _submit_suit(digit_tiles: List[int], suit: int, tiles: List[int], offset: int) -> None:
    for i, d in enumerate(digit_tiles):
        tiles[offset + i] = d | suit


def parse_tiles(text: str) -> Tuple[int, List[int]]:
    digit_tiles: List[int] = []
    tiles: List[int] = [0] * 14
    cnt = 0

    for c in text:
        if c in _DIGIT_CHARS:
            if cnt + len(digit_tiles) < 14:
                digit_tiles.append(ord(c) - ord("0"))
            continue
        if c in _SUFFIX_CHARS:
            if not digit_tiles:
                return (PARSE_ERROR_SUFFIX, [])
            suit = (_SUFFIX_CHARS.index(c) + 1) << 4
            _submit_suit(digit_tiles, suit, tiles, cnt)
            cnt += len(digit_tiles)
            digit_tiles = []
            continue
        if c in _HONOR_CHARS:
            if digit_tiles:
                return (PARSE_ERROR_SUFFIX, [])
            if cnt < 14:
                tiles[cnt] = TILE_E + _HONOR_CHARS.index(c)
                cnt += 1
            continue
        break

    return (cnt, tiles[:cnt])


def _make_fixed_pack(tiles: List[int], offer: int) -> Tuple[int, int]:
    tile_cnt = len(tiles)
    if tile_cnt == 0:
        return (0, 0)
    if tile_cnt not in (3, 4):
        return (PARSE_ERROR_WRONG_TILES_COUNT_FOR_FIXED_PACK, 0)
    if tile_cnt == 3:
        if offer == 0:
            offer = 1
        if tiles[0] == tiles[1] == tiles[2]:
            return (1, make_pack(offer, PACK_TYPE_PUNG, tiles[0]))
        if not is_honor(tiles[0]):
            sorted_tiles = sorted(tiles)
            if sorted_tiles[0] + 1 == sorted_tiles[1] and sorted_tiles[1] + 1 == sorted_tiles[2]:
                return (1, make_pack(offer, PACK_TYPE_CHOW, sorted_tiles[1]))
        return (PARSE_ERROR_CANNOT_MAKE_FIXED_PACK, 0)
    if tiles[0] != tiles[1] or tiles[1] != tiles[2] or tiles[2] != tiles[3]:
        return (PARSE_ERROR_CANNOT_MAKE_FIXED_PACK, 0)
    return (1, make_pack(offer, PACK_TYPE_KONG, tiles[0]))


def string_to_tiles(text: str) -> Tuple[int, HandTiles, int]:
    allowed = set("123456789mspESWNCFP[]")
    for c in text:
        if c not in allowed:
            return (PARSE_ERROR_ILLEGAL_CHARACTER, HandTiles([], 0, [], 0), 0)

    packs: List[int] = []
    pack_cnt = 0
    standing_tiles: List[int] = []
    standing_cnt = 0

    in_brackets = False
    digit_tiles: List[int] = []
    temp_tiles: List[int] = []
    max_cnt = 14

    tile_table = [0] * TILE_TABLE_SIZE

    for c in text:
        if c in _DIGIT_CHARS:
            if len(digit_tiles) < max_cnt:
                digit_tiles.append(ord(c) - ord("0"))
            continue

        if c in _SUFFIX_CHARS:
            if not digit_tiles:
                return (PARSE_ERROR_SUFFIX, HandTiles([], 0, [], 0), 0)
            if len(temp_tiles) + len(digit_tiles) > max_cnt:
                return (PARSE_ERROR_TOO_MANY_TILES, HandTiles([], 0, [], 0), 0)
            suit = (_SUFFIX_CHARS.index(c) + 1) << 4
            start = len(temp_tiles)
            temp_tiles.extend([0] * len(digit_tiles))
            _submit_suit(digit_tiles, suit, temp_tiles, start)
            digit_tiles = []
            continue

        if c in _HONOR_CHARS:
            if digit_tiles:
                return (PARSE_ERROR_SUFFIX, HandTiles([], 0, [], 0), 0)
            if len(temp_tiles) < max_cnt:
                temp_tiles.append(TILE_E + _HONOR_CHARS.index(c))
            continue

        if c == "[":
            if in_brackets:
                return (PARSE_ERROR_ILLEGAL_CHARACTER, HandTiles([], 0, [], 0), 0)
            if pack_cnt > 4:
                return (PARSE_ERROR_TOO_MANY_FIXED_PACKS, HandTiles([], 0, [], 0), 0)
            if digit_tiles:
                return (PARSE_ERROR_SUFFIX, HandTiles([], 0, [], 0), 0)
            if temp_tiles:
                if standing_cnt + len(temp_tiles) >= max_cnt:
                    return (PARSE_ERROR_TOO_MANY_TILES, HandTiles([], 0, [], 0), 0)
                for t in temp_tiles:
                    tile_table[t] += 1
                standing_tiles.extend(temp_tiles)
                standing_cnt += len(temp_tiles)
                temp_tiles = []
            in_brackets = True
            max_cnt = 5
            continue

        if c == "]":
            if not in_brackets:
                return (PARSE_ERROR_ILLEGAL_CHARACTER, HandTiles([], 0, [], 0), 0)
            if not temp_tiles:
                return (PARSE_ERROR_WRONG_TILES_COUNT_FOR_FIXED_PACK, HandTiles([], 0, [], 0), 0)

            offer = 0
            if len(digit_tiles) == 1:
                offer = digit_tiles[0]
                if offer == 4 or (offer & 0xF0):
                    offer = 0
                digit_tiles = []
            if digit_tiles:
                return (PARSE_ERROR_SUFFIX, HandTiles([], 0, [], 0), 0)

            for t in temp_tiles:
                tile_table[t] += 1

            ret, pack = _make_fixed_pack(temp_tiles, offer)
            if ret < 0:
                return (ret, HandTiles([], 0, [], 0), 0)

            packs.append(pack)
            pack_cnt += 1
            temp_tiles = []
            in_brackets = False
            max_cnt = 14 - standing_cnt - pack_cnt * 3
            continue

        return (PARSE_ERROR_ILLEGAL_CHARACTER, HandTiles([], 0, [], 0), 0)

    max_cnt = 14 - pack_cnt * 3
    if temp_tiles:
        if standing_cnt + len(temp_tiles) > max_cnt:
            return (PARSE_ERROR_TOO_MANY_TILES, HandTiles([], 0, [], 0), 0)
        for t in temp_tiles:
            tile_table[t] += 1
        standing_tiles.extend(temp_tiles)
        standing_cnt += len(temp_tiles)

    if standing_cnt > max_cnt:
        return (PARSE_ERROR_TOO_MANY_TILES, HandTiles([], 0, [], 0), 0)

    if any(cnt > 4 for cnt in tile_table):
        return (PARSE_ERROR_TILE_COUNT_GREATER_THAN_4, HandTiles([], 0, [], 0), 0)

    serving_tile = 0
    if standing_cnt == max_cnt:
        hand_standing = standing_tiles[: max_cnt - 1]
        serving_tile = standing_tiles[max_cnt - 1]
        hand_tiles = HandTiles(list(packs), pack_cnt, hand_standing, max_cnt - 1)
    else:
        hand_tiles = HandTiles(list(packs), pack_cnt, list(standing_tiles), standing_cnt)

    return (PARSE_NO_ERROR, hand_tiles, serving_tile)
