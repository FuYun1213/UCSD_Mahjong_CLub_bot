"""Pure tournament calculations, independent from ordinary club scoring."""
import copy
import itertools
import random
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from .store import Conflict, now

DEFAULT_NAMES = {"1": "橘色八口机2025", "2": "白色四口机2024"}
DEFAULT_SETTINGS = {"table_size": 4, "uma": [30, 10, -10, -30], "base_points": 25000,
    "bye_score": 0,
    "pairing": "swiss", "qualifying_rank": 4, "advance_on_tie": False,
    "return_point": 25000, "scoring_mode": "return", "time_limit_seconds": None,
    "allow_guest_auto_enrollment": False}

PLACEMENT_MODE = "placement_and_game_count"
PLACEMENT_FIELDS = ("first_placement_game_score", "second_placement_game_score",
                    "third_placement_game_score", "fourth_placement_game_score", "game_participation_score")


# Engine defaults, not per-tournament settings. Legacy snapshots still retain
# their original values; confirmed results are never recalculated by migration.
SCORING_DEFAULTS = {"divisor": 1000, "raw_step": 100, "min_unit": 0.1}


def scoring_value(settings, key):
    return settings.get(key, SCORING_DEFAULTS[key])


def require(condition, code):
    if not condition:
        raise Conflict(code, code)


def normalized_name(name):
    return " ".join(unicodedata.normalize("NFKC", str(name)).split())


def name_key(name):
    return normalized_name(name).casefold()


def number(value):
    try:
        require(not isinstance(value, bool) and value is not None and str(value).strip() != "", "invalid_number")
        result = Decimal(str(value))
        require(result.is_finite() and abs(result) <= 1000000000, "invalid_number")
        return result
    except (ValueError, ArithmeticError):
        raise Conflict("invalid_number", "invalid_number") from None


