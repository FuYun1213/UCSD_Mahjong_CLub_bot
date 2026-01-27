"""
Port of mahjong-algorithm tile.h from ChineseOfficialMahjongHelper.
License: MIT (see original project).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


TILE_SUIT_NONE = 0
TILE_SUIT_CHARACTERS = 1  # m
TILE_SUIT_BAMBOO = 2      # s
TILE_SUIT_DOTS = 3        # p
TILE_SUIT_HONORS = 4


def make_tile(suit: int, rank: int) -> int:
    return ((suit & 0xF) << 4) | (rank & 0xF)


def tile_get_suit(tile: int) -> int:
    return (tile >> 4) & 0xF


def tile_get_rank(tile: int) -> int:
    return tile & 0xF


def is_flower(tile: int) -> bool:
    return ((tile >> 4) & 0xF) == 5


TILE_1m = 0x11
TILE_2m = 0x12
TILE_3m = 0x13
TILE_4m = 0x14
TILE_5m = 0x15
TILE_6m = 0x16
TILE_7m = 0x17
TILE_8m = 0x18
TILE_9m = 0x19

TILE_1s = 0x21
TILE_2s = 0x22
TILE_3s = 0x23
TILE_4s = 0x24
TILE_5s = 0x25
TILE_6s = 0x26
TILE_7s = 0x27
TILE_8s = 0x28
TILE_9s = 0x29

TILE_1p = 0x31
TILE_2p = 0x32
TILE_3p = 0x33
TILE_4p = 0x34
TILE_5p = 0x35
TILE_6p = 0x36
TILE_7p = 0x37
TILE_8p = 0x38
TILE_9p = 0x39

TILE_E = 0x41
TILE_S = 0x42
TILE_W = 0x43
TILE_N = 0x44
TILE_C = 0x45
TILE_F = 0x46
TILE_P = 0x47

TILE_TABLE_SIZE = 0x48

ALL_TILES: List[int] = [
    TILE_1m, TILE_2m, TILE_3m, TILE_4m, TILE_5m, TILE_6m, TILE_7m, TILE_8m, TILE_9m,
    TILE_1s, TILE_2s, TILE_3s, TILE_4s, TILE_5s, TILE_6s, TILE_7s, TILE_8s, TILE_9s,
    TILE_1p, TILE_2p, TILE_3p, TILE_4p, TILE_5p, TILE_6p, TILE_7p, TILE_8p, TILE_9p,
    TILE_E, TILE_S, TILE_W, TILE_N, TILE_C, TILE_F, TILE_P,
]


def make_eigen(t1: int, t2: int, t3: int) -> int:
    return ((t1 & 0xFF) << 16) | ((t2 & 0xFF) << 8) | (t3 & 0xFF)


def is_green(tile: int) -> bool:
    return bool(0x0020000000AE0000 & (1 << (tile - TILE_1m)))


def is_reversible(tile: int) -> bool:
    return bool(0x0040019F01BA0000 & (1 << (tile - TILE_1m)))


def is_terminal(tile: int) -> bool:
    return (tile & 0xC7) == 1


def is_winds(tile: int) -> bool:
    return 0x40 < tile < 0x45


def is_dragons(tile: int) -> bool:
    return 0x44 < tile < 0x48


def is_honor(tile: int) -> bool:
    return 0x40 < tile < 0x48


def is_numbered_suit(tile: int) -> bool:
    if tile < 0x1A:
        return tile > 0x10
    if tile < 0x2A:
        return tile > 0x20
    if tile < 0x3A:
        return tile > 0x30
    return False


def is_numbered_suit_quick(tile: int) -> bool:
    return (tile & 0xC0) == 0


def is_terminal_or_honor(tile: int) -> bool:
    return is_terminal(tile) or is_honor(tile)


def is_suit_equal_quick(tile0: int, tile1: int) -> bool:
    return (tile0 & 0xF0) == (tile1 & 0xF0)


def is_rank_equal_quick(tile0: int, tile1: int) -> bool:
    return (tile0 & 0xCF) == (tile1 & 0xCF)


PACK_TYPE_NONE = 0
PACK_TYPE_CHOW = 1
PACK_TYPE_PUNG = 2
PACK_TYPE_KONG = 3
PACK_TYPE_PAIR = 4


def make_pack(offer: int, pack_type: int, tile: int) -> int:
    return ((offer & 0x3) << 12) | ((pack_type & 0xF) << 8) | (tile & 0xFF)


def is_pack_melded(pack: int) -> bool:
    return bool(pack & 0x3000)


def is_promoted_kong(pack: int) -> bool:
    return bool(pack & 0x4000)


def promote_pung_to_kong(pack: int) -> int:
    return pack | 0x4300


def pack_get_offer(pack: int) -> int:
    return (pack >> 12) & 0x3


def pack_get_type(pack: int) -> int:
    return (pack >> 8) & 0xF


def pack_get_tile(pack: int) -> int:
    return pack & 0xFF


@dataclass
class HandTiles:
    fixed_packs: List[int]
    pack_count: int
    standing_tiles: List[int]
    tile_count: int


def tile_to_string(tile: int) -> str:
    suit = tile_get_suit(tile)
    rank = tile_get_rank(tile)
    if suit == TILE_SUIT_CHARACTERS:
        return f"{rank}m"
    if suit == TILE_SUIT_BAMBOO:
        return f"{rank}s"
    if suit == TILE_SUIT_DOTS:
        return f"{rank}p"
    if suit == TILE_SUIT_HONORS:
        return {TILE_E: "E", TILE_S: "S", TILE_W: "W", TILE_N: "N", TILE_C: "C", TILE_F: "F", TILE_P: "P"}[tile]
    return "?"


def string_to_tile(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if len(token) == 1:
        return {"E": TILE_E, "S": TILE_S, "W": TILE_W, "N": TILE_N, "C": TILE_C, "F": TILE_F, "P": TILE_P}.get(token)
    if len(token) == 2 and token[0].isdigit():
        rank = int(token[0])
        suit = token[1].lower()
        if suit == "m":
            return make_tile(TILE_SUIT_CHARACTERS, rank)
        if suit == "s":
            return make_tile(TILE_SUIT_BAMBOO, rank)
        if suit == "p":
            return make_tile(TILE_SUIT_DOTS, rank)
    return None
