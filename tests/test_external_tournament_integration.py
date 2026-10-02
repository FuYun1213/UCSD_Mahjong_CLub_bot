"""Integration edges specific to external delivery and score review."""
import copy
import json
import sqlite3
import requests
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from mahjong_api.config import Settings
from mahjong_api.main import create_app
from mahjong_api.external_sync import ExternalSync, build_payload
from mahjong_api.sheets import DisabledSheets
from mahjong_api.store import Conflict, Store
from mahjong_api.tournament import TournamentService
from mahjong_api.tournament_models import ExternalDelivery
from test_mahjong_api import setup, settings, fill, submit, POINTS
from test_tournament import tournament, command, round_complete, finals


def test_free_score_failure_keeps_local_and_retries_identical_json(setup):
    from mahjong_api.auth import get_current_user
    from mahjong_api.models import User
    client, sheets, service = setup
    service.external.save_config({"enabled":True,"endpoint":"https://example.com/import","adapter":"json"},"admin")
    captured=[]
    def fail(endpoint,adapter,body,method):
        captured.append(copy.deepcopy(body))
        raise requests.Timeout("private provider diagnostic")
    service.external.transport=fail
    match=fill(client)
    response=submit(client,match_id=match,key="one-free-score")
    assert response.status_code == 202
    data=response.json()
    assert data["local_saved"] and data["local_completed"]
    assert data["external_sync"]["status"] == "pending" and data["external_sync"]["attempts"] == 0
    assert service.store.match(match)["scores"] == POINTS
    assert not any(service.table("1")["seats"].values())
    assert captured == [] and not sheets.history
    # Both workers are explicit: interactive submit did not execute either sink.
    service.flush()
    service.external.flush()
    delivery_key = data["external_sync"]["request_id"]
    failed = service.external.get(delivery_key)
    assert failed["status"] == "failed" and failed["error_code"] == "network_error"
    assert failed["attempts"] == 1 and "private provider" not in json.dumps(failed)
    assert len(captured) == 1
    first=captured[0]
    assert first["matchId"]==match and len(first["players"])==4
    assert all({"id","name","seat","placement","rawScore","placementPoints","gameScore","cumulativeScore"} <= set(p) for p in first["players"])
    service.external.transport=lambda endpoint,adapter,body,method:(captured.append(copy.deepcopy(body)) or (200,{"ok":True}))
    client.app.dependency_overrides[get_current_user] = lambda:User(id="admin", name="Admin", role="admin")
    retry = client.post("/api/external-deliveries/" + delivery_key + "/retry", json={})
    assert retry.status_code == 200
    assert retry.json()["status"] == "pending" and retry.json()["attempts"] == 1
    assert captured == [first], "Retry HTTP must queue work without sending it"
    service.external.flush()
    assert captured == [first, first]
    assert service.external.get(delivery_key)["status"] == "success"
    response=submit(client,match_id=match,key="one-free-score")
    assert response.status_code == 200
    assert response.json()["replayed"] is True and response.json()["external_sync"]["status"] == "success"
    assert response.json()["result"] == data["result"]
    client.post("/api/external-deliveries/" + delivery_key + "/retry", json={})
    service.external.flush()
    assert len(captured) == 2 and len(sheets.history) == 1


def test_disabled_configuration_does_not_backfill_or_contact_remote(setup):
    client,_,service=setup
    calls=[]
    service.external.transport=lambda *args:calls.append(args)
    fill(client);response=submit(client,key="disabled")
    assert response.json()["external_sync"]["status"]=="disabled"
    assert calls==[]


def test_pending_payload_keeps_original_destination_across_config_changes(tmp_path):
    store=Store(tmp_path/"pending.sqlite3")
    calls=[]
    ext=ExternalSync(store,lambda endpoint,adapter,body,method:(calls.append(endpoint) or (200,{})))
    service=TournamentService(store,ext)
    try:
        ext.save_config({"enabled":True,"endpoint":"https://example.com/first","adapter":"json"},"admin")
        state=tournament(service,4)
        command(service,state["id"],"start")
        # Disable sending during the test helper's flush, after queue creation.
        original=ext.flush
        ext.flush=lambda:None
        state=round_complete(service,state["id"])
        assert state["deliveries"][0]["status"]=="pending"
        ext.save_config({"enabled":True,"endpoint":"https://example.com/second","adapter":"json"},"admin")
        original()
        assert calls==["https://example.com/first"]
    finally:
        store.close()


def test_finals_roster_frozen_and_no_extra_swiss_after_finished(tmp_path):
    store=Store(tmp_path/"finals.sqlite3")
    service=TournamentService(store,ExternalSync(store))
    try:
        state=tournament(service,8);tid=state["id"]
        command(service,tid,"start");round_complete(service,tid);state=finals(service,tid)
        with pytest.raises(Conflict):
            command(service,tid,"preview_finals",entrants=[p["id"] for p in state["players"][:4]])
        command(service,tid,"finish")
        with pytest.raises(Conflict):
            command(service,tid,"pair")
    finally:
        store.close()


def test_outbox_restart_recovers_interrupted_delivery(tmp_path):
    path=tmp_path/"restart.sqlite3"
    store=Store(path);ext=ExternalSync(store);service=TournamentService(store,ext)
    ext.save_config({"enabled":True,"endpoint":"https://example.com/import","adapter":"json"},"admin")
    ext.flush=lambda:None
    state=tournament(service,4);command(service,state["id"],"start");state=round_complete(service,state["id"])
    key=state["deliveries"][0]["request_id"]
    with store.connect() as db:
        row=db.get(ExternalDelivery,key)
        row.status="sending";row.updated_at="2000-01-01T00:00:00+00:00"
    store.close()
    store=Store(path)
    try:
        ext=ExternalSync(store,lambda *args:(200,{"ok":True}))
        ext.flush()
        assert ext.get(key)["status"]=="success"
    finally:
        store.close()
