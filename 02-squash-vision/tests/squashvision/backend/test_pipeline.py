from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))
from squashvision.observations import (
    APPEARANCE_DIMENSION,
    BallCandidate,
    BallObservation,
    BoundingBox,
    EvidenceKind,
    Frame,
    FrameBatch,
    Keypoint,
    PlayerObservation,
    read_ball_observations,
    write_ball_observations,
    write_player_observations,
)

from squashvision.db import Database
from squashvision.jobs import JobQueue, PlannedChunk, TimeRange
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    BallInputMode,
    JobStatus,
    Calibration,
    Match,
    MediaAsset,
    ProcessingProfile,
    Stage,
    StageStatus,
)
from squashvision.pipeline import (
    ARTIFACT_SCHEMA_VERSIONS,
    AnalysisPipeline,
    ArtifactStore,
    DegradableStageError,
    EssentialStageError,
    PipelineContext,
    ExactTimestampIndex,
    PlayerBoundaryState,
    PROFILE_CONFIGS,
    StageExecution,
    StagePayload,
    _TimestampIndex,
    _support_provenance,
    _nearest_source_frame,
    _calibration_result_from_record,
    canonical_hash,
    reconcile_ball_seam,
    reconcile_player_boundary,
    stage_input_hash,
    normalize_audio_frame,
)
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
from squashvision.worker import Worker


POSE_A = {
    "manifest_id": "pose-a",
    "digest": "1" * 64,
    "revision": "pose-r1",
}
BALL_A = {
    "manifest_id": "ball-a",
    "digest": "2" * 64,
    "revision": "ball-r1",
}


def context(**changes: object) -> PipelineContext:
    values: dict[str, object] = {
        "match_public_id": "match-1",
        "duration_us": 3_600_000_000,
        "source_checksum": "3" * 64,
        "proxy_checksum": "4" * 64,
        "timestamp_map_hash": "5" * 64,
        "models": {"pose": POSE_A, "ball": BALL_A},
        "calibration_revision": 7,
        "calibration_capabilities": {
            "image_space": True,
            "floor_position": True,
            "movement_distance": True,
            "speed": True,
        },
    }
    values.update(changes)
    return PipelineContext(**values)


def job(
    profile: ProcessingProfile = ProcessingProfile.BALANCED,
    *,
    job_id: str = "job-1",
) -> AnalysisJob:
    match = Match(public_id="match-1", name="Pipeline")
    return AnalysisJob(
        public_id=job_id,
        match=match,
        processing_profile=profile,
        source_media_asset_id=1,
        match_id=1,
    )



def test_player_roi_invalidates_player_and_derived_hashes_without_recomputing_ball() -> None:
    region = {"revision": 1, "sourceSha256": "3" * 64,
              "frameSize": {"width": 1280, "height": 720},
              "points": [{"x": x, "y": y} for x, y in [(374, 384), (902, 384), (1075, 719), (202, 719)]]}
    baseline = context()
    masked = context(player_roi=region)
    for stage in Stage:
        before = stage_input_hash(stage, baseline, ProcessingProfile.MAXIMUM, ())
        after = stage_input_hash(stage, masked, ProcessingProfile.MAXIMUM, ())
        assert (before != after) == (stage in {Stage.PLAYERS, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT})


def test_streaming_preserves_720p_contract_but_invalidates_changed_image_geometry() -> None:
    legacy = context()
    native = context(source_frame_size=(1280, 720))
    high_res = context(source_frame_size=(3840, 2160))
    rotated = context(source_frame_size=(720, 1280), source_rotation=90)
    for stage in Stage:
        baseline = stage_input_hash(stage, legacy, ProcessingProfile.MAXIMUM, ())
        assert stage_input_hash(stage, native, ProcessingProfile.MAXIMUM, ()) == baseline
        assert stage_input_hash(stage, high_res, ProcessingProfile.MAXIMUM, ()) != baseline
        assert stage_input_hash(stage, rotated, ProcessingProfile.MAXIMUM, ()) != baseline
        # These profiles already used the proxy; its content hash identifies
        # any changed preparation dimensions without invalidating existing media.
        assert stage_input_hash(stage, high_res, ProcessingProfile.BALANCED, ()) == stage_input_hash(stage, legacy, ProcessingProfile.BALANCED, ())


def test_player_identity_policy_invalidates_only_player_and_derived_plan_contracts(tmp_path: Path, monkeypatch) -> None:
    import squashvision.vision.players as players_module
    current = context(duration_us=65_000_000)
    pipeline = AnalysisPipeline(storage_root=tmp_path, context_provider=lambda *_: current)
    match = job(ProcessingProfile.MAXIMUM).match
    before = pipeline.plan(match, ProcessingProfile.MAXIMUM)
    monkeypatch.setattr(players_module, "PLAYER_IDENTITY_POLICY_VERSION", "test-next-identity-policy")
    after = pipeline.plan(match, ProcessingProfile.MAXIMUM)
    for old, new in zip(before.chunks, after.chunks, strict=True):
        assert (old.dependency_hash != new.dependency_hash) == (old.stage in {
            Stage.PLAYERS, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT,
        })


def test_ball_photometry_changes_only_ball_and_derived_contracts(tmp_path: Path, monkeypatch) -> None:
    import squashvision.vision.players as players_module
    original = context(duration_us=65_000_000)
    inverted = replace(original, ball_input_mode=BallInputMode.INVERTED)
    match = job(ProcessingProfile.MAXIMUM).match
    pipeline = AnalysisPipeline(storage_root=tmp_path, context_provider=lambda *_: original)
    before = pipeline.plan(match, ProcessingProfile.MAXIMUM)
    pipeline._context_provider = lambda *_: inverted
    changed = pipeline.plan(match, ProcessingProfile.MAXIMUM)
    for old, new in zip(before.chunks, changed.chunks, strict=True):
        assert (old.dependency_hash != new.dependency_hash) == (old.stage in {
            Stage.BALL, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT,
        })
    # Inverted mode's original-image support mask consumes player boxes, so a
    # changed pose policy must also invalidate its ball results and descendants.
    monkeypatch.setattr(players_module, "PLAYER_IDENTITY_POLICY_VERSION", "test-new-pose-policy")
    after_pose = pipeline.plan(match, ProcessingProfile.MAXIMUM)
    for old, new in zip(changed.chunks, after_pose.chunks, strict=True):
        assert (old.dependency_hash != new.dependency_hash) == (old.stage in {
            Stage.PLAYERS, Stage.BALL, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT,
        })


@pytest.mark.parametrize("mode", [BallInputMode.ORIGINAL, BallInputMode.INVERTED])
def test_ball_input_transform_preserves_original_guard_pixels_and_observation_provenance(tmp_path: Path, monkeypatch, mode) -> None:
    import numpy as np
    import squashvision.vision.ball as ball_module
    import squashvision.vision.ball.contrast_support as support_module
    captured = {}
    frames = FrameBatch(tuple(Frame(timestamp_us=index * 10_000, source_frame_index=index,
        image=np.full((4, 4, 3), value, dtype=np.uint8))
        for index, value in enumerate((10, 20, 30, 40))))
    row = replace(_ball_point(30_000, 2.0, 2.0), source_frame_index=3)

    class FakeTracker:
        device = SimpleNamespace(type="cpu")
        device_fallback = False
        def __init__(self, **kwargs):
            captured["model_manifest_id"] = kwargs["model_manifest_id"]
        def track(self, incoming, background):
            captured["inputs"] = [int(frame.image[0, 0, 0]) for frame in incoming]
            captured["background"] = int(background[0, 0, 0])
            return (row,)

    class FakeSupport:
        def __init__(self, background, player_rows):
            captured["guard_background"] = int(background[0, 0, 0])
            assert player_rows
        def filter_rows(self, rows, incoming):
            captured["guard_inputs"] = [int(frame.image[0, 0, 0]) for frame in incoming]
            # A rejected detector observation must not survive in published
            # Parquet merely because the raw heatmap considered it visible.
            return tuple(replace(item, visible=False, x=None, y=None,
                covariance=None, probability=0.0, candidates=(), candidate_count=0,
                ambiguous=True, ambiguity_reason="dark_motion_support_rejected") for item in rows)

    monkeypatch.setattr(ball_module.TrackNetV3, "load", lambda *_, **__: object())
    monkeypatch.setattr(ball_module, "BallTracker", FakeTracker)
    monkeypatch.setattr(support_module, "DarkBallSupport", FakeSupport)
    current = context(duration_us=40_000, model_assets={"ball": object()}, ball_input_mode=mode)
    pipeline = AnalysisPipeline(storage_root=tmp_path, context_provider=lambda *_: current)
    monkeypatch.setattr(pipeline, "_decode_frames", lambda *_, **__: frames)
    monkeypatch.setattr(pipeline, "_iter_frame_batches", lambda *_, **__: iter((frames,)))
    monkeypatch.setattr(pipeline, "_iter_decoded_frames", lambda *_, **__: iter(frames))
    monkeypatch.setattr(pipeline, "_player_rows", lambda *_: ((object(),), ()))
    execution = StageExecution(job=job(), stage=Stage.BALL, chunk=TimeRange(0, 40_000),
        profile_config=PROFILE_CONFIGS[ProcessingProfile.BALANCED], context=current,
        upstream=(), input_hash="a" * 64, config_hash="b" * 64)
    payload = pipeline._ball(execution)
    path = tmp_path / "ball.parquet"
    path.write_bytes(payload.data)
    saved = read_ball_observations(path)
    assert captured["model_manifest_id"] == BALL_A["manifest_id"]
    assert saved[0].source_frame_index == 3
    assert saved[0].timestamp_us == row.timestamp_us
    assert all(int(frame.image[0, 0, 0]) == value for frame, value in zip(frames, (10, 20, 30, 40)))
    if mode is BallInputMode.INVERTED:
        assert captured["inputs"] == [245, 235, 225, 215]
        assert captured["background"] == 230
        assert captured["guard_inputs"] == [10, 20, 30, 40]
        assert captured["guard_background"] == 25
        assert not saved[0].visible and not saved[0].candidates
        assert "input-transform:uint8_invert_all_frames_and_median_v1" in payload.evidence
    else:
        assert captured["inputs"] == [10, 20, 30, 40]
        assert captured["background"] == 25
        assert "guard_inputs" not in captured
        assert saved[0].visible


def test_players_pipeline_scales_source_roi_for_proxy_without_calibrating(tmp_path: Path, monkeypatch) -> None:
    import numpy as np
    from squashvision.observations import PoseDetections
    import squashvision.vision.players as players_module

    captured = {}
    class Detector:
        def __init__(self, asset, *, storage_root, playing_area_polygon, inference_batch_size):
            captured["polygon"] = playing_area_polygon
            assert inference_batch_size == PROFILE_CONFIGS[ProcessingProfile.BALANCED].inference_batch_size
        def detect(self, frames):
            return [PoseDetections(timestamp_us=0, frame_index=0, detections=(), device="cpu", device_fallback=False)]

    region = {"revision": 1, "sourceSha256": "3" * 64,
              "frameSize": {"width": 1280, "height": 720},
              "points": [{"x": x, "y": y} for x, y in [(374, 384), (902, 384), (1075, 719), (202, 719)]]}
    current = context(player_roi=region, model_assets={"pose": object()})
    pipeline = AnalysisPipeline(storage_root=tmp_path, context_provider=lambda *_: current)
    monkeypatch.setattr(players_module, "PlayerDetector", Detector)
    monkeypatch.setattr(pipeline, "_iter_frame_batches", lambda *_, **__: iter((FrameBatch((
        Frame(timestamp_us=0, source_frame_index=0, image=np.zeros((360, 640, 3), dtype=np.uint8)),)),)))
    execution = StageExecution(job=job(), stage=Stage.PLAYERS, chunk=TimeRange(0, 40_000),
        profile_config=PROFILE_CONFIGS[ProcessingProfile.BALANCED], context=current,
        upstream=(), input_hash="a" * 64, config_hash="b" * 64)
    result = pipeline._players(execution)
    np.testing.assert_allclose(captured["polygon"], [[187, 192], [451, 192], [537.5, 359.5], [101, 359.5]])
    assert current.calibration is None
    assert any(value.startswith("manual-image-playing-area:") for value in result.evidence)


