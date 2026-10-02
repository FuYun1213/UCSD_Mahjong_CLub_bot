from contextlib import closing
from dataclasses import replace

from fastapi.testclient import TestClient

import mahjong_store
from mahjong_api.main import create_app
from test_mahjong_api import FakeSheets, fill, settings
from test_mahjong_v2 import relative


class LegacySheet:
    col_count = 50

    def __init__(self):
        self.rows = [["old header"], ["existing historic game"]]
        self.lose_ack = False

    def col_values(self, column, **kwargs):
        return [row[column - 1] if len(row) >= column else "" for row in self.rows]

    def row_values(self, row, **kwargs):
        return list(self.rows[row - 1]) if row <= len(self.rows) else []

    def update(self, range_name, values, value_input_option):
        from gspread.utils import a1_to_rowcol
        first_row, first_column = a1_to_rowcol(range_name.split(":", 1)[0])
        for offset, incoming in enumerate(values):
            index = first_row - 1 + offset
            while len(self.rows) <= index:
                self.rows.append([])
            row = self.rows[index]
            row.extend([""] * max(0, first_column - 1 + len(incoming) - len(row)))
            row[first_column - 1:first_column - 1 + len(incoming)] = incoming

    def append_row(self, values, **kwargs):
        self.rows.append(values)
        if self.lose_ack:
            self.lose_ack = False
            raise TimeoutError("Google stored the row but the response was lost")
        return {"updates": {"updatedRange": f"'Legacy'!A{len(self.rows)}:AR{len(self.rows)}"}}


class IntegratedSheets(FakeSheets):
    def __init__(self):
        super().__init__()
        self.legacy = {"Games Riichi": LegacySheet(), "Games/pt": LegacySheet()}
        self._book = self

    def worksheet(self, title):
        return self.legacy[title]


def test_new_scoring_updates_original_rankings_once_after_lost_ack(settings, tmp_path):
    club = tmp_path / "club.sqlite3"
    sink = IntegratedSheets()
    sink.legacy["Games Riichi"].lose_ack = True
    app = create_app(replace(settings, club_database_path=str(club)), sink)
    with TestClient(app) as client:
        match_id = fill(client)
        response = relative(client, match_id=match_id, key="club-1")
        assert response.status_code == 202
        assert response.json()["local_saved"] and response.json()["local_completed"]
        assert response.json()["result"]["duration_seconds"] is None
        assert not any(app.state.service.table("1")["seats"].values())
        assert sink.history_calls == [] and sink.current_calls == 0
        assert len(sink.legacy["Games Riichi"].rows) == len(sink.legacy["Games/pt"].rows) == 2
        with closing(mahjong_store.connect(club)) as db:
            assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
        # Only explicit background work materializes the club projection and
        # historical worksheets. The lost ACK must not replay successful targets.
        app.state.service.flush()
        states = {row["channel"]:row["status"] for row in app.state.service.history.status(match_id)["channels"]}
        assert states == {"club":"succeeded", "nfc_history":"succeeded",
                          "games_riichi":"delivery_unknown", "games_pt":"succeeded"}
        with closing(mahjong_store.connect(club)) as db:
            assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
            assert [row[0] for row in db.execute("SELECT games_played FROM players")] == [1] * 4
            points = {row["seat_wind"]: row["final_score"] for row in db.execute("SELECT seat_wind,final_score FROM game_players")}
            assert points == {"east": 35000, "south": 20000, "west": 15000, "north": 30000}
            assert db.execute("SELECT duration_seconds FROM games").fetchone()[0] is None
            assert db.execute("SELECT sync_status FROM games").fetchone()[0] != "synced"
        again = relative(client, match_id=match_id, key="club-1")
        assert again.status_code == 202 and again.json()["replayed"]
        assert again.json()["result"] == response.json()["result"]
        app.state.service.history.retry(match_id)
        app.state.service.flush()
        synced = relative(client, match_id=match_id, key="club-1")
        assert synced.status_code == 200 and synced.json()["history_sync"]["status"] == "synced"
        assert not any(app.state.service.table("1")["seats"].values())
        with closing(mahjong_store.connect(club)) as db:
            assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
            assert db.execute("SELECT sync_status FROM games").fetchone()[0] == "synced"
            assert [row[0] for row in db.execute("SELECT games_played FROM players")] == [1] * 4
        assert len(sink.legacy["Games Riichi"].rows) == 3
        assert len(sink.legacy["Games/pt"].rows) == 3
        assert sink.legacy["Games Riichi"].rows[1] == ["existing historic game"]
        assert len(sink.history) == 1 and sink.history_calls == [match_id]
        assert sink.current_calls == 0

