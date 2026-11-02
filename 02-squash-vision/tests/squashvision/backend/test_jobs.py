from __future__ import annotations

import asyncio
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))

from squashvision.app import create_app
from squashvision.db import Database
from squashvision.jobs import (
    ActiveJobConflictError,
    CheckpointConflictError,
    ClaimLostError,
    JobQueue,
    MatchNotFoundError,
    PlannedChunk,
    TimeRange,
    TransitionConflictError,
)
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    BallInputMode,
    JobChunk,
    JobStatus,
    Match,
    MediaAsset,
    ModelAssetState,
    ProcessingProfile,
    Stage,
    StageStatus,
)
from squashvision.routes.jobs import _event_stream
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
from squashvision.worker import Worker


class ManualClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def migrate(engine: object, revision: str, *, downgrade: bool = False) -> None:
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if downgrade:
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)


def migration_engine(tmp_path: Path) -> object:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite3'}")
    Database._install_sqlite_pragmas(engine)
    return engine


def make_queue(
    tmp_path: Path,
    *,
    clock: ManualClock | None = None,
    stale_after: timedelta = timedelta(seconds=30),
) -> tuple[Database, LocalStorage, JobQueue]:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path / "storage")
    queue = JobQueue(
        database,
        storage,
        clock=clock or ManualClock(),
        stale_after=stale_after,
    )
    return database, storage, queue


def add_prepared_match(database: Database, name: str = "Match") -> str:
    with database.session() as session:
        match = Match(name=name)
        proxy = MediaAsset(
            match=match,
            kind=AssetKind.PROXY,
            relative_path=f"videos/proxy/{name.lower().replace(' ', '-')}.mp4",
        )
        session.add_all([match, proxy])
        session.flush()
        return match.public_id


def planned(*ranges: tuple[int, int]) -> list[PlannedChunk]:
    return [
        PlannedChunk(Stage.CALIBRATION, TimeRange(start, end))
        for start, end in ranges
    ]


def claimed_plan_with_checkpoint_files(
    database: Database,
    storage: LocalStorage,
    queue: JobQueue,
    *ranges: tuple[int, int],
) -> tuple[str, str, str, dict[tuple[int, int], tuple[Path, Path]]]:
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    claimed = queue.claim("worker-a")
    assert claimed is not None
    assert claimed.public_id == job.public_id
    assert claimed.claim_token is not None
    queue.plan_claimed(
        job.public_id,
        "worker-a",
        claimed.claim_token,
        [
            PlannedChunk(
                Stage.CALIBRATION,
                TimeRange(start_us, end_us),
                input_hash="1" * 64,
                artifact_schema_version=1,
            )
            for start_us, end_us in ranges
        ],
    )
    checkpoint_paths: dict[tuple[int, int], tuple[Path, Path]] = {}
    with database.session() as session:
        rows = session.scalars(
            select(JobChunk)
            .where(JobChunk.analysis_job_id == job.id)
            .order_by(JobChunk.chunk_index)
        ).all()
        for row in rows:
            artifact_relative = (
                Path("checkpoints")
                / job.public_id
                / row.stage.value
                / f"{row.start_us}-{row.end_us}.bin"
            )
            payload_relative = artifact_relative.with_suffix(".payload.json")
            artifact = storage.root / artifact_relative
            payload = storage.root / payload_relative
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"artifact")
            payload.write_bytes(b"payload")
            row.status = StageStatus.COMPLETED
            row.artifact_path = str(artifact_relative)
            row.artifact_size = len(b"artifact")
            row.artifact_sha256 = hashlib.sha256(b"artifact").hexdigest()
            row.artifact_payload_path = str(payload_relative)
            row.artifact_payload_size = len(b"payload")
            row.artifact_payload_sha256 = hashlib.sha256(b"payload").hexdigest()
            checkpoint_paths[(row.start_us, row.end_us)] = (
                artifact_relative,
                payload_relative,
            )
    return (
        job.public_id,
        "worker-a",
        claimed.claim_token,
        checkpoint_paths,
    )


def test_time_range_and_canonical_enums_are_exact() -> None:
    assert [member.value for member in ProcessingProfile] == [
        "fast",
        "balanced",
        "maximum",
    ]
    assert [member.value for member in JobStatus] == [
        "queued",
        "running",
        "paused",
        "completed",
        "failed",
        "cancelled",
    ]
    assert [member.value for member in StageStatus] == [
        "pending",
        "running",
        "completed",
        "failed",
        "invalidated",
    ]
    assert [member.value for member in Stage] == [
        "prepare",
        "calibration",
        "players",
        "ball",
        "events",
        "classification",
        "report",
    ]
    assert TimeRange(0, 1) == TimeRange(start_us=0, end_us=1)
    with pytest.raises(ValueError):
        TimeRange(-1, 1)
    with pytest.raises(ValueError):
        TimeRange(1, 1)


