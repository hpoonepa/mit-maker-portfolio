from __future__ import annotations
import base64
import binascii
import hashlib
import hmac
import json
import math
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from squashvision.models import (
    AssetKind,
    BallInputMode,
    JobStatus,
    ModelAssetState,
    ProcessingProfile,
    Stage,
    StageStatus,
)
from squashvision.storage import StoredPath
from squashvision.taxonomy import ShotKind, ShotOutcomeKind


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class VideoProbe(ApiModel):
    format_names: tuple[str, ...]
    duration: float = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    codec: str | None
    time_base: str | None
    average_frame_rate: str | None
    real_frame_rate: str | None
    rotation: int
    has_video: bool
    has_audio: bool
    variable_frame_rate: bool


class IngestedMedia(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    stored_path: StoredPath
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    suffix: str
    probe: VideoProbe


class TimestampPair(ApiModel):
    source_seconds: float = Field(ge=0)
    proxy_seconds: float = Field(ge=0)


class TimestampMap(ApiModel):
    version: int = 1
    samples: list[TimestampPair] = Field(min_length=1)

    @model_validator(mode="after")
    def require_ordered_samples(self) -> TimestampMap:
        for previous, current in zip(self.samples, self.samples[1:], strict=False):
            if (
                current.source_seconds < previous.source_seconds
                or current.proxy_seconds < previous.proxy_seconds
            ):
                raise ValueError("timestamp samples must be ordered")
        return self


class ErrorResponse(ApiModel):
    code: str
    message: str
    details: dict[str, object] | None
    request_id: str


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def encode_api_cursor(
    secret: bytes,
    binding: dict[str, object],
    key: tuple[object, ...],
) -> str:
    payload = json.dumps(
        {"binding": binding, "key": list(key)},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    encoded_signature = (
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    )
    return f"{encoded_payload}.{encoded_signature}"


def decode_api_cursor(
    secret: bytes,
    cursor: str | None,
    binding: dict[str, object],
) -> tuple[object, ...] | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 8192:
            raise ValueError
        encoded_payload, encoded_signature = cursor.split(".")
        payload = base64.b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4),
            altchars=b"-_",
            validate=True,
        )
        signature = base64.b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4),
            altchars=b"-_",
            validate=True,
        )
        if len(signature) != hashlib.sha256().digest_size or not hmac.compare_digest(
            signature, hmac.new(secret, payload, hashlib.sha256).digest()
        ):
            raise ValueError
        decoded = json.loads(payload.decode("ascii"))
        if (
            not isinstance(decoded, dict)
            or set(decoded) != {"binding", "key"}
            or decoded["binding"] != binding
            or not isinstance(decoded["key"], list)
        ):
            raise ValueError
        return tuple(decoded["key"])
    except (
        ValueError,
        TypeError,
        UnicodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as error:
        raise ApiError(
            "invalid_cursor",
            "pagination cursor is invalid or no longer applies",
            422,
        ) from error


class ModelAssetDetail(ApiModel):
    name: str
    filename: str
    requested_revision: str
    source_label: str = Field(min_length=1, max_length=200)
    resolved_revision: str | None
    byte_size: int | None = Field(ge=0)
    sha256: str | None
    declared_license: str
    downloaded_at: datetime | None
    compatibility_version: int = Field(ge=0)
    required: bool
    state: ModelAssetState
    error_code: str | None

class PreparationState(StrEnum):
    PREPARED = "prepared"
    UNPREPARED = "unprepared"


class MatchMetadata(ApiModel):
    player_one: str | None = None
    player_two: str | None = None
    played_on: date | None = None
    score: str | None = None


class MediaAssetDetail(ApiModel):
    public_id: str = Field(alias="id")
    kind: AssetKind
    byte_size: int | None = Field(default=None, ge=0)
    duration_us: int | None = Field(default=None, ge=0)
    timestamp_index_available: bool = False


class FrameMapItem(ApiModel):
    proxy_timestamp_us: int = Field(ge=0)
    source_timestamp_us: int = Field(ge=0)
    source_frame_index: int = Field(ge=0)


class FrameMapDetail(ApiModel):
    start_us: int = Field(ge=0)
    end_us: int = Field(ge=0)
    items: list[FrameMapItem]


class TrackedPlayerStats(ApiModel):
    player_id: Literal["A", "B"]
    distance_m: float | None
    tracked_seconds: float
    coverage: float
    observed_samples: int
    used_samples: int
    excluded_samples: int
    contact_count: int
    identity_verified: Literal[False] = False


class TrackedContactStats(ApiModel):
    id: str
    timestamp_us: int
    proxy_timestamp_us: int | None
    source_frame_index: int | None
    hitter: Literal["A", "B"] | None
    hitter_confidence: float
    confidence: float
    position: tuple[float, float] | None
    position_method: Literal["hitter_feet_at_contact"] = "hitter_feet_at_contact"
    reason: str | None
    review_required: bool


class ProjectedBallSpeedStats(ApiModel):
    median_mps: float | None
    p90_mps: float | None
    sample_count: int
    excluded_samples: int
    tracked_seconds: float
    coverage: float
    method: str
    reason: str | None


class TrackingStatsDetail(ApiModel):
    report_revision: int
    prediction_revision: int
    calibration_revision: int | None
    calibration_available: bool
    calibration_reason: str | None
    start_us: int
    end_us: int
    players: list[TrackedPlayerStats]
    contacts: list[TrackedContactStats]
    ball_speed: ProjectedBallSpeedStats
    coordinate_system: str
    limitations: list[str]


class PlaybackPlayerBaseline(ApiModel):
    player_id: Literal["A", "B"]
    baseline_distance_m: float | None
    baseline_tracked_seconds: float


class PlaybackPlayerSample(ApiModel):
    player_id: Literal["A", "B"]
    timestamp_us: int
    proxy_timestamp_us: int | None
    proxy_end_timestamp_us: int | None
    source_frame_index: int | None
    position: tuple[float, float] | None
    cumulative_distance_m: float | None
    tracked_seconds: float
    position_reason: str | None


class PlaybackBallSpeed(ApiModel):
    timestamp_us: int
    interval_start_us: int
    proxy_timestamp_us: int | None
    proxy_end_timestamp_us: int | None
    source_frame_index: int
    speed_mps: float


class PlaybackContact(ApiModel):
    id: str
    kind: Literal["racket", "floor", "front_wall", "unknown"]
    timestamp_us: int
    proxy_timestamp_us: int | None
    source_frame_index: int | None
    confidence: float
    hitter: Literal["A", "B"] | None
    hitter_confidence: float
    shot_hitter: Literal["A", "B"] | None = None
    shot_contact_id: str | None = None
    shot_hitter_confidence: float = Field(default=0, ge=0, le=1)
    ball_image_position: tuple[float, float] | None
    image_width: int | None
    image_height: int | None
    player_position: tuple[float, float] | None
    floor_position: tuple[float, float] | None
    wall_position: tuple[float, float] | None = None
    wall_image_fraction: float | None = Field(default=None, ge=0, le=1)
    timing_uncertainty_us: int = Field(default=0, ge=0)
    position_reason: str | None
    provenance: str
    review_required: bool


class TrackingTimelineDetail(ApiModel):
    report_revision: int
    prediction_revision: int
    calibration_revision: int | None
    calibration_available: bool
    calibration_reason: str | None
    start_us: int
    end_us: int
    duration_us: int
    players: list[PlaybackPlayerBaseline]
    player_samples: list[PlaybackPlayerSample]
    ball_speeds: list[PlaybackBallSpeed]
    ball_speed_method: Literal["court_scaled_image_speed"]
    contacts: list[PlaybackContact]
    landing_count: int
    landing_reason: str | None
    limitations: list[str]


class ProcessingSummary(ApiModel):
    state: str
    job_id: str | None = None
    profile: ProcessingProfile | None = None
    stage: Stage | None = None
    updated_at: datetime | None = None


class ReportSummary(ApiModel):
    revision: int = Field(ge=1)
    prediction_revision: int = Field(ge=1)
    calibration_revision: int | None = None
    created_at: datetime
    section_hashes: dict[str, str]


class MatchQualitySummary(ApiModel):
    availability: str
    warnings: list[str]


class MatchDetail(ApiModel):
    public_id: str = Field(alias="id")
    title: str
    preparation_state: PreparationState
    metadata: MatchMetadata
    assets: list[MediaAssetDetail]
    version: int = Field(ge=1)
    updated_at: datetime
    latest_job: JobDetail | None = None
    latest_report: ReportSummary | None = None
    calibration_revision: int | None = None
    model_quality: list[ModelAssetDetail] = Field(default_factory=list)
    quality: MatchQualitySummary


class MatchSummary(ApiModel):
    public_id: str = Field(alias="id")
    title: str
    metadata: MatchMetadata
    preparation_state: PreparationState
    updated_at: datetime
    version: int = Field(ge=1)
    processing: ProcessingSummary
    latest_report: ReportSummary | None
    quality: MatchQualitySummary


class MatchListPage(ApiModel):
    items: list[MatchSummary]
    next_cursor: str | None


class MatchUpdateRequest(ApiModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    player_one: str | None = Field(default=None, max_length=200)
    player_two: str | None = Field(default=None, max_length=200)
    played_on: date | None = None
    score: str | None = Field(default=None, max_length=200)


class JobStartRequest(ApiModel):
    profile: ProcessingProfile
    ball_input_mode: BallInputMode = BallInputMode.ORIGINAL

    @model_validator(mode="after")
    def require_dense_player_evidence_for_dark_ball(self) -> JobStartRequest:
        if self.ball_input_mode is BallInputMode.INVERTED and self.profile is ProcessingProfile.FAST:
            raise ValueError("dark-ball input requires the balanced or maximum profile for per-frame player evidence")
        return self


class JobProgress(ApiModel):
    completed_chunks: int = Field(ge=0)
    planned_chunks: int = Field(gt=0)
    fraction: float = Field(ge=0, le=1)


class JobDetail(ApiModel):
    public_id: str = Field(alias="id")
    match_id: str
    profile: ProcessingProfile
    ball_input_mode: BallInputMode = BallInputMode.ORIGINAL
    state: JobStatus
    stage: Stage | None
    stage_state: StageStatus | None
    requested_state: JobStatus | None
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    heartbeat_at: datetime | None
    progress: JobProgress | None
    current_range_start_us: int | None = Field(ge=0)
    current_range_end_us: int | None = Field(ge=1)
    failure_code: str | None = Field(pattern=r"[a-z][a-z0-9_]{0,99}")

    @model_validator(mode="after")
    def validate_current_range(self) -> JobDetail:
        start, end = self.current_range_start_us, self.current_range_end_us
        if (start is None) != (end is None):
            raise ValueError("current range endpoints must both be present or null")
        if start is not None and end is not None and start >= end:
            raise ValueError("current range requires start before end")
        return self


class JobEvent(ApiModel):
    event_version: int = 1
    job: JobDetail


class CalibrationSize(ApiModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CalibrationImagePoint(ApiModel):
    x: float
    y: float


class CalibrationCourtPoint(ApiModel):
    x_m: float = Field(ge=0, le=6.40)
    y_m: float = Field(ge=0, le=9.75)


class CalibrationKeypoint(ApiModel):
    label: str = Field(min_length=1, max_length=100)
    image: CalibrationImagePoint
    court: CalibrationCourtPoint


class CalibrationCapabilitiesDetail(ApiModel):
    image_space: bool
    floor_position: bool
    movement_distance: bool
    speed: bool


class CalibrationResultDetail(ApiModel):
    calibrated: bool
    image_to_court: tuple[tuple[float, float, float], ...] | None
    court_to_image: tuple[tuple[float, float, float], ...] | None
    residuals_px: tuple[float, ...]
    rms_error_px: float | None
    max_error_px: float | None
    inlier_mask: tuple[bool, ...]
    condition_number: float | None
    parameter_covariance: tuple[tuple[float, ...], ...] | None
    confidence: float = Field(ge=0, le=1)
    capabilities: CalibrationCapabilitiesDetail
    warnings: tuple[str, ...]


class CalibrationDetail(ApiModel):
    revision: int = Field(ge=1)
    proxy_id: str
    frame_size: CalibrationSize | None
    keypoints: tuple[CalibrationKeypoint, ...]
    result: CalibrationResultDetail


class CalibrationSaveRequest(ApiModel):
    expected_revision: int = Field(ge=0)
    frame_size: CalibrationSize
    keypoints: tuple[CalibrationKeypoint, ...] = Field(min_length=4)


class CalibrationProposalRequest(ApiModel):
    timestamp_seconds: float


class PlayerRoiPoint(ApiModel):
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)


class PlayerRoiDetail(ApiModel):
    revision: int = Field(ge=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_size: CalibrationSize
    points: tuple[PlayerRoiPoint, ...] | None = Field(default=None, min_length=3, max_length=16)
    purpose: Literal["player_detection_only"] = "player_detection_only"


class PlayerRoiSaveRequest(ApiModel):
    expected_revision: int = Field(ge=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_size: CalibrationSize
    points: tuple[PlayerRoiPoint, ...] | None = Field(min_length=3, max_length=16)


class CalibrationProposalDetail(ApiModel):
    keypoints: tuple[CalibrationKeypoint, ...]
    confidence: float = Field(ge=0, le=1)
    visible_surfaces: tuple[str, ...]
    warnings: tuple[str, ...]
    line_count: int = Field(ge=0)
    intersection_count: int = Field(ge=0)


class CorrectionCommandType(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    CHANGE_HITTER = "change_hitter"
    CHANGE_SHOT_TYPE = "change_shot_type"
    ADJUST_CONTACT_TIME = "adjust_contact_time"
    CHANGE_OUTCOME = "change_outcome"
    BALL_CONTROL_POINT = "ball_control_point"
    SPLIT_RALLY = "split_rally"
    MERGE_RALLIES = "merge_rallies"


class CorrectionCommand(ApiModel):
    command_type: CorrectionCommandType
    match_id: str = Field(min_length=1)
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    expected_report_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    payload: dict[str, object]
    source_timestamp_us: int | None = Field(default=None, ge=0, strict=True)
    source_evidence_ids: list[str] | None = None
    review_entity_type: Literal["error_candidate", "shot", "rally"] | None = None
    review_entity_id: str | None = None

    @model_validator(mode="after")
    def validate_typed_payload(self) -> CorrectionCommand:
        command = self.command_type
        payload = self.payload
        if (self.review_entity_type is None) != (self.review_entity_id is None):
            raise ValueError("review entity type and ID must be supplied together")
        if command in {CorrectionCommandType.ACCEPT, CorrectionCommandType.REJECT}:
            if self.target_type not in {"error_candidate", "shot", "rally"}:
                raise ValueError(f"{command.value} requires a reviewable target")
        else:
            expected_target = (
                "rally"
                if command in {
                    CorrectionCommandType.SPLIT_RALLY,
                    CorrectionCommandType.MERGE_RALLIES,
                }
                else "shot"
            )
            if self.target_type != expected_target:
                raise ValueError(f"{command.value} requires target_type={expected_target}")
        if command in {CorrectionCommandType.ACCEPT, CorrectionCommandType.REJECT}:
            if payload:
                raise ValueError(f"{command.value} does not accept a payload")
        elif command is CorrectionCommandType.CHANGE_HITTER:
            if set(payload) != {"hitter"} or payload["hitter"] not in {"near", "far"}:
                raise ValueError("change_hitter requires a near or far hitter")
        elif command is CorrectionCommandType.CHANGE_SHOT_TYPE:
            if (
                set(payload) != {"shot_type"}
                or payload["shot_type"] not in {item.value for item in ShotKind}
            ):
                raise ValueError("change_shot_type requires a canonical shot_type")
        elif command is CorrectionCommandType.ADJUST_CONTACT_TIME:
            value = payload.get("source_timestamp_us")
            if set(payload) != {"source_timestamp_us"} or type(value) is not int or value < 0:
                raise ValueError("adjust_contact_time requires a nonnegative integer timestamp")
        elif command is CorrectionCommandType.CHANGE_OUTCOME:
            if (
                set(payload) != {"outcome"}
                or payload["outcome"]
                not in {item.value for item in ShotOutcomeKind}
            ):
                raise ValueError("change_outcome requires a canonical outcome")
        elif command is CorrectionCommandType.BALL_CONTROL_POINT:
            x_m, y_m = payload.get("x_m"), payload.get("y_m")
            if (
                set(payload) != {"x_m", "y_m"}
                or isinstance(x_m, bool)
                or isinstance(y_m, bool)
                or not isinstance(x_m, (int, float))
                or not isinstance(y_m, (int, float))
                or not math.isfinite(float(x_m))
                or not math.isfinite(float(y_m))
                or not 0 <= float(x_m) <= 6.4
                or not 0 <= float(y_m) <= 9.75
            ):
                raise ValueError("ball_control_point must be inside the regulation court")
        elif command is CorrectionCommandType.SPLIT_RALLY:
            value = payload.get("split_timestamp_us")
            if set(payload) != {"split_timestamp_us"} or type(value) is not int or value <= 0:
                raise ValueError("split_rally requires a positive split timestamp")
        elif command is CorrectionCommandType.MERGE_RALLIES:
            other = payload.get("other_target_id")
            if (
                set(payload) != {"other_target_id"}
                or not isinstance(other, str)
                or not other
                or other == self.target_id
            ):
                raise ValueError("merge_rallies requires a different rally target")
        return self


class ReportSection(ApiModel):
    schema_version: int = 1
    payload: dict[str, object]
    evidence_ids: list[str]
    hash: str
    dependency_hash: str


class MatchReport(ApiModel):
    match_id: str
    revision: int = Field(ge=1)
    prediction_revision: int = Field(ge=1)
    calibration_revision: int | None
    sections: dict[str, ReportSection]


class ExportSelection(ApiModel):
    formats: tuple[Literal["html", "json", "csv"], ...] = Field(
        default=("html", "json", "csv"),
        min_length=1,
        max_length=3,
    )
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=100)
    evidence_duration_seconds: float = Field(default=6.0, ge=1.0, le=30.0)
    include_original: bool = False

    @model_validator(mode="after")
    def validate_selection(self) -> ExportSelection:
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("export formats must not contain duplicates")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence ids must not contain duplicates")
        for evidence_id in self.evidence_ids:
            if (
                not 1 <= len(evidence_id) <= 200
                or not evidence_id[0].isalnum()
                or any(
                    not (character.isascii() and (
                        character.isalnum() or character in "._:-"
                    ))
                    for character in evidence_id
                )
            ):
                raise ValueError("evidence ids must be bounded safe identifiers")
        if (
            len(self.evidence_ids) * self.evidence_duration_seconds
            > 600.0
        ):
            raise ValueError("total evidence clip duration exceeds 600 seconds")
        return self


class ExportCreateRequest(ApiModel):
    revision: int = Field(ge=1)
    selection: ExportSelection


class ExportDetail(ApiModel):
    public_id: str = Field(alias="id")
    match_id: str
    revision: int = Field(ge=1)
    state: Literal["completed"]
    selection: ExportSelection
    relative_path: str
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceCandidateDetail(ApiModel):
    candidate_id: str
    timestamp_us: int = Field(ge=0)
    evidence_start_timestamp_us: int = Field(ge=0)
    evidence_end_timestamp_us: int = Field(ge=0)
    evidence_start_frame_index: int | None = Field(default=None, ge=0)
    evidence_end_frame_index: int | None = Field(default=None, ge=0)
    evidence_ids: list[str]
    label: str


class CorrectionConflictDetail(ApiModel):
    correction_id: str
    reason: str
    candidate_ids: list[str]
    candidates: list[EvidenceCandidateDetail] = Field(default_factory=list)



class CorrectionConflictList(ApiModel):
    conflicts: list[CorrectionConflictDetail]


class ConflictResolution(ApiModel):
    resolution: str
    candidate_id: str | None = None
    expected_report_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_resolution(self) -> ConflictResolution:
        if self.resolution not in {"select", "reject"}:
            raise ValueError("resolution must be select or reject")
        if self.resolution == "select" and not self.candidate_id:
            raise ValueError("select requires candidate_id")
        if self.resolution == "reject" and self.candidate_id is not None:
            raise ValueError("reject cannot include candidate_id")
        return self


class ReportListPage(ApiModel):
    items: list[ReportSummary]
    next_cursor: str | None


class ArtifactSelection(ApiModel):
    job_id: str
    stage: Stage
    availability: str
    warnings: list[str]
    source_manifest_ids: list[str]
    model_manifest_ids: list[str]


class PoseKeypointDetail(ApiModel):
    x: float
    y: float
    confidence: float = Field(ge=0, le=1)


class BallCandidateDetail(ApiModel):
    x: float
    y: float
    probability: float = Field(ge=0, le=1)
    covariance: tuple[tuple[float, float], tuple[float, float]]


class PlayerObservationDetail(ApiModel):
    player_id: str
    timestamp_us: int = Field(ge=0)
    source_timestamp_us: int | None = Field(default=None, ge=0)
    source_frame_index: int | None = Field(default=None, ge=0)
    box: tuple[float, float, float, float]
    detection_confidence: float = Field(ge=0, le=1)
    feet: tuple[float, float]
    keypoints: list[PoseKeypointDetail] = Field(max_length=17)
    skeleton_edges: list[tuple[int, int]] = Field(max_length=20)
    feet_uncertainty_px: float = Field(ge=0)
    evidence: str
    evidence_start_timestamp_us: int = Field(ge=0)
    evidence_end_timestamp_us: int = Field(ge=0)
    evidence_start_frame_index: int = Field(ge=0)
    evidence_end_frame_index: int = Field(ge=0)
    association_confidence: float = Field(ge=0, le=1)
    ambiguous: bool
    ambiguity_reason: str | None
    floor: tuple[float, float] | None
    floor_uncertainty_m: float | None = Field(default=None, ge=0)
    calibration_revision: str | None
    calibration_provenance: str | None
    source_manifest_id: str
    model_manifest_id: str


class BallObservationDetail(ApiModel):
    timestamp_us: int = Field(ge=0)
    source_timestamp_us: int | None = Field(default=None, ge=0)
    source_frame_index: int | None = Field(default=None, ge=0)
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    x: float | None
    y: float | None
    probability: float = Field(ge=0, le=1)
    covariance: tuple[tuple[float, float], tuple[float, float]] | None
    candidates: list[BallCandidateDetail] = Field(max_length=5)
    visible: bool
    candidate_count: int = Field(ge=0)
    evidence: str
    evidence_start_timestamp_us: int = Field(ge=0)
    evidence_end_timestamp_us: int = Field(ge=0)
    evidence_start_frame_index: int = Field(ge=0)
    evidence_end_frame_index: int = Field(ge=0)
    ambiguous: bool
    ambiguity_reason: str | None
    segment_id: str | None
    source_manifest_id: str
    model_manifest_id: str
    device: str
    device_fallback: bool


class PlayerObservationPage(ApiModel):
    items: list[PlayerObservationDetail]
    next_cursor: str | None
    start_us: int
    end_us: int
    artifact: ArtifactSelection


class BallObservationPage(ApiModel):
    items: list[BallObservationDetail]
    next_cursor: str | None
    start_us: int
    end_us: int
    artifact: ArtifactSelection


class ShotDetail(ApiModel):
    public_id: str = Field(alias="id")
    timestamp_us: int = Field(ge=0)
    prediction_revision: int = Field(ge=1)
    rally_id: str | None
    hitter: str | None
    shot_kind: ShotKind
    is_volley: bool
    outcome: ShotOutcomeKind
    contact: tuple[float, float] | None
    speed_m_s: float | None
    speed_unavailable_reason: str | None
    source_evidence_ids: list[str]


class ShotPage(ApiModel):
    items: list[ShotDetail]
    next_cursor: str | None
    prediction_revision: int


class RallyDetail(ApiModel):
    public_id: str = Field(alias="id")
    ordinal: int = Field(ge=0)
    start_us: int | None = Field(default=None, ge=0)
    end_us: int | None = Field(default=None, ge=0)
    timing_available: bool
    prediction_revision: int = Field(ge=1)
    source_evidence_ids: list[str]


class RallyPage(ApiModel):
    items: list[RallyDetail]
    next_cursor: str | None
    prediction_revision: int


class TimelineItem(ApiModel):
    kind: str
    public_id: str | None = Field(default=None, alias="id")
    timestamp_us: int = Field(ge=0)
    end_us: int | None = Field(default=None, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    observation_links: dict[str, str] | None = None
    summary: dict[str, object] = Field(default_factory=dict)


class CorrectionTargetDetail(ApiModel):
    target_type: str
    target_id: str
    source_timestamp_us: int = Field(ge=0)
    source_evidence_ids: list[str]
    evidence_start_timestamp_us: int = Field(ge=0)
    evidence_end_timestamp_us: int = Field(ge=0)
    evidence_start_frame_index: int | None = Field(default=None, ge=0)
    evidence_end_frame_index: int | None = Field(default=None, ge=0)


class CorrectionImpactDetail(ApiModel):
    invalidated_sections: list[str]
    invalidated_stats: list[str]


class ReviewItemDetail(ApiModel):
    public_id: str = Field(alias="id")
    target_type: str
    kind: str
    timestamp_us: int = Field(ge=0)
    end_us: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    issue: str
    provenance: str
    probabilities: dict[str, float]
    reasons: list[str]
    evidence_ids: list[str]
    evidence_start_timestamp_us: int = Field(ge=0)
    evidence_end_timestamp_us: int = Field(ge=0)
    evidence_start_frame_index: int | None = Field(default=None, ge=0)
    evidence_end_frame_index: int | None = Field(default=None, ge=0)
    invalidated_sections: list[str]
    invalidated_stats: list[str]
    summary: dict[str, object] = Field(default_factory=dict)
    command_targets: dict[str, CorrectionTargetDetail]
    command_impacts: dict[str, CorrectionImpactDetail]
    review_entity_type: Literal["error_candidate", "shot", "rally"]
    review_entity_id: str
    review_status: str


class ReviewItemPage(ApiModel):
    items: list[ReviewItemDetail]
    next_cursor: str | None
    report_revision: int = Field(ge=1)


class TimelinePage(ApiModel):
    items: list[TimelineItem]
    next_cursor: str | None
    prediction_revision: int
