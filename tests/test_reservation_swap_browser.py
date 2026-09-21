"""Consent UI, live reservation names/seats, and expiry on isolated databases."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import pytest

from sqlalchemy import select
import web_server
from test_web_score_bridge import website
from mahjong_api.table_models import ClubTable, ReservationParticipant, TableReservation
from mahjong_api.reservation_session_models import ReservationSession


@pytest.mark.skipif(os.getenv("NFC_BROWSER_TESTS") != "1", reason="Set NFC_BROWSER_TESTS=1 to run real browser integration")
def test_reservation_reminders_and_two_party_swap_browser(website, monkeypatch, tmp_path):
    url, app, _ = website
    accounts = json.loads(web_server.USERS_FILE.read_text(encoding="utf-8"))
    accounts["users"]["photo1"]["role"] = "admin"
    web_server.USERS_FILE.write_text(json.dumps(accounts), encoding="utf-8")
    monkeypatch.setattr(web_server, "sheet_player_names", lambda: [])
    monkeypatch.setattr(web_server, "build_dashboard", lambda *a, **kw: {"stats": {"member_count": 8}, "rankings": [], "recent_yakuman": []})
    clock_file = tmp_path / "browser-clock-offset.json"
    clock_file.write_text("0", encoding="utf-8")

    def clock():
        return (datetime.now(timezone.utc) + timedelta(seconds=json.loads(clock_file.read_text(encoding="utf-8")))).isoformat(timespec="milliseconds")

    monkeypatch.setattr(app.state.tables, "clock", clock)
    monkeypatch.setattr(app.state.seat_swaps, "clock", clock)
    current = datetime.now(timezone.utc)
    with app.state.service.store.connect() as db:
        table = db.scalar(select(ClubTable).where(ClubTable.score_table_id == "web"))
        for rid, minutes, people, status in [
            ("browser-near", -30, [2, 3], "active"),
            ("browser-next", 50, [3, 4], "active"),
            ("browser-later", 70, [5], "active"),
            ("browser-old", -70, [6], "active"),
            ("browser-cancelled", 0, [7], "cancelled"),
        ]:
            stamp = current.isoformat(timespec="milliseconds")
            start=(current + timedelta(minutes=minutes)).isoformat(timespec="milliseconds")
            end=(current + timedelta(minutes=minutes+60)).isoformat(timespec="milliseconds")
            db.add(ReservationSession(id=rid,table_id=table.id,scope=table.scope,start_at=start,end_at=end,status=status,created_at=stamp,updated_at=stamp))
            db.flush()
            db.add(TableReservation(id=rid, table_id=table.id, user_id="photo-user-1", user_name="photo1",session_id=rid,end_at=end,
                scheduled_at=(current + timedelta(minutes=minutes)).isoformat(timespec="milliseconds"),
                created_at=stamp, updated_at=stamp, status=status, version=1, note=""))
            db.flush()
            for number in people:
                db.add(ReservationParticipant(reservation_id=rid, user_id=f"photo-user-{number}",
                    user_name=f"old snapshot {number}", added_at=stamp))
    environment = os.environ.copy()
    environment.update(NFC_TEST_URL=url, SWAP_TEST_CLOCK=str(clock_file), SWAP_TEST_ACCOUNTS=str(web_server.USERS_FILE),
                       NODE_PATH=str(Path(".venv-api/browser-tests/node_modules").resolve()))
    result = subprocess.run(["node", "tests/browser_reservation_swap.cjs"], env=environment, capture_output=True,
                            text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
