"""Registered-name migration, privacy, stable identities and concurrent writes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest
import mahjong_store
import registered_names as names
import web_server


@pytest.fixture
def directory(tmp_path, monkeypatch):
    users = tmp_path / "users.json"
    db = tmp_path / "club.sqlite3"
    monkeypatch.setattr(web_server, "USERS_FILE", users)
    monkeypatch.setattr(web_server, "MAHJONG_DB_FILE", db)
    monkeypatch.setattr(web_server, "LIVE_DB_FILE", tmp_path / "live.sqlite3")
    monkeypatch.setattr(web_server, "record_action", lambda **kw: kw)
    monkeypatch.setattr(web_server, "_sessions", {})
    with closing(mahjong_store.connect(db)):
        pass
    return users, db


def account(path, name, account_id=None, **extra):
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"users": {}}
    key = " ".join(name.casefold().split())
    data["users"][key] = {"name": name, "account_id": account_id or "stable-" + str(len(data["users"])),
                          "salt": "private-salt", "password_hash": "private-hash", "role": "user", **extra}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data["users"][key]["account_id"]


@pytest.mark.parametrize("second", ["Alice", " alice ", "ALICE", "Ａｌｉｃｅ", "Alice\u00a0"])
def test_registration_names_are_unique_after_normalization(directory, second):
    path, _ = directory
    web_server.register_user({"username": "Alice", "password": "example-password"})
    with pytest.raises(ValueError, match="already in use"):
        web_server.register_user({"username": second, "password": "example-password"})
    assert len(json.loads(path.read_text())["users"]) == 1
    with sqlite3.connect(names.database_path(path)) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO registered_users(account_id,registered_name,normalized_registered_name,legacy_key,enabled) VALUES('other','Alice','alice','other',1)")


def test_whitespace_unicode_and_empty_names(directory):
    assert names.normalize_name(" Ａlice\t BOB  ") == "alice bob"
    web_server.register_user({"username": "Alice  Bob", "password": "example-password"})
    with pytest.raises(ValueError):
        web_server.register_user({"username": "alice\u00a0bob", "password": "example-password"})
    with pytest.raises(ValueError):
        web_server.register_user({"username": "  \t ", "password": "example-password"})


def test_concurrent_registration_only_one_succeeds(directory):
    path, _ = directory
    barrier = threading.Barrier(2)
    def attempt(value):
        barrier.wait()
        try:
            web_server.register_user({"username": value, "password": "example-password"})
            return "ok"
        except ValueError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(attempt, ["Ａlice  Bob", "alice bob"]))
    assert sorted(result) == ["conflict", "ok"]
    assert len(json.loads(path.read_text())["users"]) == 1


def test_duplicate_legacy_names_are_reported_and_repaired_without_deletion(directory):
    path, dbpath = directory
    alice = account(path, "Alice")
    second = account(path, "Ａｌｉｃｅ")
    account(path, "Admin", role="admin")
    report = names.ensure_directory(path)
    assert not report["ready"] and not report["unique_constraint"]
    assert {r["id"] for r in report["duplicates"][0]["users"]} == {alice, second}
    with pytest.raises(ValueError, match="paused"):
        web_server.register_user({"username": "New Name", "password": "example-password"})
    web_server.admin_registered_name({"user_id": second, "new_name": "Alice Two", "expected_name": "Ａｌｉｃｅ", "confirm": True}, "Admin")
    report = names.ensure_directory(path)
    assert report["ready"] and report["unique_constraint"]
    assert report["account_count"] == 3
    assert names.current_name_map(path)[second] == "Alice Two"
    assert names.current_name_map(path)[alice] == "Alice"


def test_admin_rename_requires_permission_confirmation_and_unique_name(directory):
    path, _ = directory
    alice = account(path, "Alice")
    account(path, "Bob")
    account(path, "Admin", role="admin")
    body = {"user_id": alice, "new_name": "Alice New", "expected_name": "Alice", "confirm": True}
    with pytest.raises(PermissionError):
        web_server.admin_registered_name(body, "Alice")
    with pytest.raises(ValueError, match="confirm"):
        web_server.admin_registered_name({**body, "confirm": False}, "Admin")
    with pytest.raises(ValueError, match="Refresh") as stale:
        web_server.admin_registered_name({**body, "expected_name": "Stale"}, "Admin")
    assert stale.value.code == "stale_name"
    with pytest.raises(ValueError, match="already in use") as taken:
        web_server.admin_registered_name({**body, "new_name": " ＢＯＢ "}, "Admin")
    assert taken.value.code == "registered_name_taken"
    assert names.current_name_map(path)[alice] == "Alice"


def test_rename_preserves_account_sql_history_session_and_writes_audit(directory):
    path, dbpath = directory
    alice = account(path, "Alice")
    admin = account(path, "Admin", role="admin")
    web_server._sessions["session"] = "Alice"
    with closing(mahjong_store.connect(dbpath)) as db:
        game = mahjong_store.import_game(db, ["Alice", "B", "C", "D"], [40000,30000,20000,10000], "2026-09-19 12:00:00")
        before_player = db.execute("SELECT id FROM players WHERE name='Alice'").fetchone()[0]
        before_relations = list(db.execute("SELECT * FROM game_players ORDER BY player_id"))
    result = web_server.admin_registered_name({"user_id": alice, "new_name": "Alice New", "expected_name": "Alice", "confirm": True, "reason": "Requested correction"}, "Admin")
    assert result["user"] == {"id": alice, "name": "Alice New"}
    assert web_server._sessions["session"] == "Alice New"
    assert web_server.stable_account_id("Alice New") == alice
    assert json.loads(path.read_text())["users"]["alice new"]["password_hash"] == "private-hash"
    with closing(mahjong_store.connect(dbpath)) as db:
        assert db.execute("SELECT id FROM players WHERE name='Alice New'").fetchone()[0] == before_player
        assert list(db.execute("SELECT * FROM game_players ORDER BY player_id")) == before_relations
        assert any(p["name"] == "Alice New" for p in mahjong_store.recent_games(db)[0][0]["players"])
    with sqlite3.connect(names.database_path(path)) as db:
        assert db.execute("SELECT account_id,old_name,new_name,admin_id,reason FROM registered_name_audit").fetchone() == (alice, "Alice", "Alice New", admin, "Requested correction")


def test_concurrent_administrators_cannot_take_same_name(directory):
    path, _ = directory
    first = account(path, "Alice")
    second = account(path, "Bob")
    account(path, "Admin", role="admin")
    barrier = threading.Barrier(2)
    def attempt(values):
        uid, old = values
        barrier.wait()
        try:
            web_server.admin_registered_name({"user_id": uid, "new_name": "One Name", "expected_name": old, "confirm": True}, "Admin")
            return "ok"
        except ValueError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, [(first,"Alice"),(second,"Bob")])) == ["conflict","ok"]


def test_search_is_bounded_private_casefolded_and_excludes_inactive(directory):
    path, _ = directory
    for i in range(32):
        account(path, f"Player {i:02d}", email="private@example.invalid", discord_id="secret", disabled=i==31)
    account(path, "中文玩家")
    first = names.search_accounts(path, " ＰＬＡＹＥＲ ", limit=10)
    second = names.search_accounts(path, "player", cursor=first["next_cursor"], limit=10)
    assert len(first["users"]) == len(second["users"]) == 10
    assert set(first["users"][0]) == {"id","name","avatar"}
    assert not {x["id"] for x in first["users"]} & {x["id"] for x in second["users"]}
    assert "private" not in json.dumps(first)
    assert names.search_accounts(path, "中文")["users"][0]["name"] == "中文玩家"
    assert names.search_accounts(path, "stable-0")["users"] == []
    assert names.search_accounts(path, ids=["stable-31"])["users"] == []
    with pytest.raises(ValueError):
        names.search_accounts(path, "different", cursor=first["next_cursor"])
    with pytest.raises(ValueError):
        names.search_accounts(path, ids=["x"]*51)


def test_existing_stable_ids_credentials_and_reruns_preserved(directory):
    path, _ = directory
    existing = account(path, "Alice", "old-account-id")
    data = json.loads(path.read_text())
    data["users"]["bob"] = {"name":"Bob","salt":"old","password_hash":"unchanged"}
    path.write_text(json.dumps(data))
    assert names.ensure_directory(path)["ready"]
    once = json.loads(path.read_text())
    assert names.ensure_directory(path)["ready"]
    assert json.loads(path.read_text()) == once
    assert once["users"]["alice"]["account_id"] == existing
    assert once["users"]["bob"]["account_id"]
    assert once["users"]["bob"]["password_hash"] == "unchanged"


def test_legacy_rename_api_cannot_bypass_confirmation(directory):
    path, _ = directory
    account(path, "Alice")
    account(path, "Admin", role="admin")
    with pytest.raises(ValueError, match="confirm"):
        web_server.admin_rename_player({"old_name":"Alice","new_name":"Other"}, "Admin")
    assert names.current_name_map(path)["stable-0"] == "Alice"


def test_http_search_requires_login_and_rename_rejects_regular_user(directory):
    path, _ = directory
    alice = account(path, "Alice")
    web_server._sessions["alice-session"] = "Alice"
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + "/api/registered-users?q=Alice")
        assert error.value.code == 401
        request = urllib.request.Request(base + "/api/registered-users?q=ali", headers={"Cookie":"mahjong_session=alice-session"})
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["users"] == [{"id":alice,"name":"Alice","avatar":""}]
        request = urllib.request.Request(base + "/api/admin/registered-name", data=json.dumps({"user_id":alice,"new_name":"Other","expected_name":"Alice","confirm":True}).encode(),
            headers={"Cookie":"mahjong_session=alice-session","Content-Type":"application/json", "Origin":base})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 403
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)


def test_score_import_cannot_change_registered_player_spelling(directory):
    _, dbpath = directory
    with closing(mahjong_store.connect(dbpath)) as db:
        original = mahjong_store.upsert_player(db, "Alice")
        imported = mahjong_store.upsert_player(db, "ALICE")
        assert imported["id"] == original["id"]
        assert imported["name"] == "Alice"


def test_failed_club_commit_is_recovered_from_durable_intent(directory, monkeypatch):
    from contextlib import contextmanager
    path, dbpath = directory
    alice = account(path, "Alice")
    account(path, "Admin", role="admin")
    with closing(mahjong_store.connect(dbpath)) as db:
        player_id = mahjong_store.upsert_player(db, "Alice")["id"]
    original = mahjong_store.connect
    failed = []
    @contextmanager
    def interrupted(*args, **kwargs):
        db = original(*args, **kwargs)
        try:
            yield db
            changed = db.execute("SELECT name FROM players WHERE id=?", (player_id,)).fetchone()[0] == "Alice New"
            if changed and not failed:
                failed.append(True)
                db.rollback()
                raise sqlite3.OperationalError("simulated commit failure")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
    monkeypatch.setattr(mahjong_store, "connect", interrupted)
    with pytest.raises(sqlite3.OperationalError):
        web_server.admin_registered_name({"user_id":alice,"new_name":"Alice New","expected_name":"Alice","confirm":True}, "Admin")
    with sqlite3.connect(names.database_path(path)) as db:
        assert db.execute("SELECT count(*) FROM pending_registered_name_changes").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM registered_name_audit").fetchone()[0] == 1
    # This is a later request, using only the durable journal.
    assert names.read_accounts(path)["users"]["alice new"]["account_id"] == alice
    with sqlite3.connect(dbpath) as db:
        assert db.execute("SELECT name FROM players WHERE id=?",(player_id,)).fetchone()[0] == "Alice New"
    with sqlite3.connect(names.database_path(path)) as db:
        assert db.execute("SELECT count(*) FROM pending_registered_name_changes").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM registered_name_audit").fetchone()[0] == 1


def test_process_death_after_club_commit_recovers_without_losing_audit(directory):
    import subprocess, sys
    path, dbpath = directory
    alice = account(path, "Alice")
    account(path, "Admin", role="admin")
    with closing(mahjong_store.connect(dbpath)) as db:
        player_id = mahjong_store.upsert_player(db, "Alice")["id"]
    names.ensure_directory(path)
    code = """
