from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from squashvision.analytics import (
    SECTION_NAMES,
    build_report_in_session,
    canonical_target,
    _report_from_row,
)
from squashvision.db import Database
from squashvision.models import (
    Correction,
    CorrectionStatus,
    ErrorCandidate,
    Match,
    Rally,
    ReportRevision,
    Shot,
)
from squashvision.schemas import (
    ConflictResolution,
    CorrectionCommand,
    CorrectionCommandType,
    MatchReport,
)


class CorrectionError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class RevisionConflict(CorrectionError):
    def __init__(self, expected: int, current: int) -> None:
        super().__init__(
            "report_revision_conflict",
            f"expected report revision {expected}, current revision is {current}",
            409,
        )
        self.expected = expected
        self.current = current


class CorrectionConflict(CorrectionError):
    def __init__(self, message: str, *, code: str = "correction_conflict") -> None:
        super().__init__(code, message, 409)


@dataclass(frozen=True, slots=True)
class ReapplyConflict:
    correction_id: str
    reason: str
    candidate_ids: list[str]
    candidates: list[dict[str, Any]]



@dataclass(frozen=True, slots=True)
class ReapplyResult:
    reapplied: int
    conflicts: list[ReapplyConflict]


INVALIDATIONS: dict[CorrectionCommandType, set[str]] = {
    CorrectionCommandType.ACCEPT: {"overview", "errors", "coaching", "review"},
    CorrectionCommandType.REJECT: {"overview", "errors", "coaching", "review"},
    CorrectionCommandType.CHANGE_HITTER: {
        "overview",
        "shots",
        "movement",
        "errors",
        "head_to_head",
        "coaching",
        "review",
    },
    CorrectionCommandType.CHANGE_SHOT_TYPE: {
        "overview",
        "shots",
        "errors",
        "head_to_head",
        "coaching",
        "review",
    },
    CorrectionCommandType.ADJUST_CONTACT_TIME: {
        "overview",
        "shots",
        "movement",
        "rallies",
        "errors",
        "trajectory",
        "head_to_head",
        "coaching",
        "review",
    },
    CorrectionCommandType.CHANGE_OUTCOME: {
        "overview",
        "shots",
        "errors",
        "head_to_head",
        "coaching",
        "review",
    },
    CorrectionCommandType.BALL_CONTROL_POINT: {
        "shots",
        "errors",
        "trajectory",
        "coaching",
        "review",
    },
    CorrectionCommandType.SPLIT_RALLY: {
        "overview",
        "shots",
        "rallies",
        "errors",
        "head_to_head",
        "coaching",
        "review",
    },
    CorrectionCommandType.MERGE_RALLIES: {
        "overview",
        "shots",
        "rallies",
        "errors",
        "head_to_head",
        "coaching",
        "review",
    },
}


def _immediate_session(db: Database):
    connection = db.engine.connect()
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    return connection, Session(bind=connection, expire_on_commit=False)


def _current_revision(session: Session, match_id: int) -> int:
    return int(
        session.scalar(
            select(func.max(ReportRevision.revision)).where(
                ReportRevision.match_id == match_id
            )
        )
        or 0
    )


def _current_report(session: Session, match_id: int) -> ReportRevision | None:
    return session.scalar(
        select(ReportRevision)
        .where(ReportRevision.match_id == match_id)
        .order_by(ReportRevision.revision.desc())
    )