def rounded(value, settings):
    unit = number(scoring_value(settings, "min_unit"))
    return float((number(value) / unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * unit)


def settings_value(data, previous=None):
    # Older clients may still send retired fields: ignore them. Preserve only
    # existing legacy values for compatibility; new tournaments do not save them.
    result = {**DEFAULT_SETTINGS, **(previous or {}), **{k: v for k, v in data.items() if k not in SCORING_DEFAULTS}}
    require(type(result["table_size"]) is int and 2 <= result["table_size"] <= 8, "invalid_settings")
    require(result["scoring_mode"] in {"legacy", "return", PLACEMENT_MODE}, "invalid_settings")
    require(type(result["allow_guest_auto_enrollment"]) is bool, "invalid_settings")
    if result["scoring_mode"] == PLACEMENT_MODE:
        require(result["table_size"] == 4, "return_four_players")
        require(all(k in result for k in PLACEMENT_FIELDS), "placement_scores_required")
        for key in PLACEMENT_FIELDS:
            result[key] = float(number(result[key]))
    require(isinstance(result["uma"], list) and len(result["uma"]) == (4 if result["scoring_mode"] == "return" else result["table_size"]), "invalid_uma")
    if result["scoring_mode"] == "return":
        require(result["table_size"] == 4, "return_four_players")
    result["return_point"] = float(number(result["return_point"]))
    limit = result["time_limit_seconds"]
    if limit in (0, "") and type(limit) is not bool:
        limit = result["time_limit_seconds"] = None
    require(limit is None or (type(limit) is int and 1 <= limit <= 604800), "invalid_time_limit")
    require(number(result["base_points"]) > 0, "invalid_settings")
    require(result["pairing"] in {"random", "swiss"}, "invalid_settings")
    require(type(result["qualifying_rank"]) is int and result["qualifying_rank"] > 0, "invalid_settings")
    require(type(result["advance_on_tie"]) is bool, "invalid_settings")
    result["uma"] = [float(number(x)) for x in result["uma"]]
    result["bye_score"] = float(number(result["bye_score"]))
    result["base_points"] = float(number(result["base_points"]))
    return {**{k: result[k] for k in DEFAULT_SETTINGS}, **{k: result[k] for k in PLACEMENT_FIELDS if k in result},
            **{k: previous[k] for k in SCORING_DEFAULTS if previous and k in previous}}


def countable_placement_game(round_record, table, seen):
    """Only one valid, confirmed occurrence of each persisted game is counted."""
    if round_record.get("status") != "confirmed":
        return False
    for record in (round_record, table):
        if (any(record.get(flag) for flag in ("void", "is_test", "duplicate_of", "cancelled")) or
                record.get("status") in {"draft", "pending", "active", "cancelled", "canceled", "void", "invalidated", "test"}):
            return False
    result = table.get("result")
    if not result:
        return False
    identity = (("match", table["match_id"]) if table.get("match_id") else
                ("request", result["request_id"]) if result.get("request_id") else None)
    if identity is not None:
        if identity in seen:
            return False
        seen.add(identity)
    return True


def placement_result(settings, players):
    """Price trusted server-calculated placements independently of raw-point rules."""
    require(settings.get("scoring_mode") == PLACEMENT_MODE, "invalid_action")
    require(len(players) == 4 and len({p["id"] for p in players}) == 4 and
            {p["placement"] for p in players} == {1, 2, 3, 4}, "invalid_roster")
    participation = number(settings["game_participation_score"])
    scored = []
    for player in players:
        placement = number(settings[PLACEMENT_FIELDS[player["placement"] - 1]])
        scored.append({**{key: player[key] for key in ("id", "name", "seat", "placement", "rawScore")},
            "placementGameScore": float(placement), "gameParticipationScore": float(participation),
            "gameScore": float(placement + participation)})
    snapshot = {"scoring_mode": PLACEMENT_MODE, **{key: settings[key] for key in PLACEMENT_FIELDS}}
    return {"players": scored, "rules": copy.deepcopy(snapshot), "saved_at": now()}


def rescore_placement_result(settings, result):
    # Raw scores/placements were validated on upload. Confirmation and an explicit
    # reprice must not reinterpret them using a subsequently edited starting total.
    require(result.get("rules", {}).get("scoring_mode") == PLACEMENT_MODE, "invalid_scoring_snapshot")
    return placement_result(settings, result["players"])


def standings(state, finals=True):
    placement_mode = state["settings"].get("scoring_mode") == PLACEMENT_MODE
    # Decimal accumulation preserves the existing min-unit rounding policy;
    # no second rounding rule is introduced for adjustments or the winner.
    rows = {p["id"]: {**p, "score": Decimal(0), "game_score": Decimal(0), "penalty_total": Decimal(0),
        "round_score": 0, "completed_rounds": 0, "placements": [0] * 8,
        "placement_score_total": Decimal(0), "participation_score_total": Decimal(0),
        "preliminary_score": 0, "finals_start": 0, "finals_added": Decimal(0)} for p in state["players"]}
    seen_games = set()
    for rnd in state["rounds"]:
        if rnd["status"] != "confirmed" or rnd.get("void") or rnd.get("is_test"):
            continue
        for row in rows.values():
            row["round_score"] = 0
        for pid in rnd["byes"]:
            if placement_mode:
                continue
            rows[pid]["game_score"] += number(rnd["bye_score"])
            rows[pid]["completed_rounds"] += 1
            rows[pid]["round_score"] = rnd["bye_score"]
        for table in rnd["tables"]:
            if placement_mode and not countable_placement_game(rnd, table, seen_games):
                continue
            if not table.get("result") or table.get("void") or table.get("is_test") or table.get("duplicate_of"):
                continue
            for score in table["result"]["players"]:
                row = rows[score["id"]]
                row["game_score"] += number(score["gameScore"])
                row["placement_score_total"] += number(score.get("placementGameScore", 0))
                row["participation_score_total"] += number(score.get("gameParticipationScore", 0))
                row["round_score"] = score["gameScore"]
                row["placements"][score["placement"] - 1] += 1
                row["completed_rounds"] += 1
    active = [p for p in state.get("penalties", []) if p["status"] == "active"]
    for penalty in active:
        if penalty["phase"] == "swiss" and penalty["player_id"] in rows:
            rows[penalty["player_id"]]["penalty_total"] -= number(penalty["amount"])
    final = state.get("finals")
    if finals and final and final["status"] != "preview":
        rows = {pid: rows[pid] for pid in final["entrants"]}
        for pid, row in rows.items():
            start = final["starts"][pid]
            row["preliminary_score"] = start["preliminary_score"]
            row["finals_start"] = start["finals_start"]
            # Frozen game carry + live adjustment carry: revoking a penalty
            # changes the adjustment, never rewrites a historical match snapshot.
            initial_penalty = number(start.get("carried_penalty", 0))
            row["game_score"] = number(row["finals_start"]) - initial_penalty
            row["penalty_total"] = number(rounded(row["penalty_total"] * number(final["ratio"]), state["settings"]))
        for table in final["tables"]:
            for hand in table["hands"]:
                if not hand["void"]:
                    for pid, delta in hand["deltas"].items():
                        rows[pid]["finals_added"] += number(delta)
                        rows[pid]["game_score"] += number(delta)
        for penalty in active:
            if penalty["phase"] == "finals" and penalty["player_id"] in rows:
                rows[penalty["player_id"]]["penalty_total"] -= number(penalty["amount"])
    for row in rows.values():
        row["score"] = row["game_score"] + row["penalty_total"]
    # Stable tie order: total, 1st/2nd/... counts, most recent round, opaque ID.
    result = sorted(rows.values(), key=(lambda r: -r["score"]) if placement_mode else lambda r: (-r["score"],
        *[-n for n in r["placements"]], -r["round_score"], r["id"]))
    previous_score, previous_rank = None, None
    for index, row in enumerate(result):
        exact = row["score"]
        for key in ("score", "game_score", "penalty_total", "round_score", "finals_added", "placement_score_total", "participation_score_total"):
            row[key] = float(row[key]) if placement_mode else round(float(row[key]), 6)
        row["rank"] = previous_rank if placement_mode and previous_score == exact else index + 1
        previous_score, previous_rank = exact, row["rank"]
    return result


def comeback(rows, player_id, target_id, unit=1):
    lookup = {r["id"]: r for r in rows}
    require(player_id in lookup and target_id in lookup, "not_found")
    gap = number(lookup[target_id]["score"]) - number(lookup[player_id]["score"])
    return {"player_id": player_id, "target_id": target_id, "gap": float(gap),
        "tie_net": float(max(Decimal(0), gap)), "overtake_net": float(max(Decimal(0), gap + number(unit)))}


def table_name(state, index):
    return state.get("table_names", {}).get(str(index)) or DEFAULT_NAMES.get(str(index)) or str(index)


def previous_encounters(state):
    pairs, last, byes = {}, {}, {}
    for rnd in state["rounds"]:
        if rnd["status"] != "confirmed":
            continue
        for pid in rnd["byes"]:
            byes[pid] = byes.get(pid, 0) + 1
        for table in rnd["tables"]:
            ids = table["seats"]
            for i, pid in enumerate(ids):
                last[pid] = i
            for pair in itertools.combinations(sorted(ids), 2):
                pairs[pair] = pairs.get(pair, 0) + 1
    return pairs, last, byes


def seat_group(ids, last, rng):
    best, cost = list(ids), len(ids) + 1
    for _ in range(150):
        candidate = rng.sample(ids, len(ids))
        score = sum(last.get(pid) == i for i, pid in enumerate(candidate))
        if score < cost:
            best, cost = candidate, score
        if cost == 0:
            break
    return best


def pair_round(state, rng=None):
    rng = rng or random.SystemRandom()
    size, rows = state["settings"]["table_size"], standings(state, finals=False)
    require(len(rows) >= size, "not_enough_players")
    pairs, last, byecount = previous_encounters(state)
    ids, totals = [r["id"] for r in rows], {r["id"]: r["score"] for r in rows}
    shuffled = rng.sample(ids, len(ids))
    byes = sorted(shuffled, key=lambda p: (byecount.get(p, 0), totals[p]))[:len(ids) % size]
    ids = [p for p in ids if p not in byes]
    swiss = state["settings"]["pairing"] == "swiss" and bool(state["rounds"])
    if not swiss:
        rng.shuffle(ids)
    groups = [ids[i:i + size] for i in range(0, len(ids), size)]
    if swiss:
        # Adjacent score bands; a repeat costs 20 score points. Bounded local
        # swaps reduce rematches without mixing players with very large gaps.
        def cost(group):
            repeats = sum(pairs.get(tuple(sorted(pair)), 0) for pair in itertools.combinations(group, 2))
            return max(totals[p] for p in group) - min(totals[p] for p in group) + 20 * repeats
        for _ in range(3):
            changed = False
            for g in range(len(groups) - 1):
                left, right = groups[g], groups[g + 1]
                best, choice = cost(left) + cost(right), None
                for i in range(size):
                    for j in range(size):
                        a, b = left[:], right[:]
                        a[i], b[j] = b[j], a[i]
                        value = cost(a) + cost(b)
                        if value < best:
                            best, choice = value, (a, b)
                if choice:
                    groups[g:g + 2] = choice
                    changed = True
            if not changed:
                break
    from .tournament_flow import stable_id
    return {"id": str(uuid4()), "number": len(state["rounds"]) + 1, "status": "preview",
        "byes": byes, "bye_score": state["settings"]["bye_score"], "revision": 1,
        "tables": [{"number": i + 1, "table_id": stable_id(state["id"], "table:" + str(i + 1)), "match_id": str(uuid4()),
            "seats": seat_group(group, last, rng), "draft": None, "result": None} for i, group in enumerate(groups)]}


def score_table(state, table, raw):
    require(all(table["seats"]) and len(table["seats"]) == state["settings"]["table_size"]
            and len(set(table["seats"])) == len(table["seats"]), "invalid_roster")
    require(isinstance(raw, dict) and set(raw) == set(table["seats"]), "invalid_roster")
    settings = copy.deepcopy(state["settings"])
    values = {p: number(raw[p]) for p in table["seats"]}
    require(all(v % number(scoring_value(settings, "raw_step")) == 0 for v in values.values()), "invalid_raw_step")
    require(sum(values.values()) == number(settings["base_points"]) * len(values), "invalid_score_total")
    order = sorted(table["seats"], key=lambda p: (-values[p], table["seats"].index(p)))
    roster = {p["id"]: p["name"] for p in state["players"]}
    if settings.get("scoring_mode") == PLACEMENT_MODE:
        # Independent calculation. Raw points validate the game and determine placement only.
        require(len(order) == 4, "return_four_players")
        players = [{"id": pid, "name": roster[pid], "seat": "ESWN"[i],
                    "placement": order.index(pid) + 1, "rawScore": float(values[pid])}
                   for i, pid in enumerate(table["seats"])]
        return placement_result(settings, players)
    use_return = settings.get("scoring_mode", "legacy") == "return"
    if use_return:
        require(len(order) == 4 and len(settings["uma"]) == 4, "return_four_players")
    return_point = number(settings["return_point"] if use_return else settings["base_points"])
    players = []
    for i, pid in enumerate(table["seats"]):
        rank, value = order.index(pid) + 1, values[pid]
        placement = settings["uma"][rank - 1]
        difference = value - return_point
        converted = difference / number(scoring_value(settings, "divisor"))
        score = rounded(converted + number(placement), settings)
        players.append({"id": pid, "name": roster[pid], "seat": "ESWN"[i] if i < 4 else str(i + 1),
            "placement": rank, "rawScore": int(value) if value % 1 == 0 else float(value),
            "returnPoint": float(return_point), "pointDifference": float(difference),
            "convertedPoints": float(converted), "placementPoints": placement,
            "placementPointsApplied": not (use_return and rank == 1), "gameScore": score})
    if use_return:
        others = sum((number(p["gameScore"]) for p in players if p["placement"] != 1), Decimal(0))
        winner = next(p for p in players if p["placement"] == 1)
        winner["gameScore"] = float(abs(others))
        winner["winnerOtherTotal"] = float(others)
        # Never add the first placement point a second time.
    return {"players": players, "rules": settings, "saved_at": now()}
