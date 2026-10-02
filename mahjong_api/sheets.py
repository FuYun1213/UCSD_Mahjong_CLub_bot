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
        elif first_row != headers and not (first_row[:len(headers)] == headers and
                first_row[len(headers):] in (["NFC_Revision"], ["NFC_Revision", "NFC_Payload_SHA256"])):
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

    def history_targets(self, match):
        manual = match["result"].get("table") is None
        return [{"channel": "nfc_manual_history" if manual else "nfc_history", "target": {
            "adapter": "gspread_history", "spreadsheet_id": self.settings.spreadsheet_id,
            "worksheet": self.settings.history_sheet + (" - Manual" if manual else ""),
        }}]

    def _target_sink(self, target):
        """Use the enqueued destination even after runtime configuration changes."""
        spreadsheet_id = target["spreadsheet_id"]
        if spreadsheet_id == self.settings.spreadsheet_id:
            return self
        from dataclasses import replace
        if not hasattr(self, "_target_sinks"):
            self._target_sinks = {}
        if spreadsheet_id not in self._target_sinks:
            self._target_sinks[spreadsheet_id] = GSpreadSheets(replace(self.settings, spreadsheet_id=spreadsheet_id))
        return self._target_sinks[spreadsheet_id]

    def open_book(self):
        if self._book is None:
            client = gspread.service_account(filename=self.settings.credentials_file,
                scopes=["https://www.googleapis.com/auth/spreadsheets"])
            client.set_timeout(self.settings.google_timeout_seconds)
            self._book = client.open_by_key(self.settings.spreadsheet_id)
        return self._book

    @staticmethod
    def _history_values(match):
        result = match["result"]
        values = [match["match_id"], result["round"] or "", result["table"] or "", result["played_at"]]
        for seat in SEATS:
            player = result["players"][seat]
            values.extend([player["user"]["id"], player["user"]["name"], player["initial_points"],
                player["final_points"], player["delta_points"], player["net_score"]])
        values.extend([result.get("started_at") or "", result.get("ended_at") or "",
            result.get("duration_seconds") if result.get("duration_seconds") is not None else "",
            result.get("seat_order", "ESWN"), result.get("source_seat_order", "ESWN"), result.get("uploader_id") or ""])
        return values

    def deliver_history(self, target, match, *, reconcile=False):
        """Locate by Match_ID, verify the frozen snapshot, then append at most once.

        The revision/hash travel in the same append as scores. Sorting a worksheet
        does not invalidate the lookup; duplicate/conflicting markers fail closed.
        """
        from .history_delivery import digest
        sink = self._target_sink(target)
        sheet = sink._worksheet(target["worksheet"], HISTORY_HEADERS)
        values = self._history_values(match)
        return publish_marked_row(sheet, match["match_id"], values, marker_column=1,
            revision_column=len(HISTORY_HEADERS) + 1, payload_hash=digest(values), marker_in_values=True)