def _apply_after(before: dict[str, Any], command: CorrectionCommand) -> dict[str, Any]:
    after = dict(before)
    payload = dict(command.payload)
    if command.command_type is CorrectionCommandType.CHANGE_HITTER:
        after["hitter"] = payload["hitter"]
    elif command.command_type is CorrectionCommandType.CHANGE_SHOT_TYPE:
        after["shot_type"] = payload["shot_type"]
    elif command.command_type is CorrectionCommandType.ADJUST_CONTACT_TIME:
        after["source_timestamp_us"] = payload["source_timestamp_us"]
    elif command.command_type is CorrectionCommandType.CHANGE_OUTCOME:
        after["outcome"] = payload["outcome"]
    elif command.command_type is CorrectionCommandType.BALL_CONTROL_POINT:
        after["contact_x_m"] = payload["x_m"]
        after["contact_y_m"] = payload["y_m"]
        after.update(payload)
    elif command.command_type is CorrectionCommandType.ACCEPT:
        after["review_status"] = "accepted"
    elif command.command_type is CorrectionCommandType.REJECT:
        after["review_status"] = "rejected"
    else:
        after.update(payload)
    return after


def _validate_source(before: dict[str, Any], command: CorrectionCommand) -> None:
    before_timestamp = before.get("source_timestamp_us")
    if before_timestamp is None:
        before_timestamp = before.get("start_timestamp_us")
    if command.source_timestamp_us is not None and before_timestamp != command.source_timestamp_us:
        raise CorrectionConflict("target source timestamp no longer matches the command")
    if command.source_evidence_ids is not None:
        if list(before.get("source_evidence_ids", [])) != list(command.source_evidence_ids):
            raise CorrectionConflict("target source evidence no longer matches the command")


def _validate_rally_operation(
    session: Session,
    match: Match,
    command: CorrectionCommand,
    prediction_revision: int,
    current_revision: int,
    before: dict[str, Any],
) -> None:
    if command.command_type is CorrectionCommandType.SPLIT_RALLY:
        split = int(command.payload["split_timestamp_us"])
        if (
            not before.get("timing_available")
            or before["start_timestamp_us"] is None
            or before["end_timestamp_us"] is None
            or not before["start_timestamp_us"] < split < before["end_timestamp_us"]
        ):
            raise CorrectionConflict(
                "split requires real timing and two positive-duration rallies"
            )
        return
    if command.command_type is not CorrectionCommandType.MERGE_RALLIES:
        return
    other = canonical_target(
        session,
        match,
        "rally",
        str(command.payload["other_target_id"]),
        prediction_revision,
        current_revision,
    )
    if other is None:
        raise CorrectionConflict("merge target was not found in the same match")
    if (
        not before.get("timing_available")
        or not other.get("timing_available")
        or before["start_timestamp_us"] is None
        or before["end_timestamp_us"] is None
        or other["start_timestamp_us"] is None
        or other["end_timestamp_us"] is None
    ):
        raise CorrectionConflict("merge requires real rally timing anchors")
    intervals = sorted(
        [
            (before["start_timestamp_us"], before["end_timestamp_us"]),
            (other["start_timestamp_us"], other["end_timestamp_us"]),
        ]
    )
    if intervals[0][1] != intervals[1][0]:
        raise CorrectionConflict("merge targets must be adjacent and nonoverlapping")


