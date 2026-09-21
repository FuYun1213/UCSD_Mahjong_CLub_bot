"""No production Discord traffic: all sends use fakes or an injected HTTP opener."""
import io
import json
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from mahjong_api.discord_reminder_config import DiscordReminderConfig
from mahjong_api.discord_reminder_migrations import migrate_discord_reminders
from mahjong_api.discord_reminder_models import DiscordReminder
from mahjong_api.discord_reminder_sender import DiscordReminderError, DiscordReminderSender, build_message
from mahjong_api.discord_reminder_service import DiscordReminderService
from mahjong_api.reservation_session_models import ReservationSession
from mahjong_api.table_models import ReservationParticipant, TableReservation
from mahjong_api.tournament_models import Tournament
from test_table_v3 import setup, make, data, USERS, ADMIN

GUILD="1278056421224747162"
CHANNEL="111111111111111111"
BOT="222222222222222222"
BOUND="333333333333333333"
NEW_BOUND="444444444444444444"
MESSAGE="555555555555555555"
CONFIG=DiscordReminderConfig(token="isolated-test-secret",guild_id=GUILD,channel_id=CHANNEL)


class FakeSender:
    def __init__(self):
        self.messages=[]
        self.preparations=0
        self.reconciliations=0
        self.prepare_hook=None
        self.send_error=None
        self.remember_uncertain=False
        self.history_error=None

    def prepare(self):
        self.preparations+=1
        if self.prepare_hook:
            self.prepare_hook()
        return {"channel_id":CHANNEL,"bot_user_id":BOT}

    def send(self,destination,payload):
        if self.send_error:
            error,self.send_error=self.send_error,None
            if self.remember_uncertain:
                self.messages.append(payload)
            raise error
        self.messages.append(payload)
        return MESSAGE

    def reconcile(self,channel,bot,nonce,since):
        self.reconciliations+=1
        assert channel==CHANNEL and bot==BOT
        if self.history_error:
            raise self.history_error
        return MESSAGE if any(message["nonce"]==nonce for message in self.messages) else None


@pytest.fixture
def reminders(setup):
    tables,app=setup
    clock=["2026-09-20T17:00:00.000+00:00"]
    tables.clock=lambda:clock[0]
    migrate_discord_reminders(tables.store.engine)
    sender=FakeSender()
    profiles={user.id:{"id":user.id,"name":user.name,"discord_id":BOUND if user==USERS[0] else ""} for user in USERS}
    worker=DiscordReminderService(tables,CONFIG,sender=sender,account_lookup=lambda ids:[profiles[uid] for uid in sorted(ids) if uid in profiles])
    table=make(tables)
    return worker,tables,table,sender,profiles,clock


def reserve(tables,table,*,start="2026-09-20T18:00:00+00:00",end=None,ids=None,actor=USERS[0]):
    return tables.reserve(table["id"],data(start_at=start,
        end_at=end or (datetime.fromisoformat(start)+timedelta(hours=1)).isoformat(),
        participant_ids=ids or [actor.id]),actor)


def jobs(worker):
    with worker.store.connect() as db:
        return list(db.scalars(select(DiscordReminder).order_by(DiscordReminder.created_at,DiscordReminder.start_at_snapshot)))


