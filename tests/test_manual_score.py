"""Manual entry uses real transactions, accounts, and the existing club history."""
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import mahjong_store
from mahjong_api.config import Settings
from mahjong_api.database_models import MatchHistory, ScoreDraft, TableState
from mahjong_api.main import create_app
from mahjong_api.manual_score_models import ManualScoreDraft, ManualScorePlayer, ManualScoreRequest
from mahjong_api.models import SEATS, User
from mahjong_api.sheets import DisabledSheets
from mahjong_api.store import Conflict, Store
from mahjong_api.table_models import ActiveTableMember
from mahjong_api.tournament_models import TournamentAudit

ADMIN = User(id="admin", name="Admin", role="admin")
CURRENT = User(id="u1", name="Player 1")
AUTH = {"Authorization": "Bearer demo-1"}
POINTS = dict(zip(SEATS, (35000, 20000, 15000, 30000)))
PLAYERS = dict(zip(SEATS, ("u1", "u2", "u3", "u4")))


class NoVision:
    def recognize(self, *args):
        raise AssertionError("Manual entry must not call photo recognition")


@pytest.fixture
def manual(tmp_path, monkeypatch):
    monkeypatch.delenv("TABLE_TOKEN_SECRET_FILE", raising=False)
    club = tmp_path / "club.sqlite3"
    app = create_app(Settings(database_path=tmp_path / "api.sqlite3", club_database_path=str(club),
                              mock_auth_enabled=True, sync_interval_seconds=3600), DisabledSheets(), NoVision())
    with TestClient(app) as client:
        accounts = [{"id": "u" + str(i), "name": "Player " + str(i), "disabled": False} for i in range(1, 6)]
        accounts.append({"id": "disabled", "name": "Disabled", "disabled": True})
        app.state.tables.account_lookup = lambda ids: accounts
        yield client, app, club, accounts


def preview(client, **changes):
    data = {"players": dict(PLAYERS), "scores": dict(POINTS), **changes}
    return client.post("/api/manual-score/preview", json=data, headers=AUTH)


def confirm(client, draft, key=None):
    return client.post("/api/manual-score/confirm", json={"draft_id": draft["draft_id"],
                      "request_id": key or str(uuid4())}, headers=AUTH)


def test_generic_preview_confirm_existing_history_no_photo_no_round(manual):
    client, app, club, _ = manual
    context = client.get("/api/manual-score/context", headers=AUTH).json()
    assert context["players"] == dict.fromkeys(SEATS) and context["table_id"] is None
    assert context["score_rules"]["step"] == 100
    draft = preview(client, players={s: " " + uid + " " for s, uid in PLAYERS.items()}).json()
    assert draft["status"] == "needs_confirmation"
    assert draft["players"]["east"]["id"] == "u1"
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ManualScorePlayer)) == 0
        assert db.scalar(select(func.count()).select_from(TableState)) == 0
    response = confirm(client, draft)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["table"] is None and result["round"] is None
    assert result["uploader_id"] == "u1"
    assert {s: p["user"]["id"] for s, p in result["players"].items()} == PLAYERS
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ScoreDraft)) == 0
        assert db.scalar(select(func.count()).select_from(TableState)) == 0
        assert db.scalar(select(func.count()).select_from(MatchHistory)) == 0
        assert {p.seat: p.user_id for p in db.scalars(select(ManualScorePlayer))} == PLAYERS
        audit = db.scalar(select(TournamentAudit).where(TournamentAudit.action == "manual_score_submitted"))
        assert audit.actor_id == "u1"
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
        assert db.execute("SELECT source,created_by FROM games").fetchone()[:] == ("manual", "Player 1")
        assert {p["seat_wind"]: p["final_score"] for p in db.execute("SELECT * FROM game_players")} == POINTS


@pytest.mark.parametrize("seat,value,code", [("east", "unknown", "account_not_found"),
    ("west", "disabled", "account_disabled"), ("north", " u1 ", "duplicate_player_ids"), ("north", "U1", "account_not_found"),
    ("south", "", "invalid_player_ids")])
