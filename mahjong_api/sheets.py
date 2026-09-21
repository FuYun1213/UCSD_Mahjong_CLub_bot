"""gspread adapter. Dedicated worksheets and stable database-assigned row numbers.

Each new match occupies the next history row. Retrying writes that same row,
including after an ambiguous timeout, rather than appending a duplicate match.
Do not sort, delete or insert rows in these two API-owned worksheets.
"""

from typing import Protocol

import gspread
from gspread.utils import rowcol_to_a1

from .config import Settings
from .models import SEATS


CURRENT_HEADERS = ["Table", "East", "South", "West", "North", "Updated_At"]
HISTORY_HEADERS = ["Match_ID", "Round", "Table", "Played_At"] + [
    f"{seat.title()}_{field}"
    for seat in SEATS
    for field in ("User_ID", "Player", "Initial_Points", "Final_Points", "Delta_Points", "Net_Score")
]

HISTORY_HEADERS += ["Started_At", "Ended_At", "Duration_Seconds", "Seat_Order", "Source_Seat_Order", "Uploader_ID"]


class SheetsSink(Protocol):
    enabled: bool

    def write_current(self, table: dict) -> None: ...
    def write_history(self, match: dict) -> None: ...
    def write_manual_history(self, match: dict) -> None: ...


class DisabledSheets:
    enabled = False

    def write_current(self, table: dict) -> None:
        pass

    def write_history(self, match: dict) -> None:
        pass

    def write_manual_history(self, match: dict) -> None:
        pass


class GSpreadSheets:
    enabled = True

    def __init__(self, settings: Settings):
        self.settings = settings
        self._book = None
        self._worksheets = {}

    def _worksheet(self, title: str, headers: list[str]):
        if title in self._worksheets:
            return self._worksheets[title]
        if self._book is None:
            client = gspread.service_account(
                filename=self.settings.credentials_file,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            client.set_timeout(self.settings.google_timeout_seconds)
            self._book = client.open_by_key(self.settings.spreadsheet_id)
        try:
            sheet = self._book.worksheet(title)
        except gspread.WorksheetNotFound:
            sheet = self._book.add_worksheet(title=title, rows=1000, cols=len(headers))
        first_row = sheet.row_values(1)
        if not first_row:
            # Refuse to initialize over unrelated data with an accidentally empty header.
            if any(any(value for value in row) for row in sheet.get_all_values()):
                raise ValueError(f"Worksheet {title} contains data but no header")
            if sheet.col_count < len(headers):
                sheet.add_cols(len(headers) - sheet.col_count)
            sheet.update(range_name=f"A1:{rowcol_to_a1(1, len(headers))}", values=[headers], value_input_option="RAW")
        elif first_row == headers[:28] and len(headers) > 28:
            # Upgrade only the known v1 history layout, preserving all old columns.
            if sheet.col_count < len(headers):
                sheet.add_cols(len(headers) - sheet.col_count)
            sheet.update(range_name=f"AC1:{rowcol_to_a1(1, len(headers))}", values=[headers[28:]], value_input_option="RAW")
        elif first_row != headers:
            raise ValueError(f"Worksheet {title} header mismatch; use a dedicated empty worksheet")
        self._worksheets[title] = sheet
        return sheet

    @staticmethod
    def _write_row(sheet, row_number: int, values: list):
        if row_number > sheet.row_count:
            sheet.add_rows(max(100, row_number - sheet.row_count))
        existing = sheet.row_values(row_number)
        if any(existing) and (not existing or str(existing[0]) != str(values[0])):
            raise ValueError("Sheet row belongs to another record; restore the matching database/worksheet layout")
        sheet.update(
            range_name=f"A{row_number}:{rowcol_to_a1(row_number, len(values))}",
            values=[values],
            value_input_option="RAW",  # Player names such as '=SUM(...)' remain text.
        )

    def write_current(self, table: dict) -> None:
        sheet = self._worksheet(self.settings.current_sheet, CURRENT_HEADERS)
        values = [table["table_id"]] + [
            table["seats"][seat]["name"] if table["seats"][seat] else "" for seat in SEATS
        ] + [table["updated_at"]]
        self._write_row(sheet, table["slot"] + 1, values)

    def write_history(self, match: dict) -> None:
        self._write_history(match, self.settings.history_sheet)

    def write_manual_history(self, match: dict) -> None:
        # Generic games have no fabricated table/round and their own durable
        # sequence, so they cannot reuse the NFC worksheet's reserved rows.
        self._write_history(match, self.settings.history_sheet + " - Manual")

    def _write_history(self, match: dict, title: str) -> None:
        sheet = self._worksheet(title, HISTORY_HEADERS)
        result = match["result"]
        values = [match["match_id"], result["round"] or "", result["table"] or "", result["played_at"]]
        for seat in SEATS:
            player = result["players"][seat]
            values.extend([
                player["user"]["id"], player["user"]["name"], player["initial_points"],
                player["final_points"], player["delta_points"], player["net_score"],
            ])
        values.extend([result.get("started_at") or "", result.get("ended_at") or "",
            result.get("duration_seconds") if result.get("duration_seconds") is not None else "",
            result.get("seat_order", "ESWN"), result.get("source_seat_order", "ESWN"), result.get("uploader_id") or ""])
        self._write_row(sheet, match["sequence"] + 1, values)
