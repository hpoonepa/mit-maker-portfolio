from dataclasses import replace

import cv2
import numpy as np
import pytest

from squashvision.observations import BallCandidate, BallObservation, EvidenceKind, Frame
from squashvision.vision.ball.contrast_support import DarkBallSupport
from squashvision.vision.ball.tracker import repair_track


def observation(index, x, y=100.):
    timestamp = index * 33333
    candidate = BallCandidate(x, y, .8, .75, 12, .9, ((2., 0.), (0., 2.)))
    return BallObservation(timestamp, timestamp, index, 640, 360, x, y, .8,
                           candidate.covariance, True, 1, (candidate,), EvidenceKind.OBSERVED,
                           timestamp, timestamp, index, index, False, None, None,
                           "source", "inverted-model", "cpu", False)


def scene(count=10, *, second_ball=False, mask_racket=False):
    background = np.full((360, 640, 3), 210, np.uint8)
    frames, rows, players = [], [], []
    for index in range(count):
        image = background.copy()
        x = 200 + 8 * index
        cv2.circle(image, (x, 100), 3, (20, 20, 20), -1)
        if second_ball:
            cv2.circle(image, (x, 160), 3, (20, 20, 20), -1)
        frames.append(Frame(index * 33333, index, image))
        rows.append(observation(index, x + .6))
        for identifier, left in (("A", 20), ("B", 550)):
            xs, ys, confidence = [0.] * 17, [0.] * 17, [0.] * 17
            if mask_racket and identifier == "A":
                xs[9], ys[9], confidence[9] = x, 100, .9
            players.append({"player_id": identifier, "evidence": "observed", "source_frame_index": index,
                            "box_x1": left, "box_y1": 220, "box_x2": left + 40, "box_y2": 310,
                            "feet_x": left + 20, "feet_y": 310,
                            "keypoints_x": xs, "keypoints_y": ys, "keypoints_confidence": confidence})
    return background, frames, rows, players


def test_real_moving_pixels_keep_exact_model_center_and_source_provenance():
    background, frames, rows, players = scene()
    result = DarkBallSupport(background, players).filter_rows(rows, iter(frames))
    assert sum(row.visible for row in result) == 8
    assert not result[0].visible and not result[-1].visible
    for before, after in zip(rows[1:-1], result[1:-1]):
        assert after.x == before.x  # No snap to the classical centroid.
        assert after.source_timestamp_us == before.source_timestamp_us
        assert after.source_frame_index == before.source_frame_index
        assert after.model_manifest_id == "inverted-model"


def test_false_model_jump_is_removed_with_all_candidate_evidence():
    background, frames, rows, players = scene()
    rows[4] = observation(4, 480)
    result = DarkBallSupport(background, players).filter_rows(rows, iter(frames))
    rejected = result[4]
    assert not rejected.visible and rejected.x is None and rejected.probability == 0
    assert rejected.candidates == () and rejected.candidate_count == 0
    assert rejected.ambiguity_reason == "dark_motion_support_rejected"
    repaired = repair_track(result, None)
    assert not any(row.source_frame_index == 4 and row.evidence is EvidenceKind.OBSERVED
                   for segment in repaired.segments for row in segment.points)


def test_two_coherent_dark_objects_remain_ambiguous_not_arbitrarily_selected():
    background, frames, rows, players = scene(second_ball=True)
    result = DarkBallSupport(background, players).filter_rows(rows, frames)
    assert not any(row.visible for row in result)


def test_racket_reach_mask_cannot_be_published_as_ball():
    background, frames, rows, players = scene(mask_racket=True)
    assert not any(row.visible for row in DarkBallSupport(background, players).filter_rows(rows, frames))


def test_missing_exact_player_exclusion_fails_closed():
    background, frames, rows, players = scene()
    players = [row for row in players if row["player_id"] == "A"]
    assert not any(row.visible for row in DarkBallSupport(background, players).filter_rows(rows, frames))


def test_source_gap_does_not_become_an_observed_center():
    background, frames, rows, players = scene(16)
    result = DarkBallSupport(background, players).filter_rows(rows, (frame for frame in frames if frame.source_frame_index != 7))
    assert result[3].visible and result[11].visible
    assert all(not result[index].visible for index in (6, 7, 8))
    assert all(row.evidence is EvidenceKind.OBSERVED for row in result)


def test_frame_size_and_exact_source_timestamp_are_verified():
    background, frames, rows, players = scene()
    rows[4] = replace(rows[4], source_width=1280)
    rows[5] = replace(rows[5], timestamp_us=rows[5].timestamp_us + 1,
                      source_timestamp_us=rows[5].source_timestamp_us + 1,
                      evidence_start_timestamp_us=rows[5].timestamp_us + 1,
                      evidence_end_timestamp_us=rows[5].timestamp_us + 1)
    result = DarkBallSupport(background, players).filter_rows(rows, frames)
    assert not result[4].visible and not result[5].visible
    with pytest.raises(ValueError, match="dimensions"):
        DarkBallSupport(background, players).filter_rows(rows, [Frame(0, 0, np.zeros((720, 1280, 3), np.uint8))])


def test_stationary_background_mark_cannot_support_a_ball_trajectory():
    background, frames, rows, players = scene()
    cv2.circle(background, (240, 100), 4, (20, 20, 20), -1)
    static_frames = [Frame(frame.timestamp_us, frame.source_frame_index, background.copy()) for frame in frames]
    static_rows = [observation(index, 240) for index in range(len(rows))]
    assert not any(row.visible for row in DarkBallSupport(background, players).filter_rows(static_rows, static_frames))
