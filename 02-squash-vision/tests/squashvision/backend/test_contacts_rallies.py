from __future__ import annotations

from dataclasses import replace
import math
import time

import numpy as np
import pytest

from squashvision.calibration import CalibrationCapabilities, CalibrationResult
from squashvision.observations import (
    APPEARANCE_DIMENSION,
    BallCandidate,
    BallObservation,
    BoundingBox,
    EvidenceKind,
    Keypoint,
    PlayerObservation,
)
from squashvision.vision.contacts import (
    AudioImpact,
    AudioSampleRateError,
    AudioSamplesError,
    ContactEvent,
    ContactEvidence,
    ContactType,
    Hitter,
    detect_audio_impacts,
    fuse_contacts,
)
from squashvision.vision.rallies import (
    ActivitySample,
    RallyPrediction,
    segment_rallies,
)


def ball_point(
    timestamp_us: int,
    x: float,
    y: float,
    *,
    segment_id: str = "segment-0001",
    width: int = 100,
    height: int = 100,
    evidence: EvidenceKind = EvidenceKind.OBSERVED,
) -> BallObservation:
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
        source_timestamp_us=timestamp_us if evidence is EvidenceKind.OBSERVED else None,
        source_frame_index=frame_index if evidence is EvidenceKind.OBSERVED else None,
        source_width=width,
        source_height=height,
        x=x,
        y=y,
        probability=0.95,
        covariance=covariance,
        visible=True,
        candidate_count=1 if evidence is EvidenceKind.OBSERVED else 0,
        candidates=(candidate,) if evidence is EvidenceKind.OBSERVED else (),
        evidence=evidence,
        evidence_start_timestamp_us=(
            timestamp_us if evidence is EvidenceKind.OBSERVED else timestamp_us - 10_000
        ),
        evidence_end_timestamp_us=(
            timestamp_us if evidence is EvidenceKind.OBSERVED else timestamp_us + 10_000
        ),
        evidence_start_frame_index=(
            frame_index if evidence is EvidenceKind.OBSERVED else frame_index - 1
        ),
        evidence_end_frame_index=(
            frame_index if evidence is EvidenceKind.OBSERVED else frame_index + 1
        ),
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
    wrist: tuple[float, float],
    *,
    ambiguous: bool = False,
    association_confidence: float = 0.9,
) -> PlayerObservation:
    keypoints = [Keypoint(50.0, 50.0, 0.8) for _ in range(17)]
    keypoints[9] = Keypoint(*wrist, 0.95)
    keypoints[10] = Keypoint(*wrist, 0.95)
    return PlayerObservation(
        player_id=player_id,
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
        association_confidence=association_confidence,
        ambiguous=ambiguous,
        ambiguity_reason="identity_margin" if ambiguous else None,
        floor=None,
        source_manifest_id="source-sha256",
        model_manifest_id="pose-sha256",
    )


def calibration(confidence: float = 0.95) -> CalibrationResult:
    return CalibrationResult(
        calibrated=confidence >= 0.7,
        image_to_court=((0.064, 0.0, 0.0), (0.0, 0.0975, 0.0), (0.0, 0.0, 1.0)),
        court_to_image=((15.625, 0.0, 0.0), (0.0, 10.2564102564, 0.0), (0.0, 0.0, 1.0)),
        residuals_px=(1.0, 1.0, 1.0, 1.0),
        rms_error_px=1.0,
        max_error_px=1.0,
        inlier_mask=(True, True, True, True),
        condition_number=1.0,
        parameter_covariance=None,
        confidence=confidence,
        capabilities=CalibrationCapabilities(
            image_space=True,
            floor_position=confidence >= 0.7,
            movement_distance=confidence >= 0.7,
            speed=confidence >= 0.7,
        ),
        warnings=() if confidence >= 0.7 else ("low_calibration_confidence",),
    )


def bounce(
    center: tuple[float, float],
    incoming: tuple[float, float],
    outgoing: tuple[float, float],
    *,
    timestamp_us: int = 200_000,
    segment_id: str = "segment-0001",
    step_us: int = 50_000,
) -> tuple[BallObservation, ...]:
    cx, cy = center
    ix, iy = incoming
    ox, oy = outgoing
    return (
        ball_point(timestamp_us - step_us, cx - ix, cy - iy, segment_id=segment_id),
        ball_point(timestamp_us, cx, cy, segment_id=segment_id),
        ball_point(timestamp_us + step_us, cx + ox, cy + oy, segment_id=segment_id),
    )


