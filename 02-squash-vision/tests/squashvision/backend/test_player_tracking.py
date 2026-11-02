from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from squashvision.calibration import (
    CalibrationCapabilities,
    CalibrationResult,
)
from squashvision.model_assets import (
    APPLICATION_COMPATIBILITY_VERSION,
    POSE_ASSET,
    ResolvedAsset,
)
from squashvision.models import ModelAssetState
from squashvision.observations import (
    APPEARANCE_DIMENSION,
    BoundingBox,
    EvidenceKind,
    FloorEstimate,
    Frame,
    FrameBatch,
    Keypoint,
    PlayerObservation,
    PoseDetection,
    PoseDetections,
    read_player_observations,
    write_player_observations,
)
import squashvision.vision.players as players_module
from squashvision.vision.players import (
    PlayerDetector,
    PlayerIdentityTracker,
    UnsupportedArchitectureError,
)

def embedding(index: int) -> tuple[float, ...]:
    values = [0.0] * APPEARANCE_DIMENSION
    values[index] = 1.0
    return tuple(values)


def make_tracker(**kwargs: object) -> PlayerIdentityTracker:
    return PlayerIdentityTracker(
        source_manifest_id="video-sha256",
        model_manifest_id="pose-sha256",
        **kwargs,
    )


def resolved_pose(
    tmp_path: Path, payload: bytes = b"approved pose model"
) -> tuple[ResolvedAsset, Path, Path]:
    storage_root = tmp_path / "storage"
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("models") / f"{digest}.pt"
    model_path = storage_root / relative
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(payload)
    asset = ResolvedAsset(
        name=POSE_ASSET.name,
        source=POSE_ASSET.source,
        url=POSE_ASSET.repo_id,
        repository=None,
        filename=POSE_ASSET.filename,
        requested_revision=POSE_ASSET.revision,
        resolved_revision=POSE_ASSET.revision,
        etag=None,
        local_path=relative,
        byte_size=len(payload),
        sha256=digest,
        declared_license="AGPL-3.0",
        downloaded_at=datetime.now(UTC),
        compatibility_version=APPLICATION_COMPATIBILITY_VERSION,
        required=True,
        state=ModelAssetState.READY,
        error_code=None,
    )
    return asset, storage_root, model_path


def keypoints(cx: float, feet_y: float, confidence: float = 0.9) -> tuple[Keypoint, ...]:
    return tuple(
        Keypoint(cx + (index % 3) - 1, feet_y - 20 + index, confidence)
        for index in range(17)
    )


def detection(
    cx: float,
    *,
    timestamp_us: int = 0,
    frame_index: int = 0,
    appearance: tuple[float, ...] | None = None,
    court_overlap: float = 1.0,
    confidence: float = 0.9,
) -> PoseDetection:
    return PoseDetection(
        box=BoundingBox(cx - 5, 20, cx + 5, 80),
        keypoints=keypoints(cx, 80),
        confidence=confidence,
        frame_index=frame_index,
        timestamp_us=timestamp_us,
        appearance=embedding(0) if appearance is None else appearance,
        feet=(cx, 80.0),
        feet_uncertainty_px=2.0,
        court_overlap=court_overlap,
    )


def detections(
    timestamp_us: int,
    *items: PoseDetection,
    source_frame_index: int = 0,
) -> PoseDetections:
    normalized = tuple(
        replace(
            item,
            timestamp_us=timestamp_us,
            frame_index=source_frame_index,
        )
        for item in items
    )
    return PoseDetections(
        timestamp_us=timestamp_us,
        frame_index=source_frame_index,
        detections=normalized,
        device="cpu",
        device_fallback=False,
    )


def observation(
    timestamp_us: int = 100_000,
    *,
    player_id: str = "A",
    floor: FloorEstimate | None = None,
) -> PlayerObservation:
    item = detection(40, timestamp_us=timestamp_us)
    return PlayerObservation(
        player_id=player_id,
        timestamp_us=timestamp_us,
        source_timestamp_us=timestamp_us,
        source_frame_index=3,
        box=item.box,
        keypoints=item.keypoints,
        detection_confidence=item.confidence,
        appearance=item.appearance,
        feet=item.feet,
        feet_uncertainty_px=item.feet_uncertainty_px,
        evidence=EvidenceKind.OBSERVED,
        evidence_start_timestamp_us=timestamp_us,
        evidence_end_timestamp_us=timestamp_us,
        evidence_start_frame_index=3,
        evidence_end_frame_index=3,
        association_confidence=0.8,
        ambiguous=False,
        ambiguity_reason=None,
        floor=floor,
        source_manifest_id="video-sha256",
        model_manifest_id="pose-sha256",
    )


