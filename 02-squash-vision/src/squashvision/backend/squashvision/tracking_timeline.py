"""Source-frame playback series: observed motion, causal interval speed, distinct impacts."""
from __future__ import annotations

from bisect import bisect_left
import math

from squashvision.schemas import PlaybackBallSpeed, PlaybackContact, PlaybackPlayerBaseline, PlaybackPlayerSample, TrackingTimelineDetail
from squashvision.tracking_stats import _player_point, court_scaled_image_speed_intervals, movement_series, source_time

MAX_ATTRIBUTED_SHOT_US = 3_000_000
MAX_ATTRIBUTION_BALL_GAP_US = 120_000


def attribute_shot_impacts(impacts, ball_rows):
    """Carry a supported racket identity forward only inside observed continuity."""
    continuity, previous, segment = {}, None, 0
    for row in sorted(ball_rows, key=source_time):
        point = (row.get("x"), row.get("y"))
        width, height, frame = row.get("source_width"), row.get("source_height"), row.get("source_frame_index")
        clean = (row.get("evidence") == "observed" and row.get("visible")
                 and not row.get("ambiguous", False) and float(row.get("probability") or 0) >= .5
                 and int(row.get("candidate_count") or 0) == 1 and isinstance(frame, int)
                 and isinstance(width, (int, float)) and isinstance(height, (int, float))
                 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point))
        if not clean or not (0 <= point[0] < width and 0 <= point[1] < height):
            continue
        timestamp = source_time(row)
        connected = False
        if previous is not None:
            dt = timestamp-source_time(previous)
            connected = (0 < dt <= MAX_ATTRIBUTION_BALL_GAP_US
                and frame > previous["source_frame_index"]
                and (width, height, row.get("source_manifest_id"), row.get("segment_id"))
                    == (previous["source_width"], previous["source_height"], previous.get("source_manifest_id"), previous.get("segment_id"))
                and math.hypot(point[0]-previous["x"], point[1]-previous["y"])/(dt/1_000_000) <= 3.5*math.hypot(width, height))
        if not connected:
            segment += 1
        continuity[timestamp] = segment
        previous = row

    attributed, owner = [], None
    for event in sorted(impacts, key=lambda item:(int(item["timestamp_us"]), str(item["id"]))):
        item = dict(event)
        item.update(shot_hitter=None, shot_contact_id=None, shot_hitter_confidence=0.)
        timestamp = int(item["timestamp_us"])
        kind = item.get("kind", item.get("surface", "unknown"))
        if kind == "racket":
            score = float(item.get("hitter_confidence") or 0)
            owner = item if item.get("hitter") in ("A", "B") and .35 <= score <= 1 else None
        elif kind == "unknown":
            owner = None
        elif owner is not None:
            age = timestamp-int(owner["timestamp_us"])
            origin_segment = continuity.get(int(owner["timestamp_us"]))
            if (not 0 <= age <= MAX_ATTRIBUTED_SHOT_US or origin_segment is None
                    or continuity.get(timestamp) != origin_segment):
                owner = None
        if owner is not None and kind in ("racket", "floor", "front_wall"):
            item.update(shot_hitter=owner["hitter"], shot_contact_id=owner["id"],
                        shot_hitter_confidence=float(owner["hitter_confidence"]))
        attributed.append(item)
    return attributed


def _nearby(rows, times, timestamp, tolerance_us=80_000):
    index = bisect_left(times, timestamp)
    nearest = min(rows[max(0, index-1):index+1], key=lambda r: abs(source_time(r)-timestamp), default=None)
    return nearest if nearest is not None and abs(source_time(nearest)-timestamp) <= tolerance_us else None


def _finite_pair(value):
    return tuple(float(v) for v in value) if isinstance(value, (tuple, list)) and len(value) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value) else None


