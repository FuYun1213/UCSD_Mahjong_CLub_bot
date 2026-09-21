"""Keep image-relative positions, physical wind, and historical array order separate."""

import re

from .models import SEATS

POSITIONS = ("bottom", "right", "top", "left")
LEGACY_SEATS = ("east", "west", "south", "north")


def relative_to_absolute(uploader_seat: str) -> dict[str, str]:
    # Example uploader=south: offset=1. Incrementing around ESWN gives
    # bottom=south, right=west, top=north, left=east, exactly as specified.
    # EWSN was a legacy serialization order, NOT the rotation order of a table.
    offset = SEATS.index(uploader_seat)
    return {position: SEATS[(offset + index) % 4] for index, position in enumerate(POSITIONS)}


def normalize_display_score(raw: str, multiplier: int = 1) -> int:
    """Use the SAME multiplier for every score in one photo (never suffix rules)."""
    value = raw.strip()
    if not re.fullmatch(r"-?[0-9]{1,8}", value):
        raise ValueError("无法识别为整数，请手动输入完整点数")
    if multiplier not in (1, 100):
        raise ValueError("显示单位只能为 1 点或 100 点")
    points = int(value) * multiplier
    if abs(points) > 10_000_000:
        raise ValueError("点数超出范围")
    return points


def display_units(scores: dict[str, str]):
    values = []
    for raw in scores.values():
        try:
            values.append(normalize_display_score(raw))
        except ValueError:
            pass
    # A complete frame sums to either 1000 display units or 100000 points.
    # Incomplete/incorrect OCR uses magnitude for a preview only. The total
    # check still requires correction. Never rescale players separately.
    raw_total = sum(values)
    if len(values) == 4 and raw_total in (1000, 100000):
        multiplier = 100 if raw_total == 1000 else 1
    else:
        multiplier = 100 if values and max(abs(v) for v in values) < 10000 else 1
    return {"display_unit": "hundreds" if multiplier == 100 else "points",
            "multiplier": multiplier, "raw_total": raw_total,
            "unit_inferred_from": "total" if len(values) == 4 and raw_total in (1000, 100000) else "magnitude_preview"}


def map_and_normalize(scores: dict[str, str], uploader_seat: str):
    mapping = relative_to_absolute(uploader_seat)
    multiplier = display_units(scores)["multiplier"]
    normalized, issues = {}, []
    for position, seat in mapping.items():
        try:
            normalized[seat] = normalize_display_score(scores[position], multiplier)
            if normalized[seat] % 100:
                issues.append({"code": "invalid_point_increment", "position": position, "seat": seat})
        except ValueError as exc:
            normalized[seat] = None
            issues.append({"code": "invalid_digits", "position": position, "seat": seat, "message": str(exc)})
    total = sum(value for value in normalized.values() if value is not None)
    if total != 100000 or any(value is None for value in normalized.values()):
        issues.append({"code": "invalid_total", "total": total, "expected_total": 100000})
    return normalized, mapping, issues
