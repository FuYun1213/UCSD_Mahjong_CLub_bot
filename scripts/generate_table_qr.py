"""Generate and decode-check the four table 1 seating QR labels."""

from pathlib import Path
import json
import argparse
import re
from urllib.parse import urlsplit
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mahjong_api.tournament_rules import DEFAULT_NAMES

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import qrcode


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "exports" / "table-1-qr"
BASE_URL = os.getenv("PUBLIC_SITE_URL", "")
WINDS = [("east", "东"), ("south", "南"), ("west", "西"), ("north", "北")]
FONT = "C:/Windows/Fonts/msyh.ttc"
BOLD_FONT = "C:/Windows/Fonts/msyhbd.ttc"


def text_center(draw, xy, text, size, bold=False, fill="#172431"):
    font = ImageFont.truetype(BOLD_FONT if bold else FONT, size)
    draw.text(xy, text, font=font, fill=fill, anchor="mm")


def main():
    parser = argparse.ArgumentParser(description="Generate seating QR images for the selected table.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--table", default="1")
    parser.add_argument("--name", default="")
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        parser.error("Set --base-url to the public website origin.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.table):
        parser.error("Table IDs must be alphanumeric.")
    base = args.base_url.rstrip("/")
    label_name = args.name or DEFAULT_NAMES.get(args.table, args.table)
    output = ROOT / "exports" / ("table-" + args.table + "-qr")
    output.mkdir(parents=True, exist_ok=True)
    page = Image.new("RGB", (2480, 3508), "white")
    page_draw = ImageDraw.Draw(page)
    text_center(page_draw, (1240, 155), f"{label_name} · 扫码入座", 96, bold=True)
    text_center(page_draw, (1240, 270), "请将对应风位的二维码贴在座位旁", 43)
    results = []
    detector = cv2.QRCodeDetectorAruco()

    for index, (wind, label) in enumerate(WINDS):
        url = f"{base}/sit?table={args.table}&seat={wind}"
        code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, border=4)
        code.add_data(url)
        code.make(fit=True)
        # Use integer module sizes to keep every QR edge sharp when printed.
        code.box_size = 900 // (code.modules_count + 8)
        qr_image = code.make_image(fill_color="black", back_color="white").convert("RGB")
        card = Image.new("RGB", (1080, 1350), "white")
        draw = ImageDraw.Draw(card)
        text_center(draw, (540, 108), f"{label}风", 112, bold=True)
        text_center(draw, (540, 218), f"{label_name} · {wind.upper()}", 43)
        card.paste(qr_image, ((1080 - qr_image.width) // 2, 290))
        text_center(draw, (540, 1224), "扫码自动选择本桌、本风位", 37)
        text_center(draw, (540, 1290), base, 27, fill="#52616f")
        path = output / f"table-{args.table}-{wind}.png"
        card.save(path, dpi=(300, 300))

        decoded, _, _ = detector.detectAndDecode(cv2.imread(str(path)))
        if decoded != url:
            raise RuntimeError(f"QR decode mismatch: {wind}: {decoded!r}")
        x = 120 + (index % 2) * 1160
        y = 380 + (index // 2) * 1430
        page.paste(card, (x, y))
        page_draw.rounded_rectangle((x, y, x + 1079, y + 1349), radius=22, outline="#cbd2d8", width=3)
        results.append({"seat": wind, "label": f"{label}风", "url": url, "file": path.name, "decoded": decoded})

    text_center(page_draw, (1240, 3280), "已登录自动入座 · 未登录先登录后继续", 42)
    text_center(page_draw, (1240, 3375), "A4 打印后沿边框裁剪，保持二维码四周白边完整", 31, fill="#52616f")
    page.save(output / f"table-{args.table}-all-winds-A4.png", dpi=(300, 300))
    # Also verify the final print layout, including all four pasted codes.
    for index, result in enumerate(results):
        x = 120 + (index % 2) * 1160
        y = 380 + (index // 2) * 1430
        crop = np.array(page.crop((x, y, x + 1080, y + 1350)))
        decoded, _, _ = detector.detectAndDecode(cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
        if decoded != result["url"]:
            raise RuntimeError(f"Print-layout QR decode mismatch: {result['seat']}")
    (output / "qr-links.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    page.resize((992, 1403), Image.Resampling.LANCZOS).save(output / f"table-{args.table}-preview.png")
    print(json.dumps({"output": str(output), "verified": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
