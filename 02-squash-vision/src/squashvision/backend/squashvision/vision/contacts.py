from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import median_filter
from scipy.signal import butter, find_peaks, sosfilt

from squashvision.calibration import COURT_LENGTH_M, COURT_WIDTH_M, CalibrationResult
from squashvision.observations import BallObservation, EvidenceKind, PlayerObservation

MIN_AUDIO_SAMPLE_RATE = 4_000
MAX_AUDIO_SAMPLE_RATE = 384_000
AUDIO_REFRACTORY_US = 40_000
CONTACT_CLUSTER_US = 30_000
CONTACT_TYPE_THRESHOLD = 0.42
MAX_BALL_GAP_US = 250_000


class AudioInputError(ValueError):
    """Base class for typed audio-input failures."""


class AudioSampleRateError(AudioInputError):
    pass


class AudioSamplesError(AudioInputError):
    pass


class ContactType(StrEnum):
    RACKET = "racket"
    FLOOR = "floor"
    FRONT_WALL = "front_wall"
    SIDE_WALL = "side_wall"
    BACK_WALL = "back_wall"
    UNKNOWN = "unknown"


class Hitter(StrEnum):
    A = "A"
    B = "B"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AudioImpact:
    timestamp_us: int
    sample_index: int
    uncertainty_us: int
    strength: float
    confidence: float
    duplicate_count: int = 1

    def __post_init__(self) -> None:
        if self.timestamp_us < 0 or self.sample_index < 0 or self.uncertainty_us < 0:
            raise ValueError("audio impact source values must be nonnegative")
        if self.duplicate_count <= 0:
            raise ValueError("audio impact duplicate count must be positive")
        if not all(math.isfinite(value) for value in (self.strength, self.confidence)):
            raise ValueError("audio impact values must be finite")
        if not 0.0 <= self.strength <= 1.0 or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("audio impact strength and confidence must be probabilities")


@dataclass(frozen=True, slots=True)
class ContactEvidence:
    audio: float
    direction_change: float
    speed_change: float
    ball_uncertainty: float
    ball_gap: float
    wrist_proximity: float
    topology_proximity: float

    def __post_init__(self) -> None:
        values = self.values()
        if not all(math.isfinite(value) for value in values):
            raise ValueError("contact evidence must be finite")
        if not all(0.0 <= value <= 1.0 for value in values):
            raise ValueError("contact evidence must be between zero and one")

    def values(self) -> tuple[float, ...]:
        return (
            self.audio,
            self.direction_change,
            self.speed_change,
            self.ball_uncertainty,
            self.ball_gap,
            self.wrist_proximity,
            self.topology_proximity,
        )


def _normalised_mapping(
    values: Mapping[ContactType | Hitter | str, float], keys: type[ContactType] | type[Hitter]
) -> Mapping[ContactType, float] | Mapping[Hitter, float]:
    converted: dict[ContactType | Hitter, float] = {key: 0.0 for key in keys}
    for raw_key, raw_value in values.items():
        key = keys(raw_key)
        value = float(raw_value)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("probabilities must be finite and nonnegative")
        converted[key] = value
    total = sum(converted.values())
    if total <= 0.0:
        raise ValueError("probabilities must have positive mass")
    return MappingProxyType({key: value / total for key, value in converted.items()})


@dataclass(frozen=True, slots=True)
class ContactEvent:
    segment_id: str
    contact_id: str
    timestamp_us: int
    uncertainty_us: int
    type_probabilities: Mapping[ContactType, float]
    selected_type: ContactType
    hitter_probabilities: Mapping[Hitter, float]
    selected_hitter: Hitter
    confidence: float
    review_required: bool
    review_reasons: tuple[str, ...]
    evidence: ContactEvidence
    supporting_ball_timestamps_us: tuple[int, ...]
    supporting_player_timestamps_us: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_type", ContactType(self.selected_type))
        object.__setattr__(self, "selected_hitter", Hitter(self.selected_hitter))
        object.__setattr__(
            self, "type_probabilities", _normalised_mapping(self.type_probabilities, ContactType)
        )
        object.__setattr__(
            self,
            "hitter_probabilities",
            _normalised_mapping(self.hitter_probabilities, Hitter),
        )
        object.__setattr__(self, "review_reasons", tuple(dict.fromkeys(self.review_reasons)))
        object.__setattr__(
            self,
            "supporting_ball_timestamps_us",
            tuple(sorted(set(self.supporting_ball_timestamps_us))),
        )
        object.__setattr__(
            self,
            "supporting_player_timestamps_us",
            tuple(sorted(set(self.supporting_player_timestamps_us))),
        )
        if not self.segment_id.strip():
            raise ValueError("contact segment identifier cannot be blank")
        if not self.contact_id.strip():
            raise ValueError("contact identifier cannot be blank")
        if self.timestamp_us < 0 or self.uncertainty_us < 0:
            raise ValueError("contact timestamp values must be nonnegative")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("contact confidence must be finite and between zero and one")
        if self.review_required != bool(self.review_reasons):
            raise ValueError("contact review flag and reasons must agree")
        if not self.supporting_ball_timestamps_us:
            raise ValueError("contact requires supporting ball evidence")
        if any(value < 0 for value in self.supporting_ball_timestamps_us):
            raise ValueError("supporting ball timestamps must be nonnegative")
        if any(value < 0 for value in self.supporting_player_timestamps_us):
            raise ValueError("supporting player timestamps must be nonnegative")


