from copy import deepcopy
from types import SimpleNamespace

import gspread
import pytest

from mahjong_api.config import Settings
from mahjong_api.models import SEATS
from mahjong_api.sheets import CURRENT_HEADERS, HISTORY_HEADERS, GSpreadSheets


class Worksheet:
    def __init__(self):
        self.rows = {}
        self.row_count = 1
        self.col_count = 6
        self.calls = []
        self.lose_ack = False

    def row_values(self, row):
        return self.rows.get(row, [])

    def get_all_values(self):
        return list(self.rows.values())

    def add_rows(self, count):
        self.row_count += count

    def add_cols(self, count):
        self.col_count += count

    def update(self, *, range_name, values, value_input_option):
        assert value_input_option == "RAW"
        start = range_name.split(":")[0]
        self.rows[int(start[1:])] = deepcopy(values[0])
        self.calls.append((range_name, values))
        if self.lose_ack:
            self.lose_ack = False
            raise TimeoutError("lost acknowledgement")


def adapter():
    current, history = Worksheet(), Worksheet()
    sink = GSpreadSheets(Settings())
    sink._book = SimpleNamespace(worksheet=lambda title: current if title == "当前对局表" else history)
    return sink, current, history


def test_header_creation_overwrite_and_explicit_empty_cells():
    sink, current, _ = adapter()
    table = {"table_id": "1", "slot": 1, "updated_at": "2026-09-16T00:00:00Z", "seats": dict.fromkeys(SEATS)}
    table["seats"]["east"] = {"id": "u1", "name": "=SUM(A1:A2)"}
    sink.write_current(table)
    assert current.rows[1] == CURRENT_HEADERS
    assert current.rows[2][1] == "=SUM(A1:A2)"
    table["seats"]["east"] = None
    sink.write_current(table)
    assert current.rows[2][1:5] == ["", "", "", ""]
    assert len(current.rows) == 2


def test_history_retry_reuses_reserved_row_after_timeout():
    sink, _, history = adapter()
    history.rows[1] = HISTORY_HEADERS
    history.col_count = len(HISTORY_HEADERS)
    match = {
        "match_id": "match-1", "sequence": 1,
        "result": {"round": 1, "table": "1", "played_at": "now", "players": {
            seat: {"user": {"id": f"id-{seat}", "name": seat}, "initial_points": 25000, "final_points": 25000, "delta_points": 0, "net_score": 0}
            for seat in SEATS
        }},
    }
    history.lose_ack = True
    with pytest.raises(TimeoutError):
        sink.write_history(match)
    sink.write_history(match)
    assert len(history.rows) == 2
    assert history.rows[2][0] == "match-1"
    assert len(history.rows[2]) == len(HISTORY_HEADERS) == 34


def test_refuse_unrelated_existing_header():
    sink, current, _ = adapter()
    current.rows[1] = ["Existing club data"]
    with pytest.raises(ValueError, match="header mismatch"):
        sink._worksheet("当前对局表", CURRENT_HEADERS)
    assert not current.calls


def test_refuse_empty_header_above_existing_data():
    sink, current, _ = adapter()
    current.rows[2] = ["Existing club data"]
    with pytest.raises(ValueError, match="contains data"):
        sink._worksheet("当前对局表", CURRENT_HEADERS)
    assert not current.calls


def test_refuse_row_collision_after_manual_sort_or_database_loss():
    _, current, _ = adapter()
    current.rows[2] = ["another-table", "someone"]
    with pytest.raises(ValueError, match="another record"):
        GSpreadSheets._write_row(current, 2, ["1", "player", "", "", "", "now"])
    assert current.rows[2][1] == "someone"


def test_service_account_configuration(monkeypatch):
    calls = {}
    worksheet = Worksheet()

    def service_account(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            set_timeout=lambda timeout: calls.update(timeout=timeout),
            open_by_key=lambda key: SimpleNamespace(worksheet=lambda title: worksheet),
        )

    monkeypatch.setattr(gspread, "service_account", service_account)
    sink = GSpreadSheets(Settings(spreadsheet_id="test-id", credentials_file="test-key.json"))
    sink._worksheet("当前对局表", CURRENT_HEADERS)
    assert calls["filename"] == "test-key.json"
    assert calls["scopes"] == ["https://www.googleapis.com/auth/spreadsheets"]
    assert calls["timeout"] == 15


def test_upgrade_v1_history_adds_columns_without_moving_existing_data():
    from unittest.mock import Mock
    sheet = Mock()
    sheet.row_values.return_value = HISTORY_HEADERS[:28]
    sheet.col_count = 28
    sink = GSpreadSheets(Settings())
    sink._book = SimpleNamespace(worksheet=lambda title: sheet)
    sink._worksheet("历史对局记录表", HISTORY_HEADERS)
    sheet.add_cols.assert_called_once_with(6)
    sheet.update.assert_called_once_with(range_name="AC1:AH1", values=[HISTORY_HEADERS[28:]], value_input_option="RAW")
