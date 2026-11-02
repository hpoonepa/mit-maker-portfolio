from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from squashvision.jobs import JobError, JobQueue
from squashvision.models import JobStatus, ModelAssetState
from squashvision.schemas import ApiError, ErrorResponse, JobDetail, JobEvent, JobStartRequest

router = APIRouter(
    tags=["jobs"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
_TERMINAL_STATES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


def _safe_job_error(error: JobError) -> ApiError:
    messages = {
        "match_not_found": "match was not found",
        "match_not_prepared": "match does not have prepared proxy media",
        "match_deleting": "match is being deleted",
        "job_not_found": "analysis job was not found",
        "active_job_exists": "match already has an active analysis job",
        "invalid_job_transition": "analysis job cannot make the requested transition",
        "job_claim_lost": "analysis job worker ownership changed",
        "checkpoint_invalid": "analysis checkpoint is no longer valid",
    }
    return ApiError(
        error.code,
        messages.get(error.code, "analysis job operation could not be completed"),
        error.status_code,
    )


def _queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


def _require_models(request: Request) -> None:
    states = request.app.state.model_manifest.states()
    unavailable = sorted(
        str(asset.name)
        for asset in states
        if asset.required and asset.state is not ModelAssetState.READY
    )
    if unavailable:
        raise ApiError(
            "required_models_unavailable",
            "required analysis models are missing or incompatible",
            503,
            details={"models": unavailable},
        )


def _enqueue(match_id: str, body: JobStartRequest, request: Request) -> JobDetail:
    _require_models(request)
    queue = _queue(request)
    try:
        job = queue.enqueue(match_id, body.profile, ball_input_mode=body.ball_input_mode)
        return queue.snapshot(job.public_id)
    except JobError as error:
        raise _safe_job_error(error) from error


@router.post(
    "/matches/{match_id}/jobs",
    response_model=JobDetail,
    response_model_by_alias=True,
    status_code=201,
    operation_id="startAnalysisJob",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def start_job(match_id: str, body: JobStartRequest, request: Request) -> JobDetail:
    return _enqueue(match_id, body, request)


@router.post(
    "/matches/{match_id}/reanalyze",
    response_model=JobDetail,
    response_model_by_alias=True,
    status_code=201,
    operation_id="reanalyzeMatch",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def reanalyze_match(
    match_id: str, body: JobStartRequest, request: Request
) -> JobDetail:
    return _enqueue(match_id, body, request)


@router.get(
    "/jobs/{job_id}",
    response_model=JobDetail,
    response_model_by_alias=True,
    operation_id="getAnalysisJob",
    responses={404: {"model": ErrorResponse}},
)
def get_job(job_id: str, request: Request) -> JobDetail:
    try:
        return _queue(request).snapshot(job_id)
    except JobError as error:
        raise _safe_job_error(error) from error


def _control(
    job_id: str,
    request: Request,
    operation: Callable[[str], object],
) -> JobDetail:
    queue = _queue(request)
    try:
        operation(job_id)
        return queue.snapshot(job_id)
    except JobError as error:
        raise _safe_job_error(error) from error


@router.post(
    "/jobs/{job_id}/pause",
    response_model=JobDetail,
    response_model_by_alias=True,
    operation_id="pauseAnalysisJob",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def pause_job(job_id: str, request: Request) -> JobDetail:
    queue = _queue(request)
    return _control(job_id, request, queue.pause)


@router.post(
    "/jobs/{job_id}/resume",
    response_model=JobDetail,
    response_model_by_alias=True,
    operation_id="resumeAnalysisJob",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def resume_job(job_id: str, request: Request) -> JobDetail:
    queue = _queue(request)
    return _control(job_id, request, queue.resume)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobDetail,
    response_model_by_alias=True,
    operation_id="cancelAnalysisJob",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def cancel_job(job_id: str, request: Request) -> JobDetail:
    queue = _queue(request)
    return _control(job_id, request, queue.cancel)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobDetail,
    response_model_by_alias=True,
    operation_id="retryAnalysisJob",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def retry_job(job_id: str, request: Request) -> JobDetail:
    queue = _queue(request)
    return _control(job_id, request, queue.retry)


async def _event_stream(
    request: Request,
    queue: JobQueue,
    job_id: str,
    *,
    poll_seconds: float = 0.25,
    heartbeat_seconds: float = 10.0,
) -> AsyncIterator[str]:
    if poll_seconds <= 0 or heartbeat_seconds <= 0:
        raise ValueError("SSE intervals must be positive")
    try:
        if await request.is_disconnected():
            return
        snapshot = queue.snapshot(job_id)
        event = JobEvent(job=snapshot)
        yield (
            "event: job.snapshot\n"
            f"id: {snapshot.version}\n"
            f"data: {event.model_dump_json(by_alias=True)}\n\n"
        )
        if snapshot.state in _TERMINAL_STATES:
            return

        last_version = snapshot.version
        last_emit = time.monotonic()
        while not await request.is_disconnected():
            await asyncio.sleep(poll_seconds)
            if await request.is_disconnected():
                return
            snapshot = queue.snapshot(job_id)
            if snapshot.version != last_version:
                last_version = snapshot.version
                last_emit = time.monotonic()
                event = JobEvent(job=snapshot)
                yield (
                    "event: job.snapshot\n"
                    f"id: {snapshot.version}\n"
                    f"data: {event.model_dump_json(by_alias=True)}\n\n"
                )
                if snapshot.state in _TERMINAL_STATES:
                    return
            elif time.monotonic() - last_emit >= heartbeat_seconds:
                last_emit = time.monotonic()
                yield f": heartbeat {snapshot.version}\n\n"
    finally:
        # The generator owns no durable subscription. Reaching this block guarantees
        # polling stops immediately when Starlette closes a disconnected response.
        pass


@router.get(
    "/jobs/{job_id}/events",
    response_model=JobEvent,
    operation_id="streamJobEvents",
    responses={
        200: {
            "model": JobEvent,
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/JobEvent"}
                }
            },
        },
        404: {"model": ErrorResponse},
    },
)
def job_events(job_id: str, request: Request) -> StreamingResponse:
    queue = _queue(request)
    try:
        queue.get(job_id)
    except JobError as error:
        raise _safe_job_error(error) from error
    return StreamingResponse(
        _event_stream(request, queue, job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
