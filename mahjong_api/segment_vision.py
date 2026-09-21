"""Read four scores on blue LCD / red LED mahjong control panels.

This is a deterministic seven-segment decoder, not a trained neural network.
It uses colour, repeated digit baselines, and segment occupancy. No score sum,
filename, fixture values, or expected player score participates in recognition.
Two independent colour thresholds must agree before automatic settlement.
"""
import itertools
import math

import cv2
import numpy as np

cv2.setNumThreads(1)  # Bound CPU/thread overhead on the small production server.

from .score_mapping import POSITIONS


# Segment order: top, upper right, lower right, bottom, lower left,
# upper left, middle. A decimal point (sometimes called the eighth segment)
# is not a score digit and must not be interpreted as an extra zero.
PATTERNS = {
    "1111110": "0", "0110000": "1", "1101101": "2", "1111001": "3",
    "0110011": "4", "1011011": "5", "1011111": "6", "1110000": "7",
    "1111111": "8", "1111011": "9",
}
ZONES = ((12, 0, 28, 10), (28, 10, 40, 27), (28, 37, 40, 54),
         (12, 54, 28, 64), (0, 37, 12, 54), (0, 10, 12, 27), (12, 27, 28, 37))


def _contours(mask):
    contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    return sorted((c for c in contours if cv2.contourArea(c) > 12),
                  key=cv2.contourArea, reverse=True)[:128]


def _deskew(mask):
    digits = []
    for contour in _contours(mask):
        center, (width, height), _ = cv2.minAreaRect(contour)
        small, large = min(width, height), max(width, height)
        if small > 3 and 1.05 < large / small < 6 and large > 15:
            digits.append((np.array(center), large))
    angles = []
    for (a, ha), (b, hb) in itertools.combinations(digits, 2):
        if not .7 < ha / hb < 1.4:
            continue
        dx, dy = b - a
        if dx < 0:
            dx, dy = -dx, -dy
        angle = math.degrees(math.atan2(dy, dx))
        if .3 < np.hypot(dx, dy) / max(ha, hb) < 3.5 and -55 < angle < 55:
            angles.append(angle)
    # Digit shapes themselves are slanted (e.g. AMOS italic LEDs). Use the
    # repeated centres of neighbouring digits, not a single glyph's angle.
    if angles:
        samples = np.asarray(angles)
        peak = max(np.arange(-55, 56, .5), key=lambda x: np.count_nonzero(abs(samples - x) < 2))
        angle = float(np.median(samples[abs(samples - peak) < 2]))
    else:
        angle = 0.0
    height, width = mask.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    new_width = int(abs(matrix[0, 0]) * width + abs(matrix[0, 1]) * height)
    new_height = int(abs(matrix[0, 1]) * width + abs(matrix[0, 0]) * height)
    matrix[:, 2] += np.array([new_width - width, new_height - height]) / 2
    return cv2.warpAffine(mask, matrix, (new_width, new_height)), angle


def _decode_digit(crop):
    height, width = crop.shape
    if width / height < .5:
        # A one has only the two right vertical segments; its tight bounding
        # box is much narrower than every other complete digit.
        if .12 < width / height and np.count_nonzero(crop > 100) / crop.size > .3:
            return "1", .2
        return "?", 0.0
    choices = []
    for shear in np.arange(-.3, .31, .05):
        matrix = np.array([[1, shear, -min(0, shear * height)], [0, 1, 0]], np.float32)
        straight = cv2.warpAffine(crop, matrix, (width + int(abs(shear * height)) + 1, height))
        yy, xx = np.where(straight > 100)
        if not len(xx):
            continue
        straight = straight[yy.min():yy.max() + 1, xx.min():xx.max() + 1]
        bitmap = cv2.resize(straight, (40, 64)) > 100
        occupancy = np.array([bitmap[y1:y2, x1:x2].mean() for x1, y1, x2, y2 in ZONES])
        pattern = "".join("1" if value > .3 else "0" for value in occupancy)
        if pattern in PATTERNS:
            margin = float(min(abs(occupancy - .3)))
            choices.append((margin, PATTERNS[pattern]))
    if not choices:
        return "?", 0.0
    margin, digit = max(choices)
    return (digit if margin >= .04 else "?"), margin


def _digit_boxes(mask):
    boxes = []
    for contour in _contours(mask):
        x, y, width, height = cv2.boundingRect(contour)
        if height < 12 or width > height * 1.5:
            continue
        if width / height > .95:
            # A faint bridge can connect adjacent digits in a phone JPEG.
            # Split only at a low-ink valley, never at a presumed score length.
            crop = mask[y:y + height, x:x + width]
            lo, hi = int(width * .3), int(width * .7)
            counts = np.count_nonzero(crop[:, lo:hi] > 100, axis=0)
            cut = lo + int(counts.argmin())
            if counts.min() > height * .25:
                boxes.append((x, y, width, height))
                continue
            for start, end in ((0, cut), (cut, width)):
                yy, xx = np.where(crop[:, start:end] > 100)
                if len(xx):
                    boxes.append((x + start + int(xx.min()), y + int(yy.min()),
                                  int(xx.max() - xx.min() + 1), int(yy.max() - yy.min() + 1)))
        else:
            boxes.append((x, y, width, height))
    return sorted(boxes)