def test_persisted_api_calibration_aliases_restore_pipeline_context() -> None:
    restored = _calibration_result_from_record({
        "calibrated": True,
        "imageToCourt": [[0.064, 0.0, 0.0], [0.0, 0.0975, 0.0], [0.0, 0.0, 1.0]],
        "courtToImage": [[15.625, 0.0, 0.0], [0.0, 10.256410256, 0.0], [0.0, 0.0, 1.0]],
        "residualsPx": [1.0, 1.0, 1.0, 1.0],
        "rmsErrorPx": 1.0,
        "maxErrorPx": 1.0,
        "inlierMask": [True, True, True, True],
        "conditionNumber": 1.0,
        "parameterCovariance": None,
        "confidence": 0.95,
        "capabilities": {
            "imageSpace": True,
            "floorPosition": True,
            "movementDistance": True,
            "speed": True,
        },
        "warnings": [],
    })

    assert restored.calibrated is True
    assert restored.image_to_court is not None
    assert restored.capabilities.floor_position is True

def test_profile_plan_is_bounded_deterministic_and_gap_free_for_one_hour(
    tmp_path: Path,
) -> None:
    current = context()
    pipeline = AnalysisPipeline(
        storage_root=tmp_path,
        context_provider=lambda _match, _profile: current,
        stage_adapters={},
    )

    expected = {
        ProcessingProfile.FAST: (2, 120_000_000, 1_000_000, 60_000_000),
        ProcessingProfile.BALANCED: (1, 90_000_000, 2_000_000, 45_000_000),
        ProcessingProfile.MAXIMUM: (1, 60_000_000, 3_000_000, 30_000_000),
    }
    for profile, (stride, player_size, overlap, ball_size) in expected.items():
        first = pipeline.plan(job(profile).match, profile)
        second = pipeline.plan(job(profile).match, profile)
        assert first == second
        assert [stage.value for stage in first.stage_order] == [
            "prepare",
            "calibration",
            "players",
            "ball",
            "events",
            "classification",
            "report",
        ]
        assert first.profile_config.player_stride == stride
        assert first.profile_config.player_chunk_us == player_size
        assert first.profile_config.ball_chunk_us == ball_size
        assert first.profile_config.overlap_us == overlap
        assert len(first.chunks) < 250

        for stage in (Stage.PLAYERS, Stage.BALL):
            ranges = [chunk.time_range for chunk in first.chunks if chunk.stage is stage]
            assert ranges[0].start_us == 0
            assert ranges[-1].end_us == current.duration_us
            assert all(0 <= item.start_us < item.end_us <= current.duration_us for item in ranges)
            assert all(left.end_us >= right.start_us for left, right in zip(ranges, ranges[1:]))
            assert all(
                left.end_us - right.start_us == overlap
                for left, right in zip(ranges, ranges[1:])
            )

        for stage in (
            Stage.PREPARE,
            Stage.CALIBRATION,
            Stage.EVENTS,
            Stage.CLASSIFICATION,
            Stage.REPORT,
        ):
            assert [chunk.time_range for chunk in first.chunks if chunk.stage is stage] == [
                TimeRange(0, current.duration_us)
            ]


def test_input_hash_tracks_exact_dependencies_and_player_ignores_calibration() -> None:
    base = context()
    upstream = ("a" * 64, "b" * 64)
    player = stage_input_hash(Stage.PLAYERS, base, ProcessingProfile.BALANCED, upstream)
    edited_calibration = replace(base, calibration_revision=8)
    assert stage_input_hash(
        Stage.PLAYERS, edited_calibration, ProcessingProfile.BALANCED, upstream
    ) == player
    assert stage_input_hash(
        Stage.BALL, edited_calibration, ProcessingProfile.BALANCED, upstream
    ) != stage_input_hash(Stage.BALL, base, ProcessingProfile.BALANCED, upstream)

    changed_pose = replace(
        base,
        models={**base.models, "pose": {**POSE_A, "digest": "6" * 64}},
    )
    changed_ball = replace(
        base,
        models={**base.models, "ball": {**BALL_A, "digest": "7" * 64}},
    )
    assert stage_input_hash(Stage.PLAYERS, changed_pose, ProcessingProfile.BALANCED, ()) != stage_input_hash(
        Stage.PLAYERS, base, ProcessingProfile.BALANCED, ()
    )
    assert stage_input_hash(Stage.PLAYERS, changed_ball, ProcessingProfile.BALANCED, ()) == stage_input_hash(
        Stage.PLAYERS, base, ProcessingProfile.BALANCED, ()
    )
    assert stage_input_hash(Stage.BALL, changed_ball, ProcessingProfile.BALANCED, ()) != stage_input_hash(
        Stage.BALL, base, ProcessingProfile.BALANCED, ()
    )
    assert stage_input_hash(
        Stage.BALL, changed_pose, ProcessingProfile.BALANCED, ()
    ) == stage_input_hash(Stage.BALL, base, ProcessingProfile.BALANCED, ())
    assert stage_input_hash(
        Stage.PREPARE, changed_pose, ProcessingProfile.BALANCED, ()
    ) != stage_input_hash(Stage.PREPARE, base, ProcessingProfile.BALANCED, ())
    assert stage_input_hash(
        Stage.PREPARE, changed_ball, ProcessingProfile.BALANCED, ()
    ) != stage_input_hash(Stage.PREPARE, base, ProcessingProfile.BALANCED, ())
    assert stage_input_hash(
        Stage.CALIBRATION,
        edited_calibration,
        ProcessingProfile.BALANCED,
        (),
    ) != stage_input_hash(
        Stage.CALIBRATION, base, ProcessingProfile.BALANCED, ()
    )
    assert stage_input_hash(Stage.EVENTS, changed_ball, ProcessingProfile.BALANCED, upstream) != stage_input_hash(
        Stage.EVENTS, base, ProcessingProfile.BALANCED, upstream
    )

    assert stage_input_hash(
        Stage.REPORT,
        replace(base, timestamp_map_hash="8" * 64),
        ProcessingProfile.BALANCED,
        upstream,
    ) != stage_input_hash(Stage.REPORT, base, ProcessingProfile.BALANCED, upstream)
    assert stage_input_hash(
        Stage.REPORT, base, ProcessingProfile.MAXIMUM, upstream
    ) != stage_input_hash(Stage.REPORT, base, ProcessingProfile.BALANCED, upstream)
    assert stage_input_hash(
        Stage.REPORT,
        base,
        ProcessingProfile.BALANCED,
        tuple(reversed(upstream)),
    ) == stage_input_hash(Stage.REPORT, base, ProcessingProfile.BALANCED, upstream)
    assert stage_input_hash(
        Stage.PREPARE,
        replace(base, source_checksum="9" * 64),
        ProcessingProfile.BALANCED,
        (),
    ) != stage_input_hash(Stage.PREPARE, base, ProcessingProfile.BALANCED, ())
    assert stage_input_hash(
        Stage.PREPARE,
        replace(base, proxy_checksum="0" * 64),
        ProcessingProfile.BALANCED,
        (),
    ) != stage_input_hash(Stage.PREPARE, base, ProcessingProfile.BALANCED, ())
    assert stage_input_hash(
        Stage.PREPARE,
        base,
        ProcessingProfile.BALANCED,
        (),
        artifact_schema_version=2,
    ) != stage_input_hash(Stage.PREPARE, base, ProcessingProfile.BALANCED, ())


def test_artifact_store_reuses_only_valid_exact_hash_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "cache")
    input_hash = canonical_hash({"source": "source-a", "stage": "prepare"})
    payload = StagePayload(
        data=b'{"prepared":true}',
        suffix=".json",
        availability="available",
        evidence=("source-verified",),
        row_count=1,
    )
    envelope = store.publish(
        stage=Stage.PREPARE,
        input_hash=input_hash,
        match_id="match-1",
        job_id="job-1",
        profile=ProcessingProfile.BALANCED,
        chunk=TimeRange(0, 5_000_000),
        context=context(duration_us=5_000_000),
        upstream_hashes=(),
        config_hash=canonical_hash({"prepare": 1}),
        payload=payload,
    )
    reused = store.load("match-1", Stage.PREPARE, input_hash)
    assert reused is not None
    assert reused.reused is True
    assert reused.envelope.payload_sha256 == envelope.envelope.payload_sha256
    assert reused.envelope.schema_version == ARTIFACT_SCHEMA_VERSIONS[Stage.PREPARE]
    mismatched_match = store.publish(
        stage=Stage.PREPARE,
        input_hash=input_hash,
        match_id="match-2",
        job_id="job-other",
        profile=ProcessingProfile.BALANCED,
        chunk=TimeRange(0, 5_000_000),
        context=replace(
            context(duration_us=5_000_000),
            match_public_id="match-2",
        ),
        upstream_hashes=(),
        config_hash=canonical_hash({"prepare": 1}),
        payload=payload,
    )
    assert mismatched_match.reused is False
    assert mismatched_match.envelope.match_id == "match-2"

    reused.payload_path.write_bytes(b"corrupt")
    assert store.load("match-1", Stage.PREPARE, input_hash) is None
    assert store.load("match-2", Stage.PREPARE, input_hash) is not None

    repaired = store.publish(
        stage=Stage.PREPARE,
        input_hash=input_hash,
        match_id="match-1",
        job_id="job-2",
        profile=ProcessingProfile.BALANCED,
        chunk=TimeRange(0, 5_000_000),
        context=context(duration_us=5_000_000),
        upstream_hashes=(),
        config_hash=canonical_hash({"prepare": 1}),
        payload=payload,
    )
    raw = json.loads(repaired.path.read_text(encoding="utf-8"))
    raw["input_hash"] = "f" * 64
    repaired.path.write_text(json.dumps(raw), encoding="utf-8")
    assert store.load("match-1", Stage.PREPARE, input_hash) is None


def test_reconciliation_is_provenance_safe_and_ball_seams_do_not_bridge_long_gaps() -> None:
    mapped = reconcile_player_boundary(
        previous=[
            {"timestamp_us": 9, "frame_index": 9, "player_id": "A", "appearance": [1.0, 0.0]},
            {"timestamp_us": 9, "frame_index": 9, "player_id": "B", "appearance": [0.0, 1.0]},
        ],
        current=[
            {"timestamp_us": 9, "frame_index": 9, "player_id": "A", "appearance": [0.0, 1.0]},
            {"timestamp_us": 9, "frame_index": 9, "player_id": "B", "appearance": [1.0, 0.0]},
        ],
    )
    assert mapped.mapping == {"A": "B", "B": "A"}
    assert mapped.ambiguous is False
    ambiguous = reconcile_player_boundary(previous=[], current=[])
    assert ambiguous.ambiguous is True

    rows = reconcile_ball_seam(
        [
            {"timestamp_us": 100_000, "frame_index": 1, "model_manifest_id": "ball", "confidence": 0.5, "x": 1.0},
            {"timestamp_us": 100_000, "frame_index": 1, "model_manifest_id": "ball", "confidence": 0.9, "x": 2.0},
            {"timestamp_us": 500_001, "frame_index": 2, "model_manifest_id": "ball", "confidence": 0.8, "x": 3.0},
        ]
    )
    assert [(row["timestamp_us"], row["x"]) for row in rows.rows] == [
        (100_000, 2.0),
        (500_001, 3.0),
    ]
    assert rows.segments == ((100_000,), (500_001,))


def test_ball_failure_is_published_as_explicit_unavailable_artifact(
    tmp_path: Path,
) -> None:
    calls = 0

    def fail_ball(_execution: object) -> StagePayload:
        nonlocal calls
        calls += 1
        raise DegradableStageError("ball_inference_failed", "trusted ball model failed")

    current = context(duration_us=5_000_000)
    pipeline = AnalysisPipeline(
        storage_root=tmp_path,
        context_provider=lambda _match, _profile: current,
        stage_adapters={Stage.BALL: fail_ball},
    )
    artifact = pipeline.run_chunk(
        job(), Stage.BALL, TimeRange(0, current.duration_us)
    )
    assert calls == 1
    assert artifact.envelope.availability == "unavailable"
    assert artifact.envelope.errors == ("ball_inference_failed: trusted ball model failed",)
    assert artifact.envelope.row_count == 0
    assert artifact.payload_path.read_bytes() == b""

    reused = pipeline.run_chunk(
        job(job_id="job-2"),
        Stage.BALL,
        TimeRange(0, current.duration_us),
    )
    assert calls == 1
    assert reused.reused is True
    assert reused.envelope.availability == "unavailable"


