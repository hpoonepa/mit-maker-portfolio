from __future__ import annotations

import math
import heapq
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

import cv2
import numpy as np
import torch
from numpy.typing import NDArray
from torch import Tensor

from squashvision.calibration import CalibrationResult
from squashvision.observations import (
    BALL_MAX_CANDIDATES,
    BallCandidate,
    BallObservation,
    EvidenceKind,
    Frame,
    FrameBatch,
)

NETWORK_WIDTH = 512
NETWORK_HEIGHT = 288
WINDOW_SIZE = 4
MAX_MEDIAN_SAMPLES = 201
MAX_INTERPOLATION_GAP_US = 250_000
MAX_PENDING_GAP = 64
_MAX_NORMALIZED_SPEED = 3.0
_MAX_NORMALIZED_ACCELERATION = 15.0
_COMPARABLE_PEAK_RATIO = 0.95

InferenceRunner = Callable[[object, Tensor, torch.device], Tensor]


def uniform_sample_indices(total: int, maximum: int = MAX_MEDIAN_SAMPLES) -> tuple[int, ...]:
    if total < 0 or maximum <= 0:
        raise ValueError("sample dimensions must be nonnegative with a positive bound")
    if total <= maximum:
        return tuple(range(total))
    return tuple(int(round(value)) for value in np.linspace(0, total - 1, maximum))


def median_background(
    frames: Sequence[NDArray[np.uint8]] | FrameBatch,
    *,
    maximum: int = MAX_MEDIAN_SAMPLES,
) -> NDArray[np.uint8]:
    images = tuple(frame.image for frame in frames) if isinstance(frames, FrameBatch) else frames
    if len(images) == 0:
        raise ValueError("median background requires at least one frame")
    first_shape = images[0].shape
    if any(
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or image.shape != first_shape
        for image in images
    ):
        raise ValueError("median background requires same-size uint8 BGR frames")
    indices = uniform_sample_indices(len(images), maximum)
    sampled = np.stack([images[index] for index in indices], axis=0)
    return np.median(sampled, axis=0).astype(np.uint8)


def preprocess_window(
    frames: Sequence[Frame],
    median: NDArray[np.uint8],
    *,
    width: int = NETWORK_WIDTH,
    height: int = NETWORK_HEIGHT,
) -> NDArray[np.float32]:
    if len(frames) != WINDOW_SIZE:
        raise ValueError("TrackNetV3 preprocessing requires exactly four video frames")
    if width <= 0 or height <= 0:
        raise ValueError("TrackNetV3 target dimensions must be positive")
    source_shape = frames[0].image.shape
    if any(frame.image.shape != source_shape for frame in frames):
        raise ValueError("TrackNetV3 window frames must share one source size")
    if (
        not isinstance(median, np.ndarray)
        or median.dtype != np.uint8
        or median.shape != source_shape
    ):
        raise ValueError("median background must match the uint8 BGR source frames")
    ordered = (median, *(frame.image for frame in frames))
    resized = np.stack([cv2.resize(image, (width, height)) for image in ordered], axis=0)
    chw = np.moveaxis(resized, -1, 1).reshape(-1, height, width)
    return np.ascontiguousarray(chw, dtype=np.float32) / np.float32(255.0)


def _component_circularity(mask: NDArray[np.uint8], area: int) -> float:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    perimeter = float(cv2.arcLength(max(contours, key=cv2.contourArea), True))
    if perimeter <= 0.0:
        return 1.0 if area == 1 else 0.0
    return max(0.0, min(1.0, 4.0 * math.pi * area / (perimeter * perimeter)))