def test_account_field_validation(manual, seat, value, code):
    client, _, _, _ = manual
    players = {**PLAYERS, seat: value}
    response = preview(client, players=players)
    assert response.status_code == 422
    assert response.json()["detail"]["field_errors"]["players." + seat] == code


@pytest.mark.parametrize("value", [True, 12.5, "35000", 35001, 10000100, None])
def test_invalid_scores_reuse_existing_precision(manual, value):
    response = preview(manual[0], scores={**POINTS, "east": value})
    assert response.status_code == 422
    assert response.json()["detail"]["field_errors"]["scores.east"] == "invalid_score"


def test_existing_total_rule_and_negative_scores(manual):
    client = manual[0]
    response = preview(client, scores={s: 100 for s in SEATS})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "invalid_score_total"
    response = preview(client, scores=dict(zip(SEATS, (70000, 20000, 15000, -5000))))
    assert response.status_code == 200


def test_lookup_seated_enabled_accounts_exact_identity_and_dedupe(manual):
    client, app, _, _ = manual
    table = app.state.tables.create({"request_id": "table", "number": 3}, ADMIN)
    app.state.tables.join(table["id"], CURRENT, "east")
    search = client.get("/api/player-lookup?q=player", headers=AUTH).json()
    assert "u1" in {p["id"] for p in search["players"]}
    assert "disabled" not in {p["id"] for p in search["players"]}
    lookup = client.post("/api/player-lookup", json={"user_ids": " u1, u1\nu2 "}, headers=AUTH)
    assert lookup.status_code == 200, lookup.text
    assert [p["id"] for p in lookup.json()["players"]] == ["u1", "u2"]
    assert set(lookup.json()["players"][0]) == {"id", "name", "avatar"}


def test_confirmation_revalidates_users_and_keeps_draft(manual):
    client, app, _, accounts = manual
    draft = preview(client).json()
    accounts[2]["disabled"] = True
    response = confirm(client, draft)
    assert response.status_code == 422
    assert response.json()["detail"]["field_errors"]["players.west"] == "account_disabled"
    again = client.get("/api/manual-score/drafts/" + draft["draft_id"], headers=AUTH).json()
    assert again["status"] == "needs_confirmation" and again["scores"] == POINTS
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ManualScoreRequest)) == 0


def test_table_prefill_empty_positions_association_and_permissions(manual):
    client, app, _, _ = manual
    table = app.state.tables.create({"request_id": "table", "number": 3}, ADMIN)
    denied = preview(client, table_id=table["id"])
    assert denied.status_code == 403
    app.state.tables.join(table["id"], CURRENT, "east")
    context = client.get("/api/manual-score/context", params={"table": table["id"]}, headers=AUTH).json()
    assert context["players"]["east"]["id"] == "u1" and context["players"]["north"] is None
    mismatched = {**PLAYERS, "east": "u2", "south": "u1"}
    assert preview(client, table_id=table["id"], players=mismatched).status_code == 422
    draft = preview(client, table_id=table["id"]).json()
    response = confirm(client, draft)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["table"] == table["score_table_id"]
    assert response.json()["result"]["match_id"] == context["match_id"]
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(MatchHistory)) == 1
        assert db.scalar(select(func.count()).select_from(ActiveTableMember)) == 0
    assert confirm(client, draft).json()["replayed"]


def test_roster_changes_after_preview_are_rejected(manual):
    client, app, _, _ = manual
    table = app.state.tables.create({"request_id": "table", "number": 3}, ADMIN)
    app.state.tables.join(table["id"], CURRENT, "east")
    draft = preview(client, table_id=table["id"]).json()
    app.state.tables.join(table["id"], User(id="u2", name="Player 2"), "south")
    response = confirm(client, draft)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "stale_roster"


