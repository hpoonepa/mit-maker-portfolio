"""Reviewable impact estimates for synchronized playback, not verified shot labels.

Use absolute velocity changes rather than turning angle alone: a slow flight
apex can turn through a large angle without a racket or surface impact.
"""
from __future__ import annotations

from bisect import bisect_left
import hashlib
import math
from typing import Any

import numpy as np

from squashvision.tracking_stats import FloorProjection, source_time


def _clean(row: dict[str, Any]) -> bool:
    return (row.get("evidence") == "observed" and row.get("visible") is True
            and not row.get("ambiguous", False) and float(row.get("probability") or 0) >= .5
            and int(row.get("candidate_count") or 0) == 1
            and all(isinstance(row.get(k), (int, float)) and math.isfinite(row[k]) for k in ("x", "y")))


def _distance_to_segment(point, a, b):
    delta = b - a
    fraction = float(np.clip(np.dot(point-a, delta) / max(float(np.dot(delta, delta)), 1), 0, 1))
    return float(np.linalg.norm(point - (a + fraction * delta)))


def _racket_support(row, nearby, diagonal):
    point = np.array([row["x"], row["y"]], dtype=float)
    scores = {}
    nearest_wrist = math.inf
    for player in nearby:
        if player.get("evidence") != "observed":
            continue
        xs, ys, confidence = (player.get(k) or [] for k in ("keypoints_x", "keypoints_y", "keypoints_confidence"))
        if min(len(xs), len(ys), len(confidence)) < 11:
            continue
        for elbow, wrist in ((7, 9), (8, 10)):
            if confidence[wrist] < .3:
                continue
            w = np.array([xs[wrist], ys[wrist]], dtype=float)
            nearest_wrist = min(nearest_wrist, float(np.linalg.norm(point-w)))
            endpoint = w
            if confidence[elbow] >= .3:
                arm = w - np.array([xs[elbow], ys[elbow]], dtype=float)
                # Racket head may extend beyond the detected wrist. This is a
                # reach estimate, not a racket detector or exact impact point.
                endpoint = w + 2.0 * arm
            distance = _distance_to_segment(point, w, endpoint)
            association = float(player.get("association_confidence") or 0)
            score = math.exp(-distance / max(1, .045 * diagonal)) * confidence[wrist] * association
            if player.get("ambiguous", False):
                score *= .4
            identifier = player.get("player_id")
            if identifier in ("A", "B"):
                scores[identifier] = max(scores.get(identifier, 0), score)
    ranked = sorted(scores.items(), key=lambda pair: -pair[1])
    if not ranked:
        return None, 0.0, nearest_wrist
    label, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    selected = label if score >= .35 and score - second >= .15 else None
    return selected, float(score), nearest_wrist


def _front_edge(projection: FloorProjection | None):
    if projection is None:
        return None
    try:
        inverse = np.linalg.inv(np.asarray(projection.matrix, dtype=float))
        points = []
        for x in (0, 6.4):
            p = inverse @ np.array([x, 0, 1])
            if abs(p[2]) < 1e-9:
                return None
            points.append((p[0] / p[2] / projection.scale_x, p[1] / p[2] / projection.scale_y))
        return points if points[1][0] > points[0][0] else None
    except (ValueError, np.linalg.LinAlgError):
        return None