def _mono_audio(samples: NDArray[np.generic]) -> NDArray[np.float64]:
    if not isinstance(samples, np.ndarray):
        raise AudioSamplesError("audio samples must be a NumPy array")
    if samples.ndim not in (1, 2):
        raise AudioSamplesError("audio samples must be mono or multichannel")
    if samples.ndim == 2 and samples.shape[1] == 0:
        raise AudioSamplesError("multichannel audio must contain at least one channel")
    if samples.dtype.kind not in "iuf":
        raise AudioSamplesError("audio samples must have a real numeric dtype")
    if not np.isfinite(samples).all():
        raise AudioSamplesError("audio samples must be finite")
    if samples.shape[0] == 0:
        return np.empty(0, dtype=np.float64)

    if samples.dtype.kind in "iu":
        info = np.iinfo(samples.dtype)
        converted = samples.astype(np.float64)
        if samples.dtype.kind == "u":
            midpoint = (float(info.max) + 1.0) / 2.0
            converted = (converted - midpoint) / midpoint
        else:
            converted /= max(abs(float(info.min)), abs(float(info.max)))
    else:
        converted = samples.astype(np.float64, copy=False)
    mono = converted if converted.ndim == 1 else converted.mean(axis=1, dtype=np.float64)
    mono = mono - float(np.median(mono))
    peak = float(np.max(np.abs(mono), initial=0.0))
    if peak == 0.0:
        return np.zeros_like(mono)
    return mono / peak


def _rolling_robust_z(values: NDArray[np.float64], width: int) -> NDArray[np.float64]:
    width = max(3, min(width | 1, 401))
    baseline = median_filter(values, size=width, mode="reflect")
    deviation = median_filter(np.abs(values - baseline), size=width, mode="reflect")
    global_deviation = float(np.median(np.abs(values - np.median(values))))
    scale = 1.4826 * np.maximum(deviation, max(global_deviation * 0.25, 1.0e-9))
    return np.maximum(0.0, (values - baseline) / scale)