def playback_contacts(data, impacts, start_us, end_us):
    ball = sorted(data["ball"], key=source_time)
    ball_times = [source_time(row) for row in ball]
    players = {p: sorted((r for r in data["players"] if r.get("player_id") == p), key=source_time) for p in ("A", "B")}
    player_times = {p:[source_time(r) for r in rows] for p, rows in players.items()}
    contacts = []
    for event in sorted(impacts, key=lambda e: e["timestamp_us"]):
        timestamp = int(event["timestamp_us"])
        if not start_us <= timestamp < end_us:
            continue
        kind = event.get("kind", event.get("surface", "unknown"))
        if kind not in ("racket", "floor", "front_wall", "unknown"):
            continue
        nearest = _nearby(ball, ball_times, timestamp)
        frame = event.get("source_frame_index", nearest.get("source_frame_index") if nearest else None)
        image = _finite_pair(event.get("ball_image_position"))
        if image is None and nearest and nearest.get("evidence") == "observed" and nearest.get("visible") and not nearest.get("ambiguous"):
            image = _finite_pair((nearest.get("x"), nearest.get("y")))
        hitter = event.get("hitter") if event.get("hitter") in ("A", "B") else None
        player = _nearby(players[hitter], player_times[hitter], timestamp) if hitter else None
        player_position = _player_point(player, data["projection"]) if player else None
        floor = _finite_pair(event.get("floor_position")) if kind == "floor" and data["projection"] else None
        wall = _finite_pair(event.get("wall_position")) if kind == "front_wall" else None
        # Surface coordinates are a different quantity from player feet.
        contacts.append(PlaybackContact(id=str(event["id"]), kind=kind, timestamp_us=timestamp,
            proxy_timestamp_us=data["proxy_by_frame"].get(frame), source_frame_index=frame,
            confidence=float(event.get("confidence", 0)), hitter=hitter,
            hitter_confidence=float(event.get("hitter_confidence", 0)), ball_image_position=image,
            shot_hitter=event.get("shot_hitter"), shot_contact_id=event.get("shot_contact_id"),
            shot_hitter_confidence=event.get("shot_hitter_confidence", 0),
            image_width=event.get("source_width", nearest.get("source_width") if nearest else None),
            image_height=event.get("source_height", nearest.get("source_height") if nearest else None),
            player_position=player_position, floor_position=floor, wall_position=wall,
            wall_image_fraction=event.get("wall_image_fraction") if kind == "front_wall" else None,
            timing_uncertainty_us=event.get("timing_uncertainty_us", 0),
            position_reason=event.get("position_reason"),
            provenance=str(event.get("provenance", "trajectory_reanalysis")),
            review_required=bool(event.get("review_required", True))))
    return contacts


def build_tracking_timeline(data, impacts, start_us: int, end_us: int) -> TrackingTimelineDetail:
    samples, baselines = [], []
    for player, series in movement_series(data["players"], data["projection"]).items():
        before = [s for s in series if source_time(s["row"]) < start_us]
        baseline = before[-1] if before else {}
        baselines.append(PlaybackPlayerBaseline(player_id=player,
            baseline_distance_m=baseline.get("cumulative_distance_m"),
            baseline_tracked_seconds=baseline.get("tracked_seconds", 0)))
        for sample in series:
            row, position = sample["row"], sample["position"]
            timestamp = source_time(row)
            if not start_us <= timestamp < end_us:
                continue
            frame = row.get("source_frame_index")
            samples.append(PlaybackPlayerSample(player_id=player, timestamp_us=timestamp,
                proxy_timestamp_us=data["proxy_by_frame"].get(frame),
                proxy_end_timestamp_us=data["proxy_end_by_frame"].get(frame), source_frame_index=frame,
                position=position, cumulative_distance_m=sample["cumulative_distance_m"],
                tracked_seconds=sample["tracked_seconds"],
                position_reason=None if position is not None else "calibration_unavailable" if data["projection"] is None else "player_observation_uncertain"))
    speeds = []
    for old, row, speed in court_scaled_image_speed_intervals(data["ball"], data["projection"]):
        timestamp = source_time(row)
        if not start_us <= timestamp < end_us:
            continue
        frame = row["source_frame_index"]
        speeds.append(PlaybackBallSpeed(timestamp_us=timestamp, interval_start_us=source_time(old),
            proxy_timestamp_us=data["proxy_by_frame"].get(frame),
            proxy_end_timestamp_us=data["proxy_end_by_frame"].get(frame),
            source_frame_index=frame, speed_mps=speed))
    # Fold the complete ordered history before applying the requested window.
    contacts = playback_contacts(data, attribute_shot_impacts(impacts, data["ball"]), start_us, end_us)
    landing_count = sum(c.kind == "floor" and c.floor_position is not None for c in contacts)
    return TrackingTimelineDetail(**{key:data[key] for key in ("report_revision", "prediction_revision", "calibration_revision", "calibration_available", "calibration_reason")},
        start_us=start_us, end_us=end_us, duration_us=data["end_us"]-data["start_us"],
        players=baselines, player_samples=sorted(samples, key=lambda s:(s.timestamp_us, s.player_id)),
        ball_speeds=speeds, ball_speed_method="court_scaled_image_speed", contacts=contacts, landing_count=landing_count,
        landing_reason=None if landing_count else "No supported floor-bounce locations in this time window.",
        limitations=[
            "Playback statistics reveal saved observations as their source frames are displayed; this is not live model inference.",
            "Cumulative movement includes accepted observed intervals only. A/B identities remain unverified; gaps and ambiguous samples add no distance.",
            "Current ball speed scales 2D image displacement by the projected court width at the interval's midpoint image Y, clamped to the visible floor extent. It is not actual airborne 3D speed; hide it outside the supplied exact proxy interval.",
            "Impact candidates are inferred from trajectory changes and available pose/calibration evidence; they are not verified contacts or a complete shot count.",
            "Ball floor/wall coordinates are surface-specific estimates. Player feet at contact are separate and must not be presented as ball impact locations.",
            "Surface-hit shot attribution inherits the last supported racket hitter only within 3 seconds of the same observed ball segment; unknown impacts or tracking gaps clear it. Attribution is estimated, not verified identity.",
        ])
