from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from squashvision.calibration import MAX_PLAYER_FLOOR_UNCERTAINTY_M
from squashvision.db import Database
from squashvision.models import (
    Correction,
    CorrectionStatus,
    Calibration,
    ErrorCandidate,
    Match,
    PlayerTrack,
    Rally,
    ReportRevision,
    Shot,
)
from squashvision.schemas import MatchReport, ReportSection

SECTION_NAMES = (
    "overview",
    "shots",
    "rallies",
    "movement",
    "errors",
    "trajectory",
    "head_to_head",
    "coaching",
    "review",
)
COURT_WIDTH_M = 6.40
COURT_LENGTH_M = 9.75
T_POINT = (3.20, 5.49)
MAX_MOVEMENT_GAP_US = 2_000_000
MAX_RECOVERY_US = 5_000_000


class ReportNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalState:
    shots: list[dict[str, Any]]
    rallies: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    tracks: list[dict[str, Any]]


def available(value: float | int) -> dict[str, Any]:
    return {"available": True, "value": value, "reason": None}


def unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "value": None, "reason": reason}

def _json_safe(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return {"unavailable": "nonfinite"}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _stable_hash(value: object) -> str:
    encoded = json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_payload(row: Shot) -> dict[str, Any]:
    speed_finite = row.speed_m_s is None or math.isfinite(row.speed_m_s)
    x_finite = row.contact_x_m is None or math.isfinite(row.contact_x_m)
    y_finite = row.contact_y_m is None or math.isfinite(row.contact_y_m)
    control_reason = (
        "nonfinite_coordinate"
        if not x_finite or not y_finite
        else "missing_coordinate"
        if row.contact_x_m is None or row.contact_y_m is None
        else None
    )
    image_x_finite = row.contact_x_px is None or math.isfinite(row.contact_x_px)
    image_y_finite = row.contact_y_px is None or math.isfinite(row.contact_y_px)
    image_coordinates_available = (
        row.contact_x_px is not None
        and row.contact_y_px is not None
        and image_x_finite
        and image_y_finite
        and row.contact_covariance is not None
        and row.contact_provenance in {"observed", "interpolated"}
        and row.contact_source_width is not None
        and row.contact_source_height is not None
    )
    return {
        "prediction_id": row.prediction_id,
        "frame_index": row.frame_index,
        "source_timestamp_us": row.source_timestamp_us,
        "source_evidence_ids": list(row.source_evidence_ids),
        "hitter": row.hitter.value if row.hitter is not None else None,
        "shot_type": row.kind.value,
        "is_volley": row.is_volley,
        "outcome": row.outcome.value,
        "contact_x_m": row.contact_x_m if x_finite else None,
        "contact_y_m": row.contact_y_m if y_finite else None,
        "control_point_unavailable_reason": control_reason,
        "contact_x_px": row.contact_x_px if image_coordinates_available else None,
        "contact_y_px": row.contact_y_px if image_coordinates_available else None,
        "contact_covariance": (
            row.contact_covariance if image_coordinates_available else None
        ),
        "contact_provenance": (
            row.contact_provenance if image_coordinates_available else None
        ),
        "contact_source_width": (
            row.contact_source_width if image_coordinates_available else None
        ),
        "contact_source_height": (
            row.contact_source_height if image_coordinates_available else None
        ),
        "image_point_unavailable_reason": (
            None
            if image_coordinates_available
            else "image_space_provenance_not_published"
        ),
        "review_required": row.review_required,
        "classification_payload": dict(row.classification_payload),
        "review_status": row.review_status,
        "evidence_provenance": row.evidence_provenance,
        "speed_m_s": row.speed_m_s if speed_finite else None,
        "speed_unavailable_reason": (
            row.speed_unavailable_reason
            if speed_finite
            else "nonfinite_speed"
        ),
        "rally_id": row.rally.prediction_id if row.rally is not None else None,
    }


def _rally_payload(row: Rally) -> dict[str, Any]:
    return {
        "prediction_id": row.prediction_id,
        "ordinal": row.ordinal,
        "start_frame": row.start_frame,
        "end_frame": row.end_frame,
        "start_timestamp_us": row.start_timestamp_us,
        "end_timestamp_us": row.end_timestamp_us,
        "timing_available": row.timing_available,
        "source_evidence_ids": list(row.source_evidence_ids),
        "review_required": row.review_required,
        "review_reasons": list(row.review_reasons),
        "review_status": row.review_status,
        "evidence_provenance": row.evidence_provenance,
    }


def _error_payload(row: ErrorCandidate) -> dict[str, Any]:
    return {
        "kind": row.kind.value,
        "prediction_id": row.prediction_id,
        "target_type": row.target_type,
        "target_prediction_id": row.target_prediction_id,
        "source_timestamp_us": row.source_timestamp_us,
        "source_evidence_ids": list(row.source_evidence_ids),
        "review_status": row.review_status,
        "evidence_payload": dict(row.evidence_payload),
    }


def _fold_state(session: Session, match: Match, prediction_revision: int, revision: int) -> CanonicalState:
    shot_rows = session.scalars(
        select(Shot)
        .where(Shot.match_id == match.id, Shot.prediction_revision == prediction_revision)
        .order_by(Shot.source_timestamp_us, Shot.prediction_id)
    ).all()
    rally_rows = session.scalars(
        select(Rally)
        .where(Rally.match_id == match.id, Rally.prediction_revision == prediction_revision)
        .order_by(Rally.start_timestamp_us.is_(None), Rally.start_timestamp_us, Rally.prediction_id)
    ).all()
    error_rows = session.scalars(
        select(ErrorCandidate)
        .where(
            ErrorCandidate.match_id == match.id,
            ErrorCandidate.prediction_revision == prediction_revision,
        )
        .order_by(ErrorCandidate.source_timestamp_us, ErrorCandidate.prediction_id)
    ).all()
    track_rows = session.scalars(
        select(PlayerTrack)
        .where(
            PlayerTrack.match_id == match.id,
            PlayerTrack.prediction_revision == prediction_revision,
        )
        .order_by(PlayerTrack.slot, PlayerTrack.source_timestamp_us, PlayerTrack.prediction_id)
    ).all()
    shots = [_row_payload(row) for row in shot_rows]
    rallies = [_rally_payload(row) for row in rally_rows]
    errors = [_error_payload(row) for row in error_rows]
    tracks = [
        {
            "prediction_id": row.prediction_id,
            "slot": row.slot.value,
            "source_timestamp_us": row.source_timestamp_us,
            "source_evidence_ids": list(row.source_evidence_ids),
            "x_m": row.x_m,
            "y_m": row.y_m,
            "observed": row.observed,
            "calibration_revision": row.calibration_revision,
            "position_covariance": row.position_covariance,
            "position_uncertainty_m": row.position_uncertainty_m,
            "position_provenance": row.position_provenance,
            "position_unavailable_reason": row.position_unavailable_reason,
        }
        for row in track_rows
    ]
    corrections = session.scalars(
        select(Correction)
        .where(
            Correction.match_id == match.id,
            Correction.prediction_revision == prediction_revision,
            Correction.status == CorrectionStatus.ACTIVE,
            Correction.expected_report_revision < revision,
        )
        .order_by(Correction.id)
    ).all()
    for correction in corrections:
        _fold_correction(shots, rallies, errors, correction)
    _assign_shots_to_rallies(shots, rallies)
    return CanonicalState(shots, rallies, errors, tracks)


def canonical_state_for_report(
    session: Session,
    match: Match,
    report: ReportRevision,
) -> CanonicalState:
    if report.match_id != match.id:
        raise ValueError("report does not belong to match")
    return _fold_state(
        session,
        match,
        report.prediction_revision,
        report.revision,
    )


def _fold_correction(
    shots: list[dict[str, Any]],
    rallies: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    correction: Correction,
) -> None:
    target = next(
        (
            item
            for item in (shots if correction.target_type == "shot" else errors if correction.target_type == "error_candidate" else rallies)
            if item["prediction_id"] == correction.target_id
        ),
        None,
    )
    review_entity_type = correction.review_entity_type
    review_entity_id = correction.review_entity_id
    review_decision = correction.review_decision
    if (
        review_entity_type is None
        and correction.command_type in {"accept", "reject"}
    ):
        review_entity_type = correction.target_type
        review_entity_id = correction.target_id
        review_decision = (
            "accepted" if correction.command_type == "accept" else "rejected"
        )
    if review_entity_type is not None and review_entity_id is not None:
        review_rows = (
            shots
            if review_entity_type == "shot"
            else rallies
            if review_entity_type == "rally"
            else errors
        )
        review_entity = next(
            (
                item
                for item in review_rows
                if item["prediction_id"] == review_entity_id
            ),
            None,
        )
        if review_entity is not None:
            review_entity["review_status"] = review_decision or "accepted"
    if correction.command_type in {"accept", "reject"}:
        if target is not None:
            target["review_status"] = "accepted" if correction.command_type == "accept" else "rejected"
        return
    if correction.command_type == "split_rally":
        if target is None or not target.get("timing_available"):
            return
        split_us = int(correction.after_payload["split_timestamp_us"])
        original_end = int(target["end_timestamp_us"])
        original_end_frame = int(target["end_frame"])
        target["end_timestamp_us"] = split_us
        ratio = (split_us - int(target["start_timestamp_us"])) / (
            original_end - int(target["start_timestamp_us"])
        )
        split_frame = int(target["start_frame"]) + round(
            (original_end_frame - int(target["start_frame"])) * ratio
        )
        target["end_frame"] = split_frame
        rallies.append(
            {
                **target,
                "prediction_id": (
                    f"{target['prediction_id']}:split:{correction.public_id}"
                ),
                "ordinal": int(target["ordinal"]) + 1,
                "start_timestamp_us": split_us,
                "end_timestamp_us": original_end,
                "start_frame": split_frame,
                "end_frame": original_end_frame,
                "review_required": False,
                "review_status": "not_required",
                "review_reasons": [],
            }
        )
        rallies.sort(
            key=lambda item: (
                item["start_timestamp_us"] is None,
                item["start_timestamp_us"] or 0,
                item["prediction_id"],
            )
        )
        for ordinal, item in enumerate(rallies, 1):
            item["ordinal"] = ordinal
        return
    if correction.command_type == "merge_rallies":
        other_id = correction.after_payload["other_target_id"]
        other = next((item for item in rallies if item["prediction_id"] == other_id), None)
        if target is None or other is None:
            return
        target["start_timestamp_us"] = min(target["start_timestamp_us"], other["start_timestamp_us"])
        target["end_timestamp_us"] = max(target["end_timestamp_us"], other["end_timestamp_us"])
        target["start_frame"] = min(target["start_frame"], other["start_frame"])
        target["end_frame"] = max(target["end_frame"], other["end_frame"])
        rallies.remove(other)
        rallies.sort(
            key=lambda item: (
                item["start_timestamp_us"] is None,
                item["start_timestamp_us"] or 0,
                item["prediction_id"],
            )
        )
        for ordinal, item in enumerate(rallies, 1):
            item["ordinal"] = ordinal
        return
    if target is None:
        return
    mapping = {
        "change_hitter": ("hitter", "hitter"),
        "change_shot_type": ("shot_type", "shot_type"),
        "adjust_contact_time": ("source_timestamp_us", "source_timestamp_us"),
        "change_outcome": ("outcome", "outcome"),
    }
    if correction.command_type in mapping:
        destination, source = mapping[correction.command_type]
        target[destination] = correction.after_payload[source]
    elif correction.command_type == "ball_control_point":
        target["contact_x_m"] = correction.after_payload["x_m"]
        target["contact_y_m"] = correction.after_payload["y_m"]
        target["control_point_unavailable_reason"] = None


def _assign_shots_to_rallies(shots: list[dict[str, Any]], rallies: list[dict[str, Any]]) -> None:
    timed = [
        rally
        for rally in rallies
        if rally.get("timing_available")
        and rally["start_timestamp_us"] is not None
        and rally["end_timestamp_us"] is not None
    ]
    for shot in shots:
        candidates = [
            rally
            for rally in timed
            if rally["start_timestamp_us"] <= shot["source_timestamp_us"] < rally["end_timestamp_us"]
        ]
        shot["rally_id"] = candidates[0]["prediction_id"] if len(candidates) == 1 else None

def _shot_section(state: CanonicalState) -> tuple[dict[str, Any], list[str]]:
    players: dict[str, Any] = {}
    for player in ("near", "far", "unknown"):
        player_shots = sorted(
            (
                shot
                for shot in state.shots
                if (shot["hitter"] or "unknown") == player
            ),
            key=lambda shot: (shot["source_timestamp_us"], shot["prediction_id"]),
        )
        type_counts = Counter(shot["shot_type"] for shot in player_shots)
        outcome_counts = Counter(shot["outcome"] for shot in player_shots)
        shot_sides = {
            shot["prediction_id"]: (
                "unknown"
                if shot["contact_x_m"] is None
                else "left"
                if shot["contact_x_m"] < COURT_WIDTH_M / 2
                else "right"
            )
            for shot in player_shots
        }
        side_counts = Counter(shot_sides.values())
        players[player] = {
            "count": len(player_shots),
            "types": {
                kind: {
                    "count": count,
                    "share": count / len(player_shots) if player_shots else None,
                    "representative_event_id": next(
                        shot["prediction_id"]
                        for shot in player_shots
                        if shot["shot_type"] == kind
                    ),
                }
                for kind, count in sorted(type_counts.items())
            },
            "outcomes": {
                outcome: {
                    "count": count,
                    "representative_event_id": next(
                        shot["prediction_id"]
                        for shot in player_shots
                        if shot["outcome"] == outcome
                    ),
                }
                for outcome, count in sorted(outcome_counts.items())
            },
            "sides": {
                side: {
                    "count": count,
                    "representative_event_id": next(
                        shot["prediction_id"]
                        for shot in player_shots
                        if shot_sides[shot["prediction_id"]] == side
                    ),
                }
                for side, count in sorted(side_counts.items())
            },
            "volleys": sum(bool(shot["is_volley"]) for shot in player_shots),
            "volley_representative_event_id": next(
                (
                    shot["prediction_id"]
                    for shot in player_shots
                    if bool(shot["is_volley"])
                ),
                None,
            ),
        }
    evidence = sorted(
        {item for shot in state.shots for item in shot["source_evidence_ids"]}
    )
    return {
        "total_count": len(state.shots),
        "players": players,
        "aggregate_contract": "complete",
    }, evidence


def _rally_section(state: CanonicalState) -> tuple[dict[str, Any], list[str]]:
    items = sorted(
        state.rallies,
        key=lambda item: (
            item["start_timestamp_us"] is None,
            item["start_timestamp_us"] or 0,
            item["prediction_id"],
        ),
    )
    rendered: list[dict[str, Any]] = []
    for item in items:
        rally_shots = sorted(
            (
                shot
                for shot in state.shots
                if shot["rally_id"] == item["prediction_id"]
            ),
            key=lambda shot: (shot["source_timestamp_us"], shot["prediction_id"]),
        )
        terminal = rally_shots[-1] if rally_shots else None
        rendered.append(
            {
                **item,
                "shot_ids": [shot["prediction_id"] for shot in rally_shots],
                "outcome": terminal["outcome"] if terminal is not None else None,
                "terminal_shot_id": (
                    terminal["prediction_id"] if terminal is not None else None
                ),
                "representative_event_id": (
                    terminal["prediction_id"]
                    if terminal is not None
                    else item["prediction_id"]
                ),
                "representative_timestamp_us": (
                    terminal["source_timestamp_us"]
                    if terminal is not None
                    else item["start_timestamp_us"]
                ),
            }
        )
    evidence = sorted(
        {item for rally in items for item in rally["source_evidence_ids"]}
    )
    return {
        "items": rendered,
        "timing_unavailable_count": sum(
            not item.get("timing_available") for item in items
        ),
    }, evidence


def _overview_section(state: CanonicalState) -> tuple[dict[str, Any], list[str]]:
    rallies = sorted(
        (
            item
            for item in state.rallies
            if item.get("timing_available")
            and item["start_timestamp_us"] is not None
            and item["end_timestamp_us"] is not None
        ),
        key=lambda item: item["start_timestamp_us"],
    )
    durations = [
        (item["end_timestamp_us"] - item["start_timestamp_us"]) / 1_000_000
        for item in rallies
    ]
    active = sum(durations)
    rest = sum(
        max(
            0,
            later["start_timestamp_us"] - earlier["end_timestamp_us"],
        )
        / 1_000_000
        for earlier, later in zip(rallies, rallies[1:])
    )
    accepted = sum(item["review_status"] == "accepted" for item in state.errors)
    reviewed = sum(item["review_status"] != "pending" for item in state.errors)
    quality_evidence = {
        item
        for collection in (state.shots, state.rallies, state.errors, state.tracks)
        for row in collection
        for item in row.get("source_evidence_ids", [])
    }
    payload = {
        "rally_count": len(state.rallies),
        "timed_rally_count": len(rallies),
        "active_duration_s": active if rallies else None,
        "rest_duration_s": rest if rallies else None,
        "work_rest_ratio": (
            available(active / rest)
            if rest > 0
            else unavailable(
                "no_rest_duration"
                if not state.rallies or rallies
                else "rally_timing_unavailable"
            )
        ),
        "shot_count": len(state.shots),
        "winner_count": sum(
            shot["outcome"] == "winner" for shot in state.shots
        ),
        "reviewed_error_count": accepted,
        "longest_rally_s": max(durations) if durations else None,
        "average_rally_s": statistics.fmean(durations) if durations else None,
        "review_completion": (
            available(reviewed / len(state.errors))
            if state.errors
            else unavailable("no_candidates")
        ),
        "evidence_quality": available(
            len(quality_evidence)
            / max(
                1,
                len(state.shots)
                + len(state.rallies)
                + len(state.errors)
                + len(state.tracks),
            )
        ),
    }
    return payload, sorted(quality_evidence)


def _movement_section(
    state: CanonicalState, active_revision: int | None
) -> tuple[dict[str, Any], list[str]]:
    exclusions: Counter[str] = Counter()
    observed: list[dict[str, Any]] = []
    grid = [[0 for _ in range(4)] for _ in range(6)]
    for row in state.tracks:
        x, y = row["x_m"], row["y_m"]
        uncertainty = row["position_uncertainty_m"]
        if (
            x is None
            or y is None
            or not math.isfinite(x)
            or not math.isfinite(y)
            or row["position_provenance"] != "measured"
            or uncertainty is None
            or not math.isfinite(uncertainty)
            or uncertainty > MAX_PLAYER_FLOOR_UNCERTAINTY_M
        ):
            exclusions["invalid_projection"] += 1
            continue
        if not row["observed"]:
            exclusions["not_observed"] += 1
            continue
        if active_revision is not None and row["calibration_revision"] != active_revision:
            exclusions["stale_calibration"] += 1
            continue
        if not (0 <= x <= COURT_WIDTH_M and 0 <= y <= COURT_LENGTH_M):
            exclusions["out_of_court"] += 1
            continue
        observed.append(row)
        x_bin = min(3, int(x / COURT_WIDTH_M * 4))
        y_bin = min(5, int(y / COURT_LENGTH_M * 6))
        grid[y_bin][x_bin] += 1
    distances: list[float] = []
    distance_by_player: dict[str, dict[str, Any]] = {}
    for slot in ("near", "far"):
        rows = sorted(
            (
                row
                for row in observed
                if row["slot"] == slot and row["source_timestamp_us"] is not None
            ),
            key=lambda row: row["source_timestamp_us"],
        )
        player_distances: list[float] = []
        for left, right in zip(rows, rows[1:]):
            gap = right["source_timestamp_us"] - left["source_timestamp_us"]
            if gap <= 0 or gap > MAX_MOVEMENT_GAP_US:
                continue
            player_distances.append(
                math.hypot(
                    right["x_m"] - left["x_m"],
                    right["y_m"] - left["y_m"],
                )
            )
        distances.extend(player_distances)
        distance_by_player[slot] = {
            "distance_m": (
                unavailable("missing_calibration")
                if active_revision is None
                else available(sum(player_distances))
                if player_distances
                else unavailable("no_valid_observed_intervals")
            ),
            "sample_count": len(player_distances),
        }
    if active_revision is None:
        distance = unavailable("missing_calibration")
    elif distances:
        distance = available(sum(distances))
    else:
        distance = unavailable("no_valid_observed_intervals")
    recoveries: list[tuple[float, str, str]] = []
    for shot in state.shots:
        hitter = shot["hitter"]
        if hitter is None:
            continue
        later = sorted(
            (
                row
                for row in observed
                if row["slot"] == hitter
                and row["source_timestamp_us"] is not None
                and shot["source_timestamp_us"] < row["source_timestamp_us"] <= shot["source_timestamp_us"] + MAX_RECOVERY_US
                and math.hypot(row["x_m"] - T_POINT[0], row["y_m"] - T_POINT[1]) <= 1.0
            ),
            key=lambda row: row["source_timestamp_us"],
        )
        if later:
            recoveries.append(((later[0]["source_timestamp_us"] - shot["source_timestamp_us"]) / 1_000_000, shot["prediction_id"], later[0]["prediction_id"]))
    recovery_values = [item[0] for item in recoveries]
    recovery = {
        "sample_count": len(recoveries),
        "median_seconds": available(statistics.median(recovery_values)) if recovery_values else unavailable("no_measured_recoveries"),
        "samples": [
            {"seconds": seconds, "shot_id": shot_id, "position_id": track_id}
            for seconds, shot_id, track_id in recoveries
        ],
    }
    evidence = sorted({item for row in observed for item in row["source_evidence_ids"]})
    return {
        "active_calibration_revision": active_revision,
        "heatmap": {
            "court_width_m": COURT_WIDTH_M,
            "court_length_m": COURT_LENGTH_M,
            "columns": 4,
            "rows": 6,
            "counts": grid,
            "excluded": dict(sorted(exclusions.items())),
        },
        "distance_m": distance,
        "players": distance_by_player,
        "t_recovery": recovery,
    }, evidence


def _errors_section(state: CanonicalState) -> tuple[dict[str, Any], list[str]]:
    objective = [shot for shot in state.shots if shot["outcome"] == "error"]
    reviewed = [
        error for error in state.errors if error["review_status"] == "accepted"
    ]
    pending = [
        error for error in state.errors if error["review_status"] == "pending"
    ]
    shot_by_id = {shot["prediction_id"]: shot for shot in state.shots}
    rows: list[dict[str, Any]] = []
    for shot in objective:
        rows.append(
            {
                "id": shot["prediction_id"],
                "category": "objective",
                "status": "accepted",
                "counted": True,
                "side": (
                    None
                    if shot["contact_x_m"] is None
                    else "left"
                    if shot["contact_x_m"] < COURT_WIDTH_M / 2
                    else "right"
                ),
                "rally_id": shot["rally_id"],
                "timestamp_us": shot["source_timestamp_us"],
                "evidence_ids": list(shot["source_evidence_ids"]),
                "target_id": shot["prediction_id"],
                "kind": "objective_outcome",
            }
        )
    for error in state.errors:
        target = shot_by_id.get(error["target_prediction_id"])
        rows.append(
            {
                "id": error["prediction_id"],
                "category": "subjective",
                "status": error["review_status"],
                "counted": error["review_status"] == "accepted",
                "side": (
                    None
                    if target is None or target["contact_x_m"] is None
                    else "left"
                    if target["contact_x_m"] < COURT_WIDTH_M / 2
                    else "right"
                ),
                "rally_id": target["rally_id"] if target is not None else None,
                "timestamp_us": error["source_timestamp_us"],
                "evidence_ids": list(error["source_evidence_ids"]),
                "target_id": error["target_prediction_id"],
                "kind": error["kind"],
            }
        )
    evidence = sorted(
        {
            item
            for row in objective + state.errors
            for item in row.get("source_evidence_ids", [])
        }
    )
    return {
        "objective_count": len(objective),
        "objective_event_ids": [item["prediction_id"] for item in objective],
        "reviewed_subjective_count": len(reviewed),
        "reviewed_subjective_ids": [item["prediction_id"] for item in reviewed],
        "unreviewed_candidate_count": len(pending),
        "unreviewed_candidate_ids": [item["prediction_id"] for item in pending],
        "items": sorted(
            rows,
            key=lambda item: (
                item["timestamp_us"] is None,
                item["timestamp_us"] or 0,
                item["id"],
            ),
        ),
    }, evidence


def _trajectory_section(
    state: CanonicalState, active_calibration_revision: int | None
) -> tuple[dict[str, Any], list[str]]:
    measured: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    control_exclusions: Counter[str] = Counter()
    control_points: list[dict[str, Any]] = []
    image_exclusions: Counter[str] = Counter()
    image_points: list[dict[str, Any]] = []
    for shot in state.shots:
        speed = shot["speed_m_s"]
        if speed is None:
            reasons[shot["speed_unavailable_reason"] or "unavailable"] += 1
        elif not math.isfinite(speed):
            reasons["nonfinite_speed"] += 1
        else:
            measured.append(shot)

        image_reason = shot.get("image_point_unavailable_reason")
        if image_reason is not None:
            image_exclusions[str(image_reason)] += 1
        else:
            image_points.append(
                {
                    "shot_id": shot["prediction_id"],
                    "timestamp_us": shot["source_timestamp_us"],
                    "x_px": shot["contact_x_px"],
                    "y_px": shot["contact_y_px"],
                    "source_width": shot["contact_source_width"],
                    "source_height": shot["contact_source_height"],
                    "provenance": (
                        "reconstructed"
                        if shot["contact_provenance"] == "interpolated"
                        else "observed"
                    ),
                    "covariance": shot["contact_covariance"],
                    "evidence_ids": list(shot["source_evidence_ids"]),
                }
            )

        x_m, y_m = shot["contact_x_m"], shot["contact_y_m"]
        control_reason = shot.get("control_point_unavailable_reason")
        if control_reason is not None:
            control_exclusions[control_reason] += 1
        elif x_m is None or y_m is None:
            control_exclusions["missing_coordinate"] += 1
        elif not math.isfinite(x_m) or not math.isfinite(y_m):
            control_exclusions["nonfinite_coordinate"] += 1
        else:
            control_points.append(
                {
                    "shot_id": shot["prediction_id"],
                    "timestamp_us": shot["source_timestamp_us"],
                    "x_m": x_m,
                    "y_m": y_m,
                    "provenance": "canonical_court_contact",
                    "uncertainty_m": None,
                    "evidence_ids": list(shot["source_evidence_ids"]),
                }
            )
    metric = (
        available(statistics.fmean(shot["speed_m_s"] for shot in measured))
        if measured
        else unavailable(next(iter(sorted(reasons)), "no_shots"))
    )
    evidence = sorted(
        {item for shot in state.shots for item in shot["source_evidence_ids"]}
    )
    return {
        "average_speed_m_s": metric,
        "measured_shot_count": len(measured),
        "unavailable_reasons": dict(sorted(reasons.items())),
        "image_trajectory": {
            "availability": (
                {"available": True, "reason": None}
                if image_points
                else {
                    "available": False,
                    "reason": next(
                        iter(sorted(image_exclusions)),
                        "image_space_provenance_not_published",
                    ),
                }
            ),
            "items": image_points,
            "excluded": dict(sorted(image_exclusions.items())),
        },
        "court_trajectory": {
            "availability": (
                {"available": True, "reason": None}
                if active_calibration_revision is not None
                else {"available": False, "reason": "missing_calibration"}
            ),
            "calibration_revision": active_calibration_revision,
            "items": (
                control_points if active_calibration_revision is not None else []
            ),
        },
        "control_point_exclusions": dict(sorted(control_exclusions.items())),
    }, evidence


def _coaching_section(state: CanonicalState, movement: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    findings: list[dict[str, Any]] = []
    evidence_ids: set[str] = set()
    for player in ("near", "far"):
        player_shots = [shot for shot in state.shots if shot["hitter"] == player]
        boasts = [shot for shot in player_shots if shot["shot_type"] == "boast"]
        if len(player_shots) >= 8 and len(boasts) / len(player_shots) > 0.30:
            measured = len(boasts) / len(player_shots)
            ids = [shot["prediction_id"] for shot in boasts]
            findings.append(_finding("boast_overuse", player, len(player_shots), measured, 0.30, ids, f"{player} used boasts on {measured:.1%} of {len(player_shots)} shots, above the 30.0% threshold."))
            evidence_ids.update(ids)
        drives = [shot for shot in player_shots if shot["shot_type"] == "drive"]
        shallow = [shot for shot in drives if shot["contact_y_m"] is not None and shot["contact_y_m"] < COURT_LENGTH_M / 2]
        if len(drives) >= 8 and len(shallow) / len(drives) > 0.40:
            measured = len(shallow) / len(drives)
            ids = [shot["prediction_id"] for shot in shallow]
            findings.append(_finding("shallow_drive_pattern", player, len(drives), measured, 0.40, ids, f"{player} contacted {measured:.1%} of {len(drives)} drives in the shallow half, above 40.0%."))
            evidence_ids.update(ids)
    accepted_ids = {item["target_prediction_id"] for item in state.errors if item["review_status"] == "accepted"}
    reviewed_error_shots = [shot for shot in state.shots if shot["prediction_id"] in accepted_ids]
    if len(reviewed_error_shots) >= 6:
        left = [shot for shot in reviewed_error_shots if shot["contact_x_m"] is not None and shot["contact_x_m"] < COURT_WIDTH_M / 2]
        right = [shot for shot in reviewed_error_shots if shot["contact_x_m"] is not None and shot["contact_x_m"] >= COURT_WIDTH_M / 2]
        concentrated = left if len(left) >= len(right) else right
        measured = len(concentrated) / len(reviewed_error_shots)
        if measured > 0.60:
            side = "left" if concentrated is left else "right"
            ids = [shot["prediction_id"] for shot in concentrated]
            findings.append(_finding("one_side_error_concentration", side, len(reviewed_error_shots), measured, 0.60, ids, f"{measured:.1%} of {len(reviewed_error_shots)} reviewed errors were on the {side}, above 60.0%."))
            evidence_ids.update(ids)
    recovery = movement["t_recovery"]
    median_metric = recovery["median_seconds"]
    if recovery["sample_count"] >= 5 and median_metric["available"] and median_metric["value"] > 2.0:
        ids = [sample["shot_id"] for sample in recovery["samples"]]
        measured = median_metric["value"]
        findings.append(_finding("slow_t_recovery", "all", recovery["sample_count"], measured, 2.0, ids, f"Median T recovery was {measured:.2f}s across {recovery['sample_count']} recoveries, above 2.00s."))
        evidence_ids.update(ids)
    timed_rallies = [
        rally
        for rally in state.rallies
        if rally.get("timing_available")
        and rally["start_timestamp_us"] is not None
        and rally["end_timestamp_us"] is not None
    ]
    long_rallies = [
        rally
        for rally in timed_rallies
        if rally["end_timestamp_us"] - rally["start_timestamp_us"] >= 10_000_000
    ]
    short_rallies = [rally for rally in timed_rallies if rally not in long_rallies]
    if len(long_rallies) >= 6 and short_rallies:
        error_rallies = {shot["rally_id"] for shot in state.shots if shot["outcome"] == "error"}
        long_rate = sum(rally["prediction_id"] in error_rallies for rally in long_rallies) / len(long_rallies)
        short_rate = sum(rally["prediction_id"] in error_rallies for rally in short_rallies) / len(short_rallies)
        difference = long_rate - short_rate
        if difference >= 0.20:
            ids = [rally["prediction_id"] for rally in long_rallies if rally["prediction_id"] in error_rallies]
            finding = _finding(
                "long_rally_error_concentration",
                "all",
                len(long_rallies),
                difference,
                0.20,
                ids,
                (
                    f"Long-rally error rate was {long_rate:.1%} versus "
                    f"{short_rate:.1%} for shorter rallies, a "
                    f"{difference:.1%} difference across "
                    f"{len(long_rallies)} long rallies, meeting 20.0%."
                ),
            )
            finding.update(
                {
                    "long_rate": long_rate,
                    "short_rate": short_rate,
                    "difference": difference,
                    "threshold": 0.20,
                }
            )
            findings.append(finding)
            evidence_ids.update(ids)
    return {"findings": findings}, sorted(evidence_ids)


def _finding(rule: str, subject: str, sample_count: int, measured: float, baseline: float, ids: list[str], sentence: str) -> dict[str, Any]:
    return {
        "rule": rule,
        "subject": subject,
        "sample_count": sample_count,
        "measured": measured,
        "baseline": baseline,
        "comparator": "greater_than",
        "supporting_event_ids": ids,
        "evidence": sentence,
    }


def _build_sections(
    state: CanonicalState, active_calibration_revision: int | None
) -> dict[str, tuple[dict[str, Any], list[str]]]:
    shots = _shot_section(state)
    rallies = _rally_section(state)
    overview = _overview_section(state)
    movement = _movement_section(state, active_calibration_revision)
    errors = _errors_section(state)
    trajectory = _trajectory_section(state, active_calibration_revision)
    head_to_head = ({
        player: {
            "shots": sum(shot["hitter"] == player for shot in state.shots),
            "volleys": sum(
                shot["hitter"] == player and bool(shot["is_volley"])
                for shot in state.shots
            ),
            "winners": sum(
                shot["hitter"] == player and shot["outcome"] == "winner"
                for shot in state.shots
            ),
            "errors": sum(
                shot["hitter"] == player and shot["outcome"] == "error"
                for shot in state.shots
            ),
            "movement": movement[0]["players"][player],
        }
        for player in ("near", "far")
    }, shots[1])
    coaching = _coaching_section(state, movement[0])
    review_entities = [
        *state.errors,
        *(shot for shot in state.shots if shot.get("review_required")),
        *(rally for rally in state.rallies if rally.get("review_required")),
    ]
    review_evidence = sorted(
        {
            evidence_id
            for item in review_entities
            for evidence_id in item.get("source_evidence_ids", [])
        }
    )
    review = ({
        "candidate_count": len(review_entities),
        "reviewed_count": sum(
            item.get("review_status") in {"accepted", "rejected"}
            for item in review_entities
        ),
        "pending_ids": [
            item["prediction_id"]
            for item in review_entities
            if item.get("review_status") == "pending"
        ],
    }, review_evidence)
    return {
        "overview": overview,
        "shots": shots,
        "rallies": rallies,
        "movement": movement,
        "errors": errors,
        "trajectory": trajectory,
        "head_to_head": head_to_head,
        "coaching": coaching,
        "review": review,
    }


def _report_from_row(match_id: str, row: ReportRevision) -> MatchReport:
    unavailable_payload = {
        "availability": {
            "available": False,
            "reason": "legacy_schema_incompatible",
        }
    }
    return MatchReport(
        match_id=match_id,
        revision=row.revision,
        prediction_revision=row.prediction_revision,
        calibration_revision=row.calibration_revision,
        sections={
            name: ReportSection(
                payload={
                    key: value
                    for key, value in (row.sections or {}).get(
                        name, unavailable_payload
                    ).items()
                    if key != "_evidence_ids"
                },
                evidence_ids=(row.sections or {}).get(name, {}).get(
                    "_evidence_ids", []
                ),
                hash=(row.section_hashes or {}).get(
                    name, "legacy_schema_incompatible"
                ),
                dependency_hash=(row.dependency_hashes or {}).get(
                    name, "legacy_schema_incompatible"
                ),
            )
            for name in SECTION_NAMES
        },
    )


def _latest_prediction_revision(session: Session, match_id: int) -> int:
    values = [
        session.scalar(
            select(func.max(model.prediction_revision)).where(
                model.match_id == match_id
            )
        )
        for model in (Shot, Rally, PlayerTrack, ErrorCandidate)
    ]
    return max((value for value in values if value is not None), default=1)


def build_report(match_id: str, revision: int, db: Database) -> MatchReport:
    connection = db.engine.connect()
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    session = Session(bind=connection, expire_on_commit=False)
    try:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        if match is None:
            raise ReportNotFoundError("match_not_found")
        existing = session.scalar(
            select(ReportRevision).where(
                ReportRevision.match_id == match.id,
                ReportRevision.revision == revision,
            )
        )
        if existing is not None:
            report = _report_from_row(match_id, existing)
            connection.commit()
            return report
        latest = session.scalar(
            select(func.max(ReportRevision.revision)).where(
                ReportRevision.match_id == match.id
            )
        )
        if latest is not None and revision != latest + 1:
            raise ReportNotFoundError("report_revision_not_found")
        report = build_report_in_session(
            session,
            match,
            revision,
            prediction_revision=_latest_prediction_revision(session, match.id),
        )
        session.flush()
        connection.commit()
        return report
    except BaseException:
        connection.rollback()
        raise
    finally:
        session.close()
        connection.close()


def build_report_in_session(
    session: Session,
    match: Match,
    revision: int,
    *,
    prediction_revision: int,
    correction_id: int | None = None,
    invalidated: set[str] | None = None,
) -> MatchReport:
    state = _fold_state(session, match, prediction_revision, revision)
    active_calibration = session.scalar(
        select(func.max(Calibration.revision)).where(
            Calibration.match_id == match.id
        )
    )
    built = _build_sections(state, active_calibration)
    previous = session.scalar(
        select(ReportRevision)
        .where(ReportRevision.match_id == match.id, ReportRevision.revision < revision)
        .order_by(ReportRevision.revision.desc())
    )
    sections: dict[str, Any] = {}
    section_hashes: dict[str, str] = {}
    dependency_hashes: dict[str, str] = {}
    recomputed: set[str] = set()
    for name in SECTION_NAMES:
        if previous is not None and invalidated is not None and name not in invalidated:
            sections[name] = previous.sections[name]
            section_hashes[name] = previous.section_hashes[name]
            dependency_hashes[name] = previous.dependency_hashes[name]
            continue
        payload, evidence = built[name]
        stored_payload = dict(payload)
        stored_payload["_evidence_ids"] = evidence
        sections[name] = stored_payload
        section_hashes[name] = _stable_hash(
            {"schema_version": 1, "payload": payload, "evidence_ids": evidence}
        )
        recomputed.add(name)
    chain = session.scalars(
        select(Correction)
        .where(
            Correction.match_id == match.id,
            Correction.prediction_revision == prediction_revision,
            Correction.status == CorrectionStatus.ACTIVE,
            Correction.expected_report_revision < revision,
        )
        .order_by(Correction.id)
    ).all()
    chain_hash = _stable_hash(
        [
            {
                "id": item.public_id,
                "command_type": item.command_type,
                "target_type": item.target_type,
                "target_id": item.target_id,
                "after_payload": item.after_payload,
            }
            for item in chain
        ]
    )
    upstreams = {
        "overview": ("shots", "rallies", "errors"),
        "shots": (),
        "rallies": (),
        "movement": ("shots",),
        "errors": ("shots",),
        "trajectory": ("shots",),
        "head_to_head": ("shots",),
        "coaching": ("shots", "rallies", "movement", "errors"),
        "review": ("errors",),
    }
    for name in recomputed:
        payload, evidence = built[name]
        dependency_hashes[name] = _stable_hash(
            {
                "schema_version": 1,
                "prediction_revision": prediction_revision,
                "active_calibration_revision": active_calibration,
                "correction_chain_hash": chain_hash,
                "input_values_hash": _stable_hash(
                    {"payload": payload, "evidence_ids": evidence}
                ),
                "upstream_section_hashes": {
                    upstream: section_hashes[upstream]
                    for upstream in upstreams[name]
                },
            }
        )
    row = ReportRevision(
        match=match,
        correction_id=correction_id,
        revision=revision,
        prediction_revision=prediction_revision,
        calibration_revision=active_calibration,
        schema_version=1,
        sections=sections,
        section_hashes=section_hashes,
        dependency_hashes=dependency_hashes,
    )
    session.add(row)
    session.flush()
    return _report_from_row(match.public_id, row)


def canonical_target(
    session: Session,
    match: Match,
    target_type: str,
    target_id: str,
    prediction_revision: int,
    report_revision: int,
) -> dict[str, Any] | None:
    state = _fold_state(session, match, prediction_revision, report_revision)
    rows = state.shots if target_type == "shot" else state.rallies if target_type == "rally" else state.errors
    return next((dict(row) for row in rows if row["prediction_id"] == target_id), None)
