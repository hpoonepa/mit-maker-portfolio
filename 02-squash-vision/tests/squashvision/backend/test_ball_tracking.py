from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch
import squashvision.vision.ball.tracknet_v3 as tracknet_module
import squashvision.vision.ball.tracker as ball_tracker_module

from squashvision.calibration import CalibrationCapabilities, CalibrationResult
from squashvision.model_assets import (
    APPLICATION_COMPATIBILITY_VERSION,
    BALL_ASSET,
    ResolvedAsset,
)
from squashvision.models import ModelAssetState
from squashvision.observations import (
    BALL_MAX_CANDIDATES,
    BallCandidate,
    BallObservation,
    EvidenceKind,
    Frame,
    FrameBatch,
    read_ball_observations,
    write_ball_observations,
)
from squashvision.vision.ball.tracknet_v3 import (
    CheckpointFormatError,
    TrackNetV3,
    _tensor_state_dict,
    normalize_checkpoint_keys,
)
from squashvision.vision.ball.tracker import (
    BallTracker,
    decode_heatmap,
    median_background,
    preprocess_window,
    repair_track,
    uniform_sample_indices,
)


def frame(index: int, value: int = 0, *, width: int = 16, height: int = 12) -> Frame:
    return Frame(
        timestamp_us=10_000 + index * 40_000,
        source_frame_index=100 + index,
        image=np.full((height, width, 3), value, dtype=np.uint8),
    )


def candidate(
    x: float,
    y: float,
    probability: float = 0.9,
    *,
    covariance: tuple[tuple[float, float], tuple[float, float]] = ((2.0, 0.0), (0.0, 2.0)),
) -> BallCandidate:
    return BallCandidate(
        x=x,
        y=y,
        peak_probability=probability,
        integrated_probability=min(1.0, probability),
        area=5,
        circularity=0.9,
        covariance=covariance,
    )


def observation(
    index: int,
    *,
    x: float | None,
    y: float | None,
    probability: float = 0.9,
    candidates: tuple[BallCandidate, ...] | None = None,
    ambiguous: bool = False,
    timestamp_us: int | None = None,
) -> BallObservation:
    timestamp = 10_000 + index * 100_000 if timestamp_us is None else timestamp_us
    visible = x is not None and y is not None
    top = candidates if candidates is not None else (() if not visible else (candidate(x, y, probability),))
    return BallObservation(
        timestamp_us=timestamp,
        source_timestamp_us=timestamp,
        source_frame_index=100 + index,
        source_width=512,
        source_height=288,
        x=x,
        y=y,
        probability=probability if visible else 0.0,
        covariance=((2.0, 0.0), (0.0, 2.0)) if visible else None,
        visible=visible,
        candidate_count=len(top),
        candidates=top,
        evidence=EvidenceKind.OBSERVED,
        evidence_start_timestamp_us=timestamp,
        evidence_end_timestamp_us=timestamp,
        evidence_start_frame_index=100 + index,
        evidence_end_frame_index=100 + index,
        ambiguous=ambiguous,
        ambiguity_reason="comparable_peaks" if ambiguous else None,
        segment_id=None,
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
        device="cpu",
        device_fallback=False,
    )


def resolved_ball(tmp_path: Path, payload: bytes) -> tuple[ResolvedAsset, Path]:
    digest = hashlib.sha256(payload).hexdigest()
    model_path = tmp_path / "storage" / "models" / f"{digest}.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(payload)
    return (
        ResolvedAsset(
            name=BALL_ASSET.name,
            source=BALL_ASSET.source,
            url=None,
            repository=BALL_ASSET.repo_id,
            filename=BALL_ASSET.filename,
            requested_revision=BALL_ASSET.revision,
            resolved_revision="a" * 40,
            etag="etag",
            local_path=Path("models") / model_path.name,
            byte_size=len(payload),
            sha256=digest,
            declared_license="not-declared",
            downloaded_at=datetime.now(UTC),
            compatibility_version=APPLICATION_COMPATIBILITY_VERSION,
            required=True,
            state=ModelAssetState.READY,
            error_code=None,
        ),
        model_path,
    )