def detect_audio_impacts(
    samples: NDArray[np.generic], sample_rate: int
) -> tuple[AudioImpact, ...]:
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, (int, np.integer))
        or not MIN_AUDIO_SAMPLE_RATE <= int(sample_rate) <= MAX_AUDIO_SAMPLE_RATE
    ):
        raise AudioSampleRateError(
            f"audio sample rate must be between {MIN_AUDIO_SAMPLE_RATE} and {MAX_AUDIO_SAMPLE_RATE} Hz"
        )
    rate = int(sample_rate)
    mono = _mono_audio(samples)
    if mono.size == 0 or not np.any(mono):
        return ()

    window = max(32, int(round(rate * 0.006)))
    hop = max(8, int(round(rate * 0.0025)))
    padded = np.pad(mono, (window, window))
    upper_hz = min(6_000.0, rate * 0.45)
    sos = butter(3, (600.0, upper_hz), btype="bandpass", fs=rate, output="sos")
    filtered = sosfilt(sos, padded)
    filtered_peak = float(np.max(np.abs(filtered), initial=0.0))
    starts = np.arange(0, filtered.size - window + 1, hop, dtype=np.int64)
    energy = np.empty(starts.size, dtype=np.float64)
    flux = np.empty(starts.size, dtype=np.float64)
    previous_spectrum: NDArray[np.float64] | None = None
    taper = np.hanning(window)
    for index, start in enumerate(starts):
        frame = filtered[int(start) : int(start) + window]
        energy[index] = math.sqrt(float(np.mean(frame * frame)))
        spectrum = np.abs(np.fft.rfft(frame * taper))
        flux[index] = (
            0.0
            if previous_spectrum is None
            else float(np.mean(np.maximum(spectrum - previous_spectrum, 0.0)))
        )
        previous_spectrum = spectrum

    floor_width = max(5, int(round(rate / hop)))
    energy_z = _rolling_robust_z(np.log1p(40.0 * energy), floor_width)
    flux_z = _rolling_robust_z(np.log1p(10.0 * flux), floor_width)
    score = 0.62 * energy_z + 0.38 * flux_z
    padded_score = np.pad(score, (1, 1), constant_values=-np.inf)
    padded_peaks, properties = find_peaks(padded_score, height=6.0)
    peak_frames = padded_peaks - 1
    raw: list[AudioImpact] = []
    for frame_index, peak_score in zip(peak_frames, properties["peak_heights"], strict=True):
        start = int(starts[int(frame_index)])
        local = np.abs(filtered[start : start + window])
        padded_sample_index = start + int(np.argmax(local))
        sample_index = padded_sample_index - window
        if not 0 <= sample_index < mono.size:
            continue
        strength = float(np.max(local, initial=0.0)) / max(filtered_peak, 1.0e-12)
        confidence = 1.0 - math.exp(-max(0.0, float(peak_score) - 4.0) / 5.0)
        raw.append(
            AudioImpact(
                timestamp_us=round(sample_index * 1_000_000 / rate),
                sample_index=sample_index,
                uncertainty_us=max(1, math.ceil(hop * 1_000_000 / rate)),
                strength=min(1.0, strength),
                confidence=min(1.0, confidence),
            )
        )
    raw.sort(key=lambda item: (item.sample_index, -item.confidence, -item.strength))

    collapsed: list[AudioImpact] = []
    group: list[AudioImpact] = []
    for item in raw:
        if group and item.timestamp_us - group[0].timestamp_us >= AUDIO_REFRACTORY_US:
            strongest = max(
                group,
                key=lambda value: (value.strength, value.confidence, -value.sample_index),
            )
            collapsed.append(replace_audio_duplicate_count(strongest, len(group)))
            group = []
        group.append(item)
    if group:
        strongest = max(
            group,
            key=lambda value: (value.strength, value.confidence, -value.sample_index),
        )
        collapsed.append(replace_audio_duplicate_count(strongest, len(group)))
    return tuple(collapsed)


def replace_audio_duplicate_count(impact: AudioImpact, count: int) -> AudioImpact:
    return AudioImpact(
        timestamp_us=impact.timestamp_us,
        sample_index=impact.sample_index,
        uncertainty_us=impact.uncertainty_us,
        strength=impact.strength,
        confidence=impact.confidence,
        duplicate_count=count,
    )


@dataclass(frozen=True, slots=True)
class _DirectionCandidate:
    timestamp_us: int
    segment_id: str
    source_manifest_id: str
    point: BallObservation
    direction: float
    speed: float
    uncertainty: float
    gap: float
    incoming_velocity: tuple[float, float]
    outgoing_velocity: tuple[float, float]
    support: tuple[int, ...]


def _segment_safe(a: BallObservation, b: BallObservation, c: BallObservation) -> bool:
    first_delta = b.timestamp_us - a.timestamp_us
    second_delta = c.timestamp_us - b.timestamp_us
    return (
        a.segment_id is not None
        and a.segment_id == b.segment_id == c.segment_id
        and 0 < first_delta <= MAX_BALL_GAP_US
        and 0 < second_delta <= MAX_BALL_GAP_US
    )


def _velocity(a: BallObservation, b: BallObservation) -> tuple[float, float]:
    elapsed = (b.timestamp_us - a.timestamp_us) / 1_000_000.0
    return (
        (float(b.x) - float(a.x)) / b.source_width / elapsed,
        (float(b.y) - float(a.y)) / b.source_height / elapsed,
    )