def pulse_audio(
    *,
    sample_rate: int = 16_000,
    duration_s: float = 0.5,
    pulses: tuple[tuple[float, float], ...] = ((0.2, 1.0),),
    dtype: np.dtype[np.generic] = np.dtype(np.float64),
    stereo: bool = False,
) -> np.ndarray:
    samples = np.zeros(int(sample_rate * duration_s), dtype=np.float64)
    for timestamp_s, amplitude in pulses:
        index = round(timestamp_s * sample_rate)
        envelope = np.asarray([0.15, 0.6, 1.0, -0.7, -0.25]) * amplitude
        samples[index : index + len(envelope)] += envelope
    if np.issubdtype(dtype, np.integer):
        maximum = np.iinfo(dtype).max
        samples = np.rint(samples * maximum * 0.8).astype(dtype)
    else:
        samples = samples.astype(dtype)
    if stereo:
        samples = np.column_stack((samples, samples * 0.75))
    return samples


def test_audio_silence_and_muted_multichannel_preserve_empty_tuple_schema() -> None:
    assert detect_audio_impacts(np.zeros(8_000, dtype=np.float32), 16_000) == ()
    result = detect_audio_impacts(np.zeros((8_000, 2), dtype=np.int16), 16_000)
    assert result == ()
    assert isinstance(result, tuple)


def test_audio_rejects_invalid_rate_shape_dtype_and_nonfinite_samples() -> None:
    with pytest.raises(AudioSampleRateError, match="sample rate"):
        detect_audio_impacts(np.zeros(100), 2_000)
    with pytest.raises(AudioSamplesError, match="mono or multichannel"):
        detect_audio_impacts(np.zeros((2, 3, 4)), 16_000)
    with pytest.raises(AudioSamplesError, match="numeric"):
        detect_audio_impacts(np.asarray(["bad"], dtype=object), 16_000)
    with pytest.raises(AudioSamplesError, match="finite"):
        detect_audio_impacts(np.asarray([0.0, np.nan]), 16_000)


def test_audio_transient_timestamp_is_sample_derived_and_integer_stereo_normalizes() -> None:
    mono = detect_audio_impacts(pulse_audio(), 16_000)
    stereo_int = detect_audio_impacts(
        pulse_audio(dtype=np.dtype(np.int16), stereo=True), 16_000
    )
    assert len(mono) == len(stereo_int) == 1
    assert mono[0].timestamp_us == pytest.approx(200_000, abs=4_000)
    assert stereo_int[0].timestamp_us == pytest.approx(mono[0].timestamp_us, abs=2_000)
    assert mono[0].sample_index == round(mono[0].timestamp_us * 16_000 / 1_000_000)
    assert 0.0 < mono[0].strength <= 1.0
    assert 0.0 < mono[0].confidence <= 1.0


def test_audio_robust_noise_floor_finds_impact_without_promoting_stationary_noise() -> None:
    rng = np.random.default_rng(41)
    noise = rng.normal(0.0, 0.015, 16_000)
    noise[8_000:8_005] += np.asarray([0.1, 0.5, 0.9, -0.6, -0.2])
    impacts = detect_audio_impacts(noise, 16_000)
    assert len(impacts) == 1
    assert impacts[0].timestamp_us == pytest.approx(500_000, abs=6_000)
    assert detect_audio_impacts(rng.normal(0.0, 0.015, 16_000), 16_000) == ()


def test_audio_refractory_collapses_echo_to_strongest_and_counts_duplicates() -> None:
    impacts = detect_audio_impacts(
        pulse_audio(pulses=((0.20, 0.45), (0.225, 1.0), (0.34, 0.8))), 16_000
    )
    assert len(impacts) == 2
    assert impacts[0].timestamp_us == pytest.approx(225_000, abs=6_000)
    assert impacts[0].duplicate_count >= 2
    assert impacts[1].timestamp_us == pytest.approx(340_000, abs=6_000)
