from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Iterator
from itertools import islice
from pathlib import Path
from urllib.parse import quote

import av
from av.error import FFmpegError
from fastapi import APIRouter, Query, Request
import pyarrow.dataset as ds
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from squashvision.calibration import (
    CalibrationProposal,
    CalibrationResult,
    CourtCorrespondence,
    CourtKeypoints,
    CourtPoint,
    ImagePoint,
    Size,
    detect_court,
    fit_calibration,
)
from squashvision.analytics import (
    CanonicalState,
    _assign_shots_to_rallies,
    _error_payload,
    _fold_correction,
    _rally_payload,
    _report_from_row,
    _row_payload,
    canonical_state_for_report,
)
from squashvision.corrections import INVALIDATIONS
from squashvision.db import Database
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    Calibration,
    Correction,
    CorrectionStatus,
    ErrorCandidate,
    JobChunk,
    JobStatus,
    Match,
    MediaAsset,
    Rally,
    ReportRevision,
    Shot,
    Stage,
    StageStatus,
    StagePublication,
)
from squashvision.schemas import (
    ApiError,
    ArtifactSelection,
    BallObservationDetail,
    BallCandidateDetail,
    BallObservationPage,
    CalibrationCapabilitiesDetail,
    CalibrationCourtPoint,
    CalibrationDetail,
    CalibrationImagePoint,
    CalibrationKeypoint,
    CalibrationProposalDetail,
    CalibrationProposalRequest,
    CalibrationResultDetail,
    CalibrationSize,
    CalibrationSaveRequest,
    ErrorResponse,
    CorrectionCommandType,
    CorrectionImpactDetail,
    CorrectionTargetDetail,
    MatchReport,
    PlayerObservationDetail,
    PoseKeypointDetail,
    PlayerObservationPage,
    RallyDetail,
    RallyPage,
    ReportListPage,
    ReportSummary,
    ReviewItemDetail,
    ReviewItemPage,
    ShotDetail,
    ShotPage,
    TimelineItem,
    TimelinePage,
    decode_api_cursor,
    encode_api_cursor,
)
from squashvision.storage import LocalStorage