def test_migration_upgrades_populated_0002_queue_states(tmp_path: Path) -> None:
    engine = migration_engine(tmp_path)
    migrate(engine, "0002")
    now = "2026-08-25 12:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO matches "
                "(id, public_id, created_at, name) "
                "VALUES (1, 'match-old', :now, 'Old match')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO media_assets "
                "(id, public_id, created_at, match_id, kind, relative_path) "
                "VALUES (1, 'asset-old', :now, 1, 'proxy', 'videos/proxy/old.mp4')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO analysis_jobs "
                "(id, public_id, created_at, match_id, source_media_asset_id, "
                "status, updated_at) "
                "VALUES (1, 'job-old', :now, 1, 1, 'succeeded', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO job_chunks "
                "(id, public_id, created_at, analysis_job_id, chunk_index, status) "
                "VALUES "
                "(1, 'chunk-queued', :now, 1, 0, 'queued'), "
                "(2, 'chunk-succeeded', :now, 1, 1, 'succeeded')"
            ),
            {"now": now},
        )

    migrate(engine, "0003")

    with engine.connect() as connection:
        job = connection.execute(
            text(
                "SELECT status, processing_profile, claim_token "
                "FROM analysis_jobs WHERE id = 1"
            )
        ).one()
        chunks = connection.execute(
            text("SELECT status FROM job_chunks ORDER BY chunk_index")
        ).scalars().all()
    assert job == ("completed", "balanced", None)
    assert chunks == ["pending", "completed"]



def test_final_integrity_migration_separates_timestamp_maps_and_backfills_taxonomy(
    tmp_path: Path,
) -> None:
    engine = migration_engine(tmp_path)
    migrate(engine, "0012")
    now = "2026-08-30 12:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO matches "
                "(id, public_id, created_at, name, deletion_state, deletion_version) "
                "VALUES (1, 'match-final', :now, 'Final migration', 'active', 0)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO media_assets "
                "(id, public_id, created_at, match_id, kind, relative_path) VALUES "
                "(1, 'map-old', :now, 1, 'export', 'exports/legacy-map.json'), "
                "(2, 'zip-old', :now, 1, 'export', 'exports/report.zip')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO shots "
                "(id, public_id, created_at, match_id, prediction_revision, "
                "prediction_id, frame_index, source_timestamp_us, "
                "source_evidence_ids, kind, is_volley, outcome, review_required, "
                "classification_payload, review_status, evidence_provenance) "
                "VALUES (1, 'shot-old', :now, 1, 1, 'shot-old', 1, 1000, "
                "'[]', 'drive', 0, 'continuation', 0, '{}', 'not_required', "
                "'unavailable')"
            ),
            {"now": now},
        )

    migrate(engine, "head")

    with engine.connect() as connection:
        assets = connection.execute(
            text("SELECT public_id, kind FROM media_assets ORDER BY id")
        ).all()
        outcome = connection.execute(
            text("SELECT outcome FROM shots WHERE id = 1")
        ).scalar_one()
        media_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'media_assets'"
            )
        ).scalar_one()
        shot_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'shots'"
            )
        ).scalar_one()
        player_columns = {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(player_tracks)")
            ).all()
        }
    assert assets == [("map-old", "timestamp_map"), ("zip-old", "export")]
    assert outcome == "in_play"
    assert "timestamp_map" in media_sql
    assert "serve" in shot_sql and "kill" in shot_sql
    assert {
        "position_covariance",
        "position_uncertainty_m",
        "position_provenance",
        "position_unavailable_reason",
    } <= player_columns
    media_columns = {
        column["name"] for column in inspect(engine).get_columns("media_assets")
    }
    assert "timestamp_index_size" in media_columns