def _read_groups(mask):
    groups = []
    for box in _digit_boxes(mask):
        x, y, width, height = box
        for group in groups:
            px, py, pw, ph = group[-1]
            # Large leading digits and smaller trailing 00 share a baseline.
            if (0 <= x - px - pw < max(height, ph)
                    and abs(y + height - py - ph) < max(height, ph) * .28
                    and min(height, ph) / max(height, ph) > .55):
                group.append(box)
                break
        else:
            groups.append([box])
    result = []
    all_boxes = [cv2.boundingRect(c) for c in _contours(mask)]
    for group in groups:
        # Single-digit ranks are separate labels above a score, not scores.
        if not 3 <= len(group) <= 7:
            continue
        digits, margins = [], []
        for x, y, width, height in group:
            digit, margin = _decode_digit(mask[y:y + height, x:x + width])
            digits.append(digit)
            margins.append(margin)
        x1 = min(box[0] for box in group)
        y1 = min(box[1] for box in group)
        x2 = max(box[0] + box[2] for box in group)
        y2 = max(box[1] + box[3] for box in group)
        height = y2 - y1
        sign = ""
        for x, y, w, h in all_boxes:
            if (w > 1.4 * h and .06 * height < h < .4 * height
                    and 0 < x1 - x - w < 2 * height
                    and abs(y + h / 2 - (y1 + y2) / 2) < .2 * height):
                sign = "-"
                break
        result.append({"raw": sign + "".join(digits), "box": [x1, y1, x2, y2],
                       "segment_margin": round(min(margins), 4)})
    return result


def _assign(groups):
    if len(groups) != 4:
        return {}, [{"code": "display_count", "found": len(groups), "expected": 4, "candidates": groups}]
    def center(group):
        x1, y1, x2, y2 = group["box"]
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    left, a, b, right = sorted(groups, key=lambda g: center(g)[0])
    top, bottom = sorted((a, b), key=lambda g: center(g)[1])
    if not (center(top)[1] < min(center(left)[1], center(right)[1])
            and center(bottom)[1] > max(center(left)[1], center(right)[1])):
        return {}, [{"code": "ambiguous_display_position", "candidates": groups}]
    observations = dict(zip(POSITIONS, (bottom, right, top, left)))
    issues = [{"code": "unreadable_segments", "position": position}
              for position, group in observations.items() if "?" in group["raw"]]
    return observations, issues


def recognize_panel(photo):
    photo = photo.copy()
    photo.thumbnail((2048, 2048))
    rgb = np.asarray(photo)
    red, green, blue = (rgb[:, :, index].astype(np.float32) for index in range(3))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    blue_mask = cv2.inRange(hsv, (90, 100, 70), (140, 255, 255))
    blue_contours = _contours(blue_mask)
    panel = np.zeros(blue_mask.shape, np.uint8)
    if blue_contours and cv2.contourArea(blue_contours[0]) > panel.size * .06:
        cv2.fillConvexPoly(panel, cv2.convexHull(blue_contours[0]), 255)
        layout = "blue_lcd"
    else:
        layout = "red_led"
    passes = []
    for delta in (0, 10):
        if layout == "blue_lcd":
            # White/cyan score glyphs; exclude yellow totals and coloured deltas.
            mask = (red > 150 + delta) & (green > 170) & (blue > 170) & (blue > green * .85) & (panel > 0)
        else:
            # Reject the orange AMOS housing and dim reflections of unlit bars.
            mask = (red > 160) & (red - np.maximum(green, blue) > 100 + delta) & (blue > green * 1.3)
        mask, angle = _deskew(mask.astype(np.uint8) * 255)
        observations, issues = _assign(_read_groups(mask))
        passes.append((observations, issues, angle))
    observations, issues, angle = passes[0]
    alternate, alternate_issues, _ = passes[1]
    scores = {position: observations.get(position, {}).get("raw", "") for position in POSITIONS}
    if alternate_issues or scores != {position: alternate.get(position, {}).get("raw", "") for position in POSITIONS}:
        issues.append({"code": "unstable_segments", "message": "不同曝光阈值的识别结果不一致，请手动核对"})
    return {"scores": scores, "issues": issues, "observations": observations,
            "model": "mahjong-seven-segment-v1", "engine": "opencv_segments", "layout": layout,
            "deskew_degrees": round(angle, 2), "box_coordinates": "deskewed_image_pixels"}
