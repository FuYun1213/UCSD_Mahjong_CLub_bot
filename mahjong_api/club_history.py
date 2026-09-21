"""Publish each NFC match once into the existing club database and worksheets.

The existing MMR/PT functions are reused so rankings and prior seasons retain
their rules. NFC MatchPlayer separately records the raw 25000-point difference.
"""
from contextlib import closing, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import re

import mahjong_store

from .models import SEATS


class ClubHistorySink:
    def __init__(self, nfc_sink, database_path):
        self.nfc_sink = nfc_sink
        self.database_path = database_path
        self.enabled = nfc_sink.enabled
        self.account_lookup = None
        self.account_path = None

    def write_current(self, table):
        self.nfc_sink.write_current(table)

    def _save_game(self, match):
        # A saved score may wait for retry while an administrator renames a
        # player. Resolve its stable account ID at the actual history write, and
        # hold the account lock through import so rename cannot race this lookup.
        # The API's immutable score snapshot and external delivery body stay intact.
        if self.account_path is not None:
            import registered_names
            guard = registered_names.account_lock(self.account_path)
        else:
            guard = nullcontext()
        with guard:
            projected = match
            if self.account_lookup is not None:
                names = {str(row["id"]): row["name"] for row in self.account_lookup()}
                projected = deepcopy(match)
                result = projected["result"]
                for player in result["players"].values():
                    current = names.get(str(player["user"]["id"]))
                    if current:
                        player["user"]["name"] = current
                current_uploader = names.get(str(result.get("uploader_id")))
                if current_uploader:
                    result["uploader_name"] = current_uploader
            return self._save_game_snapshot(projected)

    def _save_game_snapshot(self, match):
        result = match["result"]
        ordered = sorted(SEATS, key=lambda seat: (-result["players"][seat]["final_points"], SEATS.index(seat)))
        players = [result["players"][seat] for seat in ordered]
        stamp = datetime.fromisoformat(result["played_at"].replace("Z", "+00:00"))
        played_at = stamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        recorder = result.get("uploader_name") or next((p["user"]["name"] for p in players if str(p["user"]["id"]) == str(result.get("uploader_id"))), "NFC")
        with closing(mahjong_store.connect(self.database_path)) as db:
            # Lock BEFORE the idempotency lookup. The unique match ID and the
            # game's four player/MMR changes commit together inside import_game.
            db.execute("BEGIN IMMEDIATE")
            game_id = mahjong_store.import_game(
                db, [p["user"]["name"] for p in players], [p["final_points"] for p in players], played_at,
                source=result.get("source", "nfc"), created_by=recorder, quarter=mahjong_store.latest_quarter(db),
                seat_winds=ordered, source_seat_order="ESWN", nfc_match_id=match["match_id"],
                started_at=result.get("started_at"), ended_at=result.get("ended_at"), duration_seconds=result.get("duration_seconds"),
                authoritative_played_at=result.get("authoritative_played_at"), played_at_source=result.get("played_at_source"))
            row = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
            values = [p["user"]["name"] for p in players] + [p["final_points"] for p in players]
            values += mahjong_store.game_mmr_deltas(db, game_id) + mahjong_store.game_mmr_afters(db, game_id)
            values += ["✅ Calculated", row["quarter"] or ""]
            return game_id, row["played_at"], values

    @staticmethod
    def _append_once(sheet, match_id, values, marker_column):
        if sheet.col_count < marker_column:
            sheet.add_cols(marker_column - sheet.col_count)
        markers = sheet.col_values(marker_column)
        if markers and markers[0] not in ("", "NFC_Match_ID"):
            raise ValueError("Legacy worksheet marker column is already in use")
        # The marker travels IN THE SAME append request as the scores. If the
        # network loses the acknowledgement, the next attempt finds this UUID.
        if match_id in markers:
            return markers.index(match_id) + 1
        if not markers or not markers[0]:
            from gspread.utils import rowcol_to_a1
            sheet.update(range_name=rowcol_to_a1(1, marker_column), values=[["NFC_Match_ID"]], value_input_option="RAW")
        values = values + [""] * (marker_column - len(values) - 1) + [match_id]
        reply = sheet.append_row(values, value_input_option="RAW", insert_data_option="INSERT_ROWS")
        updated = reply.get("updates", {}).get("updatedRange", "")
        found = re.search(r"!A(\d+):", updated)
        if not found:
            raise RuntimeError("Append result was incomplete; retained for idempotent retry")
        return int(found.group(1))

    def write_history(self, match):
        game_id, played_at, values = self._save_game(match)
        self.nfc_sink.write_history(match)
        self._write_legacy(match, game_id, played_at, values)

    def write_manual_history(self, match):
        game_id, played_at, values = self._save_game(match)
        writer = getattr(self.nfc_sink, "write_manual_history", None)
        if writer:
            writer(match)
        elif self.enabled:
            raise RuntimeError("The configured history sink does not support manual scoring")
        self._write_legacy(match, game_id, played_at, values)

    def _write_legacy(self, match, game_id, played_at, values):
        if not self.enabled:
            return
        # GSpreadSheets opens the existing spreadsheet while writing its own
        # dedicated history tab. The legacy sheets remain in rank order.
        book = self.nfc_sink._book
        row = self._append_once(book.worksheet("Games Riichi"), match["match_id"], values, 44)
        self._append_once(book.worksheet("Games/pt"), match["match_id"], [played_at], 28)
        with closing(mahjong_store.connect(self.database_path)) as db:
            db.execute("UPDATE games SET sheet_row=?, sync_status='synced' WHERE id=?", (row, game_id))
            db.commit()
