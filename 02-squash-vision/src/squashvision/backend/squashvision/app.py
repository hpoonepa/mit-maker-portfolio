import logging
import os
import re
import secrets
import stat
from pathlib import Path, PurePath
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from squashvision.db import Database
from squashvision.exports import cleanup_export_staging
from squashvision.jobs import JobQueue
from squashvision.model_assets import ModelAssetManager, ModelManifest
from squashvision.routes.analysis import router as analysis_router
from squashvision.routes.corrections import router as corrections_router
from squashvision.routes.exports import router as exports_router
from squashvision.routes.frame_map import router as frame_map_router
from squashvision.routes.tracking_stats import router as tracking_stats_router
from squashvision.routes.shot_review import router as shot_review_router
from squashvision.routes.health import router as health_router
from squashvision.routes.jobs import router as jobs_router
from squashvision.routes.models import router as models_router
from squashvision.routes.player_roi import router as player_roi_router
from squashvision.routes.matches import (
    cleanup_orphaned_storage,
    cleanup_pending_deletions,
    router as matches_router,
)
from squashvision.schemas import ApiError, ErrorResponse
from squashvision.settings import Settings
from squashvision.storage import LocalStorage

MULTIPART_OVERHEAD_BYTES = 64 * 1024
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_LOGGER = logging.getLogger("squashvision.api")
_CURSOR_SECRET_BYTES = 32


def _cursor_secret(data_dir: Path) -> bytes:
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".api-cursor.key"
    try:
        secret = path.read_bytes()
    except FileNotFoundError:
        temporary = directory / f".api-cursor-{uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        candidate = secrets.token_bytes(_CURSOR_SECRET_BYTES)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(candidate)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            directory_descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary.unlink(missing_ok=True)
        secret = path.read_bytes()
    if len(secret) != _CURSOR_SECRET_BYTES:
        raise RuntimeError("API cursor secret is invalid")
    os.chmod(path, 0o600)
    return secret


def _request_id(scope: Scope) -> str:
    state = scope.setdefault("state", {})
    existing = state.get("request_id")
    if isinstance(existing, str):
        return existing
    request_id = uuid4().hex
    state["request_id"] = request_id
    return request_id


