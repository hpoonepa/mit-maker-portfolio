"""Conservative original-pixel support for opt-in inverted TrackNet predictions.

This guard can only remove model observations. It never publishes a classical
blob center, synthesizes a detection, or assigns an impact/player identity.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import math
from typing import Iterable, Mapping, Sequence

import cv2
import numpy as np

from squashvision.observations import BallCandidate, BallObservation, EvidenceKind, Frame, PlayerObservation

CONTRAST_SUPPORT_POLICY_VERSION = "dark-motion-trajectory-v1"
_MAX_CANDIDATES = 8


def _player_dict(row):
    if isinstance(row, PlayerObservation):
        return {
            "player_id": row.player_id, "evidence": row.evidence.value,
            "source_frame_index": row.source_frame_index,
            **{f"box_{name}": getattr(row.box, name) for name in ("x1", "y1", "x2", "y2")},
            "feet_x": row.feet[0], "feet_y": row.feet[1],
            "keypoints_x": [p.x for p in row.keypoints],
            "keypoints_y": [p.y for p in row.keypoints],
            "keypoints_confidence": [p.confidence for p in row.keypoints],
        }
    return row


class DarkBallSupport:
    def __init__(self, background: np.ndarray,
                 player_rows: Sequence[PlayerObservation | Mapping[str, object]]) -> None:
        if background.dtype != np.uint8 or background.ndim != 3 or background.shape[2] != 3:
            raise ValueError("dark-ball support requires an original uint8 BGR background")
        self.background = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
        self.height, self.width = self.background.shape
        self.scale = math.hypot(self.width, self.height) / math.hypot(1280, 720)
        self.players = defaultdict(dict)
        for source in player_rows:
            row = _player_dict(source)
            if row.get("evidence") == "observed" and row.get("source_frame_index") is not None:
                self.players[int(row["source_frame_index"])][row.get("player_id")] = row
        self.glass_mask = np.ones(self.background.shape, dtype=np.uint8)
        lines = cv2.HoughLinesP(cv2.Canny(self.background, 70, 140), 1, np.pi / 180,
                              max(20, round(100 * self.scale)),
                              minLineLength=max(40, round(220 * self.scale)),
                              maxLineGap=max(5, round(30 * self.scale)))
        if lines is not None:
            for x1, y1, x2, y2 in lines.reshape(-1, 4):
                if abs(x2 - x1) <= 10 * self.scale and abs(y2 - y1) >= 220 * self.scale:
                    slope = (x2 - x1) / (y2 - y1)
                    top = round(x1 - y1 * slope)
                    bottom = round(x1 + (self.height - 1 - y1) * slope)
                    cv2.line(self.glass_mask, (top, 0), (bottom, self.height - 1),
                             0, max(2, round(64 * self.scale)))

    def _centers(self, frame: Frame, previous: np.ndarray, following: np.ndarray):
        poses = self.players.get(frame.source_frame_index, {})
        # No unmasked guessing when a pose gap hides a person or their racket.
        if set(poses) != {"A", "B"}:
            return []
        gray = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
        residual = self.background.astype(np.int16) - gray.astype(np.int16)
        local = cv2.GaussianBlur(gray, (0, 0), max(1, 3 * self.scale)).astype(np.int16) - gray
        motion = np.maximum(cv2.absdiff(gray, previous), cv2.absdiff(gray, following))
        mask = ((residual >= 20) & (local >= 10) & (motion >= 12) & (gray < 170)).astype(np.uint8)
        kernel = max(3, round(5 * self.scale) | 1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8)) * self.glass_mask
        pad = lambda n: max(1, round(n * self.scale))
        for row in poses.values():
            x1, y1, x2, y2 = [int(row[f"box_{name}"]) for name in ("x1", "y1", "x2", "y2")]
            cv2.rectangle(mask, (x1 - pad(10), y1 - pad(6)), (x2 + pad(10), y2 + pad(10)), 0, -1)
            cv2.ellipse(mask, (int(row["feet_x"]), int(row["feet_y"]) + pad(4)),
                        (max(pad(8), int((x2 - x1) * .65)), pad(10)), 0, 0, 360, 0, -1)
            cv2.rectangle(mask, (x1 - pad(20), y2 - pad(8)), (x2 + pad(20), y2 + pad(45)), 0, -1)
            xs, ys, confidence = [row[name] for name in ("keypoints_x", "keypoints_y", "keypoints_confidence")]
            if min(len(xs), len(ys), len(confidence)) < 11:
                return []
            for elbow, wrist in ((7, 9), (8, 10)):
                if confidence[wrist] >= .5:
                    cv2.circle(mask, (int(xs[wrist]), int(ys[wrist])),
                               max(pad(60), min(pad(180), int((y2 - y1) * .9))), 0, -1)
                if min(confidence[elbow], confidence[wrist]) >= .5:
                    a = np.array([xs[wrist], ys[wrist]])
                    b = a + 2 * (a - np.array([xs[elbow], ys[elbow]]))
                    cv2.line(mask, tuple(a.astype(int)), tuple(b.astype(int)), 0, pad(20))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        centers = []
        for label in range(1, count):
            x, y, w, h, area = map(int, stats[label])
            if (not max(2, 5 * self.scale**2) <= area <= 600 * self.scale**2
                    or max(w, h) > 50 * self.scale or min(w, h) > 24 * self.scale
                    or max(w, h) / max(1, min(w, h)) > 6):
                continue
            pixels = labels[y:y+h, x:x+w] == label
            weights = np.maximum(1, residual[y:y+h, x:x+w][pixels]).astype(float)
            if weights.mean() < 25 or weights.max() < 35:
                continue
            yy, xx = np.nonzero(pixels)
            center = (float(x + np.average(xx, weights=weights)), float(y + np.average(yy, weights=weights)))
            if 80 * self.scale <= center[1] <= self.height - 40 * self.scale:
                centers.append(center)
        # Texture/noise bursts are unavailable, rather than arbitrarily ranked.
        return centers if len(centers) <= _MAX_CANDIDATES else []

    def _supported_trajectories(self, measured):
        nodes, by_frame = [], defaultdict(list)
        for frame_index, centers in sorted(measured.items()):
            for center in centers:
                by_frame[frame_index].append(len(nodes))
                nodes.append((frame_index, np.asarray(center)))
        edges, ending = {}, defaultdict(list)
        for bid, (frame_index, bp) in enumerate(nodes):
            for delta in (1, 2):
                for aid in by_frame[frame_index - delta]:
                    velocity = (bp - nodes[aid][1]) / delta
                    speed = float(np.linalg.norm(velocity))
                    if not 1.5 * self.scale <= speed <= 140 * self.scale:
                        continue
                    best = (2., None)
                    for previous in ending[aid]:
                        score, _, prior_velocity = edges[previous]
                        error = float(np.linalg.norm(velocity - prior_velocity))
                        limit = max(10 * self.scale, .3 * speed)
                        if error <= limit and score + 1 - .4 * error / limit > best[0]:
                            best = (score + 1 - .4 * error / limit, previous)
                    key = (aid, bid)
                    edges[key] = (best[0], best[1], velocity)
                    ending[bid].append(key)
        supported, used = set(), set()
        for key, (score, previous, _) in sorted(edges.items(), key=lambda item: -item[1][0]):
            if score < 4.2:
                continue
            ids = [key[1], key[0]]
            while previous is not None:
                ids.append(previous[0])
                previous = edges[previous][1]
            ids.reverse()
            if len(ids) < 5:
                continue
            first, last = nodes[ids[0]], nodes[ids[-1]]
            span = last[0] - first[0]
            distance = float(np.linalg.norm(last[1] - first[1]))
            if distance < 30 * self.scale or distance / span < 3 * self.scale or len(set(ids) - used) < 3:
                continue
            used.update(ids)
            supported.update(ids)
        result = {}
        for frame_index, ids in by_frame.items():
            selected = [nodes[node][1] for node in ids if node in supported]
            if len(selected) == 1:
                result[frame_index] = selected[0]
        return result

    @staticmethod
    def _reject(row):
        return replace(row, x=None, y=None, covariance=None, probability=0., visible=False,
                       candidate_count=0, candidates=(), ambiguous=True,
                       ambiguity_reason="dark_motion_support_rejected")

    def filter_rows(self, rows: Sequence[BallObservation], frames: Iterable[Frame]) -> tuple[BallObservation, ...]:
        measured, times = {}, {}
        previous = current = None
        previous_gray = current_gray = None
        for following in frames:
            if following.image.shape != (*self.background.shape, 3) or following.image.dtype != np.uint8:
                raise ValueError("support frame dimensions must match original background")
            following_gray = cv2.cvtColor(following.image, cv2.COLOR_BGR2GRAY)
            if previous is not None and current is not None:
                contiguous = (current.source_frame_index == previous.source_frame_index + 1
                              and following.source_frame_index == current.source_frame_index + 1
                              and 0 < current.timestamp_us - previous.timestamp_us <= 100_000
                              and 0 < following.timestamp_us - current.timestamp_us <= 100_000)
                if contiguous:
                    measured[current.source_frame_index] = self._centers(current, previous_gray, following_gray)
                    times[current.source_frame_index] = current.timestamp_us
            previous, current = current, following
            previous_gray, current_gray = current_gray, following_gray
        supported = self._supported_trajectories(measured)
        result = []
        for row in rows:
            center = supported.get(row.source_frame_index)
            accepted = (row.evidence is EvidenceKind.OBSERVED and row.visible and not row.ambiguous
                        and row.source_width == self.width and row.source_height == self.height
                        and times.get(row.source_frame_index) == row.source_timestamp_us
                        and center is not None and math.dist((row.x, row.y), center) <= max(2, 8 * self.scale))
            if not accepted:
                result.append(self._reject(row) if row.visible or row.candidates else row)
                continue
            selected = min(row.candidates, key=lambda c: math.dist((row.x, row.y), (c.x, c.y))) if row.candidates else BallCandidate(
                row.x, row.y, row.probability, row.probability, 1, 1., row.covariance)
            # Repair receives only the independently supported selected center.
            if math.dist((row.x, row.y), (selected.x, selected.y)) > 1e-6:
                result.append(self._reject(row))
            else:
                result.append(replace(row, candidates=(selected,), candidate_count=1))
        return tuple(result)