def test_job_chunk_contract_restart_and_targeted_invalidation(tmp_path: Path) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    queue = JobQueue(database, storage)
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Chunk contracts")
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy.relative),
                ),
            ]
        )
        session.flush()
        match_id = match.public_id
    queued = queue.enqueue(match_id, ProcessingProfile.BALANCED)
    claimed = queue.claim("pipeline-worker")
    assert claimed is not None and claimed.claim_token is not None

    base = [
        PlannedChunk(
            Stage.PLAYERS,
            TimeRange(0, 5_000_000),
            plan_hash="1" * 64,
            input_hash="2" * 64,
            dependency_hash="3" * 64,
            config_hash="4" * 64,
            artifact_schema_version=1,
        ),
        PlannedChunk(
            Stage.BALL,
            TimeRange(0, 5_000_000),
            plan_hash="1" * 64,
            input_hash="5" * 64,
            dependency_hash="6" * 64,
            config_hash="7" * 64,
            artifact_schema_version=1,
        ),
        PlannedChunk(
            Stage.EVENTS,
            TimeRange(0, 5_000_000),
            plan_hash="1" * 64,
            input_hash="8" * 64,
            dependency_hash="9" * 64,
            config_hash="a" * 64,
            artifact_schema_version=1,
        ),
    ]
    queue.plan_claimed(
        queued.public_id,
        "pipeline-worker",
        claimed.claim_token,
        base,
    )
    for planned in base:
        queue.start_chunk_claimed(
            queued.public_id,
            planned.stage,
            planned.time_range,
            "pipeline-worker",
            claimed.claim_token,
        )
        artifact = tmp_path / f"{planned.stage.value}.artifact"
        artifact.write_bytes(planned.stage.value.encode())
        queue.checkpoint_claimed(
            queued.public_id,
            planned.stage,
            planned.time_range,
            artifact,
            "pipeline-worker",
            claimed.claim_token,
        )

    changed = [
        base[0],
        replace(base[1], input_hash="b" * 64, dependency_hash="c" * 64),
        replace(base[2], input_hash="d" * 64, dependency_hash="e" * 64),
    ]
    reconciled = queue.reconcile_plan_claimed(
        queued.public_id,
        "pipeline-worker",
        claimed.claim_token,
        changed,
    )
    assert [row.status for row in reconciled] == [
        StageStatus.COMPLETED,
        StageStatus.INVALIDATED,
        StageStatus.INVALIDATED,
    ]
    assert reconciled[0].input_hash == "2" * 64
    assert reconciled[1].input_hash == "b" * 64
    assert queue.next_chunk(queued.public_id) == changed[1]

    with database.session() as session:
        stored = session.get(AnalysisJob, queued.id)
        assert stored is not None
        assert stored.status is JobStatus.RUNNING


def test_worker_reconciles_exact_contract_before_running_existing_plan(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    queue = JobQueue(database, storage)
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Worker contract")
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy.relative),
                ),
            ]
        )
        session.flush()
        match_id = match.public_id
    queued = queue.enqueue(match_id, ProcessingProfile.BALANCED)
    old = PlannedChunk(
        Stage.PREPARE,
        TimeRange(0, 5_000_000),
        plan_hash="1" * 64,
        input_hash="2" * 64,
        dependency_hash="3" * 64,
        config_hash="4" * 64,
        artifact_schema_version=1,
    )
    current = replace(old, input_hash="5" * 64, dependency_hash="6" * 64)
    queue.plan(queued.public_id, [old])

    class ContractHandler:
        def plan(self, _job: AnalysisJob) -> list[PlannedChunk]:
            return [replace(current, input_hash=None)]

        def chunk_contract(
            self, _job: AnalysisJob, _stage: Stage, _chunk: TimeRange
        ) -> PlannedChunk:
            return current

        def run(
            self,
            _job: AnalysisJob,
            _stage: Stage,
            _chunk: TimeRange,
            artifact: Path,
        ) -> Path:
            artifact.write_bytes(b"verified")
            return artifact

    worker = Worker(queue, "exact-worker", ContractHandler())
    assert worker.run_once()
    stored = queue.find_chunk(
        queued.public_id, Stage.PREPARE, TimeRange(0, 5_000_000)
    )
    assert stored.status is StageStatus.COMPLETED
    assert stored.input_hash == "5" * 64
    assert stored.dependency_hash == "6" * 64


def test_worker_marks_essential_planning_failure_failed_without_weakening_claim_fence(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    queue = JobQueue(database, storage)
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Essential failure")
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy.relative),
                ),
            ]
        )
        session.flush()
        match_id = match.public_id
    queued = queue.enqueue(match_id, ProcessingProfile.FAST)

    class FailingHandler:
        def plan(self, _job: AnalysisJob) -> list[PlannedChunk]:
            raise EssentialStageError(
                "pose_model_unavailable", "approved pose model is missing"
            )

        def run(
            self,
            _job: AnalysisJob,
            _stage: Stage,
            _chunk: TimeRange,
            artifact: Path,
        ) -> Path:
            raise AssertionError("run must not be reached")

    worker = Worker(queue, "essential-worker", FailingHandler())
    with pytest.raises(EssentialStageError, match="pose_model_unavailable"):
        worker.run_once()
    failed = queue.get(queued.public_id)
    assert failed.status is JobStatus.FAILED
    assert failed.failure_code == "pose_model_unavailable"
    assert failed.worker_id is None
    assert failed.claim_token is None


def _ball_point(timestamp_us: int, x: float, y: float) -> BallObservation:
    covariance = ((1.0, 0.0), (0.0, 1.0))
    candidate = BallCandidate(
        x=x,
        y=y,
        peak_probability=0.95,
        integrated_probability=0.95,
        area=3,
        circularity=0.9,
        covariance=covariance,
    )
    frame_index = timestamp_us // 10_000
    return BallObservation(
        timestamp_us=timestamp_us,
        source_timestamp_us=timestamp_us,
        source_frame_index=frame_index,
        source_width=100,
        source_height=100,
        x=x,
        y=y,
        probability=0.95,
        covariance=covariance,
        visible=True,
        candidate_count=1,
        candidates=(candidate,),
        evidence=EvidenceKind.OBSERVED,
        evidence_start_timestamp_us=timestamp_us,
        evidence_end_timestamp_us=timestamp_us,
        evidence_start_frame_index=frame_index,
        evidence_end_frame_index=frame_index,
        ambiguous=False,
        ambiguity_reason=None,
        segment_id="segment-0001",
        source_manifest_id="4" * 64,
        model_manifest_id="ball-a",
        device="cpu",
        device_fallback=False,
    )


