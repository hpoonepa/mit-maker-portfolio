from __future__ import annotations

from dataclasses import replace
import math

import pytest

from squashvision.calibration import CalibrationCapabilities, CalibrationResult
from squashvision.observations import (
    APPEARANCE_DIMENSION,
    BallCandidate,
    BallObservation,
    BoundingBox,
    EvidenceKind,
    FloorEstimate,
    Keypoint,
    PlayerObservation,
)
from squashvision.vision.ball.tracker import TrackSegment
from squashvision.vision.contacts import (
    ContactEvidence,
    ContactEvent,
    ContactType,
    Hitter,
)
from squashvision.vision.shots import (
    MAX_SHOT_SAMPLES,
    MAX_TRAJECTORY_SAMPLES,
    ErrorOutcome,
    Handedness,
    InterferenceKind,
    ShotContext,
    ShotType,
    ShotWindowBoundary,
    StrokeSide,
    TerminalContext,
    TrajectoryContactConstraint,
    UnavailableMeasurement,
    classify_shot,
    classify_terminal_event,
    estimate_speed,
    estimate_trajectory,
)


def calibration(*, calibrated: bool = True, confidence: float = 0.95) -> CalibrationResult:
    return CalibrationResult(
        calibrated=calibrated,
        image_to_court=(
            (0.064, 0.0, 0.0),
            (0.0, 0.0975, 0.0),
            (0.0, 0.0, 1.0),
        )
        if calibrated
        else None,
        court_to_image=(
            (15.625, 0.0, 0.0),
            (0.0, 10.2564102564, 0.0),
            (0.0, 0.0, 1.0),
        )
        if calibrated
        else None,
        residuals_px=(1.0, 1.0, 1.0, 1.0) if calibrated else (),
        rms_error_px=1.0 if calibrated else None,
        max_error_px=1.0 if calibrated else None,
        inlier_mask=(True, True, True, True) if calibrated else (),
        condition_number=1.0 if calibrated else None,
        parameter_covariance=None,
        confidence=confidence,
        capabilities=CalibrationCapabilities(
            image_space=True,
            floor_position=calibrated,
            movement_distance=calibrated,
            speed=calibrated,
        ),
        warnings=() if calibrated else ("uncalibrated",),
    )


def ball_point(
    timestamp_us: int,
    x: float,
    y: float,
    *,
    segment_id: str = "segment-1",
    covariance: float = 1.0,
) -> BallObservation:
    cov = ((covariance, 0.0), (0.0, covariance))
    candidate = BallCandidate(
        x=x,
        y=y,
        peak_probability=0.95,
        integrated_probability=0.95,
        area=3,
        circularity=0.9,
        covariance=cov,
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
        covariance=cov,
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
        segment_id=segment_id,
        source_manifest_id="source-sha256",
        model_manifest_id="ball-sha256",
        device="cpu",
        device_fallback=False,
    )


def player(
    timestamp_us: int,
    player_id: str,
    *,
    feet_court: tuple[float, float],
    body_x: float = 25.0,
    ambiguous: bool = False,
) -> PlayerObservation:
    keypoints = [Keypoint(body_x, 50.0, 0.9) for _ in range(17)]
    keypoints[9] = Keypoint(body_x - 5.0, 45.0, 0.95)
    keypoints[10] = Keypoint(body_x + 5.0, 45.0, 0.95)
    return PlayerObservation(
        player_id=player_id,
        timestamp_us=timestamp_us,
        source_timestamp_us=timestamp_us,
        source_frame_index=timestamp_us // 10_000,
        box=BoundingBox(body_x - 10.0, 10.0, body_x + 10.0, 95.0),
        keypoints=tuple(keypoints),
        detection_confidence=0.95,
        appearance=(0.0,) * APPEARANCE_DIMENSION,
        feet=(body_x, 95.0),
        feet_uncertainty_px=1.0,
        evidence=EvidenceKind.OBSERVED,
        evidence_start_timestamp_us=timestamp_us,
        evidence_end_timestamp_us=timestamp_us,
        evidence_start_frame_index=timestamp_us // 10_000,
        evidence_end_frame_index=timestamp_us // 10_000,
        association_confidence=0.5 if ambiguous else 0.95,
        ambiguous=ambiguous,
        ambiguity_reason="identity_margin" if ambiguous else None,
        floor=FloorEstimate(feet_court, 0.1, "cal-1", "manual-lines"),
        source_manifest_id="source-sha256",
        model_manifest_id="pose-sha256",
    )


