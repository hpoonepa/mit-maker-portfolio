from __future__ import annotations

import hashlib
import math
import os
import platform
from dataclasses import dataclass, field
from itertools import permutations
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment

from squashvision.calibration import CalibrationResult, ImagePoint, project_floor
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
    FrameBatch,
    Keypoint,
    PlayerObservation,
    PoseDetection,
    PoseDetections,
)

_APPEARANCE_SIZE = APPEARANCE_DIMENSION
_MIN_COURT_OVERLAP = 0.05
_OUTSIDE_COURT_GRACE_US = 500_000
_MAX_INTERPOLATION_GAP_US = 300_000
_ASSIGNMENT_GATE = 2.0
AMBIGUITY_COST_MARGIN = 0.18
PLAYER_IDENTITY_POLICY_VERSION = "torso-anchor-v1"

class UnsupportedArchitectureError(RuntimeError):
    pass


def _production_model_loader(path: str) -> Any:
    os.environ["YOLO_OFFLINE"] = "true"
    os.environ["ULTRALYTICS_SAFE_LOAD"] = "true"
    from ultralytics import YOLO

    return YOLO(path, task="pose", verbose=False)


def _numpy(value: Any) -> NDArray[np.float64]:
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value, dtype=np.float64)


def _normalise_histogram(values: NDArray[np.float64]) -> NDArray[np.float64]:
    total = float(values.sum())
    if total > 0.0 and math.isfinite(total):
        return values / total
    return np.zeros_like(values)


