from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))

from squashvision.app import create_app
import squashvision.routes.analysis as analysis_routes
import squashvision.routes.matches as matches_routes
from squashvision.pipeline import canonical_hash
from squashvision.analytics import build_report
from squashvision.media import MediaError
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    Correction,
    CorrectionStatus,
    ErrorCandidate,
    ErrorKind,
    JobChunk,
    JobStatus,
    Match,
    MediaAsset,
    ModelAssetState,
    PendingDeletion,
    PlayerSlot,
    ProcessingProfile,
    Rally,
    ReportRevision,
    Shot,
    ShotKind,
    Stage,
    StageStatus,
    StagePublication,
)
from squashvision.storage import LocalStorage
from squashvision.settings import Settings


SAFE_REQUEST_ID = "request-123"


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, min_free_disk_bytes=0)


def _seed_match(app: object, *, title: str = "Final") -> tuple[str, str]:
    storage = app.state.storage
    original = storage.root / "videos/original/original.mp4"
    proxy = storage.root / "videos/proxy/proxy.mp4"
    original.parent.mkdir(parents=True, exist_ok=True)
    proxy.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"original")
    proxy.write_bytes(b"proxy")
    with app.state.database.session() as session:
        match = Match(name=title, player_a_name="A", player_b_name="B", score="3-1")
        source = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path="videos/original/original.mp4",
            checksum_sha256=hashlib.sha256(b"original").hexdigest(),
            byte_size=8,
            duration_us=180_000_000,
        )
        prepared = MediaAsset(
            match=match,
            kind=AssetKind.PROXY,
            relative_path="videos/proxy/proxy.mp4",
            checksum_sha256=hashlib.sha256(b"proxy").hexdigest(),
            byte_size=5,
            duration_us=180_000_000,
        )
        session.add_all([match, source, prepared])
        session.flush()
        return match.public_id, prepared.public_id


def _ready_models(app: object) -> None:
    app.state.model_manifest.states = lambda: [
        SimpleNamespace(name="pose", required=True, state=ModelAssetState.READY),
        SimpleNamespace(name="ball", required=True, state=ModelAssetState.READY),
    ]


def _seed_completed_analysis(app: object, match_id: str) -> tuple[str, int]:
    storage = app.state.storage
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        proxy = session.scalar(
            select(MediaAsset).where(
                MediaAsset.match_id == match.id, MediaAsset.kind == AssetKind.PROXY
            )
        )
        assert proxy is not None
        job = AnalysisJob(
            match=match,
            source_media_asset=proxy,
            processing_profile=ProcessingProfile.BALANCED,
            status=JobStatus.COMPLETED,
            version=3,
        )
        report = ReportRevision(
            match=match,
            revision=2,
            prediction_revision=7,
            calibration_revision=None,
            schema_version=1,
            sections={
                name: {
                    "schemaVersion": 1,
                    "payload": {"quality": "good"} if name == "overview" else {"availability": {"available": False, "reason": "fixture_not_built"}},
                    "evidenceIds": [],
                    "hash": "a" * 64 if name == "overview" else name.ljust(64, "0")[:64],
                    "dependencyHash": "b" * 64 if name == "overview" else name.ljust(64, "1")[:64],
                }
                for name in ("overview", "shots", "rallies", "movement", "errors", "trajectory", "head_to_head", "coaching", "review")
            },
            section_hashes={name: ("a" * 64 if name == "overview" else name.ljust(64, "0")[:64]) for name in ("overview", "shots", "rallies", "movement", "errors", "trajectory", "head_to_head", "coaching", "review")},
            dependency_hashes={name: ("b" * 64 if name == "overview" else name.ljust(64, "1")[:64]) for name in ("overview", "shots", "rallies", "movement", "errors", "trajectory", "head_to_head", "coaching", "review")},
        )
        session.add_all([job, report])
        session.flush()
        job_id = job.public_id
        internal_match_id = match.id

    checkpoint = storage.root / "checkpoints" / job_id
    historical = storage.root / "checkpoints" / "historical"
    checkpoint.mkdir(parents=True, exist_ok=True)
    historical.mkdir(parents=True, exist_ok=True)
    players_path = checkpoint / "players.parquet"
    ball_path = checkpoint / "ball.parquet"
    keypoints_x = [[float(index) for index in range(17)] for _ in range(3)]
    keypoints_y = [[float(index + 1) for index in range(17)] for _ in range(3)]
    keypoints_confidence = [[0.9 for _ in range(17)] for _ in range(3)]
    candidate = {
        "x": 10.0,
        "y": 20.0,
        "peak_probability": 0.9,
        "integrated_probability": 0.9,
        "area": 2,
        "circularity": 0.8,
        "covariance_xx": 4.0,
        "covariance_xy": 0.0,
        "covariance_yx": 0.0,
        "covariance_yy": 9.0,
    }
    old_players_path = historical / "players.parquet"
    pq.write_table(
        pa.table(
            {
                "player_id": ["A", "B", "A"],
                "timestamp_us": [1_000_000, 2_000_000, 3_000_000],
                "source_timestamp_us": [1_000_000, 2_000_000, 3_000_000],
                "source_frame_index": [1, 2, 3],
                "box_x1": [1.0, 2.0, 3.0],
                "box_y1": [1.0, 2.0, 3.0],
                "box_x2": [4.0, 5.0, 6.0],
                "box_y2": [4.0, 5.0, 6.0],
                "keypoints_x": keypoints_x,
                "keypoints_y": keypoints_y,
                "keypoints_confidence": keypoints_confidence,
                "detection_confidence": [0.9, 0.8, 0.7],
                "feet_x": [2.0, 3.0, 4.0],
                "feet_y": [4.0, 5.0, 6.0],
                "feet_uncertainty_px": [0.1, 0.1, 0.1],
                "evidence": ["observed", "observed", "observed"],
                "evidence_start_timestamp_us": [1_000_000, 2_000_000, 3_000_000],
                "evidence_end_timestamp_us": [1_000_000, 2_000_000, 3_000_000],
                "evidence_start_frame_index": [1, 2, 3],
                "evidence_end_frame_index": [1, 2, 3],
                "association_confidence": [0.9, 0.8, 0.7],
                "ambiguous": [False, False, False],
                "ambiguity_reason": [None, None, None],
                "floor_x_m": [1.0, None, 2.0],
                "floor_y_m": [2.0, None, 3.0],
                "floor_uncertainty_m": [0.1, None, 0.2],
                "calibration_revision": ["1", None, "1"],
                "calibration_provenance": ["manual", None, "manual"],
                "source_manifest_id": ["current-source"] * 3,
                "model_manifest_id": ["current-pose"] * 3,
            }
        ),
        players_path,
    )
    pq.write_table(
        pa.table(
            {
                "timestamp_us": [1_000_000, 2_000_000, 3_000_000],
                "source_timestamp_us": [1_000_000, 2_000_000, 3_000_000],
                "source_frame_index": [1, 2, 3],
                "source_width": [1280] * 3,
                "source_height": [720] * 3,
                "x": [10.0, None, 30.0],
                "y": [20.0, None, 40.0],
                "probability": [0.9, 0.0, 0.8],
                "covariance": [
                    {"xx": 4.0, "xy": 0.0, "yx": 0.0, "yy": 9.0},
                    None,
                    {"xx": 9.0, "xy": 0.0, "yx": 0.0, "yy": 16.0},
                ],
                "candidates": [
                    [candidate, None, None, None, None],
                    [None, None, None, None, None],
                    [{**candidate, "x": 30.0, "y": 40.0}, None, None, None, None],
                ],
                "visible": [True, False, True],
                "candidate_count": [1, 0, 1],
                "evidence": ["observed", "observed", "observed"],
                "evidence_start_timestamp_us": [1_000_000, 2_000_000, 3_000_000],
                "evidence_end_timestamp_us": [1_000_000, 2_000_000, 3_000_000],
                "evidence_start_frame_index": [1, 2, 3],
                "evidence_end_frame_index": [1, 2, 3],
                "ambiguous": [False, False, False],
                "ambiguity_reason": [None, None, None],
                "segment_id": ["s1", None, "s1"],
                "source_manifest_id": ["current-source"] * 3,
                "model_manifest_id": ["current-ball"] * 3,
                "device": ["cpu"] * 3,
                "device_fallback": [False] * 3,
            }
        ),
        ball_path,
    )
    historical_table = pq.read_table(players_path)
    source_column = historical_table.schema.get_field_index("source_manifest_id")
    historical_table = historical_table.set_column(
        source_column,
        "source_manifest_id",
        pa.array(["historical-source"] * historical_table.num_rows),
    )
    pose_column = historical_table.schema.get_field_index("model_manifest_id")
    historical_table = historical_table.set_column(
        pose_column,
        "model_manifest_id",
        pa.array(["historical-pose"] * historical_table.num_rows),
    )
    pq.write_table(historical_table, old_players_path)

    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        current_job = session.scalar(
            select(AnalysisJob).where(AnalysisJob.public_id == job_id)
        )
        assert match is not None and current_job is not None
        historical_job = AnalysisJob(
            match=match,
            source_media_asset=current_job.source_media_asset,
            processing_profile=ProcessingProfile.FAST,
            status=JobStatus.COMPLETED,
            version=2,
        )
        session.add(historical_job)
        session.flush()
        historical_job.created_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        session.add_all(
            [
                StagePublication(
                    match_id=match.id,
                    analysis_job_id=current_job.id,
                    stage=Stage.CLASSIFICATION,
                    input_hash="7" * 64,
                    worker_id="current-worker",
                    claim_token="11111111-1111-1111-1111-111111111111",
                    prediction_revision=7,
                ),
                StagePublication(
                    match_id=match.id,
                    analysis_job_id=historical_job.id,
                    stage=Stage.CLASSIFICATION,
                    input_hash="6" * 64,
                    worker_id="historical-worker",
                    claim_token="22222222-2222-2222-2222-222222222222",
                    prediction_revision=6,
                ),
            ]
        )
        session.add_all(
            [
                JobChunk(
                    analysis_job=current_job,
                    chunk_index=1,
                    stage=Stage.PLAYERS,
                    start_us=0,
                    end_us=10_000_000,
                    status=StageStatus.COMPLETED,
                    artifact_path=str(players_path.relative_to(storage.root)),
                    artifact_payload_path=str(players_path.relative_to(storage.root)),
                    artifact_availability="available",
                ),
                JobChunk(
                    analysis_job=current_job,
                    chunk_index=2,
                    stage=Stage.BALL,
                    start_us=0,
                    end_us=10_000_000,
                    status=StageStatus.COMPLETED,
                    artifact_path=str(ball_path.relative_to(storage.root)),
                    artifact_payload_path=str(ball_path.relative_to(storage.root)),
                    artifact_availability="available",
                ),
                JobChunk(
                    analysis_job=historical_job,
                    chunk_index=1,
                    stage=Stage.PLAYERS,
                    start_us=0,
                    end_us=10_000_000,
                    status=StageStatus.COMPLETED,
                    artifact_path=str(old_players_path.relative_to(storage.root)),
                    artifact_payload_path=str(old_players_path.relative_to(storage.root)),
                    artifact_availability="available",
                ),
                Shot(
                    match=match,
                    prediction_revision=7,
                    prediction_id="shot-1",
                    frame_index=20,
                    source_timestamp_us=1_000_000,
                    source_evidence_ids=["ball-1"],
                    hitter=PlayerSlot.NEAR,
                    kind=ShotKind.DRIVE,
                    review_required=True,
                    classification_payload={
                        "confidence": 0.4,
                        "required_probability": 0.65,
                        "probabilities": {"drive": 0.4, "unknown": 0.6},
                        "reasons": ["classification_threshold_not_met"],
                    },
                    outcome="in_play",
                    review_status="pending",
                    evidence_provenance="unavailable",
                ),
                Rally(
                    match=match,
                    prediction_revision=7,
                    prediction_id="rally-1",
                    ordinal=1,
                    start_frame=1,
                    end_frame=20,
                    start_timestamp_us=500_000,
                    end_timestamp_us=2_500_000,
                    timing_available=True,
                    review_required=True,
                    review_reasons=["boundary_confidence_low"],
                    source_evidence_ids=["shot-1"],
                    review_status="pending",
                    evidence_provenance="unavailable",
                ),
                ErrorCandidate(
                    review_status="pending",
                    match=match,
                    analysis_job=current_job,
                    prediction_revision=7,
                    prediction_id="error-1",
                    kind=ErrorKind.TRACKING,
                    target_type="shot",
                    target_prediction_id="shot-1",
                    source_timestamp_us=1_000_000,
                    source_evidence_ids=["ball-1"],
                    evidence_version=1,
                    evidence_payload={"confidence": 0.5},
                ),
            ]
        )
    return job_id, internal_match_id