def test_audio_detects_qualifying_transients_at_both_signal_boundaries() -> None:
    samples = np.zeros(8_000, dtype=np.float64)
    envelope = np.asarray([0.15, 0.6, 1.0, -0.7, -0.25])
    samples[:5] = envelope
    samples[-5:] = envelope
    impacts = detect_audio_impacts(samples, 16_000)
    assert len(impacts) == 2
    assert impacts[0].timestamp_us < 10_000
    assert impacts[-1].timestamp_us > 490_000




def test_unmatched_audio_never_fabricates_a_contact() -> None:
    assert fuse_contacts((), (), detect_audio_impacts(pulse_audio(), 16_000), None) == ()


def test_visual_racket_contact_uses_audio_wrist_and_direction_explainably() -> None:
    track = bounce((50.0, 50.0), (12.0, 0.0), (-12.0, 1.0))
    audio = (AudioImpact(200_000, 3_200, 2_500, 0.9, 0.9, 1),)
    events = fuse_contacts(track, (player(200_000, "A", (50.0, 50.0)),), audio, None)
    assert len(events) == 1
    event = events[0]
    assert event.selected_type is ContactType.RACKET
    assert event.selected_hitter is Hitter.A
    assert not event.review_required
    assert event.evidence.audio > 0.0
    assert event.evidence.direction_change > 0.0
    assert event.evidence.wrist_proximity > 0.0
    assert event.supporting_ball_timestamps_us == (150_000, 200_000, 250_000)
    assert event.supporting_player_timestamps_us == (200_000,)


def test_audio_changes_confidence_but_never_contact_semantics_or_probabilities() -> None:
    track = bounce((50.0, 50.0), (12.0, 0.0), (-12.0, 1.0))
    with_audio = fuse_contacts(
        track,
        (player(200_000, "A", (50.0, 50.0)),),
        (AudioImpact(200_000, 3_200, 2_500, 0.9, 0.9, 1),),
        None,
    )[0]
    muted = fuse_contacts(track, (player(200_000, "A", (50.0, 50.0)),), (), None)[0]
    assert muted.selected_type is with_audio.selected_type is ContactType.RACKET
    assert muted.selected_hitter is with_audio.selected_hitter is Hitter.A
    assert muted.type_probabilities == with_audio.type_probabilities
    assert muted.review_reasons == with_audio.review_reasons
    assert muted.evidence.audio == 0.0
    assert with_audio.evidence.audio > 0.0
    assert muted.confidence < with_audio.confidence


def test_comparable_or_ambiguous_wrists_keep_hitter_unknown_and_review_required() -> None:
    track = bounce((50.0, 50.0), (12.0, 0.0), (-12.0, 1.0))
    events = fuse_contacts(
        track,
        (
            player(200_000, "A", (49.0, 50.0)),
            player(200_000, "B", (51.0, 50.0), ambiguous=True),
        ),
        (),
        None,
    )
    assert len(events) == 1
    assert events[0].selected_type is ContactType.RACKET
    assert events[0].selected_hitter is Hitter.UNKNOWN
    assert events[0].review_required
    assert "ambiguous_hitter" in events[0].review_reasons
    assert events[0].hitter_probabilities[Hitter.UNKNOWN] >= max(
        events[0].hitter_probabilities[Hitter.A],
        events[0].hitter_probabilities[Hitter.B],
    )


def test_floor_uses_projected_regulation_court_geometry_not_fixed_image_bands() -> None:
    compact = replace(
        calibration(),
        image_to_court=(
            (6.4 / 60.0, 0.0, -2.0),
            (0.0, 9.75 / 50.0, -3.9),
            (0.0, 0.0, 1.0),
        ),
        court_to_image=(
            (60.0 / 6.4, 0.0, 20.0),
            (0.0, 50.0 / 9.75, 20.0),
            (0.0, 0.0, 1.0),
        ),
    )
    track = bounce((50.0, 68.0), (0.0, 10.0), (0.0, -10.0))
    event = fuse_contacts(track, (), (), compact)[0]
    assert event.selected_type is ContactType.FLOOR
    assert event.evidence.topology_proximity > 0.0


