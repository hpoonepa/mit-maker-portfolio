"""Image-only playing-area constraints; these never establish court calibration."""
import cv2
import numpy as np
from fastapi import APIRouter, Request
from sqlalchemy import select, text

from squashvision.models import AnalysisJob, AssetKind, JobStatus, Match, MediaAsset
from squashvision.schemas import (
    ApiError, CalibrationSize, ErrorResponse, PlayerRoiDetail, PlayerRoiSaveRequest,
)

router = APIRouter(tags=["analysis"], responses={
    code: {"model": ErrorResponse} for code in (404, 409, 422, 500)
})


def _source(session, match_id: str):
    match = session.scalar(select(Match).where(Match.public_id == match_id))
    if match is None:
        raise ApiError("match_not_found", "match was not found", 404)
    asset = session.scalar(select(MediaAsset).where(
        MediaAsset.match_id == match.id, MediaAsset.kind == AssetKind.ORIGINAL,
    ))
    if asset is None or asset.checksum_sha256 is None or not asset.probe_metadata:
        raise ApiError("media_metadata_missing", "source media is not prepared", 409)
    width, height = asset.probe_metadata["width"], asset.probe_metadata["height"]
    if abs(asset.probe_metadata.get("rotation", 0)) % 180 == 90:
        width, height = height, width
    return match, asset, CalibrationSize(width=width, height=height)


def _detail(match, asset, frame_size):
    if match.player_roi is not None:
        detail = PlayerRoiDetail.model_validate(match.player_roi)
        if detail.source_sha256 == asset.checksum_sha256 and detail.frame_size == frame_size:
            return detail
        raise ApiError("player_roi_source_mismatch", "playing area belongs to different source media", 409)
    return PlayerRoiDetail(revision=0, source_sha256=asset.checksum_sha256,
                           frame_size=frame_size, points=None)


@router.get("/matches/{match_id}/player-roi", response_model=PlayerRoiDetail,
            operation_id="getPlayerRoi")
def get_player_roi(match_id: str, request: Request):
    with request.app.state.database.session() as session:
        return _detail(*_source(session, match_id))


@router.put("/matches/{match_id}/player-roi", response_model=PlayerRoiDetail,
            operation_id="savePlayerRoi")
def save_player_roi(match_id: str, body: PlayerRoiSaveRequest, request: Request):
    with request.app.state.database.session() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        match, asset, frame_size = _source(session, match_id)
        current = _detail(match, asset, frame_size)
        if current.revision != body.expected_revision:
            raise ApiError("player_roi_revision_conflict", "playing area changed; reload before saving", 409)
        if body.source_sha256 != asset.checksum_sha256 or body.frame_size != frame_size:
            raise ApiError("player_roi_source_mismatch", "playing area must match the source frame and checksum", 409)
        active = session.scalar(select(AnalysisJob.id).where(
            AnalysisJob.match_id == match.id,
            AnalysisJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED)),
        ).limit(1))
        if active is not None:
            raise ApiError("active_analysis_exists", "finish or cancel analysis before editing the playing area", 409)
        if body.points is not None:
            if any(point.x > frame_size.width - 1 or point.y > frame_size.height - 1 for point in body.points):
                raise ApiError("invalid_player_roi", "playing area points must be inside the source frame", 422)
            polygon = np.asarray([(point.x, point.y) for point in body.points], dtype=np.float32)
            if not cv2.isContourConvex(polygon) or cv2.contourArea(polygon) < 16:
                raise ApiError("invalid_player_roi", "playing area must be a nonzero convex polygon in boundary order", 422)
        result = PlayerRoiDetail(revision=current.revision + 1,
            source_sha256=body.source_sha256, frame_size=body.frame_size, points=body.points)
        match.player_roi = result.model_dump(mode="json", by_alias=True)
        return result
