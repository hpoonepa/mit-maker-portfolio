from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from squashvision.db import Database
from squashvision.jobs import ACTIVE_STATES
from squashvision.media import MediaError, create_proxy, ingest_upload, probe_video
from squashvision.model_assets import ResolvedAsset, public_source_label
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    Calibration,
    JobChunk,
    Match,
    MediaAsset,
    PendingDeletion,
    ReportRevision,
)
from squashvision.schemas import (
    ApiError,
    ErrorResponse,
    MatchDetail,
    MatchListPage,
    MatchMetadata,
    MatchQualitySummary,
    MatchSummary,
    MatchUpdateRequest,
    MediaAssetDetail,
    ModelAssetDetail,
    PreparationState,
    ProcessingSummary,
    ReportSummary,
    decode_api_cursor,
    encode_api_cursor,
)
from squashvision.settings import Settings
from squashvision.storage import LocalStorage

router = APIRouter(
    prefix="/matches",
    tags=["matches"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)


def _safe_media_error(error: MediaError) -> ApiError:
    messages = {
        "upload_too_large": "uploaded media exceeds the configured size limit",
        "insufficient_disk": "insufficient disk space is available for this upload",
        "unsupported_container": "supported containers are MP4, MOV, M4V, or WebM",
        "no_video_stream": "uploaded media does not contain a video track",
        "invalid_duration": "uploaded video duration could not be read safely",
        "duration_exceeded": "uploaded video exceeds the 60-minute duration limit",
        "invalid_media": "uploaded video could not be decoded safely",
        "proxy_failed": "uploaded video timestamps could not be mapped safely",
        "media_tool_unavailable": "required local media processing is unavailable",
        "media_tool_timeout": "local media processing timed out",
    }
    return ApiError(
        error.code,
        messages.get(error.code, "uploaded media could not be processed"),
        error.status_code,
    )


def _remove_generated(paths: list[Path]) -> None:
    for path in reversed(paths):
        path.unlink(missing_ok=True)


def _file_signature(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()

def _descriptor_signature(descriptor: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while block := os.read(descriptor, 1024 * 1024):
            size += len(block)
            digest.update(block)
    finally:
        os.lseek(descriptor, position, os.SEEK_SET)
    return size, digest.hexdigest()


def _version(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(1, int(value.timestamp() * 1_000_000))


_MATCH_CURSOR_BINDING: dict[str, object] = {"kind": "matches"}


def _cursor_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ApiError("invalid_cursor", "pagination cursor is invalid", 422)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ApiError("invalid_cursor", "pagination cursor is invalid", 422) from error
    if parsed.tzinfo is None:
        raise ApiError("invalid_cursor", "pagination cursor is invalid", 422)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _cursor_public_id(value: object) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise ApiError("invalid_cursor", "pagination cursor is invalid", 422)
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError as error:
        raise ApiError("invalid_cursor", "pagination cursor is invalid", 422) from error
    return value


def _model_detail(asset: object) -> ModelAssetDetail:
    return ModelAssetDetail(
        name=str(getattr(asset, "name")),
        filename=str(getattr(asset, "filename", getattr(asset, "name", "model"))),
        requested_revision=str(getattr(asset, "requested_revision", "unknown")),
        source_label=(
            public_source_label(asset)
            if isinstance(asset, ResolvedAsset)
            else f"Approved model registry · {getattr(asset, 'name', 'model')}"
        ),
        resolved_revision=getattr(asset, "resolved_revision", None),
        byte_size=getattr(asset, "byte_size", None),
        sha256=getattr(asset, "sha256", None),
        declared_license=str(getattr(asset, "declared_license", "not-declared")),
        downloaded_at=getattr(asset, "downloaded_at", None),
        compatibility_version=int(getattr(asset, "compatibility_version", 1)),
        required=bool(getattr(asset, "required", False)),
        state=getattr(asset, "state"),
        error_code=getattr(asset, "error_code", None),
    )


def _report_summary(row: ReportRevision | None) -> ReportSummary | None:
    if row is None:
        return None
    return ReportSummary(
        revision=row.revision,
        prediction_revision=row.prediction_revision,
        calibration_revision=row.calibration_revision,
        created_at=row.created_at,
        section_hashes=dict(row.section_hashes),
    )


def _latest_rows(session: object, match: Match) -> tuple[AnalysisJob | None, ReportRevision | None, int | None]:
    job = session.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.match_id == match.id)
        .order_by(AnalysisJob.created_at.desc(), AnalysisJob.id.desc())
        .limit(1)
    )
    report = session.scalar(
        select(ReportRevision)
        .where(ReportRevision.match_id == match.id)
        .order_by(ReportRevision.revision.desc())
        .limit(1)
    )
    calibration_revision = session.scalar(
        select(Calibration.revision)
        .where(Calibration.match_id == match.id)
        .order_by(Calibration.revision.desc())
        .limit(1)
    )
    return job, report, calibration_revision


def _processing(job: AnalysisJob | None) -> ProcessingSummary:
    if job is None:
        return ProcessingSummary(state="not_started")
    return ProcessingSummary(
        state=job.status.value,
        job_id=job.public_id,
        profile=job.processing_profile,
        stage=job.current_stage,
        updated_at=job.updated_at,
    )


def _quality(job: AnalysisJob | None, report: ReportRevision | None) -> MatchQualitySummary:
    warnings: list[str] = []
    if job is not None and job.status.value == "failed":
        warnings.append("analysis_failed")
    availability = "available" if report is not None else "unavailable"
    return MatchQualitySummary(availability=availability, warnings=warnings)


def _match_or_error(session: object, match_id: str) -> Match:
    match = session.scalar(select(Match).where(Match.public_id == match_id))
    if match is None:
        raise ApiError("match_not_found", "match was not found", 404)
    return match


def _proxy_bytes(
    descriptor: int, start: int, length: int
) -> Iterator[bytes]:
    with os.fdopen(descriptor, "rb") as stream:
        stream.seek(start)
        remaining = length
        while remaining > 0:
            chunk = stream.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _proxy_range(value: str, size: int) -> tuple[int, int] | None:
    if not value.startswith("bytes=") or "," in value:
        return None
    specification = value.removeprefix("bytes=")
    if "-" not in specification:
        return None
    first, last = specification.split("-", 1)
    try:
        if not first:
            suffix_length = int(last)
            if suffix_length <= 0 or size == 0:
                return None
            return max(0, size - suffix_length), size - 1
        start = int(first)
        if start < 0 or start >= size:
            return None
        if not last:
            return start, size - 1
        end = int(last)
    except ValueError:
        return None
    if end < start:
        return None
    return start, min(end, size - 1)


def _range_not_satisfiable(request: Request, size: int) -> JSONResponse:
    content = ErrorResponse(
        code="range_not_satisfiable",
        message="the requested proxy byte range is not satisfiable",
        details={"byteSize": size},
        request_id=request.state.request_id,
    ).model_dump(mode="json", by_alias=True)
    return JSONResponse(
        status_code=416,
        content=content,
        headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
    )


@router.get(
    "/{match_id}/media/proxy",
    response_class=StreamingResponse,
    operation_id="streamMatchProxy",
    responses={
        200: {"content": {"video/mp4": {}}},
        206: {"content": {"video/mp4": {}}},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        416: {"model": ErrorResponse},
    },
)
def stream_match_proxy(match_id: str, request: Request) -> Response:
    database: Database = request.app.state.database
    storage: LocalStorage = request.app.state.storage
    with database.session() as session:
        match = _match_or_error(session, match_id)
        proxy = session.scalar(
            select(MediaAsset).where(
                MediaAsset.match_id == match.id,
                MediaAsset.kind == AssetKind.PROXY,
            )
        )
        if proxy is None:
            raise ApiError(
                "proxy_unavailable",
                "the match proxy is not available yet",
                409,
            )
        relative = Path(proxy.relative_path)

    try:
        descriptor = storage.open_owned(relative, owned_paths=[relative])
        size = os.fstat(descriptor).st_size
    except (
        FileNotFoundError,
        NotADirectoryError,
        PermissionError,
        OSError,
        ValueError,
    ):
        raise ApiError(
            "proxy_unavailable",
            "the match proxy is not available yet",
            409,
        ) from None

    range_header = request.headers.get("range")
    if range_header is None:
        return StreamingResponse(
            _proxy_bytes(descriptor, 0, size),
            status_code=200,
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(size),
            },
        )

    selected = _proxy_range(range_header, size)
    if selected is None:
        os.close(descriptor)
        return _range_not_satisfiable(request, size)
    start, end = selected
    length = end - start + 1
    return StreamingResponse(
        _proxy_bytes(descriptor, start, length),
        status_code=206,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Range": f"bytes {start}-{end}/{size}",
        },
    )