def _assert_error(response: object, status: int, code: str) -> None:
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"code", "message", "details", "requestId"}
    assert payload["code"] == code
    assert isinstance(payload["message"], str) and payload["message"]
    assert payload["details"] is None or isinstance(payload["details"], dict)
    assert isinstance(payload["requestId"], str) and payload["requestId"]
    assert response.headers["x-request-id"] == payload["requestId"]


@pytest.mark.asyncio
async def test_common_error_envelope_request_ids_and_sanitized_internal_failure(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))

    @app.get("/api/v1/_boom", operation_id="testBoom", include_in_schema=False)
    def boom() -> None:
        raise RuntimeError("/private/cache/model.pt SQL SELECT secret")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        missing = await client.get(
            "/api/v1/matches/not-here", headers={"X-Request-ID": SAFE_REQUEST_ID}
        )
        _assert_error(missing, 404, "match_not_found")
        assert missing.json()["requestId"] == SAFE_REQUEST_ID

        invalid = await client.get("/api/v1/matches", params={"limit": 0})
        _assert_error(invalid, 422, "request_validation_failed")

        unsafe = await client.get(
            "/api/v1/matches/not-here", headers={"X-Request-ID": "../\nsecret"}
        )
        _assert_error(unsafe, 404, "match_not_found")
        assert unsafe.json()["requestId"] != "../\nsecret"

        failed = await client.get("/api/v1/_boom")
        _assert_error(failed, 500, "internal_error")
        assert "private" not in failed.text
        assert "SQL" not in failed.text
        assert "secret" not in failed.text