def test_migration_downgrades_populated_new_queue_states(tmp_path: Path) -> None:
    engine = migration_engine(tmp_path)
    migrate(engine, "0003")
    now = "2026-08-25 12:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO matches "
                "(id, public_id, created_at, name) "
                "VALUES (1, 'match-new', :now, 'New match')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO media_assets "
                "(id, public_id, created_at, match_id, kind, relative_path) "
                "VALUES (1, 'asset-new', :now, 1, 'proxy', 'videos/proxy/new.mp4')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO analysis_jobs "
                "(id, public_id, created_at, match_id, source_media_asset_id, "
                "processing_profile, status, claim_token, version, updated_at) "
                "VALUES "
                "(1, 'job-new', :now, 1, 1, 'balanced', 'completed', "
                "'finished-token', 4, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO job_chunks "
                "(id, public_id, created_at, analysis_job_id, chunk_index, stage, "
                "start_us, end_us, status, updated_at) VALUES "
                "(1, 'chunk-pending', :now, 1, 0, 'calibration', 0, 10, "
                "'pending', :now), "
                "(2, 'chunk-completed', :now, 1, 1, 'calibration', 10, 20, "
                "'completed', :now), "
                "(3, 'chunk-invalid', :now, 1, 2, 'players', 0, 20, "
                "'invalidated', :now)"
            ),
            {"now": now},
        )

    migrate(engine, "0002", downgrade=True)

    with engine.connect() as connection:
        job_status = connection.execute(
            text("SELECT status FROM analysis_jobs WHERE id = 1")
        ).scalar_one()
        chunk_statuses = connection.execute(
            text("SELECT status FROM job_chunks ORDER BY chunk_index")
        ).scalars().all()
    assert job_status == "succeeded"
    assert chunk_statuses == ["queued", "succeeded", "failed"]
    assert "claim_token" not in {
        column["name"] for column in inspect(engine).get_columns("analysis_jobs")
    }


def test_enqueue_validates_match_and_rejects_duplicate_active_job(tmp_path: Path) -> None:
    database, _, queue = make_queue(tmp_path)
    with pytest.raises(MatchNotFoundError) as missing:
        queue.enqueue("missing", ProcessingProfile.BALANCED)
    assert missing.value.code == "match_not_found"

    match_id = add_prepared_match(database)
    first = queue.enqueue(match_id, ProcessingProfile.MAXIMUM)
    assert first.status is JobStatus.QUEUED
    assert first.processing_profile is ProcessingProfile.MAXIMUM

    with pytest.raises(ActiveJobConflictError) as duplicate:
        queue.enqueue(match_id, ProcessingProfile.FAST)
    assert duplicate.value.code == "active_job_exists"


def test_state_machine_allows_only_explicit_transitions(tmp_path: Path) -> None:
    database, _, queue = make_queue(tmp_path)
    match_id = add_prepared_match(database)
    job = queue.enqueue(match_id, ProcessingProfile.BALANCED)

    claimed = queue.claim("worker-a")
    assert claimed is not None and claimed.status is JobStatus.RUNNING
    queue.transition(job.public_id, JobStatus.FAILED)
    retried = queue.retry(job.public_id)
    assert retried.status is JobStatus.QUEUED
    queue.cancel(job.public_id)
    assert queue.get(job.public_id).status is JobStatus.CANCELLED
    assert queue.retry(job.public_id).status is JobStatus.QUEUED

    with pytest.raises(TransitionConflictError) as conflict:
        queue.transition(job.public_id, JobStatus.COMPLETED)
    assert conflict.value.code == "invalid_job_transition"
    assert conflict.value.current is JobStatus.QUEUED
    assert conflict.value.requested is JobStatus.COMPLETED


def test_retry_rejects_a_second_active_job_with_typed_conflict(
    tmp_path: Path,
) -> None:
    database, _, queue = make_queue(tmp_path)
    match_id = add_prepared_match(database)
    failed = queue.enqueue(match_id, ProcessingProfile.BALANCED)
    queue.claim("worker-a")
    queue.transition(failed.public_id, JobStatus.FAILED)
    queue.enqueue(match_id, ProcessingProfile.FAST)

    with pytest.raises(ActiveJobConflictError) as conflict:
        queue.retry(failed.public_id)

    assert conflict.value.code == "active_job_exists"
    assert queue.get(failed.public_id).status is JobStatus.FAILED


def test_two_real_sqlite_connections_cannot_double_claim(tmp_path: Path) -> None:
    database, storage, queue = make_queue(tmp_path)
    match_id = add_prepared_match(database)
    job = queue.enqueue(match_id, ProcessingProfile.FAST)
    second_queue = JobQueue(database, storage, clock=queue.clock)
    barrier = Barrier(2)

    def claim(candidate: tuple[JobQueue, str]) -> str | None:
        candidate_queue, worker_id = candidate
        barrier.wait(timeout=2)
        claimed = candidate_queue.claim(worker_id)
        return None if claimed is None else claimed.public_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed_ids = list(
            executor.map(claim, [(queue, "worker-a"), (second_queue, "worker-b")])
        )

    assert claimed_ids.count(job.public_id) == 1
    assert claimed_ids.count(None) == 1
    with database.session() as session:
        stored = session.scalar(
            select(AnalysisJob).where(AnalysisJob.public_id == job.public_id)
        )
        assert stored is not None
        assert stored.worker_id in {"worker-a", "worker-b"}


