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

    def col_values(self, column):
        return [row[column - 1] if len(row) >= column else "" for row in self.rows]

    def update(self, range_name, values, value_input_option):
        self.rows[0] += [""] * (50 - len(self.rows[0]))
        self.rows[0][43 if range_name == "AR1" else 27] = values[0][0]

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
        with closing(mahjong_store.connect(club)) as db:
            assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
            assert [row[0] for row in db.execute("SELECT games_played FROM players")] == [1] * 4
            points = {row["seat_wind"]: row["final_score"] for row in db.execute("SELECT seat_wind,final_score FROM game_players")}
            assert points == {"east": 35000, "south": 20000, "west": 15000, "north": 30000}
            assert db.execute("SELECT duration_seconds FROM games").fetchone()[0] is not None
        assert all(app.state.service.table("1")["seats"].values())
        again = relative(client, match_id=match_id, key="club-1")
        assert again.status_code == 200
        assert not any(app.state.service.table("1")["seats"].values())
        with closing(mahjong_store.connect(club)) as db:
            assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
            assert db.execute("SELECT sync_status FROM games").fetchone()[0] == "synced"
            assert [row[0] for row in db.execute("SELECT games_played FROM players")] == [1] * 4
        assert len(sink.legacy["Games Riichi"].rows) == 3
        assert len(sink.legacy["Games/pt"].rows) == 3
        assert sink.legacy["Games Riichi"].rows[1] == ["existing historic game"]
        assert len(sink.history) == 1