def _direction_candidates(ball: Sequence[BallObservation]) -> list[_DirectionCandidate]:
    segments: dict[str, list[BallObservation]] = {}
    for point in ball:
        if point.segment_id is not None:
            segments.setdefault(point.segment_id, []).append(point)
    result: list[_DirectionCandidate] = []
    for segment_id, points in segments.items():
        ordered = sorted(points, key=lambda item: item.timestamp_us)
        for first, center, last in zip(ordered, ordered[1:], ordered[2:]):
            if not _segment_safe(first, center, last):
                continue
            if not all(
                item.visible and item.x is not None and item.y is not None
                for item in (first, center, last)
            ):
                continue
            if any(
                item.evidence not in (EvidenceKind.OBSERVED, EvidenceKind.INTERPOLATED)
                for item in (first, center, last)
            ):
                continue
            incoming = _velocity(first, center)
            outgoing = _velocity(center, last)
            incoming_speed = math.hypot(*incoming)
            outgoing_speed = math.hypot(*outgoing)
            if min(incoming_speed, outgoing_speed) <= 1.0e-9:
                direction = 0.0
            else:
                cosine = np.clip(
                    (incoming[0] * outgoing[0] + incoming[1] * outgoing[1])
                    / (incoming_speed * outgoing_speed),
                    -1.0,
                    1.0,
                )
                direction = float(math.acos(float(cosine)) / math.pi)
            speed = min(
                1.0,
                abs(outgoing_speed - incoming_speed)
                / max(incoming_speed, outgoing_speed, 0.01),
            )
            if direction < 0.16 and speed < 0.55:
                continue
            covariance_values = [
                max(item.covariance[0][0], item.covariance[1][1])
                for item in (first, center, last)
                if item.covariance is not None
            ]
            diagonal = math.hypot(center.source_width, center.source_height)
            covariance_uncertainty = min(
                1.0,
                math.sqrt(max(covariance_values, default=0.0))
                / max(diagonal * 0.04, 1.0),
            )
            provenance_uncertainty = max(
                0.0 if item.evidence is EvidenceKind.OBSERVED else 0.35
                for item in (first, center, last)
            )
            ambiguity = max(
                0.35 if item.ambiguous else 0.0 for item in (first, center, last)
            )
            uncertainty = min(
                1.0, covariance_uncertainty + provenance_uncertainty + ambiguity
            )
            gap = min(
                1.0,
                max(
                    center.timestamp_us - first.timestamp_us,
                    last.timestamp_us - center.timestamp_us,
                )
                / MAX_BALL_GAP_US,
            )
            result.append(
                _DirectionCandidate(
                    timestamp_us=center.timestamp_us,
                    segment_id=segment_id,
                    source_manifest_id=center.source_manifest_id,
                    point=center,
                    direction=direction,
                    speed=speed,
                    uncertainty=uncertainty,
                    gap=gap,
                    incoming_velocity=incoming,
                    outgoing_velocity=outgoing,
                    support=(first.timestamp_us, center.timestamp_us, last.timestamp_us),
                )
            )
    return sorted(result, key=lambda item: (item.timestamp_us, item.segment_id))


def _cluster_candidates(
    candidates: Sequence[_DirectionCandidate],
) -> list[tuple[_DirectionCandidate, ...]]:
    by_segment: dict[str, list[_DirectionCandidate]] = {}
    for candidate in candidates:
        by_segment.setdefault(candidate.segment_id, []).append(candidate)
    completed: list[tuple[_DirectionCandidate, ...]] = []
    for segment_id in sorted(by_segment):
        current: list[_DirectionCandidate] = []
        for candidate in sorted(
            by_segment[segment_id], key=lambda item: item.timestamp_us
        ):
            if (
                current
                and candidate.timestamp_us - current[0].timestamp_us
                > CONTACT_CLUSTER_US
            ):
                completed.append(tuple(current))
                current = []
            current.append(candidate)
        if current:
            completed.append(tuple(current))
    return sorted(
        completed,
        key=lambda cluster: (cluster[0].timestamp_us, cluster[0].segment_id),
    )


def _range_indices(
    timestamps: Sequence[int], earliest: int, latest: int, tolerance: int
) -> tuple[int, ...]:
    if not timestamps:
        return ()
    start = bisect_left(timestamps, earliest - tolerance)
    end = bisect_right(timestamps, latest + tolerance)
    return tuple(range(start, end))


def _median_resolution_us(timestamps: Sequence[int], default: int) -> int:
    gaps = [current - previous for previous, current in zip(timestamps, timestamps[1:]) if current > previous]
    return int(np.median(gaps)) if gaps else default