def _error_content(
    request_id: str,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return ErrorResponse(
        code=code,
        message=message,
        details=details,
        request_id=request_id,
    ).model_dump(mode="json", by_alias=True)


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied: str | None = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                try:
                    supplied = value.decode("ascii")
                except UnicodeDecodeError:
                    supplied = None
                break
        request_id = supplied if supplied and _REQUEST_ID.fullmatch(supplied) else uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        _LOGGER.info(
            "API request request_id=%s method=%s",
            request_id,
            scope.get("method", "UNKNOWN"),
        )

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class _BodyTooLarge(Exception):
    pass


class MatchUploadLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_upload_bytes: int,
        multipart_overhead_bytes: int = MULTIPART_OVERHEAD_BYTES,
    ) -> None:
        self.app = app
        self.raw_limit = max_upload_bytes + multipart_overhead_bytes

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http" or not (
            scope.get("method") == "POST"
            and scope.get("path") == "/api/v1/matches"
        ):
            await self.app(scope, receive, send)
            return

        content_length = next(
            (
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"content-length"
            ),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > self.raw_limit:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.raw_limit:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        request_id = _request_id(scope)
        response = JSONResponse(
            status_code=413,
            content=_error_content(
                request_id,
                "upload_too_large",
                "multipart request exceeds the upload limit",
            ),
            headers={"X-Request-ID": request_id},
        )
        await response(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    *,
    static_dir: Path | None = None,
    run_migrations: bool = True,
) -> FastAPI:
    app = FastAPI(title="Mosaic Squash API", version="1.0.0")
    configured = settings if settings is not None else Settings()
    if configured.storage_root is None:
        raise ValueError("settings.storage_root must be configured")
    app.state.settings = configured

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=_error_content(
                request.state.request_id,
                error.code,
                error.message,
                error.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details: dict[str, object] = {
            "errors": [
                {
                    "location": [str(part) for part in item["loc"]],
                    "type": item["type"],
                }
                for item in error.errors()
            ]
        }
        return JSONResponse(
            status_code=422,
            content=_error_content(
                request.state.request_id,
                "request_validation_failed",
                "request payload failed validation",
                details,
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code = {
            404: "route_not_found",
            405: "method_not_allowed",
        }.get(error.status_code, "http_error")
        return JSONResponse(
            status_code=error.status_code,
            content=_error_content(
                request.state.request_id,
                code,
                "the requested API operation could not be completed",
            ),
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, _error: Exception) -> JSONResponse:
        _LOGGER.error(
            "Unhandled API failure request_id=%s method=%s",
            request.state.request_id,
            request.method,
        )
        return JSONResponse(
            status_code=500,
            content=_error_content(
                request.state.request_id,
                "internal_error",
                "an unexpected internal error occurred",
            ),
            headers={"X-Request-ID": request.state.request_id},
        )
    app.state.database = Database.open(configured, migrate=run_migrations)
    app.state.cursor_secret = _cursor_secret(configured.data_dir)
    app.add_middleware(
        MatchUploadLimitMiddleware,
        max_upload_bytes=configured.max_upload_bytes,
    )
    app.add_middleware(RequestIdMiddleware)
    app.state.storage = LocalStorage(configured.storage_root)
    cleanup_pending_deletions(app.state.database, app.state.storage)
    cleanup_orphaned_storage(app.state.database, app.state.storage)
    cleanup_export_staging(app.state.storage)
    app.state.job_queue = JobQueue(app.state.database, app.state.storage)
    app.state.model_assets = ModelAssetManager(
        app.state.database, app.state.storage
    )
    app.state.model_manifest = ModelManifest(app.state.model_assets)
    app.include_router(analysis_router, prefix="/api/v1")
    app.include_router(player_roi_router, prefix="/api/v1")
    app.include_router(frame_map_router, prefix="/api/v1")
    app.include_router(tracking_stats_router, prefix="/api/v1")
    app.include_router(shot_review_router, prefix="/api/v1")
    app.include_router(corrections_router, prefix="/api/v1")
    app.include_router(exports_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(matches_router, prefix="/api/v1")
    app.include_router(jobs_router, prefix="/api/v1")
    app.include_router(models_router, prefix="/api/v1")
    if static_dir is not None:
        _mount_production_static(app, static_dir)
    return app


_SAFE_SPA_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]*\Z")


def _mount_production_static(app: FastAPI, static_dir: Path) -> None:
    root = Path(static_dir).expanduser().resolve(strict=True)
    index = root / "index.html"
    if (
        not index.is_file()
        or index.is_symlink()
        or not stat.S_ISREG(index.lstat().st_mode)
    ):
        raise ValueError("built web assets must contain a regular index.html")

    @app.api_route(
        "/{spa_path:path}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    def production_static(spa_path: str) -> FileResponse:
        if (
            spa_path == "api"
            or spa_path.startswith("api/")
            or "\\" in spa_path
            or any(ord(character) < 32 or ord(character) == 127 for character in spa_path)
        ):
            raise HTTPException(status_code=404)
        parts = spa_path.split("/") if spa_path else []
        if any(
            not part
            or part in {".", ".."}
            or _SAFE_SPA_COMPONENT.fullmatch(part) is None
            for part in parts
        ):
            raise HTTPException(status_code=404)
        if parts and parts[0] == "assets":
            candidate = root.joinpath(*parts)
            try:
                candidate.resolve(strict=True).relative_to(root)
            except (FileNotFoundError, ValueError):
                raise HTTPException(status_code=404)
            if (
                candidate.suffix == ".map"
                or candidate.is_symlink()
                or not candidate.is_file()
                or not stat.S_ISREG(candidate.lstat().st_mode)
            ):
                raise HTTPException(status_code=404)
            return FileResponse(
                candidate,
                headers={"X-Content-Type-Options": "nosniff"},
            )
        if parts and PurePath(parts[-1]).suffix:
            raise HTTPException(status_code=404)
        return FileResponse(
            index,
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )
