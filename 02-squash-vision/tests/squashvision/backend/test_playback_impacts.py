# Checks physical impact cues and keeps uncertain coordinates unavailable.
import pytest

from squashvision.playback_impacts import derive_playback_impacts
from squashvision.tracking_stats import FloorProjection

FLOOR = FloorProjection(((.01, 0, -3), (0, .01, -2), (0, 0, 1)))


def path(ys, **changes):
    return [dict(timestamp_us=i*40_000, source_timestamp_us=i*40_000,
                 source_frame_index=i, source_width=1280, source_height=720,
                 x=500., y=float(y), visible=True, evidence="observed",
                 ambiguous=False, probability=.95, candidate_count=1,
                 source_manifest_id="test", **changes) for i, y in enumerate(ys)]


def test_smooth_slow_flight_apex_is_not_an_impact():
    rows = path([400-(i-4)**2 for i in range(9)])
    assert derive_playback_impacts([], rows, FLOOR) == []


def test_floor_bounce_uses_ball_position_and_stays_estimated():
    rows = path([200, 250, 300, 350, 400, 375, 350, 325, 300])
    events = derive_playback_impacts([], rows, FLOOR)
    assert len(events) == 1
    impact = events[0]
    assert impact["kind"] == "floor"
    assert impact["timestamp_us"] == 160_000
    assert impact["ball_image_position"] == [500, 400]
    assert impact["floor_position"] == pytest.approx([2, 2])
    assert impact["hitter"] is None
    assert impact["review_required"] is True
    assert impact["provenance"] == "motion_impact_estimate"


def test_racket_strike_near_wrist_has_image_position_not_false_floor_impact():
    rows = path([450, 449, 448, 447, 446, 400, 354, 308, 262])
    players = [dict(timestamp_us=i*40_000, player_id="A", evidence="observed",
                    keypoints_x=[500.]*17, keypoints_y=[440.]*17,
                    keypoints_confidence=[.95]*17, association_confidence=.95,
                    ambiguous=False) for i in range(9)]
    event = derive_playback_impacts(players, rows, FLOOR)[0]
    assert event["kind"] == "racket"
    assert event["hitter"] == "A"
    assert event["floor_position"] is None
    assert event["ball_image_position"] == [500, 446]


def test_wall_hit_has_schematic_x_without_invented_world_height():
    rows = path([300, 270, 240, 210, 180, 200, 220, 240, 260])
    event = derive_playback_impacts([], rows, FLOOR)[0]
    assert event["kind"] == "front_wall"
    assert event["wall_image_fraction"] == pytest.approx(200/640)
    assert event["wall_position"] is None
    assert event["floor_position"] is None


def test_missing_calibration_cannot_produce_a_surface_location():
    rows = path([200, 250, 300, 350, 400, 375, 350, 325, 300])
    events = derive_playback_impacts([], rows, None)
    assert all(e["kind"] == "unknown" and e["floor_position"] is None for e in events)


def test_occlusion_and_reacquisition_jump_are_not_impacts():
    rows = path([200, 250, 300, 350, 400, 375, 350, 325, 300])
    assert derive_playback_impacts([], rows[:3]+rows[5:], FLOOR) == []
    spike = path([300, 305, 310, 315, 700, 325, 330, 335, 340])
    assert derive_playback_impacts([], spike, FLOOR) == []


def test_source_size_scaling_preserves_wall_fraction_and_floor_metres():
    rows = path([300, 270, 240, 210, 180, 200, 220, 240, 260])
    scaled = [dict(r, x=r["x"]*2, y=r["y"]*2, source_width=2560, source_height=1440) for r in rows]
    normal = derive_playback_impacts([], rows, FLOOR)[0]
    doubled = derive_playback_impacts([], scaled, FloorProjection(FLOOR.matrix, .5, .5))[0]
    assert normal["kind"] == doubled["kind"]
    assert normal["wall_image_fraction"] == pytest.approx(doubled["wall_image_fraction"])