def test_stale_running_job_is_reclaimed_without_losing_verified_chunks(
    tmp_path: Path,
) -> None:
    clock = ManualClock()
    database, _, queue = make_queue(
        tmp_path, clock=clock, stale_after=timedelta(seconds=10)
    )
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    queue.claim("dead-worker")
    queue.plan(job.public_id, planned((0, 10), (10, 20)))
    artifact = tmp_path / "first.bin"
    artifact.write_bytes(b"verified")
    queue.checkpoint(
        job.public_id, Stage.CALIBRATION, TimeRange(0, 10), artifact
    )

    clock.advance(seconds=11)
    recovered = queue.claim("replacement")

    assert recovered is not None
    assert recovered.public_id == job.public_id
    assert recovered.worker_id == "replacement"
    next_chunk = queue.next_chunk(job.public_id)
    assert next_chunk is not None
    assert next_chunk.time_range == TimeRange(10, 20)


def test_worker_heartbeat_updates_only_at_five_second_interval(tmp_path: Path) -> None:
    clock = ManualClock()
    database, _, queue = make_queue(tmp_path, clock=clock)
    queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    queue.claim("worker-a")
    first = queue.heartbeat("worker-a")

    clock.advance(seconds=4.999)
    assert queue.heartbeat("worker-a") == first
    clock.advance(milliseconds=1)
    second = queue.heartbeat("worker-a")

    assert second == clock.now
    assert second > first
    assert queue.worker_is_healthy()


def test_pause_and_cancel_apply_only_at_worker_chunk_boundaries(tmp_path: Path) -> None:
    database, _, queue = make_queue(tmp_path)
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    queue.claim("worker-a")
    queue.plan(job.public_id, planned((0, 10)))
    queue.start_chunk(job.public_id, Stage.CALIBRATION, TimeRange(0, 10))

    requested = queue.pause(job.public_id)
    assert requested.status is JobStatus.RUNNING
    assert requested.requested_status is JobStatus.PAUSED
    assert queue.apply_requested_control(job.public_id).status is JobStatus.PAUSED

    queue.resume(job.public_id)
    queue.claim("worker-a")
    queue.start_chunk(job.public_id, Stage.CALIBRATION, TimeRange(0, 10))
    requested = queue.cancel(job.public_id)
    assert requested.status is JobStatus.RUNNING
    assert requested.requested_status is JobStatus.CANCELLED
    assert queue.apply_requested_control(job.public_id).status is JobStatus.CANCELLED


def test_verified_checkpoint_is_atomic_and_identical_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    database, storage, queue = make_queue(tmp_path)
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    queue.claim("worker-a")
    chunk_range = TimeRange(0, 10)
    queue.plan(job.public_id, planned((0, 10)))
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"checkpoint")

    queue.checkpoint(job.public_id, Stage.CALIBRATION, chunk_range, artifact)
    checkpoint = queue.find_chunk(job.public_id, Stage.CALIBRATION, chunk_range)
    assert checkpoint.status is StageStatus.COMPLETED
    assert checkpoint.artifact_size == len(b"checkpoint")
    assert checkpoint.artifact_sha256 == hashlib.sha256(b"checkpoint").hexdigest()
    published = storage.root / str(checkpoint.artifact_path)
    original_mtime = published.stat().st_mtime_ns

    queue.checkpoint(job.public_id, Stage.CALIBRATION, chunk_range, artifact)
    retried = queue.find_chunk(job.public_id, Stage.CALIBRATION, chunk_range)
    assert retried.status is StageStatus.COMPLETED
    assert published.stat().st_mtime_ns == original_mtime
    assert not list(published.parent.glob(f".{published.name}.*.tmp"))


def test_corrupt_or_mismatched_checkpoint_invalidates_chunk(tmp_path: Path) -> None:
    database, storage, queue = make_queue(tmp_path)
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    queue.claim("worker-a")
    chunk_range = TimeRange(0, 10)
    queue.plan(job.public_id, planned((0, 10)))
    first = tmp_path / "first.bin"
    first.write_bytes(b"first")
    queue.checkpoint(job.public_id, Stage.CALIBRATION, chunk_range, first)
    chunk = queue.find_chunk(job.public_id, Stage.CALIBRATION, chunk_range)
    published = storage.root / str(chunk.artifact_path)
    published.write_bytes(b"corrupt")

    with pytest.raises(CheckpointConflictError) as corrupt:
        queue.checkpoint(job.public_id, Stage.CALIBRATION, chunk_range, first)
    assert corrupt.value.code == "checkpoint_invalid"
    assert (
        queue.find_chunk(job.public_id, Stage.CALIBRATION, chunk_range).status
        is StageStatus.INVALIDATED
    )

    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"different")
    with pytest.raises(CheckpointConflictError):
        queue.checkpoint(job.public_id, Stage.CALIBRATION, chunk_range, replacement)
    assert (
        queue.find_chunk(job.public_id, Stage.CALIBRATION, chunk_range).status
        is StageStatus.INVALIDATED
    )