@pytest.mark.parametrize(
    "track",
    [
        bounce((50.0, 8.0), (0.0, -10.0), (0.0, 10.0)),
        bounce((3.0, 50.0), (-10.0, 0.0), (10.0, 0.0)),
        bounce((50.0, 72.0), (0.0, 10.0), (0.0, -10.0)),
    ],
)
def test_floor_only_calibration_never_selects_unsupported_wall_types(
    track: tuple[BallObservation, ...],
) -> None:
    event = fuse_contacts(track, (), (), calibration())[0]
    assert event.selected_type is ContactType.UNKNOWN
    assert event.review_required
    assert "unsupported_wall_surface" in event.review_reasons
    assert max(
        event.type_probabilities[ContactType.FRONT_WALL],
        event.type_probabilities[ContactType.SIDE_WALL],
        event.type_probabilities[ContactType.BACK_WALL],
    ) < 0.3
    assert math.isclose(sum(event.type_probabilities.values()), 1.0, abs_tol=1.0e-9)


def test_floor_calibration_confidence_never_strengthens_unsupported_wall_claims() -> None:
    track = bounce((3.0, 50.0), (-10.0, 0.0), (10.0, 0.0))
    lower = fuse_contacts(track, (), (), calibration(0.75))[0]
    higher = fuse_contacts(track, (), (), calibration(0.95))[0]
    for wall in (
        ContactType.FRONT_WALL,
        ContactType.SIDE_WALL,
        ContactType.BACK_WALL,
    ):
        assert lower.type_probabilities[wall] == pytest.approx(
            higher.type_probabilities[wall]
        )




def test_weak_or_missing_calibration_does_not_claim_wall_or_floor_certainty() -> None:
    track = bounce((50.0, 94.0), (0.0, 10.0), (0.0, -10.0))
    missing = fuse_contacts(track, (), (), None)[0]
    weak = fuse_contacts(track, (), (), calibration(0.25))[0]
    assert missing.selected_type is ContactType.UNKNOWN
    assert weak.selected_type is ContactType.UNKNOWN
    assert missing.evidence.topology_proximity == 0.0
    assert weak.evidence.topology_proximity < 0.2
    assert missing.review_required and weak.review_required
    assert "weak_or_missing_calibration" in missing.review_reasons


def test_cross_segment_points_never_fabricate_direction_change() -> None:
    points = (
        ball_point(100_000, 20.0, 50.0, segment_id="segment-0001"),
        ball_point(150_000, 40.0, 50.0, segment_id="segment-0001"),
        ball_point(900_000, 20.0, 50.0, segment_id="segment-0002"),
    )
    assert fuse_contacts(points, (), (), calibration()) == ()
def test_duplicate_timestamps_and_missing_segment_ids_never_form_direction_events() -> None:
    duplicate = (
        ball_point(100_000, 20.0, 50.0),
        ball_point(100_000, 40.0, 50.0),
        ball_point(150_000, 20.0, 50.0),
    )
    missing_segment = tuple(replace(item, segment_id=None) for item in bounce(
        (50.0, 50.0), (12.0, 0.0), (-12.0, 0.0)
    ))
    assert fuse_contacts(duplicate, (), (), calibration()) == ()
    assert fuse_contacts(missing_segment, (), (), calibration()) == ()


def test_contact_clusters_never_merge_across_segments_and_retain_provenance() -> None:
    first = bounce(
        (50.0, 50.0), (10.0, 0.0), (-10.0, 0.0),
        timestamp_us=110_000, segment_id="segment-0001", step_us=10_000,
    )
    second = bounce(
        (50.0, 50.0), (10.0, 0.0), (-10.0, 0.0),
        timestamp_us=135_000, segment_id="segment-0002", step_us=10_000,
    )
    events = fuse_contacts(first + second, (), (), None)
    assert len(events) == 2
    assert [event.segment_id for event in events] == ["segment-0001", "segment-0002"]
    assert len({event.contact_id for event in events}) == 2
def test_interleaved_segments_cluster_independently_without_duplicate_contacts() -> None:
    segment_a = (
        ball_point(95_000, 30.0, 50.0, segment_id="segment-A"),
        ball_point(100_000, 50.0, 50.0, segment_id="segment-A"),
        ball_point(110_000, 30.0, 50.0, segment_id="segment-A"),
        ball_point(115_000, 50.0, 50.0, segment_id="segment-A"),
    )
    segment_b = (
        ball_point(101_000, 40.0, 50.0, segment_id="segment-B"),
        ball_point(105_000, 50.0, 50.0, segment_id="segment-B"),
        ball_point(109_000, 40.0, 50.0, segment_id="segment-B"),
    )
    events = fuse_contacts(
        segment_a + segment_b,
        (player(105_000, "A", (50.0, 50.0)),),
        (),
        None,
    )
    assert [(event.segment_id, event.timestamp_us) for event in events] == [
        ("segment-A", 100_000),
        ("segment-B", 105_000),
    ]
    segment_a_event = events[0]
    assert segment_a_event.selected_hitter is Hitter.A
    assert segment_a_event.supporting_ball_timestamps_us == (
        95_000,
        100_000,
        110_000,
        115_000,
    )