def test_network_preserves_spatial_shape_and_last_only_channel() -> None:
    model = TrackNetV3(in_dim=15, out_dim=4, last_only=True, base_width=2)
    output = model(torch.zeros((2, 15, 32, 48), dtype=torch.float32))
    assert output.shape == (2, 1, 32, 48)
    assert torch.isfinite(output).all()


def test_checkpoint_prefix_normalization_is_documented_and_collision_safe() -> None:
    tensor = torch.ones(1)
    normalized = normalize_checkpoint_keys(
        {"module.model._orig_mod.predictor.bias": tensor}
    )
    assert normalized == {"predictor.bias": tensor}
    with pytest.raises(CheckpointFormatError, match="collision"):
        normalize_checkpoint_keys(
            {"module.predictor.bias": tensor, "predictor.bias": tensor}
        )
    with pytest.raises(CheckpointFormatError, match="unexpected prefix"):
        normalize_checkpoint_keys({"network.x": tensor})


def test_restricted_checkpoint_accepts_only_exact_mmengine_envelope() -> None:
    state = {"predictor.bias": torch.zeros(4)}
    assert _tensor_state_dict(
        {"meta": {}, "state_dict": state, "message_hub": {}}
    ) == state
    with pytest.raises(CheckpointFormatError, match="tensor state dict"):
        _tensor_state_dict(
            {"meta": {}, "state_dict": state, "message_hub": {}, "optimizer": {}}
        )


def test_load_rejects_self_consistent_untrusted_asset_before_deserialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset, model_path = resolved_ball(tmp_path, b"self-consistent alternative")
    monkeypatch.setenv("MOSAIC_SQUASH_STORAGE_ROOT", str(tmp_path / "storage"))
    calls: list[dict[str, Any]] = []

    def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"state_dict": {"predictor.bias": torch.zeros(4)}}

    monkeypatch.setattr(torch, "load", fake_load)
    with pytest.raises(ValueError, match="trusted checkpoint identity"):
        TrackNetV3.load(asset, torch.device("cpu"))
    assert calls == []
    with pytest.raises(TypeError, match="ResolvedAsset"):
        TrackNetV3.load(model_path, torch.device("cpu"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="approved ball specification"):
        TrackNetV3.load(
            replace(asset, repository="attacker/model"), torch.device("cpu")
        )


def test_tracknet_loader_resolves_asset_from_configured_storage_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset, model_path = resolved_ball(tmp_path, b"configured-root-checkpoint")
    monkeypatch.setattr(
        tracknet_module, "TRUSTED_BALL_REVISION", asset.resolved_revision
    )
    monkeypatch.setattr(tracknet_module, "TRUSTED_BALL_SHA256", asset.sha256)
    monkeypatch.setattr(
        tracknet_module, "TRUSTED_BALL_BYTE_SIZE", asset.byte_size
    )
    loaded_paths: list[Path] = []

    def record_path(path: Path, _device: torch.device) -> object:
        loaded_paths.append(path)
        raise RuntimeError("loader reached")

    monkeypatch.setattr(tracknet_module, "_restricted_load", record_path)
    with pytest.raises(RuntimeError, match="loader reached"):
        TrackNetV3.load(
            asset,
            torch.device("cpu"),
            storage_root=tmp_path / "storage",
        )

    assert loaded_paths == [model_path.resolve()]


def test_restricted_loader_rejects_nontensor_state_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset, model_path = resolved_ball(tmp_path, b"checkpoint")
    monkeypatch.setattr(
        tracknet_module, "_validated_asset_path", lambda _: model_path
    )
    calls: list[dict[str, Any]] = []

    def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"state_dict": {"predictor.bias": "unsafe"}}

    monkeypatch.setattr(torch, "load", fake_load)
    with pytest.raises(CheckpointFormatError, match="tensor state dict"):
        TrackNetV3.load(asset, torch.device("cpu"))
    assert calls == [{"map_location": torch.device("cpu"), "weights_only": True}]


