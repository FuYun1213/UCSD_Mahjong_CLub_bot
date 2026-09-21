"""Existing-name account opening never creates or renames a historical player."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import ThreadingHTTPServer
import hashlib
import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest
import account_registration as reg
import registered_names as names
import web_server as web
from test_registered_names import directory, account
from test_registration_v10 import form, legacy


@pytest.fixture(autouse=True)
def isolated_score_database(tmp_path, monkeypatch):
    monkeypatch.delenv("NFC_DATABASE_URL", raising=False)
    monkeypatch.setenv("NFC_DATABASE_PATH", str(tmp_path / "unused-score.sqlite3"))


def claim_form(player, **extra):
    return {"player_id": "club-" + str(player["id"]), "password": "Example!2026",
            "confirm_password": "Example!2026", **extra}


def player_rows(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT * FROM players ORDER BY id").fetchall()


def journal(path, token=None):
    with closing(reg.connect(path)) as db:
        if token:
            return dict(db.execute("SELECT * FROM account_claims WHERE resume_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),)).fetchone())
        return dict(db.execute("SELECT * FROM account_claims").fetchone())


def old_request(path, token, status="pending", name="Old Requested Rename"):
    with closing(reg.connect(path)) as db, db:
        db.execute("UPDATE account_claims SET registered_name=?,normalized_name=?,status=?,reviewed_by='admin' WHERE resume_hash=?",
            (name, names.normalize_name(name), status, hashlib.sha256(token.encode()).hexdigest()))


def approve(token):
    return reg.review(web, {"claim_id": journal(web.USERS_FILE, token)["id"], "decision": "approve"}, "Admin")


def test_zero_game_player_opens_original_name_without_new_player_or_username(directory):
    path, club = directory
    player = legacy(web, "Original Player")
    account(path, "Admin", role="admin")
    before = player_rows(club)
    assert player["games_played"] == 0
    assert reg.claimable_players(web) == {"players": [{"id": "club-" + str(player["id"]), "name": "Original Player"}], "has_more": False}
    token = reg.submit_claim(web, claim_form(player))
    assert reg.resume(web, token) == ({"status": "pending"}, None)
    assert reg.claimable_players(web)["players"] == []
    assert approve(token)["status"] == "approved"
    assert player_rows(club) == before
    assert web.login_user(form("Original Player"))[1] == "Original Player"
    row = names.read_accounts(path)["users"]["original player"]
    assert row["club_player_id"] == player["id"] and row["account_id"] == "club-" + str(player["id"])
    assert reg.resume(web, token)[1] == row["account_id"]


def test_search_is_normalized_bounded_and_exposes_only_name_and_player_id(directory):
    path, _ = directory
    for name in ("Alice Bob", "Alice Carol", "Other Zero Games"):
        legacy(web, name)
    claimed = legacy(web, "Private Owner")
    account(path, "Renamed Account", account_id="private-stable-id", club_player_id=str(claimed["id"]),
            discord_id="123456789012345678", password_hash="secret-digest", avatar="private-avatar")
    result = reg.claimable_players(web, " ＡＬＩＣＥ ", 1)
    assert result["has_more"] and [p["name"] for p in result["players"]] == ["Alice Bob"]
    all_rows = reg.claimable_players(web, limit=50)["players"]
    assert len(all_rows) == 3 and all(set(row) == {"id", "name"} for row in all_rows)
    assert "secret" not in json.dumps(all_rows) and "private" not in json.dumps(all_rows).casefold()
    assert reg.is_claimed(web, claimed)
    with pytest.raises(ValueError, match="already registered"):
        reg.submit_claim(web, claim_form(claimed))


def test_search_excludes_disabled_duplicate_and_pending_players(directory):
    path, club = directory
    disabled = legacy(web, "Disabled")
    pending = legacy(web, "Pending")
    legacy(web, "Alice")
    legacy(web, "Ａｌｉｃｅ")
    empty = legacy(web, "Temporary")
    good = legacy(web, "Available")
    with closing(sqlite3.connect(club)) as db, db:
        db.execute("ALTER TABLE players ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE players SET disabled=1 WHERE id=?", (disabled["id"],))
        db.execute("UPDATE players SET name='' WHERE id=?", (empty["id"],))
    reg.submit_claim(web, claim_form(pending))
    assert reg.claimable_players(web)["players"] == [{"id": "club-" + str(good["id"]), "name": "Available"}]
    with pytest.raises(ValueError):
        reg.submit_claim(web, claim_form(disabled))
    with pytest.raises(ValueError, match="administrator review"):
        reg.submit_claim(web, claim_form({"id": 3}))


def test_numeric_name_never_conflicts_with_strict_player_id_or_old_id_payload(directory):
    path, club = directory
    first = legacy(web, "Alice")
    numeric = legacy(web, str(first["id"]))
    account(path, "Admin", role="admin")
    before = player_rows(club)
    first_token = reg.submit_claim(web, {"legacy_id": first["id"], "password": "Example!2026", "confirm_password": "Example!2026"})
    second_token = reg.submit_claim(web, claim_form(numeric))
    approve(first_token); approve(second_token)
    assert web.login_user(form("Alice"))[1] == "Alice"
    assert web.login_user(form(str(first["id"])))[1] == str(first["id"])
    assert names.read_accounts(path)["users"]["alice"]["club_player_id"] == first["id"]
    assert names.read_accounts(path)["users"][str(first["id"])]["club_player_id"] == numeric["id"]
    assert player_rows(club) == before


@pytest.mark.parametrize("bad", [None, True, 1.0, [], "Alice", "club-Alice", "0", "-1", "1 OR 1=1", "99999999999999999999"])
def test_selection_requires_a_real_positive_player_id(directory, bad):
    legacy(web, "Alice")
    with pytest.raises(ValueError, match="not found"):
        reg.submit_claim(web, {"player_id": bad, "password": "Example!2026", "confirm_password": "Example!2026"})


def test_forged_username_or_conflicting_selection_cannot_rename_player(directory):
    _, club = directory
    player = legacy(web)
    before = player_rows(club)
    with pytest.raises(names.RegisteredNameError) as error:
        reg.submit_claim(web, claim_form(player, username="Stolen New Name"))
    assert error.value.code == "existing_player_name_mismatch"
    with pytest.raises(ValueError, match="Select one"):
        reg.submit_claim(web, claim_form(player, legacy_id=player["id"] + 1))
    assert reg.claims(web) == [] and player_rows(club) == before
    # Normalized equivalent old clients remain compatible, but cannot choose display casing.
    token = reg.submit_claim(web, claim_form(player, username=" ＯＬＤ  ＰＬＡＹＥＲ "))
    assert journal(web.USERS_FILE, token)["registered_name"] == "Old Player"


def test_parallel_claims_for_one_player_have_one_pending_credential(directory):
    path, club = directory
    player = legacy(web)
    before = player_rows(club)
    barrier = threading.Barrier(4)
    def submit(_):
        barrier.wait()
        try:
            return reg.submit_claim(web, claim_form(player))
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert sum(token is not None for token in results) == 1
    assert len(reg.claims(web)) == 1 and not names.read_accounts(path)["users"]
    assert player_rows(club) == before


@pytest.mark.parametrize("status", ["pending", "approving"])
def test_old_requests_with_different_username_use_original_name_without_renaming(directory, status):
    path, club = directory
    player = legacy(web)
    account(path, "Admin", role="admin")
    before = player_rows(club)
    token = reg.submit_claim(web, claim_form(player))
    old_request(path, token, status)
    projected = reg.claims(web)[0]
    assert projected["legacy_name"] == projected["registered_name"] == "Old Player"
    if status == "pending":
        approve(token)
    else:
        assert reg.resume(web, token)[0]["status"] == "approved"
    assert web.login_user(form("Old Player"))[1] == "Old Player"
    assert "old requested rename" not in names.read_accounts(path)["users"]
    assert player_rows(club) == before


def test_current_source_name_is_checked_again_at_approval(directory):
    path, club = directory
    player = legacy(web)
    account(path, "Admin", role="admin")
    token = reg.submit_claim(web, claim_form(player))
    # Existing admin correction happened before approval, serialized by account guard.
    with names.account_lock(path), closing(sqlite3.connect(club)) as db, db:
        db.execute("UPDATE players SET name='Correct Original',name_key='correct original' WHERE id=?", (player["id"],))
    before = player_rows(club)
    assert reg.claims(web)[0]["legacy_name"] == "Correct Original"
    approve(token)
    assert web.login_user(form("Correct Original"))[1] == "Correct Original"
    assert player_rows(club) == before


def test_interrupted_publication_replays_same_credentials_and_identity(directory, monkeypatch):
    path, club = directory
    player = legacy(web)
    account(path, "Admin", role="admin")
    before = player_rows(club)
    token = reg.submit_claim(web, claim_form(player))
    with monkeypatch.context() as fault:
        fault.setattr(reg.account_legacy_links, "publish", lambda *a: (_ for _ in ()).throw(OSError("simulated interruption")))
        with pytest.raises(OSError):
            approve(token)
    pending = names.read_accounts(path)["users"]["old player"].copy()
    assert pending["status"] == "pending_claim" and journal(path, token)["status"] == "approving"
    with pytest.raises((ValueError, PermissionError)):
        web.login_user(form("Old Player"))
    assert reg.resume(web, token)[0]["status"] == "approved"
    active = names.read_accounts(path)["users"]["old player"]
    assert active == {**pending, "status": "active"} and player_rows(club) == before


def test_approved_account_admin_rename_is_not_undone_by_old_claim(directory):
    path, club = directory
    player = legacy(web)
    account(path, "Admin", role="admin")
    token = reg.submit_claim(web, claim_form(player))
    approve(token)
    uid = web.stable_account_id("Old Player")
    web.admin_registered_name({"user_id": uid, "expected_name": "Old Player", "new_name": "Admin Renamed", "confirm": True}, "Admin")
    before = names.read_accounts(path), player_rows(club)
    assert approve(token)["status"] == "approved"
    assert reg.resume(web, token)[0]["status"] == "approved"
    assert (names.read_accounts(path), player_rows(club)) == before
    assert web.login_user(form("Admin Renamed"))[1] == "Admin Renamed"


def test_old_approving_after_committed_rename_preserves_published_identity(directory):
    path, club = directory
    player = legacy(web)
    account(path, "Admin", role="admin")
    token = reg.submit_claim(web, claim_form(player))
    record = journal(path, token)
    old_request(path, token, "approving", "Previously Published Name")
    account(path, "Old Player", account_id=record["account_id"], club_player_id=player["id"],
            password_hash=record["password_hash"], salt="", status="pending_claim")
    names.rename_account(path, account_id=record["account_id"], old_name="Old Player", new_name="Previously Published Name",
        club_database=club, club_player_id=player["id"], old_role="user", admin_id="admin", admin_name="Admin", reason="Old release committed approval")
    before = player_rows(club)
    assert reg.resume(web, token)[0]["status"] == "approved"
    assert player_rows(club) == before
    assert web.login_user(form("Previously Published Name"))[1] == "Previously Published Name"


def test_old_approving_cannot_capture_same_stable_id_bound_to_another_player(directory):
    path, club = directory
    player = legacy(web)
    other = legacy(web, "Other Player")
    token = reg.submit_claim(web, claim_form(player))
    record = journal(path, token)
    old_request(path, token, "approving")
    account(path, "Unrelated Account", account_id=record["account_id"], club_player_id=str(other["id"]))
    before = names.read_accounts(path), player_rows(club)
    with pytest.raises(ValueError, match="administrator review"):
        reg.resume(web, token)
    assert (names.read_accounts(path), player_rows(club)) == before
    assert journal(path, token)["status"] == "approving"


def test_conflicting_historical_score_identities_are_not_offered(directory, monkeypatch, tmp_path):
    from mahjong_api.store import Store
    from mahjong_api.database_models import User
    score_path = tmp_path / "ambiguous-scores.sqlite3"
    monkeypatch.setenv("NFC_DATABASE_PATH", str(score_path))
    player = legacy(web)
    store = Store(score_path)
    try:
        with store.connect() as db:
            db.add(User(id="history-one", name=player["name"]))
            db.add(User(id="history-two", name=player["name"]))
        assert reg.claimable_players(web)["players"] == []
        with pytest.raises(ValueError, match="conflicting historical"):
            reg.submit_claim(web, claim_form(player))
    finally:
        store.close()


@pytest.fixture
def public_website(directory, monkeypatch):
    monkeypatch.setattr(web, "proxy_nfc_request", lambda _: False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_public_lookup_http_and_failure_do_not_disclose_credentials(public_website, directory, monkeypatch):
    path, _ = directory
    player = legacy(web, "Available")
    private = legacy(web, "Private Record")
    account(path, "Private Account", club_player_id=str(private["id"]), discord_id="123456789012345678", password_hash="private-hash")
    with urllib.request.urlopen(public_website + "/api/register/players?q=AVAIL&limit=20") as response:
        assert response.status == 200
        assert json.load(response) == {"players": [{"id": "club-" + str(player["id"]), "name": "Available"}], "has_more": False}
    monkeypatch.setattr(reg, "claimable_players", lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError("private-hash SQL private-stable-id")))
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(public_website + "/api/register/players")
    assert error.value.code == 500
    body = json.load(error.value)
    assert body == {"message": web.PUBLIC_REQUEST_ERROR, "code": "server_error"}