@pytest.mark.asyncio
async def test_match_list_detail_patch_conflict_and_safe_delete(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    _ready_models(app)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/api/v1/matches", params={"limit": 1})
        assert page.status_code == 200
        assert page.json()["items"][0]["id"] == match_id
        assert page.json()["items"][0]["processing"]["state"] == "not_started"
        _assert_error(
            await client.get("/api/v1/matches", params={"cursor": "not-a-cursor"}),
            422,
            "invalid_cursor",
        )
        _assert_error(
            await client.get("/api/v1/matches", params={"cursor": "a"}),
            422,
            "invalid_cursor",
        )
        _assert_error(
            await client.get("/api/v1/matches", params={"limit": 101}),
            422,
            "request_validation_failed",
        )

        detail = await client.get(f"/api/v1/matches/{match_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["id"] == match_id
        assert all("relativePath" not in asset for asset in body["assets"])
        version = body["version"]

        updated = await client.patch(
            f"/api/v1/matches/{match_id}",
            json={"expectedVersion": version, "title": "Updated", "score": "3-2"},
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Updated"
        assert updated.json()["version"] > version
        _assert_error(
            await client.patch(
                f"/api/v1/matches/{match_id}",
                json={"expectedVersion": version, "title": "Stale"},
            ),
            409,
            "match_revision_conflict",
        )

        created = await client.post(
            f"/api/v1/matches/{match_id}/jobs", json={"profile": "balanced"}
        )
        assert created.status_code == 201
        _assert_error(
            await client.delete(f"/api/v1/matches/{match_id}"),
            409,
            "active_job_exists",
        )
        shared_cache = app.state.storage.root / "cache/shared.bin"
        shared_cache.parent.mkdir(parents=True, exist_ok=True)
        shared_cache.write_bytes(b"shared")
        outside = tmp_path / "outside-cache-target.bin"
        outside.write_bytes(b"outside")
        cache_namespace = (
            app.state.storage.root
            / "analysis-cache"
            / canonical_hash({"match_id": match_id})
        )
        (cache_namespace / "players" / ("a" * 64)).mkdir(parents=True)
        (cache_namespace / "players" / ("a" * 64) / "payload.parquet").write_bytes(
            b"match cache"
        )
        (cache_namespace / "outside-link").symlink_to(outside)
        with app.state.database.session() as session:
            job = session.scalar(select(AnalysisJob).where(AnalysisJob.public_id == created.json()["id"]))
            assert job is not None
            job.status = JobStatus.CANCELLED
            worker_dir = app.state.storage.root / ".worker" / job.public_id
            checkpoint_dir = app.state.storage.root / "checkpoints" / job.public_id
            worker_dir.mkdir(parents=True)
            checkpoint_dir.mkdir(parents=True)
            session.add(
                JobChunk(
                    analysis_job=job,
                    chunk_index=0,
                    stage=Stage.PREPARE,
                    start_us=0,
                    end_us=1,
                    status=StageStatus.COMPLETED,
                    artifact_path="cache/shared.bin",
                    artifact_payload_path="cache/shared.bin",
                    artifact_availability="available",
                )
            )
        deleted = await client.delete(f"/api/v1/matches/{match_id}")
        assert deleted.status_code == 204 and not deleted.content, deleted.text
        _assert_error(
            await client.get(f"/api/v1/matches/{match_id}"), 404, "match_not_found"
        )
    assert not (app.state.storage.root / "videos/original/original.mp4").exists()
    assert not (app.state.storage.root / "videos/proxy/proxy.mp4").exists()
    assert shared_cache.read_bytes() == b"shared"
    assert not cache_namespace.exists()
    assert not worker_dir.exists()
    assert not checkpoint_dir.exists()
    assert outside.read_bytes() == b"outside"


@pytest.mark.asyncio
async def test_match_proxy_stream_supports_byte_ranges_and_typed_failures(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    with app.state.database.session() as session:
        unavailable = Match(name="Proxy pending")
        session.add(unavailable)
        session.flush()
        unavailable_id = unavailable.public_id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        full = await client.get(f"/api/v1/matches/{match_id}/media/proxy")
        assert full.status_code == 200
        assert full.content == b"proxy"
        assert full.headers["accept-ranges"] == "bytes"
        assert full.headers["content-length"] == "5"
        assert full.headers["content-type"] == "video/mp4"

        bounded = await client.get(
            f"/api/v1/matches/{match_id}/media/proxy",
            headers={"Range": "bytes=1-3"},
        )
        assert bounded.status_code == 206
        assert bounded.content == b"rox"
        assert bounded.headers["content-range"] == "bytes 1-3/5"
        assert bounded.headers["content-length"] == "3"
        assert bounded.headers["accept-ranges"] == "bytes"

        open_ended = await client.get(
            f"/api/v1/matches/{match_id}/media/proxy",
            headers={"Range": "bytes=3-"},
        )
        assert open_ended.status_code == 206
        assert open_ended.content == b"xy"

        suffix = await client.get(
            f"/api/v1/matches/{match_id}/media/proxy",
            headers={"Range": "bytes=-2"},
        )
        assert suffix.status_code == 206
        assert suffix.content == b"xy"

        unsatisfiable = await client.get(
            f"/api/v1/matches/{match_id}/media/proxy",
            headers={"Range": "bytes=9-"},
        )
        _assert_error(unsatisfiable, 416, "range_not_satisfiable")
        assert unsatisfiable.headers["content-range"] == "bytes */5"

        _assert_error(
            await client.get("/api/v1/matches/not-here/media/proxy"),
            404,
            "match_not_found",
        )
        _assert_error(
            await client.get(f"/api/v1/matches/{unavailable_id}/media/proxy"),
            409,
            "proxy_unavailable",
        )


@pytest.mark.asyncio
async def test_health_model_sources_and_job_runtime_evidence_are_public_and_safe(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        health = await client.get("/api/v1/health")
        assert health.status_code == 200
        worker = health.json()["worker"]
        assert set(worker) == {
            "status",
            "architecture",
            "nativeAppleSilicon",
            "mpsAvailable",
        }
        assert isinstance(worker["architecture"], str) and worker["architecture"]
        assert isinstance(worker["nativeAppleSilicon"], bool)
        assert isinstance(worker["mpsAvailable"], bool)

        models = await client.get("/api/v1/models")
        assert models.status_code == 200
        source_labels = {item["name"]: item["sourceLabel"] for item in models.json()}
        assert source_labels == {
            "pose": "GitHub · ultralytics/assets · v8.3.0",
            "ball": "Hugging Face · linfeng302/RacketVision-Models",
        }
        assert all("/tmp/" not in label and "https://" not in label for label in source_labels.values())
        _ready_models(app)

        created = await client.post(
            f"/api/v1/matches/{match_id}/jobs", json={"profile": "balanced"}
        )
        assert created.status_code == 201
        job_id = created.json()["id"]
        with app.state.database.session() as session:
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.public_id == job_id)
            )
            assert job is not None
            job.status = JobStatus.RUNNING
            job.current_stage = Stage.PLAYERS
            job.version += 1
            session.add(
                JobChunk(
                    analysis_job=job,
                    chunk_index=0,
                    stage=Stage.PLAYERS,
                    start_us=12_000_000,
                    end_us=18_000_000,
                    status=StageStatus.RUNNING,
                )
            )

        active = await client.get(f"/api/v1/jobs/{job_id}")
        assert active.status_code == 200
        assert active.json()["currentRangeStartUs"] == 12_000_000
        assert active.json()["currentRangeEndUs"] == 18_000_000
        assert active.json()["failureCode"] is None

        app.state.job_queue.fail(
            job_id,
            "/private/cache/model.pt exploded",
            failure_code="worker_runtime_error",
        )
        failed = await client.get(f"/api/v1/jobs/{job_id}")
        assert failed.status_code == 200
        assert failed.json()["failureCode"] == "worker_runtime_error"
        assert "private" not in failed.text
        events = await client.get(f"/api/v1/jobs/{job_id}/events")
        assert '"failureCode":"worker_runtime_error"' in events.text
        assert '"currentRangeStartUs":12000000' in events.text


@pytest.mark.asyncio
async def test_job_readiness_reanalysis_controls_and_sse_contract(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _assert_error(
            await client.post(
                f"/api/v1/matches/{match_id}/jobs", json={"profile": "balanced"}
            ),
            503,
            "required_models_unavailable",
        )
        _ready_models(app)
        created = await client.post(
            f"/api/v1/matches/{match_id}/jobs", json={"profile": "balanced"}
        )
        assert created.status_code == 201
        job_id = created.json()["id"]
        assert (await client.get(f"/api/v1/jobs/{job_id}")).status_code == 200
        paused = await client.post(f"/api/v1/jobs/{job_id}/pause")
        assert paused.status_code == 200 and paused.json()["state"] == "paused"
        resumed = await client.post(f"/api/v1/jobs/{job_id}/resume")
        assert resumed.status_code == 200 and resumed.json()["state"] == "queued"
        cancelled = await client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
        retried = await client.post(f"/api/v1/jobs/{job_id}/retry")
        assert retried.status_code == 200 and retried.json()["state"] == "queued"
        await client.post(f"/api/v1/jobs/{job_id}/cancel")
        reanalysis = await client.post(
            f"/api/v1/matches/{match_id}/reanalyze", json={"profile": "maximum"}
        )
        assert reanalysis.status_code == 201
        reanalysis_id = reanalysis.json()["id"]
        with app.state.database.session() as session:
            job = session.scalar(select(AnalysisJob).where(AnalysisJob.public_id == reanalysis_id))
            assert job is not None
            job.status = JobStatus.COMPLETED
        events = await client.get(f"/api/v1/jobs/{reanalysis_id}/events")
        assert events.status_code == 200
        assert events.headers["content-type"].startswith("text/event-stream")
        assert events.headers["cache-control"] == "no-cache"
        assert events.headers["x-accel-buffering"] == "no"
        assert "event: job.snapshot" in events.text
        assert '"eventVersion":1' in events.text


@pytest.mark.asyncio
async def test_reports_timeline_and_exact_current_artifact_queries_are_bounded(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    job_id, _ = _seed_completed_analysis(app, match_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reports = await client.get(f"/api/v1/matches/{match_id}/reports", params={"limit": 1})
        assert reports.status_code == 200
        assert reports.json()["items"][0]["revision"] == 2
        latest = await client.get(f"/api/v1/matches/{match_id}/reports/latest")
        exact = await client.get(f"/api/v1/matches/{match_id}/reports/2")
        assert latest.json() == exact.json()
        assert latest.json()["sections"]["overview"]["hash"] == "a" * 64
        _assert_error(
            await client.get(f"/api/v1/matches/{match_id}/reports/99"),
            404,
            "report_not_found",
        )

        query = {
            "startUs": 1_000_000,
            "endUs": 3_000_000,
            "revision": 2,
            "limit": 1,
        }
        players = await client.get(
            f"/api/v1/matches/{match_id}/observations/players", params=query
        )
        assert players.status_code == 200
        player_body = players.json()
        assert len(player_body["items"]) == 1
        assert player_body["items"][0]["sourceManifestId"] == "current-source"
        assert player_body["artifact"]["jobId"] == job_id
        assert len(player_body["items"][0]["keypoints"]) == 17
        assert player_body["items"][0]["skeletonEdges"]
        assert player_body["items"][0]["box"] == [1.0, 1.0, 4.0, 4.0]
        assert player_body["nextCursor"]
        player_page_2 = await client.get(
            f"/api/v1/matches/{match_id}/observations/players",
            params={**query, "cursor": player_body["nextCursor"]},
        )
        assert player_page_2.status_code == 200
        assert player_page_2.json()["items"][0]["timestampUs"] == 2_000_000
        assert all(
            item["sourceManifestId"] != "historical-source"
            for item in player_body["items"] + player_page_2.json()["items"]
        )

        ball = await client.get(
            f"/api/v1/matches/{match_id}/observations/ball", params=query
        )
        assert ball.status_code == 200
        assert ball.json()["items"][0]["modelManifestId"] == "current-ball"
        assert ball.json()["items"][0]["covariance"] == [[4.0, 0.0], [0.0, 9.0]]
        assert len(ball.json()["items"][0]["candidates"]) == 1

        shots = await client.get(f"/api/v1/matches/{match_id}/shots", params=query)
        rallies = await client.get(f"/api/v1/matches/{match_id}/rallies", params=query)
        timeline = await client.get(
            f"/api/v1/matches/{match_id}/timeline",
            params={**query, "limit": 10, "revision": 2, "kinds": "shot,rally,error,contact,observationWindow"},
        )
        assert shots.status_code == rallies.status_code == timeline.status_code == 200
        assert shots.json()["items"][0]["id"] == "shot-1"
        assert rallies.json()["items"][0]["id"] == "rally-1"
        assert {item["kind"] for item in timeline.json()["items"]} >= {
            "shot",
            "rally",
            "error",
            "observationWindow",
        }
        timeline_by_kind = {item["kind"]: item for item in timeline.json()["items"]}
        assert timeline_by_kind["shot"]["summary"]["reviewRequired"] is True
        assert timeline_by_kind["shot"]["summary"]["confidence"] == 0.4
        assert timeline_by_kind["shot"]["summary"]["commandTargets"]["change_shot_type"]["targetType"] == "shot"
        assert timeline_by_kind["rally"]["summary"]["reviewRequired"] is True
        assert timeline_by_kind["rally"]["summary"]["issue"] == "rally_boundary"
        observation_links = timeline_by_kind["observationWindow"]["observationLinks"]
        assert "revision=2" in observation_links["players"]
        assert "revision=2" in observation_links["ball"]
        pinned_players = await client.get(observation_links["players"])
        pinned_ball = await client.get(observation_links["ball"])
        assert pinned_players.status_code == 200
        assert pinned_ball.status_code == 200
        assert pinned_players.json()["artifact"]["jobId"] == job_id
        assert pinned_ball.json()["artifact"]["jobId"] == job_id
        review = await client.get(
            f"/api/v1/matches/{match_id}/review-items",
            params={"revision": 2, "limit": 10},
        )
        assert timeline_by_kind["shot"]["summary"]["evidenceStartFrameIndex"] == 20
        assert review.status_code == 200
        review_by_type = {
            item["reviewEntityType"]: item for item in review.json()["items"]
        }
        review_error = review_by_type["error_candidate"]
        assert review_error["id"] == "error-1"
        assert review_error["provenance"] == "unavailable"
        assert review_error["invalidatedSections"]
        assert review_error["commandTargets"]["change_outcome"]["evidenceStartFrameIndex"] == 20
        evidence = await client.get(
            f"/api/v1/matches/{match_id}/evidence/ball-1",
            params={"revision": 2},
        )
        assert evidence.status_code == 200
        assert evidence.json()["timestampUs"] == 1_000_000
        _assert_error(
            await client.get(
                f"/api/v1/matches/{match_id}/timeline",
                params={**query, "revision": 2, "kinds": "error_candidate"},
            ),
            422,
            "invalid_kinds",
        )
        review_item = review_error
        accept_target = review_item["commandTargets"]["accept"]
        accept_body = {
            "commandType": "accept",
            "expectedReportRevision": 2,
            "matchId": match_id,
            "payload": {},
            "reason": "accepted from exact published evidence",
            "sourceEvidenceIds": accept_target["sourceEvidenceIds"],
            "sourceTimestampUs": accept_target["sourceTimestampUs"],
            "targetId": accept_target["targetId"],
            "targetType": accept_target["targetType"],
            "reviewEntityType": review_item["reviewEntityType"],
            "reviewEntityId": review_item["reviewEntityId"],
        }
        accepted = await client.post(
            f"/api/v1/matches/{match_id}/corrections", json=accept_body
        )
        assert accepted.status_code == 200
        assert accepted.json()["revision"] == 3
        stale = await client.post(
            f"/api/v1/matches/{match_id}/corrections", json=accept_body
        )
        _assert_error(stale, 409, "report_revision_conflict")
        assert stale.json()["details"] == {
            "expectedRevision": 2,
            "currentRevision": 3,
        }

        for route in ("timeline", "observations/players", "observations/ball", "shots", "rallies"):
            _assert_error(
                await client.get(
                    f"/api/v1/matches/{match_id}/{route}",
                    params={"startUs": 0, "endUs": 120_000_001, "revision": 3},
                ),
                422,
                "range_too_large",
            )
            _assert_error(
                await client.get(
                    f"/api/v1/matches/{match_id}/{route}",
                    params={"startUs": 2, "endUs": 2, "revision": 3},
                ),
                422,
                "invalid_range",
            )
        _assert_error(
            await client.get(
                f"/api/v1/matches/{match_id}/timeline",
                params={"startUs": 0, "endUs": 1, "limit": 5001},
            ),
            422,
            "request_validation_failed",
        )


@pytest.mark.asyncio
async def test_canonical_limit_one_pages_do_not_materialize_full_report_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    job_id, _ = _seed_completed_analysis(app, match_id)
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        job = session.scalar(
            select(AnalysisJob).where(AnalysisJob.public_id == job_id)
        )
        assert match is not None and job is not None
        session.add_all(
            [
                Shot(
                    match=match,
                    prediction_revision=7,
                    prediction_id="shot-2",
                    frame_index=40,
                    source_timestamp_us=2_000_000,
                    source_evidence_ids=["ball-2"],
                    kind=ShotKind.DRIVE,
                    outcome="in_play",
                    review_required=True,
                    review_status="pending",
                ),
                Rally(
                    match=match,
                    prediction_revision=7,
                    prediction_id="rally-2",
                    ordinal=2,
                    start_frame=21,
                    end_frame=50,
                    start_timestamp_us=2_500_000,
                    end_timestamp_us=3_500_000,
                    timing_available=True,
                    source_evidence_ids=["shot-2"],
                    review_required=True,
                    review_status="pending",
                ),
                ErrorCandidate(
                    match=match,
                    analysis_job=job,
                    prediction_revision=7,
                    prediction_id="error-2",
                    kind=ErrorKind.TRACKING,
                    target_type="shot",
                    target_prediction_id="shot-2",
                    source_timestamp_us=2_000_000,
                    source_evidence_ids=["ball-2"],
                    evidence_version=1,
                    evidence_payload={"confidence": 0.3},
                    review_status="pending",
                ),
                Correction(
                    match=match,
                    command_type="adjust_contact_time",
                    target_type="shot",
                    target_id="shot-1",
                    prediction_revision=7,
                    expected_report_revision=2,
                    before_payload={"source_timestamp_us": 1_000_000},
                    after_payload={"source_timestamp_us": 1_500_000},
                    reason="bounded canonical regression",
                    source_evidence_ids=["ball-1"],
                    review_entity_type="error_candidate",
                    review_entity_id="error-1",
                    review_decision="accepted",
                    status=CorrectionStatus.ACTIVE,
                ),
            ]
        )
    report = build_report(match_id, 3, app.state.database)
    assert report.revision == 3

    def reject_full_state(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("bounded list route materialized full canonical state")

    monkeypatch.setattr(
        analysis_routes, "canonical_state_for_report", reject_full_state
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        window = {"startUs": 0, "endUs": 4_000_000, "limit": 1}
        for route, first_id, second_id in (
            ("shots", "shot-1", "shot-2"),
            ("rallies", "rally-1", "rally-2"),
        ):
            first = await client.get(
                f"/api/v1/matches/{match_id}/{route}", params=window
            )
            assert first.status_code == 200
            assert first.json()["items"][0]["id"] == first_id
            assert first.json()["nextCursor"]
            second = await client.get(
                f"/api/v1/matches/{match_id}/{route}",
                params={**window, "cursor": first.json()["nextCursor"]},
            )
            assert second.status_code == 200
            assert second.json()["items"][0]["id"] == second_id

        first_shot = await client.get(
            f"/api/v1/matches/{match_id}/shots", params=window
        )
        assert first_shot.json()["items"][0]["timestampUs"] == 1_500_000

        review_ids: list[str] = []
        review_cursor: str | None = None
        for _ in range(6):
            params: dict[str, object] = {"revision": 3, "limit": 1}
            if review_cursor is not None:
                params["cursor"] = review_cursor
            page = await client.get(
                f"/api/v1/matches/{match_id}/review-items", params=params
            )
            assert page.status_code == 200
            review_ids.extend(item["id"] for item in page.json()["items"])
            review_cursor = page.json()["nextCursor"]
            if review_cursor is None:
                break
        assert "error-1" not in review_ids
        assert {"shot-1", "shot-2", "rally-1", "rally-2", "error-2"} <= set(
            review_ids
        )

        first_timeline = await client.get(
            f"/api/v1/matches/{match_id}/timeline",
            params={**window, "revision": 3, "kinds": "shot"},
        )
        assert first_timeline.status_code == 200
        assert first_timeline.json()["items"][0]["id"] == "shot-1"
        assert first_timeline.json()["items"][0]["timestampUs"] == 1_500_000
        second_timeline = await client.get(
            f"/api/v1/matches/{match_id}/timeline",
            params={
                **window,
                "revision": 3,
                "kinds": "shot",
                "cursor": first_timeline.json()["nextCursor"],
            },
        )
        assert second_timeline.status_code == 200
        assert second_timeline.json()["items"][0]["id"] == "shot-2"


@pytest.mark.asyncio
async def test_review_edits_resolve_error_shot_and_rally_entities_atomically(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    _seed_completed_analysis(app, match_id)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        review = await client.get(
            f"/api/v1/matches/{match_id}/review-items",
            params={"revision": 2, "limit": 10},
        )
        assert review.status_code == 200
        by_type = {
            item["reviewEntityType"]: item for item in review.json()["items"]
        }

        async def submit(
            item: dict[str, object],
            command_type: str,
            expected_revision: int,
            payload: dict[str, object],
        ) -> None:
            target = item["commandTargets"][command_type]
            response = await client.post(
                f"/api/v1/matches/{match_id}/corrections",
                json={
                    "commandType": command_type,
                    "expectedReportRevision": expected_revision,
                    "matchId": match_id,
                    "payload": payload,
                    "reason": f"resolve {item['reviewEntityType']} with {command_type}",
                    "sourceEvidenceIds": target["sourceEvidenceIds"],
                    "sourceTimestampUs": target["sourceTimestampUs"],
                    "targetId": target["targetId"],
                    "targetType": target["targetType"],
                    "reviewEntityType": item["reviewEntityType"],
                    "reviewEntityId": item["reviewEntityId"],
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["revision"] == expected_revision + 1

        await submit(
            by_type["error_candidate"],
            "change_outcome",
            2,
            {"outcome": "winner"},
        )
        await submit(
            by_type["shot"],
            "change_shot_type",
            3,
            {"shot_type": "drop"},
        )
        await submit(
            by_type["rally"],
            "split_rally",
            4,
            {"split_timestamp_us": 1_500_000},
        )
        final_report = await client.get(
            f"/api/v1/matches/{match_id}/reports/5"
        )
        review_payload = final_report.json()["sections"]["review"]["payload"]
        assert review_payload["candidate_count"] == 3
        assert review_payload["reviewed_count"] == 3
        assert review_payload["pending_ids"] == []
        final_queue = await client.get(
            f"/api/v1/matches/{match_id}/review-items",
            params={"revision": 5, "limit": 10},
        )
        assert final_queue.json()["items"] == []


@pytest.mark.asyncio
async def test_shot_and_rally_accept_reject_clear_only_their_review_entities(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    _seed_completed_analysis(app, match_id)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        initial = await client.get(
            f"/api/v1/matches/{match_id}/review-items",
            params={"revision": 2, "limit": 10},
        )
        by_type = {
            item["reviewEntityType"]: item for item in initial.json()["items"]
        }
        for command_type, entity_type, revision in (
            ("accept", "shot", 2),
            ("reject", "rally", 3),
        ):
            item = by_type[entity_type]
            target = item["commandTargets"][command_type]
            response = await client.post(
                f"/api/v1/matches/{match_id}/corrections",
                json={
                    "commandType": command_type,
                    "expectedReportRevision": revision,
                    "matchId": match_id,
                    "payload": {},
                    "reason": f"{command_type} {entity_type} review",
                    "sourceEvidenceIds": target["sourceEvidenceIds"],
                    "sourceTimestampUs": target["sourceTimestampUs"],
                    "targetId": target["targetId"],
                    "targetType": target["targetType"],
                    "reviewEntityType": item["reviewEntityType"],
                    "reviewEntityId": item["reviewEntityId"],
                },
            )
            assert response.status_code == 200
        final_queue = await client.get(
            f"/api/v1/matches/{match_id}/review-items",
            params={"revision": 4, "limit": 10},
        )
        assert [
            item["reviewEntityType"] for item in final_queue.json()["items"]
        ] == ["error_candidate"]
        report = await client.get(f"/api/v1/matches/{match_id}/reports/4")
        review_payload = report.json()["sections"]["review"]["payload"]
        assert review_payload["candidate_count"] == 3
        assert review_payload["reviewed_count"] == 2


@pytest.mark.asyncio
async def test_accept_reject_mismatched_review_entities_fail_without_resolution(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    job_id, _ = _seed_completed_analysis(app, match_id)
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        job = session.scalar(
            select(AnalysisJob).where(AnalysisJob.public_id == job_id)
        )
        assert match is not None and job is not None
        session.add(
            ErrorCandidate(
                review_status="pending",
                match=match,
                analysis_job=job,
                prediction_revision=7,
                prediction_id="error-2",
                kind=ErrorKind.TRACKING,
                target_type="shot",
                target_prediction_id="shot-1",
                source_timestamp_us=1_000_000,
                source_evidence_ids=["ball-1"],
                evidence_version=1,
                evidence_payload={"confidence": 0.4},
            )
        )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        review = await client.get(
            f"/api/v1/matches/{match_id}/review-items",
            params={"revision": 2, "limit": 10},
        )
        error_item = next(
            item
            for item in review.json()["items"]
            if item["reviewEntityType"] == "error_candidate"
        )
        target = error_item["commandTargets"]["accept"]
        base_body = {
            "commandType": "accept",
            "expectedReportRevision": 2,
            "matchId": match_id,
            "payload": {},
            "reason": "must resolve exactly the accepted target",
            "sourceEvidenceIds": target["sourceEvidenceIds"],
            "sourceTimestampUs": target["sourceTimestampUs"],
            "targetId": target["targetId"],
            "targetType": target["targetType"],
        }
        mismatched_type = await client.post(
            f"/api/v1/matches/{match_id}/corrections",
            json={
                **base_body,
                "reviewEntityType": "shot",
                "reviewEntityId": "shot-1",
            },
        )
        _assert_error(mismatched_type, 409, "correction_conflict")
        mismatched_id = await client.post(
            f"/api/v1/matches/{match_id}/corrections",
            json={
                **base_body,
                "commandType": "reject",
                "reviewEntityType": "error_candidate",
                "reviewEntityId": "error-2",
            },
        )
        _assert_error(mismatched_id, 409, "correction_conflict")
        invalid_type = await client.post(
            f"/api/v1/matches/{match_id}/corrections",
            json={
                **base_body,
                "reviewEntityType": "observation",
                "reviewEntityId": "ball-1",
            },
        )
        _assert_error(invalid_type, 422, "request_validation_failed")

    with app.state.database.session() as session:
        statuses = dict(
            session.execute(
                select(ErrorCandidate.prediction_id, ErrorCandidate.review_status)
                .where(
                    ErrorCandidate.match.has(public_id=match_id),
                    ErrorCandidate.prediction_id.in_(["error-1", "error-2"]),
                )
                .order_by(ErrorCandidate.prediction_id)
            ).all()
        )
        shot_status = session.scalar(
            select(Shot.review_status).where(
                Shot.match.has(public_id=match_id),
                Shot.prediction_id == "shot-1",
            )
        )
        latest_revision = session.scalar(
            select(ReportRevision.revision)
            .where(ReportRevision.match.has(public_id=match_id))
            .order_by(ReportRevision.revision.desc())
        )
        correction_count = session.scalar(
            select(func.count(Correction.id)).where(
                Correction.match.has(public_id=match_id)
            )
        )
        assert statuses == {"error-1": "pending", "error-2": "pending"}
        assert shot_status == "pending"
        assert latest_revision == 2
        assert correction_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_error", "status", "code"),
    [
        (MediaError("invalid_media", "decoder /private/path", 422), 422, "invalid_media"),
        (MediaError("upload_too_large", "too big", 413), 413, "upload_too_large"),
        (MediaError("insufficient_disk", "disk /secret", 507), 507, "insufficient_disk"),
    ],
)
async def test_upload_and_existing_routes_use_common_safe_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    media_error: MediaError,
    status: int,
    code: str,
) -> None:
    app = create_app(_settings(tmp_path))

    def fail(*_args: object, **_kwargs: object) -> None:
        raise media_error

    monkeypatch.setattr("squashvision.routes.matches.ingest_upload", fail)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/matches", files={"video": ("video.mp4", b"data", "video/mp4")}
        )
        _assert_error(response, status, code)
        assert "private" not in response.text and "secret" not in response.text
        _assert_error(
            await client.get("/api/v1/matches/missing/calibration"),
            404,
            "match_not_found",
        )
        _assert_error(
            await client.get("/api/v1/matches/missing/correction-conflicts"),
            404,
            "match_not_found",
        )


def test_openapi_has_unique_stable_operation_ids_including_exports(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    schema = app.openapi()
    operations: list[str] = []
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                assert "operationId" in operation
                operations.append(operation["operationId"])
                validation = operation["responses"].get("422")
                if validation is not None:
                    reference = validation["content"]["application/json"]["schema"]["$ref"]
                    assert reference == "#/components/schemas/ErrorResponse"
    assert len(operations) == len(set(operations))
    assert {
        "createMatch",
        "listMatches",
        "getMatch",
        "updateMatch",
        "deleteMatch",
        "startAnalysisJob",
        "reanalyzeMatch",
        "streamJobEvents",
        "listReports",
        "getLatestReport",
        "getReportRevision",
        "getTimeline",
        "listPlayerObservations",
        "listBallObservations",
        "listShots",
        "listRallies",
        "createExport",
        "getExport",
        "downloadExport",
    } <= set(operations)


def _signed_cursor(
    secret: bytes, binding: dict[str, object], key: list[object]
) -> str:
    payload = json.dumps(
        {"binding": binding, "key": key},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    encoded_signature = (
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    )
    return f"{encoded_payload}.{encoded_signature}"


@pytest.mark.asyncio
async def test_cursors_are_signed_bound_keysets_and_survive_restart(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    first_id, _ = _seed_match(app, title="First")
    with app.state.database.session() as session:
        second = Match(name="Second")
        session.add(second)
        session.flush()
        second_id = second.public_id
    assert hasattr(app.state, "cursor_secret")
    secret = app.state.cursor_secret
    assert isinstance(secret, bytes) and len(secret) >= 32

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_page = await client.get("/api/v1/matches", params={"limit": 1})
        assert first_page.status_code == 200
        assert first_page.json()["items"][0]["id"] == second_id
        cursor = first_page.json()["nextCursor"]
        assert cursor and "." in cursor
        with app.state.database.session() as session:
            session.add(Match(name="Inserted after page one"))
        second_page = await client.get(
            "/api/v1/matches", params={"limit": 1, "cursor": cursor}
        )
        assert second_page.status_code == 200
        assert second_page.json()["items"][0]["id"] == first_id

        wrong_type = _signed_cursor(
            secret,
            {"kind": "matches"},
            [True, second_id],
        )
        _assert_error(
            await client.get(
                "/api/v1/matches", params={"limit": 1, "cursor": wrong_type}
            ),
            422,
            "invalid_cursor",
        )

    restarted = create_app(settings)
    assert restarted.state.cursor_secret == secret
    async with AsyncClient(
        transport=ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        resumed = await client.get(
            "/api/v1/matches", params={"limit": 1, "cursor": cursor}
        )
        assert resumed.status_code == 200
        assert resumed.json()["items"][0]["id"] == first_id


@pytest.mark.asyncio
async def test_saved_calibration_keeps_selected_published_ball_and_pose_overlays(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    job_id, _ = _seed_completed_analysis(app, match_id)
    params = {"startUs": 0, "endUs": 4_000_000, "revision": 2, "limit": 10}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        report_before = (await client.get(f"/api/v1/matches/{match_id}/reports/2")).json()
        before = {}
        for stage in ("ball", "players"):
            response = await client.get(f"/api/v1/matches/{match_id}/observations/{stage}", params=params)
            assert response.status_code == 200
            before[stage] = response.json()
            assert len(before[stage]["items"]) == 3
            assert before[stage]["artifact"]["jobId"] == job_id
        with app.state.database.session() as session:
            match = session.scalar(select(Match).where(Match.public_id == match_id))
            # This is the same invalidation performed by save_calibration.
            analysis_routes._invalidate_derived_chunks(session, match)
        with app.state.database.session() as session:
            job = session.scalar(select(AnalysisJob).where(AnalysisJob.public_id == job_id))
            ball = session.scalar(select(JobChunk).where(JobChunk.analysis_job_id == job.id, JobChunk.stage == Stage.BALL))
            assert ball.status == StageStatus.INVALIDATED
        for stage in ("ball", "players"):
            response = await client.get(f"/api/v1/matches/{match_id}/observations/{stage}", params=params)
            assert response.status_code == 200
            assert response.json() == before[stage]
            assert response.json()["artifact"]["availability"] == "available"
        assert (await client.get(f"/api/v1/matches/{match_id}/reports/2")).json() == report_before
        # Publication selection must remain explicit, never fall back to other runs.
        missing = await client.get(f"/api/v1/matches/{match_id}/observations/ball", params={**params, "revision": 99})
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_report_and_observation_cursors_bind_selected_revision_and_job(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    job_id, _ = _seed_completed_analysis(app, match_id)
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add(
            ReportRevision(
                match=match,
                revision=1,
                prediction_revision=7,
                schema_version=1,
                sections={},
                section_hashes={},
                dependency_hashes={},
            )
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        report_page = await client.get(
            f"/api/v1/matches/{match_id}/reports", params={"limit": 1}
        )
        report_cursor = report_page.json()["nextCursor"]
        assert report_cursor
        with app.state.database.session() as session:
            match = session.scalar(select(Match).where(Match.public_id == match_id))
            assert match is not None
            session.add(
                ReportRevision(
                    match=match,
                    revision=3,
                    prediction_revision=7,
                    schema_version=1,
                    sections={},
                    section_hashes={},
                    dependency_hashes={},
                )
            )
        report_page_2 = await client.get(
            f"/api/v1/matches/{match_id}/reports",
            params={"limit": 1, "cursor": report_cursor},
        )
        assert report_page_2.status_code == 200
        assert report_page_2.json()["items"][0]["revision"] == 1

        _assert_error(
            await client.get(
                f"/api/v1/matches/{match_id}/observations/players",
                params={"startUs": 0, "endUs": 4_000_000, "limit": 1},
            ),
            422,
            "request_validation_failed",
        )
        observations = await client.get(
            f"/api/v1/matches/{match_id}/observations/players",
            params={
                "startUs": 0,
                "endUs": 4_000_000,
                "revision": 2,
                "limit": 1,
            },
        )
        observation_cursor = observations.json()["nextCursor"]
        assert observation_cursor
        _assert_error(
            await client.get(
                f"/api/v1/matches/{match_id}/observations/players",
                params={
                    "startUs": 0,
                    "endUs": 5_000_000,
                    "revision": 2,
                    "limit": 1,
                    "cursor": observation_cursor,
                },
            ),
            422,
            "invalid_cursor",
        )
        _assert_error(
            await client.get(
                f"/api/v1/matches/{match_id}/reports",
                params={"limit": 1, "cursor": observation_cursor},
            ),
            422,
            "invalid_cursor",
        )

        _assert_error(
            await client.get(
                f"/api/v1/matches/{match_id}/observations/players",
                params={
                    "startUs": 0,
                    "endUs": 4_000_000,
                    "revision": 1,
                    "limit": 1,
                    "cursor": observation_cursor,
                },
            ),
            422,
            "invalid_cursor",
        )
        with app.state.database.session() as session:
            old_job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.public_id == job_id)
            )
            assert old_job is not None
            newer = AnalysisJob(
                match_id=old_job.match_id,
                source_media_asset_id=old_job.source_media_asset_id,
                processing_profile=ProcessingProfile.BALANCED,
                status=JobStatus.COMPLETED,
                version=1,
                created_at=datetime(2100, 1, 1, tzinfo=timezone.utc),
            )
            session.add(newer)
            session.flush()
            session.add(
                JobChunk(
                    analysis_job=newer,
                    chunk_index=1,
                    stage=Stage.PLAYERS,
                    start_us=0,
                    end_us=10_000_000,
                    status=StageStatus.COMPLETED,
                    artifact_path="checkpoints/new/players.parquet",
                    artifact_payload_path="checkpoints/new/players.parquet",
                    artifact_availability="available",
                )
            )
        historical_ball = await client.get(
            f"/api/v1/matches/{match_id}/observations/ball",
            params={
                "startUs": 0,
                "endUs": 4_000_000,
                "revision": 2,
                "limit": 10,
            },
        )
        assert historical_ball.status_code == 200
        assert historical_ball.json()["items"][0]["modelManifestId"] == "current-ball"
        historical_page = await client.get(
            f"/api/v1/matches/{match_id}/observations/players",
            params={
                "startUs": 0,
                "endUs": 4_000_000,
                "revision": 2,
                "limit": 1,
                "cursor": observation_cursor,
            },
        )
        assert historical_page.status_code == 200
        assert historical_page.json()["items"][0]["sourceManifestId"] == "current-source"


@pytest.mark.asyncio
async def test_shots_bind_to_selected_published_report_revision(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    _seed_completed_analysis(app, match_id)
    other_match_id = ""
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        other_match = Match(name="Other match")
        session.add(other_match)
        session.flush()
        other_match_id = other_match.public_id
        session.add(
            ReportRevision(
                match=match,
                revision=1,
                prediction_revision=6,
                schema_version=1,
                sections={},
                section_hashes={},
                dependency_hashes={},
            )
        )
        session.add_all(
            [
                Shot(
                    match=match,
                    prediction_revision=6,
                    prediction_id=f"historical-shot-{ordinal}",
                    frame_index=ordinal,
                    source_timestamp_us=ordinal * 1_000_000,
                    source_evidence_ids=[f"historical-ball-{ordinal}"],
                    hitter=PlayerSlot.NEAR,
                    kind=ShotKind.DRIVE,
                    review_required=False,
                    classification_payload={"confidence": 0.95},
                    outcome="in_play",
                    review_status="accepted",
                    evidence_provenance="observed",
                )
                for ordinal in (1, 2)
            ]
        )

    window = {"startUs": 0, "endUs": 4_000_000}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        current = await client.get(
            f"/api/v1/matches/{match_id}/shots", params=window
        )
        assert current.status_code == 200
        assert current.json()["predictionRevision"] == 7
        assert [item["id"] for item in current.json()["items"]] == ["shot-1"]

        historical = await client.get(
            f"/api/v1/matches/{match_id}/shots",
            params={**window, "reportRevision": 1, "limit": 1},
        )
        assert historical.status_code == 200
        assert historical.json()["predictionRevision"] == 6
        assert [item["id"] for item in historical.json()["items"]] == [
            "historical-shot-1"
        ]
        historical_cursor = historical.json()["nextCursor"]
        assert historical_cursor
        historical_page_2 = await client.get(
            f"/api/v1/matches/{match_id}/shots",
            params={
                **window,
                "reportRevision": 1,
                "limit": 1,
                "cursor": historical_cursor,
            },
        )
        assert historical_page_2.status_code == 200
        assert [item["id"] for item in historical_page_2.json()["items"]] == [
            "historical-shot-2"
        ]

        _assert_error(
            await client.get(
                f"/api/v1/matches/{match_id}/shots",
                params={
                    **window,
                    "reportRevision": 2,
                    "limit": 1,
                    "cursor": historical_cursor,
                },
            ),
            422,
            "invalid_cursor",
        )
        _assert_error(
            await client.get(
                f"/api/v1/matches/{other_match_id}/shots",
                params={**window, "reportRevision": 1},
            ),
            404,
            "report_not_found",
        )


@pytest.mark.asyncio
async def test_canonical_queries_fold_shot_and_rally_corrections(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    _seed_completed_analysis(app, match_id)
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        other = Rally(
            match=match,
            prediction_revision=7,
            prediction_id="rally-2",
            ordinal=2,
            start_frame=21,
            end_frame=40,
            start_timestamp_us=2_500_000,
            end_timestamp_us=4_000_000,
            timing_available=True,
            source_evidence_ids=["shot-2"],
        )
        session.add(other)
        corrections = [
            ("change_hitter", "shot", "shot-1", {"hitter": "far"}),
            ("change_shot_type", "shot", "shot-1", {"shot_type": "drop"}),
            ("change_outcome", "shot", "shot-1", {"outcome": "winner"}),
            (
                "adjust_contact_time",
                "shot",
                "shot-1",
                {"source_timestamp_us": 3_500_000},
            ),
            (
                "merge_rallies",
                "rally",
                "rally-1",
                {"other_target_id": "rally-2"},
            ),
            (
                "split_rally",
                "rally",
                "rally-1",
                {"split_timestamp_us": 1_500_000},
            ),
        ]
        for command, target_type, target_id, after in corrections:
            session.add(
                Correction(
                    match=match,
                    command_type=command,
                    target_type=target_type,
                    target_id=target_id,
                    prediction_revision=7,
                    expected_report_revision=2,
                    before_payload={},
                    after_payload=after,
                    reason="contract regression",
                    source_evidence_ids=[],
                    status=CorrectionStatus.ACTIVE,
                )
            )
    report = build_report(match_id, 3, app.state.database)
    assert report.revision == 3

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        shots = await client.get(
            f"/api/v1/matches/{match_id}/shots",
            params={"startUs": 3_000_000, "endUs": 4_000_000},
        )
        assert shots.status_code == 200
        shot = shots.json()["items"][0]
        assert shot["timestampUs"] == 3_500_000
        assert shot["hitter"] == "far"
        assert shot["shotKind"] == "drop"
        assert shot["outcome"] == "winner"

        rallies = await client.get(
            f"/api/v1/matches/{match_id}/rallies",
            params={"startUs": 0, "endUs": 5_000_000},
        )
        assert rallies.status_code == 200
        assert [(row["startUs"], row["endUs"]) for row in rallies.json()["items"]] == [
            (500_000, 1_500_000),
            (1_500_000, 4_000_000),
        ]
        boundary = await client.get(
            f"/api/v1/matches/{match_id}/rallies",
            params={"startUs": 4_000_000, "endUs": 5_000_000},
        )
        assert boundary.status_code == 200
        assert boundary.json()["items"] == []

        timeline = await client.get(
            f"/api/v1/matches/{match_id}/timeline",
            params={"startUs": 3_000_000, "endUs": 4_000_000, "limit": 20},
        )
        timeline_shot = next(
            item for item in timeline.json()["items"] if item["kind"] == "shot"
        )
        assert timeline_shot["timestampUs"] == 3_500_000
        assert timeline_shot["summary"]["shotKind"] == "drop"


@pytest.mark.asyncio
async def test_timeline_keyset_merge_has_no_omissions_and_contacts_need_coordinates(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    _seed_completed_analysis(app, match_id)
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        for index in range(2, 8):
            session.add(
                Shot(
                    match=match,
                    prediction_revision=7,
                    prediction_id=f"shot-{index}",
                    frame_index=index * 10,
                    source_timestamp_us=index * 500_000,
                    source_evidence_ids=[f"ball-{index}"],
                    kind=ShotKind.DRIVE,
                    outcome="in_play",
                    contact_x_m=float(index) if index % 2 == 0 else None,
                    contact_y_m=float(index) if index % 2 == 0 else None,
                )
            )

    seen: list[tuple[str, str | None]] = []
    cursor: str | None = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _page in range(20):
            params: dict[str, object] = {
                "startUs": 0,
                "endUs": 5_000_000,
                "limit": 2,
            }
            if cursor is not None:
                params["cursor"] = cursor
            response = await client.get(
                f"/api/v1/matches/{match_id}/timeline", params=params
            )
            assert response.status_code == 200
            body = response.json()
            seen.extend((item["kind"], item.get("id")) for item in body["items"])
            cursor = body["nextCursor"]
            if cursor is None:
                break
        else:
            raise AssertionError("timeline pagination did not terminate")
    assert len(seen) == len(set(seen))
    assert {f"shot-{index}" for index in range(1, 8)} <= {
        item_id for kind, item_id in seen if kind == "shot"
    }
    assert {item_id for kind, item_id in seen if kind == "contact"} == {
        "shot-2",
        "shot-4",
        "shot-6",
    }


@pytest.mark.asyncio
async def test_observation_cursor_streams_past_first_batch_without_omission(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    job_id, _ = _seed_completed_analysis(app, match_id)
    player_path = (
        app.state.storage.root / "checkpoints" / job_id / "players.parquet"
    )
    base = pq.read_table(player_path).slice(0, 1).to_pylist()[0]
    rows = [
        {
            **base,
            "player_id": f"P{index:02d}",
            "timestamp_us": 1_000_000,
            "source_timestamp_us": 1_000_000,
            "source_frame_index": index,
            "evidence_start_frame_index": index,
            "evidence_end_frame_index": index,
        }
        for index in range(10)
    ]
    pq.write_table(pa.Table.from_pylist(rows), player_path)

    observed: list[str] = []
    cursor: str | None = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _page in range(12):
            params: dict[str, object] = {
                "startUs": 0,
                "endUs": 2_000_000,
                "limit": 1,
                "revision": 2,
            }
            if cursor is not None:
                params["cursor"] = cursor
            response = await client.get(
                f"/api/v1/matches/{match_id}/observations/players",
                params=params,
            )
            assert response.status_code == 200
            body = response.json()
            observed.extend(item["playerId"] for item in body["items"])
            cursor = body["nextCursor"]
            if cursor is None:
                break
    assert observed == [f"P{index:02d}" for index in range(10)]


@pytest.mark.asyncio
async def test_delete_and_enqueue_are_serialized(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    _ready_models(app)
    entered = Event()
    release = Event()
    original_resolve = app.state.storage.resolve

    def blocking_resolve(*args: object, **kwargs: object) -> object:
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=5)
        return original_resolve(*args, **kwargs)

    app.state.storage.resolve = blocking_resolve
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as delete_client,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as enqueue_client,
    ):
        delete_task = asyncio.create_task(
            delete_client.delete(f"/api/v1/matches/{match_id}")
        )
        assert await asyncio.to_thread(entered.wait, 5)
        enqueue_task = asyncio.create_task(
            enqueue_client.post(
                f"/api/v1/matches/{match_id}/jobs",
                json={"profile": "balanced"},
            )
        )
        release.set()
        deleted, enqueued = await asyncio.gather(delete_task, enqueue_task)
    assert (deleted.status_code, enqueued.status_code) in {
        (204, 404),
        (204, 409),
        (409, 201),
    }


@pytest.mark.asyncio
async def test_staged_unlink_failure_returns_204_and_retries_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    match_id, _ = _seed_match(app)
    original_remove = LocalStorage.remove_owned_tree
    failed = False

    def fail_once(
        storage: LocalStorage,
        relative: Path,
        *,
        owned_paths: object,
    ) -> None:
        nonlocal failed
        if relative.name.endswith(".deleting") and not failed:
            failed = True
            raise OSError("simulated recursive cleanup failure")
        original_remove(storage, relative, owned_paths=owned_paths)

    monkeypatch.setattr(LocalStorage, "remove_owned_tree", fail_once)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/api/v1/matches/{match_id}")
    assert response.status_code == 204
    staged = list(app.state.storage.root.rglob("*.deleting"))
    assert staged

    monkeypatch.setattr(LocalStorage, "remove_owned_tree", original_remove)
    create_app(settings)
    assert not list(app.state.storage.root.rglob("*.deleting"))


@pytest.mark.asyncio
async def test_restart_recovers_crash_after_first_staged_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    match_id, _ = _seed_match(app)
    _ready_models(app)
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        proxy = session.scalar(
            select(MediaAsset).where(
                MediaAsset.match_id == match.id,
                MediaAsset.kind == AssetKind.PROXY,
            )
        )
        assert proxy is not None
        processed_job = AnalysisJob(
            match=match,
            source_media_asset=proxy,
            processing_profile=ProcessingProfile.MAXIMUM,
            status=JobStatus.COMPLETED,
            version=2,
        )
        session.add(processed_job)
        session.flush()
        processed_job_id = processed_job.public_id
    cache_namespace = (
        app.state.storage.root
        / "analysis-cache"
        / canonical_hash({"match_id": match_id})
    )
    (cache_namespace / "report" / ("b" * 64)).mkdir(parents=True)
    (cache_namespace / "report" / ("b" * 64) / "envelope.json").write_text(
        "{}",
        encoding="utf-8",
    )
    worker_dir = app.state.storage.root / ".worker" / processed_job_id
    checkpoint_dir = app.state.storage.root / "checkpoints" / processed_job_id
    worker_dir.mkdir(parents=True)
    checkpoint_dir.mkdir(parents=True)
    outside = tmp_path / "crash-recovery-outside.bin"
    outside.write_bytes(b"outside")
    (cache_namespace / "outside-link").symlink_to(outside)

    class SimulatedCrash(BaseException):
        pass

    def crash() -> None:
        raise SimulatedCrash

    monkeypatch.setattr(
        matches_routes,
        "_after_stage_rename",
        crash,
        raising=False,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with pytest.raises(SimulatedCrash):
            await client.delete(f"/api/v1/matches/{match_id}")
        enqueue = await client.post(
            f"/api/v1/matches/{match_id}/jobs",
            json={"profile": "balanced"},
        )
        _assert_error(enqueue, 409, "match_deleting")

    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        assert getattr(match, "deletion_state") == "deleting"
        pending = session.scalars(
            select(PendingDeletion).where(
                PendingDeletion.match_public_id == match_id
            )
        ).all()
        assert pending
        planned_originals = {
            Path(row.original_relative_path) for row in pending
        }
        assert cache_namespace.relative_to(app.state.storage.root) in planned_originals
        assert worker_dir.relative_to(app.state.storage.root) in planned_originals
        assert checkpoint_dir.relative_to(app.state.storage.root) in planned_originals
        assert any(
            not (app.state.storage.root / row.original_relative_path).exists()
            and (app.state.storage.root / row.staged_relative_path).exists()
            for row in pending
        )

    monkeypatch.setattr(matches_routes, "_after_stage_rename", lambda: None)
    restarted = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        _assert_error(
            await client.get(f"/api/v1/matches/{match_id}"),
            404,
            "match_not_found",
        )
    with restarted.state.database.session() as session:
        assert session.scalar(
            select(PendingDeletion.id).where(
                PendingDeletion.match_public_id == match_id
            )
        ) is None
    assert not list(restarted.state.storage.root.rglob("*.deleting"))
    assert not cache_namespace.exists()
    assert not worker_dir.exists()
    assert not checkpoint_dir.exists()
    assert outside.read_bytes() == b"outside"


@pytest.mark.asyncio
async def test_ordinary_staging_failure_restores_active_match_and_clears_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    original_stage = matches_routes._stage_deletion_path
    stage_calls = 0

    def fail_stage(original: Path, staged: Path) -> None:
        nonlocal stage_calls
        stage_calls += 1
        if stage_calls == 2:
            raise OSError("simulated staging failure")
        original_stage(original, staged)

    monkeypatch.setattr(
        matches_routes,
        "_stage_deletion_path",
        fail_stage,
        raising=False,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/api/v1/matches/{match_id}")
        _assert_error(response, 503, "deletion_staging_failed")
        assert stage_calls == 2
        assert (
            await client.get(f"/api/v1/matches/{match_id}")
        ).status_code == 200
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        assert getattr(match, "deletion_state") == "active"
        assert session.scalar(
            select(PendingDeletion.id).where(
                PendingDeletion.match_public_id == match_id
            )
        ) is None
    assert (
        app.state.storage.root / "videos/original/original.mp4"
    ).read_bytes() == b"original"
    assert (
        app.state.storage.root / "videos/proxy/proxy.mp4"
    ).read_bytes() == b"proxy"


@pytest.mark.asyncio
async def test_retry_cannot_reactivate_job_after_deletion_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(_settings(tmp_path))
    match_id, _ = _seed_match(app)
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        proxy = session.scalar(
            select(MediaAsset).where(
                MediaAsset.match_id == match.id,
                MediaAsset.kind == AssetKind.PROXY,
            )
        )
        assert proxy is not None
        job = AnalysisJob(
            match=match,
            source_media_asset=proxy,
            processing_profile=ProcessingProfile.BALANCED,
            status=JobStatus.CANCELLED,
            version=2,
        )
        session.add(job)
        session.flush()
        job_id = job.public_id

    entered = Event()
    release = Event()
    original_stage = matches_routes._stage_deletion_path

    def blocking_stage(original: Path, staged: Path) -> None:
        entered.set()
        assert release.wait(timeout=5)
        original_stage(original, staged)

    monkeypatch.setattr(matches_routes, "_stage_deletion_path", blocking_stage)
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as delete_client,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as retry_client,
    ):
        delete_task = asyncio.create_task(
            delete_client.delete(f"/api/v1/matches/{match_id}")
        )
        assert await asyncio.to_thread(entered.wait, 5)
        retry = await retry_client.post(f"/api/v1/jobs/{job_id}/retry")
        release.set()
        deleted = await delete_task
        _assert_error(retry, 409, "match_deleting")
    assert deleted.status_code == 204
