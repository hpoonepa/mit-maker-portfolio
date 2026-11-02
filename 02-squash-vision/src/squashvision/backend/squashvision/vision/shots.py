from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from scipy.interpolate import UnivariateSpline

from squashvision.calibration import CalibrationResult, ImagePoint, project_floor
from squashvision.observations import BallObservation, PlayerObservation
from squashvision.vision.ball.tracker import TrackSegment
from squashvision.vision.contacts import ContactEvent, ContactType, Hitter

SHOT_PROBABILITY_THRESHOLD = 0.55
SHOT_MARGIN_THRESHOLD = 0.20
TERMINAL_PROBABILITY_THRESHOLD = 0.55
TERMINAL_MARGIN_THRESHOLD = 0.20
MAX_SHOT_WINDOW_US = 3_000_000
MAX_SHOT_SAMPLES = 128
MAX_TRAJECTORY_SAMPLES = 128
MAX_RAW_EVIDENCE_SAMPLES = 4_096
_MIN_CALIBRATION_CONFIDENCE = 0.65
_MIN_CONTACT_CONFIDENCE = 0.65
_MAX_SPLINE_JACOBIAN_CONDITION = 1.0e8
_MIN_SPLINE_DURATION_S = 1.0e-4


class ShotType(StrEnum):
    SERVE = "serve"
    STRAIGHT_DRIVE = "straight_drive"
    CROSSCOURT_DRIVE = "crosscourt_drive"
    BOAST = "boast"
    DROP = "drop"
    LOB = "lob"
    KILL = "kill"
    UNKNOWN = "unknown"


class StrokeSide(StrEnum):
    FOREHAND = "forehand"
    BACKHAND = "backhand"
    UNKNOWN = "unknown"


class Handedness(StrEnum):
    RIGHT = "right"
    LEFT = "left"
    UNKNOWN = "unknown"


class CourtSide(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"


class CourtDepth(StrEnum):
    FRONT = "front"
    MID = "mid"
    BACK = "back"
    UNKNOWN = "unknown"


class ShotWindowBoundary(StrEnum):
    NEXT_RACKET = "next_racket"
    TERMINAL = "terminal"


class ShotOutcome(StrEnum):
    CONTINUES = "continues"
    TERMINAL = "terminal"
    UNKNOWN = "unknown"


class ErrorOutcome(StrEnum):
    WINNER = "winner"
    TIN = "tin"
    OUT = "out"
    NOT_UP = "not_up"
    LET_CANDIDATE = "let_candidate"
    STROKE_CANDIDATE = "stroke_candidate"
    FORCED_ERROR_CANDIDATE = "forced_error_candidate"
    UNFORCED_ERROR_CANDIDATE = "unforced_error_candidate"
    UNKNOWN = "unknown"


class InterferenceKind(StrEnum):
    LET = "let"
    STROKE = "stroke"


@dataclass(frozen=True, slots=True)
class ScalarRange:
    minimum: float
    median: float
    maximum: float
    uncertainty: float

    def __post_init__(self) -> None:
        values = (self.minimum, self.median, self.maximum, self.uncertainty)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("range values must be finite")
        if not self.minimum <= self.median <= self.maximum:
            raise ValueError("range values must be ordered")
        if self.uncertainty < 0.0:
            raise ValueError("range uncertainty must be nonnegative")


@dataclass(frozen=True, slots=True)
class CredibleValue:
    lower: float
    estimate: float
    upper: float

    def __post_init__(self) -> None:
        values = (self.lower, self.estimate, self.upper)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("credible values must be finite")
        if not 0.0 <= self.lower <= self.estimate <= self.upper:
            raise ValueError("credible values must be nonnegative and ordered")



@dataclass(frozen=True, slots=True)
class TrajectoryContactConstraint:
    segment_id: str
    contact_id: str
    timestamp_us: int
    confidence: float

    def __post_init__(self) -> None:
        if not self.segment_id.strip() or not self.contact_id.strip():
            raise ValueError("trajectory contact constraint identifiers cannot be blank")
        if self.timestamp_us < 0:
            raise ValueError("trajectory contact timestamp must be nonnegative")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("trajectory contact confidence must be a probability")

@dataclass(frozen=True, slots=True)
class ShotContext:
    hitter_contact: ContactEvent
    post_hit_contacts: tuple[ContactEvent, ...]
    ball_segment: TrackSegment
    hitter_observations: tuple[PlayerObservation, ...]
    opponent_observations: tuple[PlayerObservation, ...]
    calibration: CalibrationResult | None
    rally_position: int
    serve_context: bool | None
    window_start_us: int
    hit_timestamp_us: int
    window_end_us: int
    max_hit_tolerance_us: int
    max_player_tolerance_us: int
    prior_contacts: tuple[ContactEvent, ...] = ()
    wall_geometry_supported: bool = False
    hitter_handedness: Handedness = Handedness.UNKNOWN
    calibration_revision: str | None = None
    window_boundary: ShotWindowBoundary = ShotWindowBoundary.TERMINAL
    boundary_contact: ContactEvent | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "post_hit_contacts", tuple(self.post_hit_contacts))
        object.__setattr__(self, "hitter_observations", tuple(self.hitter_observations))
        object.__setattr__(self, "opponent_observations", tuple(self.opponent_observations))
        object.__setattr__(self, "prior_contacts", tuple(self.prior_contacts))
        object.__setattr__(self, "hitter_handedness", Handedness(self.hitter_handedness))
        object.__setattr__(
            self, "window_boundary", ShotWindowBoundary(self.window_boundary)
        )
        if self.rally_position < 0:
            raise ValueError("rally position must be nonnegative")
        if not (
            0 <= self.window_start_us
            <= self.hit_timestamp_us
            <= self.window_end_us
        ):
            raise ValueError("shot evidence window must contain the hit timestamp")
        if self.window_end_us - self.window_start_us > MAX_SHOT_WINDOW_US:
            raise ValueError("shot evidence window exceeds the bounded duration")
        if self.hit_timestamp_us != self.hitter_contact.timestamp_us:
            raise ValueError("shot hit timestamp must match the hitter contact")
        if self.max_hit_tolerance_us < 0 or self.max_player_tolerance_us < 0:
            raise ValueError("shot evidence tolerances must be nonnegative")
        if len(self.ball_segment.points) > MAX_RAW_EVIDENCE_SAMPLES:
            raise ValueError("shot ball evidence exceeds the raw sample bound")
        if self.window_boundary is ShotWindowBoundary.NEXT_RACKET:
            if (
                self.boundary_contact is None
                or self.boundary_contact.selected_type is not ContactType.RACKET
                or self.boundary_contact.segment_id != self.ball_segment.segment_id
                or self.boundary_contact.timestamp_us != self.window_end_us
            ):
                raise ValueError(
                    "next-racket window requires a same-segment racket boundary"
                )
        elif self.boundary_contact is not None:
            raise ValueError("terminal shot window cannot claim a racket boundary")
        if (
            len(self.hitter_observations) > MAX_RAW_EVIDENCE_SAMPLES
            or len(self.opponent_observations) > MAX_RAW_EVIDENCE_SAMPLES
            or len(self.post_hit_contacts) > MAX_SHOT_SAMPLES - 2
            or len(self.prior_contacts) > MAX_RAW_EVIDENCE_SAMPLES
        ):
            raise ValueError("shot evidence exceeds the raw sample bound")
        if self.hitter_contact.selected_type is not ContactType.RACKET:
            raise ValueError("shot context requires one racket contact")
        if self.hitter_contact.segment_id != self.ball_segment.segment_id:
            raise ValueError("hitter contact and ball evidence must share one segment")
        if any(
            point.segment_id != self.ball_segment.segment_id
            for point in self.ball_segment.points
        ):
            raise ValueError("ball evidence must belong to one segment")
        if any(
            item.segment_id != self.ball_segment.segment_id
            for item in self.post_hit_contacts
        ):
            raise ValueError("post-hit contacts and ball evidence must share one segment")
        if any(
            item.selected_type is ContactType.RACKET
            for item in self.post_hit_contacts
        ):
            raise ValueError("post-hit evidence must stop at the next racket boundary")
        _require_ordered_contacts(self.post_hit_contacts, self.hitter_contact.timestamp_us)
        _require_ordered_contacts(self.prior_contacts, None)
        if any(item.timestamp_us >= self.hitter_contact.timestamp_us for item in self.prior_contacts):
            raise ValueError("prior contacts must precede hitter contact")