import os,sys
from pathlib import Path
import registered_names,web_server
web_server.USERS_FILE=Path(sys.argv[1]);web_server.MAHJONG_DB_FILE=Path(sys.argv[2]);web_server.LIVE_DB_FILE=Path(sys.argv[2]).with_name("live.sqlite3")
web_server.record_action=lambda **kwargs: None
registered_names._write=lambda *args,**kwargs: os._exit(71)
web_server.admin_registered_name({'user_id':sys.argv[3],'new_name':'Alice New','expected_name':'Alice','confirm':True},'Admin')
"""
    result = subprocess.run([sys.executable,"-c",code,str(path),str(dbpath),alice], timeout=30)
    assert result.returncode == 71
    assert json.loads(path.read_text())["users"]["alice"]["name"] == "Alice"
    assert names.read_accounts(path)["users"]["alice new"]["account_id"] == alice
    with sqlite3.connect(dbpath) as db:
        assert db.execute("SELECT name FROM players WHERE id=?",(player_id,)).fetchone()[0] == "Alice New"
    with sqlite3.connect(names.database_path(path)) as db:
        assert db.execute("SELECT count(*) FROM registered_name_audit").fetchone()[0] == 1


def test_interrupted_mounted_account_write_recovers_complete_credentials(directory, monkeypatch):
    import errno
    path, _ = directory
    account(path, "Alice")
    names.ensure_directory(path)
    data = names.read_accounts(path)
    data["users"]["alice"]["avatar"] = "new-avatar"
    original = names.os.replace
    def mounted_replace(source, target):
        if Path(source) == names._pending_file(path) and Path(target) == path:
            # Simulate death after a Docker-mounted inode has been truncated.
            path.write_text('{"users":')
            raise SystemExit("simulated worker interruption")
        return original(source, target)
    monkeypatch.setattr(names.os, "replace", mounted_replace)
    with pytest.raises(SystemExit):
        names.write_accounts(path, data)
    assert names._pending_file(path).exists()
    monkeypatch.setattr(names.os, "replace", original)
    recovered = names.read_accounts(path)
    assert recovered["users"]["alice"]["password_hash"] == "private-hash"
    assert recovered["users"]["alice"]["avatar"] == "new-avatar"
    assert not names._pending_file(path).exists()


def test_discord_binding_and_registration_share_complete_transaction(directory, monkeypatch):
    from cogs import personaldata
    path, _ = directory
    monkeypatch.setattr(personaldata,"USERS_FILE",path)
    account(path,"Alice")
    barrier = threading.Barrier(2)
    def bind():
        barrier.wait()
        return personaldata.bind_registered_discord("Alice","123456789012345678","Discord User")
    def register():
        barrier.wait()
        return web_server.register_user({"username":"Bob","password":"test-password"})
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(bind); b = executor.submit(register)
        assert a.result() == "Alice" and b.result() == "Bob"
    data = names.read_accounts(path)
    assert set(data["users"]) == {"alice","bob"}
    assert data["users"]["alice"]["discord_id"] == "123456789012345678"
    assert personaldata.unbind_registered_discord("123456789012345678") == "Alice"
    assert "bob" in names.read_accounts(path)["users"]


@pytest.mark.parametrize("route,target", [
    ("/api/dashboard", "build_dashboard"),
    ("/api/match-candidates", "sql_match_candidates"),
    ("/api/players", "sheet_player_names"),
    ("/api/session", "current_user_profile"),
    ("/api/live-games", "active_live_games"),
    ("/api/admin/matches", "sql_admin_game_rows"),
    ("/api/admin/actions", "admin_recent_actions"),
    ("/api/annual-summary", "sql_annual_summary"),
])
def test_http_internal_failures_never_expose_sql_or_identifiers(directory, monkeypatch, route, target):
    path, _ = directory
    account(path, "Admin", role="admin")
    web_server._sessions["error-session"] = "Admin"
    secret = "8f8c3ad2-SECRET SQL SELECT password_hash FROM registered_users traceback"
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError(secret)
    monkeypatch.setattr(web_server, target, fail)
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}" + route, headers={"Cookie":"mahjong_session=error-session"})
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            payload = response.read().decode()
        assert "8f8c3ad2" not in payload and "password_hash" not in payload and "traceback" not in payload
        assert web_server.PUBLIC_REQUEST_ERROR in payload
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)


def test_sync_warning_hides_provider_error_but_business_validation_stays_readable(directory, monkeypatch):
    path, _ = directory
    account(path, "Admin", role="admin")
    secret = "secret-account-uuid raw provider stack"
    def fail(*args, **kwargs):
        raise RuntimeError(secret)
    monkeypatch.setattr(web_server,"append_quarter_marker_to_sheet",fail)
    result = web_server.change_current_quarter({"year":"2030","term":"Fall"},"Admin")
    assert result["ok"] and result["warning"] == web_server.PUBLIC_SYNC_WARNING
    assert secret not in json.dumps(result)
    assert web_server.public_response_body({"message":"Four distinct players are required.","code":"invalid_request"},400)["message"] == "Four distinct players are required."
    audit = {"recent_actions":[{"payload":{"sheet_error":secret,"sheet_errors":[secret]}}]}
    assert secret not in json.dumps(web_server.public_response_body(audit))
    assert audit["recent_actions"][0]["payload"]["sheet_error"] == secret


@pytest.mark.parametrize("new_name", ["Updated Person", "Player"])
def test_rename_rebuilds_actual_substring_index_including_shorter_names(directory, new_name):
    path, _ = directory
    uid = account(path, "Original Player")
    account(path, "Admin", role="admin")
    assert names.search_accounts(path, "Original Player")["users"] == [{"id":uid,"name":"Original Player","avatar":""}]
    web_server.admin_registered_name({"user_id":uid,"expected_name":"Original Player",
        "new_name":new_name,"confirm":True}, "Admin")
    expected = [{"id":uid,"name":new_name,"avatar":""}]
    assert names.search_accounts(path, new_name)["users"] == expected
    assert names.search_accounts(path, "Original Player")["users"] == []
    assert names.search_accounts(path, new_name[-4:])["users"] == expected
    with sqlite3.connect(names.database_path(path)) as db:
        indexed = {row[0] for row in db.execute("SELECT suffix FROM registered_name_suffixes WHERE account_id=?", (uid,))}
    normalized = names.normalize_name(new_name)
    assert indexed == {normalized[index:] for index in range(len(normalized))}


def test_directory_restart_repairs_preexisting_rename_suffix_mismatch(directory):
    path, _ = directory
    uid = account(path, "Current Name")
    names.ensure_directory(path)
    # Older builds reserved the new directory name before syncing the suffixes;
    # simulate the resulting durable mismatch and a fresh process cache.
    previous = "previous player"
    with sqlite3.connect(names.database_path(path)) as db:
        db.execute("DELETE FROM registered_name_suffixes WHERE account_id=?", (uid,))
        db.executemany("INSERT INTO registered_name_suffixes(suffix,account_id) VALUES(?,?)",
                       [(previous[index:], uid) for index in range(len(previous))])
    names._DIRECTORY_VERSIONS.pop(str(path.resolve()), None)
    assert names.search_accounts(path, "Current Name")["users"] == [{"id":uid,"name":"Current Name","avatar":""}]
    assert names.search_accounts(path, previous)["users"] == []
    assert names.read_accounts(path)["users"]["current name"]["password_hash"] == "private-hash"