def contact(
    timestamp_us: int,
    selected_type: ContactType,
    *,
    selected_hitter: Hitter = Hitter.UNKNOWN,
    confidence: float = 0.95,
    segment_id: str = "segment-1",
) -> ContactEvent:
    type_probabilities = {kind: 0.01 for kind in ContactType}
    type_probabilities[selected_type] = 0.95
    hitter_probabilities = {kind: 0.01 for kind in Hitter}
    hitter_probabilities[selected_hitter] = 0.95
    return ContactEvent(
        segment_id=segment_id,
        contact_id=f"{selected_type}-{timestamp_us}",
        timestamp_us=timestamp_us,
        uncertainty_us=2_000,
        type_probabilities=type_probabilities,
        selected_type=selected_type,
        hitter_probabilities=hitter_probabilities,
        selected_hitter=selected_hitter,
        confidence=confidence,
        review_required=False,
        review_reasons=(),
        evidence=ContactEvidence(0.8, 0.8, 0.8, 0.9, 0.9, 0.8, 0.8),
        supporting_ball_timestamps_us=(timestamp_us,),
        supporting_player_timestamps_us=(timestamp_us,),
    )


def shot_context(
    *,
    target_x: float = 20.0,
    target_y: float = 72.0,
    post_xy: tuple[tuple[float, float], ...] | None = None,
    post_contacts: tuple[ContactEvent, ...] | None = None,
    calibrated: bool = True,
    serve_context: bool | None = False,
    wall_geometry_supported: bool = False,
    prior_contacts: tuple[ContactEvent, ...] = (),
    handedness: Handedness = Handedness.RIGHT,
    hitter_ambiguous: bool = False,
) -> ShotContext:
    hit_us = 100_000
    coordinates = post_xy or (
        (32.0, 42.0),
        (28.0, 38.0),
        (24.0, 48.0),
        (target_x, target_y),
    )
    points = [ball_point(0, 18.0, 48.0), ball_point(hit_us, 30.0, 45.0)]
    points.extend(
        ball_point(hit_us + (index + 1) * 100_000, x, y)
        for index, (x, y) in enumerate(coordinates)
    )
    floor = contact(hit_us + len(coordinates) * 100_000, ContactType.FLOOR)
    return ShotContext(
        hitter_contact=contact(hit_us, ContactType.RACKET, selected_hitter=Hitter.A),
        post_hit_contacts=post_contacts if post_contacts is not None else (floor,),
        ball_segment=TrackSegment("segment-1", tuple(points)),
        hitter_observations=(
            player(
                hit_us,
                "A",
                feet_court=(1.5, 7.0),
                body_x=25.0,
                ambiguous=hitter_ambiguous,
            ),
        ),
        opponent_observations=(player(hit_us, "B", feet_court=(4.8, 5.0), body_x=75.0),),
        calibration=calibration(calibrated=calibrated),
        rally_position=4,
        serve_context=serve_context,
        prior_contacts=prior_contacts,
        wall_geometry_supported=wall_geometry_supported,
        hitter_handedness=handedness,
        window_start_us=0,
        hit_timestamp_us=hit_us,
        window_end_us=hit_us + len(coordinates) * 100_000,
        max_hit_tolerance_us=20_000,
        max_player_tolerance_us=50_000,
    )


def assert_normalized(probabilities: dict | object) -> None:
    values = tuple(probabilities.values())
    assert values
    assert all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values)
    assert sum(values) == pytest.approx(1.0)


