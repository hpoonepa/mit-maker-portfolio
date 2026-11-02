from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from squashvision.db import Database
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    BallInputMode,
    JobChunk,
    JobStatus,
    Match,
    MediaAsset,
    ProcessingProfile,
    Stage,
    StageStatus,
)
from squashvision.schemas import JobDetail, JobProgress
from squashvision.storage import LocalStorage

Clock = Callable[[], datetime]
HEARTBEAT_INTERVAL = timedelta(seconds=5)
ACTIVE_STATES = (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED)
TERMINAL_STATES = (
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
)
_STAGE_ORDER = {stage: index for index, stage in enumerate(Stage)}
_FAILURE_CODE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")


def _validated_failure_code(value: str) -> str:
    if _FAILURE_CODE.fullmatch(value) is None:
        raise ValueError("failure_code must be a sanitized lower snake-case code")
    return value




def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TimeRange:
    start_us: int
    end_us: int

    def __post_init__(self) -> None:
        if self.start_us < 0 or self.start_us >= self.end_us:
            raise ValueError("time range requires 0 <= start_us < end_us")


@dataclass(frozen=True, slots=True)
class PlannedChunk:
    stage: Stage
    time_range: TimeRange
    plan_hash: str | None = None
    input_hash: str | None = None
    dependency_hash: str | None = None
    config_hash: str | None = None
    artifact_schema_version: int | None = None

    def __post_init__(self) -> None:
        for name in ("plan_hash", "input_hash", "dependency_hash", "config_hash"):
            value = getattr(self, name)
            if value is not None and (
                len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{name} must be lowercase SHA-256")
        if self.artifact_schema_version is not None and self.artifact_schema_version <= 0:
            raise ValueError("artifact schema version must be positive")


class JobError(Exception):
    status_code = 409
    code = "job_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MatchNotFoundError(JobError):
    status_code = 404
    code = "match_not_found"


class MatchNotPreparedError(JobError):
    code = "match_not_prepared"


class MatchDeletingError(JobError):
    code = "match_deleting"


class JobNotFoundError(JobError):
    status_code = 404
    code = "job_not_found"


class ActiveJobConflictError(JobError):
    code = "active_job_exists"


class TransitionConflictError(JobError):
    code = "invalid_job_transition"

    def __init__(self, current: JobStatus, requested: JobStatus) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"cannot transition job from {current.value} to {requested.value}")


class ClaimLostError(JobError):
    code = "job_claim_lost"


class CheckpointConflictError(JobError):
    code = "checkpoint_invalid"


_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.PAUSED,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.PAUSED: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.CANCELLED: frozenset({JobStatus.QUEUED}),
}


