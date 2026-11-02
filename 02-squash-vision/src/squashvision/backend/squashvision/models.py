from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from squashvision.taxonomy import ShotKind, ShotOutcomeKind


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_public_id() -> str:
    return str(uuid4())


class AssetKind(StrEnum):
    ORIGINAL = "original"
    PROXY = "proxy"
    FRAME = "frame"
    TIMESTAMP_MAP = "timestamp_map"
    EXPORT = "export"
    MODEL = "model"


class ProcessingProfile(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    MAXIMUM = "maximum"


class BallInputMode(StrEnum):
    ORIGINAL = "original"
    INVERTED = "inverted"


class ModelAssetState(StrEnum):
    MISSING = "missing"
    DOWNLOADING = "downloading"
    READY = "ready"
    CORRUPT = "corrupt"
    INCOMPATIBLE = "incompatible"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class Stage(StrEnum):
    PREPARE = "prepare"
    CALIBRATION = "calibration"
    PLAYERS = "players"
    BALL = "ball"
    EVENTS = "events"
    CLASSIFICATION = "classification"
    REPORT = "report"


class PlayerSlot(StrEnum):
    NEAR = "near"
    FAR = "far"



class ErrorKind(StrEnum):
    TRACKING = "tracking"
    SHOT = "shot"
    RALLY = "rally"
    CALIBRATION = "calibration"


class CorrectionStatus(StrEnum):
    ACTIVE = "active"
    CONFLICT = "conflict"
    SUPERSEDED = "superseded"


def constrained_enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        name=name,
    )


class Base(DeclarativeBase):
    pass


class RecordMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=new_public_id, unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Match(RecordMixin, Base):
    __tablename__ = "matches"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    player_a_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    player_b_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    played_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    score: Mapped[str | None] = mapped_column(String(200), nullable=True)
    player_roi: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    deletion_state: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )
    deletion_version: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    media_assets: Mapped[list[MediaAsset]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    analysis_jobs: Mapped[list[AnalysisJob]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    calibrations: Mapped[list[Calibration]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    player_tracks: Mapped[list[PlayerTrack]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    shots: Mapped[list[Shot]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    rallies: Mapped[list[Rally]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    error_candidates: Mapped[list[ErrorCandidate]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    corrections: Mapped[list[Correction]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    report_revisions: Mapped[list[ReportRevision]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )


class MediaAsset(RecordMixin, Base):
    __tablename__ = "media_assets"

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[AssetKind] = mapped_column(
        constrained_enum(AssetKind, "media_asset_kind"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_us: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probe_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    timestamp_index_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timestamp_index_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp_index_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    match: Mapped[Match] = relationship(back_populates="media_assets")
    source_for_jobs: Mapped[list[AnalysisJob]] = relationship(
        back_populates="source_media_asset"
    )
    calibrations: Mapped[list[Calibration]] = relationship(back_populates="media_asset")


class AnalysisJob(RecordMixin, Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        Index(
            "uq_analysis_jobs_active_match",
            "match_id",
            unique=True,
            sqlite_where=text(
                "status IN ('queued', 'running', 'paused')"
            ),
        ),
    )

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    processing_profile: Mapped[ProcessingProfile] = mapped_column(
        constrained_enum(ProcessingProfile, "processing_profile"), nullable=False
    )
    ball_input_mode: Mapped[BallInputMode] = mapped_column(
        constrained_enum(BallInputMode, "ball_input_mode"),
        default=BallInputMode.ORIGINAL,
        server_default="original",
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        constrained_enum(JobStatus, "analysis_job_status"),
        default=JobStatus.QUEUED,
        nullable=False,
    )
    requested_status: Mapped[JobStatus | None] = mapped_column(
        constrained_enum(JobStatus, "requested_job_status"), nullable=True
    )
    worker_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_stage: Mapped[Stage | None] = mapped_column(
        constrained_enum(Stage, "analysis_stage"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    match: Mapped[Match] = relationship(back_populates="analysis_jobs")
    source_media_asset: Mapped[MediaAsset] = relationship(back_populates="source_for_jobs")
    chunks: Mapped[list[JobChunk]] = relationship(
        back_populates="analysis_job", cascade="all, delete-orphan"
    )
    player_tracks: Mapped[list[PlayerTrack]] = relationship(back_populates="analysis_job")
    error_candidates: Mapped[list[ErrorCandidate]] = relationship(
        back_populates="analysis_job"
    )


class JobChunk(RecordMixin, Base):
    __tablename__ = "job_chunks"
    __table_args__ = (
        CheckConstraint(
            "start_us >= 0 AND start_us < end_us", name="valid_job_chunk_range"
        ),
        UniqueConstraint("analysis_job_id", "chunk_index"),
        UniqueConstraint(
            "analysis_job_id",
            "stage",
            "start_us",
            "end_us",
            name="uq_job_chunk_range",
        ),
    )

    analysis_job_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[Stage] = mapped_column(
        constrained_enum(Stage, "job_chunk_stage"), nullable=False
    )
    start_us: Mapped[int] = mapped_column(Integer, nullable=False)
    end_us: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[StageStatus] = mapped_column(
        constrained_enum(StageStatus, "job_chunk_status"),
        default=StageStatus.PENDING,
        nullable=False,
    )
    artifact_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artifact_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dependency_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_availability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    artifact_warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    artifact_payload_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artifact_payload_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    analysis_job: Mapped[AnalysisJob] = relationship(back_populates="chunks")


class StagePublication(RecordMixin, Base):
    __tablename__ = "stage_publications"
    __table_args__ = (
        UniqueConstraint(
            "analysis_job_id",
            "stage",
            "input_hash",
            name="uq_stage_publication_exact_input",
        ),
    )

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_job_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[Stage] = mapped_column(
        constrained_enum(Stage, "stage_publication_stage"), nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    claim_token: Mapped[str] = mapped_column(String(36), nullable=False)
    calibration_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prediction_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Calibration(RecordMixin, Base):
    __tablename__ = "calibrations"
    __table_args__ = (UniqueConstraint("match_id", "revision"),)

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keypoints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    match: Mapped[Match] = relationship(back_populates="calibrations")
    media_asset: Mapped[MediaAsset] = relationship(back_populates="calibrations")


class PlayerTrack(RecordMixin, Base):
    __tablename__ = "player_tracks"
    __table_args__ = (
        UniqueConstraint("match_id", "prediction_revision", "prediction_id"),
    )

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="SET NULL"), index=True
    )
    prediction_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    prediction_id: Mapped[str] = mapped_column(String(100), nullable=False)
    slot: Mapped[PlayerSlot] = mapped_column(
        constrained_enum(PlayerSlot, "player_track_slot"), nullable=False
    )
    source_timestamp_us: Mapped[int | None] = mapped_column(Integer)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    x_m: Mapped[float | None] = mapped_column(Float)
    y_m: Mapped[float | None] = mapped_column(Float)
    observed: Mapped[bool] = mapped_column(default=True, nullable=False)
    calibration_revision: Mapped[int | None] = mapped_column(Integer)
    position_covariance: Mapped[list[list[float]] | None] = mapped_column(JSON)
    position_uncertainty_m: Mapped[float | None] = mapped_column(Float)
    position_provenance: Mapped[str] = mapped_column(
        String(20), default="unavailable", nullable=False
    )
    position_unavailable_reason: Mapped[str | None] = mapped_column(String(100))

    match: Mapped[Match] = relationship(back_populates="player_tracks")
    analysis_job: Mapped[AnalysisJob | None] = relationship(back_populates="player_tracks")
    shots: Mapped[list[Shot]] = relationship(back_populates="player_track")


class Rally(RecordMixin, Base):
    __tablename__ = "rallies"
    __table_args__ = (
        UniqueConstraint("match_id", "prediction_revision", "prediction_id"),
        UniqueConstraint("match_id", "prediction_revision", "ordinal"),
    )

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prediction_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    prediction_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    start_timestamp_us: Mapped[int | None] = mapped_column(Integer)
    end_timestamp_us: Mapped[int | None] = mapped_column(Integer)
    timing_available: Mapped[bool] = mapped_column(default=True, nullable=False)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    review_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    review_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="not_required", nullable=False)
    evidence_provenance: Mapped[str] = mapped_column(String(20), default="unavailable", nullable=False)

    match: Mapped[Match] = relationship(back_populates="rallies")
    shots: Mapped[list[Shot]] = relationship(back_populates="rally")


class Shot(RecordMixin, Base):
    __tablename__ = "shots"
    __table_args__ = (
        UniqueConstraint("match_id", "prediction_revision", "prediction_id"),
    )

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rally_id: Mapped[int | None] = mapped_column(
        ForeignKey("rallies.id", ondelete="SET NULL"), index=True
    )
    player_track_id: Mapped[int | None] = mapped_column(
        ForeignKey("player_tracks.id", ondelete="SET NULL"), index=True
    )
    prediction_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    prediction_id: Mapped[str] = mapped_column(String(100), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_timestamp_us: Mapped[int] = mapped_column(Integer, nullable=False)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    hitter: Mapped[PlayerSlot | None] = mapped_column(
        constrained_enum(PlayerSlot, "shot_hitter"), nullable=True
    )
    kind: Mapped[ShotKind] = mapped_column(
        constrained_enum(ShotKind, "shot_kind"), default=ShotKind.UNKNOWN, nullable=False
    )
    is_volley: Mapped[bool] = mapped_column(default=False, nullable=False)
    outcome: Mapped[ShotOutcomeKind] = mapped_column(
        constrained_enum(ShotOutcomeKind, "shot_outcome_kind"),
        default=ShotOutcomeKind.IN_PLAY,
        nullable=False,
    )
    contact_x_m: Mapped[float | None] = mapped_column(Float)
    contact_y_m: Mapped[float | None] = mapped_column(Float)
    contact_x_px: Mapped[float | None] = mapped_column(Float)
    contact_y_px: Mapped[float | None] = mapped_column(Float)
    contact_covariance: Mapped[list[list[float]] | None] = mapped_column(JSON)
    contact_provenance: Mapped[str | None] = mapped_column(String(30))
    contact_source_width: Mapped[int | None] = mapped_column(Integer)
    contact_source_height: Mapped[int | None] = mapped_column(Integer)
    review_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    classification_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="not_required", nullable=False)
    evidence_provenance: Mapped[str] = mapped_column(String(20), default="unavailable", nullable=False)
    speed_m_s: Mapped[float | None] = mapped_column(Float)
    speed_unavailable_reason: Mapped[str | None] = mapped_column(String(100))

    match: Mapped[Match] = relationship(back_populates="shots")
    rally: Mapped[Rally | None] = relationship(back_populates="shots")
    player_track: Mapped[PlayerTrack | None] = relationship(back_populates="shots")


class ErrorCandidate(RecordMixin, Base):
    __tablename__ = "error_candidates"
    __table_args__ = (
        UniqueConstraint("match_id", "prediction_revision", "prediction_id"),
    )

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="SET NULL"), index=True
    )
    prediction_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    prediction_id: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[ErrorKind] = mapped_column(
        constrained_enum(ErrorKind, "error_candidate_kind"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_prediction_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_timestamp_us: Mapped[int | None] = mapped_column(Integer)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    match: Mapped[Match] = relationship(back_populates="error_candidates")
    analysis_job: Mapped[AnalysisJob | None] = relationship(
        back_populates="error_candidates"
    )
    corrections: Mapped[list[Correction]] = relationship(
        back_populates="error_candidate"
    )


class Correction(RecordMixin, Base):
    __tablename__ = "corrections"

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    error_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("error_candidates.id", ondelete="SET NULL"), index=True
    )
    supersedes_correction_id: Mapped[int | None] = mapped_column(
        ForeignKey("corrections.id", ondelete="RESTRICT"), index=True
    )
    command_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prediction_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_report_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    before_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    after_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_timestamp_us: Mapped[int | None] = mapped_column(Integer)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    review_entity_type: Mapped[str | None] = mapped_column(String(50))
    review_entity_id: Mapped[str | None] = mapped_column(String(100))
    review_decision: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[CorrectionStatus] = mapped_column(
        constrained_enum(CorrectionStatus, "correction_status"), nullable=False
    )
    conflict_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    match: Mapped[Match] = relationship(back_populates="corrections")
    error_candidate: Mapped[ErrorCandidate | None] = relationship(
        back_populates="corrections"
    )


class ReportRevision(RecordMixin, Base):
    __tablename__ = "report_revisions"
    __table_args__ = (UniqueConstraint("match_id", "revision"),)

    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    correction_id: Mapped[int | None] = mapped_column(
        ForeignKey("corrections.id", ondelete="RESTRICT"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    prediction_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    calibration_revision: Mapped[int | None] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sections: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    section_hashes: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    dependency_hashes: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)

    match: Mapped[Match] = relationship(back_populates="report_revisions")


class PendingDeletion(RecordMixin, Base):
    __tablename__ = "pending_deletions"

    match_public_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    deletion_version: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(20), default="planned", nullable=False
    )
    original_relative_path: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    staged_relative_path: Mapped[str] = mapped_column(
        String(600), unique=True, nullable=False
    )


class ModelAsset(RecordMixin, Base):
    __tablename__ = "model_assets"
    __table_args__ = (
        UniqueConstraint("model_name"),
        CheckConstraint(
            "byte_size IS NULL OR byte_size >= 0",
            name="ck_model_assets_nonnegative_byte_size",
        ),
        CheckConstraint(
            "compatibility_version >= 0",
            name="ck_model_assets_compatibility_version",
        ),
    )

    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    repository: Mapped[str] = mapped_column(String(1000), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    requested_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    resolved_revision: Mapped[str | None] = mapped_column(String(200))
    etag: Mapped[str | None] = mapped_column(String(500))
    relative_path: Mapped[str | None] = mapped_column(String(500))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    declared_license: Mapped[str] = mapped_column(String(100), nullable=False)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    compatibility_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[ModelAssetState] = mapped_column(
        constrained_enum(ModelAssetState, "model_asset_state"),
        nullable=False,
        default=ModelAssetState.MISSING,
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