def test_fast_ball_stage_preserves_total_candidate_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np
    import squashvision.vision.ball as ball_module

    candidates = tuple(
        BallCandidate(
            x=10.0 + index,
            y=20.0,
            peak_probability=0.9 - index * 0.1,
            integrated_probability=0.9 - index * 0.1,
            area=3,
            circularity=0.9,
            covariance=((1.0, 0.0), (0.0, 1.0)),
        )
        for index in range(3)
    )
    tracked = replace(
        _ball_point(10_000, 10.0, 20.0),
        candidate_count=3,
        candidates=candidates,
    )

    class FakeTracker:
        device = SimpleNamespace(type="cpu")
        device_fallback = False

        def __init__(self, **_values: object) -> None:
            pass

        def track(
            self, _frames: FrameBatch, _background: object
        ) -> tuple[BallObservation, ...]:
            return (tracked,)

    monkeypatch.setattr(ball_module.TrackNetV3, "load", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(ball_module, "BallTracker", FakeTracker)
    current = context(
        duration_us=40_000,
        model_assets={"ball": object()},
    )
    pipeline = AnalysisPipeline(
        storage_root=tmp_path,
        context_provider=lambda _match, _profile: current,
    )
    monkeypatch.setattr(
        pipeline,
        "_decode_frames",
        lambda *_args, **_kwargs: FrameBatch(
            (
                Frame(
                    timestamp_us=10_000,
                    source_frame_index=1,
                    image=np.zeros((4, 4, 3), dtype=np.uint8),
                ),
            )
        ),
    )
    execution = StageExecution(
        job=job(ProcessingProfile.FAST),
        stage=Stage.BALL,
        chunk=TimeRange(0, 40_000),
        profile_config=PROFILE_CONFIGS[ProcessingProfile.FAST],
        context=current,
        upstream=(),
        input_hash="a" * 64,
        config_hash="b" * 64,
    )

    monkeypatch.setattr(pipeline, "_iter_frame_batches", lambda *_, **__: iter((
        pipeline._decode_frames(execution, stride=1),)))
    payload = pipeline._ball(execution)
    artifact = tmp_path / "fast-ball.parquet"
    artifact.write_bytes(payload.data)
    rows = read_ball_observations(artifact)

    assert rows[0].candidate_count == 3


def test_rally_racket_context_restarts_position_and_serve_for_every_rally() -> None:
    import squashvision.pipeline as pipeline_module

    rackets = tuple(
        SimpleNamespace(contact_id=f"contact-{index}", timestamp_us=timestamp)
        for index, timestamp in enumerate((100, 200, 1_100, 1_200), start=1)
    )
    rallies = (
        {
            "start": {"selected_us": 50},
            "end": {"selected_us": 250},
        },
        {
            "start": {"selected_us": 1_050},
            "end": {"selected_us": 1_250},
        },
    )

    contexts = pipeline_module._rally_racket_contexts(rackets, rallies)

    assert contexts == {
        "contact-1": (0, True),
        "contact-2": (1, False),
        "contact-3": (0, True),
        "contact-4": (1, False),
    }


def _player_point(timestamp_us: int) -> PlayerObservation:
    keypoints = [Keypoint(50.0, 50.0, 0.8) for _ in range(17)]
    keypoints[9] = Keypoint(50.0, 50.0, 0.95)
    keypoints[10] = Keypoint(50.0, 50.0, 0.95)
    return PlayerObservation(
        player_id="A",
        timestamp_us=timestamp_us,
        source_timestamp_us=timestamp_us,
        source_frame_index=timestamp_us // 10_000,
        box=BoundingBox(20.0, 10.0, 80.0, 95.0),
        keypoints=tuple(keypoints),
        detection_confidence=0.95,
        appearance=(0.0,) * APPEARANCE_DIMENSION,
        feet=(50.0, 95.0),
        feet_uncertainty_px=2.0,
        evidence=EvidenceKind.OBSERVED,
        evidence_start_timestamp_us=timestamp_us,
        evidence_end_timestamp_us=timestamp_us,
        evidence_start_frame_index=timestamp_us // 10_000,
        evidence_end_frame_index=timestamp_us // 10_000,
        association_confidence=0.9,
        ambiguous=False,
        ambiguity_reason=None,
        floor=None,
        source_manifest_id="4" * 64,
        model_manifest_id="pose-a",
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_player_chunk_overlap_prefers_observation_over_interpolated_same_time(monkeypatch, reverse) -> None:
    import squashvision.observations as observations
    observed = replace(_player_point(20_000), detection_confidence=0.4, association_confidence=0.5)
    reconstructed = replace(observed, evidence=EvidenceKind.INTERPOLATED,
        source_timestamp_us=None, source_frame_index=None,
        detection_confidence=0.99, association_confidence=0.99,
        evidence_start_timestamp_us=0, evidence_end_timestamp_us=40_000,
        evidence_start_frame_index=0, evidence_end_frame_index=4)
    other_player = replace(observed, player_id="B")
    chunks = [(reconstructed,), (observed, other_player)]
    if reverse:
        chunks.reverse()
    monkeypatch.setattr(observations, "read_player_observations", lambda path: chunks[path])
    execution = SimpleNamespace(upstream=tuple(SimpleNamespace(payload_path=index,
        envelope=SimpleNamespace(stage="players", availability="available")) for index in range(2)))
    merged, warnings = AnalysisPipeline._player_rows(execution)
    assert merged == (observed, other_player)
    assert warnings == ()


def test_player_publication_orders_retrospective_gap_estimates(tmp_path: Path, monkeypatch) -> None:
    import numpy as np
    from squashvision.observations import PoseDetections, read_player_observations
    import squashvision.vision.players as players_module

    class Detector:
        def __init__(self, *_, **__):
            pass
        def detect(self, frames):
            return [PoseDetections(timestamp_us=t, frame_index=t // 10_000,
                detections=(), device="cpu", device_fallback=False) for t in (20_000, 40_000)]

    retrospective = replace(_player_point(10_000), player_id="B", evidence=EvidenceKind.INTERPOLATED,
        source_timestamp_us=None, source_frame_index=None,
        evidence_start_timestamp_us=0, evidence_end_timestamp_us=40_000,
        evidence_start_frame_index=0, evidence_end_frame_index=4)
    class Tracker:
        def __init__(self, **_):
            pass
        def update(self, timestamp, detections):
            return (_player_point(20_000),) if timestamp == 20_000 else (retrospective, _player_point(40_000))

    current = context(model_assets={"pose": object()})
    pipeline = AnalysisPipeline(storage_root=tmp_path, context_provider=lambda *_: current)
    monkeypatch.setattr(players_module, "PlayerDetector", Detector)
    monkeypatch.setattr(players_module, "PlayerIdentityTracker", Tracker)
    monkeypatch.setattr(pipeline, "_iter_frame_batches", lambda *_, **__: iter((FrameBatch(tuple(
        Frame(timestamp_us=t, source_frame_index=t // 10_000, image=np.zeros((72, 128, 3), dtype=np.uint8))
        for t in (20_000, 40_000))),)))
    execution = StageExecution(job=job(), stage=Stage.PLAYERS, chunk=TimeRange(0, 50_000),
        profile_config=PROFILE_CONFIGS[ProcessingProfile.BALANCED], context=current,
        upstream=(), input_hash="a" * 64, config_hash="b" * 64)
    output = tmp_path / "ordered.parquet"
    output.write_bytes(pipeline._players(execution).data)
    rows = read_player_observations(output)
    assert [row.timestamp_us for row in rows] == [10_000, 20_000, 40_000]
    assert rows[0].evidence == EvidenceKind.INTERPOLATED


def test_support_provenance_distinguishes_interpolated_mixed_and_missing() -> None:
    observed = _ball_point(100_000, 10.0, 20.0)
    interpolated = replace(
        _ball_point(100_000, 11.0, 21.0),
        source_timestamp_us=None,
        source_frame_index=None,
        evidence=EvidenceKind.INTERPOLATED,
        evidence_start_timestamp_us=90_000,
        evidence_end_timestamp_us=110_000,
        evidence_start_frame_index=9,
        evidence_end_frame_index=11,
    )
    assert _support_provenance((100_000,), (interpolated,)) == "reconstructed"
    assert _support_provenance((100_000,), (observed, interpolated)) == "ambiguous"
    points = (
        _ball_point(0, 5.0, 5.0),
        _ball_point(100_000, 10.0, 10.0),
        _ball_point(200_000, 15.0, 15.0),
    )
    assert _nearest_source_frame(190_000, points) == 20


def test_timestamp_index_uses_binary_search_and_returns_only_bounded_slices() -> None:
    class Row:
        timestamp_reads = 0

        def __init__(self, timestamp_us: int) -> None:
            self._timestamp_us = timestamp_us

        @property
        def timestamp_us(self) -> int:
            type(self).timestamp_reads += 1
            return self._timestamp_us

    rows = tuple(Row(index * 1_000) for index in range(100_000))
    index = _TimestampIndex(rows)
    assert Row.timestamp_reads == len(rows)
    Row.timestamp_reads = 0

    for center in range(10_000_000, 90_000_000, 1_000_000):
        bounded = index.between(center - 5_000, center + 5_000)
        assert len(bounded) == 11
        assert index.nearest(center).timestamp_us == center
    assert Row.timestamp_reads == 80
    assert _support_provenance((100_000,), ()) == "unavailable"


def test_events_adapter_runs_real_seam_repair_contact_fusion_and_rally_state_machine(
    tmp_path: Path,
) -> None:
    player_file = tmp_path / "players.parquet"
    ball_file = tmp_path / "ball.parquet"
    write_player_observations(
        player_file,
        (_player_point(200_000),),
        source_manifest_id="4" * 64,
        model_manifest_id="pose-a",
    )
    write_ball_observations(
        ball_file,
        (
            _ball_point(150_000, 38.0, 50.0),
            _ball_point(200_000, 50.0, 50.0),
            _ball_point(250_000, 38.0, 51.0),
        ),
        source_manifest_id="4" * 64,
        model_manifest_id="ball-a",
    )
    adapters = {
        Stage.PLAYERS: lambda _execution: StagePayload(
            player_file.read_bytes(),
            ".parquet",
            "available",
            ("pose-inference",),
            row_count=1,
        ),
        Stage.BALL: lambda _execution: StagePayload(
            ball_file.read_bytes(),
            ".parquet",
            "available",
            ("tracknet-inference",),
            row_count=3,
        ),
    }
    from squashvision.calibration import CalibrationCapabilities, CalibrationResult

    strong_calibration = CalibrationResult(
        calibrated=True,
        image_to_court=((0.064, 0.0, 0.0), (0.0, 0.0975, 0.0), (0.0, 0.0, 1.0)),
        court_to_image=((15.625, 0.0, 0.0), (0.0, 10.256410256, 0.0), (0.0, 0.0, 1.0)),
        residuals_px=(1.0, 1.0, 1.0, 1.0),
        rms_error_px=1.0,
        max_error_px=1.0,
        inlier_mask=(True, True, True, True),
        condition_number=1.0,
        parameter_covariance=None,
        confidence=0.95,
        capabilities=CalibrationCapabilities(True, True, True, True),
        warnings=(),
    )
    current = replace(
        context(duration_us=1_000_000),
        calibration=strong_calibration,
    )
    pipeline = AnalysisPipeline(
        storage_root=tmp_path / "run",
        context_provider=lambda _match, _profile: current,
        stage_adapters=adapters,
    )
    analysis_job = job()
    whole = TimeRange(0, current.duration_us)
    pipeline.run_chunk(analysis_job, Stage.PLAYERS, whole)
    pipeline.run_chunk(analysis_job, Stage.BALL, whole)
    events = pipeline.run_chunk(analysis_job, Stage.EVENTS, whole)
    payload = json.loads(events.payload_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "ball-and-player"
    assert payload["ball_observation_count"] >= 3
    assert isinstance(payload["contacts"], list)
    assert "contact-fusion" in events.envelope.evidence
    classification = pipeline.run_chunk(
        analysis_job, Stage.CLASSIFICATION, whole
    )
    classified = json.loads(
        classification.payload_path.read_text(encoding="utf-8")
    )
    assert classified["trajectories"]
    trajectory_values = [
        value["trajectory"]
        for value in classified["trajectories"].values()
    ]
    assert all(
        "available" in value and "model" in value
        for value in trajectory_values
    )


def test_player_only_pipeline_publishes_movement_revision_without_fake_shots(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path / "db"))
    storage = LocalStorage(tmp_path / "db")
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Partial publication")
        proxy_row = MediaAsset(
            match=match,
            kind=AssetKind.PROXY,
            relative_path=str(proxy.relative),
        )
        analysis_job = AnalysisJob(
            match=match,
            source_media_asset=proxy_row,
            processing_profile=ProcessingProfile.BALANCED,
            status=JobStatus.RUNNING,
            worker_id="partial-worker",
            claim_token="11111111-1111-1111-1111-111111111111",
        )
        calibration_row = Calibration(
            match=match,
            media_asset=proxy_row,
            revision=7,
            frame_width=100,
            frame_height=100,
            keypoints=[],
            result={},
            confidence=0.95,
            capabilities={
                "image_space": True,
                "floor_position": True,
                "movement_distance": True,
                "speed": True,
            },
        )
        session.add_all([match, proxy_row, analysis_job, calibration_row])
        session.flush()
        match_id = match.public_id
        job_id = analysis_job.public_id

    player_file = tmp_path / "partial-players.parquet"
    write_player_observations(
        player_file,
        (
            _player_point(200_000),
            replace(
                _player_point(400_000),
                ambiguous=True,
                ambiguity_reason="crossing_identity",
            ),
        ),
        source_manifest_id="4" * 64,
        model_manifest_id="pose-a",
    )

    def fail_ball(_execution: object) -> StagePayload:
        raise DegradableStageError(
            "ball_inference_failed", "approved model could not infer"
        )

    from squashvision.calibration import CalibrationCapabilities, CalibrationResult

    strong_calibration = CalibrationResult(
        calibrated=True,
        image_to_court=(
            (0.064, 0.0, 0.0),
            (0.0, 0.0975, 0.0),
            (0.0, 0.0, 1.0),
        ),
        court_to_image=(
            (15.625, 0.0, 0.0),
            (0.0, 10.256410256, 0.0),
            (0.0, 0.0, 1.0),
        ),
        residuals_px=(1.0, 1.0, 1.0, 1.0),
        rms_error_px=1.0,
        max_error_px=1.0,
        inlier_mask=(True, True, True, True),
        condition_number=1.0,
        parameter_covariance=None,
        confidence=0.95,
        capabilities=CalibrationCapabilities(True, True, True, True),
        warnings=(),
    )
    current = replace(
        context(duration_us=1_000_000),
        match_public_id=match_id,
        calibration=strong_calibration,
    )
    pipeline = AnalysisPipeline(
        storage_root=tmp_path / "partial-run",
        context_provider=lambda _match, _profile: current,
        stage_adapters={
            Stage.PLAYERS: lambda _execution: StagePayload(
                player_file.read_bytes(),
                ".parquet",
                "available",
                ("pose-inference",),
                row_count=2,
            ),
            Stage.BALL: fail_ball,
        },
        database=database,
    )
    transient_match = Match(public_id=match_id, name="Partial publication")
    transient_job = AnalysisJob(
        public_id=job_id,
        match=transient_match,
        processing_profile=ProcessingProfile.BALANCED,
        source_media_asset_id=1,
        match_id=1,
        worker_id="partial-worker",
        claim_token="11111111-1111-1111-1111-111111111111",
    )
    whole = TimeRange(0, current.duration_us)
    pipeline.run_chunk(transient_job, Stage.PLAYERS, whole)
    pipeline.run_chunk(transient_job, Stage.BALL, whole)
    events = pipeline.run_chunk(transient_job, Stage.EVENTS, whole)
    classification = pipeline.run_chunk(
        transient_job, Stage.CLASSIFICATION, whole
    )
    report = pipeline.run_chunk(transient_job, Stage.REPORT, whole)

    assert events.envelope.availability == "partial"
    classified = json.loads(
        classification.payload_path.read_text(encoding="utf-8")
    )
    assert classified["player_rows"] == 2
    assert classified["shots"] == []
    assert classified["rallies"] == []
    assert classified["errors"] == []
    assert classification.envelope.availability == "partial"
    assert report.envelope.availability == "partial"
    assert "player-only-report" in report.envelope.warnings

    from sqlalchemy import func, select
    from squashvision.models import ErrorCandidate, PlayerTrack, Rally, ReportRevision, Shot

    with database.session() as session:
        tracks = session.scalars(
            select(PlayerTrack).order_by(PlayerTrack.source_timestamp_us)
        ).all()
        assert len(tracks) == 2
        track = tracks[0]
        assert track.x_m == pytest.approx(3.2)
        assert track.y_m == pytest.approx(9.2625)
        assert track.position_uncertainty_m is not None
        assert track.position_uncertainty_m > 0
        assert track.position_covariance is not None
        assert track.position_provenance == "measured"
        assert track.position_unavailable_reason is None
        ambiguous_track = tracks[1]
        assert ambiguous_track.x_m is None and ambiguous_track.y_m is None
        assert ambiguous_track.position_provenance == "unavailable"
        assert ambiguous_track.position_unavailable_reason == "ambiguous_identity"
        assert session.scalar(select(func.count(Shot.id))) == 0
        assert session.scalar(select(func.count(Rally.id))) == 0
        assert session.scalar(select(func.count(ErrorCandidate.id))) == 0
        revision = track.prediction_revision
        assert revision == 1
        published_report = session.scalar(select(ReportRevision))
        assert published_report is not None
        movement = published_report.sections["movement"]
        assert sum(sum(row) for row in movement["heatmap"]["counts"]) == 1
        assert movement["heatmap"]["excluded"] == {
            "invalid_projection": 1,
        }

    from squashvision.jobs import ClaimLostError
    from squashvision.models import StagePublication

    classification.payload_path.write_bytes(b"corrupt")
    retried = pipeline.run_chunk(
        transient_job, Stage.CLASSIFICATION, whole
    )
    assert (
        json.loads(retried.payload_path.read_text(encoding="utf-8"))[
            "prediction_revision"
        ]
        == 1
    )
    with database.session() as session:
        assert session.scalar(select(func.count(PlayerTrack.id))) == 2
        assert (
            session.scalar(select(func.count(StagePublication.id))) == 2
        )
        stored_job = session.scalar(
            select(AnalysisJob).where(
                AnalysisJob.public_id == job_id
            )
        )
        assert stored_job is not None
        stored_job.claim_token = "22222222-2222-2222-2222-222222222222"
    retried.payload_path.write_bytes(b"corrupt-again")
    with pytest.raises(ClaimLostError):
        pipeline.run_chunk(
            transient_job, Stage.CLASSIFICATION, whole
        )
    with database.session() as session:
        assert session.scalar(select(func.count(PlayerTrack.id))) == 2


def test_queue_revalidates_envelope_and_records_partial_availability(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    queue = JobQueue(database, storage)
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Envelope checkpoint")
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy.relative),
                ),
            ]
        )
        session.flush()
        match_id = match.public_id
    queued = queue.enqueue(match_id, ProcessingProfile.BALANCED)
    claimed = queue.claim("envelope-worker")
    assert claimed is not None and claimed.claim_token is not None
    chunk = TimeRange(0, 1_000_000)
    input_hash = "b" * 64
    planned = PlannedChunk(
        Stage.BALL,
        chunk,
        plan_hash="1" * 64,
        input_hash=input_hash,
        dependency_hash="2" * 64,
        config_hash="3" * 64,
        artifact_schema_version=1,
    )
    queue.plan_claimed(
        queued.public_id,
        "envelope-worker",
        claimed.claim_token,
        [planned],
    )
    queue.start_chunk_claimed(
        queued.public_id,
        Stage.BALL,
        chunk,
        "envelope-worker",
        claimed.claim_token,
    )
    artifact = ArtifactStore(tmp_path / "analysis-cache").publish(
        stage=Stage.BALL,
        input_hash=input_hash,
        match_id=match_id,
        job_id=queued.public_id,
        profile=ProcessingProfile.BALANCED,
        chunk=chunk,
        context=replace(
            context(duration_us=1_000_000),
            match_public_id=match_id,
        ),
        upstream_hashes=(),
        config_hash="3" * 64,
        payload=StagePayload(
            b"",
            ".bin",
            "unavailable",
            ("typed-degraded-stage",),
            warnings=("player-only",),
            errors=("ball_inference_failed",),
            row_count=0,
        ),
    )
    queue.checkpoint_claimed(
        queued.public_id,
        Stage.BALL,
        chunk,
        artifact.path,
        "envelope-worker",
        claimed.claim_token,
    )
    stored = queue.find_chunk(queued.public_id, Stage.BALL, chunk)
    assert stored.artifact_availability == "unavailable"
    assert stored.artifact_warnings == ["player-only"]


