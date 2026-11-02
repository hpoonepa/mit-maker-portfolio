"""Descriptive estimates from published tracks; never a replacement for 3D measurement."""
from __future__ import annotations

import math
import statistics
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from typing import Any

from squashvision.schemas import ProjectedBallSpeedStats, TrackedContactStats, TrackedPlayerStats

MAX_PLAYER_GAP_US = 120_000
MOVEMENT_SAMPLE_US = 200_000
MAX_PLAYER_SPEED_MPS = 12.0
MAX_FLOOR_UNCERTAINTY_M = 0.75


@dataclass(frozen=True)
class FloorProjection:
    matrix: tuple[tuple[float, ...], ...]
    scale_x: float = 1.0
    scale_y: float = 1.0

    def point(self, x: object, y: object, uncertainty_px: float = 0.0) -> tuple[float, float] | None:
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        x, y = float(x) * self.scale_x, float(y) * self.scale_y
        h = self.matrix
        denominator = h[2][0] * x + h[2][1] * y + h[2][2]
        if not math.isfinite(denominator) or abs(denominator) < 1e-9:
            return None
        u = (h[0][0] * x + h[0][1] * y + h[0][2]) / denominator
        v = (h[1][0] * x + h[1][1] * y + h[1][2]) / denominator
        if not (0 <= u <= 6.4 and 0 <= v <= 9.75):
            return None
        # Conservative Frobenius bound on image uncertainty propagated through H.
        jacobian = ((h[0][0] - u * h[2][0]) / denominator * self.scale_x,
                    (h[0][1] - u * h[2][1]) / denominator * self.scale_y,
                    (h[1][0] - v * h[2][0]) / denominator * self.scale_x,
                    (h[1][1] - v * h[2][1]) / denominator * self.scale_y)
        if not math.isfinite(uncertainty_px) or uncertainty_px * math.hypot(*jacobian) > MAX_FLOOR_UNCERTAINTY_M:
            return None
        return u, v


def source_time(row: dict[str, Any]) -> int:
    value = row.get("source_timestamp_us")
    return int(row["timestamp_us"] if value is None else value)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def _player_point(row: dict[str, Any], projection: FloorProjection | None) -> tuple[float, float] | None:
    if (projection is None or row.get("evidence") != "observed" or row.get("ambiguous", False)
        or float(row.get("association_confidence") or 0) < 0.5):
        return None
    uncertainty = row.get("feet_uncertainty_px")
    if not isinstance(uncertainty, (int, float)) or uncertainty < 0:
        return None
    return projection.point(row.get("feet_x"), row.get("feet_y"), float(uncertainty))


def movement_series(rows: list[dict[str, Any]], projection: FloorProjection | None) -> dict[str, list[dict[str, Any]]]:
    """Cumulative totals change only at an accepted, fully observed interval endpoint."""
    result = {}
    for player in ("A", "B"):
        selected = sorted((r for r in rows if r.get("player_id") == player), key=source_time)
        runs, run, points = [], [], {}
        for row in selected:
            point = _player_point(row, projection)
            timestamp = source_time(row)
            key = (timestamp, row.get("source_frame_index"))
            points[key] = point
            if point is None or (run and not 0 < timestamp - source_time(run[-1][0]) <= MAX_PLAYER_GAP_US):
                if run:
                    runs.append(run)
                run = []
            if point is not None:
                run.append((row, point))
        if run:
            runs.append(run)
        increments = {}
        for run in runs:
            smooth = [(row, point if i in (0, len(run)-1) else
                       tuple(statistics.median(p[axis] for _, p in run[i-1:i+2])
                             for axis in (0, 1))) for i, (row, point) in enumerate(run)]
            previous = smooth[0]
            for index, current in enumerate(smooth[1:], start=1):
                elapsed_us = source_time(current[0])-source_time(previous[0])
                if elapsed_us < MOVEMENT_SAMPLE_US and index < len(smooth)-1:
                    continue
                dt = elapsed_us/1_000_000
                step = math.dist(current[1], previous[1])
                if dt > 0 and step/dt <= MAX_PLAYER_SPEED_MPS:
                    increments[(source_time(current[0]), current[0].get("source_frame_index"))] = (step, dt)
                previous = current
        distance, seconds, accepted = 0.0, 0.0, 0
        samples = []
        for row in selected:
            key = (source_time(row), row.get("source_frame_index"))
            if key in increments:
                step, dt = increments[key]
                distance += step
                seconds += dt
                accepted += 1
            samples.append({"row": row, "position": points[key],
                            "cumulative_distance_m": distance if accepted else None,
                            "tracked_seconds": seconds})
        result[player] = samples
    return result