def test_load_fails_on_missing_unexpected_and_shape_mismatched_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset, model_path = resolved_ball(tmp_path, b"strict checkpoint")
    monkeypatch.setattr(
        tracknet_module, "_validated_asset_path", lambda _: model_path
    )
    monkeypatch.setattr(
        torch,
        "load",
        lambda *args, **kwargs: {
            "state_dict": {"predictor.bias": torch.zeros(3)}
        },
    )
    with pytest.raises(CheckpointFormatError, match="missing|shape|unexpected"):
        TrackNetV3.load(asset, torch.device("cpu"))


def test_four_frame_plus_median_preprocessing_matches_source_channel_order() -> None:
    frames = tuple(frame(index, 10 * (index + 1), width=8, height=6) for index in range(4))
    median = np.empty((6, 8, 3), dtype=np.uint8)
    median[..., 0], median[..., 1], median[..., 2] = 1, 2, 3
    tensor = preprocess_window(frames, median, width=8, height=6)
    assert tensor.shape == (15, 6, 8)
    assert tensor.dtype == np.float32
    expected = [1, 2, 3, 10, 10, 10, 20, 20, 20, 30, 30, 30, 40, 40, 40]
    assert [float(tensor[channel, 0, 0] * 255) for channel in range(15)] == pytest.approx(expected)
    assert 0.0 <= float(tensor.min()) <= float(tensor.max()) <= 1.0


def test_decoder_maps_weighted_centroid_and_covariance_without_letterbox() -> None:
    heatmap = np.zeros((288, 512), dtype=np.float32)
    heatmap[99, 199] = 0.5
    heatmap[99, 200] = 1.0
    decoded = decode_heatmap(heatmap, source_width=1024, source_height=576, threshold=0.4)
    assert len(decoded) == 1
    item = decoded[0]
    assert item.x == pytest.approx((199 * 0.5 + 200) / 1.5 * 2)
    assert item.y == pytest.approx(99 * 2)
    assert item.covariance[0][0] == pytest.approx((2 / 9) * 4)
    assert item.covariance[1][1] >= 0.0


def test_decoder_is_honest_for_no_ball_single_and_comparable_peaks() -> None:
    no_ball = np.zeros((288, 512), dtype=np.float32)
    assert decode_heatmap(no_ball, source_width=512, source_height=288) == ()

    single = no_ball.copy()
    single[20:23, 30:33] = 0.95
    one = decode_heatmap(single, source_width=512, source_height=288)
    assert len(one) == 1 and one[0].peak_probability == pytest.approx(0.95)

    multiple = no_ball.copy()
    multiple[20:23, 30:33] = 0.95
    multiple[80:83, 90:93] = 0.93
    tracker = BallTracker(
        model=lambda batch: torch.from_numpy(multiple[None, None]),
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
        device=torch.device("cpu"),
    )
    row = tracker.track(FrameBatch(tuple(frame(i) for i in range(4))), np.zeros((12, 16, 3), np.uint8))[0]
    assert not row.visible
    assert row.x is None and row.y is None and row.covariance is None
    assert row.ambiguous and row.ambiguity_reason == "comparable_peaks"
    assert row.candidate_count == 2 and len(row.candidates) == 2


def test_decoder_keeps_only_bounded_top_candidates() -> None:
    heatmap = np.zeros((288, 512), dtype=np.float32)
    for index in range(BALL_MAX_CANDIDATES + 7):
        heatmap[10 + index * 10, 20] = 0.99 - index * 0.01
    decoded = decode_heatmap(heatmap, source_width=512, source_height=288, top_n=BALL_MAX_CANDIDATES)
    assert len(decoded) == BALL_MAX_CANDIDATES
    assert tuple(item.peak_probability for item in decoded) == tuple(
        sorted((item.peak_probability for item in decoded), reverse=True)
    )
    with pytest.raises(ValueError, match="candidate bound"):
        decode_heatmap(heatmap, source_width=512, source_height=288, top_n=BALL_MAX_CANDIDATES + 1)