def test_strong_automatic_calibration_is_persisted_and_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np
    from types import SimpleNamespace

    from sqlalchemy import select
    from squashvision.calibration import (
        CalibrationCapabilities,
        CalibrationResult,
        CourtCorrespondence,
        CourtKeypoints,
        CourtPoint,
        ImagePoint,
    )
    from squashvision.models import Calibration

    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Automatic calibration")
        proxy_row = MediaAsset(
            match=match,
            kind=AssetKind.PROXY,
            relative_path=str(proxy.relative),
        )
        analysis_job = AnalysisJob(
            match=match,
            source_media_asset=proxy_row,
            processing_profile=ProcessingProfile.BALANCED,
            status=JobStatus.RUNNING,
            worker_id="calibration-worker",
            claim_token="33333333-3333-3333-3333-333333333333",
        )
        session.add_all([match, proxy_row, analysis_job])
        session.flush()
        match_id = match.public_id
        job_id = analysis_job.public_id
    points = CourtKeypoints(
        tuple(
            CourtCorrespondence(
                str(index),
                ImagePoint(float(index % 2) * 100.0, float(index // 2) * 100.0),
                CourtPoint(float(index % 2) * 6.4, float(index // 2) * 9.75),
            )
            for index in range(4)
        )
    )
    fitted = CalibrationResult(
        calibrated=True,
        image_to_court=((0.064, 0.0, 0.0), (0.0, 0.0975, 0.0), (0.0, 0.0, 1.0)),
        court_to_image=((15.625, 0.0, 0.0), (0.0, 10.256410256, 0.0), (0.0, 0.0, 1.0)),
        residuals_px=(1.0, 1.0, 1.0, 1.0),
        rms_error_px=1.0,
        max_error_px=1.0,
        inlier_mask=(True, True, True, True),
        condition_number=1.0,
        parameter_covariance=None,
        confidence=0.95,
        capabilities=CalibrationCapabilities(True, True, True, True),
        warnings=(),
    )
    current = replace(
        context(duration_us=1_000_000),
        match_public_id=match_id,
        calibration_revision=None,
        calibration_capabilities={
            "image_space": True,
            "floor_position": False,
            "movement_distance": False,
            "speed": False,
        },
    )
    pipeline = AnalysisPipeline(
        storage_root=tmp_path,
        context_provider=lambda _match, _profile: current,
        database=database,
    )
    monkeypatch.setattr(
        pipeline,
        "_representative_frame",
        lambda _execution: SimpleNamespace(
            image=np.zeros((100, 100, 3), dtype=np.uint8)
        ),
    )
    import squashvision.calibration as calibration_module

    monkeypatch.setattr(
        calibration_module,
        "detect_court",
        lambda _image: SimpleNamespace(keypoints=points),
    )
    monkeypatch.setattr(
        calibration_module,
        "fit_calibration",
        lambda _points, _size: fitted,
    )
    transient_match = Match(public_id=match_id, name="Automatic calibration")
    artifact = pipeline.run_chunk(
        AnalysisJob(
            public_id=job_id,
            match=transient_match,
            processing_profile=ProcessingProfile.BALANCED,
            source_media_asset_id=1,
            match_id=1,
            worker_id="calibration-worker",
            claim_token="33333333-3333-3333-3333-333333333333",
        ),
        Stage.CALIBRATION,
        TimeRange(0, 1_000_000),
    )
    payload = json.loads(artifact.payload_path.read_text(encoding="utf-8"))
    assert payload["revision"] == 1
    with database.session() as session:
        stored = session.scalar(select(Calibration))
        assert stored is not None
        assert stored.frame_width == 100
        assert stored.frame_height == 100
        assert len(stored.keypoints) == 4
        assert stored.confidence == 0.95


def test_exact_timestamp_index_maps_vfr_proxy_pts_without_average_rate(
    tmp_path: Path,
) -> None:
    index = ExactTimestampIndex.from_samples(
        source=((0, 0), (41_000, 1), (83_500, 2), (150_250, 3)),
        proxy=(0, 33_333, 66_666, 100_000, 133_333),
    )
    assert index.source_for_proxy(0) == (0, 0)
    assert index.source_for_proxy(33_333) == (41_000, 1)
    assert index.source_for_proxy(66_666) == (83_500, 2)
    assert index.source_for_proxy(133_333) == (150_250, 3)
    stored = index.write(tmp_path / "timestamp-index.parquet")
    restored = ExactTimestampIndex.read(stored)
    assert restored == index


def test_timestamp_index_normalizes_nonzero_source_origin_for_chunk_space() -> None:
    index = ExactTimestampIndex.from_samples(
        source=(
            (10_000_000, 0),
            (10_041_000, 1),
            (10_083_500, 2),
        ),
        proxy=(3_000_000, 3_033_333, 3_066_666),
    )
    assert index.source_raw_origin_us == 10_000_000
    assert index.proxy_raw_origin_us == 3_000_000
    assert index.proxy_timestamps_us == (0, 33_333, 66_666)
    assert index.source_for_proxy(0) == (0, 0)
    assert index.source_for_proxy(33_333) == (41_000, 1)
    assert index.source_for_proxy(66_666) == (83_500, 2)


def test_exact_index_build_and_maximum_decode_normalize_ten_second_source_pts(
    tmp_path: Path,
) -> None:
    from fractions import Fraction

    import av
    import numpy as np

    def video(path: Path, origin_us: int) -> None:
        with av.open(str(path), mode="w") as container:
            stream = container.add_stream("mpeg4", rate=25)
            stream.width = 64
            stream.height = 64
            stream.pix_fmt = "yuv420p"
            stream.time_base = Fraction(1, 1_000_000)
            for index in range(4):
                frame = av.VideoFrame.from_ndarray(
                    np.full((64, 64, 3), index * 20, dtype=np.uint8),
                    format="rgb24",
                )
                frame.pts = origin_us + index * 40_000
                frame.time_base = Fraction(1, 1_000_000)
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)

    source = tmp_path / "source.mp4"
    proxy = tmp_path / "proxy.mp4"
    index_path = tmp_path / "exact.parquet"
    video(source, 10_000_000)
    video(proxy, 3_000_000)
    ExactTimestampIndex.build(source, proxy, index_path)
    current = replace(
        context(duration_us=160_000),
        source_path=source,
        proxy_path=proxy,
        exact_timestamp_index_path=index_path,
    )
    pipeline = AnalysisPipeline(
        storage_root=tmp_path / "storage",
        context_provider=lambda _match, _profile: current,
    )
    analysis_job = job(ProcessingProfile.MAXIMUM)
    execution = StageExecution(
        job=analysis_job,
        stage=Stage.PLAYERS,
        chunk=TimeRange(0, 120_000),
        profile_config=PROFILE_CONFIGS[ProcessingProfile.MAXIMUM],
        context=current,
        upstream=(),
        input_hash="1" * 64,
        config_hash="2" * 64,
    )
    decoded = pipeline._decode_frames(execution, stride=1)
    assert decoded.frames[0].timestamp_us == 0
    assert decoded.frames[0].source_frame_index == 0
    assert all(
        frame.timestamp_us < 120_000 for frame in decoded.frames
    )
    sampled = pipeline._decode_frames(execution, stride=1, sample_count=2)
    assert [frame.source_frame_index for frame in sampled] == [0, 2]
    from squashvision.vision.ball.tracker import median_background
    np.testing.assert_array_equal(median_background(decoded, maximum=2), median_background(sampled))
    bounded = replace(current, source_frame_size=(3840, 2160),
                      source_path=tmp_path / "must-not-decode-4k-source.mp4")
    proxy_frames = pipeline._decode_frames(replace(execution, context=bounded), stride=1)
    assert [frame.source_frame_index for frame in proxy_frames] == [0, 1, 2]


def test_streamed_frame_buffers_bound_memory_and_preserve_all_ball_windows(tmp_path: Path, monkeypatch) -> None:
    import numpy as np
    from squashvision.vision.ball.tracker import median_background, preprocess_window
    pipeline = AnalysisPipeline(storage_root=tmp_path)
    decoded = []
    def frames(*_, **__):
        for index in range(20):
            decoded.append(index)
            yield Frame(timestamp_us=index * 40_000, source_frame_index=index,
                        image=np.full((2, 2, 3), index, dtype=np.uint8))
    monkeypatch.setattr(pipeline, "_iter_decoded_frames", frames)
    iterator = pipeline._iter_frame_batches(None, stride=1, batch_size=19, overlap_frames=3, max_bytes=48)
    first = next(iterator)
    assert decoded == [0, 1, 2, 3]
    batches = [first, *iterator]
    assert all(sum(frame.image.nbytes for frame in batch) <= 48 for batch in batches)
    windows = [tuple(frame.source_frame_index for frame in batch.frames[index:index + 4])
               for batch in batches for index in range(len(batch.frames) - 3)]
    assert windows == [tuple(range(index, index + 4)) for index in range(17)]
    full = tuple(frames())
    background = median_background(FrameBatch(full))
    old_inputs = np.stack([preprocess_window(full[index:index + 4], background,
                                             width=4, height=2) for index in range(17)])
    streamed_inputs = np.stack([preprocess_window(batch.frames[index:index + 4], background,
                                                  width=4, height=2)
                               for batch in batches for index in range(len(batch.frames) - 3)])
    np.testing.assert_array_equal(old_inputs, streamed_inputs)



def test_error_candidate_targets_originating_racket_shot_and_report_joins_it(
    tmp_path: Path,
) -> None:
    from sqlalchemy import select
    from squashvision.analytics import build_report
    from squashvision.models import Correction, CorrectionStatus, ErrorCandidate, Shot
    from squashvision.vision.contacts import Hitter
    from squashvision.vision.shots import (
        CourtDepth, CourtSide, ErrorOutcome, ErrorPrediction, ShotFeatures,
        ShotOutcome, ShotPrediction, ShotType, StrokeSide,
    )

    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Error target")
        proxy_row = MediaAsset(
            match=match,
            kind=AssetKind.PROXY,
            relative_path=str(proxy.relative),
        )
        analysis_job = AnalysisJob(
            match=match,
            source_media_asset=proxy_row,
            processing_profile=ProcessingProfile.BALANCED,
            status=JobStatus.RUNNING,
            worker_id="error-worker",
            claim_token="44444444-4444-4444-4444-444444444444",
        )
        session.add_all([match, proxy_row, analysis_job])
        session.flush()
        match_id = match.public_id
        job_id = analysis_job.public_id
    current = replace(
        context(duration_us=1_000_000), match_public_id=match_id
    )
    job_row = AnalysisJob(
        public_id=job_id,
        match=Match(public_id=match_id, name="Error target"),
        processing_profile=ProcessingProfile.BALANCED,
        worker_id="error-worker",
        claim_token="44444444-4444-4444-4444-444444444444",
        source_media_asset_id=1,
        match_id=1,
    )
    execution = StageExecution(
        job=job_row,
        stage=Stage.CLASSIFICATION,
        chunk=TimeRange(0, 1_000_000),
        profile_config=PROFILE_CONFIGS[ProcessingProfile.BALANCED],
        context=current,
        upstream=(),
        input_hash="e" * 64,
        config_hash="f" * 64,
    )
    shot_prediction = ShotPrediction(
        primary_type=ShotType.STRAIGHT_DRIVE,
        probabilities={ShotType.STRAIGHT_DRIVE: 0.8, ShotType.UNKNOWN: 0.2},
        confidence=0.8,
        margin=0.6,
        required_probability=0.65,
        required_margin=0.15,
        volley=False,
        volley_probability=0.1,
        stroke_side=StrokeSide.FOREHAND,
        hitter=Hitter.A,
        origin_side=CourtSide.LEFT,
        target_side=CourtSide.RIGHT,
        target_depth=CourtDepth.BACK,
        outcome=ShotOutcome.CONTINUES,
        features=ShotFeatures(
            serve_context=False, origin_court_m=None, target_court_m=None,
            origin_side=None, target_side=None, target_depth=None,
            target_depth_m=None, target_width_m=None, pre_velocity_px_s=None,
            post_velocity_px_s=None, direction_change_rad=None,
            wall_sequence=(), wall_sequence_confidence=None,
            floor_bounce_timestamp_us=None, normalized_pace=None,
            apex_proxy=None, impact_height_proxy=None, opponent_timing_s=None,
            opponent_reach=None, volley_evidence_available=True, available=(),
        ),
        sample_timestamps_us=(100_000, 200_000),
        reasons=(),
    )
    serve_prediction = replace(
        shot_prediction,
        primary_type=ShotType.SERVE,
        probabilities={ShotType.SERVE: 0.8, ShotType.UNKNOWN: 0.2},
        outcome=ShotOutcome.CONTINUES,
        reasons=("insufficient_supported_shot_evidence",),
    )
    kill_prediction = replace(
        shot_prediction,
        primary_type=ShotType.KILL,
        probabilities={ShotType.KILL: 0.8, ShotType.UNKNOWN: 0.2},
        outcome=ShotOutcome.TERMINAL,
    )
    unknown_prediction = replace(
        shot_prediction,
        primary_type=ShotType.UNKNOWN,
        probabilities={ShotType.UNKNOWN: 0.9, ShotType.STRAIGHT_DRIVE: 0.1},
        confidence=0.9,
        margin=0.8,
        reasons=(),
    )
    error_prediction = ErrorPrediction(
        selected_outcome=ErrorOutcome.UNFORCED_ERROR_CANDIDATE,
        probabilities={ErrorOutcome.UNFORCED_ERROR_CANDIDATE: 0.7, ErrorOutcome.UNKNOWN: 0.3},
        player=Hitter.A,
        confidence=0.7,
        margin=0.4,
        review_required=True,
        objective=False,
        evidence=("terminal_floor_contact",),
        reasons=("candidate_requires_human_review",),
        support_timestamps_us=(100_000, 200_000),
        required_probability=0.75,
        required_margin=0.2,
    )
    pipeline = AnalysisPipeline(
        storage_root=tmp_path,
        context_provider=lambda _match, _profile: current,
        database=database,
    )
    revision = pipeline._publish_prediction_revision(
        execution,
        players=(),
        rallies=(),
        shots=(
            {
                "contact_id": "racket-1",
                "segment_id": "segment-1",
                "source_timestamp_us": 100_000,
                "source_frame_index": 10,
                "prediction": shot_prediction,
                "trajectory": {
                    "speed": {
                        "reason": "calibration_unavailable"
                    }
                },
                "contact_ball": _ball_point(100_000, 50.0, 40.0),
            },
            {
                "contact_id": "racket-serve",
                "segment_id": "segment-2",
                "source_timestamp_us": 300_000,
                "source_frame_index": 30,
                "prediction": serve_prediction,
                "trajectory": {
                    "speed": {"reason": "calibration_unavailable"}
                },
                "contact_ball": _ball_point(300_000, 50.0, 40.0),
            },
            {
                "contact_id": "racket-kill",
                "segment_id": "segment-3",
                "source_timestamp_us": 400_000,
                "source_frame_index": 40,
                "prediction": kill_prediction,
                "trajectory": {
                    "speed": {"reason": "calibration_unavailable"}
                },
                "contact_ball": _ball_point(400_000, 50.0, 40.0),
            },
            {
                "contact_id": "racket-unknown",
                "segment_id": "segment-4",
                "source_timestamp_us": 500_000,
                "source_frame_index": 50,
                "prediction": unknown_prediction,
                "trajectory": {
                    "speed": {"reason": "calibration_unavailable"}
                },
                "contact_ball": _ball_point(500_000, 50.0, 40.0),
            },
        ),
        errors=(
            {
                "contact_id": "floor-terminal-1",
                "shot_contact_id": "racket-1",
                "segment_id": "segment-1",
                "source_timestamp_us": 200_000,
                    "prediction": error_prediction,
            },
        ),
        evidence_frames=(
            (100_000, 10),
            (200_000, 20),
            (300_000, 30),
            (400_000, 40),
            (500_000, 50),
        ),
    )
    assert revision == 1
    with database.session() as session:
        shots = session.scalars(
            select(Shot).order_by(Shot.source_timestamp_us)
        ).all()
        shot = shots[0]
        error = session.scalar(select(ErrorCandidate))
        assert error is not None
        assert [row.kind.value for row in shots] == [
            "drive",
            "serve",
            "kill",
            "unknown",
        ]
        assert [row.outcome for row in shots] == [
            "in_play",
            "in_play",
            "unknown",
            "in_play",
        ]
        assert shots[1].review_required is True
        assert shots[1].review_status == "pending"
        assert shots[3].review_required is True
        assert shots[3].review_status == "pending"
        assert error.target_type == "shot"
        assert error.target_prediction_id == shot.prediction_id
        assert error.evidence_payload["evidence_start_timestamp_us"] == 100_000
        assert error.evidence_payload["evidence_end_timestamp_us"] == 200_000
        assert error.evidence_payload["evidence_start_frame_index"] == 10
        assert error.evidence_payload["evidence_end_frame_index"] == 20
        assert shot.contact_x_px == 50.0
        assert error.evidence_payload["provenance"] == "unavailable"
        assert shot.contact_covariance == [[1.0, 0.0], [0.0, 1.0]]
        error_id = error.prediction_id
    report = build_report(match_id, 1, database)
    assert error_id in report.sections["errors"].payload[
        "unreviewed_candidate_ids"
    ]
    assert "racket-1" in report.sections["errors"].evidence_ids
    assert report.sections["trajectory"].payload["image_trajectory"]["availability"]["available"] is True
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        session.add(
            Correction(
                match=match,
                command_type="change_shot_type",
                target_type="shot",
                target_id="shot-racket-1",
                prediction_revision=1,
                expected_report_revision=1,
                before_payload={"shot_type": "drive"},
                after_payload={"shot_type": "drop"},
                reason="retain accepted analyst decision",
                source_timestamp_us=100_000,
                source_evidence_ids=["racket-1", "segment-1"],
                status=CorrectionStatus.ACTIVE,
            )
        )
    reanalysis = replace(execution, input_hash="d" * 64)
    second_revision = pipeline._publish_prediction_revision(
        reanalysis,
        players=(),
        rallies=(),
        shots=(
            {
                "contact_id": "racket-1-new",
                "segment_id": "segment-1",
                "source_timestamp_us": 100_000,
                "source_frame_index": 10,
                "prediction": shot_prediction,
                "trajectory": {
                    "speed": {"reason": "calibration_unavailable"}
                },
                "contact_ball": _ball_point(100_000, 50.0, 40.0),
            },
        ),
        errors=(),
        evidence_frames=((100_000, 10),),
    )
    assert second_revision == 2
    with database.session() as session:
        reapplied = session.scalar(
            select(Correction).where(
                Correction.prediction_revision == 2,
                Correction.status == CorrectionStatus.ACTIVE,
            )
        )
        assert reapplied is not None
        assert reapplied.target_id == "shot-racket-1-new"
        assert reapplied.after_payload["shot_type"] == "drop"


def test_terminal_errors_target_only_preceding_generated_racket_shots(
    tmp_path: Path,
) -> None:
    from squashvision.observations import write_ball_observations
    from squashvision.vision.ball import repair_track
    from squashvision.vision.contacts import (
        ContactEvent,
        ContactEvidence,
        ContactType,
        Hitter,
    )

    raw_ball = (
        _ball_point(100_000, 20.0, 40.0),
        _ball_point(150_000, 30.0, 45.0),
        _ball_point(200_000, 40.0, 50.0),
        _ball_point(600_000, 20.0, 40.0),
        _ball_point(650_000, 30.0, 45.0),
        _ball_point(700_000, 40.0, 50.0),
    )
    repaired = repair_track(raw_ball, None)
    assert len(repaired.segments) == 2
    ball_rows = tuple(
        point for segment in repaired.segments for point in segment.points
    )
    ball_file = tmp_path / "terminal-ball.parquet"
    player_file = tmp_path / "terminal-player.parquet"
    write_ball_observations(
        ball_file,
        ball_rows,
        source_manifest_id="4" * 64,
        model_manifest_id="ball-a",
    )
    write_player_observations(
        player_file,
        (_player_point(150_000), _player_point(650_000)),
        source_manifest_id="4" * 64,
        model_manifest_id="pose-a",
    )

    def contact(
        segment_id: str,
        contact_id: str,
        timestamp_us: int,
        selected_type: ContactType,
        hitter: Hitter,
    ) -> ContactEvent:
        type_probabilities = {
            item: (
                0.9
                if item is selected_type
                else 0.1
                if item is ContactType.UNKNOWN
                else 0.0
            )
            for item in ContactType
        }
        hitter_probabilities = {
            item: (
                0.9
                if item is hitter
                else 0.1
                if item is Hitter.UNKNOWN
                else 0.0
            )
            for item in Hitter
        }
        return ContactEvent(
            segment_id=segment_id,
            contact_id=contact_id,
            timestamp_us=timestamp_us,
            uncertainty_us=10_000,
            type_probabilities=type_probabilities,
            selected_type=selected_type,
            hitter_probabilities=hitter_probabilities,
            selected_hitter=hitter,
            confidence=0.9,
            review_required=False,
            review_reasons=(),
            evidence=ContactEvidence(
                audio=0.0,
                direction_change=0.8,
                speed_change=0.5,
                ball_uncertainty=0.1,
                ball_gap=0.0,
                wrist_proximity=0.8,
                topology_proximity=0.8,
            ),
            supporting_ball_timestamps_us=(timestamp_us,),
            supporting_player_timestamps_us=(timestamp_us,),
        )

    first_segment, second_segment = repaired.segments
    contacts = (
        contact(
            first_segment.segment_id,
            "terminal-racket",
            first_segment.points[-1].timestamp_us,
            ContactType.RACKET,
            Hitter.A,
        ),
        contact(
            second_segment.segment_id,
            "origin-racket",
            second_segment.points[-2].timestamp_us,
            ContactType.RACKET,
            Hitter.A,
        ),
        contact(
            second_segment.segment_id,
            "terminal-floor",
            second_segment.points[-1].timestamp_us,
            ContactType.FLOOR,
            Hitter.UNKNOWN,
        ),
    )
    events_payload = StagePayload(
        json.dumps(
            AnalysisPipeline._json_safe(
                {
                    "mode": "ball-and-player",
                    "contacts": contacts,
                    "rallies": [],
                    "audio": "unavailable",
                }
            ),
            sort_keys=True,
        ).encode(),
        ".json",
        "available",
        ("contact-fusion",),
        row_count=len(contacts),
    )
    current = context(duration_us=1_000_000)
    pipeline = AnalysisPipeline(
        storage_root=tmp_path / "terminal-run",
        context_provider=lambda _match, _profile: current,
        stage_adapters={
            Stage.PLAYERS: lambda _execution: StagePayload(
                player_file.read_bytes(),
                ".parquet",
                "available",
                ("pose-inference",),
                row_count=2,
            ),
            Stage.BALL: lambda _execution: StagePayload(
                ball_file.read_bytes(),
                ".parquet",
                "available",
                ("tracknet-inference",),
                row_count=len(ball_rows),
            ),
            Stage.EVENTS: lambda _execution: events_payload,
        },
    )
    analysis_job = job()
    whole = TimeRange(0, 1_000_000)
    pipeline.run_chunk(analysis_job, Stage.PLAYERS, whole)
    pipeline.run_chunk(analysis_job, Stage.BALL, whole)
    pipeline.run_chunk(analysis_job, Stage.EVENTS, whole)
    classified = pipeline.run_chunk(
        analysis_job, Stage.CLASSIFICATION, whole
    )
    payload = json.loads(
        classified.payload_path.read_text(encoding="utf-8")
    )
    shot_contacts = {row["contact_id"] for row in payload["shots"]}
    assert shot_contacts == {"origin-racket"}
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["contact_id"] == "terminal-floor"
    assert payload["errors"][0]["shot_contact_id"] in shot_contacts
    assert all(
        row["contact_id"] != "terminal-racket"
        for row in payload["errors"]
    )

def test_audio_normalization_handles_planar_and_packed_channel_axes() -> None:
    import numpy as np

    planar = np.asarray([[1.0, 3.0, 5.0], [3.0, 5.0, 7.0]])
    packed = planar.T
    assert normalize_audio_frame(planar, channels=2, planar=True).tolist() == [
        2.0,
        4.0,
        6.0,
    ]
    assert normalize_audio_frame(packed, channels=2, planar=False).tolist() == [
        2.0,
        4.0,
        6.0,
    ]


def test_successful_boundary_remapping_preserves_within_chunk_ambiguity(tmp_path: Path, monkeypatch) -> None:
    import squashvision.observations as observations
    current = context(duration_us=65_000_000)
    pipeline = AnalysisPipeline(storage_root=tmp_path, context_provider=lambda *_: current)
    appearance_a = (1.0,) + (0.0,) * (APPEARANCE_DIMENSION - 1)
    appearance_b = (0.0, 1.0) + (0.0,) * (APPEARANCE_DIMENSION - 2)
    prior = (replace(_player_point(57_000_000), appearance=appearance_a),
             replace(_player_point(57_000_000), player_id='B', appearance=appearance_b))
    rows = (replace(prior[0], appearance=appearance_b, ambiguous=True, ambiguity_reason='ambiguous_assignment'),
            replace(prior[1], appearance=appearance_a))
    previous = SimpleNamespace(payload_path=tmp_path/'previous.parquet',
                               envelope=SimpleNamespace(start_us=0, end_us=60_000_000))
    pipeline._latest[(current.match_public_id, ProcessingProfile.MAXIMUM.value, Stage.PLAYERS)] = [previous]
    monkeypatch.setattr(pipeline, '_artifact_matches_context', lambda *_: True)
    monkeypatch.setattr(observations, 'read_player_observations', lambda _: prior)
    execution = StageExecution(job=job(ProcessingProfile.MAXIMUM), stage=Stage.PLAYERS,
        chunk=TimeRange(57_000_000,65_000_000), profile_config=PROFILE_CONFIGS[ProcessingProfile.MAXIMUM],
        context=current, upstream=(), input_hash='a'*64, config_hash='b'*64)
    merged, warnings = pipeline._reconcile_player_chunk(execution, rows)
    assert [row.player_id for row in merged] == ['B', 'A']
    assert merged[0].ambiguous and merged[0].ambiguity_reason == 'ambiguous_assignment'
    assert not merged[1].ambiguous and merged[1].ambiguity_reason is None
    assert warnings[0].startswith('player-boundary-mapping:B:A:')


def test_player_boundary_state_stays_ambiguous_until_later_confident_resolution() -> None:
    state = PlayerBoundaryState()
    state.initialize(("A", "B"))
    ambiguous = state.reconcile(previous=[], current=[])
    assert ambiguous.ambiguous is True
    assert state.map_player("A") is None
    assert state.map_player("B") is None
    resolved = state.reconcile(
        previous=[
            {"player_id": "A", "appearance": [1.0, 0.0]},
            {"player_id": "B", "appearance": [0.0, 1.0]},
        ],
        current=[
            {"player_id": "A", "appearance": [0.0, 1.0]},
            {"player_id": "B", "appearance": [1.0, 0.0]},
        ],
    )
    assert resolved.ambiguous is False
    assert state.map_player("A") == "B"
    assert state.map_player("B") == "A"


def test_checkpoint_payload_corruption_invalidates_completed_chunk(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    queue = JobQueue(database, storage)
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Payload restart")
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy.relative),
                ),
            ]
        )
        session.flush()
        match_id = match.public_id
    queued = queue.enqueue(match_id, ProcessingProfile.FAST)
    claimed = queue.claim("payload-worker")
    assert claimed is not None and claimed.claim_token is not None
    chunk = TimeRange(0, 1_000_000)
    planned = PlannedChunk(
        Stage.BALL,
        chunk,
        input_hash="b" * 64,
        config_hash="c" * 64,
        artifact_schema_version=1,
    )
    queue.plan_claimed(
        queued.public_id,
        "payload-worker",
        claimed.claim_token,
        [planned],
    )
    queue.start_chunk_claimed(
        queued.public_id,
        Stage.BALL,
        chunk,
        "payload-worker",
        claimed.claim_token,
    )
    artifact = ArtifactStore(tmp_path / "cache").publish(
        stage=Stage.BALL,
        input_hash="b" * 64,
        match_id=match_id,
        job_id=queued.public_id,
        profile=ProcessingProfile.FAST,
        chunk=chunk,
        context=replace(
            context(duration_us=1_000_000), match_public_id=match_id
        ),
        upstream_hashes=(),
        config_hash="c" * 64,
        payload=StagePayload(
            b"ball-evidence",
            ".bin",
            "available",
            ("tracknet-inference",),
        ),
    )
    queue.checkpoint_claimed(
        queued.public_id,
        Stage.BALL,
        chunk,
        artifact.path,
        "payload-worker",
        claimed.claim_token,
    )
    stored = queue.find_chunk(queued.public_id, Stage.BALL, chunk)
    assert stored.artifact_payload_path is not None
    (storage.root / stored.artifact_payload_path).write_bytes(b"corrupt")
    assert queue.next_chunk(queued.public_id) == planned
    assert (
        queue.find_chunk(queued.public_id, Stage.BALL, chunk).status
        is StageStatus.INVALIDATED
    )