def test_explicit_serve_context_dominates_other_supporting_evidence() -> None:
    context = shot_context(
        serve_context=True,
        wall_geometry_supported=True,
        post_contacts=(
            contact(200_000, ContactType.SIDE_WALL),
            contact(300_000, ContactType.FRONT_WALL),
        ),
    )

    prediction = classify_shot(context)

    assert prediction.primary_type is ShotType.SERVE
    assert prediction.features.serve_context is True
    assert prediction.sample_timestamps_us
    assert_normalized(prediction.probabilities)


@pytest.mark.parametrize(
    ("target_x", "expected"),
    ((20.0, ShotType.STRAIGHT_DRIVE), (80.0, ShotType.CROSSCOURT_DRIVE)),
)
def test_drives_require_calibrated_origin_and_target_sides(
    target_x: float, expected: ShotType
) -> None:
    prediction = classify_shot(shot_context(target_x=target_x))

    assert prediction.primary_type is expected
    assert prediction.features.origin_side is not None
    assert prediction.features.target_side is not None
    assert prediction.features.target_depth_m is not None
    assert prediction.margin >= prediction.required_margin


def test_supported_side_wall_before_front_wall_classifies_boast() -> None:
    prediction = classify_shot(
        shot_context(
            wall_geometry_supported=True,
            post_contacts=(
                contact(200_000, ContactType.SIDE_WALL),
                contact(300_000, ContactType.FRONT_WALL),
            ),
        )
    )

    assert prediction.primary_type is ShotType.BOAST
    assert prediction.features.wall_sequence == (
        ContactType.SIDE_WALL,
        ContactType.FRONT_WALL,
    )


@pytest.mark.parametrize(
    ("post_xy", "target_y", "expected"),
    (
        (((30.0, 48.0), (28.0, 50.0), (25.0, 45.0), (22.0, 24.0)), 24.0, ShotType.DROP),
        (((35.0, 30.0), (42.0, 8.0), (50.0, 25.0), (80.0, 90.0)), 90.0, ShotType.LOB),
        (((55.0, 47.0), (75.0, 49.0), (90.0, 52.0), (35.0, 24.0)), 24.0, ShotType.KILL),
    ),
)
def test_pace_depth_and_apex_evidence_support_special_shots(
    post_xy: tuple[tuple[float, float], ...], target_y: float, expected: ShotType
) -> None:
    prediction = classify_shot(
        shot_context(post_xy=post_xy, target_x=post_xy[-1][0], target_y=target_y)
    )

    assert prediction.primary_type is expected
    assert prediction.features.normalized_pace is not None
    assert prediction.features.apex_proxy is not None


def test_volley_is_independent_and_retains_base_shot_type() -> None:
    previous_opponent = contact(0, ContactType.RACKET, selected_hitter=Hitter.B)
    context = shot_context(
        target_x=80.0,
        prior_contacts=(previous_opponent,),
    )

    prediction = classify_shot(context)

    assert prediction.primary_type is ShotType.CROSSCOURT_DRIVE
    assert prediction.volley is True
    assert prediction.volley_probability >= 0.7


def test_missing_volley_evidence_is_unknown_not_false() -> None:
    prediction = classify_shot(shot_context(prior_contacts=()))

    assert prediction.volley is None
    assert prediction.volley_probability < 0.7


def test_volley_unknown_for_cross_segment_or_ambiguous_intervening_contact() -> None:
    previous = contact(0, ContactType.RACKET, selected_hitter=Hitter.B)
    cross_segment = replace(previous, segment_id="segment-2")
    ambiguous = replace(
        contact(50_000, ContactType.UNKNOWN, confidence=0.4),
        review_required=True,
        review_reasons=("ambiguous_contact",),
    )

    cross_prediction = classify_shot(shot_context(prior_contacts=(cross_segment,)))
    ambiguous_prediction = classify_shot(
        shot_context(prior_contacts=(previous, ambiguous))
    )

    assert cross_prediction.volley is None
    assert ambiguous_prediction.volley is None