def test_reconcile_plan_removes_invalidated_and_obsolete_files_only_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, storage, queue = make_queue(tmp_path)
    job_id, worker_id, claim_token, checkpoint_paths = (
        claimed_plan_with_checkpoint_files(
            database, storage, queue, (0, 10), (10, 20)
        )
    )
    removed: list[Path] = []
    original_remove = storage.remove_owned_tree

    def remove_after_commit(
        relative: Path, *, owned_paths: set[Path]
    ) -> None:
        with database.session() as session:
            retained = session.scalar(
                select(JobChunk).where(
                    JobChunk.start_us == 0,
                    JobChunk.end_us == 10,
                )
            )
            obsolete = session.scalar(
                select(JobChunk).where(
                    JobChunk.start_us == 10,
                    JobChunk.end_us == 20,
                )
            )
            assert retained is not None
            assert retained.artifact_path is None
            assert retained.artifact_payload_path is None
            assert obsolete is None
        assert owned_paths == {relative}
        removed.append(relative)
        original_remove(relative, owned_paths=owned_paths)

    monkeypatch.setattr(storage, "remove_owned_tree", remove_after_commit)

    reconciled = queue.reconcile_plan_claimed(
        job_id,
        worker_id,
        claim_token,
        [
            PlannedChunk(
                Stage.CALIBRATION,
                TimeRange(0, 10),
                input_hash="2" * 64,
                artifact_schema_version=1,
            )
        ],
    )

    expected_paths = {
        path for pair in checkpoint_paths.values() for path in pair
    }
    assert len(reconciled) == 1
    assert reconciled[0].status is StageStatus.INVALIDATED
    assert set(removed) == expected_paths
    assert all(not (storage.root / path).exists() for path in expected_paths)


def test_reconcile_chunk_rollback_preserves_db_ownership_and_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, storage, queue = make_queue(tmp_path)
    job_id, worker_id, claim_token, checkpoint_paths = (
        claimed_plan_with_checkpoint_files(
            database, storage, queue, (0, 10)
        )
    )
    artifact_relative, payload_relative = checkpoint_paths[(0, 10)]
    removed: list[Path] = []
    monkeypatch.setattr(
        storage,
        "remove_owned_tree",
        lambda relative, *, owned_paths: removed.append(relative),
    )

    def force_rollback(_job: AnalysisJob) -> None:
        raise RuntimeError("forced transaction rollback")

    monkeypatch.setattr(queue, "_touch", force_rollback)

    with pytest.raises(RuntimeError, match="forced transaction rollback"):
        queue.reconcile_chunk_claimed(
            job_id,
            worker_id,
            claim_token,
            PlannedChunk(
                Stage.CALIBRATION,
                TimeRange(0, 10),
                input_hash="2" * 64,
                artifact_schema_version=1,
            ),
        )

    with database.session() as session:
        row = session.scalar(
            select(JobChunk).where(
                JobChunk.start_us == 0,
                JobChunk.end_us == 10,
            )
        )
        assert row is not None
        assert row.status is StageStatus.COMPLETED
        assert row.artifact_path == str(artifact_relative)
        assert row.artifact_payload_path == str(payload_relative)
    assert removed == []
    assert (storage.root / artifact_relative).read_bytes() == b"artifact"
    assert (storage.root / payload_relative).read_bytes() == b"payload"


def test_reconcile_chunk_cleanup_failure_does_not_hide_committed_invalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, storage, queue = make_queue(tmp_path)
    job_id, worker_id, claim_token, checkpoint_paths = (
        claimed_plan_with_checkpoint_files(
            database, storage, queue, (0, 10)
        )
    )
    cleanup_attempted = False

    def fail_cleanup(
        _relative: Path, *, owned_paths: set[Path]
    ) -> None:
        nonlocal cleanup_attempted
        cleanup_attempted = True
        raise OSError("forced cleanup failure")

    monkeypatch.setattr(storage, "remove_owned_tree", fail_cleanup)

    reconciled = queue.reconcile_chunk_claimed(
        job_id,
        worker_id,
        claim_token,
        PlannedChunk(
            Stage.CALIBRATION,
            TimeRange(0, 10),
            input_hash="2" * 64,
            artifact_schema_version=1,
        ),
    )

    assert cleanup_attempted
    assert reconciled.status is StageStatus.INVALIDATED
    with database.session() as session:
        row = session.scalar(
            select(JobChunk).where(
                JobChunk.start_us == 0,
                JobChunk.end_us == 10,
            )
        )
        assert row is not None
        assert row.artifact_path is None
        assert row.artifact_payload_path is None
    assert all(
        (storage.root / path).exists()
        for path in checkpoint_paths[(0, 10)]
    )


