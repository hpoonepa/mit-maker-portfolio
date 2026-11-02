from __future__ import annotations

from fastapi import APIRouter, Request

from squashvision.corrections import (
    CorrectionError,
    apply_correction,
    list_conflicts,
    RevisionConflict,
    resolve_conflict,
)
from squashvision.db import Database
from squashvision.schemas import (
    ApiError,
    ConflictResolution,
    CorrectionCommand,
    CorrectionConflictDetail,
    CorrectionConflictList,
    ErrorResponse,
    EvidenceCandidateDetail,
    MatchReport,
)

router = APIRouter(
    prefix="/matches",
    tags=["corrections"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)

def _error(error: CorrectionError) -> ApiError:
    details = (
        {"expectedRevision": error.expected, "currentRevision": error.current}
        if isinstance(error, RevisionConflict)
        else None
    )
    return ApiError(error.code, error.message, error.status_code, details=details)


@router.post(
    "/{match_id}/corrections",
    response_model=MatchReport,
    operation_id="createCorrection",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_correction(
    match_id: str, command: CorrectionCommand, request: Request
) -> MatchReport:
    if command.match_id != match_id:
        raise _error(
            CorrectionError(
                "match_id_mismatch",
                "path match ID and correction match ID must agree",
                422,
            )
        )
    database: Database = request.app.state.database
    try:
        return apply_correction(command, database)
    except CorrectionError as error:
        raise _error(error) from error


@router.get(
    "/{match_id}/correction-conflicts",
    response_model=CorrectionConflictList,
    operation_id="listCorrectionConflicts",
    responses={404: {"model": ErrorResponse}},
)
def get_conflicts(match_id: str, request: Request) -> CorrectionConflictList:
    database: Database = request.app.state.database
    try:
        return CorrectionConflictList(
            conflicts=[
                CorrectionConflictDetail(
                    correction_id=item.correction_id,
                    reason=item.reason,
                    candidate_ids=item.candidate_ids,
                    candidates=[
                        EvidenceCandidateDetail(**candidate)
                        for candidate in item.candidates
                    ],
                )
                for item in list_conflicts(match_id, database)
            ]
        )
    except CorrectionError as error:
        raise _error(error) from error


@router.post(
    "/{match_id}/correction-conflicts/{correction_id}/resolve",
    response_model=MatchReport,
    operation_id="resolveCorrectionConflict",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def resolve_correction_conflict(
    match_id: str,
    correction_id: str,
    resolution: ConflictResolution,
    request: Request,
) -> MatchReport:
    database: Database = request.app.state.database
    try:
        return resolve_conflict(match_id, correction_id, resolution, database)
    except CorrectionError as error:
        raise _error(error) from error