def test_missing_calibration_and_unsupported_unknown_walls_stay_unknown() -> None:
    unknown_wall = contact(200_000, ContactType.UNKNOWN)
    prediction = classify_shot(
        shot_context(
            calibrated=False,
            wall_geometry_supported=False,
            post_contacts=(unknown_wall, contact(300_000, ContactType.FRONT_WALL)),
        )
    )

    assert prediction.primary_type is ShotType.UNKNOWN
    assert prediction.features.wall_sequence == ()
    assert prediction.reasons
    assert_normalized(prediction.probabilities)


def test_low_margin_evidence_stays_unknown_with_visible_probabilities() -> None:
    context = shot_context(
        post_xy=((36.0, 42.0), (44.0, 28.0), (54.0, 35.0), (51.0, 50.0)),
        target_x=51.0,
        target_y=50.0,
    )

    prediction = classify_shot(context)

    assert prediction.primary_type is ShotType.UNKNOWN
    assert prediction.confidence == pytest.approx(
        prediction.probabilities[ShotType.UNKNOWN]
    )
    assert prediction.rejected_candidate in {
        ShotType.STRAIGHT_DRIVE,
        ShotType.CROSSCOURT_DRIVE,
    }
    assert prediction.margin < prediction.required_margin or prediction.confidence < prediction.required_probability
    assert_normalized(prediction.probabilities)

def test_active_calibration_reprojects_hitter_feet_instead_of_using_stale_floor() -> None:
    context = shot_context()
    stale = replace(
        context.hitter_observations[0],
        floor=FloorEstimate((5.9, 1.0), 0.01, "stale-cal", "old-lines"),
    )

    prediction = classify_shot(
        replace(context, hitter_observations=(stale,), calibration_revision="cal-1")
    )

    assert prediction.features.origin_court_m == pytest.approx((1.6, 9.2625))
    assert prediction.features.origin_side is not None


def test_shot_window_tolerances_filter_remote_evidence_and_bound_samples() -> None:
    context = shot_context()
    remote_ball = ball_point(900_000, 90.0, 10.0)
    remote_player = player(900_000, "B", feet_court=(0.2, 0.2), body_x=10.0)
    many_points = tuple(
        ball_point(
            index * 2_000,
            20.0 + index * 0.05,
            45.0 + math.sin(index / 10.0),
        )
        for index in range(300)
    )
    bounded = classify_shot(
        replace(
            context,
            ball_segment=TrackSegment("segment-1", many_points + (remote_ball,)),
            opponent_observations=context.opponent_observations + (remote_player,),
        )
    )
    no_hit_support = classify_shot(
        replace(
            context,
            ball_segment=replace(
                context.ball_segment,
                points=(
                    context.ball_segment.points[0],
                    ball_point(150_000, 30.0, 45.0),
                    *context.ball_segment.points[2:],
                ),
            ),
        )
    )

    assert len(bounded.sample_timestamps_us) <= MAX_SHOT_SAMPLES
    assert all(
        context.window_start_us <= timestamp <= context.window_end_us
        for timestamp in bounded.sample_timestamps_us
    )
    assert no_hit_support.primary_type is ShotType.UNKNOWN


def test_opponent_reach_is_finite_temporally_matched_image_geometry() -> None:
    prediction = classify_shot(shot_context())

    assert prediction.features.opponent_reach is not None
    assert 0.0 <= prediction.features.opponent_reach <= 1.0



def test_shot_window_can_end_at_an_explicit_next_racket_boundary() -> None:
    context = shot_context(
        post_contacts=(contact(200_000, ContactType.FRONT_WALL),)
    )
    boundary = contact(
        context.window_end_us,
        ContactType.RACKET,
        selected_hitter=Hitter.B,
    )

    prediction = classify_shot(
        replace(
            context,
            window_boundary=ShotWindowBoundary.NEXT_RACKET,
            boundary_contact=boundary,
        )
    )

    assert boundary.timestamp_us not in prediction.sample_timestamps_us
    assert all(
        timestamp <= context.window_end_us
        for timestamp in prediction.sample_timestamps_us
    )