def _detail(request: Request, match_id: str) -> MatchDetail:
    database: Database = request.app.state.database
    with database.session() as session:
        match = _match_or_error(session, match_id)
        job, report, calibration_revision = _latest_rows(session, match)
        assets = session.scalars(
            select(MediaAsset)
            .where(MediaAsset.match_id == match.id)
            .order_by(MediaAsset.created_at, MediaAsset.id)
        ).all()
        latest_job = (
            request.app.state.job_queue.snapshot(job.public_id) if job is not None else None
        )
        return MatchDetail(
            id=match.public_id,
            title=match.name,
            preparation_state=(
                PreparationState.PREPARED
                if any(asset.kind is AssetKind.PROXY for asset in assets)
                else "unprepared"
            ),
            metadata=MatchMetadata(
                player_one=match.player_a_name,
                player_two=match.player_b_name,
                played_on=match.played_on,
                score=match.score,
            ),
            assets=[
                MediaAssetDetail(
                    id=asset.public_id,
                    kind=asset.kind,
                    byte_size=asset.byte_size,
                    duration_us=asset.duration_us,
                    timestamp_index_available=asset.timestamp_index_path is not None,
                )
                for asset in assets
            ],
            version=_version(match.created_at),
            updated_at=match.created_at,
            latest_job=latest_job,
            latest_report=_report_summary(report),
            calibration_revision=calibration_revision,
            model_quality=[
                _model_detail(asset) for asset in request.app.state.model_manifest.states()
            ],
            quality=_quality(job, report),
        )


