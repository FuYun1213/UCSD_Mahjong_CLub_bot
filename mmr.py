import itertools
import math


PARAMS = {
    "uma_by_rank": [30, 10, -10, -30],
    "riichi_start": 25000,
    "riichi_div": 1000,
    "w_uma": 1.0,
    "w_offset": 0.4,
    "perf_pos_scale": 0.85,
    "perf_neg_scale": 1.15,
    "center_perf": True,
    "mmr_scale": 400.0,
    "beta_mmr": 1.0,
    "k": 0.75,
    "enable_asym_k": True,
    "k_gamma": 0.3,
    "k_scale_cap": 0.5,
}


def tie_groups_desc(values):
    indexes = sorted(range(len(values)), key=lambda index: values[index], reverse=True)
    groups = []
    current = [indexes[0]]
    for index in indexes[1:]:
        if values[index] == values[current[-1]]:
            current.append(index)
        else:
            groups.append(current)
            current = [index]
    groups.append(current)
    return groups


def avg_ranks(start_rank, size, seq_by_rank):
    return sum(seq_by_rank[start_rank - 1 : start_rank - 1 + size]) / size


def clamp(value, low, high):
    return max(low, min(high, value))


def strengths_from_mmr(mmrs, params):
    mean = sum(mmrs) / len(mmrs)
    return [math.exp(params["beta_mmr"] * (rating - mean) / params["mmr_scale"]) for rating in mmrs]


def pl_rank_probs(strengths):
    probs = [[0.0 for _ in range(4)] for _ in range(4)]
    for perm in itertools.permutations(range(4)):
        remaining = list(range(4))
        probability = 1.0
        for index in perm:
            denom = sum(strengths[player] for player in remaining)
            probability *= strengths[index] / denom
            remaining.remove(index)
        for rank, index in enumerate(perm):
            probs[index][rank] += probability
    return probs


def compute_one_table(points, mmrs, params=None):
    params = params or PARAMS
    points = [float(point or 0) for point in points]
    mmrs = [float(mmr or 1500) for mmr in mmrs]

    uma_obs = [0.0, 0.0, 0.0, 0.0]
    next_rank = 1
    for group in tie_groups_desc(points):
        avg_uma = avg_ranks(next_rank, len(group), params["uma_by_rank"])
        for index in group:
            uma_obs[index] = avg_uma
        next_rank += len(group)

    offsets = [(point - params["riichi_start"]) / params["riichi_div"] for point in points]
    strengths = strengths_from_mmr(mmrs, params)
    rank_probs = pl_rank_probs(strengths)
    expected_uma = [
        sum(probability * params["uma_by_rank"][rank] for rank, probability in enumerate(player_probs))
        for player_probs in rank_probs
    ]

    perf_raw = [
        params["w_uma"] * (uma_obs[index] - expected_uma[index]) + params["w_offset"] * offsets[index]
        for index in range(4)
    ]
    perf_shaped = [
        value * (params["perf_pos_scale"] if value >= 0 else params["perf_neg_scale"])
        for value in perf_raw
    ]
    mean_perf = sum(perf_shaped) / len(perf_shaped) if params["center_perf"] else 0.0
    perf = [value - mean_perf for value in perf_shaped]

    deltas = []
    for index, value in enumerate(perf):
        rating = mmrs[index]
        opponent_mean = (sum(mmrs) - rating) / 3.0
        gap = (opponent_mean - rating) / params["mmr_scale"]
        sign = 1.0 if value > 0 else (-1.0 if value < 0 else 0.0)
        k_scale = 1.0
        if params["enable_asym_k"] and sign != 0:
            k_scale = 1.0 + params["k_gamma"] * gap * sign
        deltas.append(
            params["k"]
            * clamp(k_scale, 1.0 - params["k_scale_cap"], 1.0 + params["k_scale_cap"])
            * value
        )

    return {
        "deltas": deltas,
        "new_mmr": [rating + deltas[index] for index, rating in enumerate(mmrs)],
    }