def test_decoder_circularity_work_is_limited_to_component_bounding_boxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heatmap = np.zeros((288, 512), dtype=np.float32)
    locations = [
        (10 + 4 * (index // 40), 10 + 4 * (index % 40))
        for index in range(200)
    ]
    for y, x in locations:
        heatmap[y, x] = 0.9
    processed_pixels: list[int] = []

    def record_local_mask(mask: np.ndarray, area: int) -> float:
        processed_pixels.append(int(mask.size))
        assert mask.size == 1
        assert area == 1
        return 1.0

    monkeypatch.setattr(
        ball_tracker_module, "_component_circularity", record_local_mask
    )
    decoded = decode_heatmap(
        heatmap,
        source_width=512,
        source_height=288,
    )
    assert len(decoded) == BALL_MAX_CANDIDATES
    assert len(processed_pixels) == len(locations)
    assert sum(processed_pixels) == len(locations)

def test_tracker_preserves_total_candidate_count_with_bounded_top_evidence() -> None:
    heatmap = np.zeros((288, 512), dtype=np.float32)
    for index in range(BALL_MAX_CANDIDATES + 7):
        heatmap[10 + index * 10, 20] = 0.99 - index * 0.01
    tracker = BallTracker(
        model=lambda batch: torch.from_numpy(heatmap[None, None]),
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
        device=torch.device("cpu"),
    )
    row = tracker.track(
        FrameBatch(tuple(frame(index) for index in range(4))),
        np.zeros((12, 16, 3), np.uint8),
    )[0]
    assert row.candidate_count == BALL_MAX_CANDIDATES + 7
    assert len(row.candidates) == BALL_MAX_CANDIDATES
    assert (row.source_width, row.source_height) == (16, 12)



def test_overlapping_windows_preserve_global_fourth_frame_provenance() -> None:
    heatmap = np.zeros((288, 512), dtype=np.float32)
    heatmap[144, 256] = 1.0
    tracker = BallTracker(
        model=lambda batch: torch.from_numpy(np.repeat(heatmap[None, None], len(batch), axis=0)),
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
        device=torch.device("cpu"),
        inference_batch_size=2,
    )
    batch = FrameBatch(tuple(frame(i) for i in range(7)))
    rows = tracker.track(batch, np.zeros((12, 16, 3), np.uint8))
    assert [row.source_frame_index for row in rows] == [103, 104, 105, 106]
    assert [row.source_timestamp_us for row in rows] == [130_000, 170_000, 210_000, 250_000]
    assert all(row.timestamp_us == row.source_timestamp_us for row in rows)
    assert all(
        (row.source_width, row.source_height) == (16, 12) for row in rows
    )


def test_tracker_prefers_mps_after_successful_native_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.setattr(torch, "empty", lambda *args, **kwargs: object())
    monkeypatch.setattr(torch.mps, "synchronize", lambda: None)
    tracker = BallTracker(
        model=object(),
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
    )
    assert tracker.device == torch.device("mps")


def test_tracker_uses_cpu_when_mps_smoke_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)

    def fail_mps(*args: object, **kwargs: object) -> object:
        raise RuntimeError("MPS allocation unavailable")

    monkeypatch.setattr(torch, "empty", fail_mps)
    tracker = BallTracker(
        model=object(),
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
    )
    assert tracker.device == torch.device("cpu")
    assert not tracker.device_fallback


def test_mps_failure_falls_back_to_cpu_once_per_tracker() -> None:
    heatmap = torch.zeros((1, 1, 288, 512))
    calls: list[str] = []

    def runner(model: object, batch: torch.Tensor, device: torch.device) -> torch.Tensor:
        calls.append(device.type)
        if device.type == "mps":
            raise RuntimeError("unsupported MPS operation")
        return heatmap.repeat(batch.shape[0], 1, 1, 1)

    tracker = BallTracker(
        model=object(),
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
        device=torch.device("mps"),
        inference_runner=runner,
    )
    batch = FrameBatch(tuple(frame(i) for i in range(4)))
    first = tracker.track(batch, np.zeros((12, 16, 3), np.uint8))[0]
    second = tracker.track(batch, np.zeros((12, 16, 3), np.uint8))[0]
    assert calls == ["mps", "cpu", "cpu"]
    assert first.device == second.device == "cpu"
    assert first.device_fallback and second.device_fallback


def test_median_background_uniform_sampling_is_bounded_and_deterministic() -> None:
    assert uniform_sample_indices(10, 201) == tuple(range(10))
    indices = uniform_sample_indices(1_000_000, 201)
    assert len(indices) == 201 and indices[0] == 0 and indices[-1] == 999_999
    assert indices == uniform_sample_indices(1_000_000, 201)
    images = tuple(np.full((2, 3, 3), index, np.uint8) for index in range(255))
    first = median_background(images)
    second = median_background(images)
    assert np.array_equal(first, second)
    assert np.all(first == 127)


def test_constant_acceleration_selection_uses_motion_not_largest_peak() -> None:
    points = [
        observation(0, x=10.0, y=20.0),
        observation(1, x=20.0, y=20.0),
        observation(
            2,
            x=None,
            y=None,
            candidates=(candidate(30.0, 20.0, 0.70), candidate(150.0, 20.0, 0.99)),
            ambiguous=True,
        ),
    ]
    segments = repair_track(points, None)
    assert len(segments.segments) == 1
    assert segments.segments[0].points[-1].x == pytest.approx(30.0)
    assert segments.segments[0].points[-1].ambiguous

def test_candidate_selection_scores_retained_evidence_before_visible_first_peak() -> None:
    points = [
        observation(0, x=10.0, y=20.0),
        observation(1, x=20.0, y=20.0),
        observation(
            2,
            x=150.0,
            y=20.0,
            candidates=(
                candidate(150.0, 20.0, 0.99),
                candidate(30.0, 20.0, 0.75),
            ),
            ambiguous=False,
        ),
    ]
    repaired = repair_track(points, None)
    assert len(repaired.segments) == 1
    assert repaired.segments[0].points[-1].x == pytest.approx(30.0)



def test_kalman_acceleration_prediction_beats_a_higher_probability_lagging_peak() -> None:
    points = [
        observation(0, x=0.0, y=20.0),
        observation(1, x=1.0, y=20.0),
        observation(2, x=4.0, y=20.0),
        observation(3, x=9.0, y=20.0),
        observation(
            4,
            x=None,
            y=None,
            candidates=(candidate(16.0, 20.0, 0.70), candidate(12.0, 20.0, 0.99)),
            ambiguous=True,
        ),
    ]
    repaired = repair_track(points, None)
    assert repaired.segments[0].points[-1].x == pytest.approx(16.0)


def test_acceleration_gate_rejects_implausible_candidate_and_splits() -> None:
    points = [
        observation(0, x=10.0, y=20.0),
        observation(1, x=20.0, y=20.0),
        observation(2, x=None, y=None, candidates=(candidate(500.0, 250.0),)),
    ]
    segments = repair_track(points, None)
    assert len(segments.segments) == 1
    assert [point.x for point in segments.segments[0].points] == [10.0, 20.0]


def test_short_gap_interpolates_only_with_observed_endpoints_and_expands_covariance() -> None:
    points = [
        observation(0, x=10.0, y=10.0),
        observation(1, x=None, y=None),
        observation(2, x=30.0, y=10.0),
    ]
    segments = repair_track(points, None)
    repaired = segments.segments[0].points
    assert len(repaired) == 3
    middle = repaired[1]
    assert middle.evidence is EvidenceKind.INTERPOLATED
    assert middle.source_timestamp_us is None and middle.source_frame_index is None
    assert middle.x == pytest.approx(20.0)
    assert middle.covariance is not None
    assert middle.covariance[0][0] > repaired[0].covariance[0][0]
    assert middle.evidence_start_frame_index == 100
    assert middle.evidence_end_frame_index == 102


def test_900ms_gap_splits_segments_without_inventing_points() -> None:
    points = [
        observation(0, x=10.0, y=10.0, timestamp_us=0),
        observation(1, x=None, y=None, timestamp_us=200_000),
        observation(2, x=None, y=None, timestamp_us=500_000),
        observation(3, x=20.0, y=20.0, timestamp_us=900_000),
    ]
    segments = repair_track(points, None)
    assert len(segments.segments) == 2
    assert [
        [point.timestamp_us for point in segment.points]
        for segment in segments.segments
    ] == [[0], [900_000]]


def test_observed_points_over_250ms_apart_split_without_explicit_missing_rows() -> None:
    points = [
        observation(0, x=10.0, y=10.0, timestamp_us=0),
        observation(1, x=20.0, y=10.0, timestamp_us=300_000),
    ]
    segments = repair_track(points, None)
    assert len(segments.segments) == 2
    assert [
        [point.timestamp_us for point in segment.points]
        for segment in segments.segments
    ] == [[0], [300_000]]


def test_implausible_short_gap_splits_and_long_missing_state_is_bounded() -> None:
    implausible = [
        observation(0, x=10.0, y=10.0, timestamp_us=0),
        observation(1, x=None, y=None, timestamp_us=100_000),
        observation(2, x=500.0, y=250.0, timestamp_us=200_000),
    ]
    assert len(repair_track(implausible, None).segments) == 2
    long_missing = [observation(0, x=10.0, y=10.0, timestamp_us=0)]
    long_missing.extend(
        observation(i + 1, x=None, y=None, timestamp_us=(i + 1) * 100_000)
        for i in range(10_000)
    )
    result = repair_track(long_missing, None)
    assert result.max_pending_gap_count <= 64
    assert sum(len(segment.points) for segment in result.segments) == 1


def test_optional_calibration_only_gates_plausibility_and_never_claims_3d() -> None:
    calibration = CalibrationResult(
        calibrated=True,
        image_to_court=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        court_to_image=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        residuals_px=(),
        rms_error_px=0.0,
        max_error_px=0.0,
        inlier_mask=(),
        condition_number=1.0,
        parameter_covariance=None,
        confidence=1.0,
        capabilities=CalibrationCapabilities(True, True, True, True),
        warnings=(),
    )
    points = [observation(0, x=3.0, y=4.0)]
    repaired = repair_track(points, calibration).segments[0].points[0]
    assert repaired.x == 3.0 and repaired.y == 4.0
    assert not hasattr(repaired, "z") and not hasattr(repaired, "floor")


def test_ball_parquet_roundtrip_preserves_exact_provenance_and_candidates(tmp_path: Path) -> None:
    path = tmp_path / "ball.parquet"
    rows = (
        replace(observation(0, x=10.0, y=20.0), segment_id="segment-0001"),
        replace(observation(1, x=None, y=None, ambiguous=True, candidates=(candidate(12, 20), candidate(40, 80, 0.88))), segment_id=None),
    )
    info = write_ball_observations(path, rows)
    assert info.row_count == 2 and info.artifact_kind == "ball_observations"
    assert read_ball_observations(path) == rows
    metadata = pq.read_schema(path).metadata or {}
    assert metadata[b"source_manifest_id"] == b"source-sha256"
    assert metadata[b"model_manifest_id"] == b"ball-sha256"
    assert metadata[b"candidate_bound"] == str(BALL_MAX_CANDIDATES).encode()


def test_ball_parquet_zero_row_requires_and_preserves_manifests(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    with pytest.raises(ValueError, match="source_manifest_id"):
        write_ball_observations(path, ())
    info = write_ball_observations(
        path,
        (),
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
    )
    assert info.row_count == 0 and read_ball_observations(path) == ()
    metadata = pq.read_schema(path).metadata or {}
    assert metadata[b"source_manifest_id"] == b"source-sha256"
    assert metadata[b"model_manifest_id"] == b"ball-sha256"


def test_ball_parquet_rejects_corrupt_schema_metadata_and_provenance(tmp_path: Path) -> None:
    path = tmp_path / "ball.parquet"
    write_ball_observations(path, (observation(0, x=10.0, y=20.0),))
    table = pq.read_table(path)

    pq.write_table(table.append_column("extra", pa.array([1])), path)
    with pytest.raises(ValueError, match="column schema"):
        read_ball_observations(path)

    write_ball_observations(path, (observation(0, x=10.0, y=20.0),))
    table = pq.read_table(path)
    metadata = dict(table.schema.metadata or {})
    metadata[b"candidate_bound"] = b"999"
    pq.write_table(table.replace_schema_metadata(metadata), path)
    with pytest.raises(ValueError, match="candidate bound"):
        read_ball_observations(path)

    write_ball_observations(path, (observation(0, x=10.0, y=20.0),))
    table = pq.read_table(path)
    metadata = dict(table.schema.metadata or {})
    metadata[b"source_manifest_id"] = b""
    pq.write_table(table.replace_schema_metadata(metadata), path)
    with pytest.raises(ValueError, match="blank manifest"):
        read_ball_observations(path)


def test_ball_parquet_rejects_incomplete_bounded_candidate_slots(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ball.parquet"
    write_ball_observations(path, (observation(0, x=10.0, y=20.0),))
    table = pq.read_table(path)
    column_index = table.column_names.index("candidate_count")
    table = table.set_column(
        column_index,
        table.schema.field(column_index),
        pa.array([2], type=pa.int32()),
    )
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="complete bounded candidate evidence"):
        read_ball_observations(path)


def test_ball_parquet_rejects_unordered_indices_and_nonfinite_covariance(tmp_path: Path) -> None:
    path = tmp_path / "ball.parquet"
    rows = (observation(0, x=10.0, y=20.0), observation(1, x=12.0, y=21.0))
    write_ball_observations(path, rows)
    table = pq.read_table(path)
    reversed_indices = pa.array([101, 100], type=pa.int64())
    for column in (
        "source_frame_index",
        "evidence_start_frame_index",
        "evidence_end_frame_index",
    ):
        column_index = table.column_names.index(column)
        table = table.set_column(
            column_index, table.schema.field(column_index), reversed_indices
        )
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="unordered source"):
        read_ball_observations(path)

    write_ball_observations(path, (observation(0, x=10.0, y=20.0),))
    table = pq.read_table(path)
    covariance_index = table.column_names.index("covariance")
    table = table.set_column(
        covariance_index,
        "covariance",
        pa.array(
            [{"xx": float("nan"), "xy": 0.0, "yx": 0.0, "yy": 2.0}],
            type=table.schema.field("covariance").type,
        ),
    )
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="nonfinite"):
        read_ball_observations(path)


def test_ball_observation_enforces_visibility_evidence_and_candidate_invariants() -> None:
    row = observation(0, x=10.0, y=20.0)
    with pytest.raises(ValueError, match="visible"):
        replace(row, x=None)
    with pytest.raises(ValueError, match="candidate count"):
        replace(row, candidate_count=0)
    with pytest.raises(ValueError, match="complete bounded candidate evidence"):
        replace(row, candidate_count=2)
    with pytest.raises(ValueError, match="manifest"):
        replace(row, source_manifest_id="")
    with pytest.raises(ValueError, match="candidate bound"):
        replace(
            row,
            candidates=tuple(candidate(float(i), 0.0) for i in range(BALL_MAX_CANDIDATES + 1)),
            candidate_count=BALL_MAX_CANDIDATES + 1,
        )


def test_tracknet_attribution_contains_exact_upstream_mit_license() -> None:
    attribution = (
        Path(tracknet_module.__file__).with_name("ATTRIBUTION.txt").read_text()
    )
    license_text = """MIT License

Copyright (c) 2025 Linfeng Dong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
    assert license_text in attribution
