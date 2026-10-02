"""Publish each NFC match once into the existing club database and worksheets.

The existing MMR/PT functions are reused so rankings and prior seasons retain
their rules. NFC MatchPlayer separately records the raw 25000-point difference.
"""
from contextlib import closing, nullcontext
from copy import deepcopy
from datetime import datetime, timezone

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
        from zoneinfo import ZoneInfo
        from competition_time import site_timezone
        summary_time = stamp.astimezone(ZoneInfo(site_timezone())).strftime("%Y-%m-%d %H:%M:%S")
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
                authoritative_played_at=result.get("authoritative_played_at"), played_at_source=result.get("played_at_source"),
                summary_time=summary_time)
            row = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
            values = [p["user"]["name"] for p in players] + [p["final_points"] for p in players]
            values += mahjong_store.game_mmr_deltas(db, game_id) + mahjong_store.game_mmr_afters(db, game_id)
            values += ["✅ Calculated", row["quarter"] or ""]
            import json
            summary = db.execute("SELECT payload_json FROM game_score_summaries WHERE game_id=?", (game_id,)).fetchone()
            recorded_time = json.loads(summary[0])["description"].removeprefix("**Time Recorded:** ") if summary else row["played_at"]
            return game_id, recorded_time, values

    @staticmethod
    def _append_once(sheet, match_id, values, marker_column):
        from .sheets import publish_marked_row
        from .history_delivery import digest
        return publish_marked_row(sheet, match_id, values, marker_column=marker_column,
            revision_column=marker_column + 1, payload_hash=digest(values))["row"]
    
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
        from .sheets import publish_marked_row
        from .history_delivery import digest
        publish_marked_row(book.worksheet("Games/pt"), match["match_id"], [played_at],
            marker_column=28, revision_column=29, payload_hash=digest([played_at]), required_row=row)
        with closing(mahjong_store.connect(self.database_path)) as db:
            db.execute("UPDATE games SET sheet_row=?, sync_status='synced' WHERE id=?", (row, game_id))
            db.commit()

    def history_targets(self, match):
        from pathlib import Path
        targets = [{"channel": "club", "kind": "projection", "target": {
            "adapter": "club", "database_path": str(Path(self.database_path).resolve()),
        }}]
        if not self.enabled:
            return targets
        factory = getattr(self.nfc_sink, "history_targets", None)
        if factory:
            targets.extend(factory(match))
        else:
            targets.append({"channel": "nfc_history", "target": {"adapter": "club_compat_history",
                "manual": match["result"].get("table") is None}})
        settings = getattr(self.nfc_sink, "settings", None)
        spreadsheet_id = settings.spreadsheet_id if settings else ""
        for channel, title, marker in (("games_riichi", "Games Riichi", 44), ("games_pt", "Games/pt", 28)):
            target = {"adapter": "legacy_sheet", "spreadsheet_id": spreadsheet_id,
                "worksheet": title, "marker_column": marker}
            if channel == "games_pt":
                target["requires_channel"] = "games_riichi"
            targets.append({"channel": channel, "target": target, "depends_on": "club"})
        return targets

    def deliver_history(self, target, match, *, reconcile=False):
        from .history_delivery import HistoryDeliveryUnknown, HistoryNeedsReview, digest
        if target["adapter"] == "club":
            # Local projection can briefly take the account guard, but never has
            # member lock or any remote operation nested inside that guard.
            from pathlib import Path
            projector = self
            if Path(target["database_path"]).resolve() != Path(self.database_path).resolve():
                projector = ClubHistorySink(self.nfc_sink, target["database_path"])
                projector.account_lookup, projector.account_path = self.account_lookup, self.account_path
            game_id, played_at, values = projector._save_game(match)
            return {"game_id": game_id, "played_at": played_at, "values": values,
                    "database_path": target["database_path"], "match_id": match["match_id"], "revision": 1}
        if target["adapter"] == "gspread_history":
            return self.nfc_sink.deliver_history(target, match, reconcile=reconcile)
        if target["adapter"] == "club_compat_history":
            if reconcile:
                probe = getattr(self.nfc_sink, "reconcile_manual_history" if target.get("manual") else "reconcile_history", None)
                outcome = probe(match) if probe else None
                if outcome == "matched":
                    return {"match_id": match["match_id"], "revision": 1}
                if outcome != "absent":
                    raise HistoryDeliveryUnknown("Compatibility sink cannot reconcile")
            writer = getattr(self.nfc_sink, "write_manual_history", None) if target.get("manual") else self.nfc_sink.write_history
            if writer is None:
                raise HistoryNeedsReview("History sink does not support manual scores")
            writer(match)
            return {"match_id": match["match_id"], "revision": 1}
        if target["adapter"] != "legacy_sheet":
            raise HistoryNeedsReview("Unknown frozen history adapter")
        from .sheets import publish_marked_row
        projected = match.get("projection")
        if not projected:
            raise HistoryNeedsReview("Club projection must complete before legacy worksheet delivery")
        sink = self.nfc_sink._target_sink(target) if hasattr(self.nfc_sink, "_target_sink") else self.nfc_sink
        book = sink.open_book() if hasattr(sink, "open_book") else sink._book
        values = projected["values"] if target["worksheet"] == "Games Riichi" else [projected["played_at"]]
        required_row = None
        if target["worksheet"] == "Games/pt":
            with closing(mahjong_store.connect(projected["database_path"])) as db:
                row = db.execute("SELECT sheet_row FROM games WHERE id=? AND nfc_match_id=?",
                    (projected["game_id"], match["match_id"])).fetchone()
                required_row = row[0] if row else None
            if required_row is None:
                raise HistoryDeliveryUnknown("Score row must be acknowledged before its date is written")
        result = publish_marked_row(book.worksheet(target["worksheet"]), match["match_id"], values,
            marker_column=target["marker_column"], revision_column=target["marker_column"] + 1,
            payload_hash=digest(values), required_row=required_row)
        if target["worksheet"] == "Games Riichi":
            with closing(mahjong_store.connect(projected["database_path"])) as db:
                db.execute("UPDATE games SET sheet_row=? WHERE id=? AND nfc_match_id=?",
                    (result["row"], projected["game_id"], match["match_id"]))
                db.commit()
        return result


    def complete_history(self, projection, *, had_external_targets):
        """Idempotent local compatibility status after all channel acknowledgements."""
        with closing(mahjong_store.connect(projection["database_path"])) as db:
            db.execute("UPDATE games SET sync_status=? WHERE id=? AND nfc_match_id=?",
                ("synced" if had_external_targets else "disabled", projection["game_id"], projection["match_id"]))
            db.commit()