@dataclass(frozen=True, slots=True)
class ShotFeatures:
    serve_context: bool | None
    origin_court_m: tuple[float, float] | None
    target_court_m: tuple[float, float] | None
    origin_side: CourtSide | None
    target_side: CourtSide | None
    target_depth: CourtDepth | None
    target_depth_m: float | None
    target_width_m: float | None
    pre_velocity_px_s: tuple[float, float] | None
    post_velocity_px_s: tuple[float, float] | None
    direction_change_rad: float | None
    wall_sequence: tuple[ContactType, ...]
    wall_sequence_confidence: float | None
    floor_bounce_timestamp_us: int | None
    normalized_pace: float | None
    apex_proxy: float | None
    impact_height_proxy: float | None
    opponent_timing_s: float | None
    opponent_reach: float | None
    volley_evidence_available: bool
    available: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShotPrediction:
    primary_type: ShotType
    probabilities: Mapping[ShotType, float]
    confidence: float
    margin: float
    required_probability: float
    required_margin: float
    volley: bool | None
    volley_probability: float
    stroke_side: StrokeSide
    hitter: Hitter
    origin_side: CourtSide
    target_side: CourtSide
    target_depth: CourtDepth
    outcome: ShotOutcome
    features: ShotFeatures
    sample_timestamps_us: tuple[int, ...]
    reasons: tuple[str, ...]
    rejected_candidate: ShotType | None = None


@dataclass(frozen=True, slots=True)
class TrajectoryEstimate:
    segment_id: str
    available: bool
    unavailability_reason: str | None
    observed_image_points: tuple[tuple[float, float], ...]
    fitted_image_points: tuple[tuple[float, float], ...]
    timestamps_s: tuple[float, ...]
    source_timestamps_us: tuple[int, ...]
    covariances_px2: tuple[tuple[tuple[float, float], tuple[float, float]], ...]
    uncertainty_envelopes_px: tuple[
        tuple[tuple[float, float], tuple[float, float]], ...
    ]
    residual_rms_px: float
    robust_iterations: int
    jacobian_condition_number: float
    covariance_model: str
    image_speed_px_s: ScalarRange
    image_speed_normalized_s: ScalarRange
    court_points_m: tuple[tuple[float, float, float] | None, ...]
    metric_unavailability_reason: str | None
    source_manifest_ids: tuple[str, ...]
    model_manifest_ids: tuple[str, ...]
    model: str


@dataclass(frozen=True, slots=True)
class SpeedEstimate:
    minimum_m_s: CredibleValue
    median_m_s: CredibleValue
    peak_m_s: CredibleValue
    provenance: str
    segment_id: str


@dataclass(frozen=True, slots=True)
class UnavailableMeasurement:
    reason: str
    details: tuple[str, ...]
    segment_id: str




