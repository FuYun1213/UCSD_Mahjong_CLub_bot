from pathlib import Path
import sys

import mahjong_store


ROOT = Path(__file__).resolve().parent
VENDOR_DIR = ROOT / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import gspread

SHEET_ID = "1Ce5k2Blbf5MYXbM4rSTeWHOf2uTHPrvZX6vm6Cdyc5Q"
CREDENTIALS_FILE = ROOT / "credentials.json"
DB_FILE = ROOT / "mahjong.sqlite3"
YAKUMAN_WINNER_INDEX = 18
YAKUMAN_DEAL_IN_INDEX = 19
YAKUMAN_NAMES_INDEX = 20
QUARTER_COLUMN_INDEX = 17


def safe_int(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def sync():
    client = gspread.service_account(filename=str(CREDENTIALS_FILE))
    sheet = client.open_by_key(SHEET_ID)
    game_rows = sheet.worksheet("Games Riichi").get_all_values()
    pt_rows = sheet.worksheet("Games/pt").get_all_values()

    imported = 0
    skipped = 0
    current_quarter = ""
    with mahjong_store.connect(DB_FILE) as connection:
        for row_index in range(1, len(game_rows)):
            row = game_rows[row_index]
            marker = row[QUARTER_COLUMN_INDEX].strip() if len(row) > QUARTER_COLUMN_INDEX else ""
            if marker:
                current_quarter = marker

            if len(row) < 8:
                skipped += 1
                continue

            names = [str(value).strip() for value in row[:4]]
            scores = [safe_int(value) for value in row[4:8]]
            if not all(names) or len(scores) != 4 or sum(scores) != 100000:
                skipped += 1
                continue
            if len({mahjong_store.normalize_name(name) for name in names}) != 4:
                print(f"Skipped row {row_index + 1}: duplicate player names: {names}")
                skipped += 1
                continue

            pt_row = pt_rows[row_index] if row_index < len(pt_rows) else []
            played_at = pt_row[0] if pt_row else ""
            if not played_at:
                played_at = f"sheet-row-{row_index + 1}"

            yakuman = {
                "winner": row[YAKUMAN_WINNER_INDEX].strip() if len(row) > YAKUMAN_WINNER_INDEX else "",
                "deal_in": row[YAKUMAN_DEAL_IN_INDEX].strip() if len(row) > YAKUMAN_DEAL_IN_INDEX else "",
                "text": row[YAKUMAN_NAMES_INDEX].strip() if len(row) > YAKUMAN_NAMES_INDEX else "",
            }
            before = connection.total_changes
            mahjong_store.import_game(
                connection,
                names,
                scores,
                played_at,
                source="sheet",
                sheet_row=row_index + 1,
                created_by="sheet-sync",
                yakuman=yakuman,
                quarter=current_quarter,
            )
            if connection.total_changes > before:
                imported += 1

        if current_quarter:
            mahjong_store.set_current_quarter(connection, current_quarter)

    print(f"Imported or updated {imported} games. Skipped {skipped} rows.")


if __name__ == "__main__":
    sync()