def movement_stats(rows: list[dict[str, Any]], projection: FloorProjection | None,
                   duration_us: int, contact_counts: Counter[str]) -> list[TrackedPlayerStats]:
    result = []
    for player, samples in movement_series(rows, projection).items():
        latest = samples[-1] if samples else {}
        seconds = latest.get("tracked_seconds", 0.0)
        used = sum(sample["position"] is not None for sample in samples)
        result.append(TrackedPlayerStats(player_id=player,
            distance_m=latest.get("cumulative_distance_m"), tracked_seconds=seconds,
            coverage=min(1.0, seconds*1_000_000/duration_us) if duration_us else 0,
            observed_samples=sum(s["row"].get("evidence") == "observed" for s in samples),
            used_samples=used, excluded_samples=len(samples)-used, contact_count=contact_counts[player]))
    return result

def contact_stats(events: list[dict[str, Any]], rows: list[dict[str, Any]],
                  ball: list[dict[str, Any]], projection: FloorProjection | None,
                  proxy_by_frame: dict[int, int]) -> list[TrackedContactStats]:
    players = {p: sorted((r for r in rows if r.get("player_id") == p), key=source_time) for p in ("A", "B")}
    times = {p: [source_time(r) for r in players[p]] for p in players}
    balls = sorted(ball, key=source_time)
    ball_times = [source_time(r) for r in balls]
    result = []
    for event in sorted(events, key=lambda r: int(r["timestamp_us"])):
        if event.get("selected_type") != "racket":
            continue
        timestamp = int(event["timestamp_us"])
        hitter = event.get("selected_hitter")
        hitter = hitter if hitter in ("A", "B") else None
        position, reason, closest = None, "unknown_hitter", None
        if hitter:
            index = bisect_left(times[hitter], timestamp)
            nearby = players[hitter][max(0, index-1):index+1]
            closest = min(nearby, key=lambda r: abs(source_time(r)-timestamp), default=None)
            if projection is None:
                reason = "calibration_unavailable"
            elif closest is None or abs(source_time(closest)-timestamp) > 80_000:
                reason = "no_nearby_player_observation"
            else:
                position = _player_point(closest, projection)
                reason = None if position is not None else "player_position_uncertain"
        index = bisect_left(ball_times, timestamp)
        nearby_ball = balls[max(0, index-1):index+1]
        frame_row = min(nearby_ball, key=lambda r: abs(source_time(r)-timestamp), default=None)
        frame = (frame_row.get("source_frame_index") if frame_row is not None
                 and abs(source_time(frame_row)-timestamp) <= 80_000 else None)
        probabilities = event.get("hitter_probabilities") or {}
        result.append(TrackedContactStats(id=str(event["contact_id"]), timestamp_us=timestamp,
            proxy_timestamp_us=proxy_by_frame.get(frame), source_frame_index=frame,
            hitter=hitter, hitter_confidence=float(probabilities.get(hitter or "unknown", 0)),
            confidence=float(event.get("confidence", 0)), position=position, reason=reason,
            review_required=bool(event.get("review_required", True))))
    return result


def ball_speed_intervals(rows: list[dict[str, Any]], projection: FloorProjection | None) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    intervals = []
    previous = None
    for row in sorted(rows, key=source_time):
        valid = (projection is not None and row.get("evidence") == "observed"
                 and row.get("visible") and not row.get("ambiguous", False)
                 and float(row.get("probability") or 0) >= 0.5
                 and int(row.get("candidate_count") or 0) == 1)
        point = projection.point(row.get("x"), row.get("y")) if valid and projection else None
        if point is not None and previous is not None:
            old, old_point = previous
            dt = (source_time(row)-source_time(old))/1_000_000
            old_frame, frame = old.get("source_frame_index"), row.get("source_frame_index")
            if (isinstance(frame, int) and isinstance(old_frame, int) and frame == old_frame+1
                and 0 < dt <= 0.1 and old.get("segment_id") == row.get("segment_id")):
                intervals.append((old, row, math.dist(point, old_point)/dt))
        previous = (row, point) if point is not None else None
    if len(intervals) >= 8:
        values = [speed for _, _, speed in intervals]
        q1, q3 = percentile(values, .25), percentile(values, .75)
        if q3 > q1:
            intervals = [item for item in intervals if item[2] <= q3+3*(q3-q1)]
    return intervals