def test_frame_batch_requires_real_ordered_bgr_frames() -> None:
    image = np.zeros((12, 16, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="nonempty"):
        FrameBatch(())
    with pytest.raises(ValueError, match="strictly increasing"):
        FrameBatch(
            (
                Frame(timestamp_us=2, source_frame_index=1, image=image),
                Frame(timestamp_us=2, source_frame_index=2, image=image.copy()),
            )
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        FrameBatch(
            (
                Frame(timestamp_us=2, source_frame_index=2, image=image),
                Frame(timestamp_us=3, source_frame_index=2, image=image.copy()),
            )
        )
    with pytest.raises(ValueError, match="BGR"):
        Frame(
            timestamp_us=0,
            source_frame_index=0,
            image=np.zeros((12, 16), dtype=np.uint8),
        )

def test_pose_batch_rejects_mismatched_source_frame_provenance() -> None:
    with pytest.raises(ValueError, match="source frame"):
        replace(
            detections(100, detection(20), source_frame_index=7),
            frame_index=8,
        )


class ArrayValue:
    def __init__(self, value: object) -> None:
        self.value = np.asarray(value)

    def cpu(self) -> ArrayValue:
        return self

    def numpy(self) -> np.ndarray:
        return self.value


class FakeResult:
    def __init__(self) -> None:
        self.boxes = SimpleNamespace(
            xyxy=ArrayValue([[2.0, 3.0, 10.0, 18.0]]),
            conf=ArrayValue([0.75]),
        )
        self.keypoints = SimpleNamespace(
            xy=ArrayValue([[[5.0, float(index + 1)] for index in range(17)]]),
            conf=ArrayValue([[0.8] * 17]),
        )


class RecordingModel:
    def __init__(self, *, fail_mps: bool = False) -> None:
        self.fail_mps = fail_mps
        self.devices: list[str] = []

    def predict(self, *, source: list[np.ndarray], device: str, **kwargs: object) -> list[FakeResult]:
        self.devices.append(device)
        assert len(source) == 1
        if device == "mps" and self.fail_mps:
            raise RuntimeError("MPS kernel failed")
        return [FakeResult()]


class FakeTorch:
    def __init__(self, available: bool) -> None:
        self.backends = SimpleNamespace(
            mps=SimpleNamespace(is_available=lambda: available)
        )
        self.mps = SimpleNamespace(synchronize=lambda: None)

    @staticmethod
    def empty(size: int, *, device: str) -> np.ndarray:
        assert size == 1 and device == "mps"
        return np.empty(1)

class BrokenMpsTorch(FakeTorch):
    @staticmethod
    def empty(size: int, *, device: str) -> np.ndarray:
        raise RuntimeError("MPS allocation unavailable")


def test_detector_validates_resolved_asset_and_normalizes_yolo(tmp_path: Path) -> None:
    asset, storage_root, model_path = resolved_pose(tmp_path)
    loaded: list[str] = []
    model = RecordingModel()
    detector = PlayerDetector(
        asset,
        storage_root=storage_root,
        model_loader=lambda path: loaded.append(path) or model,
        torch_module=FakeTorch(False),
        court_polygon=np.array(
            [[0, 0], [16, 0], [16, 20], [0, 20]], dtype=np.float32
        ),
    )
    batch = FrameBatch(
        (
            Frame(
                timestamp_us=123,
                source_frame_index=42,
                image=np.full((20, 16, 3), 127, np.uint8),
            ),
        )
    )

    result = detector.detect(batch)[0]

    assert loaded == [str(model_path.resolve())]
    assert result.timestamp_us == 123
    assert result.frame_index == 42
    assert result.device == "cpu"
    assert result.detections[0].frame_index == 42
    assert result.detections[0].box == BoundingBox(2.0, 3.0, 10.0, 18.0)
    assert len(result.detections[0].keypoints) == 17
    assert result.detections[0].keypoints[0] == Keypoint(5.0, 1.0, 0.8)
    assert result.detections[0].court_overlap > 0.9
    assert len(result.detections[0].appearance) == APPEARANCE_DIMENSION
    assert all(np.isfinite(result.detections[0].appearance))


def test_image_playing_area_removes_spectators_but_keeps_uncertain_player_and_edge_tolerance(tmp_path: Path) -> None:
    asset, storage_root, _ = resolved_pose(tmp_path)
    result = FakeResult()
    boxes = [[530, 430, 618, 636], [347, 535, 427, 669],
             [1197, 299, 1278, 507], [192, 650, 212, 721]]
    result.boxes.xyxy = ArrayValue(boxes)
    result.boxes.conf = ArrayValue([0.79, 0.37, 0.95, 0.3])
    result.keypoints.xy = ArrayValue([
        [[(x1 + x2) / 2, y2] for _ in range(17)] for x1, y1, x2, y2 in boxes
    ])
    result.keypoints.conf = ArrayValue([[0.8] * 17 for _ in boxes])
    model = RecordingModel()
    model.predict = lambda **_: [result]
    detector = PlayerDetector(asset, storage_root=storage_root,
        model_loader=lambda _: model, torch_module=FakeTorch(False),
        playing_area_polygon=np.asarray([[374, 384], [902, 384], [1075, 719], [202, 719]], dtype=np.float32))
    frame = Frame(timestamp_us=12_520_000, source_frame_index=313,
                  image=np.zeros((720, 1280, 3), dtype=np.uint8))
    items = detector.detect(FrameBatch((frame,)))[0].detections
    assert len(items) == 3
    assert [item.confidence for item in items] == [0.79, 0.37, 0.3]
    assert all(item.box.x1 < 1197 for item in items)
    assert all(item.court_overlap == 1 for item in items)


def test_detector_rejects_arbitrary_or_replaced_pt_before_loader(tmp_path: Path) -> None:
    asset, storage_root, model_path = resolved_pose(tmp_path)
    calls = 0

    def loader(_: str) -> object:
        nonlocal calls
        calls += 1
        return object()

    with pytest.raises(TypeError, match="ResolvedAsset"):
        PlayerDetector(model_path, storage_root=storage_root, model_loader=loader)

    model_path.write_bytes(b"replaced after resolution")
    with pytest.raises(ValueError, match="digest or size"):
        PlayerDetector(asset, storage_root=storage_root, model_loader=loader)

    assert calls == 0

def test_detector_rejects_darwin_x86_before_model_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset, storage_root, _ = resolved_pose(tmp_path)
    calls = 0

    def loader(_: str) -> object:
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr(players_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(players_module.platform, "machine", lambda: "x86_64")

    with pytest.raises(UnsupportedArchitectureError, match="native arm64"):
        PlayerDetector(asset, storage_root=storage_root, model_loader=loader)

    assert calls == 0


def test_detector_rejects_non_ready_or_missing_resolved_asset(tmp_path: Path) -> None:
    asset, storage_root, model_path = resolved_pose(tmp_path)
    with pytest.raises(ValueError, match="READY"):
        PlayerDetector(
            replace(asset, state=ModelAssetState.MISSING),
            storage_root=storage_root,
            model_loader=lambda _: RecordingModel(),
        )
    model_path.unlink()
    with pytest.raises(FileNotFoundError, match="resolved pose asset"):
        PlayerDetector(
            asset,
            storage_root=storage_root,
            model_loader=lambda _: RecordingModel(),
        )


def test_production_loader_forces_offline_and_safe_weight_loading_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset, storage_root, model_path = resolved_pose(tmp_path)
    loaded: list[tuple[str, str, bool]] = []

    def fake_yolo(path: str, *, task: str, verbose: bool) -> RecordingModel:
        loaded.append((path, task, verbose))
        return RecordingModel()

    monkeypatch.delenv("YOLO_OFFLINE", raising=False)
    monkeypatch.delenv("ULTRALYTICS_SAFE_LOAD", raising=False)
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=fake_yolo))

    PlayerDetector(
        asset,
        storage_root=storage_root,
        torch_module=FakeTorch(False),
    )

    assert os.environ["YOLO_OFFLINE"] == "true"
    assert os.environ["ULTRALYTICS_SAFE_LOAD"] == "true"
    assert loaded == [(str(model_path.resolve()), "pose", False)]


def test_long_pose_chunks_use_bounded_batches_with_exact_frame_provenance(tmp_path: Path) -> None:
    asset, storage_root, _ = resolved_pose(tmp_path)
    batches = []
    class Model:
        def predict(self, *, source, device, **kwargs):
            batches.append((len(source), device))
            return [FakeResult() for _ in source]
    detector = PlayerDetector(asset, storage_root=storage_root, model_loader=lambda _: Model(),
        torch_module=FakeTorch(False), inference_batch_size=4)
    frames = FrameBatch(tuple(Frame(timestamp_us=index * 40_000, source_frame_index=index,
        image=np.zeros((20, 16, 3), dtype=np.uint8)) for index in range(11)))
    result = detector.detect(frames)
    assert batches == [(4, "cpu"), (4, "cpu"), (3, "cpu")]
    assert [item.frame_index for item in result] == list(range(11))
    assert [item.timestamp_us for item in result] == [index * 40_000 for index in range(11)]


def test_later_pose_batch_fallback_preserves_prior_mps_provenance(tmp_path: Path) -> None:
    asset, storage_root, _ = resolved_pose(tmp_path)
    batches = []
    class Model:
        def predict(self, *, source, device, **kwargs):
            batches.append((len(source), device))
            if len(batches) == 2 and device == "mps":
                raise RuntimeError("simulated later MPS failure")
            return [FakeResult() for _ in source]
    detector = PlayerDetector(asset, storage_root=storage_root, model_loader=lambda _: Model(),
        torch_module=FakeTorch(True), inference_batch_size=2)
    frames = FrameBatch(tuple(Frame(timestamp_us=index, source_frame_index=index,
        image=np.zeros((20, 16, 3), dtype=np.uint8)) for index in range(5)))
    result = detector.detect(frames)
    assert batches == [(2, "mps"), (2, "mps"), (2, "cpu"), (1, "cpu")]
    assert [item.device for item in result] == ["mps", "mps", "cpu", "cpu", "cpu"]
    assert [item.device_fallback for item in result] == [False, False, True, True, True]


def test_mps_inference_failure_retries_cpu_exactly_once(tmp_path: Path) -> None:
    asset, storage_root, _ = resolved_pose(tmp_path)
    model = RecordingModel(fail_mps=True)
    detector = PlayerDetector(
        asset,
        storage_root=storage_root,
        model_loader=lambda _: model,
        torch_module=FakeTorch(True),
    )

    result = detector.detect(
        FrameBatch(
            (
                Frame(
                    timestamp_us=1,
                    source_frame_index=8,
                    image=np.zeros((20, 16, 3), dtype=np.uint8),
                ),
            )
        )
    )[0]

    assert model.devices == ["mps", "cpu"]
    assert result.device == "cpu"
    assert result.device_fallback


def test_failed_mps_smoke_selects_cpu_without_marking_inference_fallback(
    tmp_path: Path,
) -> None:
    asset, storage_root, _ = resolved_pose(tmp_path)
    model = RecordingModel()
    detector = PlayerDetector(
        asset,
        storage_root=storage_root,
        model_loader=lambda _: model,
        torch_module=BrokenMpsTorch(True),
    )

    result = detector.detect(
        FrameBatch(
            (
                Frame(
                    timestamp_us=1,
                    source_frame_index=8,
                    image=np.zeros((20, 16, 3), dtype=np.uint8),
                ),
            )
        )
    )[0]

    assert model.devices == ["cpu"]
    assert result.device == "cpu"
    assert not result.device_fallback


def test_invalid_crops_produce_a_finite_neutral_embedding(tmp_path: Path) -> None:
    asset, storage_root, _ = resolved_pose(tmp_path)
    result = FakeResult()
    result.boxes.xyxy = ArrayValue([[40.0, 40.0, 50.0, 50.0]])
    model = RecordingModel()
    model.predict = lambda **_: [result]  # type: ignore[method-assign]
    detector = PlayerDetector(
        asset,
        storage_root=storage_root,
        model_loader=lambda _: model,
        torch_module=FakeTorch(False),
    )

    appearance = detector.detect(
        FrameBatch(
            (
                Frame(
                    timestamp_us=1,
                    source_frame_index=8,
                    image=np.zeros((20, 16, 3), dtype=np.uint8),
                ),
            )
        )
    )[0].detections[0].appearance

    assert len(appearance) == APPEARANCE_DIMENSION
    assert np.isfinite(appearance).all()
    assert np.count_nonzero(appearance) == 0

def test_observation_types_reject_wrong_appearance_dimension() -> None:
    with pytest.raises(ValueError, match="72"):
        replace(detection(20), appearance=(1.0, 0.0))
    with pytest.raises(ValueError, match="72"):
        replace(observation(), appearance=(1.0, 0.0))
    with pytest.raises(ValueError, match="observed source"):
        replace(observation(), source_timestamp_us=99)


def test_tracker_requires_real_manifest_identifiers() -> None:
    with pytest.raises(ValueError, match="manifest"):
        PlayerIdentityTracker(
            source_manifest_id="",
            model_manifest_id="pose-sha256",
        )
    with pytest.raises(ValueError, match="manifest"):
        PlayerIdentityTracker(
            source_manifest_id="video-sha256",
            model_manifest_id="",
        )


def test_transient_spectator_or_reflection_does_not_become_active() -> None:
    tracker = make_tracker(min_initial_persistence=2)
    assert tracker.update(
        0,
        detections(0, detection(25), detection(90, court_overlap=0.0)),
    ) == ()

    rows = tracker.update(100_000, detections(100_000, detection(27)))

    assert [(row.player_id, row.feet[0]) for row in rows] == [("A", 27)]


def test_initial_selection_caps_active_players_at_two_and_uses_quality() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    rows = tracker.update(
        0,
        detections(
            0,
            detection(20, confidence=0.95),
            detection(50, confidence=0.9),
            detection(80, confidence=0.2, court_overlap=0.1),
        ),
    )

    assert len(rows) == 2
    assert {row.player_id for row in rows} == {"A", "B"}
    assert {row.feet[0] for row in rows} == {20, 50}


def test_crossing_players_keep_identity_when_appearance_is_distinct() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    red = embedding(0)
    blue = embedding(1)
    tracker.update(0, detections(0, detection(20, appearance=red), detection(80, appearance=blue)))
    tracker.update(
        100_000,
        detections(100_000, detection(40, appearance=red), detection(60, appearance=blue)),
    )

    rows = tracker.update(
        200_000,
        detections(200_000, detection(65, appearance=red), detection(35, appearance=blue)),
    )

    by_id = {row.player_id: row for row in rows}
    assert by_id["A"].feet[0] == 65
    assert by_id["B"].feet[0] == 35
    assert not any(row.ambiguous for row in rows)

def test_distinct_crossing_is_not_ambiguous_when_detector_order_changes() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    red = embedding(0)
    blue = embedding(1)
    tracker.update(
        0,
        detections(0, detection(20, appearance=red), detection(80, appearance=blue)),
    )

    rows = tracker.update(
        100_000,
        detections(
            100_000,
            detection(60, appearance=blue),
            detection(40, appearance=red),
        ),
    )

    by_id = {row.player_id: row for row in rows}
    assert by_id["A"].feet[0] == 40
    assert by_id["B"].feet[0] == 60
    assert not any(row.ambiguous for row in rows)


def test_indistinguishable_crossing_emits_explicit_ambiguity() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    same = embedding(0)
    tracker.update(0, detections(0, detection(30, appearance=same), detection(70, appearance=same)))
    tracker.update(
        100_000,
        detections(100_000, detection(46, appearance=same), detection(54, appearance=same)),
    )

    rows = tracker.update(
        200_000,
        detections(200_000, detection(52, appearance=same), detection(48, appearance=same)),
    )

    assert len(rows) == 2
    assert all(row.ambiguous for row in rows)
    assert {row.ambiguity_reason for row in rows} == {"assignment_cost_margin"}


def test_ambiguous_crossing_cannot_replace_stable_shirt_identity() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    red, blue = embedding(0), embedding(1)
    merged = tuple((a+b)/np.sqrt(2) for a, b in zip(red, blue, strict=True))
    tracker.update(0, detections(0, detection(20, appearance=red), detection(80, appearance=blue)))
    uncertain = tracker.update(100_000, detections(100_000,
        detection(48, appearance=merged), detection(52, appearance=merged)))
    assert all(row.ambiguous for row in uncertain)
    assert tracker._tracks["A"].appearance_anchor == red
    assert tracker._tracks["A"].last_timestamp_us == 0
    # Reversing out of an occlusion must not follow the guessed crossing velocity.
    tracker.update(200_000, detections(200_000))
    resolved = tracker.update(300_000, detections(300_000,
        detection(70, appearance=blue), detection(30, appearance=red)))
    assert {row.player_id: row.feet[0] for row in resolved} == {"A": 30, "B": 70}
    assert not any(row.ambiguous for row in resolved)


def test_distinct_anchor_vetoes_motion_only_swap_after_occlusion() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    red, blue = embedding(0), embedding(1)
    tracker.update(0, detections(0, detection(20, appearance=red), detection(80, appearance=blue)))
    tracker.update(100_000, detections(100_000))
    rows = tracker.update(200_000, detections(200_000,
        detection(80, appearance=red), detection(20, appearance=blue), source_frame_index=2))
    assert {row.player_id: row.feet[0] for row in rows} == {"A": 80, "B": 20}


def test_torso_appearance_excludes_background_and_separates_shirt_colors() -> None:
    box = BoundingBox(0, 0, 100, 100)
    points = [Keypoint(0, 0, 0) for _ in range(17)]
    for index, position in {5:(30,20), 6:(70,20), 11:(30,70), 12:(70,70)}.items():
        points[index] = Keypoint(*position, 0.95)
    yellow = np.full((100,100,3), (25,40,190), dtype=np.uint8)
    yellow[20:71,30:71] = (20,220,230)
    changed_background = np.full_like(yellow, (210,200,30))
    changed_background[20:71,30:71] = (20,220,230)
    navy = yellow.copy()
    navy[20:71,30:71] = (80,35,20)
    first = players_module._appearance_embedding(yellow, box, tuple(points))
    second = players_module._appearance_embedding(changed_background, box, tuple(points))
    other = players_module._appearance_embedding(navy, box, tuple(points))
    assert first == second
    assert players_module._cosine_distance(first, other) >= 0.2
    points[5] = Keypoint(30,20,0.1)
    assert not any(players_module._appearance_embedding(yellow, box, tuple(points)))

def test_merged_detection_does_not_commit_arbitrary_identity_and_interval_persists() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    red = embedding(0)
    blue = embedding(1)
    merged = tuple(
        (left + right) / np.sqrt(2.0) for left, right in zip(red, blue, strict=True)
    )
    tracker.update(
        0,
        detections(
            0,
            detection(20, appearance=red),
            detection(80, appearance=blue),
            source_frame_index=0,
        ),
    )

    assert tracker.update(
        100_000,
        detections(
            100_000,
            detection(50, appearance=merged),
            source_frame_index=1,
        ),
    ) == ()

    unresolved = tracker.update(
        200_000,
        detections(
            200_000,
            detection(40, appearance=red),
            source_frame_index=2,
        ),
    )
    assert len(unresolved) == 1
    assert unresolved[0].player_id == "A"
    assert unresolved[0].ambiguous
    assert unresolved[0].ambiguity_reason == "unresolved_identity_interval"

    resolved = tracker.update(
        300_000,
        detections(
            300_000,
            detection(45, appearance=red),
            detection(55, appearance=blue),
            source_frame_index=3,
        ),
    )
    assert {row.player_id for row in resolved if row.timestamp_us == 300_000} == {
        "A",
        "B",
    }
    assert not any(row.ambiguous for row in resolved)


def test_extra_in_court_spectator_makes_comparable_assignment_explicit() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    red = embedding(0)
    blue = embedding(1)
    tracker.update(
        0,
        detections(0, detection(20, appearance=red), detection(80, appearance=blue)),
    )

    rows = tracker.update(
        100_000,
        detections(
            100_000,
            detection(40, appearance=red),
            detection(60, appearance=blue),
            detection(42, appearance=red),
        ),
    )

    assert len(rows) == 2
    assert all(row.ambiguous for row in rows)
    assert {row.ambiguity_reason for row in rows} == {"assignment_cost_margin"}


def test_short_occlusion_is_interpolated_only_after_observed_endpoint() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    red = embedding(0)
    blue = embedding(1)
    tracker.update(
        0,
        detections(
            0,
            detection(20, appearance=red),
            detection(80, appearance=blue),
            source_frame_index=0,
        ),
    )
    during_gap = tracker.update(
        100_000,
        detections(
            100_000,
            detection(70, appearance=blue),
            source_frame_index=1,
        ),
    )
    assert all(row.player_id != "A" for row in during_gap)

    rows = tracker.update(
        200_000,
        detections(
            200_000,
            detection(40, appearance=red),
            detection(60, appearance=blue),
            source_frame_index=2,
        ),
    )

    interpolated = [
        row for row in rows if row.player_id == "A" and row.timestamp_us == 100_000
    ]
    assert len(interpolated) == 1
    assert interpolated[0].evidence is EvidenceKind.INTERPOLATED
    assert interpolated[0].feet == (30.0, 80.0)
    assert interpolated[0].evidence_start_timestamp_us == 0
    assert interpolated[0].evidence_end_timestamp_us == 200_000
    assert interpolated[0].source_timestamp_us is None
    assert interpolated[0].source_frame_index is None
    assert interpolated[0].evidence_start_frame_index == 0
    assert interpolated[0].evidence_end_frame_index == 2


def test_long_gap_does_not_invent_player_positions() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    tracker.update(0, detections(0, detection(20)))
    assert tracker.update(400_000, detections(400_000)) == ()

    rows = tracker.update(500_000, detections(500_000, detection(40)))

    assert [(row.timestamp_us, row.evidence) for row in rows] == [
        (500_000, EvidenceKind.OBSERVED)
    ]

def test_pending_gap_storage_clears_once_interpolation_window_expires() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    tracker.update(0, detections(0, detection(20)))
    tracker.update(100_000, detections(100_000))
    tracker.update(200_000, detections(200_000))
    tracker.update(300_000, detections(300_000))
    assert tracker.pending_gap_count == 3

    tracker.update(400_000, detections(400_000))
    assert tracker.pending_gap_count == 0
    for timestamp_us in range(500_000, 2_000_001, 100_000):
        tracker.update(timestamp_us, detections(timestamp_us))
        assert tracker.pending_gap_count == 0


def test_established_track_gets_only_500ms_outside_court_grace() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    tracker.update(0, detections(0, detection(30)))
    grace = tracker.update(
        400_000, detections(400_000, detection(35, court_overlap=0.0))
    )
    expired = tracker.update(
        600_001, detections(600_001, detection(37, court_overlap=0.0))
    )

    assert len(grace) == 1 and grace[0].player_id == "A"
    assert expired == ()


def test_source_timestamps_drive_velocity_across_variable_frame_intervals() -> None:
    tracker = make_tracker(min_initial_persistence=1)
    tracker.update(0, detections(0, detection(10)))
    tracker.update(100_000, detections(100_000, detection(20)))

    rows = tracker.update(350_000, detections(350_000, detection(45)))

    assert len(rows) == 1
    assert rows[0].timestamp_us == 350_000
    assert rows[0].feet[0] == 45
    assert rows[0].source_timestamp_us == 350_000


def identity_calibration() -> CalibrationResult:
    return CalibrationResult(
        calibrated=True,
        image_to_court=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        court_to_image=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        residuals_px=(0.0,) * 4,
        rms_error_px=0.0,
        max_error_px=0.0,
        inlier_mask=(True,) * 4,
        condition_number=1.0,
        parameter_covariance=None,
        confidence=1.0,
        capabilities=CalibrationCapabilities(True, True, True, True),
        warnings=(),
    )


def test_optional_floor_estimate_is_tagged_with_calibration_provenance() -> None:
    tracker = make_tracker(
        min_initial_persistence=1,
        calibration=identity_calibration(),
        calibration_revision="calibration-r7",
        calibration_provenance="manual-court-points",
    )

    row = tracker.update(0, detections(0, detection(3)))[0]

    assert row.floor is not None
    assert row.floor.point_m == (3.0, 80.0)
    assert row.floor.calibration_revision == "calibration-r7"
    assert row.floor.calibration_provenance == "manual-court-points"


def test_parquet_roundtrip_preserves_raw_evidence_and_metadata(tmp_path: Path) -> None:
    floor = FloorEstimate(
        point_m=(3.0, 4.0),
        uncertainty_m=0.2,
        calibration_revision="r1",
        calibration_provenance="manual",
    )
    rows = (observation(100_000, floor=floor), observation(200_000, player_id="B"))
    path = tmp_path / "players.parquet"

    info = write_player_observations(path, rows)
    restored = read_player_observations(path)
    metadata = pq.read_metadata(path).metadata or {}

    assert restored == rows
    assert info.row_count == 2
    assert info.min_timestamp_us == 100_000
    assert info.max_timestamp_us == 200_000
    assert metadata[b"artifact_kind"] == b"player_observations"
    assert metadata[b"schema_version"] == b"2"
    assert metadata[b"coordinate_conventions"] == b"image_bgr_pixels_xyxy_coco17"
    assert metadata[b"source_manifest_id"] == b"video-sha256"
    assert metadata[b"model_manifest_id"] == b"pose-sha256"

def test_empty_parquet_requires_and_preserves_explicit_manifests(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    with pytest.raises(ValueError, match="manifest"):
        write_player_observations(path, ())

    info = write_player_observations(
        path,
        (),
        source_manifest_id="video-sha256",
        model_manifest_id="pose-sha256",
    )
    metadata = pq.read_metadata(path).metadata or {}

    assert info.row_count == 0
    assert read_player_observations(path) == ()
    assert metadata[b"source_manifest_id"] == b"video-sha256"
    assert metadata[b"model_manifest_id"] == b"pose-sha256"


def test_parquet_reader_rejects_blank_manifest_metadata(tmp_path: Path) -> None:
    path = tmp_path / "players.parquet"
    write_player_observations(path, (observation(),))
    table = pq.read_table(path)
    metadata = dict(table.schema.metadata or {})
    metadata[b"source_manifest_id"] = b""
    pq.write_table(table.replace_schema_metadata(metadata), path)

    with pytest.raises(ValueError, match="blank manifest"):
        read_player_observations(path)


def test_raw_pose_survives_floor_calibration_revision_changes(tmp_path: Path) -> None:
    raw = observation(
        floor=FloorEstimate((1.0, 2.0), 0.1, "r1", "manual")
    )
    revised = replace(
        raw,
        floor=FloorEstimate((2.0, 3.0), 0.3, "r2", "auto-refit"),
    )
    first_path = tmp_path / "first.parquet"
    revised_path = tmp_path / "revised.parquet"
    write_player_observations(first_path, (raw,))
    write_player_observations(revised_path, (revised,))

    first = read_player_observations(first_path)[0]
    second = read_player_observations(revised_path)[0]

    assert (first.box, first.keypoints, first.feet, first.appearance) == (
        second.box,
        second.keypoints,
        second.feet,
        second.appearance,
    )
    assert first.floor != second.floor


def test_parquet_reader_rejects_wrong_schema_metadata(tmp_path: Path) -> None:
    path = tmp_path / "players.parquet"
    write_player_observations(path, (observation(),))
    table = pq.read_table(path)
    metadata = dict(table.schema.metadata or {})
    metadata[b"schema_version"] = b"999"
    pq.write_table(table.replace_schema_metadata(metadata), path)

    with pytest.raises(ValueError, match="schema version"):
        read_player_observations(path)

def test_parquet_reader_rejects_missing_schema_metadata(tmp_path: Path) -> None:
    path = tmp_path / "players.parquet"
    write_player_observations(path, (observation(),))
    table = pq.read_table(path)
    metadata = dict(table.schema.metadata or {})
    del metadata[b"coordinate_conventions"]
    pq.write_table(table.replace_schema_metadata(metadata), path)

    with pytest.raises(ValueError, match="missing required schema metadata"):
        read_player_observations(path)


def test_parquet_reader_rejects_invalid_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "players.parquet"
    write_player_observations(path, (observation(),))
    table = pq.read_table(path)
    column_index = table.schema.get_field_index("timestamp_us")
    table = table.set_column(
        column_index,
        table.schema.field(column_index),
        pa.array([-1], type=pa.int64()),
    )
    metadata = dict(table.schema.metadata or {})
    metadata[b"min_timestamp_us"] = b"-1"
    metadata[b"max_timestamp_us"] = b"-1"
    pq.write_table(table.replace_schema_metadata(metadata), path)

    with pytest.raises(ValueError, match="nonnegative"):
        read_player_observations(path)


def test_parquet_reader_rejects_nonfinite_required_values(tmp_path: Path) -> None:
    path = tmp_path / "players.parquet"
    write_player_observations(path, (observation(),))
    table = pq.read_table(path)
    column_index = table.schema.get_field_index("box_x1")
    table = table.set_column(
        column_index,
        table.schema.field(column_index),
        pa.array([float("nan")], type=pa.float64()),
    )
    pq.write_table(table, path)

    with pytest.raises(ValueError, match="nonfinite"):
        read_player_observations(path)
