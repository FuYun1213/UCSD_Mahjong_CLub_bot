"""Mahjong panel decoder, with optional explicit-region CRNN adapter.

The adapter preserves raw character strings (including dubious decimals), rather
than converting via float and losing evidence. Domain accuracy needs real photos.
"""
import importlib.util
import io
import math
import threading
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .score_mapping import POSITIONS


ROTATIONS = dict.fromkeys(POSITIONS, 0)  # All scores on a control panel are upright.


def read_photo(content):
    try:
        with Image.open(io.BytesIO(content)) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("仅支持 JPEG、PNG、WebP 照片")
            if original.width * original.height > 24_000_000:
                raise ValueError("图片超过 2400 万像素，请先缩小")
            original.draft("RGB", (2048, 2048))
            oriented = ImageOps.exif_transpose(original)
            oriented.thumbnail((2048, 2048))
            return oriented.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("无法读取照片") from exc


def validate_regions(regions):
    if not isinstance(regions, dict) or set(regions) != set(POSITIONS):
        raise ValueError("regions 必须包含 bottom/right/top/left 四个区域")
    result = {}
    for position, value in regions.items():
        if not isinstance(value, dict):
            raise ValueError("区域必须包含 box 和 rotation")
        box = value.get("box")
        rotation = value.get("rotation", ROTATIONS[position])
        if not isinstance(box, list) or len(box) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in box):
            raise ValueError("box 必须是四个有限坐标值")
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1) or rotation not in (0, 90, 180, 270):
            raise ValueError("区域坐标应归一化到 0..1，旋转角度应为 0/90/180/270")
        result[position] = {"box": box, "rotation": rotation, "confidence": 1.0}
    return result


class LCDRecognizer:
    def __init__(self, directory: Path, confidence=0.95):
        self.directory = directory.resolve()
        self.confidence = confidence
        self._module = None
        self._lock = threading.Lock()

    def _load(self):
        if self._module is None:
            path = self.directory / "ocr_reader.py"
            spec = importlib.util.spec_from_file_location("nfc_lcd_reader", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.get_crnn()
            self._module = module
        return self._module

    def recognize(self, content: bytes, regions=None):
        with self._lock:
            photo = read_photo(content)
            if regions is None:
                from .segment_vision import recognize_panel
                return recognize_panel(photo)
            selected = validate_regions(regions)
            module = self._load()
            import torch

            issues = []
            scores, observations = dict.fromkeys(POSITIONS, ""), {}
            for position in POSITIONS:
                region = selected.get(position)
                if region is None:
                    issues.append({"code": "missing_display", "position": position})
                    continue
                x1, y1, x2, y2 = region["box"]
                crop = photo.crop((int(x1 * photo.width), int(y1 * photo.height), int(x2 * photo.width), int(y2 * photo.height)))
                if crop.width < 4 or crop.height < 4:
                    issues.append({"code": "tiny_display", "position": position})
                    continue
                crop = crop.rotate(region["rotation"], expand=True)
                tensor = module.TRANSFORM(module.smart_resize(crop)).unsqueeze(0)
                with torch.inference_mode():
                    logits = module.get_crnn()(tensor).log_softmax(2)
                raw, character_confidence = module.decode_with_confidence(logits[:, 0, :])
                confidence = min(region["confidence"], character_confidence)
                scores[position] = raw
                observations[position] = {**region, "raw": raw, "confidence": confidence}
                if confidence < self.confidence:
                    issues.append({"code": "low_confidence", "position": position, "confidence": confidence})
            return {"scores": scores, "issues": issues, "observations": observations,
                    "model": "OICWS/lcd-digit-recognition@v1.1.0"}