@dataclass(frozen=True, slots=True)
class TerminalContext:
    contacts: tuple[ContactEvent, ...]
    ball_segment: TrackSegment
    calibration: CalibrationResult | None
    terminal_player: Hitter
    window_start_us: int
    window_end_us: int
    terminal_contact_id: str
    max_contact_tolerance_us: int
    interference: InterferenceKind | None = None
    opponent_pressure: float | None = None
    opponent_reach: float | None = None
    player_displacement_m: float | None = None
    shot_difficulty: float | None = None
    rally_continued: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "contacts", tuple(self.contacts))
        object.__setattr__(self, "terminal_player", Hitter(self.terminal_player))
        if self.interference is not None:
            object.__setattr__(self, "interference", InterferenceKind(self.interference))
        _require_ordered_contacts(self.contacts, None)
        if not 0 <= self.window_start_us <= self.window_end_us:
            raise ValueError("terminal evidence window must be ordered")
        if self.window_end_us - self.window_start_us > MAX_SHOT_WINDOW_US:
            raise ValueError("terminal evidence window exceeds the bounded duration")
        if self.max_contact_tolerance_us < 0:
            raise ValueError("terminal contact tolerance must be nonnegative")
        if (
            len(self.contacts) > MAX_RAW_EVIDENCE_SAMPLES
            or len(self.ball_segment.points) > MAX_RAW_EVIDENCE_SAMPLES
        ):
            raise ValueError("terminal evidence exceeds the raw sample bound")
        if not self.terminal_contact_id.strip() or not any(
            item.contact_id == self.terminal_contact_id for item in self.contacts
        ):
            raise ValueError("terminal contact identifier must select supplied evidence")
        if any(
            item.segment_id != self.ball_segment.segment_id for item in self.contacts
        ) or any(
            point.segment_id != self.ball_segment.segment_id
            for point in self.ball_segment.points
        ):
            raise ValueError("terminal contact and ball evidence must share one segment")
        probabilities = (self.opponent_pressure, self.opponent_reach, self.shot_difficulty)
        if any(value is not None and (not math.isfinite(value) or not 0.0 <= value <= 1.0) for value in probabilities):
            raise ValueError("terminal probabilities must be finite and between zero and one")
        if self.player_displacement_m is not None and (
            not math.isfinite(self.player_displacement_m) or self.player_displacement_m < 0.0
        ):
            raise ValueError("player displacement must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class ErrorPrediction:
    selected_outcome: ErrorOutcome
    probabilities: Mapping[ErrorOutcome, float]
    player: Hitter
    confidence: float
    margin: float
    review_required: bool
    objective: bool
    evidence: tuple[str, ...]
    reasons: tuple[str, ...]
    support_timestamps_us: tuple[int, ...]
    required_probability: float
    required_margin: float


def _require_ordered_contacts(
    contacts: Sequence[ContactEvent], after_timestamp_us: int | None
) -> None:
    timestamps = tuple(item.timestamp_us for item in contacts)
    if any(later <= earlier for earlier, later in zip(timestamps, timestamps[1:])):
        raise ValueError("contacts must be strictly ordered")
    if after_timestamp_us is not None and any(value <= after_timestamp_us for value in timestamps):
        raise ValueError("post-hit contacts must follow hitter contact")


def _normalise_scores(scores: Mapping[StrEnum, float]) -> Mapping:
    if any(not math.isfinite(value) or value < 0.0 for value in scores.values()):
        raise ValueError("scores must be finite and nonnegative")
    total = float(sum(scores.values()))
    if total <= 0.0:
        raise ValueError("scores must have positive mass")
    return MappingProxyType({key: float(value / total) for key, value in scores.items()})


def _velocity(
    before: BallObservation, after: BallObservation
) -> tuple[float, float] | None:
    if before.x is None or before.y is None or after.x is None or after.y is None:
        return None
    dt = (after.timestamp_us - before.timestamp_us) / 1_000_000.0
    if dt <= 0.0:
        return None
    return ((after.x - before.x) / dt, (after.y - before.y) / dt)


def _resample_by_timestamp(
    items: Sequence,
    maximum: int,
    *,
    required_timestamps_us: Sequence[int] = (),
) -> tuple:
    ordered = tuple(sorted(items, key=lambda item: item.timestamp_us))
    if len(ordered) <= maximum:
        return ordered
    required_indices = {
        min(
            range(len(ordered)),
            key=lambda index: abs(
                ordered[index].timestamp_us - required_timestamp
            ),
        )
        for required_timestamp in required_timestamps_us
    }
    required_indices.update((0, len(ordered) - 1))
    remaining = max(0, maximum - len(required_indices))
    regular = {
        int(round(value))
        for value in np.linspace(0, len(ordered) - 1, remaining + 2)
    }
    selected = sorted(required_indices | regular)
    if len(selected) > maximum:
        optional = [index for index in selected if index not in required_indices]
        keep_optional = max(0, maximum - len(required_indices))
        optional = optional[:keep_optional]
        selected = sorted(required_indices | set(optional))
    return tuple(ordered[index] for index in selected)


def _windowed_shot_evidence(
    context: ShotContext,
) -> tuple[
    tuple[BallObservation, ...],
    tuple[PlayerObservation, ...],
    tuple[PlayerObservation, ...],
    tuple[ContactEvent, ...],
    tuple[ContactEvent, ...],
]:
    def in_window(timestamp_us: int) -> bool:
        before_boundary = (
            timestamp_us < context.window_end_us
            if context.window_boundary is ShotWindowBoundary.NEXT_RACKET
            else timestamp_us <= context.window_end_us
        )
        return context.window_start_us <= timestamp_us and before_boundary

    post_contacts = tuple(
        item
        for item in context.post_hit_contacts
        if context.hit_timestamp_us < item.timestamp_us and in_window(item.timestamp_us)
    )
    prior_contacts = tuple(
        item
        for item in context.prior_contacts
        if context.window_start_us <= item.timestamp_us < context.hit_timestamp_us
    )
    required = (
        context.hit_timestamp_us,
        *(item.timestamp_us for item in post_contacts),
    )
    points = _resample_by_timestamp(
        tuple(
            item
            for item in context.ball_segment.points
            if in_window(item.timestamp_us)
        ),
        MAX_SHOT_SAMPLES,
        required_timestamps_us=required,
    )
    hitter_observations = _resample_by_timestamp(
        tuple(
            item
            for item in context.hitter_observations
            if in_window(item.timestamp_us)
        ),
        MAX_SHOT_SAMPLES,
        required_timestamps_us=(context.hit_timestamp_us,),
    )
    opponent_observations = _resample_by_timestamp(
        tuple(
            item
            for item in context.opponent_observations
            if in_window(item.timestamp_us)
        ),
        MAX_SHOT_SAMPLES,
        required_timestamps_us=(context.hit_timestamp_us,),
    )
    return (
        points,
        hitter_observations,
        opponent_observations,
        post_contacts,
        prior_contacts,
    )


def _nearest_player(
    observations: Sequence[PlayerObservation],
    timestamp_us: int,
    player_id: str,
    tolerance_us: int,
) -> PlayerObservation | None:
    candidates = tuple(item for item in observations if item.player_id == player_id)
    if not candidates:
        return None
    selected = min(candidates, key=lambda item: abs(item.timestamp_us - timestamp_us))
    if abs(selected.timestamp_us - timestamp_us) > tolerance_us:
        return None
    return selected


def _side(x_m: float, *, margin_m: float = 0.20) -> CourtSide:
    center = 3.20
    if x_m < center - margin_m:
        return CourtSide.LEFT
    if x_m > center + margin_m:
        return CourtSide.RIGHT
    return CourtSide.UNKNOWN


def _depth(y_m: float) -> CourtDepth:
    if y_m < 3.25:
        return CourtDepth.FRONT
    if y_m > 6.50:
        return CourtDepth.BACK
    return CourtDepth.MID


def _feature_point(
    points: Sequence[BallObservation],
    timestamp_us: int,
    tolerance_us: int,
) -> BallObservation | None:
    visible = tuple(
        item
        for item in points
        if item.visible and item.x is not None and item.y is not None
    )
    if not visible:
        return None
    selected = min(visible, key=lambda item: abs(item.timestamp_us - timestamp_us))
    if abs(selected.timestamp_us - timestamp_us) > tolerance_us:
        return None
    return selected


def _finite_pair(value: tuple[float, float] | None) -> tuple[float, float] | None:
    if value is None or not all(math.isfinite(item) for item in value):
        return None
    return value


def _extract_shot_features(context: ShotContext) -> ShotFeatures:
    (
        points,
        hitter_observations,
        opponent_observations,
        post_contacts,
        _,
    ) = _windowed_shot_evidence(context)
    hit_us = context.hit_timestamp_us
    before = tuple(item for item in points if item.timestamp_us < hit_us and item.visible)
    after = tuple(item for item in points if item.timestamp_us > hit_us and item.visible)
    hit_point = _feature_point(points, hit_us, context.max_hit_tolerance_us)
    pre_velocity = (
        _finite_pair(_velocity(before[-1], hit_point))
        if before and hit_point is not None
        else None
    )
    post_velocity = (
        _finite_pair(_velocity(hit_point, after[0]))
        if after and hit_point is not None
        else None
    )
    direction_change = None
    if pre_velocity is not None and post_velocity is not None:
        pre_angle = math.atan2(pre_velocity[1], pre_velocity[0])
        post_angle = math.atan2(post_velocity[1], post_velocity[0])
        direction_change = abs(
            math.atan2(
                math.sin(post_angle - pre_angle),
                math.cos(post_angle - pre_angle),
            )
        )

    selected_hitter = context.hitter_contact.selected_hitter
    player_observation = None
    if selected_hitter in (Hitter.A, Hitter.B):
        player_observation = _nearest_player(
            hitter_observations,
            hit_us,
            selected_hitter.value,
            context.max_player_tolerance_us,
        )
    origin = None
    if (
        player_observation is not None
        and not player_observation.ambiguous
        and context.calibration is not None
        and context.calibration.calibrated
        and context.calibration.capabilities.floor_position
    ):
        projection = project_floor(
            ImagePoint(*player_observation.feet), context.calibration
        )
        if projection.value is not None and projection.inside_court is not False:
            origin = (projection.value.x_m, projection.value.y_m)

    floor_contacts = tuple(
        item
        for item in post_contacts
        if item.selected_type is ContactType.FLOOR
        and item.confidence >= _MIN_CONTACT_CONFIDENCE
        and not item.review_required
    )
    target = None
    target_timestamp = floor_contacts[0].timestamp_us if floor_contacts else None
    if (
        target_timestamp is not None
        and context.calibration is not None
        and context.calibration.calibrated
        and context.calibration.capabilities.floor_position
    ):
        floor_contact = floor_contacts[0]
        maximum_offset_us = max(
            context.max_hit_tolerance_us, 3 * floor_contact.uncertainty_us
        )
        target_point = _feature_point(points, target_timestamp, maximum_offset_us)
        if target_point is not None:
            projection = project_floor(
                ImagePoint(float(target_point.x), float(target_point.y)),
                context.calibration,
            )
            if projection.value is not None and projection.inside_court is not False:
                target = (projection.value.x_m, projection.value.y_m)

    wall_sequence: tuple[ContactType, ...] = ()
    wall_confidence = None
    wall_contacts = tuple(
        item
        for item in post_contacts
        if item.selected_type
        in (ContactType.SIDE_WALL, ContactType.FRONT_WALL, ContactType.BACK_WALL)
    )
    invalid_wall_evidence = any(
        item.selected_type is ContactType.UNKNOWN
        or item.review_required
        or item.confidence < _MIN_CONTACT_CONFIDENCE
        for item in post_contacts
    )
    if (
        context.wall_geometry_supported
        and context.calibration is not None
        and context.calibration.calibrated
        and wall_contacts
        and not invalid_wall_evidence
    ):
        wall_sequence = tuple(item.selected_type for item in wall_contacts)
        wall_confidence = min(item.confidence for item in wall_contacts)

    pace = None
    apex = None
    if hit_point is not None and after:
        post_path = (hit_point,) + after
        speeds: list[float] = []
        for first, second in zip(post_path, post_path[1:]):
            velocity = _velocity(first, second)
            if velocity is not None:
                diagonal = math.hypot(first.source_width, first.source_height)
                speeds.append(math.hypot(*velocity) / diagonal)
        if speeds:
            pace = float(np.median(np.asarray(speeds, dtype=np.float64)))
        minimum_y = min(float(item.y) for item in after if item.y is not None)
        apex = max(
            0.0, (float(hit_point.y) - minimum_y) / hit_point.source_height
        )

    impact_height = None
    if hit_point is not None and player_observation is not None:
        body_height = player_observation.box.y2 - player_observation.box.y1
        if body_height > 0.0:
            impact_height = min(
                1.0,
                max(
                    0.0,
                    (player_observation.feet[1] - float(hit_point.y))
                    / body_height,
                ),
            )

    opponent_timing = None
    opponent_reach = None
    if opponent_observations:
        closest_opponent = min(
            opponent_observations,
            key=lambda item: abs(item.timestamp_us - hit_us),
        )
        timing_us = abs(closest_opponent.timestamp_us - hit_us)
        if timing_us <= context.max_player_tolerance_us:
            opponent_ball = _feature_point(
                points,
                closest_opponent.timestamp_us,
                context.max_hit_tolerance_us,
            )
            opponent_timing = timing_us / 1_000_000.0
            if opponent_ball is not None:
                candidate_points = [
                    (
                        keypoint.x,
                        keypoint.y,
                    )
                    for keypoint in (
                        closest_opponent.keypoints[9],
                        closest_opponent.keypoints[10],
                    )
                    if keypoint.confidence >= 0.5
                ]
                candidate_points.append(
                    (
                        (closest_opponent.box.x1 + closest_opponent.box.x2) / 2.0,
                        (closest_opponent.box.y1 + closest_opponent.box.y2) / 2.0,
                    )
                )
                distance = min(
                    math.hypot(
                        float(opponent_ball.x) - candidate_x,
                        float(opponent_ball.y) - candidate_y,
                    )
                    for candidate_x, candidate_y in candidate_points
                )
                diagonal = math.hypot(
                    opponent_ball.source_width, opponent_ball.source_height
                )
                opponent_reach = min(
                    1.0, max(0.0, 1.0 - distance / (0.35 * diagonal))
                )

    available: list[str] = []
    if hit_point is not None:
        available.append("hit_point")
    for name, value in (
        ("origin_court", origin),
        ("target_court", target),
        ("pre_velocity", pre_velocity),
        ("post_velocity", post_velocity),
        ("direction_change", direction_change),
        ("wall_sequence", wall_sequence or None),
        ("normalized_pace", pace),
        ("apex_proxy", apex),
        ("impact_height_proxy", impact_height),
        ("opponent_timing", opponent_timing),
        ("opponent_reach", opponent_reach),
    ):
        if value is not None:
            available.append(name)

    return ShotFeatures(
        serve_context=context.serve_context,
        origin_court_m=origin,
        target_court_m=target,
        origin_side=_side(origin[0]) if origin is not None else None,
        target_side=_side(target[0]) if target is not None else None,
        target_depth=_depth(target[1]) if target is not None else None,
        target_depth_m=target[1] if target is not None else None,
        target_width_m=target[0] if target is not None else None,
        pre_velocity_px_s=pre_velocity,
        post_velocity_px_s=post_velocity,
        direction_change_rad=direction_change,
        wall_sequence=wall_sequence,
        wall_sequence_confidence=wall_confidence,
        floor_bounce_timestamp_us=target_timestamp,
        normalized_pace=pace,
        apex_proxy=apex,
        impact_height_proxy=impact_height,
        opponent_timing_s=opponent_timing,
        opponent_reach=opponent_reach,
        volley_evidence_available=False,
        available=tuple(available),
    )


def _volley_prediction(
    context: ShotContext, features: ShotFeatures
) -> tuple[bool | None, float, bool]:
    _, _, _, _, prior_contacts = _windowed_shot_evidence(context)
    hit_us = context.hit_timestamp_us
    eligible = tuple(
        item
        for item in prior_contacts
        if item.segment_id == context.ball_segment.segment_id
        and item.selected_type is ContactType.RACKET
        and item.selected_hitter in (Hitter.A, Hitter.B)
        and item.selected_hitter is not context.hitter_contact.selected_hitter
        and item.confidence >= _MIN_CONTACT_CONFIDENCE
        and not item.review_required
    )
    if not eligible or features.impact_height_proxy is None:
        return None, 0.25, False
    previous = eligible[-1]
    between = tuple(
        item
        for item in prior_contacts
        if previous.timestamp_us < item.timestamp_us < hit_us
    )
    if any(
        item.segment_id != context.ball_segment.segment_id
        or item.selected_type is ContactType.UNKNOWN
        or item.review_required
        or item.confidence < _MIN_CONTACT_CONFIDENCE
        for item in between
    ):
        return None, 0.30, False
    no_floor = not any(item.selected_type is ContactType.FLOOR for item in between)
    timing_supported = (
        0 < hit_us - previous.timestamp_us <= MAX_SHOT_WINDOW_US
    )
    height_supported = features.impact_height_proxy >= 0.35
    if not timing_supported:
        return None, 0.30, False
    if not no_floor:
        return False, 0.85, True
    if height_supported:
        return True, 0.85, True
    return None, 0.40, True


def _stroke_side(context: ShotContext, hitter: Hitter) -> StrokeSide:
    if (
        hitter not in (Hitter.A, Hitter.B)
        or context.hitter_handedness is Handedness.UNKNOWN
    ):
        return StrokeSide.UNKNOWN
    points, hitter_observations, _, _, _ = _windowed_shot_evidence(context)
    observation = _nearest_player(
        hitter_observations,
        context.hit_timestamp_us,
        hitter.value,
        context.max_player_tolerance_us,
    )
    point = _feature_point(
        points, context.hit_timestamp_us, context.max_hit_tolerance_us
    )
    if observation is None or observation.ambiguous or point is None:
        return StrokeSide.UNKNOWN
    delta = float(point.x) - (observation.box.x1 + observation.box.x2) / 2.0
    if abs(delta) < max(2.0, observation.feet_uncertainty_px):
        return StrokeSide.UNKNOWN
    forehand = (
        delta > 0.0
        if context.hitter_handedness is Handedness.RIGHT
        else delta < 0.0
    )
    return StrokeSide.FOREHAND if forehand else StrokeSide.BACKHAND


def classify_shot(context: ShotContext) -> ShotPrediction:
    features = _extract_shot_features(context)
    scores = {shot_type: 0.0 for shot_type in ShotType}
    scores[ShotType.UNKNOWN] = 1.0
    reasons: list[str] = []

    hit_supported = "hit_point" in features.available
    if features.serve_context is True:
        scores[ShotType.SERVE] = 12.0
        scores[ShotType.UNKNOWN] = 0.2
        reasons.append("explicit_serve_context")
    elif not hit_supported:
        reasons.append("hitter_ball_contact_not_temporally_supported")
    elif features.wall_sequence[:2] == (
        ContactType.SIDE_WALL,
        ContactType.FRONT_WALL,
    ):
        scores[ShotType.BOAST] = 8.0
        scores[ShotType.UNKNOWN] = 0.4
        reasons.append("supported_side_before_front_wall")
    elif (
        features.normalized_pace is not None
        and features.target_depth_m is not None
        and features.apex_proxy is not None
    ):
        pace = features.normalized_pace
        depth = features.target_depth_m
        apex = features.apex_proxy
        if depth <= 3.25 and pace <= 0.45 and apex <= 0.30:
            scores[ShotType.DROP] = 7.0
            reasons.append("low_pace_short_depth")
        elif depth >= 7.5 and apex >= 0.30:
            scores[ShotType.LOB] = 7.0
            reasons.append("deep_target_high_apex")
        elif depth <= 3.25 and pace >= 0.80 and apex <= 0.30:
            scores[ShotType.KILL] = 7.0
            reasons.append("high_pace_short_depth")

    if hit_supported and max(
        scores[shot_type]
        for shot_type in ShotType
        if shot_type is not ShotType.UNKNOWN
    ) == 0.0:
        origin_side = features.origin_side
        target_side = features.target_side
        if (
            origin_side in (CourtSide.LEFT, CourtSide.RIGHT)
            and target_side in (CourtSide.LEFT, CourtSide.RIGHT)
        ):
            drive_type = (
                ShotType.STRAIGHT_DRIVE
                if origin_side is target_side
                else ShotType.CROSSCOURT_DRIVE
            )
            scores[drive_type] = 6.0
            scores[ShotType.UNKNOWN] = 0.8
            reasons.append("calibrated_origin_target_sides")
        elif origin_side is not None and target_side is CourtSide.UNKNOWN:
            scores[ShotType.STRAIGHT_DRIVE] = 1.1
            scores[ShotType.CROSSCOURT_DRIVE] = 1.1
            reasons.append("target_side_margin_insufficient")
        else:
            reasons.append("insufficient_supported_shot_evidence")

    probabilities = _normalise_scores(scores)
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    top_type, top_confidence = ranked[0]
    top_margin = top_confidence - ranked[1][1]
    selected = ShotType(top_type)
    rejected_candidate = None
    if (
        selected is not ShotType.UNKNOWN
        and (
            top_confidence < SHOT_PROBABILITY_THRESHOLD
            or top_margin < SHOT_MARGIN_THRESHOLD
        )
    ):
        rejected_candidate = selected
        selected = ShotType.UNKNOWN
        reasons.append("classification_threshold_or_margin_not_met")
    confidence = float(probabilities[selected])
    second_for_selected = max(
        value for shot_type, value in probabilities.items() if shot_type is not selected
    )
    margin = confidence - second_for_selected

    hitter = context.hitter_contact.selected_hitter
    observation = None
    points, hitter_observations, opponent_observations, post_contacts, _ = (
        _windowed_shot_evidence(context)
    )
    if hitter in (Hitter.A, Hitter.B):
        observation = _nearest_player(
            hitter_observations,
            context.hit_timestamp_us,
            hitter.value,
            context.max_player_tolerance_us,
        )
    if observation is None or observation.ambiguous:
        hitter = Hitter.UNKNOWN
    stroke_side = _stroke_side(context, hitter)
    volley, volley_probability, volley_available = _volley_prediction(context, features)
    features = ShotFeatures(
        **{
            field: getattr(features, field)
            for field in features.__dataclass_fields__
            if field != "volley_evidence_available"
        },
        volley_evidence_available=volley_available,
    )
    timestamps = sorted(
        {
            context.hitter_contact.timestamp_us,
            *(item.timestamp_us for item in post_contacts),
            *(item.timestamp_us for item in points),
            *(item.timestamp_us for item in hitter_observations),
            *(item.timestamp_us for item in opponent_observations),
        }
    )
    if len(timestamps) > MAX_SHOT_SAMPLES:
        indices = sorted(
            {
                int(round(value))
                for value in np.linspace(0, len(timestamps) - 1, MAX_SHOT_SAMPLES)
            }
        )
        timestamps = [timestamps[index] for index in indices]
    timestamps_tuple = tuple(timestamps)
    return ShotPrediction(
        primary_type=selected,
        probabilities=probabilities,
        confidence=float(confidence),
        margin=float(margin),
        required_probability=SHOT_PROBABILITY_THRESHOLD,
        required_margin=SHOT_MARGIN_THRESHOLD,
        volley=volley,
        volley_probability=volley_probability,
        stroke_side=stroke_side,
        hitter=hitter,
        origin_side=features.origin_side or CourtSide.UNKNOWN,
        target_side=features.target_side or CourtSide.UNKNOWN,
        target_depth=features.target_depth or CourtDepth.UNKNOWN,
        outcome=ShotOutcome.UNKNOWN,
        features=features,
        sample_timestamps_us=timestamps_tuple,
        reasons=tuple(dict.fromkeys(reasons)),
        rejected_candidate=rejected_candidate,
    )


def _fit_coordinate(
    timestamps_s: np.ndarray,
    values: np.ndarray,
    variances: np.ndarray,
) -> tuple[np.ndarray, int]:
    count = len(values)
    if count <= 3:
        return values.copy(), 1
    sigma = np.sqrt(np.clip(variances, 1.0e-6, None))
    weights = 1.0 / sigma
    fitted = values.copy()
    iterations = 3
    smoothing = float(
        count * max(100.0, float(np.median(variances)) * 100.0)
    )
    for _ in range(iterations):
        spline = UnivariateSpline(
            timestamps_s,
            values,
            w=weights,
            k=min(3, count - 1),
            s=smoothing,
        )
        fitted = np.asarray(spline(timestamps_s), dtype=np.float64)
        residuals = values - fitted
        median = float(np.median(residuals))
        mad = float(np.median(np.abs(residuals - median)))
        scale = max(1.4826 * mad, float(np.median(sigma)), 1.0e-3)
        robust = 1.0 / np.sqrt(
            1.0 + (residuals / (2.5 * scale)) ** 2
        )
        weights = robust / sigma
    return fitted, iterations


def _pointwise_envelopes(
    values: np.ndarray, variances: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    sigmas = np.sqrt(np.clip(variances, 1.0e-9, None))
    return values - 3.0 * sigmas, values + 3.0 * sigmas


def _fit_axis_with_constraints(
    timestamps_s: np.ndarray,
    values: np.ndarray,
    variances: np.ndarray,
    constraint_indices: frozenset[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    fitted, iterations = _fit_coordinate(timestamps_s, values, variances)
    lower, upper = _pointwise_envelopes(values, variances)
    fitted = np.clip(fitted, lower, upper)
    if len(fitted):
        fitted[0] = values[0]
        fitted[-1] = values[-1]
    for index in constraint_indices:
        fitted[index] = values[index]
    return fitted, lower, upper, iterations


def _finite_difference_jacobian(
    timestamps_s: np.ndarray,
    values: np.ndarray,
    variances: np.ndarray,
    constraint_indices: frozenset[int],
    baseline: np.ndarray,
) -> np.ndarray:
    count = len(values)
    jacobian = np.zeros((count, count), dtype=np.float64)
    for index in range(count):
        step = max(1.0e-4, math.sqrt(max(variances[index], 1.0e-9)) * 1.0e-3)
        perturbed = values.copy()
        perturbed[index] += step
        changed, _, _, _ = _fit_axis_with_constraints(
            timestamps_s, perturbed, variances, constraint_indices
        )
        jacobian[:, index] = (changed - baseline) / step
    return jacobian


def _range(
    values: Sequence[float], uncertainties: Sequence[float]
) -> ScalarRange:
    if not values:
        return ScalarRange(0.0, 0.0, 0.0, 0.0)
    array = np.asarray(values, dtype=np.float64)
    uncertainty = (
        float(
            np.sqrt(
                np.median(np.asarray(uncertainties, dtype=np.float64) ** 2)
            )
        )
        if uncertainties
        else 0.0
    )
    return ScalarRange(
        float(np.min(array)),
        float(np.median(array)),
        float(np.max(array)),
        uncertainty,
    )


def estimate_trajectory(
    segment: TrackSegment,
    calibration: CalibrationResult,
    *,
    contact_constraints: Sequence[TrajectoryContactConstraint] = (),
) -> TrajectoryEstimate:
    if not segment.segment_id.strip():
        raise ValueError("trajectory segment identifier cannot be blank")
    if len(segment.points) > MAX_RAW_EVIDENCE_SAMPLES:
        raise ValueError("trajectory exceeds the raw sample bound")
    if any(point.segment_id != segment.segment_id for point in segment.points):
        raise ValueError("trajectory points must belong to exactly one segment")
    constraints = tuple(contact_constraints)
    if len(constraints) > MAX_TRAJECTORY_SAMPLES - 2:
        raise ValueError("trajectory contact constraints exceed the bounded sample count")
    if any(item.segment_id != segment.segment_id for item in constraints):
        raise ValueError("trajectory contact constraints must share the segment")
    visible = tuple(point for point in segment.points if point.visible)
    raw_timestamps_us = tuple(point.timestamp_us for point in visible)
    if any(
        later <= earlier
        for earlier, later in zip(
            raw_timestamps_us, raw_timestamps_us[1:]
        )
    ):
        raise ValueError("trajectory timestamps must be strictly increasing")
    if any(
        point.x is None or point.y is None or point.covariance is None
        for point in visible
    ):
        raise ValueError(
            "visible trajectory points require coordinates and covariance"
        )
    visible_timestamps = {point.timestamp_us for point in visible}
    supported_constraints = tuple(
        item
        for item in constraints
        if item.confidence >= _MIN_CONTACT_CONFIDENCE
        and item.timestamp_us in visible_timestamps
    )
    points = _resample_by_timestamp(
        visible,
        MAX_TRAJECTORY_SAMPLES,
        required_timestamps_us=tuple(
            item.timestamp_us for item in supported_constraints
        ),
    )
    timestamps_us = tuple(point.timestamp_us for point in points)
    observed = np.asarray(
        [(float(point.x), float(point.y)) for point in points],
        dtype=np.float64,
    )
    timestamps_s_absolute = (
        np.asarray(timestamps_us, dtype=np.float64) / 1_000_000.0
    )
    timestamps_s = (
        timestamps_s_absolute - timestamps_s_absolute[0]
        if len(timestamps_s_absolute)
        else timestamps_s_absolute
    )
    covariance_arrays = tuple(
        np.asarray(point.covariance, dtype=np.float64) for point in points
    )
    if any(
        matrix.shape != (2, 2) or not np.all(np.isfinite(matrix))
        for matrix in covariance_arrays
    ):
        raise ValueError("trajectory covariance must be finite and 2x2")

    raw_deltas = (
        np.diff(np.asarray(raw_timestamps_us, dtype=np.float64))
        / 1_000_000.0
    )
    raw_median_delta = (
        float(np.median(raw_deltas)) if len(raw_deltas) else 0.0
    )
    gap_limit = (
        max(0.5, 4.0 * raw_median_delta)
        if raw_median_delta > 0.0
        else 0.5
    )
    deltas = np.diff(timestamps_s)
    continuity_mask = deltas <= gap_limit
    gap = bool(len(continuity_mask) and not np.all(continuity_mask))
    too_short = bool(
        len(timestamps_s) >= 2
        and float(timestamps_s[-1] - timestamps_s[0])
        < _MIN_SPLINE_DURATION_S
    )
    point_index_by_timestamp = {
        point.timestamp_us: index for index, point in enumerate(points)
    }
    constraint_indices = frozenset(
        point_index_by_timestamp[constraint.timestamp_us]
        for constraint in supported_constraints
    )

    jacobian_condition = 1.0
    covariance_model = "finite_difference_jacobian"
    ill_conditioned = too_short
    if len(points) >= 2 and not gap and not too_short:
        x_variances = np.asarray(
            [matrix[0, 0] for matrix in covariance_arrays],
            dtype=np.float64,
        )
        y_variances = np.asarray(
            [matrix[1, 1] for matrix in covariance_arrays],
            dtype=np.float64,
        )
        x_fit, x_lower, x_upper, x_iterations = _fit_axis_with_constraints(
            timestamps_s,
            observed[:, 0],
            x_variances,
            constraint_indices,
        )
        y_fit, y_lower, y_upper, y_iterations = _fit_axis_with_constraints(
            timestamps_s,
            observed[:, 1],
            y_variances,
            constraint_indices,
        )
        fitted = np.column_stack((x_fit, y_fit))
        x_jacobian = _finite_difference_jacobian(
            timestamps_s,
            observed[:, 0],
            x_variances,
            constraint_indices,
            x_fit,
        )
        y_jacobian = _finite_difference_jacobian(
            timestamps_s,
            observed[:, 1],
            y_variances,
            constraint_indices,
            y_fit,
        )
        regularizer = np.eye(len(points), dtype=np.float64) * 1.0e-6
        jacobian_condition = max(
            float(np.linalg.cond(x_jacobian + regularizer)),
            float(np.linalg.cond(y_jacobian + regularizer)),
        )
        ill_conditioned = (
            not math.isfinite(jacobian_condition)
            or jacobian_condition > _MAX_SPLINE_JACOBIAN_CONDITION
            or not np.all(np.isfinite(fitted))
        )
        robust_iterations = max(x_iterations, y_iterations)
    else:
        fitted = observed.copy()
        x_lower = observed[:, 0].copy() if len(points) else np.asarray([])
        x_upper = x_lower.copy()
        y_lower = observed[:, 1].copy() if len(points) else np.asarray([])
        y_upper = y_lower.copy()
        x_jacobian = np.eye(len(points), dtype=np.float64)
        y_jacobian = np.eye(len(points), dtype=np.float64)
        robust_iterations = 0

    residuals = (
        np.linalg.norm(observed - fitted, axis=1)
        if len(points)
        else np.asarray([])
    )
    residual_rms = (
        float(math.sqrt(float(np.mean(residuals**2))))
        if len(residuals)
        else 0.0
    )
    residual_variance = (
        float(np.median(residuals**2)) / max(1, len(points) - 2)
        if len(residuals)
        else 0.0
    )
    count = len(points)
    input_covariance = np.zeros((2 * count, 2 * count), dtype=np.float64)
    full_jacobian = np.zeros_like(input_covariance)
    for index, matrix in enumerate(covariance_arrays):
        rows = (index, count + index)
        input_covariance[np.ix_(rows, rows)] = matrix
    full_jacobian[:count, :count] = x_jacobian
    full_jacobian[count:, count:] = y_jacobian
    propagated_full = (
        full_jacobian @ input_covariance @ full_jacobian.T
        + np.eye(2 * count, dtype=np.float64) * residual_variance
    )
    if not np.all(np.isfinite(propagated_full)):
        ill_conditioned = True
        propagated_full = np.eye(2 * count, dtype=np.float64)
    output_covariances = []
    for index in range(count):
        rows = (index, count + index)
        propagated = propagated_full[np.ix_(rows, rows)]
        propagated = (propagated + propagated.T) / 2.0
        eigenvalues, eigenvectors = np.linalg.eigh(propagated)
        propagated = (
            eigenvectors
            @ np.diag(np.clip(eigenvalues, 1.0e-9, None))
            @ eigenvectors.T
        )
        output_covariances.append(
            (
                (float(propagated[0, 0]), float(propagated[0, 1])),
                (float(propagated[1, 0]), float(propagated[1, 1])),
            )
        )

    speeds_px: list[float] = []
    speeds_normalized: list[float] = []
    speed_uncertainties_px: list[float] = []
    speed_uncertainties_normalized: list[float] = []
    for index, (dt, continuous) in enumerate(
        zip(deltas, continuity_mask, strict=True)
    ):
        if dt <= 0.0 or not continuous:
            continue
        displacement = fitted[index + 1] - fitted[index]
        distance = float(np.linalg.norm(displacement))
        speed = distance / float(dt)
        covariance = (
            np.asarray(output_covariances[index], dtype=np.float64)
            + np.asarray(output_covariances[index + 1], dtype=np.float64)
        )
        if distance > 1.0e-12:
            direction = displacement / distance
            distance_variance = float(direction @ covariance @ direction)
        else:
            distance_variance = float(
                np.max(np.linalg.eigvalsh(covariance))
            )
        speed_uncertainty = (
            math.sqrt(max(0.0, distance_variance)) / float(dt)
        )
        diagonal = math.hypot(
            points[index].source_width, points[index].source_height
        )
        speeds_px.append(speed)
        speeds_normalized.append(speed / diagonal)
        speed_uncertainties_px.append(speed_uncertainty)
        speed_uncertainties_normalized.append(speed_uncertainty / diagonal)

    metric_reason = (
        "uncalibrated"
        if not calibration.calibrated
        else "floor_only_calibration"
    )
    available = len(points) >= 2 and not gap and not ill_conditioned
    unavailability_reason = None
    if gap:
        unavailability_reason = "segment_gap"
    elif len(points) < 2:
        unavailability_reason = "insufficient_points"
    elif ill_conditioned:
        unavailability_reason = "uncertainty_too_high"
    envelopes = tuple(
        (
            (float(x_lower[index]), float(x_upper[index])),
            (float(y_lower[index]), float(y_upper[index])),
        )
        for index in range(len(points))
    )
    return TrajectoryEstimate(
        segment_id=segment.segment_id,
        available=available,
        unavailability_reason=unavailability_reason,
        observed_image_points=tuple(
            (float(row[0]), float(row[1])) for row in observed
        ),
        fitted_image_points=tuple(
            (float(row[0]), float(row[1])) for row in fitted
        ),
        timestamps_s=tuple(float(value) for value in timestamps_s),
        source_timestamps_us=timestamps_us,
        covariances_px2=tuple(output_covariances),
        uncertainty_envelopes_px=envelopes,
        residual_rms_px=residual_rms,
        robust_iterations=robust_iterations,
        jacobian_condition_number=float(jacobian_condition),
        covariance_model=covariance_model,
        image_speed_px_s=_range(speeds_px, speed_uncertainties_px),
        image_speed_normalized_s=_range(
            speeds_normalized, speed_uncertainties_normalized
        ),
        court_points_m=(None,) * len(points),
        metric_unavailability_reason=metric_reason,
        source_manifest_ids=tuple(
            sorted({point.source_manifest_id for point in points})
        ),
        model_manifest_ids=tuple(
            sorted({point.model_manifest_id for point in points})
        ),
        model="bounded_robust_cubic_smoothing_spline_image_space",
    )


def estimate_speed(
    trajectory: TrajectoryEstimate,
) -> SpeedEstimate | UnavailableMeasurement:
    if trajectory.unavailability_reason is not None:
        return UnavailableMeasurement(
            trajectory.unavailability_reason,
            ("trajectory_not_continuous",),
            trajectory.segment_id,
        )
    return UnavailableMeasurement(
        trajectory.metric_unavailability_reason or "uncalibrated",
        ("validated_2.5d_reconstruction_producer_unavailable",),
        trajectory.segment_id,
    )


def classify_terminal_event(context: TerminalContext) -> ErrorPrediction:
    scores = {outcome: 0.0 for outcome in ErrorOutcome}
    scores[ErrorOutcome.UNKNOWN] = 1.0
    evidence: list[str] = []
    reasons: list[str] = []
    support_timestamps: list[int] = []
    objective = False
    review_required = True
    candidate: ErrorOutcome | None = None

    windowed_contacts = tuple(
        item
        for item in context.contacts
        if context.window_start_us <= item.timestamp_us <= context.window_end_us
    )
    terminal_contact = next(
        (
            item
            for item in windowed_contacts
            if item.contact_id == context.terminal_contact_id
        ),
        None,
    )
    terminal_supported = (
        terminal_contact is not None
        and terminal_contact.confidence >= _MIN_CONTACT_CONFIDENCE
        and not terminal_contact.review_required
    )

    terminal_event_types = {
        ContactType.FLOOR,
        ContactType.FRONT_WALL,
        ContactType.SIDE_WALL,
        ContactType.BACK_WALL,
    }
    terminal_event_supported = (
        terminal_supported
        and terminal_contact is not None
        and terminal_contact.selected_type in terminal_event_types
    )
    last_racket = next(
        (
            item
            for item in reversed(windowed_contacts)
            if item.selected_type is ContactType.RACKET
            and terminal_contact is not None
            and item.timestamp_us < terminal_contact.timestamp_us
        ),
        None,
    )

    def has_temporally_matched_ball(contact: ContactEvent) -> bool:
        return any(
            point.visible
            and abs(point.timestamp_us - contact.timestamp_us)
            <= context.max_contact_tolerance_us
            for point in context.ball_segment.points
        )

    floor_contacts = tuple(
        item
        for item in windowed_contacts
        if last_racket is not None
        and item.timestamp_us > last_racket.timestamp_us
        and item.selected_type is ContactType.FLOOR
        and item.confidence >= _MIN_CONTACT_CONFIDENCE
        and not item.review_required
        and has_temporally_matched_ball(item)
    )
    not_up_supported = (
        terminal_event_supported
        and terminal_contact is not None
        and terminal_contact.selected_type is ContactType.FLOOR
        and len(floor_contacts) >= 2
        and floor_contacts[-1].contact_id == terminal_contact.contact_id
        and context.calibration is not None
        and context.calibration.calibrated
        and context.calibration.capabilities.floor_position
        and context.calibration.confidence >= _MIN_CALIBRATION_CONFIDENCE
    )
    if not_up_supported:
        candidate = ErrorOutcome.NOT_UP
        scores[candidate] = 9.0
        scores[ErrorOutcome.UNKNOWN] = 0.2
        objective = True
        review_required = False
        evidence.append("two_supported_floor_contacts_after_last_racket")
        support_timestamps.extend(
            item.timestamp_us for item in floor_contacts[-2:]
        )
    elif (
        terminal_supported
        and terminal_contact is not None
        and context.interference is InterferenceKind.LET
    ):
        candidate = ErrorOutcome.LET_CANDIDATE
        scores[candidate] = 8.0
        scores[ErrorOutcome.UNKNOWN] = 0.5
        evidence.append("interference_evidence")
        reasons.append("candidate_requires_human_review")
        support_timestamps.append(terminal_contact.timestamp_us)
    elif (
        terminal_supported
        and terminal_contact is not None
        and context.interference is InterferenceKind.STROKE
    ):
        candidate = ErrorOutcome.STROKE_CANDIDATE
        scores[candidate] = 8.0
        scores[ErrorOutcome.UNKNOWN] = 0.5
        evidence.append("interference_evidence")
        reasons.append("candidate_requires_human_review")
        support_timestamps.append(terminal_contact.timestamp_us)
    elif (
        terminal_event_supported
        and terminal_contact is not None
        and context.opponent_pressure is not None
        and context.opponent_reach is not None
        and context.player_displacement_m is not None
        and context.shot_difficulty is not None
        and context.rally_continued is False
    ):
        forced_support = (
            context.opponent_pressure >= 0.65
            and context.opponent_reach <= 0.45
            and context.player_displacement_m >= 1.0
            and context.shot_difficulty >= 0.60
        )
        unforced_support = (
            context.opponent_pressure <= 0.35
            and context.opponent_reach >= 0.65
            and context.player_displacement_m <= 0.75
            and context.shot_difficulty <= 0.40
        )
        if forced_support:
            candidate = ErrorOutcome.FORCED_ERROR_CANDIDATE
        elif unforced_support:
            candidate = ErrorOutcome.UNFORCED_ERROR_CANDIDATE
        if candidate is not None:
            scores[candidate] = 7.0
            scores[ErrorOutcome.UNKNOWN] = 0.8
            evidence.extend(
                (
                    "opponent_pressure_and_reach",
                    "player_displacement",
                    "shot_difficulty",
                    "terminal_noncontinuation",
                    "confidence_gated_terminal_contact",
                )
            )
            reasons.append("candidate_requires_human_review")
            support_timestamps.append(terminal_contact.timestamp_us)
    if candidate is None and not reasons:
        reasons.append("insufficient_supported_terminal_evidence")

    probabilities = _normalise_scores(scores)
    ranked = sorted(
        probabilities.items(), key=lambda item: item[1], reverse=True
    )
    top_outcome, top_confidence = ranked[0]
    top_margin = top_confidence - ranked[1][1]
    selected = ErrorOutcome(top_outcome)
    if (
        selected is not ErrorOutcome.UNKNOWN
        and (
            top_confidence < TERMINAL_PROBABILITY_THRESHOLD
            or top_margin < TERMINAL_MARGIN_THRESHOLD
        )
    ):
        selected = ErrorOutcome.UNKNOWN
        objective = False
        review_required = True
        support_timestamps.clear()
        reasons.append("classification_threshold_or_margin_not_met")
    confidence = float(probabilities[selected])
    margin = confidence - max(
        value
        for outcome, value in probabilities.items()
        if outcome is not selected
    )
    return ErrorPrediction(
        selected_outcome=selected,
        probabilities=probabilities,
        player=context.terminal_player,
        confidence=confidence,
        margin=float(margin),
        review_required=review_required,
        objective=objective,
        evidence=tuple(dict.fromkeys(evidence)),
        reasons=tuple(dict.fromkeys(reasons)),
        support_timestamps_us=tuple(sorted(set(support_timestamps))),
        required_probability=TERMINAL_PROBABILITY_THRESHOLD,
        required_margin=TERMINAL_MARGIN_THRESHOLD,
    )


__all__ = [
    "MAX_SHOT_SAMPLES",
    "MAX_TRAJECTORY_SAMPLES",
    "CourtDepth",
    "CourtSide",
    "CredibleValue",
    "ErrorOutcome",
    "ErrorPrediction",
    "Handedness",
    "InterferenceKind",
    "ScalarRange",
    "ShotContext",
    "ShotFeatures",
    "ShotOutcome",
    "ShotPrediction",
    "ShotType",
    "ShotWindowBoundary",
    "SpeedEstimate",
    "StrokeSide",
    "TerminalContext",
    "TrajectoryEstimate",
    "TrajectoryContactConstraint",
    "UnavailableMeasurement",
    "classify_shot",
    "classify_terminal_event",
    "estimate_speed",
    "estimate_trajectory",
]