def test_claimed_plan_reconciles_changed_geometry_and_preserves_exact_rows(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    queue = JobQueue(database, storage)
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    proxy.absolute.write_bytes(b"proxy")
    with database.session() as session:
        match = Match(name="Geometry")
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy.relative),
                ),
            ]
        )
        session.flush()
        match_id = match.public_id
    queued = queue.enqueue(match_id, ProcessingProfile.FAST)
    claimed = queue.claim("geometry-worker")
    assert claimed is not None and claimed.claim_token is not None
    keep = PlannedChunk(
        Stage.PREPARE,
        TimeRange(0, 5_000_000),
        plan_hash="a" * 64,
        input_hash="1" * 64,
        dependency_hash="1" * 64,
        config_hash="1" * 64,
        artifact_schema_version=1,
    )
    keep_calibration = PlannedChunk(
        Stage.CALIBRATION,
        TimeRange(0, 5_000_000),
        plan_hash="a" * 64,
        input_hash="2" * 64,
        dependency_hash="2" * 64,
        config_hash="2" * 64,
        artifact_schema_version=1,
    )
    obsolete = PlannedChunk(
        Stage.PLAYERS,
        TimeRange(0, 5_000_000),
        plan_hash="a" * 64,
        dependency_hash="3" * 64,
    )
    queue.plan_claimed(
        queued.public_id,
        "geometry-worker",
        claimed.claim_token,
        [keep, keep_calibration, obsolete],
    )
    for exact in (keep, keep_calibration):
        queue.start_chunk_claimed(
            queued.public_id,
            exact.stage,
            exact.time_range,
            "geometry-worker",
            claimed.claim_token,
        )
        artifact = tmp_path / f"{exact.stage.value}.bin"
        artifact.write_bytes(exact.stage.value.encode())
        queue.checkpoint_claimed(
            queued.public_id,
            exact.stage,
            exact.time_range,
            artifact,
            "geometry-worker",
            claimed.claim_token,
        )
    changed = [
        replace(keep, plan_hash="b" * 64),
        replace(keep_calibration, plan_hash="b" * 64),
        PlannedChunk(
            Stage.PLAYERS,
            TimeRange(0, 3_000_000),
            plan_hash="b" * 64,
            dependency_hash="4" * 64,
        ),
        PlannedChunk(
            Stage.PLAYERS,
            TimeRange(2_000_000, 5_000_000),
            plan_hash="b" * 64,
            dependency_hash="5" * 64,
        ),
    ]
    rows = queue.reconcile_plan_claimed(
        queued.public_id,
        "geometry-worker",
        claimed.claim_token,
        changed,
    )
    assert [
        (row.stage, row.start_us, row.end_us, row.chunk_index)
        for row in rows
    ] == [
        (Stage.PREPARE, 0, 5_000_000, 0),
        (Stage.CALIBRATION, 0, 5_000_000, 1),
        (Stage.PLAYERS, 0, 3_000_000, 2),
        (Stage.PLAYERS, 2_000_000, 5_000_000, 3),
    ]
    assert rows[0].status is StageStatus.COMPLETED
    assert rows[1].status is StageStatus.COMPLETED
    assert queue.next_chunk(queued.public_id) == changed[2]