def test_target_requires_ball_evidence_at_the_floor_contact_timestamp() -> None:
    context = shot_context()
    context = replace(
        context,
        ball_segment=replace(
            context.ball_segment,
            points=context.ball_segment.points[:-1],
        ),
    )

    prediction = classify_shot(context)

    assert prediction.primary_type is ShotType.UNKNOWN
    assert prediction.features.target_court_m is None


def test_shot_context_rejects_cross_segment_evidence_and_next_racket_contact() -> None:
    context = shot_context()
    mixed_segment = replace(
        context.ball_segment,
        points=context.ball_segment.points[:-1]
        + (replace(context.ball_segment.points[-1], segment_id="segment-2"),),
    )

    with pytest.raises(ValueError, match="segment"):
        replace(context, ball_segment=mixed_segment)
    with pytest.raises(ValueError, match="boundary"):
        replace(
            context,
            post_hit_contacts=(
                contact(200_000, ContactType.FRONT_WALL),
                contact(300_000, ContactType.RACKET, selected_hitter=Hitter.B),
            ),
        )


def test_hitter_and_stroke_side_require_unambiguous_player_evidence() -> None:
    clear = classify_shot(shot_context())
    ambiguous = classify_shot(shot_context(hitter_ambiguous=True))

    assert clear.hitter is Hitter.A
    assert clear.stroke_side in {StrokeSide.FOREHAND, StrokeSide.BACKHAND}
    assert ambiguous.hitter is Hitter.UNKNOWN
    assert ambiguous.stroke_side is StrokeSide.UNKNOWN


def trajectory_segment(
    *,
    segment_id: str = "segment-1",
    timestamps: tuple[int, ...] = (0, 80_000, 190_000, 330_000, 500_000),
    coordinates: tuple[tuple[float, float], ...] = (
        (10.0, 20.0),
        (18.0, 24.0),
        (29.0, 28.0),
        (43.0, 31.0),
        (60.0, 35.0),
    ),
) -> TrackSegment:
    return TrackSegment(
        segment_id,
        tuple(
            ball_point(timestamp, x, y, segment_id=segment_id)
            for timestamp, (x, y) in zip(timestamps, coordinates, strict=True)
        ),
    )


def test_trajectory_uses_timestamp_seconds_and_reports_image_speed_uncertainty() -> None:
    estimate = estimate_trajectory(trajectory_segment(), calibration())

    assert estimate.available
    assert estimate.timestamps_s == pytest.approx((0.0, 0.08, 0.19, 0.33, 0.5))
    assert len(estimate.fitted_image_points) == 5
    assert estimate.image_speed_px_s.minimum <= estimate.image_speed_px_s.median <= estimate.image_speed_px_s.maximum
    assert estimate.image_speed_normalized_s.minimum <= estimate.image_speed_normalized_s.median
    assert estimate.image_speed_px_s.uncertainty > 0.0
    assert estimate.image_speed_normalized_s.uncertainty > 0.0
    assert all(math.isfinite(value) for covariance in estimate.covariances_px2 for row in covariance for value in row)
    assert estimate.source_manifest_ids == ("source-sha256",)
    assert estimate.model_manifest_ids == ("ball-sha256",)
    assert estimate.covariance_model == "finite_difference_jacobian"
    assert math.isfinite(estimate.jacobian_condition_number)
    for fitted, observation in zip(
        estimate.fitted_image_points,
        trajectory_segment().points,
        strict=True,
    ):
        assert observation.x - 3.0 <= fitted[0] <= observation.x + 3.0
        assert observation.y - 3.0 <= fitted[1] <= observation.y + 3.0