def _wrist_scores(
    candidate: _DirectionCandidate,
    observations: Sequence[PlayerObservation],
) -> tuple[dict[Hitter, float], tuple[int, ...], bool]:
    scores = {Hitter.A: 0.0, Hitter.B: 0.0}
    timestamps: list[int] = []
    ambiguous = False
    diagonal = math.hypot(candidate.point.source_width, candidate.point.source_height)
    for observation in observations:
        timestamps.append(observation.timestamp_us)
        for wrist in (observation.keypoints[9], observation.keypoints[10]):
            if wrist.confidence < 0.2:
                continue
            distance = math.hypot(float(candidate.point.x) - wrist.x, float(candidate.point.y) - wrist.y)
            proximity = math.exp(-distance / max(diagonal * 0.08, 1.0))
            score = (
                proximity
                * wrist.confidence
                * observation.detection_confidence
                * observation.association_confidence
            )
            hitter = Hitter(observation.player_id)
            scores[hitter] = max(scores[hitter], min(1.0, score))
        if observation.ambiguous:
            ambiguous = True
    return scores, tuple(sorted(set(timestamps))), ambiguous


def _hitter_distribution(
    wrist_scores: Mapping[Hitter, float], ambiguous: bool
) -> tuple[Mapping[Hitter, float], Hitter, bool]:
    a_score = wrist_scores[Hitter.A]
    b_score = wrist_scores[Hitter.B]
    strongest = max(a_score, b_score)
    comparable = strongest > 0.15 and abs(a_score - b_score) <= 0.18
    if ambiguous or comparable:
        unknown = max(0.55, strongest + 0.15)
    else:
        unknown = max(0.08, 0.35 * (1.0 - strongest))
    probabilities = _normalised_mapping(
        {Hitter.A: max(0.01, a_score), Hitter.B: max(0.01, b_score), Hitter.UNKNOWN: unknown},
        Hitter,
    )
    ranked = sorted((probability, hitter) for hitter, probability in probabilities.items())
    top_probability, top_hitter = ranked[-1]
    next_probability = ranked[-2][0]
    if (
        top_hitter is Hitter.UNKNOWN
        or top_probability < 0.6
        or top_probability - next_probability <= 0.18
        or ambiguous
        or comparable
    ):
        return probabilities, Hitter.UNKNOWN, ambiguous or comparable or strongest > 0.0
    return probabilities, top_hitter, False


def _projected_floor_polygon(
    calibration: CalibrationResult | None,
) -> NDArray[np.float64] | None:
    if (
        calibration is None
        or not calibration.capabilities.image_space
        or not calibration.capabilities.floor_position
        or calibration.court_to_image is None
    ):
        return None
    matrix = np.asarray(calibration.court_to_image, dtype=np.float64)
    corners = np.asarray(
        [
            [0.0, 0.0, 1.0],
            [COURT_WIDTH_M, 0.0, 1.0],
            [COURT_WIDTH_M, COURT_LENGTH_M, 1.0],
            [0.0, COURT_LENGTH_M, 1.0],
        ],
        dtype=np.float64,
    )
    projected = (matrix @ corners.T).T
    if (
        not np.isfinite(projected).all()
        or np.any(np.abs(projected[:, 2]) <= 1.0e-12)
    ):
        return None
    polygon = projected[:, :2] / projected[:, 2, None]
    return polygon if np.isfinite(polygon).all() else None


def _point_segment_distance(
    point: NDArray[np.float64],
    start: NDArray[np.float64],
    end: NDArray[np.float64],
) -> float:
    delta = end - start
    denominator = float(delta @ delta)
    if denominator <= 1.0e-12:
        return float(np.linalg.norm(point - start))
    fraction = float(np.clip(((point - start) @ delta) / denominator, 0.0, 1.0))
    return float(np.linalg.norm(point - (start + fraction * delta)))


def _inside_convex_polygon(
    point: NDArray[np.float64], polygon: NDArray[np.float64]
) -> bool:
    crosses = []
    for start, end in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
        edge = end - start
        offset = point - start
        crosses.append(float(edge[0] * offset[1] - edge[1] * offset[0]))
    return all(value >= -1.0e-6 for value in crosses) or all(
        value <= 1.0e-6 for value in crosses
    )