def apply_correction(command: CorrectionCommand, db: Database) -> MatchReport:
    connection, session = _immediate_session(db)
    try:
        match = session.scalar(select(Match).where(Match.public_id == command.match_id))
        if match is None:
            raise CorrectionError("match_not_found", "match was not found", 404)
        current = _current_revision(session, match.id)
        if current != command.expected_report_revision:
            raise RevisionConflict(command.expected_report_revision, current)
        previous = _current_report(session, match.id)
        if previous is None:
            raise CorrectionError("report_not_found", "build the initial report first", 409)
        before = canonical_target(
            session,
            match,
            command.target_type,
            command.target_id,
            previous.prediction_revision,
            current,
        )
        if before is None:
            raise CorrectionConflict("correction target does not exist in the canonical report")
        _validate_source(before, command)
        review_entity_type = command.review_entity_type
        review_entity_id = command.review_entity_id
        if review_entity_type is None and command.command_type in {
            CorrectionCommandType.ACCEPT,
            CorrectionCommandType.REJECT,
        }:
            review_entity_type = command.target_type
            review_entity_id = command.target_id
        if (
            command.command_type
            in {CorrectionCommandType.ACCEPT, CorrectionCommandType.REJECT}
            and (
                review_entity_type != command.target_type
                or review_entity_id != command.target_id
            )
        ):
            raise CorrectionConflict(
                "accept/reject review entity must match the correction target"
            )
        review_entity = (
            canonical_target(
                session,
                match,
                review_entity_type,
                review_entity_id,
                previous.prediction_revision,
                current,
            )
            if review_entity_type is not None and review_entity_id is not None
            else None
        )
        if review_entity_type is not None and review_entity is None:
            raise CorrectionConflict("review entity no longer exists")
        if review_entity is not None and review_entity.get("review_status") != "pending":
            raise CorrectionConflict("review entity is already resolved")
        if (
            review_entity_type == "error_candidate"
            and command.target_type == "shot"
            and review_entity is not None
            and review_entity.get("target_prediction_id") != command.target_id
        ):
            raise CorrectionConflict("review candidate does not target the edited shot")
        if (
            review_entity_type in {"shot", "rally"}
            and command.command_type
            not in {CorrectionCommandType.ACCEPT, CorrectionCommandType.REJECT}
            and review_entity_id != command.target_id
        ):
            raise CorrectionConflict("review entity does not match the edited target")
        _validate_rally_operation(
            session,
            match,
            command,
            previous.prediction_revision,
            current,
            before,
        )
        after = _apply_after(before, command)
        error_candidate = None
        if review_entity_type == "error_candidate" and review_entity_id is not None:
            error_candidate = session.scalar(
                select(ErrorCandidate).where(
                    ErrorCandidate.match_id == match.id,
                    ErrorCandidate.prediction_revision == previous.prediction_revision,
                    ErrorCandidate.prediction_id == review_entity_id,
                )
            )
        correction = Correction(
            match=match,
            error_candidate=error_candidate,
            command_type=command.command_type.value,
            target_type=command.target_type,
            target_id=command.target_id,
            prediction_revision=previous.prediction_revision,
            expected_report_revision=current,
            before_payload=before,
            after_payload=after,
            reason=command.reason,
            source_timestamp_us=(command.source_timestamp_us if command.source_timestamp_us is not None else before.get("source_timestamp_us")),
            source_evidence_ids=(list(command.source_evidence_ids) if command.source_evidence_ids is not None else list(before.get("source_evidence_ids", []))),
            review_entity_type=review_entity_type,
            review_entity_id=review_entity_id,
            review_decision=(
                "rejected"
                if command.command_type is CorrectionCommandType.REJECT
                else "accepted"
                if review_entity_id is not None
                else None
            ),
            status=CorrectionStatus.ACTIVE,
        )
        session.add(correction)
        session.flush()
        report = build_report_in_session(
            session,
            match,
            current + 1,
            prediction_revision=previous.prediction_revision,
            correction_id=correction.id,
            invalidated={*INVALIDATIONS[command.command_type], "review"},
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


def _candidate_rows(
    session: Session,
    match_id: int,
    target_type: str,
    prediction_revision: int,
) -> list[dict[str, Any]]:
    if target_type == "shot":
        rows = session.scalars(
            select(Shot).where(
                Shot.match_id == match_id,
                Shot.prediction_revision == prediction_revision,
            )
            .order_by(Shot.prediction_id)
        ).all()
        return [
            {
                "id": row.prediction_id,
                "source_timestamp_us": row.source_timestamp_us,
                "source_evidence_ids": list(row.source_evidence_ids),
                "frame_index": row.frame_index,
                "shot_type": row.kind.value,
            }
            for row in rows
        ]
    if target_type == "rally":
        rows = session.scalars(
            select(Rally).where(
                Rally.match_id == match_id,
                Rally.prediction_revision == prediction_revision,
            )
            .order_by(Rally.prediction_id)
        ).all()
        return [
            {
                "id": row.prediction_id,
                "source_timestamp_us": row.start_timestamp_us,
                "source_evidence_ids": list(row.source_evidence_ids),
                "start_timestamp_us": row.start_timestamp_us,
                "end_timestamp_us": row.end_timestamp_us,
                "start_frame": row.start_frame,
                "end_frame": row.end_frame,
                "kind": "rally",
            }
            for row in rows
        ]
    rows = session.scalars(
        select(ErrorCandidate).where(
            ErrorCandidate.match_id == match_id,
            ErrorCandidate.prediction_revision == prediction_revision,
        )
        .order_by(ErrorCandidate.prediction_id)
    ).all()
    return [
        {
            "id": row.prediction_id,
            "source_timestamp_us": row.source_timestamp_us,
            "source_evidence_ids": list(row.source_evidence_ids),
            "target_type": row.target_type,
            "target_prediction_id": row.target_prediction_id,
            "kind": row.kind.value,
            "evidence_payload": dict(row.evidence_payload),
        }
        for row in rows
    ]


def _anchor_matches(
    source_timestamp_us: int | None,
    source_evidence_ids: list[str],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    evidence = set(source_evidence_ids)
    exact = [
        candidate
        for candidate in candidates
        if evidence and evidence == set(candidate["source_evidence_ids"])
    ]
    if exact:
        return exact, "exact_evidence"
    contextual = [
        candidate
        for candidate in candidates
        if source_timestamp_us is not None
        and candidate["source_timestamp_us"] is not None
        and abs(candidate["source_timestamp_us"] - source_timestamp_us) <= 50_000
        and bool(evidence & set(candidate["source_evidence_ids"]))
    ]
    return contextual, "time_context"


def _matches(
    correction: Correction, candidates: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    return _anchor_matches(
        correction.source_timestamp_us,
        list(correction.source_evidence_ids),
        candidates,
    )


@dataclass(frozen=True, slots=True)
class _ReviewRemap:
    entity_type: str | None
    entity_id: str | None
    reason: str | None
    candidate_ids: list[str]
    strategy: str | None


def _remap_review_entity(
    session: Session,
    original: Correction,
    new_prediction_revision: int,
    mapped_target_id: str,
) -> _ReviewRemap:
    entity_type = original.review_entity_type
    entity_id = original.review_entity_id
    if entity_type is None and entity_id is None:
        return _ReviewRemap(None, None, None, [], None)
    if (
        entity_type not in {"error_candidate", "shot", "rally"}
        or entity_id is None
    ):
        return _ReviewRemap(
            None, None, "invalid_review_entity_linkage", [], None
        )
    if entity_type == original.target_type and entity_id == original.target_id:
        return _ReviewRemap(
            entity_type, mapped_target_id, None, [mapped_target_id], "selected_target"
        )
    if entity_type != "error_candidate":
        return _ReviewRemap(
            None, None, "review_entity_target_mismatch", [], None
        )
    source = session.scalar(
        select(ErrorCandidate).where(
            ErrorCandidate.match_id == original.match_id,
            ErrorCandidate.prediction_revision == original.prediction_revision,
            ErrorCandidate.prediction_id == entity_id,
        )
    )
    if source is None:
        return _ReviewRemap(None, None, "no_matching_review_entity", [], None)
    if (
        source.target_type != original.target_type
        or source.target_prediction_id != original.target_id
    ):
        return _ReviewRemap(
            None, None, "review_entity_target_mismatch", [], None
        )
    candidates = [
        candidate
        for candidate in _candidate_rows(
            session,
            original.match_id,
            "error_candidate",
            new_prediction_revision,
        )
        if candidate["target_type"] == source.target_type
        and candidate["target_prediction_id"] == mapped_target_id
    ]
    matches, strategy = _anchor_matches(
        source.source_timestamp_us,
        list(source.source_evidence_ids),
        candidates,
    )
    if len(matches) != 1:
        return _ReviewRemap(
            None,
            None,
            "no_matching_review_entity"
            if not matches
            else "ambiguous_review_entity_match",
            [candidate["id"] for candidate in matches],
            strategy,
        )
    return _ReviewRemap(
        "error_candidate",
        matches[0]["id"],
        None,
        [matches[0]["id"]],
        strategy,
    )


def _conflict_candidate(candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    timestamp = int(payload.get("source_timestamp_us") or payload.get("start_timestamp_us") or 0)
    evidence_value = payload.get("evidence_payload")
    evidence_payload = evidence_value if isinstance(evidence_value, dict) else {}
    start_timestamp = int(
        evidence_payload.get("evidence_start_timestamp_us")
        or payload.get("start_timestamp_us")
        or timestamp
    )
    end_timestamp = int(
        evidence_payload.get("evidence_end_timestamp_us")
        or payload.get("end_timestamp_us")
        or timestamp
    )
    start_frame = evidence_payload.get("evidence_start_frame_index")
    if start_frame is None:
        start_frame = payload.get("start_frame")
    if start_frame is None:
        start_frame = payload.get("frame_index")
    end_frame = evidence_payload.get("evidence_end_frame_index")
    if end_frame is None:
        end_frame = payload.get("end_frame")
    if end_frame is None:
        end_frame = payload.get("frame_index")
    return {
        "candidate_id": candidate_id,
        "timestamp_us": timestamp,
        "evidence_start_timestamp_us": start_timestamp,
        "evidence_end_timestamp_us": max(start_timestamp, end_timestamp),
        "evidence_start_frame_index": start_frame,
        "evidence_end_frame_index": end_frame,
        "evidence_ids": list(payload.get("source_evidence_ids", [])),
        "label": f"{payload.get('shot_type') or payload.get('kind') or payload.get('target_type') or 'prediction'} at {timestamp}",
    }


def _record_reapply_conflict(
    session: Session,
    original: Correction,
    new_prediction_revision: int,
    current_revision: int,
    reason: str,
    strategy: str,
    target_candidates: list[dict[str, Any]],
    review_remap: _ReviewRemap | None = None,
) -> ReapplyConflict:
    target_candidate_ids = [
        candidate["id"] for candidate in target_candidates
    ]
    selection_candidates = target_candidates
    selection_target_type = original.target_type
    if (
        review_remap is not None
        and review_remap.reason == "ambiguous_review_entity_match"
        and review_remap.candidate_ids
    ):
        review_ids = set(review_remap.candidate_ids)
        selection_candidates = [
            candidate
            for candidate in _candidate_rows(
                session,
                original.match_id,
                "error_candidate",
                new_prediction_revision,
            )
            if candidate["id"] in review_ids
        ]
        selection_target_type = "error_candidate"
    candidate_ids = [
        candidate["id"] for candidate in selection_candidates
    ]
    details: dict[str, Any] = {
        "reason": reason,
        "strategy": strategy,
        "candidate_ids": candidate_ids,
        "target_candidate_ids": target_candidate_ids,
        "selection_target_type": selection_target_type,
        "source_review_entity_type": original.review_entity_type,
        "source_review_entity_id": original.review_entity_id,
    }
    if review_remap is not None:
        details["review_strategy"] = review_remap.strategy
        details["review_candidate_ids"] = list(review_remap.candidate_ids)
    conflict = Correction(
        match_id=original.match_id,
        supersedes_correction_id=original.id,
        command_type=original.command_type,
        target_type=original.target_type,
        target_id=original.target_id,
        prediction_revision=new_prediction_revision,
        expected_report_revision=current_revision,
        before_payload=original.before_payload,
        after_payload=original.after_payload,
        reason=original.reason,
        source_timestamp_us=original.source_timestamp_us,
        source_evidence_ids=list(original.source_evidence_ids),
        review_decision=original.review_decision,
        status=CorrectionStatus.CONFLICT,
        conflict_details=details,
    )
    session.add(conflict)
    session.flush()
    return ReapplyConflict(
        conflict.public_id,
        reason,
        candidate_ids,
        [
            _conflict_candidate(candidate["id"], candidate)
            for candidate in selection_candidates
        ],
    )


def reapply_corrections_in_session(
    session: Session,
    match: Match,
    old_revision: int,
    new_prediction_revision: int,
) -> ReapplyResult:
    conflicts: list[ReapplyConflict] = []
    reapplied = 0
    child = aliased(Correction)
    originals = session.scalars(
        select(Correction)
        .where(
            Correction.match_id == match.id,
            Correction.prediction_revision == old_revision,
            Correction.status == CorrectionStatus.ACTIVE,
            ~select(child.id)
            .where(child.supersedes_correction_id == Correction.id)
            .exists(),
        )
        .order_by(Correction.id)
    ).all()
    for original in originals:
        candidates = _candidate_rows(
            session, match.id, original.target_type, new_prediction_revision
        )
        matches, strategy = _matches(original, candidates)
        current = _current_revision(session, match.id)
        if len(matches) != 1:
            conflicts.append(
                _record_reapply_conflict(
                    session,
                    original,
                    new_prediction_revision,
                    current,
                    "no_matching_prediction"
                    if not matches
                    else "ambiguous_prediction_match",
                    strategy,
                    matches,
                )
            )
            continue
        candidate = matches[0]
        review_remap = _remap_review_entity(
            session,
            original,
            new_prediction_revision,
            candidate["id"],
        )
        if review_remap.reason is not None:
            conflicts.append(
                _record_reapply_conflict(
                    session,
                    original,
                    new_prediction_revision,
                    current,
                    review_remap.reason,
                    strategy,
                    [candidate],
                    review_remap,
                )
            )
            continue
        before = canonical_target(
            session,
            match,
            original.target_type,
            candidate["id"],
            new_prediction_revision,
            current + 1,
        )
        if before is None:
            raise CorrectionConflict("matched prediction was not canonical")
        error_candidate = (
            session.scalar(
                select(ErrorCandidate).where(
                    ErrorCandidate.match_id == match.id,
                    ErrorCandidate.prediction_revision
                    == new_prediction_revision,
                    ErrorCandidate.prediction_id == review_remap.entity_id,
                )
            )
            if review_remap.entity_type == "error_candidate"
            and review_remap.entity_id is not None
            else None
        )
        reapplied_row = Correction(
            match_id=match.id,
            error_candidate=error_candidate,
            supersedes_correction_id=original.id,
            command_type=original.command_type,
            target_type=original.target_type,
            target_id=candidate["id"],
            prediction_revision=new_prediction_revision,
            expected_report_revision=current,
            before_payload=before,
            after_payload={**before, **_changed_values(original)},
            reason=original.reason,
            source_timestamp_us=candidate["source_timestamp_us"],
            source_evidence_ids=list(candidate["source_evidence_ids"]),
            review_entity_type=review_remap.entity_type,
            review_entity_id=review_remap.entity_id,
            review_decision=original.review_decision,
            status=CorrectionStatus.ACTIVE,
            conflict_details={
                "reapplied_from": original.public_id,
                "strategy": strategy,
                "review_strategy": review_remap.strategy,
            },
        )
        session.add(reapplied_row)
        session.flush()
        build_report_in_session(
            session,
            match,
            current + 1,
            prediction_revision=new_prediction_revision,
            correction_id=reapplied_row.id,
            invalidated=set(SECTION_NAMES),
        )
        reapplied += 1
    session.flush()
    return ReapplyResult(reapplied, conflicts)


def reapply_corrections(
    old_revision: int,
    new_prediction_revision: int,
    db: Database,
    *,
    match_id: str,
) -> ReapplyResult:
    connection, session = _immediate_session(db)
    try:
        match = session.scalar(
            select(Match).where(Match.public_id == match_id)
        )
        if match is None:
            raise CorrectionError(
                "match_not_found", "match was not found", 404
            )
        result = reapply_corrections_in_session(
            session,
            match,
            old_revision,
            new_prediction_revision,
        )
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        session.close()
        connection.close()


def _changed_values(correction: Correction) -> dict[str, Any]:
    return {
        key: value
        for key, value in correction.after_payload.items()
        if correction.before_payload.get(key) != value
    }


def list_conflicts(match_id: str, db: Database) -> list[ReapplyConflict]:
    with db.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        if match is None:
            raise CorrectionError("match_not_found", "match was not found", 404)
        current_report = _current_report(session, match.id)
        if current_report is None:
            return []
        child = aliased(Correction)
        rows = session.scalars(
            select(Correction)
            .where(
                Correction.match_id == match.id,
                or_(
                    Correction.prediction_revision
                    == current_report.prediction_revision,
                    Correction.expected_report_revision
                    == current_report.revision,
                ),
                Correction.status == CorrectionStatus.CONFLICT,
                ~select(child.id)
                .where(child.supersedes_correction_id == Correction.id)
                .exists(),
            )
            .order_by(Correction.id)
        ).all()
        current = current_report.revision
        result: list[ReapplyConflict] = []
        for row in rows:
            details = row.conflict_details or {}
            candidate_ids = list(details.get("candidate_ids", []))
            selection_target_type = str(
                details.get("selection_target_type", row.target_type)
            )
            candidates: list[dict[str, Any]] = []
            for candidate_id in candidate_ids:
                payload = canonical_target(
                    session,
                    match,
                    selection_target_type,
                    candidate_id,
                    row.prediction_revision,
                    current,
                )
                if payload is not None:
                    candidates.append(_conflict_candidate(candidate_id, payload))
            result.append(
                ReapplyConflict(
                    row.public_id,
                    (row.conflict_details or {}).get("reason", "conflict"),
                    candidate_ids,
                    candidates,
                )
            )
        return result


def resolve_conflict(
    match_id: str,
    correction_id: str,
    resolution: ConflictResolution,
    db: Database,
) -> MatchReport:
    connection, session = _immediate_session(db)
    try:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        if match is None:
            raise CorrectionError("match_not_found", "match was not found", 404)
        current_report = _current_report(session, match.id)
        current = current_report.revision if current_report is not None else 0
        if current != resolution.expected_report_revision:
            raise RevisionConflict(resolution.expected_report_revision, current)
        conflict = session.scalar(
            select(Correction).where(
                Correction.public_id == correction_id,
                Correction.match_id == match.id,
                Correction.status == CorrectionStatus.CONFLICT,
            )
        )
        if conflict is None:
            raise CorrectionError("conflict_not_found", "correction conflict was not found", 404)
        if current_report is None or (
            conflict.prediction_revision != current_report.prediction_revision
            and conflict.expected_report_revision != current
        ):
            raise CorrectionConflict(
                "correction conflict is stale; reload conflicts for the current prediction revision"
            )
        original = (
            session.get(Correction, conflict.supersedes_correction_id)
            if conflict.supersedes_correction_id is not None
            else None
        )
        if original is None:
            raise CorrectionConflict("correction conflict has no source correction")
        if session.scalar(
            select(Correction).where(Correction.supersedes_correction_id == conflict.id)
        ) is not None:
            raise CorrectionConflict("correction conflict was already resolved")
        details = conflict.conflict_details or {}
        candidates = list(details.get("candidate_ids", []))
        if (
            resolution.resolution == "select"
            and resolution.candidate_id not in candidates
        ):
            raise CorrectionConflict(
                "selected candidate is not part of the conflict"
            )
        if resolution.resolution == "reject":
            row = Correction(
                match=match,
                supersedes_correction_id=conflict.id,
                command_type="reject_reapplication",
                target_type=conflict.target_type,
                target_id=conflict.target_id,
                prediction_revision=conflict.prediction_revision,
                expected_report_revision=current,
                before_payload=conflict.before_payload,
                after_payload=conflict.before_payload,
                reason=resolution.reason,
                source_timestamp_us=conflict.source_timestamp_us,
                source_evidence_ids=list(conflict.source_evidence_ids),
                status=CorrectionStatus.SUPERSEDED,
            )
            session.add(row)
            session.flush()
            existing = _current_report(session, match.id)
            assert existing is not None
            report = _report_from_row(match_id, existing)
        else:
            assert resolution.candidate_id is not None
            selection_target_type = str(
                details.get("selection_target_type", conflict.target_type)
            )
            target_id = resolution.candidate_id
            selected_review: ErrorCandidate | None = None
            if selection_target_type == "error_candidate":
                target_candidates = list(
                    details.get("target_candidate_ids", [])
                )
                if len(target_candidates) != 1:
                    raise CorrectionConflict(
                        "review-entity selection lacks a unique prediction target"
                    )
                target_id = str(target_candidates[0])
                selected_review = session.scalar(
                    select(ErrorCandidate).where(
                        ErrorCandidate.match_id == match.id,
                        ErrorCandidate.prediction_revision
                        == conflict.prediction_revision,
                        ErrorCandidate.prediction_id
                        == resolution.candidate_id,
                        ErrorCandidate.target_type == conflict.target_type,
                        ErrorCandidate.target_prediction_id == target_id,
                    )
                )
                if selected_review is None:
                    raise CorrectionConflict(
                        "selected review entity is no longer available"
                    )
            before = canonical_target(
                session,
                match,
                conflict.target_type,
                target_id,
                conflict.prediction_revision,
                current,
            )
            if before is None:
                raise CorrectionConflict(
                    "selected prediction is no longer available"
                )
            review_remap = (
                _ReviewRemap(
                    "error_candidate",
                    selected_review.prediction_id,
                    None,
                    [selected_review.prediction_id],
                    "selected_review_entity",
                )
                if selected_review is not None
                else _remap_review_entity(
                    session,
                    original,
                    conflict.prediction_revision,
                    target_id,
                )
            )
            if review_remap.reason is not None:
                raise CorrectionConflict(
                    f"selected prediction has {review_remap.reason.replace('_', ' ')}"
                )
            error_candidate = (
                selected_review
                if selected_review is not None
                else session.scalar(
                    select(ErrorCandidate).where(
                        ErrorCandidate.match_id == match.id,
                        ErrorCandidate.prediction_revision
                        == conflict.prediction_revision,
                        ErrorCandidate.prediction_id
                        == review_remap.entity_id,
                    )
                )
                if review_remap.entity_type == "error_candidate"
                and review_remap.entity_id is not None
                else None
            )
            row = Correction(
                match=match,
                error_candidate=error_candidate,
                supersedes_correction_id=conflict.id,
                command_type=conflict.command_type,
                target_type=conflict.target_type,
                target_id=target_id,
                prediction_revision=conflict.prediction_revision,
                expected_report_revision=current,
                before_payload=before,
                after_payload={**before, **_changed_values(conflict)},
                reason=resolution.reason,
                source_timestamp_us=before.get("source_timestamp_us"),
                source_evidence_ids=list(before.get("source_evidence_ids", [])),
                review_entity_type=review_remap.entity_type,
                review_entity_id=review_remap.entity_id,
                review_decision=original.review_decision,
                status=CorrectionStatus.ACTIVE,
                conflict_details={
                    "resolved_from": conflict.public_id,
                    "review_strategy": review_remap.strategy,
                },
            )
            session.add(row)
            session.flush()
            report = build_report_in_session(
                session,
                match,
                current + 1,
                prediction_revision=conflict.prediction_revision,
                correction_id=row.id,
                invalidated=set(SECTION_NAMES),
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