class JobQueue:
    def __init__(
        self,
        database: Database,
        storage: LocalStorage,
        *,
        clock: Clock = _utc_now,
        stale_after: timedelta = timedelta(seconds=30),
    ) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        self.database = database
        self.storage = storage
        self.clock = clock
        self.stale_after = stale_after
        self.poll_count = 0
        self._worker_heartbeats: dict[str, datetime] = {}
        self._heartbeat_lock = Lock()

    def enqueue(
        self, match_id: str, profile: ProcessingProfile,
        *, ball_input_mode: BallInputMode = BallInputMode.ORIGINAL,
    ) -> AnalysisJob:
        ball_input_mode = BallInputMode(ball_input_mode)
        if ball_input_mode is BallInputMode.INVERTED and profile is ProcessingProfile.FAST:
            raise ValueError("dark-ball input requires balanced or maximum processing")
        try:
            with self._immediate_session() as session:
                match = session.scalar(select(Match).where(Match.public_id == match_id))
                if match is None:
                    raise MatchNotFoundError(f"match {match_id} does not exist")
                if match.deletion_state != "active":
                    raise MatchDeletingError(
                        f"match {match_id} is being deleted"
                    )
                source = session.scalar(
                    select(MediaAsset)
                    .where(
                        MediaAsset.match_id == match.id,
                        MediaAsset.kind == AssetKind.PROXY,
                    )
                    .order_by(MediaAsset.id)
                )
                if source is None:
                    raise MatchNotPreparedError(
                        f"match {match_id} has no prepared proxy media"
                    )
                active = session.scalar(
                    select(AnalysisJob.id).where(
                        AnalysisJob.match_id == match.id,
                        AnalysisJob.status.in_(ACTIVE_STATES),
                    )
                )
                if active is not None:
                    raise ActiveJobConflictError(
                        f"match {match_id} already has an active analysis job"
                    )
                now = self.clock()
                job = AnalysisJob(
                    match=match,
                    source_media_asset=source,
                    processing_profile=profile,
                    ball_input_mode=ball_input_mode,
                    status=JobStatus.QUEUED,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(job)
                session.flush()
                return job
        except IntegrityError as error:
            raise ActiveJobConflictError(
                f"match {match_id} already has an active analysis job"
            ) from error

    def claim(self, worker_id: str) -> AnalysisJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        now = self.clock()
        stale_before = now - self.stale_after
        connection = self.database.engine.connect()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            job = session.scalar(
                select(AnalysisJob)
                .where(
                    or_(
                        AnalysisJob.status == JobStatus.QUEUED,
                        and_(
                            AnalysisJob.status == JobStatus.RUNNING,
                            or_(
                                AnalysisJob.heartbeat_at.is_(None),
                                AnalysisJob.heartbeat_at < stale_before,
                            ),
                        ),
                    )
                )
                .order_by(AnalysisJob.created_at, AnalysisJob.id)
                .limit(1)
            )
            if job is None:
                connection.commit()
                return None
            was_queued = job.status is JobStatus.QUEUED
            job.status = JobStatus.RUNNING
            if was_queued:
                job.requested_status = None
            job.worker_id = worker_id
            job.claim_token = str(uuid4())
            job.heartbeat_at = now
            job.updated_at = now
            job.version += 1
            session.flush()
            connection.commit()
            with self._heartbeat_lock:
                self._worker_heartbeats[worker_id] = now
            return job
        except BaseException:
            connection.rollback()
            raise
        finally:
            session.close()
            connection.close()

    def get(self, job_id: str) -> AnalysisJob:
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            session.expunge(job)
            if job.heartbeat_at is not None:
                job.heartbeat_at = _as_utc(job.heartbeat_at)
            return job

    def transition(self, job_id: str, requested: JobStatus) -> AnalysisJob:
        with self._immediate_session() as session:
            job = self._job_or_raise(session, job_id)
            if requested in ACTIVE_STATES:
                match = session.get(Match, job.match_id)
                if match is None:
                    raise MatchNotFoundError("job match does not exist")
                if match.deletion_state != "active":
                    raise MatchDeletingError("job match is being deleted")
            if requested not in _ALLOWED_TRANSITIONS[job.status]:
                raise TransitionConflictError(job.status, requested)
            self._set_state(job, requested)
            return job

    def pause(self, job_id: str) -> AnalysisJob:
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            if job.status is JobStatus.RUNNING:
                job.requested_status = JobStatus.PAUSED
                self._touch(job)
            elif job.status is JobStatus.QUEUED:
                self._set_state(job, JobStatus.PAUSED)
            else:
                raise TransitionConflictError(job.status, JobStatus.PAUSED)
            return job

    def resume(self, job_id: str) -> AnalysisJob:
        return self.transition(job_id, JobStatus.QUEUED)

    def cancel(self, job_id: str) -> AnalysisJob:
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            if job.status is JobStatus.RUNNING:
                job.requested_status = JobStatus.CANCELLED
                self._touch(job)
            elif job.status in (JobStatus.QUEUED, JobStatus.PAUSED):
                self._set_state(job, JobStatus.CANCELLED)
            else:
                raise TransitionConflictError(job.status, JobStatus.CANCELLED)
            return job

    def retry(self, job_id: str) -> AnalysisJob:
        try:
            with self._immediate_session() as session:
                job = self._job_or_raise(session, job_id)
                match = session.get(Match, job.match_id)
                if match is None:
                    raise MatchNotFoundError("job match does not exist")
                if match.deletion_state != "active":
                    raise MatchDeletingError("job match is being deleted")
                if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
                    raise TransitionConflictError(job.status, JobStatus.QUEUED)
                active = session.scalar(
                    select(AnalysisJob.id).where(
                        AnalysisJob.match_id == job.match_id,
                        AnalysisJob.id != job.id,
                        AnalysisJob.status.in_(ACTIVE_STATES),
                    )
                )
                if active is not None:
                    raise ActiveJobConflictError(
                        "match already has another active analysis job"
                    )
                chunks = session.scalars(
                    select(JobChunk).where(JobChunk.analysis_job_id == job.id)
                ).all()
                self._set_state(job, JobStatus.QUEUED)
                job.error_message = None
                job.failure_code = None
                for chunk in chunks:
                    if chunk.status in (StageStatus.RUNNING, StageStatus.FAILED):
                        chunk.status = StageStatus.PENDING
                        chunk.updated_at = self.clock()
                return job
        except IntegrityError as error:
            raise ActiveJobConflictError(
                "match already has another active analysis job"
            ) from error

    def fail(
        self,
        job_id: str,
        message: str,
        *,
        failure_code: str = "processing_failed",
    ) -> AnalysisJob:
        code = _validated_failure_code(failure_code)
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            if job.status is not JobStatus.RUNNING:
                raise TransitionConflictError(job.status, JobStatus.FAILED)
            job.error_message = message
            job.failure_code = code
            self._set_state(job, JobStatus.FAILED)
            for chunk in job.chunks:
                if chunk.status is StageStatus.RUNNING:
                    chunk.status = StageStatus.FAILED
                    chunk.updated_at = self.clock()
            return job

    def apply_requested_control(self, job_id: str) -> AnalysisJob:
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            if job.requested_status is None:
                return job
            requested = job.requested_status
            if requested not in (JobStatus.PAUSED, JobStatus.CANCELLED):
                raise TransitionConflictError(job.status, requested)
            if job.status is not JobStatus.RUNNING:
                raise TransitionConflictError(job.status, requested)
            self._set_state(job, requested)
            return job

    def has_plan(self, job_id: str) -> bool:
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            return (
                session.scalar(
                    select(JobChunk.id)
                    .where(JobChunk.analysis_job_id == job.id)
                    .limit(1)
                )
                is not None
            )


    def plan(self, job_id: str, chunks: Iterable[PlannedChunk]) -> list[JobChunk]:
        ordered = sorted(
            chunks,
            key=lambda chunk: (
                _STAGE_ORDER[chunk.stage],
                chunk.time_range.start_us,
                chunk.time_range.end_us,
            ),
        )
        identities = [
            (chunk.stage, chunk.time_range.start_us, chunk.time_range.end_us)
            for chunk in ordered
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("job plan contains duplicate chunks")
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            existing = sorted(job.chunks, key=lambda chunk: chunk.chunk_index)
            if existing:
                existing_identities = [
                    (chunk.stage, chunk.start_us, chunk.end_us) for chunk in existing
                ]
                if existing_identities != identities:
                    raise CheckpointConflictError(
                        f"job {job_id} already has a different chunk plan"
                    )
                return existing
            now = self.clock()
            rows = [
                JobChunk(
                    analysis_job=job,
                    chunk_index=index,
                    stage=chunk.stage,
                    start_us=chunk.time_range.start_us,
                    end_us=chunk.time_range.end_us,
                    status=StageStatus.PENDING,
                    created_at=now,
                    updated_at=now,
                    plan_hash=chunk.plan_hash,
                    input_hash=chunk.input_hash,
                    dependency_hash=chunk.dependency_hash,
                    config_hash=chunk.config_hash,
                    artifact_schema_version=chunk.artifact_schema_version,
                )
                for index, chunk in enumerate(ordered)
            ]
            session.add_all(rows)
            self._touch(job)
            session.flush()
            return rows

    def next_chunk(self, job_id: str) -> PlannedChunk | None:
        invalidated: PlannedChunk | None = None
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            chunks = session.scalars(
                select(JobChunk)
                .where(JobChunk.analysis_job_id == job.id)
                .order_by(JobChunk.chunk_index)
            ).all()
            for chunk in chunks:
                planned = self._planned_chunk(chunk)
                if chunk.status is not StageStatus.COMPLETED:
                    return planned
                if not self._checkpoint_is_verified(chunk):
                    chunk.status = StageStatus.INVALIDATED
                    chunk.updated_at = self.clock()
                    self._touch(job)
                    invalidated = planned
                    break
        return invalidated

    def start_chunk(
        self, job_id: str, stage: Stage, chunk_range: TimeRange
    ) -> JobChunk:
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            if job.status is not JobStatus.RUNNING:
                raise TransitionConflictError(job.status, JobStatus.RUNNING)
            chunk = self._chunk_or_raise(session, job, stage, chunk_range)
            if chunk.status is StageStatus.COMPLETED and self._checkpoint_is_verified(chunk):
                return chunk
            chunk.status = StageStatus.RUNNING
            chunk.updated_at = self.clock()
            job.current_stage = stage
            self._touch(job)
            return chunk

    def find_chunk(
        self, job_id: str, stage: Stage, chunk_range: TimeRange
    ) -> JobChunk:
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            return self._chunk_or_raise(session, job, stage, chunk_range)

    def checkpoint(
        self,
        job_id: str,
        stage: Stage,
        chunk: TimeRange,
        artifact: Path,
    ) -> None:
        source = Path(artifact)
        source_signature = self._file_signature(source)
        if source_signature is None or source_signature[0] <= 0:
            raise CheckpointConflictError("checkpoint artifact must be a nonempty file")
        source_size, source_hash = source_signature
        destination = self._checkpoint_path(job_id, stage, chunk)

        invalid_reason: str | None = None
        publish_required = True
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            row = self._chunk_or_raise(session, job, stage, chunk)
            actual = self._file_signature(destination)
            expected = (
                (row.artifact_size, row.artifact_sha256)
                if row.artifact_size is not None and row.artifact_sha256 is not None
                else None
            )
            incoming = (source_size, source_hash)
            if row.status is StageStatus.COMPLETED:
                if actual == expected == incoming:
                    return
                invalid_reason = "completed checkpoint artifact is missing or mismatched"
            elif row.status is StageStatus.INVALIDATED and expected is not None:
                if incoming != expected:
                    invalid_reason = "replacement does not match the invalidated checkpoint"
            elif actual is not None:
                if actual == incoming:
                    publish_required = False
                else:
                    invalid_reason = "unrecorded checkpoint artifact is mismatched"
            if invalid_reason is not None:
                row.status = StageStatus.INVALIDATED
                row.updated_at = self.clock()
                self._touch(job)

        if invalid_reason is not None:
            raise CheckpointConflictError(invalid_reason)

        if publish_required:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.{uuid4().hex}.tmp"
            )
            try:
                with source.open("rb") as source_file, temporary.open("xb") as target_file:
                    shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
                    target_file.flush()
                    os.fsync(target_file.fileno())
                if self._file_signature(temporary) != (source_size, source_hash):
                    raise CheckpointConflictError(
                        "checkpoint artifact changed while it was copied"
                    )
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

        relative = destination.relative_to(self.storage.root)
        publish_invalid = False
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            row = self._chunk_or_raise(session, job, stage, chunk)
            if self._file_signature(destination) != (source_size, source_hash):
                row.status = StageStatus.INVALIDATED
                row.updated_at = self.clock()
                self._touch(job)
                publish_invalid = True
            else:
                row.artifact_path = str(relative)
                row.artifact_size = source_size
                row.artifact_sha256 = source_hash
                row.status = StageStatus.COMPLETED
                row.updated_at = self.clock()
                job.current_stage = stage
                self._touch(job)
        if publish_invalid:
            raise CheckpointConflictError(
                "published checkpoint failed integrity verification"
            )

    def heartbeat(self, worker_id: str) -> datetime:
        now = self.clock()
        with self._heartbeat_lock:
            last = self._worker_heartbeats.get(worker_id)
            if last is not None and now - last < HEARTBEAT_INTERVAL:
                return last
            self._worker_heartbeats[worker_id] = now
        with self.database.session() as session:
            jobs = session.scalars(
                select(AnalysisJob).where(
                    AnalysisJob.worker_id == worker_id,
                    AnalysisJob.status == JobStatus.RUNNING,
                )
            ).all()
            for job in jobs:
                job.heartbeat_at = now
                job.updated_at = now
                job.version += 1
        return now

    def worker_is_healthy(self) -> bool:
        now = self.clock()
        with self._heartbeat_lock:
            latest = max(self._worker_heartbeats.values(), default=None)
        with self.database.session() as session:
            durable = session.scalar(
                select(AnalysisJob.heartbeat_at)
                .where(AnalysisJob.heartbeat_at.is_not(None))
                .order_by(AnalysisJob.heartbeat_at.desc())
                .limit(1)
            )
        candidates = [value for value in (latest, durable) if value is not None]
        return bool(
            candidates
            and now - max(_as_utc(value) for value in candidates) <= self.stale_after
        )

    def snapshot(self, job_id: str) -> JobDetail:
        self.poll_count += 1
        with self.database.session() as session:
            job = self._job_or_raise(session, job_id)
            match_id = session.scalar(
                select(Match.public_id).where(Match.id == job.match_id)
            )
            chunks = session.scalars(
                select(JobChunk)
                .where(JobChunk.analysis_job_id == job.id)
                .order_by(JobChunk.chunk_index)
            ).all()
            progress: JobProgress | None = None
            if chunks:
                completed = sum(
                    chunk.status is StageStatus.COMPLETED for chunk in chunks
                )
                progress = JobProgress(
                    completed_chunks=completed,
                    planned_chunks=len(chunks),
                    fraction=completed / len(chunks),
                )
            stage_state: StageStatus | None = None
            current_chunk: JobChunk | None = None
            if job.current_stage is not None:
                stage_chunks = [
                    chunk for chunk in chunks if chunk.stage is job.current_stage
                ]
                if stage_chunks:
                    if any(
                        chunk.status is StageStatus.INVALIDATED
                        for chunk in stage_chunks
                    ):
                        stage_state = StageStatus.INVALIDATED
                    elif any(
                        chunk.status is StageStatus.FAILED for chunk in stage_chunks
                    ):
                        stage_state = StageStatus.FAILED
                    elif any(
                        chunk.status is StageStatus.RUNNING for chunk in stage_chunks
                    ):
                        stage_state = StageStatus.RUNNING
                    elif all(
                        chunk.status is StageStatus.COMPLETED for chunk in stage_chunks
                    ):
                        stage_state = StageStatus.COMPLETED
                    else:
                        stage_state = StageStatus.PENDING
                for status in (
                    StageStatus.RUNNING,
                    StageStatus.FAILED,
                    StageStatus.PENDING,
                    StageStatus.COMPLETED,
                ):
                    matching = [
                        chunk for chunk in stage_chunks if chunk.status is status
                    ]
                    if matching:
                        current_chunk = (
                            matching[-1]
                            if status is StageStatus.COMPLETED
                            else matching[0]
                        )
                        break
            assert match_id is not None
            return JobDetail(
                id=job.public_id,
                match_id=match_id,
                profile=job.processing_profile,
                ball_input_mode=job.ball_input_mode,
                state=job.status,
                stage=job.current_stage,
                stage_state=stage_state,
                requested_state=job.requested_status,
                version=job.version,
                created_at=job.created_at,
                updated_at=job.updated_at,
                heartbeat_at=job.heartbeat_at,
                progress=progress,
                current_range_start_us=(
                    current_chunk.start_us if current_chunk is not None else None
                ),
                current_range_end_us=(
                    current_chunk.end_us if current_chunk is not None else None
                ),
                failure_code=job.failure_code,
            )

    def apply_requested_control_claimed(
        self, job_id: str, worker_id: str, claim_token: str
    ) -> AnalysisJob:
        with self._immediate_session() as session:
            job = self._claimed_job(session, job_id, worker_id, claim_token)
            if job.requested_status is None:
                return job
            requested = job.requested_status
            if requested not in (JobStatus.PAUSED, JobStatus.CANCELLED):
                raise TransitionConflictError(job.status, requested)
            self._set_state(job, requested)
            return job

    def plan_claimed(
        self,
        job_id: str,
        worker_id: str,
        claim_token: str,
        chunks: Iterable[PlannedChunk],
    ) -> list[JobChunk]:
        ordered = sorted(
            chunks,
            key=lambda chunk: (
                _STAGE_ORDER[chunk.stage],
                chunk.time_range.start_us,
                chunk.time_range.end_us,
            ),
        )
        identities = [
            (chunk.stage, chunk.time_range.start_us, chunk.time_range.end_us)
            for chunk in ordered
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("job plan contains duplicate chunks")
        with self._immediate_session() as session:
            job = self._claimed_job(session, job_id, worker_id, claim_token)
            existing = session.scalars(
                select(JobChunk)
                .where(JobChunk.analysis_job_id == job.id)
                .order_by(JobChunk.chunk_index)
            ).all()
            if existing:
                if [
                    (chunk.stage, chunk.start_us, chunk.end_us)
                    for chunk in existing
                ] != identities:
                    raise CheckpointConflictError(
                        f"job {job_id} already has a different chunk plan"
                    )
                return existing
            now = self.clock()
            rows = [
                JobChunk(
                    analysis_job=job,
                    chunk_index=index,
                    stage=chunk.stage,
                    start_us=chunk.time_range.start_us,
                    end_us=chunk.time_range.end_us,
                    status=StageStatus.PENDING,
                    created_at=now,
                    updated_at=now,
                    plan_hash=chunk.plan_hash,
                    input_hash=chunk.input_hash,
                    dependency_hash=chunk.dependency_hash,
                    config_hash=chunk.config_hash,
                    artifact_schema_version=chunk.artifact_schema_version,
                )
                for index, chunk in enumerate(ordered)
            ]
            session.add_all(rows)
            self._touch(job)
            session.flush()
            return rows

    def reconcile_plan_claimed(
        self,
        job_id: str,
        worker_id: str,
        claim_token: str,
        chunks: Iterable[PlannedChunk],
    ) -> list[JobChunk]:
        ordered = sorted(
            chunks,
            key=lambda chunk: (
                _STAGE_ORDER[chunk.stage],
                chunk.time_range.start_us,
                chunk.time_range.end_us,
            ),
        )
        identities = [
            (chunk.stage, chunk.time_range.start_us, chunk.time_range.end_us)
            for chunk in ordered
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("job plan contains duplicate chunks")
        cleanup_paths: set[Path] = set()
        with self._immediate_session() as session:
            job = self._claimed_job(
                session, job_id, worker_id, claim_token
            )
            existing = session.scalars(
                select(JobChunk)
                .where(JobChunk.analysis_job_id == job.id)
                .order_by(JobChunk.chunk_index)
            ).all()
            by_identity = {
                (row.stage, row.start_us, row.end_us): row
                for row in existing
            }
            for offset, row in enumerate(existing, start=1):
                row.chunk_index = -offset
            session.flush()
            reconciled: list[JobChunk] = []
            changed = False
            for index, planned in enumerate(ordered):
                identity = (
                    planned.stage,
                    planned.time_range.start_us,
                    planned.time_range.end_us,
                )
                row = by_identity.pop(identity, None)
                if row is None:
                    row = JobChunk(
                        analysis_job=job,
                        chunk_index=index,
                        stage=planned.stage,
                        start_us=planned.time_range.start_us,
                        end_us=planned.time_range.end_us,
                        status=StageStatus.PENDING,
                        created_at=self.clock(),
                        updated_at=self.clock(),
                    )
                    self._apply_planned_contract(row, planned)
                    session.add(row)
                    changed = True
                else:
                    row.chunk_index = index
                    if self._contract_changed(row, planned):
                        cleanup_paths.update(
                            self._managed_checkpoint_paths(row)
                        )
                        self._apply_planned_contract(row, planned)
                        self._invalidate_contract(row)
                        changed = True
                    elif (
                        planned.plan_hash is not None
                        and row.plan_hash != planned.plan_hash
                    ):
                        row.plan_hash = planned.plan_hash
                        row.updated_at = self.clock()
                        changed = True
                reconciled.append(row)
            for obsolete in by_identity.values():
                cleanup_paths.update(
                    self._managed_checkpoint_paths(obsolete)
                )
                session.delete(obsolete)
                changed = True
            if changed:
                self._touch(job)
            session.flush()
        self._remove_managed_checkpoint_paths(cleanup_paths)
        return reconciled

    def reconcile_chunk_claimed(
        self,
        job_id: str,
        worker_id: str,
        claim_token: str,
        planned: PlannedChunk,
    ) -> JobChunk:
        cleanup_paths: set[Path] = set()
        with self._immediate_session() as session:
            job = self._claimed_job(session, job_id, worker_id, claim_token)
            row = self._chunk_or_raise(
                session, job, planned.stage, planned.time_range
            )
            if self._contract_changed(row, planned):
                cleanup_paths.update(self._managed_checkpoint_paths(row))
                self._apply_planned_contract(row, planned)
                self._invalidate_contract(row)
                self._touch(job)
            elif (
                planned.plan_hash is not None
                and row.plan_hash != planned.plan_hash
            ):
                row.plan_hash = planned.plan_hash
                row.updated_at = self.clock()
                self._touch(job)
        self._remove_managed_checkpoint_paths(cleanup_paths)
        return row

    def start_chunk_claimed(
        self,
        job_id: str,
        stage: Stage,
        chunk_range: TimeRange,
        worker_id: str,
        claim_token: str,
    ) -> JobChunk:
        with self._immediate_session() as session:
            job = self._claimed_job(session, job_id, worker_id, claim_token)
            chunk = self._chunk_or_raise(session, job, stage, chunk_range)
            if (
                chunk.status is StageStatus.COMPLETED
                and self._checkpoint_is_verified(chunk)
            ):
                return chunk
            chunk.status = StageStatus.RUNNING
            chunk.updated_at = self.clock()
            job.current_stage = stage
            self._touch(job)
            return chunk

    def heartbeat_claim(
        self, job_id: str, worker_id: str, claim_token: str
    ) -> datetime:
        now = self.clock()
        with self._immediate_session() as session:
            job = self._claimed_job(session, job_id, worker_id, claim_token)
            with self._heartbeat_lock:
                last = self._worker_heartbeats.get(worker_id)
            if last is not None and now - last < HEARTBEAT_INTERVAL:
                return last
            job.heartbeat_at = now
            job.updated_at = now
            job.version += 1
        with self._heartbeat_lock:
            self._worker_heartbeats[worker_id] = now
        return now

    def complete_claimed(
        self, job_id: str, worker_id: str, claim_token: str
    ) -> AnalysisJob:
        with self._immediate_session() as session:
            job = self._claimed_job(session, job_id, worker_id, claim_token)
            self._set_state(job, JobStatus.COMPLETED)
            return job

    def fail_claimed(
        self,
        job_id: str,
        worker_id: str,
        claim_token: str,
        message: str,
        *,
        failure_code: str = "processing_failed",
    ) -> AnalysisJob:
        code = _validated_failure_code(failure_code)
        with self._immediate_session() as session:
            job = self._claimed_job(session, job_id, worker_id, claim_token)
            running_chunks = session.scalars(
                select(JobChunk).where(
                    JobChunk.analysis_job_id == job.id,
                    JobChunk.status == StageStatus.RUNNING,
                )
            ).all()
            job.error_message = message
            job.failure_code = code
            self._set_state(job, JobStatus.FAILED)
            for chunk in running_chunks:
                chunk.status = StageStatus.FAILED
                chunk.updated_at = self.clock()
            return job

    def checkpoint_claimed(
        self,
        job_id: str,
        stage: Stage,
        chunk: TimeRange,
        artifact: Path,
        worker_id: str,
        claim_token: str,
    ) -> None:
        source = Path(artifact)
        source_signature = self._file_signature(source)
        if source_signature is None or source_signature[0] <= 0:
            raise CheckpointConflictError("checkpoint artifact must be a nonempty file")
        source_size, source_hash = source_signature
        envelope_metadata = self._artifact_envelope_metadata(source)
        destination = self._checkpoint_path(job_id, stage, chunk)
        invalid_reason: str | None = None

        with self._immediate_session() as session:
            job = self._claimed_job(session, job_id, worker_id, claim_token)
            row = self._chunk_or_raise(session, job, stage, chunk)
            actual = self._file_signature(destination)
            expected = (
                (row.artifact_size, row.artifact_sha256)
                if row.artifact_size is not None and row.artifact_sha256 is not None
                else None
            )
            incoming = (source_size, source_hash)
            if envelope_metadata is not None:
                (
                    envelope_stage,
                    envelope_range,
                    envelope_input_hash,
                    envelope_schema,
                    _availability,
                    _warnings,
                    payload_source,
                    payload_size,
                    payload_sha256,
                ) = envelope_metadata
                if (
                    envelope_stage is not stage
                    or envelope_range != chunk
                    or (
                        row.input_hash is not None
                        and envelope_input_hash != row.input_hash
                    )
                    or (
                        row.artifact_schema_version is not None
                        and envelope_schema != row.artifact_schema_version
                    )
                ):
                    invalid_reason = "artifact envelope does not match chunk contract"
            publish_required = True
            if row.status is StageStatus.COMPLETED:
                if (
                    actual == expected == incoming
                    and self._checkpoint_is_verified(row)
                ):
                    return
                invalid_reason = "completed checkpoint artifact is missing or mismatched"
            elif row.status is StageStatus.INVALIDATED and expected is not None:
                if incoming != expected:
                    invalid_reason = (
                        "replacement does not match the invalidated checkpoint"
                    )
            elif actual is not None:
                if actual == incoming:
                    publish_required = False
                else:
                    invalid_reason = "unrecorded checkpoint artifact is mismatched"

            if invalid_reason is not None:
                row.status = StageStatus.INVALIDATED
                row.updated_at = self.clock()
                self._touch(job)
            else:
                if publish_required:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_name(
                        f".{destination.name}.{uuid4().hex}.tmp"
                    )
                    try:
                        with (
                            source.open("rb") as source_file,
                            temporary.open("xb") as target_file,
                        ):
                            shutil.copyfileobj(
                                source_file, target_file, length=1024 * 1024
                            )
                            target_file.flush()
                            os.fsync(target_file.fileno())
                        if self._file_signature(temporary) != incoming:
                            raise CheckpointConflictError(
                                "checkpoint artifact changed while it was copied"
                            )
                        os.replace(temporary, destination)
                    finally:
                        temporary.unlink(missing_ok=True)
                payload_destination: Path | None = None
                if envelope_metadata is not None:
                    payload_destination = destination.with_name(
                        f"{destination.stem}.payload{payload_source.suffix}"
                    )
                    payload_incoming = (payload_size, payload_sha256)
                    if self._file_signature(payload_destination) != payload_incoming:
                        payload_temporary = payload_destination.with_name(
                            f".{payload_destination.name}.{uuid4().hex}.tmp"
                        )
                        try:
                            with (
                                payload_source.open("rb") as source_file,
                                payload_temporary.open("xb") as target_file,
                            ):
                                shutil.copyfileobj(
                                    source_file,
                                    target_file,
                                    length=1024 * 1024,
                                )
                                target_file.flush()
                                os.fsync(target_file.fileno())
                            if self._file_signature(payload_temporary) != payload_incoming:
                                raise CheckpointConflictError(
                                    "checkpoint payload changed while it was copied"
                                )
                            os.replace(
                                payload_temporary, payload_destination
                            )
                        finally:
                            payload_temporary.unlink(missing_ok=True)
                if (
                    self._file_signature(destination) != incoming
                    or (
                        envelope_metadata is not None
                        and self._file_signature(payload_destination)
                        != (payload_size, payload_sha256)
                    )
                ):
                    row.status = StageStatus.INVALIDATED
                    row.updated_at = self.clock()
                    self._touch(job)
                    invalid_reason = (
                        "published checkpoint failed integrity verification"
                    )
                else:
                    row.artifact_path = str(
                        destination.relative_to(self.storage.root)
                    )
                    row.artifact_size = source_size
                    row.artifact_sha256 = source_hash
                    if envelope_metadata is not None:
                        row.artifact_availability = envelope_metadata[4]
                        row.artifact_warnings = list(envelope_metadata[5])
                        assert payload_destination is not None
                        row.artifact_payload_path = str(
                            payload_destination.relative_to(
                                self.storage.root
                            )
                        )
                        row.artifact_payload_size = payload_size
                        row.artifact_payload_sha256 = payload_sha256
                    row.status = StageStatus.COMPLETED
                    row.updated_at = self.clock()
                    job.current_stage = stage
                    self._touch(job)
        if invalid_reason is not None:
            raise CheckpointConflictError(invalid_reason)

    @contextmanager
    def _immediate_session(self) -> Iterator[Session]:
        connection = self.database.engine.connect()
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

    def _claimed_job(
        self,
        session: Session,
        job_id: str,
        worker_id: str,
        claim_token: str,
    ) -> AnalysisJob:
        job = self._job_or_raise(session, job_id)
        if (
            job.status is not JobStatus.RUNNING
            or job.worker_id != worker_id
            or job.claim_token != claim_token
        ):
            raise ClaimLostError(f"worker {worker_id} no longer owns job {job_id}")
        return job

    def _checkpoint_path(
        self, job_id: str, stage: Stage, chunk: TimeRange
    ) -> Path:
        root = self.storage.root.resolve(strict=False)
        destination = (
            root
            / "checkpoints"
            / job_id
            / stage.value
            / f"{chunk.start_us}-{chunk.end_us}.bin"
        ).resolve(strict=False)
        if root not in destination.parents:
            raise CheckpointConflictError("checkpoint path escaped storage root")
        return destination

    def _checkpoint_is_verified(self, chunk: JobChunk) -> bool:
        if (
            chunk.artifact_path is None
            or chunk.artifact_size is None
            or chunk.artifact_sha256 is None
        ):
            return False
        candidate = (self.storage.root / chunk.artifact_path).resolve(strict=False)
        root = self.storage.root.resolve(strict=False)
        if root not in candidate.parents:
            return False
        if self._file_signature(candidate) != (
            chunk.artifact_size,
            chunk.artifact_sha256,
        ):
            return False
        payload_fields = (
            chunk.artifact_payload_path,
            chunk.artifact_payload_size,
            chunk.artifact_payload_sha256,
        )
        if payload_fields == (None, None, None):
            return True
        if any(value is None for value in payload_fields):
            return False
        payload = (
            self.storage.root / str(chunk.artifact_payload_path)
        ).resolve(strict=False)
        if root not in payload.parents:
            return False
        return self._file_signature(payload) == (
            chunk.artifact_payload_size,
            chunk.artifact_payload_sha256,
        )

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, str] | None:
        try:
            if not path.is_file():
                return None
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    size += len(block)
                    digest.update(block)
            return size, digest.hexdigest()
        except OSError:
            return None

    @classmethod
    def _artifact_envelope_metadata(
        cls, path: Path
    ) -> tuple[
        Stage,
        TimeRange,
        str,
        int,
        str,
        tuple[str, ...],
        Path,
        int,
        str,
    ] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or not {
            "schema_version",
            "stage",
            "input_hash",
            "payload_name",
        }.issubset(raw):
            return None
        try:
            stage = Stage(str(raw["stage"]))
            time_range = TimeRange(int(raw["start_us"]), int(raw["end_us"]))
            input_hash = str(raw["input_hash"])
            schema_version = int(raw["schema_version"])
            availability = str(raw["availability"])
            warnings = tuple(str(item) for item in raw["warnings"])
            payload_name = str(raw["payload_name"])
            payload_size = int(raw["payload_size"])
            payload_sha256 = str(raw["payload_sha256"])
            artifact_size = int(raw["artifact_size"])
            artifact_sha256 = str(raw["artifact_sha256"])
        except (KeyError, TypeError, ValueError) as error:
            raise CheckpointConflictError(
                "checkpoint artifact envelope is malformed"
            ) from error
        if (
            len(input_hash) != 64
            or any(character not in "0123456789abcdef" for character in input_hash)
            or schema_version <= 0
            or availability not in {"available", "partial", "unavailable"}
            or Path(payload_name).name != payload_name
        ):
            raise CheckpointConflictError(
                "checkpoint artifact envelope is invalid"
            )
        payload_path = (path.parent / payload_name).resolve(strict=False)
        if path.parent.resolve(strict=False) not in payload_path.parents:
            raise CheckpointConflictError(
                "checkpoint artifact payload escaped its envelope"
            )
        signature = cls._file_signature(payload_path)
        if signature != (payload_size, payload_sha256) or signature != (
            artifact_size,
            artifact_sha256,
        ):
            raise CheckpointConflictError(
                "checkpoint artifact payload failed integrity validation"
            )
        return (
            stage,
            time_range,
            input_hash,
            schema_version,
            availability,
            warnings,
            payload_path,
            payload_size,
            payload_sha256,
        )

    @staticmethod
    def _job_or_raise(session: Session, job_id: str) -> AnalysisJob:
        job = session.scalar(
            select(AnalysisJob).where(AnalysisJob.public_id == job_id)
        )
        if job is None:
            raise JobNotFoundError(f"analysis job {job_id} does not exist")
        return job

    @staticmethod
    def _chunk_or_raise(
        session: Session,
        job: AnalysisJob,
        stage: Stage,
        chunk: TimeRange,
    ) -> JobChunk:
        row = session.scalar(
            select(JobChunk).where(
                JobChunk.analysis_job_id == job.id,
                JobChunk.stage == stage,
                JobChunk.start_us == chunk.start_us,
                JobChunk.end_us == chunk.end_us,
            )
        )
        if row is None:
            raise CheckpointConflictError(
                f"chunk {stage.value}:{chunk.start_us}-{chunk.end_us} is not planned"
            )
        return row

    @staticmethod
    def _planned_contract(
        chunk: PlannedChunk,
    ) -> tuple[str | None, str | None, str | None, str | None, int | None]:
        return (
            chunk.plan_hash,
            chunk.input_hash,
            chunk.dependency_hash,
            chunk.config_hash,
            chunk.artifact_schema_version,
        )

    @staticmethod
    def _chunk_contract(
        chunk: JobChunk,
    ) -> tuple[str | None, str | None, str | None, str | None, int | None]:
        return (
            chunk.plan_hash,
            chunk.input_hash,
            chunk.dependency_hash,
            chunk.config_hash,
            chunk.artifact_schema_version,
        )

    @staticmethod
    def _planned_chunk(chunk: JobChunk) -> PlannedChunk:
        return PlannedChunk(
            chunk.stage,
            TimeRange(chunk.start_us, chunk.end_us),
            plan_hash=chunk.plan_hash,
            input_hash=chunk.input_hash,
            dependency_hash=chunk.dependency_hash,
            config_hash=chunk.config_hash,
            artifact_schema_version=chunk.artifact_schema_version,
        )

    @staticmethod
    def _contract_changed(row: JobChunk, planned: PlannedChunk) -> bool:
        values = (
            ("input_hash", planned.input_hash),
            ("dependency_hash", planned.dependency_hash),
            ("config_hash", planned.config_hash),
            ("artifact_schema_version", planned.artifact_schema_version),
        )
        return any(
            value is not None and getattr(row, name) != value
            for name, value in values
        )

    @staticmethod
    def _apply_planned_contract(row: JobChunk, planned: PlannedChunk) -> None:
        for name in (
            "plan_hash",
            "input_hash",
            "dependency_hash",
            "config_hash",
            "artifact_schema_version",
        ):
            value = getattr(planned, name)
            if value is not None:
                setattr(row, name, value)

    @staticmethod
    def _managed_checkpoint_paths(row: JobChunk) -> set[Path]:
        return {
            Path(value)
            for value in (
                row.artifact_path,
                row.artifact_payload_path,
            )
            if value is not None
        }

    def _remove_managed_checkpoint_paths(
        self, relative_paths: Iterable[Path]
    ) -> None:
        for relative in relative_paths:
            try:
                self.storage.remove_owned_tree(
                    relative,
                    owned_paths={relative},
                )
            except (OSError, PermissionError, ValueError):
                continue


    def _invalidate_contract(self, row: JobChunk) -> None:
        if row.status is not StageStatus.PENDING:
            row.status = StageStatus.INVALIDATED
        row.artifact_path = None
        row.artifact_size = None
        row.artifact_sha256 = None
        row.artifact_availability = None
        row.artifact_warnings = None
        row.artifact_payload_path = None
        row.artifact_payload_size = None
        row.artifact_payload_sha256 = None
        row.updated_at = self.clock()

    def _set_state(self, job: AnalysisJob, requested: JobStatus) -> None:
        job.status = requested
        job.requested_status = None
        if requested is not JobStatus.RUNNING:
            job.worker_id = None
            job.claim_token = None
        if requested in (JobStatus.QUEUED, JobStatus.PAUSED):
            job.heartbeat_at = None
        self._touch(job)

    def _touch(self, job: AnalysisJob) -> None:
        job.updated_at = self.clock()
        job.version += 1