def test_cluster_extent_drives_player_audio_association_and_uncertainty() -> None:
    points = (
        ball_point(90_000, 30.0, 50.0),
        ball_point(110_000, 45.0, 50.0),
        ball_point(130_000, 50.0, 50.0),
        ball_point(150_000, 35.0, 50.0),
    )
    associated_player = player(70_000, "A", (45.0, 50.0))
    associated_audio = AudioImpact(90_000, 1_440, 4_000, 0.8, 0.8, 1)
    event = fuse_contacts(points, (associated_player,), (associated_audio,), None)[0]
    assert event.supporting_player_timestamps_us == (70_000,)
    assert event.evidence.audio > 0.0
    assert event.uncertainty_us >= 30_000




def test_nearby_direction_candidates_cluster_once_with_bounded_support() -> None:
    points = (
        ball_point(100_000, 30.0, 50.0),
        ball_point(120_000, 45.0, 50.0),
        ball_point(140_000, 50.0, 50.0),
        ball_point(160_000, 35.0, 50.0),
    )
    events = fuse_contacts(points, (player(140_000, "A", (50.0, 50.0)),), (), None)
    assert len(events) == 1
    assert len(events[0].supporting_ball_timestamps_us) <= 4


def test_contact_probabilities_evidence_ids_and_order_are_finite_and_deterministic() -> None:
    first_track = bounce((50.0, 50.0), (12.0, 0.0), (-12.0, 1.0), timestamp_us=200_000)
    second_track = bounce(
        (50.0, 94.0),
        (0.0, 10.0),
        (0.0, -10.0),
        timestamp_us=600_000,
        segment_id="segment-0002",
    )
    evidence = first_track + second_track
    players = (player(200_000, "A", (50.0, 50.0)),)
    one = fuse_contacts(evidence, players, (), calibration())
    two = fuse_contacts(evidence, players, (), calibration())
    assert one == two
    assert [item.contact_id for item in one] == [item.contact_id for item in two]
    assert [item.timestamp_us for item in one] == sorted(item.timestamp_us for item in one)
    assert len({item.contact_id for item in one}) == len(one)
    for item in one:
        assert math.isclose(sum(item.type_probabilities.values()), 1.0, abs_tol=1.0e-9)
        assert math.isclose(sum(item.hitter_probabilities.values()), 1.0, abs_tol=1.0e-9)
        assert 0.0 <= item.confidence <= 1.0
        assert all(math.isfinite(value) for value in item.evidence.values())


def manual_contact(timestamp_us: int, contact_type: ContactType, suffix: str = "") -> ContactEvent:
    type_probabilities = {kind: 0.02 for kind in ContactType}
    type_probabilities[contact_type] = 0.9
    total = sum(type_probabilities.values())
    type_probabilities = {kind: value / total for kind, value in type_probabilities.items()}
    return ContactEvent(
        segment_id="manual-segment",
        contact_id=f"contact-{timestamp_us}{suffix}",
        timestamp_us=timestamp_us,
        uncertainty_us=10_000,
        type_probabilities=type_probabilities,
        selected_type=contact_type,
        hitter_probabilities={Hitter.A: 0.8, Hitter.B: 0.05, Hitter.UNKNOWN: 0.15},
        selected_hitter=Hitter.A if contact_type is ContactType.RACKET else Hitter.UNKNOWN,
        confidence=0.85,
        review_required=False,
        review_reasons=(),
        evidence=ContactEvidence(
            audio=0.5,
            direction_change=0.8,
            speed_change=0.4,
            ball_uncertainty=0.1,
            ball_gap=0.0,
            wrist_proximity=0.8 if contact_type is ContactType.RACKET else 0.0,
            topology_proximity=0.8 if contact_type is not ContactType.RACKET else 0.0,
        ),
        supporting_ball_timestamps_us=(timestamp_us,),
        supporting_player_timestamps_us=(timestamp_us,),
    )