def test_parallel_confirmation_idempotency_and_request_collision(manual):
    client, app, club, _ = manual
    draft = preview(client).json()
    data = {"draft_id": draft["draft_id"], "request_id": "same-request"}
    with ThreadPoolExecutor(4) as pool:
        replies = list(pool.map(lambda _: app.state.manual_scores.confirm(data, CURRENT), range(4)))
    assert sum(not body["replayed"] for body, _ in replies) == 1
    assert len({body["result"]["match_id"] for body, _ in replies}) == 1
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ManualScorePlayer)) == 4
        assert db.scalar(select(func.count()).select_from(TournamentAudit).where(TournamentAudit.action == "manual_score_submitted")) == 1
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
    another = preview(client).json()
    assert confirm(client, another, "same-request").status_code == 409


def test_other_user_cannot_confirm_or_view_draft(manual):
    client = manual[0]
    draft = preview(client).json()
    headers = {"Authorization": "Bearer demo-2"}
    assert client.get("/api/manual-score/drafts/" + draft["draft_id"], headers=headers).status_code == 403
    assert client.post("/api/manual-score/confirm", json={"draft_id": draft["draft_id"],
                        "request_id": "stolen"}, headers=headers).status_code == 403
    assert client.post("/api/manual-score/preview", json={"players": PLAYERS, "scores": POINTS}).status_code == 401


def test_additive_migration_is_repeatable(manual):
    client, app, _, _ = manual
    draft = preview(client).json()
    reopened = Store(app.state.service.store.path)
    with reopened.connect() as db:
        assert db.scalar(select(ManualScoreDraft.id)) == draft["draft_id"]
    reopened.close()


def _confirm_in_process(args):
    """Separate interpreters have independent Python locks and connection pools."""
    from mahjong_api.club_history import ClubHistorySink
    from mahjong_api.manual_score import ManualScoreService
    from mahjong_api.service import MatchService
    from mahjong_api.table_service import TableService
    from mahjong_api.tournament import TournamentService
    database, club, payload = args
    settings = Settings(database_path=Path(database), club_database_path=club)
    store = Store(settings.database_path)
    try:
        matches = MatchService(store, ClubHistorySink(DisabledSheets(), club), settings)
        tables = TableService(matches, TournamentService(store, matches.external))
        tables.account_lookup = lambda ids: [{"id": "u" + str(i), "name": "Player " + str(i)} for i in range(1, 5)]
        service = ManualScoreService(matches, tables)
        return service.confirm(payload, CURRENT)
    finally:
        store.close()


def test_separate_processes_confirm_one_generic_game(manual):
    client, app, club, _ = manual
    draft = preview(client).json()
    args = (str(app.state.service.store.path), str(club),
            {"draft_id": draft["draft_id"], "request_id": "across-processes"})
    with ProcessPoolExecutor(2) as pool:
        replies = list(pool.map(_confirm_in_process, [args, args]))
    assert sum(not body["replayed"] for body, _ in replies) == 1
    assert all(status == 200 for _, status in replies)
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
        assert [row[0] for row in db.execute("SELECT games_played FROM players")] == [1] * 4


def test_generic_history_lost_ack_retries_without_duplicate_game(manual, monkeypatch):
    client, app, club, _ = manual
    draft = preview(client).json()
    sink = app.state.service.sheets
    original = sink.write_manual_history
    failed = False

    def lost_ack(match):
        nonlocal failed
        original(match)
        if not failed:
            failed = True
            raise TimeoutError("Saved but acknowledgment lost")

    monkeypatch.setattr(sink, "write_manual_history", lost_ack)
    response = confirm(client, draft, "retry")
    assert response.status_code == 202 and response.json()["local_saved"]
    response = confirm(client, draft, "retry")
    assert response.status_code == 200 and response.json()["replayed"]
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1