def advance(clock,seconds):
    clock[0]=(datetime.fromisoformat(clock[0])+timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


def test_scheduled_one_hour_before_start_and_restart_recovers_pending(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table,start="2026-09-20T19:00:00+00:00")
    worker.tick()
    assert len(jobs(worker))==1 and jobs(worker)[0].status=="pending"
    assert jobs(worker)[0].scheduled_for=="2026-09-20T18:00:00.000+00:00"
    assert not sender.messages
    restarted=DiscordReminderService(tables,CONFIG,sender=sender,account_lookup=worker.account_lookup)
    advance(clock,3600)
    restarted.tick();restarted.tick()
    row=jobs(worker)[0]
    assert row.status=="sent" and row.discord_message_id==MESSAGE and row.sent_at
    assert row.attempt_count==1 and len(sender.messages)==1


def test_one_message_for_session_union_and_latest_end_name_binding(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    first=reserve(tables,table,ids=[USERS[0].id,USERS[1].id])
    second=reserve(tables,table,start="2026-09-20T18:20:00+00:00",end="2026-09-20T20:00:00+00:00",ids=[USERS[1].id,USERS[2].id],actor=USERS[1])
    assert first["session_id"]==second["session_id"]
    profiles[USERS[0].id]["discord_id"]=NEW_BOUND
    profiles[USERS[1].id]["name"]="New Registered Name"
    worker.tick()
    assert len(sender.messages)==1
    message=sender.messages[0]
    assert "<@"+NEW_BOUND+">" in message["content"] and BOUND not in message["content"]
    assert "New Registered Name" in message["content"]
    assert f"<t:{int(datetime.fromisoformat(second['end_at']).timestamp())}:F>" in message["content"]
    assert "1 more player for this table" in message["content"]
    assert message["content"].count("New Registered Name")==1
    assert all(user.id not in message["content"] for user in USERS)
    assert message["allowed_mentions"]=={"parse":[],"users":[NEW_BOUND],"roles":[],"replied_user":False}
    assert message["enforce_nonce"] and len(message["nonce"])<=25


@pytest.mark.parametrize("count,phrase",[(2,"2 more players"),(3,"1 more player"),(4,"All seats are reserved.")])
def test_missing_count_plural_and_full(count,phrase):
    message=build_message(table_number=3,start_at="2026-09-20T18:00:00+00:00",end_at="2026-09-20T19:30:00+00:00",
        capacity=4,participants=[{"id":str(i),"name":"Player "+str(i)} for i in range(count)],nonce="test")
    assert phrase in message["content"]
    assert ("We still need" in message["content"]) == (count<4)


def test_content_sanitization_dedup_and_no_negative_gap():
    people=[{"id":"internal-private","name":"@everyone <@&999999999999999999> [click](https://evil.invalid)\n@here"}]*2
    message=build_message(table_number=3,start_at="2026-09-20T18:00:00+00:00",end_at="2026-09-20T19:30:00+00:00",
        capacity=0,participants=people,nonce="test")
    assert "@everyone" not in message["content"] and "@here" not in message["content"]
    assert "<@&" not in message["content"] and "internal-private" not in message["content"]
    assert message["content"].count("• ")==1
    assert "need -" not in message["content"]
    assert message["allowed_mentions"]["users"]==[]


def test_late_creation_sends_once_future_only(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table,start="2026-09-20T17:30:00+00:00")
    worker.tick();worker.tick()
    assert len(sender.messages)==1
    past_table=make(tables,9)
    reserve(tables,past_table,start="2026-09-20T16:59:59+00:00")
    exact_table=make(tables,10)
    reserve(tables,exact_table,start=clock[0])
    worker.tick()
    assert len(sender.messages)==1 and len(jobs(worker))==1


def test_individual_edit_without_session_start_change_never_resends_new_start_does(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    first=reserve(tables,table)
    second=reserve(tables,table,start="2026-09-20T18:20:00+00:00",actor=USERS[1])
    worker.tick()
    tables.update_reservation(second["id"],{"version":1,"start_at":"2026-09-20T18:30:00+00:00","end_at":"2026-09-20T20:00:00+00:00"},USERS[1])
    worker.tick()
    assert len(sender.messages)==1
    tables.update_reservation(first["id"],{"version":1,"status":"cancelled"},USERS[0])
    advance(clock,1800)
    worker.tick();worker.tick()
    assert len(sender.messages)==2 and len(jobs(worker))==2
    assert sender.messages[0]["nonce"]!=sender.messages[1]["nonce"]


@pytest.mark.parametrize("mode",["cancelled","completed","deleted","closed","bad_scope","tournament_deleted"])
def test_invalid_session_never_sends(reminders,mode):
    worker,tables,table,sender,profiles,clock=reminders
    if mode=="tournament_deleted":
        tournament=tables.tournaments.create(data(name="Reminder test event"),ADMIN.id)
        table=make(tables,7,tournament["id"])
    row=reserve(tables,table)
    worker.plan()
    if mode in {"cancelled","completed"}:
        tables.update_reservation(row["id"],{"version":1,"status":mode},ADMIN)
    elif mode=="closed":
        tables.update(table["id"],{"status":"closed"},ADMIN)
    elif mode=="deleted":
        with tables.store.connect() as db:
            db.execute(delete(ReservationParticipant).where(ReservationParticipant.reservation_id==row["id"]))
            db.execute(delete(TableReservation).where(TableReservation.id==row["id"]))
            db.execute(delete(ReservationSession).where(ReservationSession.id==row["session_id"]))
    elif mode=="bad_scope":
        with tables.store.connect() as db:
            db.get(ReservationSession,row["session_id"]).scope="other:venue"
    else:
        with tables.store.connect() as db:
            db.get(Tournament,table["tournament_id"]).deleted_at=clock[0]
    worker.tick()
    assert not sender.messages
    assert all(job.status=="cancelled" for job in jobs(worker))


def test_cancelled_participant_not_mentioned_and_counts_latest_union(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    first=reserve(tables,table)
    second=reserve(tables,table,ids=[USERS[1].id,USERS[2].id],actor=USERS[1])
    tables.update_reservation(second["id"],{"version":1,"status":"cancelled"},USERS[1])
    worker.tick()
    assert "3 more players" in sender.messages[0]["content"]
    assert USERS[1].name not in sender.messages[0]["content"]


def test_missing_config_disabled_and_permanent_failure_do_not_block_reservations(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    worker.config=DiscordReminderConfig(enabled=False)
    worker.tick()
    assert jobs(worker)[0].last_error=="reminders_disabled" and sender.preparations==0
    worker.config=DiscordReminderConfig()
    advance(clock,61);worker.tick()
    assert jobs(worker)[0].last_error=="missing_configuration" and sender.preparations==0
    worker.config=CONFIG
    sender.prepare_hook=lambda:(_ for _ in ()).throw(DiscordReminderError("missing_channel_permissions"))
    advance(clock,61);worker.tick()
    assert jobs(worker)[0].status=="failed" and jobs(worker)[0].last_error=="missing_channel_permissions"
    assert tables.get(table["id"],USERS[0])["reservations"][0]["status"]=="active"


def test_429_backoff_then_retry_uses_same_nonce(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    sender.send_error=DiscordReminderError("rate_limited",retryable=True,retry_after=90)
    worker.tick()
    row=jobs(worker)[0]
    assert row.status=="retrying" and not row.delivery_uncertain
    assert row.next_attempt_at=="2026-09-20T17:01:30.000+00:00"
    worker.tick();assert sender.preparations==1
    advance(clock,90);worker.tick()
    assert jobs(worker)[0].status=="sent" and len(sender.messages)==1
    assert sender.messages[0]["nonce"]==row.nonce


def test_preflight_temporary_failure_retries_without_an_uncertain_post(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    sender.prepare_hook=lambda:(_ for _ in ()).throw(DiscordReminderError("discord_network_error",retryable=True))
    worker.tick()
    assert jobs(worker)[0].status=="retrying" and not jobs(worker)[0].delivery_uncertain
    sender.prepare_hook=None;advance(clock,11);worker.tick()
    assert jobs(worker)[0].status=="sent"


@pytest.mark.parametrize("delivered",[True,False])
def test_uncertain_post_reconciles_or_fails_closed_never_reposts(reminders,delivered):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    sender.remember_uncertain=delivered
    sender.send_error=DiscordReminderError("discord_network_error",retryable=True,uncertain=True)
    worker.tick()
    assert jobs(worker)[0].delivery_uncertain
    advance(clock,31);worker.tick();advance(clock,300);worker.tick()
    row=jobs(worker)[0]
    assert row.status==("sent" if delivered else "failed")
    assert row.last_error==(None if delivered else "delivery_unknown")
    assert len(sender.messages)==int(delivered) and sender.preparations==1
    assert sender.reconciliations==1


def test_success_then_local_db_failure_survives_restart_without_duplicate(reminders,monkeypatch):
    worker,tables,table,sender,profiles,clock=reminders
    row=reserve(tables,table)
    monkeypatch.setattr(worker,"_record_sent",lambda *args:(_ for _ in ()).throw(RuntimeError("simulated local write failure")))
    worker.tick()
    assert len(sender.messages)==1 and jobs(worker)[0].status=="processing"
    assert jobs(worker)[0].delivery_uncertain
    # Even cancellation after Discord success cannot erase the delivery evidence.
    tables.update_reservation(row["id"],{"version":1,"status":"cancelled"},USERS[0])
    restarted=DiscordReminderService(tables,CONFIG,sender=sender,account_lookup=worker.account_lookup)
    advance(clock,121);restarted.tick()
    assert jobs(worker)[0].status=="sent" and len(sender.messages)==1


def test_two_workers_claim_once(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    worker.plan()
    second=DiscordReminderService(tables,CONFIG,sender=sender,account_lookup=worker.account_lookup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda runner:runner.tick(),[worker,second]))
    assert len(sender.messages)==1 and jobs(worker)[0].attempt_count==1


def test_cancel_commit_wins_before_final_send_gate(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    row=reserve(tables,table)
    entered,released=threading.Event(),threading.Event()
    sender.prepare_hook=lambda:(entered.set(),released.wait(timeout=10))
    with ThreadPoolExecutor(max_workers=2) as pool:
        task=pool.submit(worker.tick)
        assert entered.wait(timeout=5)
        tables.update_reservation(row["id"],{"version":1,"status":"cancelled"},USERS[0])
        released.set();task.result(timeout=10)
    assert not sender.messages and jobs(worker)[0].status=="cancelled"


def test_account_file_is_read_fresh_by_stable_id_and_never_modified(reminders,tmp_path):
    worker,tables,table,sender,profiles,clock=reminders
    row=reserve(tables,table,ids=[USERS[0].id,USERS[1].id])
    path=tmp_path/"accounts.json"
    accounts={"users":{
        "renamed":{"account_id":USERS[0].id,"name":"Renamed Website User","registeredName":"Renamed Website User","discord_id":NEW_BOUND,"discord_name":"new nickname","avatar":"data:image/png;base64,userupload","password_hash":"test-only"},
        "unbound":{"account_id":USERS[1].id,"name":"Unbound Website User","avatar":"cached-discord-avatar"}}}
    path.write_text(json.dumps(accounts),encoding="utf-8")
    before=path.read_bytes()
    production_reader=DiscordReminderService(tables,CONFIG,sender=sender,account_path=path)
    production_reader.tick()
    assert path.read_bytes()==before
    assert "<@"+NEW_BOUND+">" in sender.messages[0]["content"]
    assert "Unbound Website User" in sender.messages[0]["content"]
    assert "test-only" not in json.dumps(sender.messages) and "avatar" not in json.dumps(sender.messages)


class Response:
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.value).encode()


class Opener:
    def __init__(self):self.calls=[];self.failure=None;self.channel_guild=GUILD;self.permissions=1024|2048|65536;self.history=[]
    def __call__(self,request,timeout):
        self.calls.append(request)
        if self.failure:raise self.failure
        path=request.full_url.split("/api/v10")[-1]
        values={"/channels/"+CHANNEL:{"id":CHANNEL,"guild_id":self.channel_guild,"type":0,"permission_overwrites":[]},
                "/users/@me":{"id":BOT,"bot":True},"/guilds/"+GUILD+"/members/"+BOT:{"roles":[]},
                "/guilds/"+GUILD+"/roles":[{"id":GUILD,"permissions":str(self.permissions)}]}
        if request.method=="POST":return Response({"id":MESSAGE})
        if "messages?" in path:return Response(self.history)
        return Response(values[path])


def test_sender_checks_guild_permissions_and_explicit_allowed_mentions():
    opener=Opener();sender=DiscordReminderSender(CONFIG,opener=opener)
    destination=sender.prepare()
    payload=build_message(table_number=3,start_at="2026-09-20T18:00:00+00:00",end_at="2026-09-20T19:00:00+00:00",
        capacity=4,participants=[{"id":"private","name":"Unknown","discord_id":BOUND}],nonce="safe-nonce")
    assert sender.send(destination,payload)==MESSAGE
    request=opener.calls[-1]
    assert request.method=="POST" and request.full_url=="https://discord.com/api/v10/channels/"+CHANNEL+"/messages"
    assert json.loads(request.data)["allowed_mentions"]["users"]==[BOUND]
    opener.channel_guild="999999999999999999"
    with pytest.raises(DiscordReminderError,match="channel_guild_mismatch"):sender.prepare()
    opener.channel_guild=GUILD;opener.permissions=1024
    with pytest.raises(DiscordReminderError,match="missing_channel_permissions"):sender.prepare()


def test_sender_rate_limit_and_safe_errors_never_include_secrets(caplog):
    opener=Opener();sender=DiscordReminderSender(CONFIG,opener=opener)
    headers=Message();headers["Retry-After"]="20"
    opener.failure=urllib.error.HTTPError("https://discord.com",429,"SECRET SHOULD NOT LEAK",headers,io.BytesIO(b'{"retry_after":42.5,"token":"secret"}'))
    with pytest.raises(DiscordReminderError) as caught:sender.prepare()
    assert caught.value.retry_after==42.5 and caught.value.retryable
    assert "SECRET" not in str(caught.value) and "secret" not in caplog.text
    for code,error in [(401,"invalid_bot_token"),(403,"missing_channel_permissions"),(404,"channel_not_found")]:
        opener.failure=urllib.error.HTTPError("https://discord.com",code,"SECRET",headers,io.BytesIO(b"SECRET"))
        with pytest.raises(DiscordReminderError,match=error):sender.prepare()
    opener.failure=urllib.error.URLError("SECRET Authorization Bot isolated-test-secret")
    with pytest.raises(DiscordReminderError) as caught:sender.send({"channel_id":CHANNEL},{})
    assert caught.value.uncertain and "isolated-test-secret" not in str(caught.value)


def test_history_requires_positive_nonce_and_same_bot_evidence():
    opener=Opener();sender=DiscordReminderSender(CONFIG,opener=opener)
    opener.history=[{"id":MESSAGE,"nonce":"nonce","author":{"id":NEW_BOUND},"timestamp":"2026-09-20T17:00:01+00:00"}]
    assert sender.reconcile(CHANNEL,BOT,"nonce","2026-09-20T17:00:00+00:00") is None
    opener.history[0]["author"]["id"]=BOT
    assert sender.reconcile(CHANNEL,BOT,"nonce","2026-09-20T17:00:00+00:00")==MESSAGE
    del opener.history[0]["nonce"]
    assert sender.reconcile(CHANNEL,BOT,"nonce","2026-09-20T17:00:00+00:00") is None


def test_config_disabled_and_missing_channel_do_not_read_or_expose_token(monkeypatch):
    monkeypatch.setenv("DISCORD_RESERVATION_REMINDERS_ENABLED","false")
    monkeypatch.setenv("DISCORD_BOT_TOKEN","do-not-print-test-token")
    monkeypatch.setenv("DISCORD_RESERVATION_REMINDER_CHANNEL_ID",CHANNEL)
    config=DiscordReminderConfig.from_env()
    assert not config.enabled and not config.token and "do-not-print-test-token" not in repr(config)
    monkeypatch.setenv("DISCORD_RESERVATION_REMINDERS_ENABLED","true")
    monkeypatch.delenv("DISCORD_RESERVATION_REMINDER_CHANNEL_ID")
    monkeypatch.delenv("DISCORD_GAME_RECORD_CHANNEL_ID",raising=False)
    config=DiscordReminderConfig.from_env()
    assert not config.configured and not config.token


def test_migration_idempotent_preserves_outbox_and_unique_version(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table);worker.plan()
    before=jobs(worker)[0]
    migrate_discord_reminders(tables.store.engine);migrate_discord_reminders(tables.store.engine)
    worker.plan()
    assert len(jobs(worker))==1 and jobs(worker)[0].id==before.id and jobs(worker)[0].nonce==before.nonce


def _process_tick(database,profiles,messages,barrier):
    """Spawned process, separate engine and no shared Python lock."""
    from mahjong_api.store import Store
    store=Store(Path(database))
    tables=SimpleNamespace(store=store,clock=lambda:"2026-09-20T17:00:00.000+00:00")
    class Sender:
        def prepare(self):return {"channel_id":CHANNEL,"bot_user_id":BOT}
        def send(self,destination,payload):messages.append(payload);return MESSAGE
        def reconcile(self,*args):return None
    worker=DiscordReminderService(tables,CONFIG,sender=Sender(),account_lookup=lambda ids:[profiles[uid] for uid in sorted(ids)])
    try:
        barrier.wait(timeout=20)
        return worker.tick()
    finally:
        store.close()


def test_separate_processes_share_db_claim_and_send_once(reminders):
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import Manager
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table);worker.plan()
    with Manager() as manager:
        messages=manager.list();barrier=manager.Barrier(2)
        with ProcessPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(_process_tick,str(tables.store.path),profiles,messages,barrier) for _ in range(2)]
            for task in tasks:task.result(timeout=40)
        assert len(messages)==1
    assert jobs(worker)[0].status=="sent" and jobs(worker)[0].attempt_count==1


def test_actual_commit_failure_preserves_pre_send_fence(reminders,monkeypatch):
    from contextlib import contextmanager
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    original=tables.store.connect
    @contextmanager
    def failing_commit():
        with original() as db:
            yield db
            if any(isinstance(row,DiscordReminder) and row.status=="sent" for row in db.identity_map.values()):
                raise RuntimeError("simulated commit failure with private SQL context")
    monkeypatch.setattr(tables.store,"connect",failing_commit)
    worker.tick()
    monkeypatch.setattr(tables.store,"connect",original)
    row=jobs(worker)[0]
    assert row.status=="processing" and row.delivery_uncertain and len(sender.messages)==1
    advance(clock,121)
    restarted=DiscordReminderService(tables,CONFIG,sender=sender,account_lookup=worker.account_lookup)
    restarted.tick()
    assert jobs(worker)[0].status=="sent" and len(sender.messages)==1


def test_stale_worker_lease_cannot_post_after_replacement_claim(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    entered,released=threading.Event(),threading.Event()
    sender.prepare_hook=lambda:(entered.set(),released.wait(timeout=10))
    replacement_sender=FakeSender()
    replacement=DiscordReminderService(tables,CONFIG,sender=replacement_sender,account_lookup=worker.account_lookup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(worker.tick)
        assert entered.wait(timeout=5)
        advance(clock,121)
        replacement.tick()
        released.set();first.result(timeout=10)
    assert not sender.messages and len(replacement_sender.messages)==1
    assert jobs(worker)[0].status=="sent"


def test_429_cooldown_is_shared_by_other_jobs_and_workers(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    other=make(tables,8)
    reserve(tables,other,actor=USERS[1])
    sender.send_error=DiscordReminderError("rate_limited",retryable=True,retry_after=90)
    worker.tick()
    assert sender.preparations==1 and not sender.messages
    second=DiscordReminderService(tables,CONFIG,sender=sender,account_lookup=worker.account_lookup)
    second.tick();assert sender.preparations==1
    advance(clock,90);second.tick()
    assert len(sender.messages)==2 and all(row.status=="sent" for row in jobs(worker))


def test_unsent_start_version_can_be_restored_without_resetting_sent_evidence(reminders):
    worker,tables,table,sender,profiles,clock=reminders
    reservation=reserve(tables,table,start="2026-09-20T19:00:00+00:00")
    worker.plan()
    original=jobs(worker)[0]
    tables.update_reservation(reservation["id"],{"version":1,"start_at":"2026-09-20T20:00:00+00:00","end_at":"2026-09-20T21:00:00+00:00"},USERS[0])
    worker.plan()
    assert next(row for row in jobs(worker) if row.id==original.id).status=="cancelled"
    tables.update_reservation(reservation["id"],{"version":2,"start_at":"2026-09-20T19:00:00+00:00","end_at":"2026-09-20T20:00:00+00:00"},USERS[0])
    worker.plan();advance(clock,3600);worker.tick();worker.tick()
    assert len(sender.messages)==1 and sender.messages[0]["nonce"]==original.nonce
    assert next(row for row in jobs(worker) if row.id==original.id).status=="sent"


@pytest.fixture
def slow_discord():
    import time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    entered=threading.Event();closed=threading.Event();posts=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length","0")))
            posts.append(self.path);entered.set()
            payload=json.dumps({"id":MESSAGE}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Length",str(len(payload)))
                self.end_headers()
                for byte in payload:
                    self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(.03)
            except OSError:
                closed.set()
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    runner=threading.Thread(target=server.serve_forever,daemon=True);runner.start()
    try:yield server,entered,closed,posts
    finally:server.shutdown();server.server_close();runner.join(timeout=2)


def test_post_deadline_aborts_slow_drip_without_background_send(slow_discord):
    import http.client
    import time
    server,entered,closed,posts=slow_discord
    sender=DiscordReminderSender(CONFIG,opener=Opener(),deadline_seconds=.12,
        connection_factory=lambda:http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=1))
    prepared=sender.prepare()
    started=time.monotonic()
    with pytest.raises(DiscordReminderError) as caught:
        sender.send(prepared,{"content":"isolated test"})
    assert caught.value.uncertain
    assert time.monotonic()-started<.5
    assert prepared["_connection"].sock is None
    assert closed.wait(timeout=1)
    assert len(posts)==1


def test_slow_discord_holds_db_less_than_short_busy_timeout(reminders,slow_discord):
    import http.client
    import time
    from sqlalchemy import event
    worker,tables,table,fake,profiles,clock=reminders
    reserve(tables,table)
    # Scale the real 5s POST / 30s busy-timeout relationship to a fast test.
    @event.listens_for(tables.store.engine,"connect")
    def short_busy(connection,record):connection.execute("PRAGMA busy_timeout=500")
    tables.store.engine.dispose()
    server,entered,closed,posts=slow_discord
    worker.sender=DiscordReminderSender(CONFIG,opener=Opener(),deadline_seconds=.1,
        connection_factory=lambda:http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending=pool.submit(worker.tick)
        assert entered.wait(timeout=5)
        started=time.monotonic()
        created=reserve(tables,table,start="2026-09-20T18:20:00+00:00",actor=USERS[1])
        elapsed=time.monotonic()-started
        sending.result(timeout=5)
    assert created["status"]=="active" and elapsed<.5
    assert len(posts)==1 and jobs(worker)[0].delivery_uncertain
    assert jobs(worker)[0].status=="retrying"


def test_final_account_lock_is_nonblocking_and_retries_without_post(reminders,tmp_path):
    import registered_names
    import time
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    path=tmp_path/"accounts.json"
    path.write_text(json.dumps({"users":{"alice":{"account_id":USERS[0].id,"name":"Alice"}}}),encoding="utf-8")
    actual=DiscordReminderService(tables,CONFIG,sender=sender,account_path=path)
    held,release=threading.Event(),threading.Event()
    def hold():
        with registered_names.account_lock(path):held.set();release.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        def prepare_hook():
            pool.submit(hold)
            assert held.wait(timeout=2)
        sender.prepare_hook=prepare_hook
        started=time.monotonic()
        try:
            actual.tick()
            assert time.monotonic()-started<.5
            assert not sender.messages
            assert jobs(actual)[0].last_error=="account_directory_busy"
            assert not jobs(actual)[0].delivery_uncertain
            assert reserve(tables,table,actor=USERS[1])["status"]=="active"
        finally:release.set()
    with registered_names.account_lock(path,blocking=False):
        with registered_names.account_lock(path,blocking=False):pass


@pytest.mark.parametrize("pending_kind",["file","rename"])
def test_new_account_recovery_after_preflight_is_not_read_or_published_under_db_gate(reminders,tmp_path,pending_kind):
    import registered_names
    import sqlite3
    worker,tables,table,sender,profiles,clock=reminders
    reserve(tables,table)
    path=tmp_path/"accounts.json"
    path.write_text(json.dumps({"users":{"alice":{"account_id":USERS[0].id,"name":"Alice","avatar":"keep"}}}),encoding="utf-8")
    registered_names.ensure_directory(path)
    before=path.read_bytes()
    def new_pending():
        if pending_kind=="file":
            Path(str(path)+".pending").write_text(json.dumps({"users":{}}),encoding="utf-8")
        else:
            with sqlite3.connect(registered_names.database_path(path)) as db:
                db.execute("INSERT INTO pending_registered_name_changes(operation_id,account_id,old_name,new_name,club_database,old_role) VALUES(?,?,?,?,?,?)",
                           ("isolated-pending",USERS[0].id,"Alice","New Alice","unused","user"))
    sender.prepare_hook=new_pending
    actual=DiscordReminderService(tables,CONFIG,sender=sender,account_path=path)
    actual.tick()
    assert not sender.messages and path.read_bytes()==before
    assert jobs(actual)[0].last_error=="account_recovery_pending"
    assert not jobs(actual)[0].delivery_uncertain


def _hold_account_file(path,entered,release):
    import registered_names
    with registered_names.account_lock(path):entered.set();release.wait(timeout=15)


def test_account_nonblocking_cross_process_lock_releases_after_failure(tmp_path):
    import registered_names
    import time
    from multiprocessing import Manager
    from concurrent.futures import ProcessPoolExecutor
    path=tmp_path/"account-lock.json"
    with Manager() as manager:
        entered,release=manager.Event(),manager.Event()
        with ProcessPoolExecutor(max_workers=1) as pool:
            task=pool.submit(_hold_account_file,str(path),entered,release)
            assert entered.wait(timeout=10)
            try:
                started=time.monotonic()
                with pytest.raises(TimeoutError):
                    with registered_names.account_lock(path,blocking=False):pass
                assert time.monotonic()-started<.2
            finally:release.set()
            task.result(timeout=10)
    with registered_names.account_lock(path,blocking=False):pass


def test_prepared_connection_is_closed_on_cancellation_before_post(reminders):
    worker,tables,table,fake,profiles,clock=reminders
    reserved=reserve(tables,table)
    class Connection:
        closed=False
        def connect(self):tables.update_reservation(reserved["id"],{"version":1,"status":"cancelled"},USERS[0])
        def close(self):self.closed=True
    connection=Connection()
    worker.sender=DiscordReminderSender(CONFIG,opener=Opener(),connection_factory=lambda:connection)
    worker.tick()
    assert connection.closed and jobs(worker)[0].status=="cancelled"