def _cell(value):
    # Sheets reads numeric cells as strings; 0 and 0.0 are the same stored value.
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def publish_marked_row(sheet, match_id, values, *, marker_column, revision_column,
                       payload_hash, marker_in_values=False, required_row=None):
    """Shared marker reconciliation for the dedicated and two legacy targets."""
    from .history_delivery import HistoryDeliveryUnknown, HistoryNeedsReview
    hash_column = revision_column + 1
    headers = sheet.row_values(1)
    metadata_columns = ((marker_column, "Match_ID" if marker_in_values else "NFC_Match_ID"),
                        (revision_column, "NFC_Revision"), (hash_column, "NFC_Payload_SHA256"))
    # Validate every column before any mutation. An empty header does not mean
    # the column is unused: formulas below it may display an empty string.
    for column, label in metadata_columns:
        old = headers[column - 1] if len(headers) >= column else ""
        if old not in ("", label):
            raise HistoryNeedsReview("History metadata column is already in use")
        if not old and column <= sheet.col_count and any(
                value not in (None, "") for value in sheet.col_values(column, value_render_option="FORMULA")[1:]):
            raise HistoryNeedsReview("History metadata column contains data without a header")
    if sheet.col_count < hash_column:
        sheet.add_cols(hash_column - sheet.col_count)
    for column, label in metadata_columns:
        if len(headers) < column or not headers[column - 1]:
            sheet.update(range_name=rowcol_to_a1(1, column), values=[[label]], value_input_option="RAW")
    markers = sheet.col_values(marker_column)
    rows = [index + 1 for index, marker in enumerate(markers) if str(marker) == str(match_id)]
    if len(rows) > 1:
        raise HistoryNeedsReview("Duplicate history match markers")
    if required_row is not None and rows and rows[0] != required_row:
        raise HistoryNeedsReview("The game's date and score rows are misaligned")
    expected = list(values)
    if not marker_in_values:
        expected += [""] * (marker_column - len(expected) - 1) + [match_id]
    expected += [""] * (revision_column - len(expected) - 1) + [1, payload_hash]
    if not rows:
        # A lost append acknowledgement is handled on the next worker attempt by
        # the stable marker, never by assuming the original row number persisted.
        if required_row is None:
            # appendCells always starts at column A after the last populated
            # row. values.append can choose a separate metadata table to the
            # right or insert into historical gaps, shifting score/date rows.
            cells = [{"userEnteredValue": {"numberValue": value}} if isinstance(value, (int, float))
                     else {"userEnteredValue": {"stringValue": str(value)}} for value in expected]
            sheet.spreadsheet.batch_update({"requests": [{"appendCells": {
                "sheetId": sheet.id, "rows": [{"values": cells}], "fields": "userEnteredValue"}}]})
        else:
            if sheet.row_count < required_row:
                sheet.add_rows(required_row - sheet.row_count)
            actual = sheet.row_values(required_row, value_render_option="UNFORMATTED_VALUE")
            for index, value in enumerate(values):
                stored = actual[index] if index < len(actual) else ""
                if stored not in (None, "") and _cell(stored) != _cell(value):
                    raise HistoryNeedsReview("Date row already contains another game")
            for index in (marker_column - 1, revision_column - 1, hash_column - 1):
                if index < len(actual) and actual[index] not in (None, ""):
                    raise HistoryNeedsReview("Date row already contains other metadata")
            # Write only the date and metadata; preserve all intervening formulas.
            sheet.batch_update([
                {"range": f"A{required_row}:{rowcol_to_a1(required_row, len(values))}", "values": [list(values)]},
                {"range": f"{rowcol_to_a1(required_row, marker_column)}:{rowcol_to_a1(required_row, hash_column)}",
                 "values": [[match_id, 1, payload_hash]]},
            ], value_input_option="RAW")
        markers = sheet.col_values(marker_column)
        rows = [index + 1 for index, marker in enumerate(markers) if str(marker) == str(match_id)]
        if len(rows) != 1:
            if len(rows) > 1:
                raise HistoryNeedsReview("Duplicate history match markers")
            raise HistoryDeliveryUnknown("History append could not be verified")
    row_number = rows[0]
    actual = sheet.row_values(row_number, value_render_option="UNFORMATTED_VALUE")
    if len(actual) < marker_column or str(actual[marker_column - 1]) != str(match_id):
        raise HistoryDeliveryUnknown("History row moved during marker verification")
    # Legacy rows without revision metadata are accepted only after their actual
    # source values match. A stable ID alone is not proof of the current payload.
    for index, value in enumerate(values):
        stored = actual[index] if index < len(actual) else ""
        if _cell(stored) != _cell(value):
            raise HistoryNeedsReview("History match payload differs from frozen snapshot")
    old_revision = actual[revision_column - 1] if len(actual) >= revision_column else ""
    old_hash = actual[hash_column - 1] if len(actual) >= hash_column else ""
    if old_revision not in ("", 1, "1") or old_hash not in ("", payload_hash):
        raise HistoryNeedsReview("History revision metadata differs from frozen snapshot")
    if not old_revision or not old_hash:
        # This annotates only an already verified legacy row; scores are unchanged.
        sheet.update(range_name=f"{rowcol_to_a1(row_number, revision_column)}:{rowcol_to_a1(row_number, hash_column)}",
            values=[[1, payload_hash]], value_input_option="RAW")
        verified = sheet.row_values(row_number, value_render_option="UNFORMATTED_VALUE")
        if len(verified) < hash_column or str(verified[marker_column - 1]) != str(match_id) or str(verified[revision_column - 1]) != "1" or verified[hash_column - 1] != payload_hash:
            raise HistoryDeliveryUnknown("History metadata acknowledgement could not be verified")
    return {"match_id": match_id, "revision": 1, "payload_hash": payload_hash, "row": row_number}