@pytest.mark.parametrize("swap_destination", [False, True], ids=["normal", "swapped"])
def test_lazy_timestamp_index_generation_uses_managed_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap_destination: bool,
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    database = Database.open(Settings(data_dir=tmp_path / "database"))
    original = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    timestamp_map = storage.allocate(AssetKind.TIMESTAMP_MAP, ".json")
    original_bytes = b"migrated-original"
    proxy_bytes = b"migrated-proxy"
    timestamp_bytes = b'{"version":1,"samples":[]}'
    for stored, payload in (
        (original, original_bytes),
        (proxy, proxy_bytes),
        (timestamp_map, timestamp_bytes),
    ):
        stored.absolute.write_bytes(payload)

    with database.session() as session:
        match = Match(name="Migrated timestamp metadata")
        proxy_asset = MediaAsset(
            match=match,
            kind=AssetKind.PROXY,
            relative_path=str(proxy.relative),
            checksum_sha256=hashlib.sha256(proxy_bytes).hexdigest(),
            byte_size=len(proxy_bytes),
            duration_us=1_000_000,
            probe_metadata={},
        )
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.ORIGINAL,
                    relative_path=str(original.relative),
                    checksum_sha256=hashlib.sha256(original_bytes).hexdigest(),
                    byte_size=len(original_bytes),
                    duration_us=1_000_000,
                    probe_metadata={},
                ),
                proxy_asset,
                MediaAsset(
                    match=match,
                    kind=AssetKind.TIMESTAMP_MAP,
                    relative_path=str(timestamp_map.relative),
                    checksum_sha256=hashlib.sha256(timestamp_bytes).hexdigest(),
                    byte_size=len(timestamp_bytes),
                ),
            ]
        )
        session.flush()
        match_id = match.public_id
        proxy_asset_id = proxy_asset.id

    index_bytes = b"descriptor-backed-index"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_index_directory = storage.root / "timestamp-index-original"

    def swap_index_directory() -> None:
        index_directory = storage.root / "timestamp-index"
        if index_directory.is_symlink():
            return
        index_directory.mkdir(exist_ok=True)
        index_directory.rename(original_index_directory)
        index_directory.symlink_to(outside, target_is_directory=True)

    real_allocate = LocalStorage.allocate_timestamp_index

    def allocate_then_swap(current: LocalStorage):
        allocated = real_allocate(current)
        swap_index_directory()
        return allocated

    def legacy_path_build(_source: Path, _proxy: Path, destination: Path) -> Path:
        if swap_destination:
            swap_index_directory()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(index_bytes)
        return destination

    def descriptor_build(
        _source: Path, _proxy: Path, descriptor: int
    ) -> int:
        os.ftruncate(descriptor, 0)
        os.write(descriptor, index_bytes)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor

    monkeypatch.setattr(
        ExactTimestampIndex, "build", staticmethod(legacy_path_build)
    )
    monkeypatch.setattr(
        ExactTimestampIndex,
        "build_to_descriptor",
        staticmethod(descriptor_build),
    )
    if swap_destination:
        monkeypatch.setattr(
            LocalStorage, "allocate_timestamp_index", allocate_then_swap
        )

    pipeline = AnalysisPipeline(
        storage_root=storage.root,
        database=database,
    )
    if swap_destination:
        with pytest.raises(EssentialStageError) as error:
            pipeline._ensure_media_metadata(match_id)
        assert error.value.code == "timestamp_index_corrupt"
        assert (storage.root / "timestamp-index").is_symlink()
        assert list(outside.iterdir()) == []
        return

    pipeline._ensure_media_metadata(match_id)
    with database.session() as session:
        migrated_proxy = session.get(MediaAsset, proxy_asset_id)
        assert migrated_proxy is not None
        assert migrated_proxy.timestamp_index_path is not None
        relative = Path(migrated_proxy.timestamp_index_path)
        assert relative.parent == Path("timestamp-index")
        assert (storage.root / relative).read_bytes() == index_bytes
        assert migrated_proxy.timestamp_index_size == len(index_bytes)
        assert migrated_proxy.timestamp_index_sha256 == hashlib.sha256(
            index_bytes
        ).hexdigest()