@router.get(
    "",
    response_model=MatchListPage,
    response_model_by_alias=True,
    operation_id="listMatches",
    responses={422: {"model": ErrorResponse}},
)
def list_matches(
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> MatchListPage:
    decoded = decode_api_cursor(
        request.app.state.cursor_secret,
        cursor,
        _MATCH_CURSOR_BINDING,
    )
    before: tuple[datetime, str] | None = None
    if decoded is not None:
        if len(decoded) != 2:
            raise ApiError("invalid_cursor", "pagination cursor is invalid", 422)
        before = (_cursor_datetime(decoded[0]), _cursor_public_id(decoded[1]))
    database: Database = request.app.state.database
    with database.session() as session:
        query = select(Match)
        if before is not None:
            query = query.where(
                or_(
                    Match.created_at < before[0],
                    and_(
                        Match.created_at == before[0],
                        Match.public_id < before[1],
                    ),
                )
            )
        rows = session.scalars(
            query.order_by(Match.created_at.desc(), Match.public_id.desc()).limit(
                limit + 1
            )
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items: list[MatchSummary] = []
        for match in rows:
            job, report, _calibration = _latest_rows(session, match)
            prepared = session.scalar(
                select(MediaAsset.id).where(
                    MediaAsset.match_id == match.id,
                    MediaAsset.kind == AssetKind.PROXY,
                )
            )
            items.append(
                MatchSummary(
                    id=match.public_id,
                    title=match.name,
                    metadata=MatchMetadata(
                        player_one=match.player_a_name,
                        player_two=match.player_b_name,
                        played_on=match.played_on,
                        score=match.score,
                    ),
                    preparation_state=(
                        PreparationState.PREPARED if prepared is not None else "unprepared"
                    ),
                    updated_at=match.created_at,
                    version=_version(match.created_at),
                    processing=_processing(job),
                    latest_report=_report_summary(report),
                    quality=_quality(job, report),
                )
            )
    return MatchListPage(
        items=items,
        next_cursor=(
            encode_api_cursor(
                request.app.state.cursor_secret,
                _MATCH_CURSOR_BINDING,
                (
                    rows[-1].created_at.replace(tzinfo=timezone.utc).isoformat()
                    if rows[-1].created_at.tzinfo is None
                    else rows[-1].created_at.astimezone(timezone.utc).isoformat(),
                    rows[-1].public_id,
                ),
            )
            if has_more and rows
            else None
        ),
    )


@router.get(
    "/{match_id}",
    response_model=MatchDetail,
    response_model_by_alias=True,
    operation_id="getMatch",
    responses={404: {"model": ErrorResponse}},
)
def get_match(match_id: str, request: Request) -> MatchDetail:
    return _detail(request, match_id)


@router.patch(
    "/{match_id}",
    response_model=MatchDetail,
    response_model_by_alias=True,
    operation_id="updateMatch",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def update_match(match_id: str, body: MatchUpdateRequest, request: Request) -> MatchDetail:
    database: Database = request.app.state.database
    with database.session() as session:
        match = _match_or_error(session, match_id)
        if body.expected_version != _version(match.created_at):
            raise ApiError(
                "match_revision_conflict",
                "match metadata changed since the requested revision",
                409,
            )
        changed = body.model_fields_set - {"expected_version"}
        if "title" in changed:
            assert body.title is not None
            match.name = body.title.strip()
        if "player_one" in changed:
            match.player_a_name = body.player_one
        if "player_two" in changed:
            match.player_b_name = body.player_two
        if "played_on" in changed:
            match.played_on = body.played_on
        if "score" in changed:
            match.score = body.score
        now = datetime.now(timezone.utc)
        prior = match.created_at
        if prior.tzinfo is None:
            prior = prior.replace(tzinfo=timezone.utc)
        match.created_at = max(now, prior + timedelta(microseconds=1))
    return _detail(request, match_id)


@contextmanager
def _immediate_session(database: Database) -> Iterator[Session]:
    connection = database.engine.connect()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        yield session
        session.flush()
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        session.close()
        connection.close()


def _after_stage_rename() -> None:
    pass


def _stage_deletion_path(original: Path, staged: Path) -> None:
    os.replace(original, staged)
    _after_stage_rename()


def _match_cache_namespace(match_id: str) -> str:
    encoded = json.dumps(
        {"match_id": match_id},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _owned_deletion_paths(session: Session, match: Match) -> set[Path]:
    media = session.scalars(
        select(MediaAsset).where(MediaAsset.match_id == match.id)
    ).all()
    jobs = session.scalars(
        select(AnalysisJob).where(AnalysisJob.match_id == match.id)
    ).all()
    media_prefixes = {
        AssetKind.ORIGINAL: (("videos", "original"),),
        AssetKind.PROXY: (("videos", "proxy"),),
        AssetKind.FRAME: (("frames",),),
        AssetKind.TIMESTAMP_MAP: (("timestamp-maps",), ("exports",)),
        AssetKind.EXPORT: (("exports",),),
    }
    relative_paths: set[Path] = set()
    for asset in media:
        relative = Path(asset.relative_path)
        prefixes = media_prefixes.get(asset.kind, ())
        if any(
            relative.parts[: len(prefix)] == prefix
            for prefix in prefixes
        ):
            relative_paths.add(relative)
        if asset.timestamp_index_path is not None:
            timestamp_index = Path(asset.timestamp_index_path)
            if timestamp_index.parts[:1] == ("timestamp-index",):
                relative_paths.add(timestamp_index)
    relative_paths.add(
        Path("analysis-cache", _match_cache_namespace(match.public_id))
    )
    for job in jobs:
        relative_paths.add(Path(".worker", job.public_id))
        relative_paths.add(Path("checkpoints", job.public_id))
    return relative_paths


def _plan_deletion(
    database: Database,
    storage: LocalStorage,
    match_id: str,
) -> int:
    with _immediate_session(database) as session:
        match = session.scalar(
            select(Match).where(Match.public_id == match_id)
        )
        if match is None:
            raise ApiError("match_not_found", "match was not found", 404)
        if match.deletion_state != "active":
            raise ApiError("match_deleting", "match is being deleted", 409)
        active = session.scalar(
            select(AnalysisJob.id).where(
                AnalysisJob.match_id == match.id,
                AnalysisJob.status.in_(ACTIVE_STATES),
            )
        )
        if active is not None:
            raise ApiError(
                "active_job_exists",
                "match cannot be deleted while analysis is active",
                409,
            )
        planned_paths: set[Path] = set()
        for relative in _owned_deletion_paths(session, match):
            candidate = storage.root / relative
            if not candidate.exists() and not candidate.is_symlink():
                continue
            storage.resolve(relative, owned_paths={relative})
            planned_paths.add(relative)
        relative_paths = planned_paths
        match.deletion_state = "deleting"
        match.deletion_version += 1
        version = match.deletion_version
        for relative in sorted(relative_paths):
            staged = relative.with_name(
                f".{relative.name}.{uuid4().hex}.deleting"
            )
            session.add(
                PendingDeletion(
                    match_public_id=match.public_id,
                    deletion_version=version,
                    state="planned",
                    original_relative_path=str(relative),
                    staged_relative_path=str(staged),
                )
            )
        return version


def _pending_group(
    database: Database,
    match_id: str,
    version: int,
) -> list[PendingDeletion]:
    with database.session() as session:
        return list(
            session.scalars(
                select(PendingDeletion)
                .where(
                    PendingDeletion.match_public_id == match_id,
                    PendingDeletion.deletion_version == version,
                )
                .order_by(PendingDeletion.id)
            ).all()
        )


def _journal_absolute_paths(
    storage: LocalStorage,
    rows: list[PendingDeletion],
) -> dict[int, tuple[Path, Path]]:
    owned = {
        Path(value)
        for row in rows
        for value in (
            row.original_relative_path,
            row.staged_relative_path,
        )
    }
    paths: dict[int, tuple[Path, Path]] = {}
    for row in rows:
        original = storage.resolve(
            Path(row.original_relative_path), owned_paths=owned
        ).absolute
        staged_relative = Path(row.staged_relative_path)
        if not staged_relative.name.endswith(".deleting"):
            raise ValueError("pending deletion staging path is invalid")
        staged = storage.resolve(
            staged_relative, owned_paths=owned
        ).absolute
        paths[row.id] = (original, staged)
    return paths


def _mark_staged(database: Database, row_id: int) -> None:
    with _immediate_session(database) as session:
        row = session.get(PendingDeletion, row_id)
        if row is not None:
            row.state = "staged"


def _stage_pending_group(
    database: Database,
    storage: LocalStorage,
    rows: list[PendingDeletion],
) -> None:
    paths = _journal_absolute_paths(storage, rows)
    owned = {
        Path(value)
        for row in rows
        for value in (
            row.original_relative_path,
            row.staged_relative_path,
        )
    }
    for row in rows:
        original, staged = paths[row.id]
        if original.exists():
            if staged.exists() or staged.is_symlink():
                storage.remove_owned_tree(
                    Path(row.staged_relative_path),
                    owned_paths=owned,
                )
            _stage_deletion_path(original, staged)
        _mark_staged(database, row.id)


def _restore_pending_group(
    storage: LocalStorage,
    rows: list[PendingDeletion],
) -> bool:
    try:
        paths = _journal_absolute_paths(storage, rows)
        owned = {
            Path(value)
            for row in rows
            for value in (
                row.original_relative_path,
                row.staged_relative_path,
            )
        }
        for row in reversed(rows):
            original, staged = paths[row.id]
            if not staged.exists() and not staged.is_symlink():
                continue
            if original.exists() or original.is_symlink():
                storage.remove_owned_tree(
                    Path(row.staged_relative_path),
                    owned_paths=owned,
                )
            else:
                os.replace(staged, original)
        return True
    except (OSError, PermissionError, ValueError):
        return False


def _clear_deletion_intent(
    database: Database,
    match_id: str,
    version: int,
) -> None:
    with _immediate_session(database) as session:
        match = session.scalar(
            select(Match).where(Match.public_id == match_id)
        )
        if (
            match is not None
            and match.deletion_state == "deleting"
            and match.deletion_version == version
        ):
            match.deletion_state = "active"
        rows = session.scalars(
            select(PendingDeletion).where(
                PendingDeletion.match_public_id == match_id,
                PendingDeletion.deletion_version == version,
            )
        ).all()
        for row in rows:
            session.delete(row)


def _commit_deletion(
    database: Database,
    storage: LocalStorage,
    match_id: str,
    version: int,
) -> None:
    with _immediate_session(database) as session:
        match = session.scalar(
            select(Match).where(Match.public_id == match_id)
        )
        if match is None:
            return
        if (
            match.deletion_state != "deleting"
            or match.deletion_version != version
        ):
            raise ApiError("match_deleting", "match deletion intent changed", 409)
        rows = session.scalars(
            select(PendingDeletion).where(
                PendingDeletion.match_public_id == match_id,
                PendingDeletion.deletion_version == version,
            )
        ).all()
        paths = _journal_absolute_paths(storage, list(rows))
        if any(original.exists() for original, _staged in paths.values()):
            raise ApiError(
                "deletion_staging_failed",
                "match files could not be staged for deletion",
                503,
            )
        active = session.scalar(
            select(AnalysisJob.id).where(
                AnalysisJob.match_id == match.id,
                AnalysisJob.status.in_(ACTIVE_STATES),
            )
        )
        if active is not None:
            raise ApiError(
                "active_job_exists",
                "match cannot be deleted while analysis is active",
                409,
            )
        for row in rows:
            row.state = "cleanup"
        session.connection().exec_driver_sql("PRAGMA defer_foreign_keys = ON")
        session.execute(delete(Match).where(Match.id == match.id))


def _cleanup_deleted_group(
    database: Database,
    storage: LocalStorage,
    match_id: str,
    version: int,
) -> None:
    rows = _pending_group(database, match_id, version)
    if not rows:
        return
    try:
        paths = _journal_absolute_paths(storage, rows)
    except (OSError, PermissionError, ValueError):
        return
    completed: list[int] = []
    owned = {
        Path(value)
        for row in rows
        for value in (
            row.original_relative_path,
            row.staged_relative_path,
        )
    }
    for row in rows:
        try:
            storage.remove_owned_tree(
                Path(row.original_relative_path),
                owned_paths=owned,
            )
            storage.remove_owned_tree(
                Path(row.staged_relative_path),
                owned_paths=owned,
            )
        except (OSError, PermissionError, ValueError):
            continue
        completed.append(row.id)
    if completed:
        with database.session() as session:
            for row in session.scalars(
                select(PendingDeletion).where(
                    PendingDeletion.id.in_(completed)
                )
            ).all():
                session.delete(row)


def cleanup_pending_deletions(
    database: Database, storage: LocalStorage
) -> None:
    with database.session() as session:
        pending = session.scalars(
            select(PendingDeletion).order_by(PendingDeletion.id)
        ).all()
        group_keys = {
            (row.match_public_id, row.deletion_version)
            for row in pending
            if row.match_public_id is not None
        }
        group_keys.update(
            session.execute(
                select(Match.public_id, Match.deletion_version).where(
                    Match.deletion_state == "deleting"
                )
            ).all()
        )
        groups = sorted(group_keys)
        legacy = [row for row in pending if row.match_public_id is None]
    for row in legacy:
        try:
            staged = storage.resolve(
                Path(row.staged_relative_path),
                owned_paths={Path(row.staged_relative_path)},
            ).absolute
            staged.unlink(missing_ok=True)
        except (OSError, PermissionError, ValueError):
            continue
        with database.session() as session:
            current = session.get(PendingDeletion, row.id)
            if current is not None:
                session.delete(current)
    for match_id, version in groups:
        assert match_id is not None
        rows = _pending_group(database, match_id, version)
        with database.session() as session:
            match = session.scalar(
                select(Match).where(Match.public_id == match_id)
            )
            state = (
                (match.deletion_state, match.deletion_version)
                if match is not None
                else None
            )
        if state is None:
            _cleanup_deleted_group(
                database, storage, match_id, version
            )
            continue
        if state != ("deleting", version):
            if _restore_pending_group(storage, rows):
                _clear_deletion_intent(database, match_id, version)
            continue
        try:
            _stage_pending_group(database, storage, rows)
            _commit_deletion(database, storage, match_id, version)
        except Exception:
            if _restore_pending_group(storage, rows):
                _clear_deletion_intent(database, match_id, version)
            continue
        _cleanup_deleted_group(database, storage, match_id, version)


def cleanup_orphaned_storage(
    database: Database, storage: LocalStorage
) -> None:
    with database.session() as session:
        owned: set[Path] = set()
        for relative_path, timestamp_index_path in session.execute(
            select(
                MediaAsset.relative_path,
                MediaAsset.timestamp_index_path,
            )
        ):
            owned.add(Path(relative_path))
            if timestamp_index_path is not None:
                owned.add(Path(timestamp_index_path))
        for artifact_path, payload_path in session.execute(
            select(
                JobChunk.artifact_path,
                JobChunk.artifact_payload_path,
            )
        ):
            if artifact_path is not None:
                owned.add(Path(artifact_path))
            if payload_path is not None:
                owned.add(Path(payload_path))
        for original_path, staged_path in session.execute(
            select(
                PendingDeletion.original_relative_path,
                PendingDeletion.staged_relative_path,
            )
        ):
            owned.add(Path(original_path))
            owned.add(Path(staged_path))
    storage.reconcile_orphans(
        owned_paths=owned,
        protected_trees=(),
    )


@router.delete(
    "/{match_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteMatch",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def delete_match(match_id: str, request: Request) -> Response:
    database: Database = request.app.state.database
    storage: LocalStorage = request.app.state.storage
    version = _plan_deletion(database, storage, match_id)
    rows = _pending_group(database, match_id, version)
    try:
        _stage_pending_group(database, storage, rows)
    except Exception as error:
        if _restore_pending_group(storage, rows):
            _clear_deletion_intent(database, match_id, version)
        raise ApiError(
            "deletion_staging_failed",
            "match files could not be staged for deletion",
            503,
        ) from error
    try:
        _commit_deletion(database, storage, match_id, version)
    except Exception as error:
        if _restore_pending_group(storage, rows):
            _clear_deletion_intent(database, match_id, version)
        if isinstance(error, ApiError):
            raise
        raise ApiError(
            "deletion_commit_failed",
            "match deletion could not be committed",
            503,
        ) from error
    try:
        _cleanup_deleted_group(database, storage, match_id, version)
    except Exception:
        pass
    return Response(status_code=204)


@router.post(
    "",
    response_model=MatchDetail,
    response_model_by_alias=True,
    status_code=201,
    operation_id="createMatch",
    responses={
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
        507: {"model": ErrorResponse},
    },
)
def create_match(
    request: Request,
    video: UploadFile = File(...),
    title: str | None = Form(default=None),
    player_one: str | None = Form(default=None, alias="playerOne"),
    player_two: str | None = Form(default=None, alias="playerTwo"),
    played_on: date | None = Form(default=None, alias="playedOn"),
    score: str | None = Form(default=None),
) -> MatchDetail:
    settings: Settings = request.app.state.settings
    database: Database = request.app.state.database
    storage: LocalStorage = request.app.state.storage
    generated: list[Path] = []
    proxy_temporary: Path | None = None
    map_temporary: Path | None = None
    match_id: str | None = None

    try:
        ingested = ingest_upload(
            video.file,
            video.filename or "upload",
            storage,
            max_bytes=settings.max_upload_bytes,
            max_duration_seconds=settings.max_video_duration_seconds,
            min_free_disk_bytes=settings.min_free_disk_bytes,
            probe_timeout_seconds=settings.ffprobe_timeout_seconds,
        )
        generated.append(ingested.stored_path.absolute)

        proxy_stored = storage.allocate(AssetKind.PROXY, ".mp4")
        generated.append(proxy_stored.absolute)
        proxy_temporary = storage.root / f".proxy-{uuid4().hex}.mp4"
        timestamp_map = create_proxy(
            ingested.stored_path.absolute,
            proxy_temporary,
            timeout_seconds=settings.proxy_timeout_for_duration(ingested.probe.duration),
        )
        storage.publish(proxy_stored, proxy_temporary)

        map_stored = storage.allocate(AssetKind.TIMESTAMP_MAP, ".json")
        generated.append(map_stored.absolute)
        map_temporary = storage.root / f".timestamp-{uuid4().hex}.json"
        map_temporary.write_text(
            timestamp_map.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
        )
        storage.publish(map_stored, map_temporary)
        from squashvision.pipeline import ExactTimestampIndex

        proxy_size, proxy_sha256 = _file_signature(proxy_stored.absolute)
        map_size, map_sha256 = _file_signature(map_stored.absolute)
        proxy_probe = probe_video(
            proxy_stored.absolute,
            timeout_seconds=settings.ffprobe_timeout_seconds,
        )
        index_stored = storage.allocate_timestamp_index()
        with storage.create_timestamp_index_stage() as (
            _index_stage,
            index_descriptor,
        ):
            ExactTimestampIndex.build_to_descriptor(
                ingested.stored_path.absolute,
                proxy_stored.absolute,
                index_descriptor,
            )
            index_size, index_sha256 = _descriptor_signature(
                index_descriptor
            )
            storage.publish_descriptor(index_stored, index_descriptor)
        generated.append(index_stored.absolute)
        index_relative = index_stored.relative

        match_name = title.strip() if title and title.strip() else "Untitled match"
        with database.session() as session:
            match = Match(
                name=match_name,
                player_a_name=player_one,
                player_b_name=player_two,
                played_on=played_on,
                score=score,
            )
            rows = [
                MediaAsset(
                    match=match,
                    kind=AssetKind.ORIGINAL,
                    relative_path=str(ingested.stored_path.relative),
                    checksum_sha256=ingested.sha256,
                    byte_size=ingested.bytes,
                    duration_us=int(round(ingested.probe.duration * 1_000_000)),
                    probe_metadata=ingested.probe.model_dump(mode="json"),
                ),
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy_stored.relative),
                    checksum_sha256=proxy_sha256,
                    byte_size=proxy_size,
                    duration_us=int(round(proxy_probe.duration * 1_000_000)),
                    probe_metadata=proxy_probe.model_dump(mode="json"),
                    timestamp_index_path=str(index_relative),
                    timestamp_index_sha256=index_sha256,
                    timestamp_index_size=index_size,
                ),
                MediaAsset(
                    match=match,
                    kind=AssetKind.TIMESTAMP_MAP,
                    relative_path=str(map_stored.relative),
                    checksum_sha256=map_sha256,
                    byte_size=map_size,
                ),
            ]
            session.add_all([match, *rows])
            session.flush()
            match_id = match.public_id
    except MediaError as error:
        _remove_generated(generated)
        raise _safe_media_error(error) from error
    except BaseException:
        _remove_generated(generated)
        raise
    finally:
        if proxy_temporary is not None:
            proxy_temporary.unlink(missing_ok=True)
        if map_temporary is not None:
            map_temporary.unlink(missing_ok=True)

    assert match_id is not None
    return _detail(request, match_id)