def ball_speed_stats(rows: list[dict[str, Any]], projection: FloorProjection | None,
                     duration_us: int) -> ProjectedBallSpeedStats:
    intervals = ball_speed_intervals(rows, projection)
    seconds = sum((source_time(row)-source_time(old))/1_000_000 for old, row, _ in intervals)
    values = [speed for _, _, speed in intervals]
    return ProjectedBallSpeedStats(median_mps=statistics.median(values) if values else None,
        p90_mps=percentile(values, .9) if values else None, sample_count=len(values),
        excluded_samples=max(0, len(rows)-1-len(values)), tracked_seconds=seconds,
        coverage=min(1.0, seconds*1_000_000/duration_us) if duration_us else 0,
        method="Adjacent observed source frames, confidence ≥0.5, one candidate, inside floor projection; median / 90th percentile after a 3-IQR upper-outlier filter.",
        reason=None if values else "calibration_unavailable" if projection is None else "no_clean_contiguous_ball_intervals")


def court_scaled_image_speed_intervals(rows: list[dict[str, Any]], projection: FloorProjection | None) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    """Apparent 2D speed using one local court-width scale, including airborne pixels.

    Image Y is clamped to the visible projected floor extent; points above the
    front floor use the front-court width instead of an extrapolated homography.
    This is a display approximation, never a reconstructed 3D speed.
    """
    if projection is None:
        return []
    import numpy as np
    try:
        inverse = np.linalg.inv(np.asarray(projection.matrix, dtype=float))
        corners = []
        for x, y in ((0., 0.), (6.4, 0.), (0., 9.75), (6.4, 9.75)):
            point = inverse @ np.array([x, y, 1.])
            if not np.isfinite(point).all() or abs(point[2]) < 1e-9:
                return []
            corners.append((point[0]/point[2]/projection.scale_x,
                            point[1]/point[2]/projection.scale_y))
    except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
        return []
    front_left, front_right, back_left, back_right = corners
    front_y = (front_left[1]+front_right[1])/2
    back_y = (back_left[1]+back_right[1])/2
    if abs(back_left[1]-front_left[1]) < 1e-9 or abs(back_right[1]-front_right[1]) < 1e-9:
        return []

    def scale_at(image_y, height):
        low, high = max(0., min(front_y, back_y)), min(float(height), max(front_y, back_y))
        if high <= low:
            return None
        y = min(high, max(low, image_y))
        left = front_left[0] + (y-front_left[1])*(back_left[0]-front_left[0])/(back_left[1]-front_left[1])
        right = front_right[0] + (y-front_right[1])*(back_right[0]-front_right[0])/(back_right[1]-front_right[1])
        width = abs(right-left)
        return 6.4/width if math.isfinite(width) and width > 1 else None

    intervals, previous = [], None
    for row in sorted(rows, key=source_time):
        width, height = row.get("source_width"), row.get("source_height")
        valid = (row.get("evidence") == "observed" and row.get("visible")
                 and not row.get("ambiguous", False) and float(row.get("probability") or 0) >= .5
                 and int(row.get("candidate_count") or 0) == 1
                 and isinstance(width, (int, float)) and isinstance(height, (int, float)))
        point = (row.get("x"), row.get("y"))
        valid = valid and all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)
        valid = valid and 0 <= point[0] < width and 0 <= point[1] < height
        if valid and previous is not None:
            old = previous
            old_frame, frame = old.get("source_frame_index"), row.get("source_frame_index")
            dt = (source_time(row)-source_time(old))/1_000_000
            if (isinstance(frame, int) and isinstance(old_frame, int) and frame == old_frame+1
                and 0 < dt <= .1 and old.get("segment_id") == row.get("segment_id")
                and old.get("source_manifest_id") == row.get("source_manifest_id")
                and (old.get("source_width"), old.get("source_height")) == (width, height)):
                # Match the continuity guard used by impact attribution. A
                # reacquisition jump is not a measurable flight interval.
                if math.hypot(row["x"]-old["x"], row["y"]-old["y"])/dt > 3.5*math.hypot(width, height):
                    previous = row
                    continue
                scale = scale_at((row["y"]+old["y"])/2, height)
                if scale is not None:
                    speed = math.hypot(row["x"]-old["x"], row["y"]-old["y"])/dt*scale
                    if math.isfinite(speed):
                        intervals.append((old, row, speed))
        previous = row if valid else None
    return intervals