def _topology_scores(
    candidate: _DirectionCandidate, calibration: CalibrationResult | None
) -> tuple[dict[ContactType, float], float]:
    polygon = _projected_floor_polygon(calibration)
    if polygon is None:
        return {
            ContactType.FLOOR: 0.0,
            ContactType.FRONT_WALL: 0.0,
            ContactType.SIDE_WALL: 0.0,
            ContactType.BACK_WALL: 0.0,
        }, 0.0
    assert calibration is not None
    factor = (
        min(1.0, calibration.confidence)
        if calibration.calibrated
        else min(0.15, calibration.confidence * 0.4)
    )
    point = np.asarray(
        [float(candidate.point.x), float(candidate.point.y)], dtype=np.float64
    )
    edges = tuple(zip(polygon, np.roll(polygon, -1, axis=0), strict=True))
    distances = tuple(
        _point_segment_distance(point, start, end) for start, end in edges
    )
    diagonal = max(
        float(np.linalg.norm(first - second))
        for first in polygon
        for second in polygon
    )
    radius = max(2.0, 0.12 * diagonal)
    proximities = tuple(max(0.0, 1.0 - distance / radius) for distance in distances)
    incoming_y = candidate.incoming_velocity[1]
    outgoing_y = candidate.outgoing_velocity[1]
    floor_orientation = 1.0 if incoming_y > 0.0 and outgoing_y < 0.0 else 0.0
    near_floor = max(proximities)
    floor_score = (
        factor
        * near_floor
        * floor_orientation
        * (1.0 if _inside_convex_polygon(point, polygon) else 0.35)
    )
    scores = {
        ContactType.FLOOR: floor_score,
        ContactType.FRONT_WALL: 0.0,
        ContactType.SIDE_WALL: 0.0,
        ContactType.BACK_WALL: 0.0,
    }
    return scores, max(scores.values())


def _contact_id(
    segment_id: str, source_manifest_id: str, timestamp_us: int, support: tuple[int, ...]
) -> str:
    payload = (
        f"{source_manifest_id}|{segment_id}|{timestamp_us}|"
        f"{','.join(str(value) for value in support)}"
    ).encode()
    return f"contact-{hashlib.sha256(payload).hexdigest()[:20]}"


