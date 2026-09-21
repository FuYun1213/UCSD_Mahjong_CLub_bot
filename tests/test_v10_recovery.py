"""Account recovery schema and provider-success regressions using isolated state."""
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import account_discord as discord
import account_registration as reg
import registered_names as names
import web_server as web
from test_registered_names import directory, account
from test_registration_v10 import form, legacy


def test_rejected_claim_can_be_resubmitted_and_approved(directory):
    path, _ = directory
    old = legacy(web)
    account(path, "Admin", role="admin")
    first = reg.submit_claim(web, form("Old Player", legacy_id=old["id"]))
    claim = reg.claims(web)[0]
    reg.review(web, {"claim_id": claim["id"], "decision": "reject"}, "Admin")
    second = reg.submit_claim(web, form("Old Player", legacy_id=old["id"]))
    pending = next(c for c in reg.claims(web) if c["status"] == "pending")
    reg.review(web, {"claim_id": pending["id"], "decision": "approve"}, "Admin")
    assert reg.resume(web, first)[0]["status"] == "rejected"
    result, account_id = reg.resume(web, second)
    assert result["status"] == "approved" and account_id
    assert web.login_user(form("Old Player"))[1] == "Old Player"


def test_early_v10_claim_schema_migrates_without_losing_rejections(directory):
    path, _ = directory
    with closing(reg.connect(path)) as db:
        schema = db.execute("SELECT sql FROM sqlite_master WHERE name='account_claims'").fetchone()[0]
        db.execute("DROP TABLE account_claims")
        db.execute(schema.replace("account_id TEXT NOT NULL,", "account_id TEXT NOT NULL UNIQUE,"))
        db.execute("INSERT INTO account_claims(id,legacy_player_id,legacy_name,registered_name,normalized_name,password_hash,account_id,resume_hash,status) VALUES('claim',1,'Legacy','Candidate','candidate','hash','club-1','nonce','rejected')")
        db.commit()
    with closing(reg.connect(path)) as db:
        assert db.execute("SELECT status FROM account_claims WHERE id='claim'").fetchone()[0] == "rejected"
        db.execute("INSERT INTO account_claims(id,legacy_player_id,legacy_name,registered_name,normalized_name,password_hash,account_id,resume_hash) VALUES('new',1,'Legacy','Candidate','candidate','hash','club-1','nonce2')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO account_claims(id,legacy_player_id,legacy_name,registered_name,normalized_name,password_hash,account_id,resume_hash) VALUES('duplicate',1,'Legacy','Other','other','hash','club-1','nonce3')")
        db.rollback()


def test_oauth_provider_success_one_use_state_and_duplicate_binding(directory, monkeypatch):
    path, _ = directory
    for key in ("DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_REDIRECT_URI"):
        monkeypatch.setenv(key, "test-only")
    reg.create_new(web, form("First"))
    reg.create_new(web, form("Second"))
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"access_token": "provider-test-token"})
    def get(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer provider-test-token"
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"id": "123456789012345678", "global_name": "Discord Name", "avatar": "image_hash"})
    monkeypatch.setattr(discord.requests, "post", post)
    monkeypatch.setattr(discord.requests, "get", get)
    def state(uid):
        return parse_qs(urlsplit(discord.start(uid, "session", "/reservations")).query)["state"][0]
    uid = web.stable_account_id("First")
    nonce = state(uid)
    query = {"state": nonce, "code": "provider-code"}
    assert discord.complete(path, query, uid, "session") == ("/reservations", True)
    with pytest.raises(ValueError, match="expired or is invalid"):
        discord.complete(path, query, uid, "session")
    other = web.stable_account_id("Second")
    assert discord.complete(path, {"state": state(other), "code": "other-code"}, other, "session") == ("/reservations", False)
    rows = names.read_accounts(path)["users"]
    assert rows["first"]["discord_id"] == "123456789012345678"
    assert rows["first"]["discord_avatar"].startswith("https://cdn.discordapp.com/avatars/")
    assert "discord_id" not in rows["second"]
    assert "provider-test-token" not in path.read_text()
    assert "provider-code" not in path.read_text()
    assert calls[0][1]["allow_redirects"] is False
    assert web.login_user(form("Second"))[1] == "Second"