def derive_playback_impacts(player_rows, ball_rows, floor_projection, *, calibration_revision=None):
    """Return separate racket, floor and front-wall estimates in source time.

    Court positions are returned only for plausible floor bounces. Wall
    fraction is a schematic horizontal image coordinate, never a 3D position.
    Every event remains review-required. Up to one missing source frame can be
    spanned by supporting observations; no missing image center is synthesized.
    """
    rows = sorted((row for row in ball_rows if _clean(row)), key=source_time)
    players = sorted(player_rows, key=source_time)
    player_times = [source_time(row) for row in players]
    front = _front_edge(floor_projection)
    candidates = []
    for index in range(2, len(rows)-2):
        window = rows[index-2:index+3]
        a, point, b = window[0], window[2], window[4]
        gaps = [source_time(y)-source_time(x) for x, y in zip(window, window[1:])]
        frames = [row.get("source_frame_index") for row in window]
        if (any(not 0 < gap <= 80_000 for gap in gaps)
                or any(not isinstance(frame, int) for frame in frames)
                or any(not 1 <= y-x <= 2 for x, y in zip(frames, frames[1:]))):
            continue
        width, height = int(point.get("source_width") or 0), int(point.get("source_height") or 0)
        if width <= 0 or height <= 0 or any((row.get("source_width"), row.get("source_height")) != (width, height) for row in window):
            continue
        diagonal = math.hypot(width, height)
        if any(math.hypot(y["x"]-x["x"], y["y"]-x["y"]) / (gap/1e6) > 3.5*diagonal
               for x, y, gap in zip(window, window[1:], gaps)):
            continue
        vin = np.array([point["x"]-a["x"], point["y"]-a["y"]]) / ((source_time(point)-source_time(a))/1e6)
        vout = np.array([b["x"]-point["x"], b["y"]-point["y"]]) / ((source_time(b)-source_time(point))/1e6)
        speeds = [float(np.linalg.norm(v)) for v in (vin, vout)]
        delta = float(np.linalg.norm(vout-vin))
        ratio = delta / max(*speeds, 1)
        # Reacquisition jumps are not physical impacts. Slow parabola apexes
        # fail the absolute-change threshold even when their angle reverses.
        if delta < .10*diagonal or ratio < .35 or max(speeds) > 3.5*diagonal:
            continue
        timestamp = source_time(point)
        start = bisect_left(player_times, timestamp-80_000)
        end = bisect_left(player_times, timestamp+80_001)
        hitter, hitter_score, wrist_distance = _racket_support(point, players[start:end], diagonal)
        floor = floor_projection.point(point["x"], point["y"]) if floor_projection else None
        kind, floor_position, wall_fraction = "unknown", None, None
        fraction = None
        if front:
            left, right = front
            fraction = (point["x"]-left[0])/(right[0]-left[0])
            front_y = left[1] + fraction*(right[1]-left[1])
            if (-.025 <= fraction <= 1.025 and point["y"] < front_y-.01*height
                    and vin[1] < -.10*diagonal and vout[1]-vin[1] > .10*diagonal):
                kind = "front_wall"
                wall_fraction = min(1.0, max(0.0, float(fraction)))
        if kind == "unknown":
            # A racket can add energy; a floor rebound generally reduces the
            # image-plane speed. Surface assignments remain estimates because
            # perspective and airborne height can change both quantities.
            if (speeds[1] > speeds[0]*1.25 and wrist_distance < .18*diagonal
                    and delta > .20*diagonal):
                kind = "racket"
            elif (floor is not None and vin[1] > .12*diagonal
                  and vout[1] < .4*vin[1] and speeds[1] <= speeds[0]*1.15):
                kind, floor_position = "floor", list(floor)
            elif hitter_score >= .65 and delta > .25*diagonal:
                kind = "racket"
        if kind != "racket":
            hitter, hitter_score = None, 0.0
        confidence = min(float(row["probability"]) for row in window) * min(1, ratio) * .8
        event = {
            "id": "impact-" + hashlib.sha256(f"{point.get('source_manifest_id','')}:{timestamp}:{kind}:v1".encode()).hexdigest()[:20],
            "timestamp_us": timestamp, "source_frame_index": point["source_frame_index"],
            "source_width": width, "source_height": height,
            "kind": kind, "confidence": float(confidence), "hitter": hitter,
            "hitter_confidence": hitter_score, "ball_image_position": [point["x"], point["y"]],
            "floor_position": floor_position, "wall_position": None,
            "wall_image_fraction": wall_fraction,
            "timing_uncertainty_us": max(timestamp-source_time(a), source_time(b)-timestamp),
            "position_reason": None if floor_position is not None else "image_position_only",
            "provenance": "motion_impact_estimate", "review_required": True,
            "_strength": delta,
        }
        candidates.append(event)
    # One visible impact may produce several neighboring acceleration peaks.
    selected = []
    for event in sorted(candidates, key=lambda item: -item["_strength"]):
        if not any(abs(event["timestamp_us"]-other["timestamp_us"]) < 160_000 for other in selected):
            selected.append(event)
    for event in selected:
        event.pop("_strength")
    return sorted(selected, key=lambda item: item["timestamp_us"])