def test_external_generic_round_is_null_and_cumulative_includes_each_game_once(manual):
    import json
    from mahjong_api.tournament_models import ExternalDelivery
    client, app, _, _ = manual
    first = preview(client).json()
    first_result = confirm(client, first).json()["result"]
    second = preview(client).json()
    second_result = confirm(client, second).json()["result"]
    with app.state.service.store.connect() as db:
        first_delivery = json.loads(db.get(ExternalDelivery, "nfc-" + first_result["match_id"]).canonical_json)
        second_delivery = json.loads(db.get(ExternalDelivery, "nfc-" + second_result["match_id"]).canonical_json)
        assert first_delivery["roundId"] is None and first_delivery["tableNumber"] is None
        assert {p["id"]: p["cumulativeScore"] for p in first_delivery["players"]} == dict(zip(PLAYERS.values(), (10, -5, -10, 5)))
        assert {p["id"]: p["cumulativeScore"] for p in second_delivery["players"]} == dict(zip(PLAYERS.values(), (20, -10, -20, 10)))
    table = app.state.tables.create({"request_id": "with-table", "number": 4}, ADMIN)
    app.state.tables.join(table["id"], CURRENT, "east")
    linked = preview(client, table_id=table["id"]).json()
    linked_result = confirm(client, linked).json()["result"]
    assert confirm(client, linked).json()["replayed"]
    with app.state.service.store.connect() as db:
        delivery = json.loads(db.get(ExternalDelivery, "nfc-" + linked_result["match_id"]).canonical_json)
        assert delivery["roundId"] == "1"
        assert {p["id"]: p["cumulativeScore"] for p in delivery["players"]} == dict(zip(PLAYERS.values(), (30, -15, -30, 15)))
    after_linked = preview(client).json()
    result = confirm(client, after_linked).json()["result"]
    with app.state.service.store.connect() as db:
        delivery = json.loads(db.get(ExternalDelivery, "nfc-" + result["match_id"]).canonical_json)
        assert {p["id"]: p["cumulativeScore"] for p in delivery["players"]} == dict(zip(PLAYERS.values(), (40, -20, -40, 20)))

def upload(client, key="upload-once", **changes):
    return client.post("/api/manual-score/upload", json={"request_id": key, "players": dict(PLAYERS),
                       "scores": dict(POINTS), **changes}, headers=AUTH)


def test_upload_one_action_validates_and_saves_without_photo(manual):
    client, app, club, _ = manual
    invalid = upload(client, scores={s: 100 for s in SEATS})
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["score_totals"] == {"current": 400, "expected": 100000, "difference": -99600}
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ManualScoreDraft)) == 0
    response = upload(client)
    assert response.status_code == 200 and response.json()["local_saved"]
    assert upload(client).json()["replayed"]
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ManualScoreDraft)) == 1
        assert db.scalar(select(func.count()).select_from(ManualScoreRequest)) == 1
        assert db.scalar(select(func.count()).select_from(ScoreDraft)) == 0
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1


def test_upload_request_payload_is_immutable(manual):
    client, app, _, _ = manual
    first = upload(client).json()
    changed = {**POINTS, "east": 30000, "north": 35000}
    response = upload(client, scores=changed)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "submission_conflict"
    assert upload(client, players={**PLAYERS, "east": "u2", "south": "u1"}).status_code == 409
    assert upload(client, scores={**POINTS, "east": "35000"}).status_code == 409
    # A separate login cannot claim the global request key.
    response = client.post("/api/manual-score/upload", json={"request_id": "upload-once", "players": PLAYERS,
        "scores": POINTS}, headers={"Authorization": "Bearer demo-2"})
    assert response.status_code == 409
    assert upload(client).json()["result"]["match_id"] == first["result"]["match_id"]


def test_parallel_uploads_reuse_one_draft_and_game(manual):
    _, app, club, _ = manual
    payload = {"request_id": "parallel-upload", "players": PLAYERS, "scores": POINTS}
    with ThreadPoolExecutor(4) as pool:
        replies = list(pool.map(lambda _: app.state.manual_scores.upload(payload, CURRENT), range(4)))
    assert sum(not body["replayed"] for body, _ in replies) == 1
    assert len({body["draft_id"] for body, _ in replies}) == 1
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ManualScoreDraft)) == 1
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1


