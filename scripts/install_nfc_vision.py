"""Download the public OICWS v1.1.0 model with release SHA-256 verification.

Upstream inference code: AGPL-3.0; pretrained weights: CC BY 4.0.
https://github.com/OICWS/lcd-digit-recognition/releases/tag/v1.1.0
"""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / "third_party" / "lcd_digit_recognition"
ASSETS = {
    "best.pt": "d43dcf6d806586f92e4646b7c7d39d57008e80cedbf8f6479cb51a8e4c4b388f",
    "final_crnn.pth": "0bc18c193043516986a5b4445643b1558e03a03d8eb191b9bad2dd860131b408",
    "crnn_config.json": "ff9843b958e481eaf06305ae9e42058e79d95d8d82ea3aa933269b8038bdc2fb",
}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "models").mkdir(exist_ok=True)
    manifest = {"project": "OICWS/lcd-digit-recognition", "version": "v1.1.0", "files": {}}
    source_hashes = {"ocr_reader.py": "8dcd8016d5affec415c218751ea32a12482f5e34d550a5d0ba7aada90d5c606f",
                     "LICENSE": "8486a10c4393cee1c25392769ddd3b2d6c242d6ec7928e1414efff7dfb2f07ef"}
    for name in source_hashes:
        url = f"https://raw.githubusercontent.com/OICWS/lcd-digit-recognition/v1.1.0/{name}"
        content = urlopen(url, timeout=60).read()
        if hashlib.sha256(content).hexdigest() != source_hashes[name]:
            raise RuntimeError(f"Source checksum mismatch for {name}")
        (ROOT / name).write_bytes(content)
        manifest["files"][name] = {"url": url, "sha256": hashlib.sha256(content).hexdigest()}
    for name, expected in ASSETS.items():
        url = f"https://github.com/OICWS/lcd-digit-recognition/releases/download/v1.1.0/{name}"
        target = ROOT / "models" / name
        content = target.read_bytes() if target.exists() else urlopen(url, timeout=60).read()
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Checksum mismatch for {name}")
        target.write_bytes(content)
        manifest["files"][f"models/{name}"] = {"url": url, "sha256": actual}
    (ROOT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Verified OCR weights installed at {ROOT}")


if __name__ == "__main__":
    main()