def fuse_contacts(
    ball: Sequence[BallObservation],
    players: Sequence[PlayerObservation],
    audio: Sequence[AudioImpact],
    calibration: CalibrationResult | None,
) -> tuple[ContactEvent, ...]:
    candidates = _direction_candidates(ball)
    if not candidates:
        return ()
    clusters = _cluster_candidates(candidates)
    ordered_players = sorted(players, key=lambda item: item.timestamp_us)
    player_times = [item.timestamp_us for item in ordered_players]
    ordered_audio = sorted(audio, key=lambda item: item.timestamp_us)
    audio_times = [item.timestamp_us for item in ordered_audio]
    ball_resolution = _median_resolution_us(
        sorted(item.timestamp_us for item in ball), 40_000
    )
    player_tolerance = min(120_000, max(35_000, 2 * ball_resolution))
    audio_tolerance = min(60_000, max(15_000, ball_resolution))

    events: list[ContactEvent] = []
    for cluster in clusters:
        representative = max(
            cluster,
            key=lambda item: (
                item.direction + 0.5 * item.speed,
                -item.timestamp_us,
            ),
        )
        timestamp_us = representative.timestamp_us
        cluster_start_us = min(item.timestamp_us for item in cluster)
        cluster_end_us = max(item.timestamp_us for item in cluster)
        direction = max(item.direction for item in cluster)
        speed = max(item.speed for item in cluster)
        uncertainty = max(item.uncertainty for item in cluster)
        gap = max(item.gap for item in cluster)
        support = tuple(sorted({value for item in cluster for value in item.support}))

        audio_indices = _range_indices(
            audio_times, cluster_start_us, cluster_end_us, audio_tolerance
        )
        associated_audio = [ordered_audio[index] for index in audio_indices]
        audio_score = max(
            (item.strength * item.confidence for item in associated_audio), default=0.0
        )
        player_indices = _range_indices(
            player_times, cluster_start_us, cluster_end_us, player_tolerance
        )
        associated_players = [ordered_players[index] for index in player_indices]
        wrist_scores, player_support, player_ambiguous = _wrist_scores(
            representative, associated_players
        )
        wrist_score = max(wrist_scores.values())
        hitter_probabilities, selected_hitter, hitter_ambiguous = _hitter_distribution(
            wrist_scores, player_ambiguous
        )
        topology_scores, topology_score = _topology_scores(
            representative, calibration
        )

        raw_type_scores: dict[ContactType, float] = {
            ContactType.RACKET: 0.35 * direction
            + 0.15 * speed
            + 0.9 * wrist_score,
            ContactType.FLOOR: 0.01
            + 1.2 * topology_scores[ContactType.FLOOR]
            + 0.18 * direction,
            ContactType.FRONT_WALL: 0.01
            + topology_scores[ContactType.FRONT_WALL],
            ContactType.SIDE_WALL: 0.01
            + topology_scores[ContactType.SIDE_WALL],
            ContactType.BACK_WALL: 0.01
            + topology_scores[ContactType.BACK_WALL],
            ContactType.UNKNOWN: 0.2 + 0.25 * uncertainty + 0.2 * gap,
        }
        if wrist_score < 0.15 and topology_score < 0.2:
            raw_type_scores[ContactType.UNKNOWN] += 0.35
        type_probabilities = _normalised_mapping(raw_type_scores, ContactType)
        ranked_types = sorted(
            (probability, contact_type)
            for contact_type, probability in type_probabilities.items()
            if contact_type is not ContactType.UNKNOWN
        )
        top_probability, selected_type = ranked_types[-1]
        second_probability = ranked_types[-2][0]
        if (
            top_probability < CONTACT_TYPE_THRESHOLD
            or top_probability - second_probability < 0.08
        ):
            selected_type = ContactType.UNKNOWN
        if selected_type is not ContactType.RACKET:
            selected_hitter = Hitter.UNKNOWN

        reasons: list[str] = []
        if selected_type is ContactType.UNKNOWN:
            reasons.append("low_or_ambiguous_contact_type")
        if selected_type is ContactType.RACKET and hitter_ambiguous:
            reasons.append("ambiguous_hitter")
        if selected_type is ContactType.RACKET and selected_hitter is Hitter.UNKNOWN:
            reasons.append("unknown_hitter")
        geometry_available = _projected_floor_polygon(calibration) is not None
        if (
            selected_type is ContactType.UNKNOWN
            and geometry_available
            and wrist_score < 0.15
        ):
            reasons.append("unsupported_wall_surface")
        elif topology_score < 0.2 and wrist_score < 0.15:
            reasons.append("weak_or_missing_calibration")
        if uncertainty >= 0.5:
            reasons.append("uncertain_ball_evidence")
        reliability = max(wrist_score, topology_score, 0.35 * direction)
        confidence = min(
            1.0,
            max(type_probabilities.values())
            * (0.72 + 0.18 * audio_score + 0.1 * reliability)
            * (1.0 - 0.25 * uncertainty),
        )
        evidence = ContactEvidence(
            audio=min(1.0, audio_score),
            direction_change=direction,
            speed_change=speed,
            ball_uncertainty=uncertainty,
            ball_gap=gap,
            wrist_proximity=wrist_score,
            topology_proximity=topology_score,
        )
        extent_uncertainty_us = (
            cluster_end_us - cluster_start_us + math.ceil(ball_resolution / 2)
        )
        events.append(
            ContactEvent(
                segment_id=representative.segment_id,
                contact_id=_contact_id(
                    representative.segment_id,
                    representative.source_manifest_id,
                    timestamp_us,
                    support,
                ),
                timestamp_us=timestamp_us,
                uncertainty_us=max(
                    [extent_uncertainty_us]
                    + [item.uncertainty_us for item in associated_audio]
                ),
                type_probabilities=type_probabilities,
                selected_type=selected_type,
                hitter_probabilities=hitter_probabilities,
                selected_hitter=selected_hitter,
                confidence=confidence,
                review_required=bool(reasons),
                review_reasons=tuple(reasons),
                evidence=evidence,
                supporting_ball_timestamps_us=support,
                supporting_player_timestamps_us=player_support,
            )
        )
    return tuple(sorted(events, key=lambda item: (item.timestamp_us, item.contact_id)))


__all__ = [
    "AUDIO_REFRACTORY_US",
    "CONTACT_CLUSTER_US",
    "CONTACT_TYPE_THRESHOLD",
    "AudioImpact",
    "AudioInputError",
    "AudioSampleRateError",
    "AudioSamplesError",
    "ContactEvent",
    "ContactEvidence",
    "ContactType",
    "Hitter",
    "detect_audio_impacts",
    "fuse_contacts",
]