def test_restart_selects_first_missing_chunk_and_skips_verified_chunks(
    tmp_path: Path,
) -> None:
    database, _, queue = make_queue(tmp_path)
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    queue.claim("worker-a")
    queue.plan(
        job.public_id,
        [
            PlannedChunk(Stage.CALIBRATION, TimeRange(0, 10)),
            PlannedChunk(Stage.CALIBRATION, TimeRange(10, 20)),
            PlannedChunk(Stage.PLAYERS, TimeRange(0, 20)),
        ],
    )
    artifact = tmp_path / "done.bin"
    artifact.write_bytes(b"done")
    queue.checkpoint(
        job.public_id, Stage.CALIBRATION, TimeRange(0, 10), artifact
    )

    restarted = JobQueue(database, queue.storage, clock=queue.clock)
    next_chunk = restarted.next_chunk(job.public_id)

    assert next_chunk is not None
    assert next_chunk.stage is Stage.CALIBRATION
    assert next_chunk.time_range == TimeRange(10, 20)


class RecordingHandler:
    def __init__(self, ranges: list[PlannedChunk]) -> None:
        self.ranges = ranges
        self.calls: list[tuple[Stage, TimeRange]] = []

    def plan(self, _job: AnalysisJob) -> list[PlannedChunk]:
        return self.ranges

    def run(
        self,
        _job: AnalysisJob,
        stage: Stage,
        chunk: TimeRange,
        artifact: Path,
    ) -> Path:
        self.calls.append((stage, chunk))
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(f"{stage.value}:{chunk.start_us}-{chunk.end_us}".encode())
        return artifact


class BlockingHandler(RecordingHandler):
    def __init__(self, entered: Event, release: Event) -> None:
        super().__init__(planned((0, 10)))
        self.entered = entered
        self.release = release

    def run(
        self,
        job: AnalysisJob,
        stage: Stage,
        chunk: TimeRange,
        artifact: Path,
    ) -> Path:
        self.entered.set()
        assert self.release.wait(timeout=2)
        return super().run(job, stage, chunk, artifact)