def _decode_heatmap_evidence(
    heatmap: NDArray[np.floating[Any]],
    *,
    source_width: int,
    source_height: int,
    threshold: float,
    top_n: int,
) -> tuple[tuple[BallCandidate, ...], int]:
    values = np.asarray(heatmap, dtype=np.float64)
    if values.shape != (NETWORK_HEIGHT, NETWORK_WIDTH):
        raise ValueError("TrackNetV3 heatmap must be 288x512")
    if not np.isfinite(values).all():
        raise ValueError("TrackNetV3 heatmap must be finite")
    if source_width <= 0 or source_height <= 0:
        raise ValueError("source dimensions must be positive")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("heatmap threshold must be between zero and one")
    if not 1 <= top_n <= BALL_MAX_CANDIDATES:
        raise ValueError("requested candidate bound exceeds the fixed candidate bound")
    binary = (values >= threshold).astype(np.uint8)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    scale_x = source_width / NETWORK_WIDTH
    scale_y = source_height / NETWORK_HEIGHT
    bounded: list[
        tuple[
            tuple[float, float, float, int],
            int,
            BallCandidate,
        ]
    ] = []
    total_count = 0
    for label in range(1, component_count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area <= 0:
            continue
        left = int(stats[label, cv2.CC_STAT_LEFT])
        top = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        local_labels = labels[top : top + height, left : left + width]
        component_mask = (local_labels == label).astype(np.uint8)
        local_ys, local_xs = np.nonzero(component_mask)
        ys = local_ys + top
        xs = local_xs + left
        weights = values[ys, xs]
        weight_sum = float(weights.sum())
        if weight_sum <= 0.0:
            continue
        total_count += 1
        x_mean = float(np.dot(xs, weights) / weight_sum)
        y_mean = float(np.dot(ys, weights) / weight_sum)
        dx = xs - x_mean
        dy = ys - y_mean
        covariance_xx = (
            float(np.dot(weights, dx * dx) / weight_sum) * scale_x**2
        )
        covariance_xy = (
            float(np.dot(weights, dx * dy) / weight_sum) * scale_x * scale_y
        )
        covariance_yy = (
            float(np.dot(weights, dy * dy) / weight_sum) * scale_y**2
        )
        # Shape work stays within this component's stats bounding box.
        candidate = BallCandidate(
            x=x_mean * scale_x,
            y=y_mean * scale_y,
            peak_probability=float(weights.max()),
            integrated_probability=float(weights.mean()),
            area=area,
            circularity=_component_circularity(component_mask, area),
            covariance=(
                (covariance_xx, covariance_xy),
                (covariance_xy, covariance_yy),
            ),
        )
        priority = (
            candidate.peak_probability,
            candidate.integrated_probability,
            candidate.circularity,
            -candidate.area,
        )
        heapq.heappush(bounded, (priority, label, candidate))
        if len(bounded) > top_n:
            heapq.heappop(bounded)
    ordered = tuple(
        item[2] for item in sorted(bounded, key=lambda item: item[:2], reverse=True)
    )
    return ordered, total_count


def decode_heatmap(
    heatmap: NDArray[np.floating[Any]],
    *,
    source_width: int,
    source_height: int,
    threshold: float = 0.5,
    top_n: int = BALL_MAX_CANDIDATES,
) -> tuple[BallCandidate, ...]:
    candidates, _ = _decode_heatmap_evidence(
        heatmap,
        source_width=source_width,
        source_height=source_height,
        threshold=threshold,
        top_n=top_n,
    )
    return candidates


def _default_inference_runner(
    model: object, batch: Tensor, device: torch.device
) -> Tensor:
    values = batch.to(device)
    if hasattr(model, "to"):
        model = model.to(device)  # type: ignore[union-attr]
    output = model(values)  # type: ignore[operator]
    if not isinstance(output, Tensor):
        raise TypeError("TrackNetV3 inference must return a tensor")
    return output

def _preferred_device() -> torch.device:
    try:
        if not torch.backends.mps.is_available():
            return torch.device("cpu")
        torch.empty(1, device="mps")
        torch.mps.synchronize()
        return torch.device("mps")
    except (AttributeError, RuntimeError, NotImplementedError):
        return torch.device("cpu")


class BallTracker:
    def __init__(
        self,
        *,
        model: object,
        source_manifest_id: str,
        model_manifest_id: str,
        device: torch.device | None = None,
        threshold: float = 0.5,
        inference_batch_size: int = 8,
        inference_runner: InferenceRunner = _default_inference_runner,
    ) -> None:
        if not source_manifest_id.strip() or not model_manifest_id.strip():
            raise ValueError("ball tracker requires source and model manifest identifiers")
        if device is None:
            device = _preferred_device()
        if device.type not in {"cpu", "mps"}:
            raise ValueError("ball tracker device must be cpu or mps")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("ball tracker threshold must be between zero and one")
        if inference_batch_size <= 0:
            raise ValueError("ball inference batch size must be positive")
        self._model = model
        self._source_manifest_id = source_manifest_id
        self._model_manifest_id = model_manifest_id
        self._device = device
        self._threshold = threshold
        self._batch_size = inference_batch_size
        self._inference_runner = inference_runner
        self._device_fallback = False

    @property
    def device(self) -> torch.device:
        return self._device

    @property
    def device_fallback(self) -> bool:
        return self._device_fallback

    def _infer(self, batch: Tensor) -> Tensor:
        try:
            with torch.inference_mode():
                output = self._inference_runner(self._model, batch, self._device)
        except (RuntimeError, NotImplementedError) as error:
            if self._device.type != "mps":
                raise
            self._device = torch.device("cpu")
            self._device_fallback = True
            try:
                with torch.inference_mode():
                    output = self._inference_runner(self._model, batch, self._device)
            except Exception:
                raise error
        if output.ndim != 4 or output.shape != (
            batch.shape[0],
            1,
            NETWORK_HEIGHT,
            NETWORK_WIDTH,
        ):
            raise ValueError("TrackNetV3 inference returned an unexpected heatmap shape")
        return output.detach().to("cpu")

    def track(
        self, frames: FrameBatch, median_background: NDArray[np.uint8]
    ) -> tuple[BallObservation, ...]:
        if len(frames) < WINDOW_SIZE:
            return ()
        first_shape = frames.frames[0].image.shape
        if median_background.shape != first_shape or median_background.dtype != np.uint8:
            raise ValueError("median background must match the tracked frame size")
        source_height, source_width = first_shape[:2]
        rows: list[BallObservation] = []
        window_starts = range(0, len(frames) - WINDOW_SIZE + 1)
        for batch_start in range(0, len(window_starts), self._batch_size):
            starts = tuple(window_starts[batch_start : batch_start + self._batch_size])
            arrays = np.stack(
                [
                    preprocess_window(
                        frames.frames[start : start + WINDOW_SIZE], median_background
                    )
                    for start in starts
                ],
                axis=0,
            )
            output = self._infer(torch.from_numpy(arrays)).numpy()
            for offset, heatmap in zip(starts, output[:, 0], strict=True):
                source = frames.frames[offset + WINDOW_SIZE - 1]
                candidates, candidate_count = _decode_heatmap_evidence(
                    heatmap,
                    source_width=source_width,
                    source_height=source_height,
                    threshold=self._threshold,
                    top_n=BALL_MAX_CANDIDATES,
                )
                comparable = (
                    len(candidates) > 1
                    and candidates[1].peak_probability
                    >= candidates[0].peak_probability * _COMPARABLE_PEAK_RATIO
                )
                selected = None if comparable or not candidates else candidates[0]
                rows.append(
                    BallObservation(
                        timestamp_us=source.timestamp_us,
                        source_timestamp_us=source.timestamp_us,
                        source_frame_index=source.source_frame_index,
                        source_width=source_width,
                        source_height=source_height,
                        x=None if selected is None else selected.x,
                        y=None if selected is None else selected.y,
                        probability=0.0 if selected is None else selected.peak_probability,
                        covariance=None if selected is None else selected.covariance,
                        visible=selected is not None,
                        candidate_count=candidate_count,
                        candidates=candidates,
                        evidence=EvidenceKind.OBSERVED,
                        evidence_start_timestamp_us=source.timestamp_us,
                        evidence_end_timestamp_us=source.timestamp_us,
                        evidence_start_frame_index=source.source_frame_index,
                        evidence_end_frame_index=source.source_frame_index,
                        ambiguous=comparable,
                        ambiguity_reason="comparable_peaks" if comparable else None,
                        segment_id=None,
                        source_manifest_id=self._source_manifest_id,
                        model_manifest_id=self._model_manifest_id,
                        device=self._device.type,
                        device_fallback=self._device_fallback,
                    )
                )
        return tuple(rows)


@dataclass(frozen=True, slots=True)
class TrackSegment:
    segment_id: str
    points: tuple[BallObservation, ...]


@dataclass(frozen=True, slots=True)
class TrackSegmentSet:
    segments: tuple[TrackSegment, ...]
    max_pending_gap_count: int


def _court_penalty(candidate: BallCandidate, calibration: CalibrationResult | None) -> float:
    if (
        calibration is None
        or not calibration.calibrated
        or not calibration.capabilities.floor_position
        or calibration.image_to_court is None
    ):
        return 0.0
    matrix = np.asarray(calibration.image_to_court, dtype=np.float64)
    homogeneous = matrix @ np.asarray([candidate.x, candidate.y, 1.0], dtype=np.float64)
    if abs(float(homogeneous[2])) <= 1.0e-12:
        return 3.0
    court_x = float(homogeneous[0] / homogeneous[2])
    court_y = float(homogeneous[1] / homogeneous[2])
    return 0.0 if -2.0 <= court_x <= 8.4 and -2.0 <= court_y <= 11.75 else 3.0


class _ConstantAccelerationKalman:
    def __init__(self, point: BallObservation) -> None:
        if point.x is None or point.y is None or point.covariance is None:
            raise ValueError("Kalman initialization requires a visible ball observation")
        self.timestamp_us = point.timestamp_us
        self.state = np.asarray(
            [point.x, point.y, 0.0, 0.0, 0.0, 0.0], dtype=np.float64
        )
        self.covariance = np.diag(
            [
                max(point.covariance[0][0], 1.0),
                max(point.covariance[1][1], 1.0),
                1.0e5,
                1.0e5,
                1.0e7,
                1.0e7,
            ]
        )

    @staticmethod
    def _measurement_covariance(candidate: BallCandidate) -> NDArray[np.float64]:
        covariance = np.asarray(candidate.covariance, dtype=np.float64)
        return covariance + np.eye(2, dtype=np.float64)

    def predict(
        self, timestamp_us: int
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        elapsed = (timestamp_us - self.timestamp_us) / 1_000_000
        if elapsed < 0.0:
            raise ValueError("Kalman prediction timestamp cannot move backwards")
        transition = np.eye(6, dtype=np.float64)
        transition[0, 2] = elapsed
        transition[1, 3] = elapsed
        transition[0, 4] = 0.5 * elapsed * elapsed
        transition[1, 5] = 0.5 * elapsed * elapsed
        transition[2, 4] = elapsed
        transition[3, 5] = elapsed
        jerk_noise = max(elapsed, 1.0e-3)
        process = np.diag(
            [
                jerk_noise**5 / 20,
                jerk_noise**5 / 20,
                jerk_noise**3 / 3,
                jerk_noise**3 / 3,
                jerk_noise,
                jerk_noise,
            ]
        )
        predicted_state = transition @ self.state
        predicted_covariance = (
            transition @ self.covariance @ transition.T + process
        )
        return predicted_state, predicted_covariance

    def innovation_score(
        self, candidate: BallCandidate, timestamp_us: int
    ) -> float:
        predicted_state, predicted_covariance = self.predict(timestamp_us)
        observation = np.asarray([candidate.x, candidate.y], dtype=np.float64)
        residual = observation - predicted_state[:2]
        innovation = (
            predicted_covariance[:2, :2]
            + self._measurement_covariance(candidate)
        )
        return float(residual @ np.linalg.solve(innovation, residual))

    def update(self, candidate: BallCandidate, timestamp_us: int) -> None:
        predicted_state, predicted_covariance = self.predict(timestamp_us)
        measurement = np.asarray([candidate.x, candidate.y], dtype=np.float64)
        measurement_matrix = np.zeros((2, 6), dtype=np.float64)
        measurement_matrix[0, 0] = 1.0
        measurement_matrix[1, 1] = 1.0
        measurement_covariance = self._measurement_covariance(candidate)
        innovation = (
            measurement_matrix
            @ predicted_covariance
            @ measurement_matrix.T
            + measurement_covariance
        )
        gain = (
            predicted_covariance
            @ measurement_matrix.T
            @ np.linalg.inv(innovation)
        )
        residual = measurement - measurement_matrix @ predicted_state
        self.state = predicted_state + gain @ residual
        identity = np.eye(6, dtype=np.float64)
        correction = identity - gain @ measurement_matrix
        self.covariance = (
            correction @ predicted_covariance @ correction.T
            + gain @ measurement_covariance @ gain.T
        )
        self.timestamp_us = timestamp_us


def _plausible_transition(
    accepted: Sequence[BallObservation], candidate: BallCandidate, timestamp_us: int
) -> bool:
    if not accepted:
        return True
    last = accepted[-1]
    if last.x is None or last.y is None:
        return True
    elapsed = (timestamp_us - last.timestamp_us) / 1_000_000
    if elapsed <= 0.0:
        return False
    velocity_x = (candidate.x - last.x) / elapsed / last.source_width
    velocity_y = (candidate.y - last.y) / elapsed / last.source_height
    if math.hypot(velocity_x, velocity_y) > _MAX_NORMALIZED_SPEED:
        return False
    if len(accepted) < 2:
        return True
    previous = accepted[-2]
    previous_elapsed = (last.timestamp_us - previous.timestamp_us) / 1_000_000
    if previous_elapsed <= 0.0 or previous.x is None or previous.y is None:
        return True
    previous_velocity_x = (
        (last.x - previous.x) / previous_elapsed / last.source_width
    )
    previous_velocity_y = (
        (last.y - previous.y) / previous_elapsed / last.source_height
    )
    acceleration_x = (velocity_x - previous_velocity_x) / max(
        (elapsed + previous_elapsed) / 2, 1.0e-6
    )
    acceleration_y = (velocity_y - previous_velocity_y) / max(
        (elapsed + previous_elapsed) / 2, 1.0e-6
    )
    return math.hypot(acceleration_x, acceleration_y) <= _MAX_NORMALIZED_ACCELERATION


def _select_candidate(
    point: BallObservation,
    accepted: Sequence[BallObservation],
    calibration: CalibrationResult | None,
    kalman: _ConstantAccelerationKalman | None,
) -> BallCandidate | None:
    if point.candidates:
        available = point.candidates
    elif (
        point.visible
        and point.x is not None
        and point.y is not None
        and point.covariance is not None
    ):
        available = (
            BallCandidate(
                x=point.x,
                y=point.y,
                peak_probability=point.probability,
                integrated_probability=point.probability,
                area=1,
                circularity=1.0,
                covariance=point.covariance,
            ),
        )
    else:
        available = ()
    plausible = tuple(
        candidate
        for candidate in available
        if _plausible_transition(accepted, candidate, point.timestamp_us)
    )
    if not plausible:
        return None
    def score(candidate: BallCandidate) -> float:
        uncertainty = math.sqrt(
            max(0.0, candidate.covariance[0][0] + candidate.covariance[1][1])
        ) / math.hypot(point.source_width, point.source_height)
        motion = (
            0.0
            if kalman is None
            else kalman.innovation_score(candidate, point.timestamp_us)
        )
        return (
            motion
            + uncertainty
            + 0.25 * (1.0 - candidate.peak_probability)
            + _court_penalty(candidate, calibration)
        )

    return min(plausible, key=score)


def _selected_observation(point: BallObservation, candidate: BallCandidate) -> BallObservation:
    return replace(
        point,
        x=candidate.x,
        y=candidate.y,
        probability=candidate.peak_probability,
        covariance=candidate.covariance,
        visible=True,
    )


def _interpolated_observation(
    missing: BallObservation,
    start: BallObservation,
    end: BallObservation,
) -> BallObservation:
    assert start.x is not None and start.y is not None and start.covariance is not None
    assert end.x is not None and end.y is not None and end.covariance is not None
    fraction = (missing.timestamp_us - start.timestamp_us) / (
        end.timestamp_us - start.timestamp_us
    )
    x = start.x + fraction * (end.x - start.x)
    y = start.y + fraction * (end.y - start.y)
    process_variance = 4.0 * fraction * (1.0 - fraction)
    covariance = (
        (
            (1.0 - fraction) * start.covariance[0][0]
            + fraction * end.covariance[0][0]
            + process_variance,
            (1.0 - fraction) * start.covariance[0][1]
            + fraction * end.covariance[0][1],
        ),
        (
            (1.0 - fraction) * start.covariance[1][0]
            + fraction * end.covariance[1][0],
            (1.0 - fraction) * start.covariance[1][1]
            + fraction * end.covariance[1][1]
            + process_variance,
        ),
    )
    return replace(
        missing,
        source_timestamp_us=None,
        source_frame_index=None,
        x=x,
        y=y,
        probability=min(start.probability, end.probability),
        covariance=covariance,
        visible=True,
        candidate_count=0,
        candidates=(),
        evidence=EvidenceKind.INTERPOLATED,
        evidence_start_timestamp_us=start.timestamp_us,
        evidence_end_timestamp_us=end.timestamp_us,
        evidence_start_frame_index=int(start.source_frame_index),
        evidence_end_frame_index=int(end.source_frame_index),
        ambiguous=False,
        ambiguity_reason=None,
        segment_id=None,
    )


def repair_track(
    points: Sequence[BallObservation], calibration: CalibrationResult | None
) -> TrackSegmentSet:
    if not points:
        return TrackSegmentSet(segments=(), max_pending_gap_count=0)
    timestamps = tuple(point.timestamp_us for point in points)
    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("ball repair input timestamps must be strictly ordered")
    source_manifests = {point.source_manifest_id for point in points}
    model_manifests = {point.model_manifest_id for point in points}
    if len(source_manifests) != 1 or len(model_manifests) != 1:
        raise ValueError("ball repair input must share source and model manifests")

    completed: list[list[BallObservation]] = []
    current: list[BallObservation] = []
    kalman: _ConstantAccelerationKalman | None = None
    pending: deque[BallObservation] = deque(maxlen=MAX_PENDING_GAP)
    max_pending = 0
    gap_expired = False

    def close_segment() -> None:
        nonlocal current, kalman
        if current:
            completed.append(current)
            current = []
        kalman = None

    for raw in points:
        if (
            current
            and (raw.visible or raw.candidates)
            and raw.timestamp_us - current[-1].timestamp_us
            > MAX_INTERPOLATION_GAP_US
        ):
            close_segment()
            pending.clear()
            gap_expired = False
        selected = _select_candidate(raw, current[-3:], calibration, kalman)
        if selected is None:
            if (
                raw.visible
                and raw.x is not None
                and raw.y is not None
                and raw.covariance is not None
            ):
                selected = BallCandidate(
                    x=raw.x,
                    y=raw.y,
                    peak_probability=raw.probability,
                    integrated_probability=raw.probability,
                    area=1,
                    circularity=1.0,
                    covariance=raw.covariance,
                )
                close_segment()
                pending.clear()
                gap_expired = False
            else:
                if current:
                    if (
                        raw.timestamp_us - current[-1].timestamp_us
                        <= MAX_INTERPOLATION_GAP_US
                    ):
                        pending.append(raw)
                        max_pending = max(max_pending, len(pending))
                    else:
                        pending.clear()
                        gap_expired = True
                continue

        observed = _selected_observation(raw, selected)
        if not current:
            pending.clear()
            gap_expired = False
            current.append(observed)
            kalman = _ConstantAccelerationKalman(observed)
            continue

        start = current[-1]
        elapsed = observed.timestamp_us - start.timestamp_us
        transition_plausible = _plausible_transition(current[-3:], selected, observed.timestamp_us)
        can_interpolate = (
            pending
            and not gap_expired
            and elapsed <= MAX_INTERPOLATION_GAP_US
            and transition_plausible
            and start.source_frame_index is not None
            and observed.source_frame_index is not None
        )
        if can_interpolate:
            current.extend(
                _interpolated_observation(missing, start, observed)
                for missing in pending
                if start.timestamp_us < missing.timestamp_us < observed.timestamp_us
            )
            current.append(observed)
            assert kalman is not None
            kalman.update(selected, observed.timestamp_us)
        elif pending or gap_expired or not transition_plausible:
            close_segment()
            current.append(observed)
            kalman = _ConstantAccelerationKalman(observed)
        else:
            current.append(observed)
            assert kalman is not None
            kalman.update(selected, observed.timestamp_us)
        pending.clear()
        gap_expired = False

    close_segment()
    segments: list[TrackSegment] = []
    for index, segment_points in enumerate(completed, start=1):
        segment_id = f"segment-{index:04d}"
        tagged = tuple(replace(point, segment_id=segment_id) for point in segment_points)
        segments.append(TrackSegment(segment_id=segment_id, points=tagged))
    return TrackSegmentSet(segments=tuple(segments), max_pending_gap_count=max_pending)


__all__ = [
    "BallTracker",
    "MAX_MEDIAN_SAMPLES",
    "TrackSegment",
    "TrackSegmentSet",
    "decode_heatmap",
    "median_background",
    "preprocess_window",
    "repair_track",
    "uniform_sample_indices",
]
