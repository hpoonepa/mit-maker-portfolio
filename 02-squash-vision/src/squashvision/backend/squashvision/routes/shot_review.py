from fastapi import APIRouter, Request
from sqlalchemy import select
from squashvision.models import Match, ReportRevision, MediaAsset, AssetKind
from squashvision.schemas import ApiError, ErrorResponse
from squashvision.shot_review import ShotReviewDocument, SaveShotReview, read_review, save_review

router = APIRouter(tags=["shot-review"], responses={404:{"model":ErrorResponse},409:{"model":ErrorResponse},422:{"model":ErrorResponse}})

def _context(request, match_id, revision):
    with request.app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        if match is None: raise ApiError("match_not_found", "Match was not found", 404)
        report = session.scalar(select(ReportRevision).where(ReportRevision.match_id == match.id, ReportRevision.revision == revision))
        if report is None: raise ApiError("report_not_found", "Report was not found", 404)
        proxy = session.scalar(select(MediaAsset).where(MediaAsset.match_id == match.id, MediaAsset.kind == AssetKind.PROXY))
        return request.app.state.settings.data_dir / "shot-reviews.sqlite3", proxy.duration_us if proxy else None

@router.get("/matches/{match_id}/reports/{revision}/shot-review", response_model=ShotReviewDocument, operation_id="getShotReview")
def get_shot_review(match_id: str, revision: int, request: Request):
    path, _ = _context(request, match_id, revision)
    return read_review(path, match_id, revision)

@router.put("/matches/{match_id}/reports/{revision}/shot-review", response_model=ShotReviewDocument, operation_id="saveShotReview")
def put_shot_review(match_id: str, revision: int, command: SaveShotReview, request: Request):
    path, duration = _context(request, match_id, revision)
    if duration is None: raise ApiError("review_media_unavailable", "Prepared video is required to mark shots", 409)
    for shot in command.shots:
        times = [shot.contact_us] + [i.time_us for i in [shot.wall, shot.landing] if i is not None]
        if any(t >= duration for t in times): raise ApiError("review_time_outside_video", "Shot marker is outside the video", 422)
    return save_review(path, match_id, revision, command)