def test_worker_renews_claim_while_planner_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = ManualClock()
    database, storage, queue = make_queue(
        tmp_path, clock=clock, stale_after=timedelta(seconds=10)
    )
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    entered = Event()
    release = Event()
    tick = Event()
    observed = Event()

    class BlockingPlanner(RecordingHandler):
        def plan(self, current: AnalysisJob) -> list[PlannedChunk]:
            entered.set()
            assert release.wait(timeout=2)
            return super().plan(current)

    def controlled_wait(stop: Event, _seconds: float) -> bool:
        while not stop.is_set():
            if tick.wait(timeout=0.01):
                tick.clear()
                return False
        return True
    original_heartbeat = queue.heartbeat_claim

    def recording_heartbeat(
        job_id: str, worker_id: str, claim_token: str
    ) -> datetime:
        result = original_heartbeat(job_id, worker_id, claim_token)
        observed.set()
        return result

    monkeypatch.setattr(queue, "heartbeat_claim", recording_heartbeat)

    worker = Worker(
        queue,
        "worker-a",
        BlockingPlanner(planned((0, 10))),
        clock=clock,
        heartbeat_wait=controlled_wait,
    )
    replacement_queue = JobQueue(
        database, storage, clock=clock, stale_after=timedelta(seconds=10)
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(worker.run_once)
        assert entered.wait(timeout=2)
        observed.clear()
        clock.advance(seconds=5)
        tick.set()
        assert observed.wait(timeout=2)
        clock.advance(seconds=6)
        assert replacement_queue.claim("worker-b") is None
        release.set()
        assert running.result(timeout=2)


def test_worker_renews_claim_every_five_seconds_during_blocking_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = ManualClock()
    database, _, queue = make_queue(
        tmp_path, clock=clock, stale_after=timedelta(seconds=10)
    )
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    entered = Event()
    release = Event()
    tick = Event()
    observed = Event()
    handler = BlockingHandler(entered, release)
    def controlled_wait(stop: Event, _seconds: float) -> bool:
        while not stop.is_set():
            if tick.wait(timeout=0.01):
                tick.clear()
                return False
        return True

    original_heartbeat = queue.heartbeat_claim

    def recording_heartbeat(
        job_id: str, worker_id: str, claim_token: str
    ) -> datetime:
        result = original_heartbeat(job_id, worker_id, claim_token)
        observed.set()
        return result

    monkeypatch.setattr(queue, "heartbeat_claim", recording_heartbeat)
    worker = Worker(
        queue,
        "worker-a",
        handler,
        clock=clock,
        heartbeat_wait=controlled_wait,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(worker.run_once)
        assert entered.wait(timeout=2)
        observed.clear()
        clock.advance(seconds=5)
        tick.set()
        assert observed.wait(timeout=2)
        assert queue.get(job.public_id).heartbeat_at == clock.now
        clock.advance(seconds=6)
        assert queue.claim("worker-b") is None
        release.set()
        assert running.result(timeout=2)


def test_stale_owner_cannot_checkpoint_or_fail_after_reclaim(tmp_path: Path) -> None:
    clock = ManualClock()
    database, storage, queue = make_queue(
        tmp_path, clock=clock, stale_after=timedelta(seconds=10)
    )
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    entered = Event()
    release = Event()
    handler = BlockingHandler(entered, release)

    def wait_until_stopped(stop: Event, _seconds: float) -> bool:
        stop.wait(timeout=2)
        return True

    worker = Worker(
        queue,
        "worker-a",
        handler,
        clock=clock,
        heartbeat_wait=wait_until_stopped,
    )
    replacement_queue = JobQueue(
        database, storage, clock=clock, stale_after=timedelta(seconds=10)
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        abandoned = executor.submit(worker.run_once)
        assert entered.wait(timeout=2)
        clock.advance(seconds=11)
        replacement = replacement_queue.claim("worker-b")
        assert replacement is not None
        release.set()
        with pytest.raises(ClaimLostError):
            abandoned.result(timeout=2)

    current = replacement_queue.get(job.public_id)
    assert current.status is JobStatus.RUNNING
    assert current.worker_id == "worker-b"
    assert replacement_queue.next_chunk(job.public_id) == PlannedChunk(
        Stage.CALIBRATION, TimeRange(0, 10)
    )


def test_worker_clears_lost_claim_and_can_claim_other_work(tmp_path: Path) -> None:
    clock = ManualClock()
    database, storage, queue = make_queue(
        tmp_path, clock=clock, stale_after=timedelta(seconds=10)
    )
    first = queue.enqueue(
        add_prepared_match(database, "First"), ProcessingProfile.BALANCED
    )
    worker = Worker(
        queue,
        "worker-a",
        RecordingHandler(planned((0, 10), (10, 20))),
        clock=clock,
    )
    assert worker.run_once()

    clock.advance(seconds=11)
    replacement_queue = JobQueue(
        database, storage, clock=clock, stale_after=timedelta(seconds=10)
    )
    replacement = replacement_queue.claim("worker-b")
    assert replacement is not None
    assert replacement.public_id == first.public_id
    second = queue.enqueue(
        add_prepared_match(database, "Second"), ProcessingProfile.FAST
    )

    with pytest.raises(ClaimLostError):
        worker.run_once()
    assert worker.run_once()

    claimed_second = queue.get(second.public_id)
    assert claimed_second.status is JobStatus.RUNNING
    assert claimed_second.worker_id == "worker-a"


@pytest.mark.parametrize(
    ("operation", "expected"),
    [("pause", JobStatus.PAUSED), ("cancel", JobStatus.CANCELLED)],
)
def test_stale_reclaim_preserves_control_request_before_planning(
    tmp_path: Path, operation: str, expected: JobStatus
) -> None:
    clock = ManualClock()
    database, _, queue = make_queue(
        tmp_path, clock=clock, stale_after=timedelta(seconds=10)
    )
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)
    queue.claim("dead-worker")
    getattr(queue, operation)(job.public_id)
    clock.advance(seconds=11)

    class PlanningMustNotRun(RecordingHandler):
        def plan(self, _job: AnalysisJob) -> list[PlannedChunk]:
            raise AssertionError("requested control must apply before planning")

    worker = Worker(queue, "replacement", PlanningMustNotRun([]), clock=clock)
    assert worker.run_once()
    assert queue.get(job.public_id).status is expected


def test_worker_uses_injected_handler_and_completes_real_queue_lifecycle(
    tmp_path: Path,
) -> None:
    clock = ManualClock()
    database, _, queue = make_queue(tmp_path, clock=clock)
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.FAST)
    handler = RecordingHandler(planned((0, 10), (10, 20)))
    worker = Worker(queue, "worker-a", handler, clock=clock)

    assert worker.run_once()
    clock.advance(seconds=5)
    assert worker.run_once()
    clock.advance(seconds=5)
    assert worker.run_once()

    finished = queue.get(job.public_id)
    assert finished.status is JobStatus.COMPLETED
    assert handler.calls == [
        (Stage.CALIBRATION, TimeRange(0, 10)),
        (Stage.CALIBRATION, TimeRange(10, 20)),
    ]
    assert finished.heartbeat_at == clock.now


@pytest.mark.asyncio
async def test_job_routes_return_typed_errors_and_truthful_progress(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    match_id = add_prepared_match(app.state.database)
    app.state.model_manifest.states = lambda: [
        SimpleNamespace(
            name="pose",
            required=True,
            state=ModelAssetState.READY,
        ),
        SimpleNamespace(
            name="ball",
            required=True,
            state=ModelAssetState.READY,
        ),
    ]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.post(
            "/api/v1/matches/missing/jobs", json={"profile": "balanced"}
        )
        started = await client.post(
            f"/api/v1/matches/{match_id}/jobs", json={"profile": "balanced"}
        )
        duplicate = await client.post(
            f"/api/v1/matches/{match_id}/jobs", json={"profile": "fast"}
        )
        job_id = started.json()["id"]
        invalid = await client.post(f"/api/v1/jobs/{job_id}/resume")
        detail = await client.get(f"/api/v1/jobs/{job_id}")

    assert missing.status_code == 404
    assert missing.json()["code"] == "match_not_found"
    assert started.status_code == 201
    assert started.json()["state"] == "queued"
    assert started.json()["progress"] is None
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "active_job_exists"
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "invalid_job_transition"
    assert detail.json()["version"] >= 1
    assert detail.json()["ballInputMode"] == "original"


@pytest.mark.asyncio
async def test_ball_input_mode_is_validated_persisted_and_retained_when_paused(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    match_id = add_prepared_match(app.state.database)
    app.state.model_manifest.states = lambda: []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post(f"/api/v1/matches/{match_id}/jobs",
            json={"profile": "maximum", "ballInputMode": "automatic"})
        assert invalid.status_code == 422
        sparse_pose = await client.post(f"/api/v1/matches/{match_id}/jobs",
            json={"profile": "fast", "ballInputMode": "inverted"})
        assert sparse_pose.status_code == 422
        started = await client.post(f"/api/v1/matches/{match_id}/jobs",
            json={"profile": "maximum", "ballInputMode": "inverted"})
        assert started.status_code == 201
        job_id = started.json()["id"]
        assert started.json()["ballInputMode"] == "inverted"
        assert app.state.job_queue.get(job_id).ball_input_mode is BallInputMode.INVERTED
        paused = await client.post(f"/api/v1/jobs/{job_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["ballInputMode"] == "inverted"
        detail = await client.get(f"/api/v1/jobs/{job_id}")
        assert detail.json()["ballInputMode"] == "inverted"


def test_ball_input_migration_preserves_historical_jobs_as_original(tmp_path: Path) -> None:
    database, _, queue = make_queue(tmp_path)
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.MAXIMUM)
    migrate(database.engine, "0014", downgrade=True)
    migrate(database.engine, "head")
    restored = queue.get(job.public_id)
    assert restored.ball_input_mode is BallInputMode.ORIGINAL
    assert restored.processing_profile is ProcessingProfile.MAXIMUM
    assert restored.status is JobStatus.QUEUED


@pytest.mark.asyncio
async def test_sse_has_content_type_versioned_snapshot_and_terminal_end(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    match_id = add_prepared_match(app.state.database)
    job = app.state.job_queue.enqueue(match_id, ProcessingProfile.BALANCED)
    app.state.job_queue.cancel(job.public_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/jobs/{job.public_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: job.snapshot" in response.text
    assert '"version":' in response.text
    assert '"state":"cancelled"' in response.text


@pytest.mark.asyncio
async def test_sse_stops_on_disconnect_and_bounds_database_polling(
    tmp_path: Path,
) -> None:
    database, _, queue = make_queue(tmp_path)
    job = queue.enqueue(add_prepared_match(database), ProcessingProfile.BALANCED)

    class DisconnectingRequest:
        def __init__(self) -> None:
            self.checks = 0

        async def is_disconnected(self) -> bool:
            self.checks += 1
            return self.checks >= 2

    request = DisconnectingRequest()
    stream = _event_stream(
        request, queue, job.public_id, poll_seconds=0.01, heartbeat_seconds=0.01
    )
    first = await anext(stream)
    assert "event: job.snapshot" in first
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=0.1)
    assert request.checks == 2
    assert queue.poll_count <= 2


@pytest.mark.asyncio
async def test_health_reads_real_durable_worker_heartbeat(tmp_path: Path) -> None:
    clock = ManualClock()
    app = create_app(Settings(data_dir=tmp_path))
    queue = JobQueue(
        app.state.database,
        app.state.storage,
        clock=clock,
        stale_after=timedelta(seconds=10),
    )
    app.state.job_queue = queue

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        unavailable = await client.get("/api/v1/health")
        queue.heartbeat("worker-a")
        ready = await client.get("/api/v1/health")
        clock.advance(seconds=11)
        stale = await client.get("/api/v1/health")

    assert unavailable.json()["worker"]["status"] == "unavailable"
    assert ready.json()["worker"]["status"] == "ready"
    assert stale.json()["worker"]["status"] == "unavailable"
