import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .auth import check_cookie_origin, get_current_user, require_yolo_key
from .config import Settings
from .models import ConfirmScores, RelativeSubmission, Seat, SubmitScores, TableId, User
from .runtime import single_writer
from .service import MatchService
from .sheets import DisabledSheets, GSpreadSheets, SheetsSink
from .store import Conflict, Store, now
from .external_sync import ExternalSync
from .tournament import TournamentService
from .tournament_routes import router as tournament_router
from .table_routes import router as table_router
from .table_service import TableService
from .reservation_reminder_routes import router as reservation_reminder_router
from .seat_swap_service import SeatSwapService
from .discord_reminder_service import DiscordReminderService
from .seat_swap_routes import router as seat_swap_router
from .manual_score import ManualScoreService
from .manual_score_routes import router as manual_score_router
from .logging_filters import install_token_redaction

logger = logging.getLogger(__name__)
CurrentUser = Annotated[User, Depends(get_current_user)]
RequestKey = Annotated[str | None, Header(min_length=1, max_length=128)]


def create_app(settings: Settings | None = None, sheets: SheetsSink | None = None, vision=None):
    settings = settings or Settings.from_env()
    install_token_redaction()

    @asynccontextmanager
    async def lifespan(app):
        with single_writer(settings):
            sink = sheets if sheets is not None else (GSpreadSheets(settings) if settings.sheets_enabled else DisabledSheets())
            if settings.club_database_path:
                from .club_history import ClubHistorySink
                sink = ClubHistorySink(sink, settings.club_database_path)
            database = Store(settings.database_path, settings.database_url)
            try:
                service = MatchService(database, sink, settings)
                app.state.service = service
                app.state.external = service.external
                app.state.tournaments = TournamentService(database, service.external)
                app.state.tables = TableService(service, app.state.tournaments)
                app.state.seat_swaps = SeatSwapService(app.state.tables)
                app.state.discord_reminders = DiscordReminderService(app.state.tables)
                if settings.club_database_path:
                    sink.account_lookup = app.state.tables._account_rows
                    sink.account_path = Path(os.getenv("TABLE_ACCOUNT_FILE", str(Path(__file__).resolve().parents[1] / "web_users.json")))
                app.state.manual_scores = ManualScoreService(service, app.state.tables)
                app.state.vision = vision
                if settings.vision_enabled and vision is None:
                    from .vision import LCDRecognizer
                    app.state.vision = LCDRecognizer(settings.vision_directory, settings.vision_confidence)
                if not sink.enabled:
                    logger.warning("Sheets disabled; data stored locally only")
                if settings.mock_auth_enabled:
                    logger.warning("Demo authentication enabled")
                await asyncio.to_thread(service.flush)
                await asyncio.to_thread(app.state.manual_scores.flush)
                stop = asyncio.Event()

                async def retry_sync():
                    while not stop.is_set():
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=settings.sync_interval_seconds)
                        except asyncio.TimeoutError:
                            try:
                                await asyncio.to_thread(service.flush)
                                await asyncio.to_thread(app.state.manual_scores.flush)
                                await asyncio.to_thread(service.external.flush)
                            except Exception:
                                logger.exception("Sync worker failed; will retry")

                async def reservation_reminders():
                    # Independent persisted scheduler: ordinary requests and the
                    # existing Sheets/external retry worker do not wait for Discord.
                    while not stop.is_set():
                        try:
                            await asyncio.to_thread(app.state.discord_reminders.tick, limit=10)
                        except Exception:
                            # Sender errors are stored as bounded codes. Never log
                            # arbitrary exception text/headers from a remote client.
                            logger.warning("Discord reservation scheduler failed; will retry")
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=15)
                        except asyncio.TimeoutError:
                            pass

                worker = asyncio.create_task(retry_sync())
                reminder_worker = asyncio.create_task(reservation_reminders())
                try:
                    yield
                finally:
                    stop.set()
                    await asyncio.gather(worker, reminder_worker)
            finally:
                database.close()

    app = FastAPI(title="麻将 NFC / 照片 OCR 自动登分 API", version="2.1.0", lifespan=lifespan)
    app.state.settings = settings
    from .guest_routes import router as guest_router
    app.include_router(guest_router)
    app.include_router(tournament_router)
    app.include_router(table_router)
    app.include_router(reservation_reminder_router)
    app.include_router(seat_swap_router)
    app.include_router(manual_score_router)
    if settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
            allow_credentials=True, allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Idempotency-Key"])

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        if (request.url.path.startswith("/api/") and 200 <= response.status_code < 300
                and "application/json" in response.headers.get("content-type", "")
                and hasattr(app.state, "tables")):
            body = b"".join([part async for part in response.body_iterator])
            value = await asyncio.to_thread(app.state.tables.display_names, json.loads(body))
            headers = {key: value for key, value in response.headers.items() if key.lower() not in {"content-length", "content-type"}}
            return JSONResponse(value, status_code=response.status_code, headers=headers)
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=410 if exc.detail["code"] == "tournament_deleted" else 403 if exc.detail["code"] in {"admin_required", "not_assigned", "reservation_not_owner", "must_join_first", "swap_not_target", "swap_not_requester"} else 409, content={"detail": exc.detail})

    @app.api_route("/api/sit", methods=["GET", "POST"], dependencies=[Depends(check_cookie_origin)])
    def sit(request: Request, table: TableId, seat: Seat, user: CurrentUser):
        table = request.app.state.tables.resolve_score_id(table)
        body, status = request.app.state.service.sit(table, seat.value, user)
        return JSONResponse(status_code=status, content=body)

    @app.post("/api/submit_scores", dependencies=[Depends(check_cookie_origin)])
    def submit_scores(request: Request, payload: RelativeSubmission, user: CurrentUser, idempotency_key: RequestKey = None):
        # The uploader comes ONLY from authenticated credentials, never a JSON user_id.
        body, status = request.app.state.service.submit_relative(payload, user, idempotency_key)
        return JSONResponse(status_code=status, content=body)

    @app.post("/api/confirm_scores", dependencies=[Depends(check_cookie_origin)])
    def confirm_scores(request: Request, payload: ConfirmScores, user: CurrentUser):
        body, status = request.app.state.service.confirm(payload.draft_id, payload.scores.model_dump(), user)
        return JSONResponse(status_code=status, content=body)

    @app.get("/api/score_drafts/{draft_id}")
    def score_draft(request: Request, draft_id: str, user: CurrentUser):
        service = request.app.state.service
        with service.lock:
            draft = service.get_draft(draft_id, user)
            body = service._review_response(draft)
            body["draft_status"] = draft["status"]
            return body

    @app.get("/api/tables/{table}")
    def get_table(request: Request, table: TableId, user: CurrentUser):
        result = request.app.state.service.table(table)
        if result is None:
            raise HTTPException(404, detail={"code": "table_not_found"})
        return result

    @app.get("/api/statistics")
    def statistics(request: Request, user: CurrentUser, table: str | None = None):
        service = request.app.state.service
        with service.lock:
            return {"overall": service.store.stats(table_id=table),
                    "player": service.store.stats(table_id=table, user_id=user.id)}

    @app.post("/api/recognize_photo", dependencies=[Depends(check_cookie_origin)])
    async def recognize_photo(
        request: Request, user: CurrentUser, file: Annotated[UploadFile, File()],
        table: Annotated[str, Form(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")],
        match_id: Annotated[str, Form(min_length=1, max_length=64)],
        regions: Annotated[str | None, Form()] = None,
        review_only: Annotated[bool, Form()] = False,
        idempotency_key: RequestKey = None,
    ):
        recognizer = request.app.state.vision
        if recognizer is None:
            raise HTTPException(503, detail={"code": "vision_not_configured", "message": "请安装并启用照片识别组件"})
        service = request.app.state.service
        ended_at = now()
        content = await file.read(settings.max_photo_bytes + 1)
        await file.close()
        if len(content) > settings.max_photo_bytes:
            raise HTTPException(413, detail={"code": "photo_too_large"})
        try:
            regions_value = json.loads(regions) if regions else None
            photo_hash = hashlib.sha256(content + json.dumps(regions_value, sort_keys=True, allow_nan=False).encode()).hexdigest()
            context, replay = await asyncio.to_thread(service.photo_context, table, match_id, user, idempotency_key, photo_hash)
            if replay:
                body, status = replay
                return JSONResponse(status_code=status, content=body)
            recognized = await asyncio.to_thread(recognizer.recognize, content, regions_value)
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(422, detail={"code": "invalid_photo", "message": str(exc)}) from exc
        except (ImportError, FileNotFoundError) as exc:
            logger.exception("OCR runtime is not installed")
            raise HTTPException(503, detail={"code": "vision_not_configured"}) from exc
        payload = RelativeSubmission(table=table, match_id=match_id, scores=recognized["scores"])
        body, status = await asyncio.to_thread(service.submit_relative, payload, user, idempotency_key,
            recognized.get("issues", []) + ([{"code": "manual_confirmation_requested"}] if review_only else []), ended_at, context["seats"], photo_hash)
        body["recognition"] = recognized
        return JSONResponse(status_code=status, content=body)

    # Compatibility route for the first implementation's machine-only absolute scores.
    @app.post("/api/submit_absolute_scores", dependencies=[Depends(require_yolo_key)], deprecated=True)
    def submit_absolute(request: Request, payload: SubmitScores, idempotency_key: RequestKey = None):
        try:
            body, status = request.app.state.service.submit(payload, idempotency_key)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "invalid_score_total", "message": str(exc)}) from exc
        return JSONResponse(status_code=status, content=body)

    @app.get("/api/machine/tables/{table}", dependencies=[Depends(require_yolo_key)])
    def machine_table(request: Request, table: TableId):
        result = request.app.state.service.table(table)
        if result is None:
            raise HTTPException(404, detail={"code": "table_not_found"})
        return result

    @app.post("/api/sync", dependencies=[Depends(require_yolo_key)])
    def sync(request: Request):
        remaining = request.app.state.service.flush()
        return {"status": "pending" if any(remaining.values()) else "success", "remaining": remaining}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/score", include_in_schema=False)
    @app.get("/sit", include_in_schema=False)
    def score_page(request: Request):
        if request.query_params.get("embedded") != "1":
            from fastapi.responses import RedirectResponse
            from urllib.parse import urlencode
            return RedirectResponse("/?" + urlencode({"page": "record", **{k: v for k, v in request.query_params.items() if k in {"table", "draft_id"}}}), status_code=302)
        return FileResponse(Path(__file__).with_name("static") / "score.html")

    return app


app = create_app()