router = APIRouter(
    tags=["analysis"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
_DERIVED_COURT_STAGES = frozenset(
    {Stage.BALL, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT}
)
_MAX_DECODED_PROPOSAL_FRAMES = 90

_COCO_SKELETON_EDGES = (
    (5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12),
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 1), (0, 2),
)
_COMMAND_BY_ISSUE = {
    "rally_boundary": CorrectionCommandType.SPLIT_RALLY,
    "identity": CorrectionCommandType.CHANGE_HITTER,
    "player_identity": CorrectionCommandType.CHANGE_HITTER,
    "hitter": CorrectionCommandType.CHANGE_HITTER,
    "shot_type": CorrectionCommandType.CHANGE_SHOT_TYPE,
    "type": CorrectionCommandType.CHANGE_SHOT_TYPE,
    "ball_seam": CorrectionCommandType.BALL_CONTROL_POINT,
    "outcome": CorrectionCommandType.CHANGE_OUTCOME,
    "accept": CorrectionCommandType.ACCEPT,
}
_INVALIDATED_STATS = {
    CorrectionCommandType.ACCEPT: ["reviewed_error_count", "accepted_subjective_errors", "coaching_findings", "review_counts"],
    CorrectionCommandType.REJECT: ["reviewed_error_count", "accepted_subjective_errors", "coaching_findings", "review_counts"],
    CorrectionCommandType.CHANGE_HITTER: ["player_shot_counts", "player_movement", "error_side_context", "head_to_head_players", "coaching_findings", "review_counts"],
    CorrectionCommandType.CHANGE_SHOT_TYPE: ["shot_type_counts", "error_context", "head_to_head_shots", "coaching_findings", "review_counts"],
    CorrectionCommandType.ADJUST_CONTACT_TIME: ["shot_timing", "rally_assignment", "movement_windows", "ball_trajectory", "coaching_findings", "review_counts"],
    CorrectionCommandType.CHANGE_OUTCOME: ["winner_count", "shot_outcomes", "objective_error_count", "head_to_head_outcomes", "coaching_findings", "review_counts"],
    CorrectionCommandType.BALL_CONTROL_POINT: ["shot_contacts", "error_context", "ball_trajectory", "coaching_findings"],
    CorrectionCommandType.SPLIT_RALLY: ["rally_count", "active_duration_s", "rest_duration_s", "shot_rally_id", "error_rally_context", "coaching_findings", "review_counts"],
    CorrectionCommandType.MERGE_RALLIES: ["rally_count", "active_duration_s", "rest_duration_s", "shot_rally_id", "error_rally_context", "coaching_findings", "review_counts"],
}

class CalibrationApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _error_response(error: CalibrationApiError) -> None:
    raise ApiError(error.code, error.message, error.status_code) from error


def _keypoint_value(point: CalibrationKeypoint) -> CourtCorrespondence:
    return CourtCorrespondence(
        label=point.label,
        image=ImagePoint(point.image.x, point.image.y),
        court=CourtPoint(point.court.x_m, point.court.y_m),
    )


def _canonical_keypoints(
    points: tuple[CalibrationKeypoint, ...],
) -> tuple[CalibrationKeypoint, ...]:
    labels = [point.label for point in points]
    if len(labels) != len(set(labels)):
        raise CalibrationApiError(
            "duplicate_keypoint_label", "calibration labels must be unique", 422
        )
    if any(
        not all(
            math.isfinite(value)
            for value in (
                point.image.x,
                point.image.y,
                point.court.x_m,
                point.court.y_m,
            )
        )
        for point in points
    ):
        raise CalibrationApiError(
            "non_finite_keypoint", "calibration coordinates must be finite", 422
        )
    return tuple(sorted(points, key=lambda point: point.label))


def _keypoints_payload(
    points: tuple[CalibrationKeypoint, ...],
) -> list[dict[str, object]]:
    return [point.model_dump(mode="json", by_alias=True) for point in points]


def _result_detail(result: CalibrationResult) -> CalibrationResultDetail:
    return CalibrationResultDetail(
        calibrated=result.calibrated,
        image_to_court=result.image_to_court,
        court_to_image=result.court_to_image,
        residuals_px=result.residuals_px,
        rms_error_px=result.rms_error_px,
        max_error_px=result.max_error_px,
        inlier_mask=result.inlier_mask,
        condition_number=result.condition_number,
        parameter_covariance=result.parameter_covariance,
        confidence=result.confidence,
        capabilities=CalibrationCapabilitiesDetail(
            image_space=result.capabilities.image_space,
            floor_position=result.capabilities.floor_position,
            movement_distance=result.capabilities.movement_distance,
            speed=result.capabilities.speed,
        ),
        warnings=result.warnings,
    )


def _row_detail(row: Calibration) -> CalibrationDetail:
    frame_size = (
        CalibrationSize(width=row.frame_width, height=row.frame_height)
        if row.frame_width is not None and row.frame_height is not None
        else None
    )
    return CalibrationDetail(
        revision=row.revision,
        proxy_id=row.media_asset.public_id,
        frame_size=frame_size,
        keypoints=tuple(
            CalibrationKeypoint.model_validate(point) for point in row.keypoints
        ),
        result=CalibrationResultDetail.model_validate(row.result),
    )


def _match(session: object, match_id: str) -> Match:
    match = session.scalar(select(Match).where(Match.public_id == match_id))
    if match is None:
        raise CalibrationApiError("match_not_found", "match was not found", 404)
    return match


def _proxy(session: object, match: Match) -> MediaAsset:
    proxy = session.scalar(
        select(MediaAsset)
        .where(MediaAsset.match_id == match.id, MediaAsset.kind == AssetKind.PROXY)
        .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
    )
    if proxy is None:
        raise CalibrationApiError(
            "proxy_not_found", "match has no prepared proxy video", 409
        )
    return proxy


def _latest_calibration(session: object, match: Match) -> Calibration | None:
    return session.scalar(
        select(Calibration)
        .where(Calibration.match_id == match.id)
        .order_by(Calibration.revision.desc())
        .limit(1)
    )


def _invalidate_derived_chunks(session: object, match: Match) -> None:
    chunks = session.scalars(
        select(JobChunk)
        .join(JobChunk.analysis_job)
        .where(
            JobChunk.analysis_job.has(match_id=match.id),
            JobChunk.stage.in_(_DERIVED_COURT_STAGES),
        )
    ).all()
    for chunk in chunks:
        chunk.status = StageStatus.INVALIDATED


def _proposal_detail(proposal: CalibrationProposal) -> CalibrationProposalDetail:
    return CalibrationProposalDetail(
        keypoints=tuple(
            CalibrationKeypoint(
                label=point.label,
                image=CalibrationImagePoint(x=point.image.x, y=point.image.y),
                court=CalibrationCourtPoint(
                    x_m=point.court.x_m, y_m=point.court.y_m
                ),
            )
            for point in proposal.keypoints.points
        ),
        confidence=proposal.confidence,
        visible_surfaces=proposal.visible_surfaces,
        warnings=proposal.warnings,
        line_count=proposal.line_count,
        intersection_count=proposal.intersection_count,
    )


def _proxy_size(path: Path) -> Size:
    try:
        with av.open(str(path), mode="r") as container:
            stream = next(
                (candidate for candidate in container.streams if candidate.type == "video"),
                None,
            )
            if stream is None or stream.width <= 0 or stream.height <= 0:
                raise CalibrationApiError(
                    "invalid_proxy", "proxy has no valid video geometry", 422
                )
            return Size(stream.width, stream.height)
    except CalibrationApiError:
        raise
    except (FFmpegError, OSError, ValueError) as error:
        raise CalibrationApiError(
            "invalid_proxy", "proxy geometry could not be decoded", 422
        ) from error


def _proxy_frame(path: Path, timestamp_seconds: float):
    if not math.isfinite(timestamp_seconds) or timestamp_seconds < 0:
        raise CalibrationApiError(
            "timestamp_out_of_range", "timestamp must be within the proxy duration", 422
        )
    try:
        with av.open(str(path), mode="r") as container:
            stream = next(
                (candidate for candidate in container.streams if candidate.type == "video"),
                None,
            )
            if stream is None:
                raise CalibrationApiError(
                    "invalid_proxy", "proxy contains no video stream", 422
                )
            if stream.time_base is None:
                raise CalibrationApiError(
                    "invalid_proxy", "proxy video has no time base", 422
                )
            time_base = float(stream.time_base)
            start_pts = stream.start_time if stream.start_time is not None else 0
            stream_start_seconds = float(start_pts * stream.time_base)
            target_seconds = stream_start_seconds + timestamp_seconds
            if stream.duration is not None:
                stream_end_seconds = stream_start_seconds + float(
                    stream.duration * stream.time_base
                )
                if target_seconds >= stream_end_seconds:
                    raise CalibrationApiError(
                        "timestamp_out_of_range",
                        "timestamp must be within the proxy video stream",
                        422,
                    )
            seek_offset = start_pts + int(timestamp_seconds / time_base)
            container.seek(max(0, seek_offset), stream=stream, backward=True)
            for index, frame in enumerate(container.decode(stream)):
                if index >= _MAX_DECODED_PROPOSAL_FRAMES:
                    break
                if frame.pts is None or frame.time_base is None:
                    continue
                frame_seconds = float(frame.pts * frame.time_base)
                if frame_seconds + 1.0e-9 >= target_seconds:
                    return frame.to_ndarray(format="bgr24")
    except CalibrationApiError:
        raise
    except (FFmpegError, OSError, ValueError) as error:
        raise CalibrationApiError(
            "invalid_proxy", "proxy frame could not be decoded", 422
        ) from error
    raise CalibrationApiError(
        "timestamp_out_of_range", "timestamp must be within the proxy duration", 422
    )


@router.get(
    "/matches/{match_id}/calibration",
    response_model=CalibrationDetail,
    response_model_by_alias=True,
    responses={404: {"model": ErrorResponse}},
    operation_id="getCalibration",
)
def get_calibration(match_id: str, request: Request) -> CalibrationDetail:
    database: Database = request.app.state.database
    try:
        with database.session() as session:
            match = _match(session, match_id)
            latest = _latest_calibration(session, match)
            if latest is None:
                raise CalibrationApiError(
                    "calibration_not_found", "match has no saved calibration", 404
                )
            return _row_detail(latest)
    except CalibrationApiError as error:
        return _error_response(error)


@router.post(
    "/matches/{match_id}/calibration/propose",
    response_model=CalibrationProposalDetail,
    response_model_by_alias=True,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    operation_id="proposeCalibration",
)
def propose_calibration(
    match_id: str, body: CalibrationProposalRequest, request: Request
) -> CalibrationProposalDetail:
    database: Database = request.app.state.database
    storage: LocalStorage = request.app.state.storage
    try:
        with database.session() as session:
            match = _match(session, match_id)
            proxy = _proxy(session, match)
            stored = storage.resolve(
                Path(proxy.relative_path), owned_paths=(Path(proxy.relative_path),)
            )
        frame = _proxy_frame(stored.absolute, body.timestamp_seconds)
        return _proposal_detail(detect_court(frame))
    except CalibrationApiError as error:
        return _error_response(error)
    except (FileNotFoundError, PermissionError, ValueError) as error:
        return _error_response(
            CalibrationApiError(
                "proxy_unavailable", "stored proxy is unavailable or unsafe", 422
            )
        )


@router.put(
    "/matches/{match_id}/calibration",
    response_model=CalibrationDetail,
    response_model_by_alias=True,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    operation_id="saveCalibration",
)
def save_calibration(
    match_id: str, body: CalibrationSaveRequest, request: Request
) -> CalibrationDetail:
    database: Database = request.app.state.database
    storage: LocalStorage = request.app.state.storage
    try:
        canonical = _canonical_keypoints(body.keypoints)
        payload = _keypoints_payload(canonical)
        with database.session() as session:
            match = _match(session, match_id)
            proxy = _proxy(session, match)
            latest = _latest_calibration(session, match)
            current_revision = latest.revision if latest is not None else 0
            if body.expected_revision != current_revision:
                raise CalibrationApiError(
                    "calibration_revision_conflict",
                    "saved calibration changed since the requested revision",
                    409,
                )
            try:
                stored = storage.resolve(
                    Path(proxy.relative_path),
                    owned_paths=(Path(proxy.relative_path),),
                )
            except (FileNotFoundError, PermissionError, ValueError) as error:
                raise CalibrationApiError(
                    "proxy_unavailable",
                    "stored proxy is unavailable or unsafe",
                    422,
                ) from error
            frame_size = _proxy_size(stored.absolute)
            if (
                body.frame_size.width != frame_size.width
                or body.frame_size.height != frame_size.height
            ):
                raise CalibrationApiError(
                    "frame_size_mismatch",
                    "frame size must match the selected proxy video",
                    422,
                )
            if (
                latest is not None
                and latest.keypoints == payload
                and latest.media_asset_id == proxy.id
                and latest.frame_width == frame_size.width
                and latest.frame_height == frame_size.height
            ):
                return _row_detail(latest)

            result = fit_calibration(
                CourtKeypoints(tuple(_keypoint_value(point) for point in canonical)),
                frame_size,
            )
            result_detail = _result_detail(result)
            row = Calibration(
                match=match,
                media_asset=proxy,
                revision=current_revision + 1,
                frame_width=frame_size.width,
                frame_height=frame_size.height,
                keypoints=payload,
                result=result_detail.model_dump(mode="json", by_alias=True),
                confidence=result.confidence,
                capabilities=result_detail.capabilities.model_dump(
                    mode="json", by_alias=True
                ),
            )
            session.add(row)
            _invalidate_derived_chunks(session, match)
            session.flush()
            return _row_detail(row)
    except CalibrationApiError as error:
        return _error_response(error)
    except IntegrityError:
        return _error_response(
            CalibrationApiError(
                "calibration_revision_conflict",
                "saved calibration changed since the requested revision",
                409,
            )
        )


_MAX_WINDOW_US = 120_000_000
_MAX_PAGE = 5_000


def _invalid_cursor(error: Exception | None = None) -> ApiError:
    failure = ApiError("invalid_cursor", "pagination cursor is invalid", 422)
    if error is not None:
        failure.__cause__ = error
    return failure


def _cursor_int(
    value: object,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _invalid_cursor()
    if maximum is not None and value > maximum:
        raise _invalid_cursor()
    return value


def _cursor_text(
    value: object,
    *,
    maximum: int = 500,
    allow_empty: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or (not value and not allow_empty)
        or len(value) > maximum
    ):
        raise _invalid_cursor()
    return value


def _bound_cursor(
    request: Request,
    cursor: str | None,
    binding: dict[str, object],
    length: int,
) -> tuple[object, ...] | None:
    decoded = decode_api_cursor(request.app.state.cursor_secret, cursor, binding)
    if decoded is not None and len(decoded) != length:
        raise _invalid_cursor()
    return decoded


def _range(start_us: int, end_us: int) -> tuple[int, int]:
    if start_us < 0 or end_us <= start_us:
        raise ApiError(
            "invalid_range",
            "time range must satisfy 0 <= startUs < endUs",
            422,
        )
    if end_us - start_us > _MAX_WINDOW_US:
        raise ApiError(
            "range_too_large",
            "time range cannot exceed 120 seconds",
            422,
        )
    return start_us, end_us


def _api_match(session: object, match_id: str) -> Match:
    match = session.scalar(select(Match).where(Match.public_id == match_id))
    if match is None:
        raise ApiError("match_not_found", "match was not found", 404)
    return match


def _report_summary_api(row: ReportRevision) -> ReportSummary:
    return ReportSummary(
        revision=row.revision,
        prediction_revision=row.prediction_revision,
        calibration_revision=row.calibration_revision,
        created_at=row.created_at,
        section_hashes=dict(row.section_hashes),
    )


def _current_report(session: object, match: Match) -> ReportRevision:
    report = session.scalar(
        select(ReportRevision)
        .where(ReportRevision.match_id == match.id)
        .order_by(ReportRevision.revision.desc())
        .limit(1)
    )
    if report is None:
        raise ApiError(
            "report_not_found",
            "match does not have a completed report",
            404,
        )
    return report


def _selected_report(
    session: object, match: Match, revision: int | None
) -> ReportRevision:
    if revision is None:
        return _current_report(session, match)
    report = session.scalar(
        select(ReportRevision).where(
            ReportRevision.match_id == match.id,
            ReportRevision.revision == revision,
        )
    )
    if report is None:
        raise ApiError("report_not_found", "report revision was not found", 404)
    return report


@router.get(
    "/matches/{match_id}/reports",
    response_model=ReportListPage,
    operation_id="listReports",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def list_reports(
    match_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> ReportListPage:
    binding: dict[str, object] = {
        "kind": "reports",
        "matchId": match_id,
    }
    decoded = _bound_cursor(request, cursor, binding, 1)
    before_revision = (
        _cursor_int(decoded[0], minimum=1) if decoded is not None else None
    )
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        query = select(ReportRevision).where(
            ReportRevision.match_id == match.id
        )
        if before_revision is not None:
            query = query.where(ReportRevision.revision < before_revision)
        rows = session.scalars(
            query.order_by(ReportRevision.revision.desc()).limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return ReportListPage(
            items=[_report_summary_api(row) for row in rows],
            next_cursor=(
                encode_api_cursor(
                    request.app.state.cursor_secret,
                    binding,
                    (rows[-1].revision,),
                )
                if has_more and rows
                else None
            ),
        )


@router.get(
    "/matches/{match_id}/reports/latest",
    response_model=MatchReport,
    operation_id="getLatestReport",
    responses={404: {"model": ErrorResponse}},
)
def get_latest_report(match_id: str, request: Request) -> MatchReport:
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        return _report_from_row(match.public_id, _current_report(session, match))


@router.get(
    "/matches/{match_id}/reports/{revision}",
    response_model=MatchReport,
    operation_id="getReportRevision",
    responses={404: {"model": ErrorResponse}},
)
def get_report_revision(
    match_id: str, revision: int, request: Request
) -> MatchReport:
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        row = session.scalar(
            select(ReportRevision).where(
                ReportRevision.match_id == match.id,
                ReportRevision.revision == revision,
            )
        )
        if row is None:
            raise ApiError("report_not_found", "report revision was not found", 404)
        return _report_from_row(match.public_id, row)


def _report_artifact_chunks(
    session: object,
    match: Match,
    report_revision: int,
    stage: Stage,
    start_us: int,
    end_us: int,
) -> tuple[ReportRevision, AnalysisJob, list[JobChunk]]:
    report = session.scalar(
        select(ReportRevision).where(
            ReportRevision.match_id == match.id,
            ReportRevision.revision == report_revision,
        )
    )
    if report is None:
        raise ApiError(
            "report_not_found", "report revision was not found", 404
        )
    publication = session.scalar(
        select(StagePublication)
        .where(
            StagePublication.match_id == match.id,
            StagePublication.stage == Stage.CLASSIFICATION,
            StagePublication.prediction_revision
            == report.prediction_revision,
        )
        .order_by(StagePublication.id.desc())
        .limit(1)
    )
    if publication is None:
        raise ApiError(
            "analysis_artifact_unavailable",
            "selected report has no immutable analysis artifact publication",
            409,
        )
    job = session.get(AnalysisJob, publication.analysis_job_id)
    if job is None or job.match_id != match.id:
        raise ApiError(
            "analysis_artifact_unavailable",
            "selected report analysis artifacts are unavailable",
            409,
        )
    chunks = session.scalars(
        select(JobChunk)
        .where(
            JobChunk.analysis_job_id == job.id,
            JobChunk.stage == stage,
            # A newer court setup marks reusable computation stale, but does
            # not revoke the artifacts of this explicitly selected publication.
            JobChunk.status.in_((StageStatus.COMPLETED, StageStatus.INVALIDATED)),
            JobChunk.start_us < end_us,
            JobChunk.end_us > start_us,
            JobChunk.artifact_payload_path.is_not(None),
        )
        .order_by(JobChunk.start_us, JobChunk.end_us, JobChunk.id)
    ).all()
    return report, job, list(chunks)


def _artifact_page(
    request: Request,
    chunks: list[JobChunk],
    *,
    start_us: int,
    end_us: int,
    columns: tuple[str, ...],
    row_limit: int,
    key_for: Callable[[dict[str, object]], tuple[object, ...]],
    after: tuple[object, ...] | None,
) -> tuple[list[dict[str, object]], bool]:
    storage: LocalStorage = request.app.state.storage
    relative_paths = {
        Path(chunk.artifact_payload_path)
        for chunk in chunks
        if chunk.artifact_payload_path is not None
    }

    def stream(
        relative: Path,
    ) -> Iterator[tuple[tuple[object, ...], dict[str, object]]]:
        stored = storage.resolve(relative, owned_paths=relative_paths)
        artifact = ds.dataset(stored.absolute, format="parquet")
        selected_columns = [
            column for column in columns if column in artifact.schema.names
        ]
        if "timestamp_us" not in selected_columns:
            raise ValueError("artifact has no timestamp column")
        lower_bound = (
            max(start_us, _cursor_int(after[0]))
            if after is not None
            else start_us
        )
        expression = (
            (ds.field("timestamp_us") >= lower_bound)
            & (ds.field("timestamp_us") < end_us)
        )
        scanner = artifact.scanner(
            columns=selected_columns,
            filter=expression,
            batch_size=128,
            use_threads=False,
        )
        for batch in scanner.to_batches():
            for row in sorted(batch.to_pylist(), key=key_for):
                key = key_for(row)
                if after is None or key > after:
                    yield key, row

    try:
        streams = [stream(relative) for relative in sorted(relative_paths)]
        heap: list[
            tuple[
                tuple[object, ...],
                int,
                dict[str, object],
            ]
        ] = []
        for index, rows in enumerate(streams):
            try:
                key, row = next(rows)
            except StopIteration:
                continue
            heapq.heappush(heap, (key, index, row))
        selected: list[dict[str, object]] = []
        last_key: tuple[object, ...] | None = None
        while heap and len(selected) < row_limit + 1:
            key, index, row = heapq.heappop(heap)
            if key != last_key:
                selected.append(row)
                last_key = key
            try:
                next_key, next_row = next(streams[index])
            except StopIteration:
                continue
            heapq.heappush(heap, (next_key, index, next_row))
        return selected[:row_limit], len(selected) > row_limit
    except (
        FileNotFoundError,
        KeyError,
        PermissionError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise ApiError(
            "artifact_unavailable",
            "selected analysis artifact is unavailable or invalid",
            503,
        ) from error


def _artifact_selection(
    job: AnalysisJob,
    stage: Stage,
    chunks: list[JobChunk],
    rows: list[dict[str, object]],
) -> ArtifactSelection:
    source_ids = sorted(
        {
            str(row["source_manifest_id"])
            for row in rows
            if row.get("source_manifest_id") is not None
        }
    )
    model_ids = sorted(
        {
            str(row["model_manifest_id"])
            for row in rows
            if row.get("model_manifest_id") is not None
        }
    )
    availability = (
        "available"
        if chunks and all(chunk.artifact_availability != "unavailable" for chunk in chunks)
        else "unavailable"
    )
    warnings = sorted(
        {
            warning
            for chunk in chunks
            for warning in (chunk.artifact_warnings or [])
        }
    )
    return ArtifactSelection(
        job_id=job.public_id,
        stage=stage,
        availability=availability,
        warnings=warnings,
        source_manifest_ids=source_ids,
        model_manifest_ids=model_ids,
    )


_PLAYER_COLUMNS = (
    "player_id",
    "timestamp_us",
    "source_timestamp_us",
    "source_frame_index",
    "box_x1",
    "box_y1",
    "box_x2",
    "box_y2",
    "keypoints_x",
    "keypoints_y",
    "keypoints_confidence",
    "detection_confidence",
    "feet_x",
    "feet_y",
    "feet_uncertainty_px",
    "evidence",
    "evidence_start_timestamp_us",
    "evidence_end_timestamp_us",
    "evidence_start_frame_index",
    "evidence_end_frame_index",
    "association_confidence",
    "ambiguous",
    "ambiguity_reason",
    "floor_x_m",
    "floor_y_m",
    "floor_uncertainty_m",
    "calibration_revision",
    "calibration_provenance",
    "source_manifest_id",
    "model_manifest_id",
)


def _player_key(row: dict[str, object]) -> tuple[int, str, str, str]:
    return (
        int(row["timestamp_us"]),
        str(row["player_id"]),
        str(row["source_manifest_id"]),
        str(row["model_manifest_id"]),
    )


def _player_detail(row: dict[str, object]) -> PlayerObservationDetail:
    floor = (
        (float(row["floor_x_m"]), float(row["floor_y_m"]))
        if row.get("floor_x_m") is not None and row.get("floor_y_m") is not None
        else None
    )
    return PlayerObservationDetail(
        player_id=str(row["player_id"]),
        timestamp_us=int(row["timestamp_us"]),
        source_timestamp_us=(
            int(row["source_timestamp_us"])
            if row.get("source_timestamp_us") is not None
            else None
        ),
        source_frame_index=(
            int(row["source_frame_index"])
            if row.get("source_frame_index") is not None
            else None
        ),
        box=(
            float(row["box_x1"]),
            float(row["box_y1"]),
            float(row["box_x2"]),
            float(row["box_y2"]),
        ),
        keypoints=[
            PoseKeypointDetail(x=float(x), y=float(y), confidence=float(confidence))
            for x, y, confidence in zip(
                row["keypoints_x"],
                row["keypoints_y"],
                row["keypoints_confidence"],
                strict=True,
            )
        ],
        skeleton_edges=list(_COCO_SKELETON_EDGES),
        detection_confidence=float(row["detection_confidence"]),
        feet=(float(row["feet_x"]), float(row["feet_y"])),
        feet_uncertainty_px=float(row["feet_uncertainty_px"]),
        evidence=str(row["evidence"]),
        evidence_start_timestamp_us=int(row["evidence_start_timestamp_us"]),
        evidence_end_timestamp_us=int(row["evidence_end_timestamp_us"]),
        evidence_start_frame_index=int(row["evidence_start_frame_index"]),
        evidence_end_frame_index=int(row["evidence_end_frame_index"]),
        association_confidence=float(row["association_confidence"]),
        ambiguous=bool(row["ambiguous"]),
        ambiguity_reason=(
            str(row["ambiguity_reason"])
            if row.get("ambiguity_reason") is not None
            else None
        ),
        floor=floor,
        floor_uncertainty_m=(
            float(row["floor_uncertainty_m"])
            if row.get("floor_uncertainty_m") is not None
            else None
        ),
        calibration_revision=(
            str(row["calibration_revision"])
            if row.get("calibration_revision") is not None
            else None
        ),
        calibration_provenance=(
            str(row["calibration_provenance"])
            if row.get("calibration_provenance") is not None
            else None
        ),
        source_manifest_id=str(row["source_manifest_id"]),
        model_manifest_id=str(row["model_manifest_id"]),
    )


@router.get(
    "/matches/{match_id}/observations/players",
    response_model=PlayerObservationPage,
    operation_id="listPlayerObservations",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def list_player_observations(
    match_id: str,
    request: Request,
    start_us: int = Query(alias="startUs"),
    end_us: int = Query(alias="endUs"),
    cursor: str | None = None,
    revision: int = Query(ge=1),
    limit: int = Query(default=500, ge=1, le=_MAX_PAGE),
) -> PlayerObservationPage:
    start_us, end_us = _range(start_us, end_us)
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        report, job, chunks = _report_artifact_chunks(
            session, match, revision, Stage.PLAYERS, start_us, end_us
        )
        binding: dict[str, object] = {
            "kind": "playerObservations",
            "matchId": match.public_id,
            "startUs": start_us,
            "endUs": end_us,
            "jobId": job.public_id,
            "reportRevision": report.revision,
            "predictionRevision": report.prediction_revision,
        }
        decoded = _bound_cursor(request, cursor, binding, 4)
        after = (
            (
                _cursor_int(decoded[0]),
                _cursor_text(decoded[1], maximum=100),
                _cursor_text(decoded[2]),
                _cursor_text(decoded[3]),
            )
            if decoded is not None
            else None
        )
        page_rows, has_more = _artifact_page(
            request,
            chunks,
            start_us=start_us,
            end_us=end_us,
            columns=_PLAYER_COLUMNS,
            row_limit=limit,
            key_for=_player_key,
            after=after,
        )
        return PlayerObservationPage(
            items=[_player_detail(row) for row in page_rows],
            next_cursor=(
                encode_api_cursor(
                    request.app.state.cursor_secret,
                    binding,
                    _player_key(page_rows[-1]),
                )
                if has_more and page_rows
                else None
            ),
            start_us=start_us,
            end_us=end_us,
            artifact=_artifact_selection(
                job, Stage.PLAYERS, chunks, page_rows
            ),
        )


_BALL_COLUMNS = (
    "timestamp_us",
    "source_timestamp_us",
    "source_frame_index",
    "source_width",
    "source_height",
    "x",
    "y",
    "probability",
    "covariance",
    "candidates",
    "visible",
    "candidate_count",
    "evidence",
    "evidence_start_timestamp_us",
    "evidence_end_timestamp_us",
    "evidence_start_frame_index",
    "evidence_end_frame_index",
    "ambiguous",
    "ambiguity_reason",
    "segment_id",
    "source_manifest_id",
    "model_manifest_id",
    "device",
    "device_fallback",
)


def _ball_key(row: dict[str, object]) -> tuple[int, int, str, str]:
    return (
        int(row["timestamp_us"]),
        int(row["source_frame_index"]) if row.get("source_frame_index") is not None else -1,
        str(row["source_manifest_id"]),
        str(row["model_manifest_id"]),
    )


def _covariance_detail(value: object) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if not isinstance(value, dict):
        return None
    required = ("xx", "xy", "yx", "yy")
    if any(name not in value for name in required):
        return None
    return (
        (float(value["xx"]), float(value["xy"])),
        (float(value["yx"]), float(value["yy"])),
    )


def _ball_candidate_detail(value: object) -> BallCandidateDetail | None:
    if not isinstance(value, dict):
        return None
    covariance = (
        (float(value["covariance_xx"]), float(value["covariance_xy"])),
        (float(value["covariance_yx"]), float(value["covariance_yy"])),
    )
    return BallCandidateDetail(
        x=float(value["x"]),
        y=float(value["y"]),
        probability=float(value["peak_probability"]),
        covariance=covariance,
    )


def _ball_detail(row: dict[str, object]) -> BallObservationDetail:
    return BallObservationDetail(
        timestamp_us=int(row["timestamp_us"]),
        source_timestamp_us=(
            int(row["source_timestamp_us"])
            if row.get("source_timestamp_us") is not None
            else None
        ),
        source_frame_index=(
            int(row["source_frame_index"])
            if row.get("source_frame_index") is not None
            else None
        ),
        source_width=int(row["source_width"]),
        source_height=int(row["source_height"]),
        x=float(row["x"]) if row.get("x") is not None else None,
        y=float(row["y"]) if row.get("y") is not None else None,
        probability=float(row["probability"]),
        covariance=_covariance_detail(row.get("covariance")),
        candidates=[
            candidate
            for value in row["candidates"]
            if (candidate := _ball_candidate_detail(value)) is not None
        ],
        visible=bool(row["visible"]),
        candidate_count=int(row["candidate_count"]),
        evidence=str(row["evidence"]),
        evidence_start_timestamp_us=int(row["evidence_start_timestamp_us"]),
        evidence_end_timestamp_us=int(row["evidence_end_timestamp_us"]),
        evidence_start_frame_index=int(row["evidence_start_frame_index"]),
        evidence_end_frame_index=int(row["evidence_end_frame_index"]),
        ambiguous=bool(row["ambiguous"]),
        ambiguity_reason=(
            str(row["ambiguity_reason"])
            if row.get("ambiguity_reason") is not None
            else None
        ),
        segment_id=(
            str(row["segment_id"]) if row.get("segment_id") is not None else None
        ),
        source_manifest_id=str(row["source_manifest_id"]),
        model_manifest_id=str(row["model_manifest_id"]),
        device=str(row["device"]),
        device_fallback=bool(row["device_fallback"]),
    )


@router.get(
    "/matches/{match_id}/observations/ball",
    response_model=BallObservationPage,
    operation_id="listBallObservations",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def list_ball_observations(
    match_id: str,
    request: Request,
    start_us: int = Query(alias="startUs"),
    end_us: int = Query(alias="endUs"),
    cursor: str | None = None,
    revision: int = Query(ge=1),
    limit: int = Query(default=500, ge=1, le=_MAX_PAGE),
) -> BallObservationPage:
    start_us, end_us = _range(start_us, end_us)
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        report, job, chunks = _report_artifact_chunks(
            session, match, revision, Stage.BALL, start_us, end_us
        )
        binding: dict[str, object] = {
            "kind": "ballObservations",
            "matchId": match.public_id,
            "startUs": start_us,
            "endUs": end_us,
            "jobId": job.public_id,
            "reportRevision": report.revision,
            "predictionRevision": report.prediction_revision,
        }
        decoded = _bound_cursor(request, cursor, binding, 4)
        after = (
            (
                _cursor_int(decoded[0]),
                _cursor_int(decoded[1], minimum=-1),
                _cursor_text(decoded[2]),
                _cursor_text(decoded[3]),
            )
            if decoded is not None
            else None
        )
        page_rows, has_more = _artifact_page(
            request,
            chunks,
            start_us=start_us,
            end_us=end_us,
            columns=_BALL_COLUMNS,
            row_limit=limit,
            key_for=_ball_key,
            after=after,
        )
        return BallObservationPage(
            items=[_ball_detail(row) for row in page_rows],
            next_cursor=(
                encode_api_cursor(
                    request.app.state.cursor_secret,
                    binding,
                    _ball_key(page_rows[-1]),
                )
                if has_more and page_rows
                else None
            ),
            start_us=start_us,
            end_us=end_us,
            artifact=_artifact_selection(job, Stage.BALL, chunks, page_rows),
        )


def _canonical_binding(
    kind: str,
    match: Match,
    report: ReportRevision,
    start_us: int,
    end_us: int,
    *,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    binding: dict[str, object] = {
        "kind": kind,
        "matchId": match.public_id,
        "startUs": start_us,
        "endUs": end_us,
        "reportRevision": report.revision,
        "predictionRevision": report.prediction_revision,
    }
    if extra is not None:
        binding.update(extra)
    return binding


def _canonical_shot_key(row: dict[str, object]) -> tuple[int, str]:
    return (
        int(row["source_timestamp_us"]),
        str(row["prediction_id"]),
    )


def _canonical_shot_detail(
    row: dict[str, object], prediction_revision: int
) -> ShotDetail:
    contact = (
        (float(row["contact_x_m"]), float(row["contact_y_m"]))
        if row.get("contact_x_m") is not None
        and row.get("contact_y_m") is not None
        else None
    )
    return ShotDetail(
        id=str(row["prediction_id"]),
        timestamp_us=int(row["source_timestamp_us"]),
        prediction_revision=prediction_revision,
        rally_id=(
            str(row["rally_id"]) if row.get("rally_id") is not None else None
        ),
        hitter=(
            str(row["hitter"]) if row.get("hitter") is not None else None
        ),
        shot_kind=str(row["shot_type"]),
        is_volley=bool(row["is_volley"]),
        outcome=str(row["outcome"]),
        contact=contact,
        speed_m_s=(
            float(row["speed_m_s"])
            if row.get("speed_m_s") is not None
            else None
        ),
        speed_unavailable_reason=(
            str(row["speed_unavailable_reason"])
            if row.get("speed_unavailable_reason") is not None
            else None
        ),
        source_evidence_ids=[
            str(value) for value in row["source_evidence_ids"]
        ],
    )


def _canonical_source_key(
    row: dict[str, object], source_type: str
) -> tuple[int, str]:
    timestamp_name = (
        "start_timestamp_us"
        if source_type == "rally"
        else "source_timestamp_us"
    )
    return int(row[timestamp_name]), str(row["prediction_id"])


def _bounded_canonical_source(
    session: object,
    match: Match,
    report: ReportRevision,
    *,
    source_type: str,
    start_us: int | None,
    end_us: int | None,
    after: tuple[int, str] | None,
    limit: int,
    pending_only: bool = False,
    contact_only: bool = False,
    include_rally_context: bool = False,
) -> CanonicalState:
    entity_types = {source_type}
    if source_type == "error_candidate" or include_rally_context:
        entity_types.update({"shot", "rally"})
    corrections = list(
        session.scalars(
            select(Correction)
            .where(
                Correction.match_id == match.id,
                Correction.prediction_revision == report.prediction_revision,
                Correction.status == CorrectionStatus.ACTIVE,
                Correction.expected_report_revision < report.revision,
                or_(
                    Correction.target_type.in_(entity_types),
                    Correction.review_entity_type.in_(entity_types),
                ),
            )
            .order_by(Correction.id)
        ).all()
    )
    corrected_ids: dict[str, set[str]] = {
        "shot": set(),
        "rally": set(),
        "error_candidate": set(),
    }
    for correction in corrections:
        if correction.target_type in corrected_ids:
            corrected_ids[correction.target_type].add(correction.target_id)
        if (
            correction.review_entity_type in corrected_ids
            and correction.review_entity_id is not None
        ):
            corrected_ids[correction.review_entity_type].add(
                correction.review_entity_id
            )
        if correction.command_type == "merge_rallies":
            other_id = correction.after_payload.get("other_target_id")
            if isinstance(other_id, str):
                corrected_ids["rally"].add(other_id)

    model = (
        Shot
        if source_type == "shot"
        else Rally
        if source_type == "rally"
        else ErrorCandidate
    )
    timestamp_column = (
        Rally.start_timestamp_us
        if source_type == "rally"
        else model.source_timestamp_us
    )
    selection_parts = [timestamp_column.is_not(None)]
    if start_us is not None and end_us is not None:
        if source_type == "rally":
            selection_parts.extend(
                [
                    Rally.timing_available.is_(True),
                    Rally.end_timestamp_us.is_not(None),
                    Rally.start_timestamp_us < end_us,
                    Rally.end_timestamp_us > start_us,
                ]
            )
        else:
            selection_parts.extend(
                [timestamp_column >= start_us, timestamp_column < end_us]
            )
    if after is not None:
        selection_parts.append(
            or_(
                timestamp_column > after[0],
                and_(
                    timestamp_column == after[0],
                    model.prediction_id > after[1],
                ),
            )
        )
    if pending_only:
        selection_parts.append(model.review_status == "pending")
    if contact_only:
        selection_parts.extend(
            [Shot.contact_x_m.is_not(None), Shot.contact_y_m.is_not(None)]
        )
    selection = and_(*selection_parts)
    source_ids = corrected_ids[source_type]
    source_statement = select(model)
    if source_type == "shot":
        source_statement = source_statement.options(joinedload(Shot.rally))
    source_statement = (
        source_statement.where(
            model.match_id == match.id,
            model.prediction_revision == report.prediction_revision,
            (
                or_(selection, model.prediction_id.in_(source_ids))
                if source_ids
                else selection
            ),
        )
        .order_by(timestamp_column, model.prediction_id)
        .limit(limit + 1 + len(source_ids))
    )
    source_rows = list(session.scalars(source_statement).all())

    shot_rows = source_rows if source_type == "shot" else []
    rally_rows = source_rows if source_type == "rally" else []
    error_rows = source_rows if source_type == "error_candidate" else []
    if source_type == "error_candidate":
        target_shot_ids = {
            row.target_prediction_id
            for row in error_rows
            if row.target_type == "shot"
        }
        target_shot_ids.update(corrected_ids["shot"])
        if target_shot_ids:
            shot_rows = list(
                session.scalars(
                    select(Shot)
                    .options(joinedload(Shot.rally))
                    .where(
                        Shot.match_id == match.id,
                        Shot.prediction_revision
                        == report.prediction_revision,
                        Shot.prediction_id.in_(target_shot_ids),
                    )
                    .limit(len(target_shot_ids))
                ).all()
            )

    if source_type == "error_candidate" or include_rally_context:
        provisional_shots = [_row_payload(row) for row in shot_rows]
        provisional_errors = [_error_payload(row) for row in error_rows]
        for correction in corrections:
            _fold_correction(
                provisional_shots, [], provisional_errors, correction
            )
        rally_ids = set(corrected_ids["rally"])
        rally_ids.update(
            str(row["rally_id"])
            for row in provisional_shots
            if row.get("rally_id") is not None
        )
        rally_conditions = []
        shot_timestamps = [
            int(row["source_timestamp_us"]) for row in provisional_shots
        ]
        if shot_timestamps:
            rally_conditions.append(
                and_(
                    Rally.timing_available.is_(True),
                    Rally.start_timestamp_us.is_not(None),
                    Rally.end_timestamp_us.is_not(None),
                    Rally.start_timestamp_us <= max(shot_timestamps),
                    Rally.end_timestamp_us >= min(shot_timestamps),
                )
            )
        if rally_ids:
            rally_conditions.append(Rally.prediction_id.in_(rally_ids))
        if rally_conditions:
            rally_rows = list(
                session.scalars(
                    select(Rally)
                    .where(
                        Rally.match_id == match.id,
                        Rally.prediction_revision
                        == report.prediction_revision,
                        or_(*rally_conditions),
                    )
                    .order_by(
                        Rally.start_timestamp_us,
                        Rally.prediction_id,
                    )
                    .limit(limit + 1 + len(rally_ids) + len(shot_rows))
                ).all()
            )

    shots = [_row_payload(row) for row in shot_rows]
    rallies = [_rally_payload(row) for row in rally_rows]
    errors = [_error_payload(row) for row in error_rows]
    for correction in corrections:
        _fold_correction(shots, rallies, errors, correction)
    if shots and rallies:
        _assign_shots_to_rallies(shots, rallies)
    return CanonicalState(shots=shots, rallies=rallies, errors=errors, tracks=[])


@router.get(
    "/matches/{match_id}/shots",
    response_model=ShotPage,
    operation_id="listShots",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def list_shots(
    match_id: str,
    request: Request,
    start_us: int = Query(alias="startUs"),
    end_us: int = Query(alias="endUs"),
    report_revision: int | None = Query(default=None, alias="reportRevision", ge=1),
    cursor: str | None = None,
    limit: int = Query(default=500, ge=1, le=_MAX_PAGE),
) -> ShotPage:
    start_us, end_us = _range(start_us, end_us)
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        report = _selected_report(session, match, report_revision)
        binding = _canonical_binding(
            "shots", match, report, start_us, end_us
        )
        decoded = _bound_cursor(request, cursor, binding, 2)
        after = (
            (_cursor_int(decoded[0]), _cursor_text(decoded[1]))
            if decoded is not None
            else None
        )
        state = _bounded_canonical_source(
            session,
            match,
            report,
            source_type="shot",
            start_us=start_us,
            end_us=end_us,
            after=after,
            limit=limit,
            include_rally_context=True,
        )
        rows = sorted(
            (
                row
                for row in state.shots
                if start_us <= int(row["source_timestamp_us"]) < end_us
                and (
                    after is None
                    or _canonical_shot_key(row) > after
                )
            ),
            key=_canonical_shot_key,
        )[: limit + 1]
        has_more = len(rows) > limit
        rows = rows[:limit]
        return ShotPage(
            items=[
                _canonical_shot_detail(row, report.prediction_revision)
                for row in rows
            ],
            next_cursor=(
                encode_api_cursor(
                    request.app.state.cursor_secret,
                    binding,
                    _canonical_shot_key(rows[-1]),
                )
                if has_more and rows
                else None
            ),
            prediction_revision=report.prediction_revision,
        )


def _canonical_rally_key(row: dict[str, object]) -> tuple[int, str]:
    return (
        int(row["start_timestamp_us"]),
        str(row["prediction_id"]),
    )


def _canonical_rally_detail(
    row: dict[str, object], prediction_revision: int
) -> RallyDetail:
    return RallyDetail(
        id=str(row["prediction_id"]),
        ordinal=int(row["ordinal"]),
        start_us=(
            int(row["start_timestamp_us"])
            if row.get("start_timestamp_us") is not None
            else None
        ),
        end_us=(
            int(row["end_timestamp_us"])
            if row.get("end_timestamp_us") is not None
            else None
        ),
        timing_available=bool(row["timing_available"]),
        prediction_revision=prediction_revision,
        source_evidence_ids=[
            str(value) for value in row["source_evidence_ids"]
        ],
    )

def _correction_target(
    target_type: str,
    target_id: str,
    timestamp_us: int,
    evidence_ids: list[str],
    start_timestamp_us: int,
    end_timestamp_us: int,
    start_frame_index: int | None,
    end_frame_index: int | None,
) -> CorrectionTargetDetail:
    return CorrectionTargetDetail(
        target_type=target_type,
        target_id=target_id,
        source_timestamp_us=timestamp_us,
        source_evidence_ids=evidence_ids,
        evidence_start_timestamp_us=start_timestamp_us,
        evidence_end_timestamp_us=end_timestamp_us,
        evidence_start_frame_index=start_frame_index,
        evidence_end_frame_index=end_frame_index,
    )


def _review_item_detail(
    row: dict[str, object], state: CanonicalState
) -> ReviewItemDetail:
    payload = row.get("evidence_payload")
    evidence_payload = payload if isinstance(payload, dict) else {}
    issue_value = evidence_payload.get("issue")
    issue = (
        str(issue_value)
        if isinstance(issue_value, str) and issue_value
        else "rally_boundary"
        if row.get("target_type") == "rally"
        else "accept"
    )
    probability_value = evidence_payload.get("probabilities")
    probabilities = {
        str(name): float(value)
        for name, value in (
            probability_value.items()
            if isinstance(probability_value, dict)
            else ()
        )
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    }
    reason_value = evidence_payload.get("reasons")
    reasons = (
        [str(value) for value in reason_value if isinstance(value, str)]
        if isinstance(reason_value, list)
        else []
    )
    timestamp_us = int(row.get("source_timestamp_us") or 0)
    start_timestamp_value = evidence_payload.get("evidence_start_timestamp_us")
    end_timestamp_value = evidence_payload.get("evidence_end_timestamp_us")
    evidence_start_timestamp_us = (
        int(start_timestamp_value)
        if isinstance(start_timestamp_value, int) and start_timestamp_value >= 0
        else timestamp_us
    )
    evidence_end_timestamp_us = (
        int(end_timestamp_value)
        if isinstance(end_timestamp_value, int)
        and end_timestamp_value >= evidence_start_timestamp_us
        else timestamp_us
    )
    start_frame = evidence_payload.get("evidence_start_frame_index")
    end_frame = evidence_payload.get("evidence_end_frame_index")
    evidence_start_frame_index = (
        int(start_frame)
        if isinstance(start_frame, int) and start_frame >= 0
        else None
    )
    evidence_end_frame_index = (
        int(end_frame)
        if isinstance(end_frame, int) and end_frame >= 0
        else None
    )
    confidence_value = evidence_payload.get("confidence")
    confidence = (
        float(confidence_value)
        if isinstance(confidence_value, (int, float))
        and not isinstance(confidence_value, bool)
        and math.isfinite(float(confidence_value))
        and 0 <= float(confidence_value) <= 1
        else None
    )
    provenance_value = evidence_payload.get(
        "provenance", evidence_payload.get("source_state")
    )
    provenance = (
        str(provenance_value)
        if provenance_value in {"observed", "reconstructed", "ambiguous"}
        else "unavailable"
    )
    evidence_ids = [str(value) for value in row["source_evidence_ids"]]
    error_target = _correction_target(
        "error_candidate",
        str(row["prediction_id"]),
        timestamp_us,
        evidence_ids,
        evidence_start_timestamp_us,
        evidence_end_timestamp_us,
        evidence_start_frame_index,
        evidence_end_frame_index,
    )
    command_targets: dict[str, CorrectionTargetDetail] = {
        CorrectionCommandType.ACCEPT.value: error_target,
        CorrectionCommandType.REJECT.value: error_target,
    }
    shot = next(
        (
            candidate
            for candidate in state.shots
            if candidate["prediction_id"] == row["target_prediction_id"]
        ),
        None,
    )
    if shot is not None:
        shot_timestamp = int(shot["source_timestamp_us"])
        shot_frame = int(shot["frame_index"])
        shot_target = _correction_target(
            "shot",
            str(shot["prediction_id"]),
            shot_timestamp,
            [str(value) for value in shot["source_evidence_ids"]],
            shot_timestamp,
            shot_timestamp,
            shot_frame,
            shot_frame,
        )
        for command in (
            CorrectionCommandType.CHANGE_HITTER,
            CorrectionCommandType.CHANGE_SHOT_TYPE,
            CorrectionCommandType.ADJUST_CONTACT_TIME,
            CorrectionCommandType.CHANGE_OUTCOME,
            CorrectionCommandType.BALL_CONTROL_POINT,
        ):
            command_targets[command.value] = shot_target
        rally = next(
            (
                candidate
                for candidate in state.rallies
                if candidate["prediction_id"] == shot.get("rally_id")
            ),
            None,
        )
        if (
            rally is not None
            and rally.get("start_timestamp_us") is not None
            and rally.get("end_timestamp_us") is not None
        ):
            rally_target = _correction_target(
                "rally",
                str(rally["prediction_id"]),
                int(rally["start_timestamp_us"]),
                [str(value) for value in rally["source_evidence_ids"]],
                int(rally["start_timestamp_us"]),
                int(rally["end_timestamp_us"]),
                int(rally["start_frame"]),
                int(rally["end_frame"]),
            )
            command_targets[CorrectionCommandType.SPLIT_RALLY.value] = rally_target
            command_targets[CorrectionCommandType.MERGE_RALLIES.value] = rally_target
    command_impacts = {
        command.value: CorrectionImpactDetail(
            invalidated_sections=sorted(INVALIDATIONS[command]),
            invalidated_stats=list(_INVALIDATED_STATS[command]),
        )
        for command in CorrectionCommandType
        if command.value in command_targets
    }
    default_command = _COMMAND_BY_ISSUE.get(issue, CorrectionCommandType.ACCEPT)
    if default_command.value not in command_impacts:
        default_command = CorrectionCommandType.ACCEPT
    default_impact = command_impacts[default_command.value]
    return ReviewItemDetail(
        id=str(row["prediction_id"]),
        target_type="error_candidate",
        kind=str(row["kind"]),
        timestamp_us=timestamp_us,
        end_us=evidence_end_timestamp_us,
        confidence=confidence,
        issue=issue,
        provenance=provenance,
        probabilities=probabilities,
        reasons=reasons,
        evidence_ids=evidence_ids,
        evidence_start_timestamp_us=evidence_start_timestamp_us,
        evidence_end_timestamp_us=evidence_end_timestamp_us,
        evidence_start_frame_index=evidence_start_frame_index,
        evidence_end_frame_index=evidence_end_frame_index,
        invalidated_sections=default_impact.invalidated_sections,
        invalidated_stats=default_impact.invalidated_stats,
        summary={
            **evidence_payload,
            "reviewStatus": row["review_status"],
            "targetId": row["target_prediction_id"],
        },
        command_targets=command_targets,
        command_impacts=command_impacts,
        review_entity_type="error_candidate",
        review_entity_id=str(row["prediction_id"]),
        review_status=str(row["review_status"]),
    )


def _error_timeline_item(
    row: dict[str, object], state: CanonicalState
) -> TimelineItem:
    detail = _review_item_detail(row, state)
    return TimelineItem(
        kind="error",
        id=detail.public_id,
        timestamp_us=detail.timestamp_us,
        end_us=detail.end_us,
        evidence_ids=detail.evidence_ids,
        summary={
            **detail.summary,
            "issue": detail.issue,
            "confidence": detail.confidence,
            "probabilities": detail.probabilities,
            "reasons": detail.reasons,
            "provenance": detail.provenance,
            "evidenceStartTimestampUs": detail.evidence_start_timestamp_us,
            "evidenceEndTimestampUs": detail.evidence_end_timestamp_us,
            "evidenceStartFrameIndex": detail.evidence_start_frame_index,
            "evidenceEndFrameIndex": detail.evidence_end_frame_index,
            "invalidatedSections": detail.invalidated_sections,
            "invalidatedStats": detail.invalidated_stats,
            "reviewEntityType": detail.review_entity_type,
            "reviewEntityId": detail.review_entity_id,
            "reviewStatus": detail.review_status,
            "commandTargets": {
                key: value.model_dump(by_alias=True)
                for key, value in detail.command_targets.items()
            },
            "commandImpacts": {
                key: value.model_dump(by_alias=True)
                for key, value in detail.command_impacts.items()
            },
        },
    )


def _timeline_review_detail(
    item: TimelineItem, review_entity_type: str, review_status: str
) -> ReviewItemDetail:
    summary = dict(item.summary)
    targets_value = summary.get("commandTargets")
    impacts_value = summary.get("commandImpacts")
    command_targets = {
        str(command): CorrectionTargetDetail.model_validate(value)
        for command, value in (
            targets_value.items() if isinstance(targets_value, dict) else ()
        )
    }
    command_impacts = {
        str(command): CorrectionImpactDetail.model_validate(value)
        for command, value in (
            impacts_value.items() if isinstance(impacts_value, dict) else ()
        )
    }
    issue = str(summary.get("issue") or "accept")
    default_command = _COMMAND_BY_ISSUE.get(issue, CorrectionCommandType.ACCEPT)
    if default_command.value not in command_impacts:
        default_command = CorrectionCommandType.ACCEPT
    impact = command_impacts[default_command.value]
    confidence_value = summary.get("confidence")
    confidence = (
        float(confidence_value)
        if isinstance(confidence_value, (int, float))
        and not isinstance(confidence_value, bool)
        and math.isfinite(float(confidence_value))
        else None
    )
    probabilities_value = summary.get("probabilities")
    probabilities = {
        str(name): float(value)
        for name, value in (
            probabilities_value.items()
            if isinstance(probabilities_value, dict)
            else ()
        )
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    }
    reasons_value = summary.get("reasons")
    reasons = (
        [str(value) for value in reasons_value if isinstance(value, str)]
        if isinstance(reasons_value, list)
        else []
    )
    start_frame = summary.get("evidenceStartFrameIndex")
    end_frame = summary.get("evidenceEndFrameIndex")
    return ReviewItemDetail(
        id=item.public_id or f"{item.kind}-{item.timestamp_us}",
        target_type=review_entity_type,
        kind=item.kind,
        timestamp_us=item.timestamp_us,
        end_us=item.end_us,
        confidence=confidence,
        issue=issue,
        provenance=str(summary.get("provenance") or "unavailable"),
        probabilities=probabilities,
        reasons=reasons,
        evidence_ids=list(item.evidence_ids),
        evidence_start_timestamp_us=int(
            summary.get("evidenceStartTimestampUs") or item.timestamp_us
        ),
        evidence_end_timestamp_us=int(
            summary.get("evidenceEndTimestampUs")
            or item.end_us
            or item.timestamp_us
        ),
        evidence_start_frame_index=(
            int(start_frame) if isinstance(start_frame, int) else None
        ),
        evidence_end_frame_index=(
            int(end_frame) if isinstance(end_frame, int) else None
        ),
        invalidated_sections=impact.invalidated_sections,
        invalidated_stats=impact.invalidated_stats,
        summary=summary,
        command_targets=command_targets,
        command_impacts=command_impacts,
        review_entity_type=review_entity_type,
        review_entity_id=item.public_id or f"{item.kind}-{item.timestamp_us}",
        review_status=review_status,
    )


def _review_key(item: ReviewItemDetail) -> tuple[int, str]:
    return (item.timestamp_us, item.public_id)


@router.get(
    "/matches/{match_id}/review-items",
    response_model=ReviewItemPage,
    operation_id="listReviewItems",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def list_review_items(
    match_id: str,
    request: Request,
    revision: int = Query(ge=1),
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> ReviewItemPage:
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        report = _selected_report(session, match, revision)
        binding = {
            "kind": "reviewItems",
            "matchId": match.public_id,
            "reportRevision": report.revision,
        }
        decoded = _bound_cursor(request, cursor, binding, 2)
        after = (
            (_cursor_int(decoded[0]), _cursor_text(decoded[1]))
            if decoded is not None
            else None
        )
        error_state = _bounded_canonical_source(
            session,
            match,
            report,
            source_type="error_candidate",
            start_us=None,
            end_us=None,
            after=after,
            limit=limit,
            pending_only=True,
        )
        shot_state = _bounded_canonical_source(
            session,
            match,
            report,
            source_type="shot",
            start_us=None,
            end_us=None,
            after=after,
            limit=limit,
            pending_only=True,
        )
        rally_state = _bounded_canonical_source(
            session,
            match,
            report,
            source_type="rally",
            start_us=None,
            end_us=None,
            after=after,
            limit=limit,
            pending_only=True,
        )
        ordered = sorted(
            [
                *(
                    _review_item_detail(row, error_state)
                    for row in error_state.errors
                    if row.get("review_status") == "pending"
                ),
                *(
                    _timeline_review_detail(
                        _shot_timeline_item(row), "shot", "pending"
                    )
                    for row in shot_state.shots
                    if row.get("review_status") == "pending"
                ),
                *(
                    _timeline_review_detail(
                        _rally_timeline_item(row), "rally", "pending"
                    )
                    for row in rally_state.rallies
                    if row.get("review_status") == "pending"
                ),
            ],
            key=_review_key,
        )
        page = [
            item
            for item in ordered
            if after is None or _review_key(item) > after
        ][: limit + 1]
        has_more = len(page) > limit
        items = page[:limit]
        return ReviewItemPage(
            items=items,
            next_cursor=(
                encode_api_cursor(
                    request.app.state.cursor_secret,
                    binding,
                    _review_key(items[-1]),
                )
                if has_more and items
                else None
            ),
            report_revision=report.revision,
        )


def _evidence_timeline_item(
    state: CanonicalState, evidence_id: str
) -> TimelineItem | None:
    for row in state.shots:
        if evidence_id == row["prediction_id"] or evidence_id in row["source_evidence_ids"]:
            return TimelineItem(
                kind="shot",
                id=str(row["prediction_id"]),
                timestamp_us=int(row["source_timestamp_us"]),
                evidence_ids=[str(value) for value in row["source_evidence_ids"]],
                summary={
                    "shotKind": row["shot_type"],
                    "hitter": row["hitter"],
                    "outcome": row["outcome"],
                    "sourceTimestampUs": row["source_timestamp_us"],
                },
            )
    for row in state.rallies:
        if evidence_id == row["prediction_id"] or evidence_id in row["source_evidence_ids"]:
            timestamp = row.get("start_timestamp_us")
            if timestamp is None:
                continue
            return TimelineItem(
                kind="rally",
                id=str(row["prediction_id"]),
                timestamp_us=int(timestamp),
                end_us=(
                    int(row["end_timestamp_us"])
                    if row.get("end_timestamp_us") is not None
                    else None
                ),
                evidence_ids=[str(value) for value in row["source_evidence_ids"]],
                summary={"ordinal": row["ordinal"]},
            )
    for row in state.errors:
        if evidence_id == row["prediction_id"] or evidence_id in row["source_evidence_ids"]:
            timestamp = row.get("source_timestamp_us")
            if timestamp is None:
                continue
            detail = _review_item_detail(row, state)
            return TimelineItem(
                kind="error",
                id=str(row["prediction_id"]),
                timestamp_us=int(timestamp),
                end_us=detail.end_us,
                evidence_ids=[str(value) for value in row["source_evidence_ids"]],
                summary={
                    **detail.summary,
                    "issue": detail.issue,
                    "confidence": detail.confidence,
                    "probabilities": detail.probabilities,
                    "reasons": detail.reasons,
                    "provenance": detail.provenance,
                },
            )
    return None


@router.get(
    "/matches/{match_id}/evidence/{evidence_id}",
    response_model=TimelineItem,
    operation_id="getEvidenceEvent",
    responses={404: {"model": ErrorResponse}},
)
def get_evidence_event(
    match_id: str,
    evidence_id: str,
    request: Request,
    revision: int = Query(ge=1),
) -> TimelineItem:
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        report = _selected_report(session, match, revision)
        item = _evidence_timeline_item(
            canonical_state_for_report(session, match, report), evidence_id
        )
        if item is None:
            raise ApiError("evidence_not_found", "public evidence was not found", 404)
        return item



@router.get(
    "/matches/{match_id}/rallies",
    response_model=RallyPage,
    operation_id="listRallies",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def list_rallies(
    match_id: str,
    request: Request,
    start_us: int = Query(alias="startUs"),
    end_us: int = Query(alias="endUs"),
    cursor: str | None = None,
    limit: int = Query(default=500, ge=1, le=_MAX_PAGE),
) -> RallyPage:
    start_us, end_us = _range(start_us, end_us)
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        report = _current_report(session, match)
        binding = _canonical_binding(
            "rallies", match, report, start_us, end_us
        )
        decoded = _bound_cursor(request, cursor, binding, 2)
        after = (
            (_cursor_int(decoded[0]), _cursor_text(decoded[1]))
            if decoded is not None
            else None
        )
        state = _bounded_canonical_source(
            session,
            match,
            report,
            source_type="rally",
            start_us=start_us,
            end_us=end_us,
            after=after,
            limit=limit,
        )
        rows = sorted(
            (
                row
                for row in state.rallies
                if row.get("timing_available")
                and row.get("start_timestamp_us") is not None
                and row.get("end_timestamp_us") is not None
                and int(row["start_timestamp_us"]) < end_us
                and int(row["end_timestamp_us"]) > start_us
                and (
                    after is None
                    or _canonical_rally_key(row) > after
                )
            ),
            key=_canonical_rally_key,
        )[: limit + 1]
        has_more = len(rows) > limit
        rows = rows[:limit]
        return RallyPage(
            items=[
                _canonical_rally_detail(row, report.prediction_revision)
                for row in rows
            ],
            next_cursor=(
                encode_api_cursor(
                    request.app.state.cursor_secret,
                    binding,
                    _canonical_rally_key(rows[-1]),
                )
                if has_more and rows
                else None
            ),
            prediction_revision=report.prediction_revision,
        )


def _impact_detail(command: CorrectionCommandType) -> CorrectionImpactDetail:
    return CorrectionImpactDetail(
        invalidated_sections=sorted(INVALIDATIONS[command]),
        invalidated_stats=list(_INVALIDATED_STATS[command]),
    )


def _shot_timeline_item(row: dict[str, object]) -> TimelineItem:
    timestamp_us = int(row["source_timestamp_us"])
    frame_index = int(row["frame_index"])
    target = _correction_target(
        "shot",
        str(row["prediction_id"]),
        timestamp_us,
        [str(value) for value in row["source_evidence_ids"]],
        timestamp_us,
        timestamp_us,
        frame_index,
        frame_index,
    )
    commands = (
        CorrectionCommandType.ACCEPT,
        CorrectionCommandType.REJECT,
        CorrectionCommandType.CHANGE_HITTER,
        CorrectionCommandType.CHANGE_SHOT_TYPE,
        CorrectionCommandType.ADJUST_CONTACT_TIME,
        CorrectionCommandType.CHANGE_OUTCOME,
        CorrectionCommandType.BALL_CONTROL_POINT,
    )
    payload = row.get("classification_payload")
    classification = payload if isinstance(payload, dict) else {}
    confidence_value = classification.get("confidence")
    confidence = (
        float(confidence_value)
        if isinstance(confidence_value, (int, float))
        and not isinstance(confidence_value, bool)
        and math.isfinite(float(confidence_value))
        else None
    )
    return TimelineItem(
        kind="shot",
        id=str(row["prediction_id"]),
        timestamp_us=timestamp_us,
        evidence_ids=[str(value) for value in row["source_evidence_ids"]],
        summary={
            "shotKind": row["shot_type"],
            "hitter": row["hitter"],
            "outcome": row["outcome"],
            "confidence": confidence,
            "reviewRequired": bool(row.get("review_required")),
            "issue": (
                "hitter" if row.get("hitter") is None else "shot_type"
            ),
            "probabilities": classification.get("probabilities", {}),
            "reasons": classification.get("reasons", []),
            "reviewStatus": row.get("review_status", "not_required"),
            "reviewEntityType": "shot",
            "reviewEntityId": row["prediction_id"],
            "provenance": row.get("evidence_provenance", "unavailable"),
            "evidenceStartTimestampUs": timestamp_us,
            "evidenceEndTimestampUs": timestamp_us,
            "evidenceStartFrameIndex": frame_index,
            "evidenceEndFrameIndex": frame_index,
            "commandTargets": {
                command.value: target.model_dump(by_alias=True)
                for command in commands
            },
            "commandImpacts": {
                command.value: _impact_detail(command).model_dump(by_alias=True)
                for command in commands
            },
        },
    )


def _rally_timeline_item(row: dict[str, object]) -> TimelineItem:
    start_us = int(row["start_timestamp_us"])
    end_us = int(row["end_timestamp_us"])
    target = _correction_target(
        "rally",
        str(row["prediction_id"]),
        start_us,
        [str(value) for value in row["source_evidence_ids"]],
        start_us,
        end_us,
        int(row["start_frame"]),
        int(row["end_frame"]),
    )
    commands = (
        CorrectionCommandType.ACCEPT,
        CorrectionCommandType.REJECT,
        CorrectionCommandType.SPLIT_RALLY,
        CorrectionCommandType.MERGE_RALLIES,
    )
    return TimelineItem(
        kind="rally",
        id=str(row["prediction_id"]),
        timestamp_us=start_us,
        end_us=end_us,
        evidence_ids=[str(value) for value in row["source_evidence_ids"]],
        summary={
            "ordinal": row["ordinal"],
            "reviewRequired": bool(row.get("review_required")),
            "issue": "rally_boundary",
            "reasons": list(row.get("review_reasons", [])),
            "reviewStatus": row.get("review_status", "not_required"),
            "reviewEntityType": "rally",
            "reviewEntityId": row["prediction_id"],
            "provenance": row.get("evidence_provenance", "unavailable"),
            "evidenceStartTimestampUs": start_us,
            "evidenceEndTimestampUs": end_us,
            "evidenceStartFrameIndex": row["start_frame"],
            "evidenceEndFrameIndex": row["end_frame"],
            "commandTargets": {
                command.value: target.model_dump(by_alias=True)
                for command in commands
            },
            "commandImpacts": {
                command.value: _impact_detail(command).model_dump(by_alias=True)
                for command in commands
            },
        },
    )


def _timeline_key(item: TimelineItem) -> tuple[int, str, str]:
    return (item.timestamp_us, item.kind, item.public_id or "")


def _bounded_timeline_source(
    items: Iterator[TimelineItem],
    after: tuple[int, str, str] | None,
    limit: int,
) -> list[TimelineItem]:
    ordered = sorted(items, key=_timeline_key)
    return list(
        islice(
            (
                item
                for item in ordered
                if after is None or _timeline_key(item) > after
            ),
            limit + 1,
        )
    )

def _timeline_source_after(
    after: tuple[int, str, str] | None, source_kind: str
) -> tuple[int, str] | None:
    if after is None:
        return None
    timestamp_us, cursor_kind, public_id = after
    if source_kind < cursor_kind:
        return timestamp_us, "\U0010ffff"
    if source_kind > cursor_kind:
        return timestamp_us, ""
    return timestamp_us, public_id


@router.get(
    "/matches/{match_id}/timeline",
    response_model=TimelinePage,
    operation_id="getTimeline",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def get_timeline(
    match_id: str,
    request: Request,
    start_us: int = Query(alias="startUs"),
    end_us: int = Query(alias="endUs"),
    revision: int | None = Query(default=None, ge=1),
    cursor: str | None = None,
    limit: int = Query(default=500, ge=1, le=_MAX_PAGE),
    kinds: str | None = None,
) -> TimelinePage:
    start_us, end_us = _range(start_us, end_us)
    allowed = {"shot", "rally", "error", "contact", "observationWindow"}
    selected = (
        {item for item in kinds.split(",") if item}
        if kinds is not None
        else allowed
    )
    if not selected or not selected <= allowed:
        raise ApiError("invalid_kinds", "timeline kinds filter is invalid", 422)
    database: Database = request.app.state.database
    with database.session() as session:
        match = _api_match(session, match_id)
        report = _selected_report(session, match, revision)
        binding = _canonical_binding(
            "timeline",
            match,
            report,
            start_us,
            end_us,
            extra={"kinds": sorted(selected)},
        )
        decoded = _bound_cursor(request, cursor, binding, 3)
        after: tuple[int, str, str] | None = None
        if decoded is not None:
            cursor_kind = _cursor_text(decoded[1], maximum=40)
            if cursor_kind not in allowed:
                raise _invalid_cursor()
            after = (
                _cursor_int(decoded[0]),
                cursor_kind,
                _cursor_text(decoded[2], allow_empty=True),
            )
        sources: list[list[TimelineItem]] = []
        if "shot" in selected:
            shot_state = _bounded_canonical_source(
                session,
                match,
                report,
                source_type="shot",
                start_us=start_us,
                end_us=end_us,
                after=_timeline_source_after(after, "shot"),
                limit=limit,
            )
            sources.append(
                _bounded_timeline_source(
                    (
                        _shot_timeline_item(row)
                        for row in shot_state.shots
                        if start_us
                        <= int(row["source_timestamp_us"])
                        < end_us
                    ),
                    after,
                    limit,
                )
            )
        if "contact" in selected:
            contact_state = _bounded_canonical_source(
                session,
                match,
                report,
                source_type="shot",
                start_us=start_us,
                end_us=end_us,
                after=_timeline_source_after(after, "contact"),
                limit=limit,
                contact_only=True,
            )
            sources.append(
                _bounded_timeline_source(
                    (
                        TimelineItem(
                            kind="contact",
                            id=str(row["prediction_id"]),
                            timestamp_us=int(row["source_timestamp_us"]),
                            evidence_ids=[
                                str(value)
                                for value in row["source_evidence_ids"]
                            ],
                            summary={
                                "xM": row["contact_x_m"],
                                "yM": row["contact_y_m"],
                            },
                        )
                        for row in contact_state.shots
                        if start_us
                        <= int(row["source_timestamp_us"])
                        < end_us
                        and row.get("contact_x_m") is not None
                        and row.get("contact_y_m") is not None
                    ),
                    after,
                    limit,
                )
            )
        if "rally" in selected:
            rally_state = _bounded_canonical_source(
                session,
                match,
                report,
                source_type="rally",
                start_us=start_us,
                end_us=end_us,
                after=_timeline_source_after(after, "rally"),
                limit=limit,
            )
            sources.append(
                _bounded_timeline_source(
                    (
                        _rally_timeline_item(row)
                        for row in rally_state.rallies
                        if row.get("timing_available")
                        and row.get("start_timestamp_us") is not None
                        and row.get("end_timestamp_us") is not None
                        and int(row["start_timestamp_us"]) < end_us
                        and int(row["end_timestamp_us"]) > start_us
                    ),
                    after,
                    limit,
                )
            )
        if "error" in selected:
            error_state = _bounded_canonical_source(
                session,
                match,
                report,
                source_type="error_candidate",
                start_us=start_us,
                end_us=end_us,
                after=_timeline_source_after(after, "error"),
                limit=limit,
            )
            sources.append(
                _bounded_timeline_source(
                    (
                        _error_timeline_item(row, error_state)
                        for row in error_state.errors
                        if row.get("source_timestamp_us") is not None
                        and start_us
                        <= int(row["source_timestamp_us"])
                        < end_us
                    ),
                    after,
                    limit,
                )
            )
        if "observationWindow" in selected:
            safe_match_id = quote(match.public_id, safe="")
            sources.append(
                _bounded_timeline_source(
                    iter(
                        (
                            TimelineItem(
                                kind="observationWindow",
                                timestamp_us=start_us,
                                end_us=end_us,
                                observation_links={
                                    "players": (
                                        f"/api/v1/matches/{safe_match_id}/"
                                        "observations/players"
                                        f"?startUs={start_us}&endUs={end_us}"
                                        f"&revision={report.revision}"
                                    ),
                                    "ball": (
                                        f"/api/v1/matches/{safe_match_id}/"
                                        "observations/ball"
                                        f"?startUs={start_us}&endUs={end_us}"
                                        f"&revision={report.revision}"
                                    ),
                                },
                            ),
                        )
                    ),
                    after,
                    limit,
                )
            )
        merged = list(
            islice(
                heapq.merge(*sources, key=_timeline_key),
                limit + 1,
            )
        )
        has_more = len(merged) > limit
        page_items = merged[:limit]
        return TimelinePage(
            items=page_items,
            next_cursor=(
                encode_api_cursor(
                    request.app.state.cursor_secret,
                    binding,
                    _timeline_key(page_items[-1]),
                )
                if has_more and page_items
                else None
            ),
            prediction_revision=report.prediction_revision,
        )