def activity(
    timestamp_us: int,
    *,
    visible: bool = True,
    ball_confidence: float = 0.9,
    player_activity: float = 0.8,
) -> ActivitySample:
    return ActivitySample(
        timestamp_us=timestamp_us,
        ball_visible=visible,
        ball_confidence=ball_confidence if visible else 0.0,
        player_activity=player_activity,
    )


def activated_rally_contacts(offset: int = 0) -> tuple[ContactEvent, ...]:
    return (
        manual_contact(offset + 1_000_000, ContactType.RACKET, "-serve"),
        manual_contact(offset + 1_300_000, ContactType.FRONT_WALL, "-front"),
        manual_contact(offset + 1_800_000, ContactType.RACKET, "-return"),
    )


def assert_valid_predictions(rallies: tuple[RallyPrediction, ...]) -> None:
    for rally in rallies:
        assert rally.start_us < rally.end_us
        assert rally.start.earliest_us <= rally.start_us <= rally.start.latest_us
        assert rally.end.earliest_us <= rally.end_us <= rally.end.latest_us
    assert all(
        previous.end_us <= current.start_us
        for previous, current in zip(rallies, rallies[1:])
    )


def test_lone_serve_candidate_expires_without_creating_a_rally() -> None:
    contacts = (manual_contact(1_000_000, ContactType.RACKET),)
    samples = (activity(1_100_000), activity(2_700_000, visible=False, player_activity=0.0))
    assert segment_rallies(contacts, samples) == ()


def test_serve_front_wall_confirmation_activates_and_terminal_floor_ends_rally() -> None:
    contacts = activated_rally_contacts() + (
        manual_contact(2_200_000, ContactType.FLOOR, "-terminal"),
    )
    rallies = segment_rallies(contacts, ())
    assert len(rallies) == 1
    rally = rallies[0]
    assert rally.start_us == 1_000_000
    assert rally.end_us == 2_200_000
    assert rally.supporting_contact_ids == tuple(item.contact_id for item in contacts)
    assert "serve_racket" in rally.start.evidence
    assert "terminal_floor" in rally.end.evidence
    assert_valid_predictions(rallies)


def test_ball_activity_sequence_confirms_serve_and_keeps_honest_open_end() -> None:
    contacts = (manual_contact(1_000_000, ContactType.RACKET, "-serve"),)
    samples = (
        activity(1_100_000),
        activity(1_300_000),
        activity(1_800_000),
    )
    rallies = segment_rallies(contacts, samples)
    assert len(rallies) == 1
    assert rallies[0].start_us == 1_000_000
    assert rallies[0].end_us == 1_800_000
    assert "ball_activity_confirmation" in rallies[0].start.evidence
    assert "end_of_observations" in rallies[0].end.evidence
    assert rallies[0].review_required
def test_duplicate_activity_timestamps_cannot_confirm_a_serve() -> None:
    contacts = (manual_contact(1_000_000, ContactType.RACKET, "-serve"),)
    duplicate = activity(1_100_000)
    assert segment_rallies(contacts, (duplicate, duplicate)) == ()




def test_active_rally_contact_dead_time_ends_before_next_serve() -> None:
    first = activated_rally_contacts()
    second = activated_rally_contacts(offset=5_000_000)
    contacts = first + second + (
        manual_contact(7_200_000, ContactType.FLOOR, "-terminal"),
    )
    rallies = segment_rallies(contacts, ())
    assert len(rallies) == 2
    assert rallies[0].end_us == first[-1].timestamp_us
    assert "contact_dead_time" in rallies[0].end.evidence
    assert rallies[1].start_us == second[0].timestamp_us
    assert_valid_predictions(rallies)
def test_explicit_terminal_contact_after_dead_time_refines_boundary_and_support() -> None:
    contacts = activated_rally_contacts() + (
        manual_contact(5_100_000, ContactType.FLOOR, "-late-terminal"),
    )
    rally = segment_rallies(contacts, ())[0]
    assert rally.end_us == 5_100_000
    assert "terminal_floor" in rally.end.evidence
    assert rally.supporting_contact_ids[-1] == contacts[-1].contact_id