def test_trajectory_rejects_duplicate_timestamps_and_cross_segment_points() -> None:
    duplicate = trajectory_segment(timestamps=(0, 80_000, 80_000, 330_000, 500_000))
    mixed = trajectory_segment()
    mixed = replace(
        mixed,
        points=mixed.points[:-1] + (replace(mixed.points[-1], segment_id="segment-2"),),
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        estimate_trajectory(duplicate, calibration())
    with pytest.raises(ValueError, match="segment"):
        estimate_trajectory(mixed, calibration())


def test_trajectory_does_not_bridge_large_segment_local_gap() -> None:
    segment = trajectory_segment(timestamps=(0, 50_000, 100_000, 900_000, 950_000))

    estimate = estimate_trajectory(segment, calibration())
    speed = estimate_speed(estimate)

    assert not estimate.available
    assert estimate.unavailability_reason == "segment_gap"
    assert isinstance(speed, UnavailableMeasurement)
    assert speed.reason == "segment_gap"


def test_ill_conditioned_spline_covariance_is_typed_unavailable() -> None:
    segment = trajectory_segment(timestamps=(0, 1, 2, 3, 4))

    estimate = estimate_trajectory(segment, calibration())

    assert not estimate.available
    assert estimate.unavailability_reason == "uncertainty_too_high"


def test_regular_three_hundred_millisecond_samples_use_one_continuity_mask() -> None:
    segment = trajectory_segment(
        timestamps=(0, 300_000, 600_000, 900_000, 1_200_000),
    )

    estimate = estimate_trajectory(segment, calibration())

    assert estimate.available
    assert estimate.image_speed_px_s.median > 0.0


def test_robust_fit_reduces_outlier_but_preserves_floor_contact_knot() -> None:
    segment = trajectory_segment(
        timestamps=(0, 100_000, 200_000, 300_000, 400_000, 500_000, 600_000),
        coordinates=(
            (10.0, 10.0),
            (20.0, 20.0),
            (30.0, 30.0),
            (40.0, 42.0),
            (50.0, 30.0),
            (60.0, -35.0),
            (70.0, 10.0),
        ),
    )

    unconstrained = estimate_trajectory(segment, calibration())
    constraint = TrajectoryContactConstraint(
        segment_id="segment-1",
        contact_id="floor-300000",
        timestamp_us=300_000,
        confidence=0.95,
    )
    estimate = estimate_trajectory(
        segment, calibration(), contact_constraints=(constraint,)
    )
    remote_constraint = replace(
        constraint,
        contact_id="floor-310000",
        timestamp_us=310_000,
    )
    low_confidence_constraint = replace(constraint, confidence=0.4)
    remote = estimate_trajectory(
        segment,
        calibration(),
        contact_constraints=(remote_constraint,),
    )
    low_confidence = estimate_trajectory(
        segment,
        calibration(),
        contact_constraints=(low_confidence_constraint,),
    )

    assert unconstrained.fitted_image_points[3] != pytest.approx((40.0, 42.0))
    assert estimate.fitted_image_points[3] == pytest.approx((40.0, 42.0))
    for actual, expected in zip(
        remote.fitted_image_points,
        unconstrained.fitted_image_points,
        strict=True,
    ):
        assert actual == pytest.approx(expected)
    for actual, expected in zip(
        low_confidence.fitted_image_points,
        unconstrained.fitted_image_points,
        strict=True,
    ):
        assert actual == pytest.approx(expected)
    assert 1.0 < abs(estimate.fitted_image_points[5][1] + 35.0) <= 3.0
    assert estimate.robust_iterations >= 2
    assert math.isfinite(estimate.residual_rms_px)


def test_trajectory_resampling_is_bounded_and_preserves_explicit_contact_knots() -> None:
    points = tuple(
        ball_point(index * 5_000, float(index), 20.0 + math.sin(index / 8.0))
        for index in range(300)
    )
    segment = TrackSegment("segment-1", points)
    constraint = TrajectoryContactConstraint(
        segment_id="segment-1",
        contact_id="front-750000",
        timestamp_us=750_000,
        confidence=0.9,
    )

    estimate = estimate_trajectory(
        segment, calibration(), contact_constraints=(constraint,)
    )

    assert len(estimate.timestamps_s) <= MAX_TRAJECTORY_SAMPLES
    assert estimate.source_timestamps_us[0] == 0
    assert estimate.source_timestamps_us[-1] == 1_495_000
    assert 750_000 in estimate.source_timestamps_us
    too_many_constraints = tuple(
        TrajectoryContactConstraint(
            segment_id="segment-1",
            contact_id=f"contact-{index}",
            timestamp_us=index * 5_000,
            confidence=0.9,
        )
        for index in range(1, MAX_TRAJECTORY_SAMPLES)
    )
    with pytest.raises(ValueError, match="bounded"):
        estimate_trajectory(
            segment,
            calibration(),
            contact_constraints=too_many_constraints,
        )


def test_floor_only_calibration_never_projects_airborne_path_or_claims_metric_speed() -> None:
    estimate = estimate_trajectory(trajectory_segment(), calibration())
    speed = estimate_speed(estimate)

    assert estimate.court_points_m == (None,) * len(estimate.timestamps_s)
    assert estimate.metric_unavailability_reason == "floor_only_calibration"
    assert isinstance(speed, UnavailableMeasurement)
    assert speed.reason == "floor_only_calibration"
    assert estimate.image_speed_px_s.median > 0.0


def test_metric_speed_has_no_caller_fabricated_positive_path() -> None:
    floor_only = estimate_trajectory(trajectory_segment(), calibration())
    uncalibrated = estimate_trajectory(
        trajectory_segment(), calibration(calibrated=False)
    )

    assert not hasattr(floor_only, "metric_points")
    assert not hasattr(floor_only, "metric_evidence")
    with pytest.raises(TypeError):
        replace(floor_only, metric_points=())
    floor_speed = estimate_speed(floor_only)
    uncalibrated_speed = estimate_speed(uncalibrated)
    assert isinstance(floor_speed, UnavailableMeasurement)
    assert floor_speed.reason == "floor_only_calibration"
    assert isinstance(uncalibrated_speed, UnavailableMeasurement)
    assert uncalibrated_speed.reason == "uncalibrated"


def terminal_context(
    *,
    interference: InterferenceKind | None = None,
    terminal_player: Hitter = Hitter.A,
    opponent_pressure: float | None = None,
    opponent_reach: float | None = None,
    player_displacement_m: float | None = None,
    shot_difficulty: float | None = None,
    rally_continued: bool | None = False,
    contacts: tuple[ContactEvent, ...] | None = None,
) -> TerminalContext:
    terminal_contacts = contacts or (
        contact(100_000, ContactType.FRONT_WALL),
    )
    return TerminalContext(
        contacts=terminal_contacts,
        ball_segment=trajectory_segment(),
        calibration=calibration(),
        terminal_player=terminal_player,
        interference=interference,
        opponent_pressure=opponent_pressure,
        opponent_reach=opponent_reach,
        player_displacement_m=player_displacement_m,
        shot_difficulty=shot_difficulty,
        rally_continued=rally_continued,
        window_start_us=0,
        window_end_us=500_000,
        terminal_contact_id=terminal_contacts[-1].contact_id,
        max_contact_tolerance_us=30_000,
    )


def test_floor_only_calibration_cannot_claim_tin_out_or_winner() -> None:
    prediction = classify_terminal_event(terminal_context())

    assert prediction.selected_outcome is ErrorOutcome.UNKNOWN
    assert prediction.objective is False
    assert prediction.review_required is True
    assert prediction.support_timestamps_us == ()
    assert_normalized(prediction.probabilities)


def test_not_up_requires_two_actual_supported_floor_contacts_after_last_racket() -> None:
    contacts = (
        contact(0, ContactType.RACKET, selected_hitter=Hitter.B),
        contact(100_000, ContactType.FLOOR),
        contact(200_000, ContactType.FLOOR),
    )
    prediction = classify_terminal_event(
        terminal_context(contacts=contacts)
    )
    low_second_bounce = classify_terminal_event(
        terminal_context(
            contacts=contacts[:-1]
            + (contact(200_000, ContactType.FLOOR, confidence=0.4),)
        )
    )

    assert prediction.selected_outcome is ErrorOutcome.NOT_UP
    assert prediction.objective is True
    assert prediction.review_required is False
    assert prediction.support_timestamps_us == (100_000, 200_000)
    assert low_second_bounce.selected_outcome is ErrorOutcome.UNKNOWN
    assert low_second_bounce.support_timestamps_us == ()


@pytest.mark.parametrize(
    ("interference", "expected"),
    (
        (InterferenceKind.LET, ErrorOutcome.LET_CANDIDATE),
        (InterferenceKind.STROKE, ErrorOutcome.STROKE_CANDIDATE),
    ),
)
def test_interference_outcomes_are_review_required_candidates(
    interference: InterferenceKind, expected: ErrorOutcome
) -> None:
    prediction = classify_terminal_event(
        terminal_context(interference=interference)
    )

    assert prediction.selected_outcome is expected
    assert prediction.review_required is True
    assert prediction.objective is False
    assert prediction.support_timestamps_us == (100_000,)


@pytest.mark.parametrize(
    ("pressure", "reach", "displacement", "difficulty", "expected"),
    (
        (0.9, 0.2, 2.5, 0.9, ErrorOutcome.FORCED_ERROR_CANDIDATE),
        (0.1, 0.9, 0.2, 0.2, ErrorOutcome.UNFORCED_ERROR_CANDIDATE),
    ),
)
def test_forced_and_unforced_are_review_candidates_not_referee_certainty(
    pressure: float,
    reach: float,
    displacement: float,
    difficulty: float,
    expected: ErrorOutcome,
) -> None:
    prediction = classify_terminal_event(
        terminal_context(
            opponent_pressure=pressure,
            opponent_reach=reach,
            player_displacement_m=displacement,
            shot_difficulty=difficulty,
            rally_continued=False,
        )
    )

    assert prediction.selected_outcome is expected
    assert prediction.review_required is True
    assert prediction.objective is False
    assert "candidate_requires_human_review" in prediction.reasons
    assert prediction.support_timestamps_us == (100_000,)


def test_subjective_error_requires_confident_same_segment_windowed_terminal_contact() -> None:
    low_confidence = contact(100_000, ContactType.FRONT_WALL, confidence=0.4)
    prediction = classify_terminal_event(
        terminal_context(
            contacts=(low_confidence,),
            opponent_pressure=0.9,
            opponent_reach=0.2,
            player_displacement_m=2.5,
            shot_difficulty=0.9,
            rally_continued=False,
        )
    )

    assert prediction.selected_outcome is ErrorOutcome.UNKNOWN
    assert prediction.support_timestamps_us == ()


@pytest.mark.parametrize("terminal_type", (ContactType.RACKET, ContactType.UNKNOWN))
def test_subjective_error_rejects_non_terminal_contact_types(
    terminal_type: ContactType,
) -> None:
    prediction = classify_terminal_event(
        terminal_context(
            contacts=(contact(100_000, terminal_type),),
            opponent_pressure=0.9,
            opponent_reach=0.2,
            player_displacement_m=2.5,
            shot_difficulty=0.9,
            rally_continued=False,
        )
    )

    assert prediction.selected_outcome is ErrorOutcome.UNKNOWN
    assert prediction.support_timestamps_us == ()


def test_terminal_context_rejects_cross_segment_evidence_and_consumes_only_used_contact() -> None:
    with pytest.raises(ValueError, match="segment"):
        terminal_context(
            contacts=(
                replace(
                    contact(100_000, ContactType.FRONT_WALL),
                    segment_id="segment-2",
                ),
            )
        )
    contacts = (
        contact(0, ContactType.RACKET, selected_hitter=Hitter.B),
        contact(50_000, ContactType.UNKNOWN),
        contact(100_000, ContactType.FLOOR),
        contact(200_000, ContactType.FLOOR),
    )
    prediction = classify_terminal_event(
        terminal_context(contacts=contacts)
    )

    assert prediction.selected_outcome is ErrorOutcome.NOT_UP
    assert prediction.support_timestamps_us == (100_000, 200_000)


def test_missing_subjective_error_evidence_stays_unknown() -> None:
    prediction = classify_terminal_event(terminal_context())

    assert prediction.selected_outcome is ErrorOutcome.UNKNOWN
    assert prediction.review_required is True
    assert prediction.player is Hitter.A
    assert_normalized(prediction.probabilities)
    assert prediction.support_timestamps_us == ()
