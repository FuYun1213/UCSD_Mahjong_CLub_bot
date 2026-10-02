# Licensing and assets

Original project source code and documentation are licensed under the [MIT License](LICENSE), as authorized by the repository owner. Standard license text: <https://opensource.org/license/mit>.

Third-party packages keep their own licenses. Installing dependencies does not relicense them under this project's MIT license. No pretrained OCR model weights are committed here. The production frontend includes React 18.3.1, React DOM 18.3.1 and generated Tailwind CSS under their original MIT licenses. The unmodified optional HEIC decoder in `web/vendor/heic-to-1.5.2.js` is heic-to 1.5.2 under LGPL-3.0; its full license and upstream source/build references are supplied in `web/vendor/heic-to-LICENSE.txt` and `web/vendor/heic-to-NOTICE.txt`.

The default panel decoder uses Pillow, NumPy and OpenCV. An **optional**, separately downloaded OCR integration is provided by `scripts/install_nfc_vision.py`: OICWS/lcd-digit-recognition v1.1.0. Its inference code is identified by the upstream project as AGPL-3.0, and its pretrained weights as CC BY 4.0. The optional Ultralytics/Torch stack has separate license terms. Review the upstream licenses before enabling, modifying or distributing those integrations; the repository's MIT license does not replace their terms.

- OICWS project: <https://github.com/OICWS/lcd-digit-recognition>
- Optional download locations and integrity checks: `scripts/install_nfc_vision.py`
- Python dependencies: `requirements*.txt`
- Development JavaScript dependencies: `package.json` and `package-lock.json`

The DORA/UC San Diego names and `web/assets/UCSD_mermaid_whitebg.jpg` and `web/assets/dora-club-icon.png` identify the original club. The MIT software license does not grant trademark rights or imply university/club endorsement. Replace the branding for an unrelated deployment. Display-panel images under `tests/fixtures/displays/` are regression fixtures, not production user uploads.