def _appearance_embedding(
    image: NDArray[np.uint8], box: BoundingBox,
    keypoints: tuple[Keypoint, ...] | None = None,
) -> tuple[float, ...]:
    height, width = image.shape[:2]
    x1 = max(0, min(width, int(math.floor(box.x1))))
    y1 = max(0, min(height, int(math.floor(box.y1))))
    x2 = max(0, min(width, int(math.ceil(box.x2))))
    y2 = max(0, min(height, int(math.ceil(box.y2))))
    if x2 <= x1 or y2 <= y1:
        return (0.0,) * _APPEARANCE_SIZE
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return (0.0,) * _APPEARANCE_SIZE
    try:
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        grayscale = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = np.ones(crop.shape[:2], dtype=bool)
        if keypoints is not None:
            # Shoulder/hip support isolates the shirt from the court, shorts,
            # skin and racket inside a person box. Unreliable torso geometry
            # contributes no appearance evidence rather than a background cue.
            torso = [keypoints[index] for index in (5, 6, 12, 11)]
            if any(point.confidence < 0.5 for point in torso):
                return (0.0,) * _APPEARANCE_SIZE
            polygon = np.asarray([[p.x - x1, p.y - y1] for p in torso], dtype=np.float32)
            polygon = polygon.mean(axis=0) + 0.75 * (polygon - polygon.mean(axis=0))
            if not cv2.isContourConvex(polygon) or cv2.contourArea(polygon) < 16:
                return (0.0,) * _APPEARANCE_SIZE
            torso_mask = np.zeros(crop.shape[:2], dtype=np.uint8)
            cv2.fillConvexPoly(torso_mask, np.rint(polygon).astype(np.int32), 1)
            mask = torso_mask.astype(bool)
            if np.count_nonzero(mask) < 16:
                return (0.0,) * _APPEARANCE_SIZE
        components = [
            _normalise_histogram(
                np.histogram(hsv[..., 0][mask], bins=24, range=(0, 180))[0].astype(np.float64)
            ),
            _normalise_histogram(
                np.histogram(hsv[..., 1][mask], bins=16, range=(0, 256))[0].astype(np.float64)
            ),
            _normalise_histogram(
                np.histogram(hsv[..., 2][mask], bins=16, range=(0, 256))[0].astype(np.float64)
            ),
        ]
        center = grayscale.astype(np.int16)
        right = np.roll(center, -1, axis=1)
        down = np.roll(center, -1, axis=0)
        texture_code = np.clip((right - center) // 16 + 8, 0, 15)
        texture_code ^= np.clip((down - center) // 32 + 4, 0, 7)
        components.append(
            _normalise_histogram(
                np.histogram(texture_code[mask], bins=16, range=(0, 16))[0].astype(np.float64)
            )
        )
        combined = np.concatenate(components)
        norm = float(np.linalg.norm(combined))
        if norm > 0.0 and math.isfinite(norm):
            combined /= norm
        if combined.size != _APPEARANCE_SIZE or not np.isfinite(combined).all():
            return (0.0,) * _APPEARANCE_SIZE
        return tuple(float(value) for value in combined)
    except (cv2.error, ValueError, FloatingPointError):
        return (0.0,) * _APPEARANCE_SIZE


def _court_overlap(box: BoundingBox, polygon: NDArray[np.float32] | None) -> float:
    if polygon is None:
        return 1.0
    rectangle = np.asarray(
        [[box.x1, box.y1], [box.x2, box.y1], [box.x2, box.y2], [box.x1, box.y2]],
        dtype=np.float32,
    )
    try:
        area, _ = cv2.intersectConvexConvex(rectangle, polygon)
    except cv2.error:
        return 0.0
    return max(0.0, min(1.0, float(area) / (box.width * box.height)))


def _feet(keypoints: tuple[Keypoint, ...], box: BoundingBox) -> tuple[tuple[float, float], float]:
    ankles = tuple(point for point in (keypoints[15], keypoints[16]) if point.confidence >= 0.1)
    if not ankles:
        return ((box.x1 + box.x2) / 2.0, box.y2), box.width / 2.0
    weight = sum(point.confidence for point in ankles)
    x = sum(point.x * point.confidence for point in ankles) / weight
    y = sum(point.y * point.confidence for point in ankles) / weight
    average_confidence = weight / len(ankles)
    uncertainty = max(1.0, box.width * (1.0 - average_confidence))
    return (float(x), float(y)), float(uncertainty)


class PlayerDetector:
    def __init__(
        self,
        asset: ResolvedAsset,
        *,
        storage_root: Path,
        model_loader: Callable[[str], Any] = _production_model_loader,
        torch_module: Any | None = None,
        court_polygon: NDArray[np.float32] | None = None,
        playing_area_polygon: NDArray[np.float32] | None = None,
        inference_batch_size: int = 8,
    ) -> None:
        if platform.system() == "Darwin" and platform.machine() != "arm64":
            raise UnsupportedArchitectureError(
                "pose inference on Darwin requires a native arm64 Python runtime"
            )
        if not 1 <= inference_batch_size <= 128:
            raise ValueError("pose inference batch size must be between 1 and 128")
        self._batch_size = inference_batch_size
        self.model_path = self._validated_model_path(asset, storage_root)
        self._model = model_loader(str(self.model_path))
        if torch_module is None:
            import torch

            torch_module = torch
        self._torch = torch_module
        self._device = self._select_device()
        if court_polygon is None:
            self._court_polygon = None
        else:
            polygon = np.asarray(court_polygon, dtype=np.float32)
            if polygon.ndim != 2 or polygon.shape[0] < 3 or polygon.shape[1] != 2:
                raise ValueError("court polygon must contain at least three image points")
            if not np.isfinite(polygon).all():
                raise ValueError("court polygon must be finite")
            self._court_polygon = polygon
        self._playing_area_polygon = None
        if playing_area_polygon is not None:
            polygon = np.asarray(playing_area_polygon, dtype=np.float32)
            if (polygon.ndim != 2 or polygon.shape[0] < 3 or polygon.shape[1] != 2
                    or not np.isfinite(polygon).all() or not cv2.isContourConvex(polygon)):
                raise ValueError("playing area must be a finite convex image polygon")
            self._playing_area_polygon = polygon

    @staticmethod
    def _validated_model_path(asset: ResolvedAsset, storage_root: Path) -> Path:
        if not isinstance(asset, ResolvedAsset):
            raise TypeError("pose detector requires a ResolvedAsset")
        if asset.state is not ModelAssetState.READY:
            raise ValueError("pose detector requires a READY model asset")
        if asset.compatibility_version != APPLICATION_COMPATIBILITY_VERSION:
            raise ValueError("pose model asset is incompatible with this application")
        if (
            asset.name != POSE_ASSET.name
            or asset.source != POSE_ASSET.source
            or asset.url != POSE_ASSET.repo_id
            or asset.repository is not None
            or asset.filename != POSE_ASSET.filename
            or asset.requested_revision != POSE_ASSET.revision
            or asset.resolved_revision != POSE_ASSET.revision
            or asset.error_code is not None
            or asset.downloaded_at is None
            or not asset.required
        ):
            raise ValueError("resolved model asset does not match the approved pose specification")
        if (
            asset.local_path is None
            or asset.sha256 is None
            or len(asset.sha256) != 64
            or any(character not in "0123456789abcdef" for character in asset.sha256)
            or asset.byte_size is None
            or asset.byte_size <= 0
        ):
            raise ValueError("READY pose asset is missing integrity provenance")
        relative = Path(asset.local_path)
        expected_relative = Path("models") / f"{asset.sha256}.pt"
        if relative != expected_relative:
            raise ValueError("resolved pose asset path does not match its digest")
        root = Path(storage_root).expanduser().resolve()
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError("resolved pose asset escapes managed storage") from error
        if not resolved.is_file():
            raise FileNotFoundError(f"resolved pose asset does not exist: {resolved}")
        # The READY registry record is the trust root. Verify its content address
        # immediately before Ultralytics performs restricted weights-only loading.
        digest = hashlib.sha256()
        byte_size = 0
        with resolved.open("rb") as model_file:
            while chunk := model_file.read(64 * 1024):
                byte_size += len(chunk)
                digest.update(chunk)
        if byte_size != asset.byte_size or digest.hexdigest() != asset.sha256:
            raise ValueError("resolved pose asset digest or size no longer matches")
        return resolved

    def _select_device(self) -> str:
        try:
            if not self._torch.backends.mps.is_available():
                return "cpu"
            self._torch.empty(1, device="mps")
            self._torch.mps.synchronize()
            return "mps"
        except (AttributeError, RuntimeError, NotImplementedError):
            return "cpu"

    def _predict(self, images: list[NDArray[np.uint8]], device: str) -> Any:
        return self._model.predict(
            source=images,
            device=device,
            verbose=False,
            stream=False,
            save=False,
            show=False,
        )

    def detect(self, frames: FrameBatch) -> list[PoseDetections]:
        images = [frame.image for frame in frames]
        device = self._device
        fallback = False
        materialized: list[tuple[Any, str, bool]] = []
        for start in range(0, len(images), self._batch_size):
            batch = images[start : start + self._batch_size]
            try:
                results = list(self._predict(batch, device))
            except Exception:
                if device != "mps":
                    raise
                results = list(self._predict(batch, "cpu"))
                device = "cpu"
                fallback = True
                self._device = "cpu"
            if len(results) != len(batch):
                raise ValueError("pose model returned a different result count than the frame batch")
            materialized.extend((result, device, fallback) for result in results)
        normalized: list[PoseDetections] = []
        for frame, (result, result_device, result_fallback) in zip(frames, materialized, strict=True):
            boxes = _numpy(result.boxes.xyxy)
            confidences = _numpy(result.boxes.conf).reshape(-1)
            points = _numpy(result.keypoints.xy)
            point_confidence_value = getattr(result.keypoints, "conf", None)
            point_confidences = (
                np.ones(points.shape[:2], dtype=np.float64)
                if point_confidence_value is None
                else _numpy(point_confidence_value)
            )
            count = len(boxes)
            if len(confidences) != count or points.shape != (count, 17, 2) or point_confidences.shape != (count, 17):
                raise ValueError("pose model result has an invalid COCO keypoint shape")
            items: list[PoseDetection] = []
            for index in range(count):
                box = BoundingBox(*(float(value) for value in boxes[index]))
                pose = tuple(
                    Keypoint(
                        float(points[index, keypoint_index, 0]),
                        float(points[index, keypoint_index, 1]),
                        float(np.clip(point_confidences[index, keypoint_index], 0.0, 1.0)),
                    )
                    for keypoint_index in range(17)
                )
                feet, feet_uncertainty = _feet(pose, box)
                if self._playing_area_polygon is not None:
                    # A reviewed image mask is a hard eligibility constraint,
                    # independent of metric court calibration or tracker grace.
                    tolerance = max(2.0, min(frame.image.shape[:2]) * 0.01)
                    bottom_center = ((box.x1 + box.x2) / 2.0, box.y2)
                    if not any(cv2.pointPolygonTest(self._playing_area_polygon, point, True) >= -tolerance
                               for point in (feet, bottom_center)):
                        continue
                items.append(
                    PoseDetection(
                        box=box,
                        keypoints=pose,
                        confidence=float(np.clip(confidences[index], 0.0, 1.0)),
                        frame_index=frame.source_frame_index,
                        timestamp_us=frame.timestamp_us,
                        appearance=_appearance_embedding(frame.image, box, pose),
                        feet=feet,
                        feet_uncertainty_px=feet_uncertainty,
                        court_overlap=(1.0 if self._playing_area_polygon is not None
                                       else _court_overlap(box, self._court_polygon)),
                    )
                )
            normalized.append(
                PoseDetections(
                    timestamp_us=frame.timestamp_us,
                    frame_index=frame.source_frame_index,
                    detections=tuple(items),
                    device=result_device,
                    device_fallback=result_fallback,
                )
            )
        return normalized


@dataclass(slots=True)
class _Candidate:
    detection: PoseDetection
    count: int
    last_timestamp_us: int


@dataclass(slots=True)
class _Track:
    player_id: str
    detection: PoseDetection
    last_timestamp_us: int
    appearance_anchor: tuple[float, ...] = ()
    velocity: tuple[float, float] = (0.0, 0.0)
    last_inside_timestamp_us: int = 0
    pending_timestamps_us: list[int] = field(default_factory=list)
    ambiguity_active: bool = False

    def predicted_feet(self, timestamp_us: int) -> tuple[float, float]:
        elapsed = timestamp_us - self.last_timestamp_us
        return (
            self.detection.feet[0] + self.velocity[0] * elapsed,
            self.detection.feet[1] + self.velocity[1] * elapsed,
        )


def _cosine_distance(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    if len(first) != len(second):
        return 1.0
    left = np.asarray(first, dtype=np.float64)
    right = np.asarray(second, dtype=np.float64)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= 1.0e-12:
        return 0.0 if np.linalg.norm(left - right) <= 1.0e-12 else 1.0
    return float(np.clip(1.0 - float(np.dot(left, right) / denominator), 0.0, 2.0))


def _lerp(first: float, second: float, ratio: float) -> float:
    return first + (second - first) * ratio


class PlayerIdentityTracker:
    def __init__(
        self,
        *,
        source_manifest_id: str,
        model_manifest_id: str,
        min_initial_persistence: int = 2,
        calibration: CalibrationResult | None = None,
        calibration_revision: str | None = None,
        calibration_provenance: str | None = None,
    ) -> None:
        if min_initial_persistence <= 0:
            raise ValueError("initial persistence must be positive")
        if calibration is not None and (not calibration_revision or not calibration_provenance):
            raise ValueError("calibration estimates require revision and provenance")
        if not source_manifest_id.strip() or not model_manifest_id.strip():
            raise ValueError("tracker requires nonempty source and model manifest identifiers")
        self.min_initial_persistence = min_initial_persistence
        self.calibration = calibration
        self.calibration_revision = calibration_revision
        self.calibration_provenance = calibration_provenance
        self.source_manifest_id = source_manifest_id
        self.model_manifest_id = model_manifest_id
        self._tracks: dict[str, _Track] = {}
        self._candidates: list[_Candidate] = []
        self._last_timestamp_us: int | None = None

    def _floor(self, feet: tuple[float, float]) -> FloorEstimate | None:
        if self.calibration is None:
            return None
        estimate = project_floor(ImagePoint(*feet), self.calibration)
        if estimate.value is None or estimate.uncertainty is None:
            return None
        return FloorEstimate(
            point_m=(estimate.value.x_m, estimate.value.y_m),
            uncertainty_m=estimate.uncertainty,
            calibration_revision=str(self.calibration_revision),
            calibration_provenance=str(self.calibration_provenance),
        )

    def _allowed_for_track(self, track: _Track, item: PoseDetection, timestamp_us: int) -> bool:
        return item.court_overlap >= _MIN_COURT_OVERLAP or (
            timestamp_us - track.last_inside_timestamp_us <= _OUTSIDE_COURT_GRACE_US
        )

    def _cost(self, track: _Track, item: PoseDetection, timestamp_us: int) -> float:
        predicted_x, predicted_y = track.predicted_feet(timestamp_us)
        scale = max(track.detection.box.height, item.box.height, 1.0)
        motion = math.hypot(item.feet[0] - predicted_x, item.feet[1] - predicted_y) / scale
        has_appearance = np.linalg.norm(item.appearance) > 1e-12
        has_anchor = np.linalg.norm(track.appearance_anchor) > 1e-12
        appearance = _cosine_distance(track.appearance_anchor, item.appearance) if has_appearance and has_anchor else 0.0
        if has_appearance and has_anchor:
            for other in self._tracks.values():
                if other is track or np.linalg.norm(other.appearance_anchor) <= 1e-12:
                    continue
                # Distinct stable shirts can veto a motion-only identity swap.
                # Similar/absent colors do not create a forced identity choice.
                separation = _cosine_distance(track.appearance_anchor, other.appearance_anchor)
                alternative = _cosine_distance(other.appearance_anchor, item.appearance)
                if separation >= 0.2 and alternative <= 0.35 and appearance - alternative >= 0.12:
                    return math.inf
        pose_scale = abs(math.log(max(item.box.height, 1.0) / max(track.detection.box.height, 1.0)))
        floor_distance = 0.0
        floor_weight = 0.0
        if self.calibration is not None:
            predicted_floor = self._floor((predicted_x, predicted_y))
            item_floor = self._floor(item.feet)
            if predicted_floor is not None and item_floor is not None:
                floor_distance = math.dist(predicted_floor.point_m, item_floor.point_m) / 6.4
                floor_weight = 0.1
        return 0.5 * motion + 0.35 * appearance + 0.15 * pose_scale + floor_weight * floor_distance

    def _update_candidates(self, timestamp_us: int, items: list[PoseDetection]) -> None:
        prior = self._candidates
        updated: list[_Candidate] = []
        used: set[int] = set()
        for item in items:
            if item.court_overlap < _MIN_COURT_OVERLAP:
                continue
            best_index: int | None = None
            best_cost = math.inf
            for index, candidate in enumerate(prior):
                if index in used or timestamp_us <= candidate.last_timestamp_us:
                    continue
                elapsed_s = (timestamp_us - candidate.last_timestamp_us) / 1_000_000.0
                distance = math.dist(item.feet, candidate.detection.feet)
                if elapsed_s <= 1.0 and distance < 80.0 and distance < best_cost:
                    best_index = index
                    best_cost = distance
            if best_index is None:
                updated.append(_Candidate(item, 1, timestamp_us))
            else:
                candidate = prior[best_index]
                used.add(best_index)
                updated.append(_Candidate(item, candidate.count + 1, timestamp_us))
        self._candidates = updated

    def _activate_candidates(self, timestamp_us: int) -> list[tuple[_Track, PoseDetection]]:
        slots = 2 - len(self._tracks)
        if slots <= 0:
            self._candidates.clear()
            return []
        eligible = [
            candidate
            for candidate in self._candidates
            if candidate.count >= self.min_initial_persistence
        ]
        eligible.sort(
            key=lambda candidate: (
                0.4 * candidate.detection.court_overlap
                + 0.25 * candidate.detection.confidence
                + 0.25 * candidate.detection.pose_completeness
                + 0.1 * min(candidate.count / self.min_initial_persistence, 2.0),
            ),
            reverse=True,
        )
        activated: list[tuple[_Track, PoseDetection]] = []
        available_ids = [player_id for player_id in ("A", "B") if player_id not in self._tracks]
        for candidate, player_id in zip(eligible[:slots], available_ids):
            item = candidate.detection
            track = _Track(
                player_id=player_id,
                detection=item,
                last_timestamp_us=timestamp_us,
                appearance_anchor=item.appearance,
                last_inside_timestamp_us=timestamp_us,
            )
            self._tracks[player_id] = track
            activated.append((track, item))
        self._candidates = [candidate for candidate in self._candidates if candidate not in eligible[:slots]]
        return activated

    def _observed(
        self,
        track: _Track,
        item: PoseDetection,
        cost: float,
        ambiguity_reason: str | None,
    ) -> PlayerObservation:
        return PlayerObservation(
            player_id=track.player_id,
            timestamp_us=item.timestamp_us,
            source_timestamp_us=item.timestamp_us,
            source_frame_index=item.frame_index,
            box=item.box,
            keypoints=item.keypoints,
            detection_confidence=item.confidence,
            appearance=item.appearance,
            feet=item.feet,
            feet_uncertainty_px=item.feet_uncertainty_px,
            evidence=EvidenceKind.OBSERVED,
            evidence_start_timestamp_us=item.timestamp_us,
            evidence_end_timestamp_us=item.timestamp_us,
            evidence_start_frame_index=item.frame_index,
            evidence_end_frame_index=item.frame_index,
            association_confidence=float(np.clip(1.0 - cost / _ASSIGNMENT_GATE, 0.0, 1.0)),
            ambiguous=ambiguity_reason is not None,
            ambiguity_reason=ambiguity_reason,
            floor=self._floor(item.feet),
            source_manifest_id=self.source_manifest_id,
            model_manifest_id=self.model_manifest_id,
        )

    def _interpolated(
        self,
        track: _Track,
        start: PoseDetection,
        end: PoseDetection,
        timestamp_us: int,
        ambiguity_reason: str | None,
    ) -> PlayerObservation:
        ratio = (timestamp_us - start.timestamp_us) / (end.timestamp_us - start.timestamp_us)
        box = BoundingBox(
            _lerp(start.box.x1, end.box.x1, ratio),
            _lerp(start.box.y1, end.box.y1, ratio),
            _lerp(start.box.x2, end.box.x2, ratio),
            _lerp(start.box.y2, end.box.y2, ratio),
        )
        points = tuple(
            Keypoint(
                _lerp(first.x, second.x, ratio),
                _lerp(first.y, second.y, ratio),
                _lerp(first.confidence, second.confidence, ratio),
            )
            for first, second in zip(start.keypoints, end.keypoints, strict=True)
        )
        appearance = tuple(
            _lerp(first, second, ratio)
            for first, second in zip(start.appearance, end.appearance, strict=True)
        )
        feet = (
            _lerp(start.feet[0], end.feet[0], ratio),
            _lerp(start.feet[1], end.feet[1], ratio),
        )
        return PlayerObservation(
            player_id=track.player_id,
            timestamp_us=timestamp_us,
            source_timestamp_us=None,
            source_frame_index=None,
            box=box,
            keypoints=points,
            detection_confidence=_lerp(start.confidence, end.confidence, ratio),
            appearance=appearance,
            feet=feet,
            feet_uncertainty_px=_lerp(start.feet_uncertainty_px, end.feet_uncertainty_px, ratio),
            evidence=EvidenceKind.INTERPOLATED,
            evidence_start_timestamp_us=start.timestamp_us,
            evidence_end_timestamp_us=end.timestamp_us,
            evidence_start_frame_index=start.frame_index,
            evidence_end_frame_index=end.frame_index,
            association_confidence=0.0,
            ambiguous=ambiguity_reason is not None,
            ambiguity_reason=ambiguity_reason,
            floor=self._floor(feet),
            source_manifest_id=self.source_manifest_id,
            model_manifest_id=self.model_manifest_id,
        )

    @property
    def pending_gap_count(self) -> int:
        return sum(len(track.pending_timestamps_us) for track in self._tracks.values())

    @staticmethod
    def _assignment_options(
        costs: NDArray[np.float64],
    ) -> list[tuple[float, tuple[tuple[int, int, float], ...]]]:
        track_count, item_count = costs.shape
        options: list[tuple[float, tuple[tuple[int, int, float], ...]]] = []

        def consider(
            total: float, pairs: tuple[tuple[int, int, float], ...]
        ) -> None:
            options.append((total, pairs))
            options.sort(key=lambda option: option[0])
            if len(options) > 2:
                options.pop()

        if track_count == 2 and item_count >= 2:
            for item_indices in permutations(range(item_count), 2):
                values = (
                    float(costs[0, item_indices[0]]),
                    float(costs[1, item_indices[1]]),
                )
                if all(math.isfinite(value) for value in values):
                    consider(
                        sum(values),
                        (
                            (0, item_indices[0], values[0]),
                            (1, item_indices[1], values[1]),
                        ),
                    )
        elif track_count == 2 and item_count == 1:
            for track_index in range(2):
                value = float(costs[track_index, 0])
                if math.isfinite(value):
                    consider(value, ((track_index, 0, value),))
        elif track_count == 1:
            for item_index in range(item_count):
                value = float(costs[0, item_index])
                if math.isfinite(value):
                    consider(value, ((0, item_index, value),))
        return options

    def update(
        self, timestamp_us: int, detections: PoseDetections
    ) -> tuple[PlayerObservation, ...]:
        if timestamp_us != detections.timestamp_us:
            raise ValueError("tracker timestamp must match pose detections")
        if self._last_timestamp_us is not None and timestamp_us <= self._last_timestamp_us:
            raise ValueError("tracker timestamps must be strictly increasing")
        self._last_timestamp_us = timestamp_us
        items = list(detections.detections)
        if not self._tracks:
            self._update_candidates(timestamp_us, items)
            activated = self._activate_candidates(timestamp_us)
            return tuple(
                self._observed(track, item, 0.0, None) for track, item in activated
            )

        tracks = list(self._tracks.values())
        costs = np.full((len(tracks), len(items)), np.inf, dtype=np.float64)
        for track_index, track in enumerate(tracks):
            for item_index, item in enumerate(items):
                if self._allowed_for_track(track, item, timestamp_us):
                    value = self._cost(track, item, timestamp_us)
                    if value <= _ASSIGNMENT_GATE:
                        costs[track_index, item_index] = value

        options = self._assignment_options(costs)
        comparable = (
            len(options) >= 2
            and options[1][0] - options[0][0] < AMBIGUITY_COST_MARGIN
        )
        if options:
            matches = list(options[0][1])
        else:
            matches: list[tuple[int, int, float]] = []
            if items and np.isfinite(costs).any():
                safe = np.where(np.isfinite(costs), costs, _ASSIGNMENT_GATE + 1.0)
                row_indices, column_indices = linear_sum_assignment(safe)
                matches = [
                    (int(row), int(column), float(costs[row, column]))
                    for row, column in zip(row_indices, column_indices, strict=True)
                    if math.isfinite(float(costs[row, column]))
                ]

        if comparable:
            for track in tracks:
                track.ambiguity_active = True
                track.pending_timestamps_us.clear()
            if len(tracks) == 2 and len(items) == 1:
                matches.clear()

        full_confident_resolution = (
            len(tracks) == 2
            and len(matches) == 2
            and not comparable
        )
        if full_confident_resolution:
            for track in tracks:
                track.ambiguity_active = False

        matched_tracks = {track_index for track_index, _, _ in matches}
        matched_items = {item_index for _, item_index, _ in matches}
        output: list[PlayerObservation] = []
        for track_index, item_index, cost in matches:
            track = tracks[track_index]
            item = items[item_index]
            start = track.detection
            gap = timestamp_us - track.last_timestamp_us
            if comparable:
                ambiguity_reason = "assignment_cost_margin"
            elif track.ambiguity_active:
                ambiguity_reason = "unresolved_identity_interval"
            else:
                ambiguity_reason = None
            if (
                ambiguity_reason is None
                and track.pending_timestamps_us
                and gap <= _MAX_INTERPOLATION_GAP_US
            ):
                output.extend(
                    self._interpolated(
                        track,
                        start,
                        item,
                        missing_timestamp,
                        None,
                    )
                    for missing_timestamp in track.pending_timestamps_us
                    if start.timestamp_us < missing_timestamp < item.timestamp_us
                )
            track.pending_timestamps_us.clear()
            if ambiguity_reason is None:
                elapsed = timestamp_us - track.last_timestamp_us
                if elapsed > 0:
                    track.velocity = (
                        (item.feet[0] - start.feet[0]) / elapsed,
                        (item.feet[1] - start.feet[1]) / elapsed,
                    )
                track.detection = item
                track.last_timestamp_us = timestamp_us
                if np.linalg.norm(track.appearance_anchor) <= 1e-12 and np.linalg.norm(item.appearance) > 1e-12:
                    track.appearance_anchor = item.appearance
                if item.court_overlap >= _MIN_COURT_OVERLAP:
                    track.last_inside_timestamp_us = timestamp_us
            output.append(self._observed(track, item, cost, ambiguity_reason))

        ambiguity_interval_active = any(track.ambiguity_active for track in tracks)
        for track_index, track in enumerate(tracks):
            if track_index in matched_tracks:
                continue
            gap = timestamp_us - track.last_timestamp_us
            if ambiguity_interval_active or gap > _MAX_INTERPOLATION_GAP_US:
                track.pending_timestamps_us.clear()
            else:
                track.pending_timestamps_us.append(timestamp_us)

        unmatched = [item for index, item in enumerate(items) if index not in matched_items]
        self._update_candidates(timestamp_us, unmatched)
        for track, item in self._activate_candidates(timestamp_us):
            output.append(self._observed(track, item, 0.0, None))
        output.sort(key=lambda row: (row.timestamp_us, row.player_id))
        return tuple(output)


__all__ = [
    "AMBIGUITY_COST_MARGIN",
    "PLAYER_IDENTITY_POLICY_VERSION",
    "PlayerDetector",
    "PlayerIdentityTracker",
    "UnsupportedArchitectureError",
]