def test_real_queue_worker_pipeline_resolves_detached_job_and_reuses_verified_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_dir = tmp_path / "fixture"
    fixture_script = (
        Path(__file__).resolve().parents[3] / "scripts/make_squash_fixture.py"
    )
    subprocess.run(
        [sys.executable, str(fixture_script), str(fixture_dir)],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    fixture = fixture_dir / "squash_fixture.mp4"

    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    original = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    timestamp_map = storage.allocate(AssetKind.TIMESTAMP_MAP, ".json")
    original.absolute.write_bytes(fixture.read_bytes())
    proxy.absolute.write_bytes(fixture.read_bytes())
    timestamp_map.absolute.write_text(
        json.dumps(
            {
                "version": 1,
                "samples": [
                    {"sourceSeconds": 0.0, "proxySeconds": 0.0},
                    {"sourceSeconds": 5.0, "proxySeconds": 5.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    with database.session() as session:
        match = Match(name="Detached pipeline")
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.ORIGINAL,
                    relative_path=str(original.relative),
                ),
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy.relative),
                ),
                MediaAsset(
                    match=match,
                    kind=AssetKind.TIMESTAMP_MAP,
                    relative_path=str(timestamp_map.relative),
                ),
            ]
        )
        session.flush()
        match_id = match.public_id
    queue = JobQueue(database, storage)
    queued = queue.enqueue(match_id, ProcessingProfile.FAST)
    adapters = {
        stage: (
            lambda execution, stage=stage: StagePayload(
                json.dumps(
                    {
                        "stage": stage.value,
                        "input": execution.input_hash,
                    },
                    sort_keys=True,
                ).encode(),
                ".json",
                "available",
                ("concrete-test-adapter",),
            )
        )
        for stage in Stage
    }
    pipeline = AnalysisPipeline(
        storage_root=storage.root,
        database=database,
        stage_adapters=adapters,
    )
    context_calls = 0
    original_context_provider = pipeline._production_context

    def counted_context_provider(match: Match, profile: ProcessingProfile):
        nonlocal context_calls
        context_calls += 1
        return original_context_provider(match, profile)

    monkeypatch.setattr(pipeline, "_production_context", counted_context_provider)
    worker = Worker(queue, "detached-worker", pipeline)
    for _ in range(8):
        worker.run_once()
    assert queue.get(queued.public_id).status is JobStatus.COMPLETED
    assert context_calls == 1
    with database.session() as session:
        from sqlalchemy import select

        media_assets = list(session.scalars(select(MediaAsset)))
        assert len(media_assets) == 3
        for asset in media_assets:
            data = (storage.root / asset.relative_path).read_bytes()
            assert asset.byte_size == len(data)
            assert asset.checksum_sha256 == hashlib.sha256(data).hexdigest()


def test_production_plan_uses_original_end_exclusive_duration_without_changing_proxy(
    tmp_path: Path,
) -> None:
    source_duration_us = 3_600_000_000
    proxy_duration_us = 3_599_000_000
    storage = LocalStorage(tmp_path)
    original = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    timestamp_map = storage.allocate(AssetKind.TIMESTAMP_MAP, ".json")
    original_bytes = b"original-duration-source"
    proxy_bytes = b"shorter-duration-proxy"
    timestamp_bytes = json.dumps(
        {
            "version": 1,
            "samples": [
                {"sourceSeconds": 0.0, "proxySeconds": 0.0},
                {"sourceSeconds": 3600.0, "proxySeconds": 3599.0},
            ],
        }
    ).encode("utf-8")
    index_relative = Path("timestamp-index", "duration-horizon.parquet")
    index_path = storage.root / index_relative
    index_bytes = b"duration-horizon-index"
    original.absolute.write_bytes(original_bytes)
    proxy.absolute.write_bytes(proxy_bytes)
    timestamp_map.absolute.write_bytes(timestamp_bytes)
    index_path.parent.mkdir(parents=True)
    index_path.write_bytes(index_bytes)

    def digest(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    match = Match(public_id="duration-horizon", name="Duration horizon")
    source_asset = MediaAsset(
        match=match,
        kind=AssetKind.ORIGINAL,
        relative_path=str(original.relative),
        checksum_sha256=digest(original_bytes),
        byte_size=len(original_bytes),
        duration_us=source_duration_us,
        probe_metadata={},
    )
    proxy_asset = MediaAsset(
        match=match,
        kind=AssetKind.PROXY,
        relative_path=str(proxy.relative),
        checksum_sha256=digest(proxy_bytes),
        byte_size=len(proxy_bytes),
        duration_us=proxy_duration_us,
        probe_metadata={},
        timestamp_index_path=str(index_relative),
        timestamp_index_sha256=digest(index_bytes),
        timestamp_index_size=len(index_bytes),
    )
    timestamp_asset = MediaAsset(
        match=match,
        kind=AssetKind.TIMESTAMP_MAP,
        relative_path=str(timestamp_map.relative),
        checksum_sha256=digest(timestamp_bytes),
        byte_size=len(timestamp_bytes),
    )
    match.media_assets = [source_asset, proxy_asset, timestamp_asset]

    plan = AnalysisPipeline(storage_root=storage.root).plan(
        match, ProcessingProfile.FAST
    )

    assert plan.duration_us == source_duration_us
    assert max(chunk.time_range.end_us for chunk in plan.chunks) == source_duration_us
    assert proxy_asset.duration_us == proxy_duration_us


def test_production_context_uses_dedicated_timestamp_map_and_verifies_all_media_bytes(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path)
    original = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    proxy = storage.allocate(AssetKind.PROXY, ".mp4")
    timestamp_map = storage.allocate(AssetKind.TIMESTAMP_MAP, ".json")
    export = storage.allocate(AssetKind.EXPORT, ".zip")
    original_bytes = b"immutable-original"
    proxy_bytes = b"immutable-proxy"
    timestamp_bytes = json.dumps(
        {
            "version": 1,
            "samples": [
                {"sourceSeconds": 0.0, "proxySeconds": 0.0},
                {"sourceSeconds": 1.0, "proxySeconds": 1.0},
            ],
        }
    ).encode("utf-8")
    index_bytes = b"immutable-timestamp-index"
    original.absolute.write_bytes(original_bytes)
    proxy.absolute.write_bytes(proxy_bytes)
    timestamp_map.absolute.write_bytes(timestamp_bytes)
    export.absolute.write_bytes(b"PK\x03\x04not-a-timestamp-map")
    index_relative = Path("timestamp-index", "exact.parquet")
    index_path = storage.root / index_relative
    index_path.parent.mkdir(parents=True)
    index_path.write_bytes(index_bytes)

    def digest(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    with database.session() as session:
        match = Match(name="Immutable media")
        session.add_all(
            [
                match,
                MediaAsset(
                    match=match,
                    kind=AssetKind.ORIGINAL,
                    relative_path=str(original.relative),
                    checksum_sha256=digest(original_bytes),
                    byte_size=len(original_bytes),
                    duration_us=1_000_000,
                    probe_metadata={},
                ),
                MediaAsset(
                    match=match,
                    kind=AssetKind.PROXY,
                    relative_path=str(proxy.relative),
                    checksum_sha256=digest(proxy_bytes),
                    byte_size=len(proxy_bytes),
                    duration_us=1_000_000,
                    probe_metadata={},
                    timestamp_index_path=str(index_relative),
                    timestamp_index_sha256=digest(index_bytes),
                    timestamp_index_size=len(index_bytes),
                ),
                MediaAsset(
                    match=match,
                    kind=AssetKind.TIMESTAMP_MAP,
                    relative_path=str(timestamp_map.relative),
                    checksum_sha256=digest(timestamp_bytes),
                    byte_size=len(timestamp_bytes),
                ),
                MediaAsset(
                    match=match,
                    kind=AssetKind.EXPORT,
                    relative_path=str(export.relative),
                    checksum_sha256=digest(export.absolute.read_bytes()),
                    byte_size=export.absolute.stat().st_size,
                ),
            ]
        )
        session.flush()
        pipeline = AnalysisPipeline(storage_root=storage.root)
        verified = pipeline._production_context(match, ProcessingProfile.FAST)
        assert verified.timestamp_map_path == timestamp_map.absolute

        original.absolute.write_bytes(b"corrupt-original")
        with pytest.raises(EssentialStageError) as original_error:
            pipeline._production_context(match, ProcessingProfile.FAST)
        assert original_error.value.code == "media_asset_corrupt"
        original.absolute.write_bytes(original_bytes)

        index_path.write_bytes(b"corrupt-timestamp-index")
        with pytest.raises(EssentialStageError) as index_error:
            pipeline._production_context(match, ProcessingProfile.FAST)
        assert index_error.value.code == "timestamp_index_corrupt"