def _upload_in_process(args):
    from mahjong_api.club_history import ClubHistorySink
    from mahjong_api.manual_score import ManualScoreService
    from mahjong_api.service import MatchService
    from mahjong_api.table_service import TableService
    from mahjong_api.tournament import TournamentService
    database, club, payload = args
    settings = Settings(database_path=Path(database), club_database_path=club)
    store = Store(settings.database_path)
    try:
        matches = MatchService(store, ClubHistorySink(DisabledSheets(), club), settings)
        tables = TableService(matches, TournamentService(store, matches.external))
        tables.account_lookup = lambda ids: [{"id": "u" + str(i), "name": "Player " + str(i)} for i in range(1, 5)]
        return ManualScoreService(matches, tables).upload(payload, CURRENT)
    finally:
        store.close()


def test_processes_upload_same_key_once(manual):
    _, app, club, _ = manual
    args = (str(app.state.service.store.path), str(club),
            {"request_id": "process-upload", "players": PLAYERS, "scores": POINTS})
    with ProcessPoolExecutor(2) as pool:
        replies = list(pool.map(_upload_in_process, [args, args]))
    assert sum(not body["replayed"] for body, _ in replies) == 1
    assert len({body["draft_id"] for body, _ in replies}) == 1
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
        assert [row[0] for row in db.execute("SELECT games_played FROM players")] == [1] * 4


def test_upload_resume_after_draft_saved_before_confirmation(manual, monkeypatch):
    client, app, _, _ = manual
    original = app.state.manual_scores.confirm
    def interrupted(*args):
        raise TimeoutError("connection dropped")
    monkeypatch.setattr(app.state.manual_scores, "confirm", interrupted)
    with pytest.raises(TimeoutError):
        app.state.manual_scores.upload({"request_id": "interrupted", "players": PLAYERS, "scores": POINTS}, CURRENT)
    monkeypatch.setattr(app.state.manual_scores, "confirm", original)
    response = upload(client, key="interrupted")
    assert response.status_code == 200
    with app.state.service.store.connect() as db:
        assert db.scalar(select(func.count()).select_from(ManualScoreDraft)) == 1
        assert db.scalar(select(func.count()).select_from(ManualScorePlayer)) == 4


def test_nondefault_total_rule_comes_from_existing_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("TABLE_TOKEN_SECRET_FILE", raising=False)
    app = create_app(Settings(database_path=tmp_path / "custom.sqlite3", club_database_path=str(tmp_path / "club.sqlite3"),
        initial_points=30000, mock_auth_enabled=True, sync_interval_seconds=3600), DisabledSheets(), NoVision())
    with TestClient(app) as client:
        app.state.tables.account_lookup = lambda ids: [{"id": "u" + str(i), "name": "Player " + str(i)} for i in range(1, 5)]
        assert client.get("/api/manual-score/context", headers=AUTH).json()["score_rules"]["expected_total"] == 120000
        assert upload(client).status_code == 422
        response = upload(client, scores={s: 30000 for s in SEATS})
        assert response.status_code == 200 and response.json()["local_saved"]


def test_external_failure_preserves_local_score_and_retry_same_delivery(manual):
    import requests
    client, app, club, _ = manual
    external = app.state.service.external
    external.save_config({"enabled": True, "adapter": "json", "endpoint": "https://example.com/scores"}, "admin")
    calls = []
    def transport(endpoint, adapter, payload, method):
        calls.append(payload)
        if len(calls) == 1:
            raise requests.Timeout("Provider saved it but the acknowledgement was lost")
        return 200, {"ok": True}
    external.transport = transport
    response = upload(client).json()
    assert response["local_saved"] and response["external_sync"]["status"] == "failed"
    draft_id = response["draft_id"]
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
    assert client.post("/api/manual-score/drafts/" + draft_id + "/retry", headers={"Authorization": "Bearer demo-2"}, json={}).status_code == 403
    retry = client.post("/api/manual-score/drafts/" + draft_id + "/retry", headers=AUTH, json={}).json()
    assert retry["local_saved"] and retry["external_sync"]["status"] == "success"
    assert calls[0] == calls[1] and calls[0]["requestId"] == response["external_sync"]["request_id"]
    assert upload(client).json()["replayed"] and len(calls) == 2
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1


