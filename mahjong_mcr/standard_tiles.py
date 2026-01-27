"""
Port of mahjong-algorithm standard_tiles.h from ChineseOfficialMahjongHelper.
License: MIT (see original project).
"""

from __future__ import annotations

from .tile import (
    TILE_1m, TILE_9m, TILE_1s, TILE_9s, TILE_1p, TILE_9p,
    TILE_E, TILE_S, TILE_W, TILE_N, TILE_C, TILE_F, TILE_P,
    TILE_2m, TILE_5m, TILE_8m, TILE_3m, TILE_6m, TILE_9m as TILE_9m_dup,
    TILE_2s, TILE_5s, TILE_8s, TILE_3s, TILE_6s, TILE_9s as TILE_9s_dup,
    TILE_2p, TILE_5p, TILE_8p, TILE_3p, TILE_6p, TILE_9p as TILE_9p_dup,
    TILE_4m, TILE_7m, TILE_4s, TILE_7s, TILE_4p, TILE_7p,
)


STANDARD_THIRTEEN_ORPHANS = [
    TILE_1m, TILE_9m, TILE_1s, TILE_9s, TILE_1p, TILE_9p,
    TILE_E, TILE_S, TILE_W, TILE_N, TILE_C, TILE_F, TILE_P,
]


STANDARD_KNITTED_STRAIGHT = [
    [TILE_1m, TILE_4m, TILE_7m, TILE_2s, TILE_5s, TILE_8s, TILE_3p, TILE_6p, TILE_9p_dup],
    [TILE_1m, TILE_4m, TILE_7m, TILE_3s, TILE_6s, TILE_9s_dup, TILE_2p, TILE_5p, TILE_8p],
    [TILE_2m, TILE_5m, TILE_8m, TILE_1s, TILE_4s, TILE_7s, TILE_3p, TILE_6p, TILE_9p_dup],
    [TILE_2m, TILE_5m, TILE_8m, TILE_3s, TILE_6s, TILE_9s_dup, TILE_1p, TILE_4p, TILE_7p],
    [TILE_3m, TILE_6m, TILE_9m_dup, TILE_1s, TILE_4s, TILE_7s, TILE_2p, TILE_5p, TILE_8p],
    [TILE_3m, TILE_6m, TILE_9m_dup, TILE_2s, TILE_5s, TILE_8s, TILE_1p, TILE_4p, TILE_7p],
]