def test_missing_ball_period_creates_honest_uncertain_end_boundary() -> None:
    contacts = activated_rally_contacts()
    samples = (
        activity(1_900_000),
        activity(2_100_000, visible=False, player_activity=0.05),
        activity(3_200_000, visible=False, player_activity=0.05),
    )
    rally = segment_rallies(contacts, samples)[0]
    assert rally.end.earliest_us == 2_100_000
    assert rally.end.latest_us == 3_200_000
    assert rally.review_required
    assert "missing_ball_end" in rally.review_reasons
    assert "extended_missing_ball" in rally.end.evidence


def test_muted_and_noisy_audio_contacts_have_identical_rally_state_semantics() -> None:
    base = activated_rally_contacts() + (
        manual_contact(2_200_000, ContactType.FLOOR, "-terminal"),
    )
    noisy = tuple(
        replace(
            item,
            evidence=replace(item.evidence, audio=0.05),
            confidence=max(0.0, item.confidence - 0.1),
        )
        for item in base
    )
    muted = tuple(replace(item, evidence=replace(item.evidence, audio=0.0)) for item in base)
    noisy_rally = segment_rallies(noisy, ())[0]
    muted_rally = segment_rallies(muted, ())[0]
    assert type(noisy_rally) is type(muted_rally)
    assert (noisy_rally.start_us, noisy_rally.end_us) == (
        muted_rally.start_us,
        muted_rally.end_us,
    )
    assert noisy_rally.start.evidence == muted_rally.start.evidence
    assert noisy_rally.end.evidence == muted_rally.end.evidence
def test_synced_and_muted_fusion_produce_identical_rally_transitions() -> None:
    first = bounce(
        (50.0, 50.0), (12.0, 0.0), (-12.0, 0.0),
        timestamp_us=1_000_000, segment_id="segment-serve",
    )
    second = bounce(
        (50.0, 50.0), (12.0, 0.0), (-12.0, 0.0),
        timestamp_us=1_400_000, segment_id="segment-return",
    )
    terminal = bounce(
        (50.0, 94.0), (0.0, 10.0), (0.0, -10.0),
        timestamp_us=2_000_000, segment_id="segment-floor",
    )
    ball = first + second + terminal
    players = (
        player(1_000_000, "A", (50.0, 50.0)),
        player(1_400_000, "B", (50.0, 50.0)),
    )
    synced_audio = (
        AudioImpact(1_000_000, 16_000, 2_500, 0.9, 0.9, 1),
        AudioImpact(1_400_000, 22_400, 2_500, 0.9, 0.9, 1),
        AudioImpact(2_000_000, 32_000, 2_500, 0.9, 0.9, 1),
    )
    synced_contacts = fuse_contacts(ball, players, synced_audio, calibration())
    muted_contacts = fuse_contacts(ball, players, (), calibration())
    assert [item.selected_type for item in synced_contacts] == [
        item.selected_type for item in muted_contacts
    ]
    synced = segment_rallies(synced_contacts, ())
    muted = segment_rallies(muted_contacts, ())
    assert [(item.start_us, item.end_us) for item in synced] == [
        (item.start_us, item.end_us) for item in muted
    ]
    assert [item.start.evidence for item in synced] == [
        item.start.evidence for item in muted
    ]
    assert [item.end.evidence for item in synced] == [
        item.end.evidence for item in muted
    ]




def test_rally_ids_are_deterministic_and_multiple_predictions_are_ordered_nonoverlapping() -> None:
    contacts = activated_rally_contacts() + (
        manual_contact(2_200_000, ContactType.FLOOR, "-one"),
    )
    contacts += activated_rally_contacts(offset=3_000_000) + (
        manual_contact(5_300_000, ContactType.FLOOR, "-two"),
    )
    first = segment_rallies(contacts, ())
    second = segment_rallies(tuple(reversed(contacts)), ())
    assert first == second
    assert len(first) == 2
    assert len({rally.rally_id for rally in first}) == 2
    assert_valid_predictions(first)


def test_large_activity_fixture_remains_linear_and_pending_state_bounded() -> None:
    contacts = activated_rally_contacts() + (
        manual_contact(7_000_000, ContactType.FLOOR, "-terminal"),
    )
    samples = tuple(activity(index * 1_000, player_activity=0.6) for index in range(8_000))
    started = time.monotonic()
    rallies = segment_rallies(contacts, samples)
    elapsed = time.monotonic() - started
    assert len(rallies) == 1
    assert elapsed < 2.0
    assert_valid_predictions(rallies)