def test_background_retries_transient_manual_failure_after_backoff(manual):
    from datetime import datetime, timezone, timedelta
    from mahjong_api.tournament_models import ExternalDelivery
    client, app, _, _ = manual
    external = app.state.service.external
    external.save_config({"enabled": True, "adapter": "json", "endpoint": "https://example.com/scores"}, "admin")
    calls = []
    def transport(endpoint, adapter, payload, method):
        calls.append(payload)
        return (503, {}) if len(calls) == 1 else (200, {"ok": True})
    external.transport = transport
    first = upload(client).json()
    app.state.manual_scores.flush()
    assert len(calls) == 1
    with app.state.service.store.connect() as db:
        delivery = db.get(ExternalDelivery, first["external_sync"]["request_id"])
        delivery.updated_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    app.state.manual_scores.flush()
    assert len(calls) == 2 and calls[0] == calls[1]
    assert external.get(first["external_sync"]["request_id"])["status"] == "success"


def test_pending_history_uses_current_registered_name_without_changing_delivery(manual, tmp_path, monkeypatch):
    import json
    import registered_names
    import web_server
    from mahjong_api.tournament_models import ExternalDelivery
    client, app, club, accounts = manual
    account_file = tmp_path / "rename-accounts.json"
    data = {"users": {p["name"].lower(): {"name": p["name"], "account_id": p["id"], "role": "user"}
                       for p in accounts if not p.get("disabled")}}
    data["users"]["admin"] = {"name": "Admin", "account_id": "admin", "role": "admin"}
    account_file.write_text(json.dumps(data), encoding="utf-8")
    registered_names.ensure_directory(account_file)
    monkeypatch.setattr(web_server, "USERS_FILE", account_file)
    monkeypatch.setattr(web_server, "MAHJONG_DB_FILE", club)
    monkeypatch.setattr(web_server, "LIVE_DB_FILE", tmp_path / "live.sqlite3")
    monkeypatch.setattr(web_server, "record_action", lambda **kw: kw)
    with closing(mahjong_store.connect(club)) as db:
        original_player = mahjong_store.upsert_player(db, "Player 1")["id"]
    sink = app.state.service.sheets
    sink.account_lookup = lambda: registered_names.account_rows(account_file)
    sink.account_path = account_file
    original_writer = sink.write_manual_history
    def fail_before_history(match):
        raise TimeoutError("history database unavailable")
    monkeypatch.setattr(sink, "write_manual_history", fail_before_history)
    first = upload(client, key="rename-before-history-retry").json()
    assert first["local_saved"] and first["status"] == "pending"
    with app.state.service.store.connect() as db:
        delivery_before = db.get(ExternalDelivery, first["external_sync"]["request_id"]).payload_json
    web_server.admin_registered_name({"user_id": "u1", "expected_name": "Player 1", "new_name": "Renamed Player",
                                      "confirm": True}, "Admin")
    monkeypatch.setattr(sink, "write_manual_history", original_writer)
    app.state.manual_scores.flush()
    with closing(mahjong_store.connect(club)) as db:
        assert db.execute("SELECT id FROM players WHERE name='Renamed Player'").fetchone()[0] == original_player
        assert db.execute("SELECT COUNT(*) FROM players WHERE name='Player 1'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM game_players WHERE player_id=?", (original_player,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
    with app.state.service.store.connect() as db:
        draft = db.scalar(select(ManualScoreDraft).where(ManualScoreDraft.id == first["draft_id"]))
        assert json.loads(draft.result_json)["players"]["east"]["user"]["name"] == "Player 1"
        assert db.get(ExternalDelivery, first["external_sync"]["request_id"]).payload_json == delivery_before


def test_case_distinct_opaque_ids_remain_distinct_for_manual_upload(manual):
    client, app, _, accounts = manual
    accounts.append({"id": "U1", "name": "Distinct Registered Player", "disabled": False})
    players = {**PLAYERS, "south": "U1"}
    lookup = client.post("/api/player-lookup", json={"user_ids": ["u1", "U1"]}, headers=AUTH)
    assert [p["id"] for p in lookup.json()["players"]] == ["u1", "U1"]
    response = upload(client, key="case-distinct", players=players)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["players"]["east"]["user"]["id"] == "u1"
    assert response.json()["result"]["players"]["south"]["user"]["id"] == "U1"
    swapped = {**players, "east": "U1", "south": "u1"}
    assert upload(client, key="case-distinct", players=swapped).status_code == 409
    with app.state.service.store.connect() as db:
        assert {p.user_id for p in db.scalars(select(ManualScorePlayer))} == set(players.values())


def test_application_lifespan_wires_current_names_for_pending_history(tmp_path, monkeypatch):
    import json
    import registered_names
    import web_server
    from mahjong_api.tournament_models import ExternalDelivery
    account_file, club = tmp_path / "accounts.json", tmp_path / "club.sqlite3"
    data = {"users": {"player " + str(i): {"name": "Player " + str(i), "account_id": "u" + str(i), "role": "user"}
                       for i in range(1, 5)}}
    data["users"]["admin"] = {"name": "Admin", "account_id": "admin", "role": "admin"}
    account_file.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("TABLE_ACCOUNT_FILE", str(account_file))
    monkeypatch.delenv("TABLE_TOKEN_SECRET_FILE", raising=False)
    monkeypatch.setattr(web_server, "USERS_FILE", account_file)
    monkeypatch.setattr(web_server, "MAHJONG_DB_FILE", club)
    monkeypatch.setattr(web_server, "LIVE_DB_FILE", tmp_path / "live.sqlite3")
    monkeypatch.setattr(web_server, "record_action", lambda **kw: kw)
    registered_names.ensure_directory(account_file)
    with closing(mahjong_store.connect(club)) as db:
        original_player = mahjong_store.upsert_player(db, "Player 1")["id"]
    app = create_app(Settings(database_path=tmp_path / "api.sqlite3", club_database_path=str(club),
        mock_auth_enabled=True, sync_interval_seconds=3600), DisabledSheets(), NoVision())
    with TestClient(app) as client:
        sink = app.state.service.sheets
        assert sink.account_path == account_file
        assert sink.account_lookup.__self__ is app.state.tables
        original_writer = sink.write_manual_history
        def fail_before_history(match):
            raise TimeoutError("temporary history failure")
        monkeypatch.setattr(sink, "write_manual_history", fail_before_history)
        first = upload(client, key="lifespan-pending-rename").json()
        assert first["local_saved"] and first["status"] == "pending"
        with app.state.service.store.connect() as db:
            payload_before = db.get(ExternalDelivery, first["external_sync"]["request_id"]).payload_json
        web_server.admin_registered_name({"user_id": "u1", "expected_name": "Player 1", "new_name": "Current Registered Name",
                                          "confirm": True}, "Admin")
        monkeypatch.setattr(sink, "write_manual_history", original_writer)
        again = upload(client, key="lifespan-pending-rename")
        assert again.status_code == 200 and again.json()["replayed"]
        assert again.json()["result"]["players"]["east"]["user"]["name"] == "Current Registered Name"
        with closing(mahjong_store.connect(club)) as db:
            assert db.execute("SELECT id FROM players WHERE name='Current Registered Name'").fetchone()[0] == original_player
            assert db.execute("SELECT COUNT(*) FROM players WHERE name='Player 1'").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM game_players WHERE player_id=?", (original_player,)).fetchone()[0] == 1
        with app.state.service.store.connect() as db:
            assert db.get(ExternalDelivery, first["external_sync"]["request_id"]).payload_json == payload_before
