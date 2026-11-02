"""On-demand estimates from the selected report's immutable observation artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from squashvision.analytics import canonical_state_for_report
from squashvision.models import AnalysisJob, AssetKind, Calibration, JobChunk, Match, MediaAsset, ReportRevision, Stage, StagePublication
from squashvision.schemas import ApiError, ErrorResponse, TrackingStatsDetail, TrackingTimelineDetail
from squashvision.tracking_stats import FloorProjection, ball_speed_stats, contact_stats, movement_stats, source_time
from squashvision.tracking_timeline import build_tracking_timeline

router = APIRouter(tags=["analysis"], responses={code: {"model": ErrorResponse} for code in (404, 409, 422, 500)})
_PLAYER_COLUMNS = ("player_id", "timestamp_us", "source_timestamp_us", "source_frame_index", "feet_x", "feet_y", "feet_uncertainty_px", "evidence", "ambiguous", "association_confidence", "detection_confidence")
_BALL_COLUMNS = ("timestamp_us", "source_timestamp_us", "source_frame_index", "source_width", "source_height", "x", "y", "probability", "candidate_count", "evidence", "visible", "ambiguous", "segment_id", "source_manifest_id")
_IMPACT_PLAYER_COLUMNS = (*_PLAYER_COLUMNS, "keypoints_x", "keypoints_y", "keypoints_confidence", "box_x1", "box_y1", "box_x2", "box_y2")


@contextmanager
def _verified(storage, path: str, size: int | None, checksum: str | None):
    relative = Path(path)
    if size is None or checksum is None:
        raise ValueError("artifact integrity metadata is missing")
    descriptor = storage.open_owned(relative, owned_paths=[relative])
    with os.fdopen(descriptor, "rb") as stream:
        if os.fstat(stream.fileno()).st_size != size:
            raise ValueError("artifact size mismatch")
        digest = hashlib.sha256()
        while block := stream.read(1024 * 1024):
            digest.update(block)
        if digest.hexdigest() != checksum:
            raise ValueError("artifact checksum mismatch")
        stream.seek(0)
        yield stream


def _rows(storage, chunks, columns, *, start_us=None, end_us=None):
    result = []
    for chunk in chunks:
        with _verified(storage, chunk.artifact_payload_path, chunk.artifact_payload_size, chunk.artifact_payload_sha256) as stream:
            parquet = pq.ParquetFile(stream)
            selected = [name for name in columns if name in parquet.schema_arrow.names]
            if "timestamp_us" not in selected:
                raise ValueError("artifact lacks exact timestamp")
            for batch in parquet.iter_batches(batch_size=4096, columns=selected):
                result.extend(row for row in batch.to_pylist()
                              if (start_us is None or source_time(row) >= start_us)
                              and (end_us is None or source_time(row) < end_us))
                if len(result) > 2_000_000:
                    raise ValueError("tracking stats exceed supported observation count")
    # Chunk overlap is not extra time travelled.
    unique = {}
    def quality(row):
        return (row.get("evidence") == "observed", not row.get("ambiguous", False),
                float(row.get("association_confidence") or row.get("probability") or 0),
                float(row.get("detection_confidence") or 0))
    for row in result:
        # Overlap can contain an interpolated row and an observed row for the
        # same logical sample. Missing frame provenance must not duplicate it.
        key = (row.get("player_id"), source_time(row))
        if key not in unique or quality(row) > quality(unique[key]):
            unique[key] = row
    return sorted(unique.values(), key=source_time)


def _projection(calibration, source, ball, profile) -> tuple[FloorProjection | None, str | None]:
    if calibration is None:
        return None, "Save court calibration to estimate metres."
    result = calibration.result
    matrix = result.get("imageToCourt", result.get("image_to_court"))
    if not result.get("calibrated") or not matrix or not calibration.capabilities.get("floorPosition", calibration.capabilities.get("floor_position", False)):
        return None, "Saved calibration does not support floor positions."
    if len(matrix) != 3 or any(len(row) != 3 or not all(math.isfinite(x) for x in row) for row in matrix):
        return None, "Saved calibration matrix is invalid."
    metadata = source.probe_metadata or {}
    # Legacy field names describe the actual inference image, which may be the
    # bounded proxy for high-resolution or rotated source media.
    dimensions = {(r.get("source_width"), r.get("source_height")) for r in ball
                  if r.get("source_width") and r.get("source_height")}
    if len(dimensions) > 1:
        return None, "Observation image dimensions changed within the selected report."
    if dimensions:
        width, height = next(iter(dimensions))
    elif profile in ("fast", "balanced"):
        width, height = calibration.frame_width, calibration.frame_height
    else:
        width, height = metadata.get("width"), metadata.get("height")
        if not width or not height or width > 1280 or height > 720 or metadata.get("rotation", 0) not in (0, 360):
            return None, "Inference image dimensions are unavailable for this historical player-only report."
    if not width or not height or not calibration.frame_width or not calibration.frame_height:
        return None, "Observation image dimensions cannot be matched to calibration."
    return FloorProjection(tuple(tuple(float(v) for v in row) for row in matrix), calibration.frame_width / width, calibration.frame_height / height), None


def _tracking_inputs(match_id: str, revision: int, request: Request,
                     calibration_revision: int | None = None):
    storage = request.app.state.storage
    with request.app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        if match is None:
            raise ApiError("match_not_found", "match was not found", 404)
        report = session.scalar(select(ReportRevision).where(ReportRevision.match_id == match.id, ReportRevision.revision == revision))
        if report is None:
            raise ApiError("report_not_found", "report revision was not found", 404)
        publication = session.scalar(select(StagePublication).where(StagePublication.match_id == match.id,
            StagePublication.stage == Stage.CLASSIFICATION, StagePublication.prediction_revision == report.prediction_revision).order_by(StagePublication.id.desc()).limit(1))
        if publication is None:
            raise ApiError("analysis_artifact_unavailable", "selected report has no published observations", 409)
        job = session.get(AnalysisJob, publication.analysis_job_id)
        if job is None or job.match_id != match.id:
            raise ApiError("analysis_artifact_unavailable", "selected report source is unavailable", 409)
        source = session.get(MediaAsset, job.source_media_asset_id)
        proxy = session.scalar(select(MediaAsset).where(MediaAsset.match_id == match.id, MediaAsset.kind == AssetKind.PROXY))
        if source is None or proxy is None:
            raise ApiError("analysis_artifact_unavailable", "selected report media is unavailable", 409)
        query = select(Calibration).where(Calibration.match_id == match.id, Calibration.media_asset_id == proxy.id)
        if calibration_revision is not None:
            query = query.where(Calibration.revision == calibration_revision)
        calibration = session.scalar(query.order_by(Calibration.revision.desc()).limit(1))
        if calibration_revision is not None and calibration is None:
            raise ApiError("calibration_not_found", "calibration revision was not found for this video", 404)
        # A later calibration invalidates mutable chunk status, not the old report's bytes.
        chunks = list(session.scalars(select(JobChunk).where(JobChunk.analysis_job_id == job.id,
            JobChunk.stage.in_([Stage.PLAYERS, Stage.BALL, Stage.EVENTS]), JobChunk.artifact_payload_path.is_not(None)).order_by(JobChunk.start_us, JobChunk.id)).all())
        by_stage = {stage: [c for c in chunks if c.stage == stage] for stage in (Stage.PLAYERS, Stage.BALL, Stage.EVENTS)}
        if not by_stage[Stage.PLAYERS]:
            raise ApiError("analysis_artifact_unavailable", "selected report has no player observations", 409)
        start_us = min(c.start_us for c in chunks)
        end_us = max(c.end_us for c in chunks)
        try:
            players = _rows(storage, by_stage[Stage.PLAYERS], _PLAYER_COLUMNS)
            ball = _rows(storage, by_stage[Stage.BALL], _BALL_COLUMNS)
            events = {}
            for chunk in by_stage[Stage.EVENTS]:
                with _verified(storage, chunk.artifact_payload_path, chunk.artifact_payload_size, chunk.artifact_payload_sha256) as stream:
                    for contact in json.load(stream).get("contacts", []):
                        events[contact["contact_id"]] = contact
            proxy_by_frame, proxy_end_by_frame = {}, {}
            previous_frame = None
            if proxy.timestamp_index_path:
                with _verified(storage, proxy.timestamp_index_path, proxy.timestamp_index_size, proxy.timestamp_index_sha256) as stream:
                    parquet = pq.ParquetFile(stream)
                    for batch in parquet.iter_batches(batch_size=4096, columns=["proxy_timestamp_us", "source_frame_index"]):
                        for row in batch.to_pylist():
                            frame, timestamp = row["source_frame_index"], row["proxy_timestamp_us"]
                            if previous_frame is not None:
                                proxy_end_by_frame[previous_frame] = timestamp
                            previous_frame = frame
                            proxy_by_frame[frame] = min(timestamp, proxy_by_frame.get(frame, timestamp))
            if previous_frame is not None and proxy.duration_us is not None:
                proxy_end_by_frame[previous_frame] = proxy.duration_us
        except (OSError, ValueError, TypeError, KeyError, pa.ArrowException) as error:
            raise ApiError("tracking_stats_artifact_invalid", "selected report observations could not be verified", 409) from error
        projection, calibration_reason = _projection(calibration, source, ball, job.processing_profile.value)
        # Published classification and human corrections take precedence for matched events.
        state = canonical_state_for_report(session, match, report)
        for shot in state.shots:
            for evidence_id in shot["source_evidence_ids"]:
                if evidence_id in events:
                    event = events[evidence_id]
                    event["timestamp_us"] = shot["source_timestamp_us"]
                    event["selected_hitter"] = {"near": "A", "far": "B"}.get(shot["hitter"], "unknown")
        return {"report_revision":revision, "prediction_revision":report.prediction_revision,
                "calibration_revision":calibration.revision if calibration else None,
                "calibration_available":projection is not None, "calibration_reason":calibration_reason,
                "start_us":start_us, "end_us":end_us, "players":players, "ball":ball,
                "events":list(events.values()), "projection":projection, "calibration":calibration,
                "proxy_by_frame":proxy_by_frame, "proxy_end_by_frame":proxy_end_by_frame,
                "player_chunks":by_stage[Stage.PLAYERS], "source":source}


@router.get("/matches/{match_id}/reports/{revision}/tracking-stats", response_model=TrackingStatsDetail, operation_id="getTrackingStats")
def get_tracking_stats(match_id: str, revision: int, request: Request,
                       calibration_revision: int | None = Query(default=None, alias="calibrationRevision", ge=1)) -> TrackingStatsDetail:
    data = _tracking_inputs(match_id, revision, request, calibration_revision)
    contacts = contact_stats(data["events"], data["players"], data["ball"], data["projection"], data["proxy_by_frame"])
    duration_us = data["end_us"]-data["start_us"]
    return TrackingStatsDetail(**{key:data[key] for key in ("report_revision", "prediction_revision", "calibration_revision", "calibration_available", "calibration_reason", "start_us", "end_us")},
        players=movement_stats(data["players"], data["projection"], duration_us, Counter(c.hitter for c in contacts if c.hitter)),
        contacts=contacts, ball_speed=ball_speed_stats(data["ball"], data["projection"], duration_us),
        coordinate_system="Metres from the front-left floor corner: x across the 6.40 m width, y toward the back wall over 9.75 m.",
        limitations=[
            "A/B are model track labels, not verified person identities; identity switches remain possible.",
            "Contact times and hitters are inferred from saved ball/pose/audio evidence. Locations show player feet near contact, not the ball's 3D impact point.",
            "Tracked movement is a partial path: ambiguous/interpolated/out-of-court/high-uncertainty samples and gaps over 120 ms are excluded; three-point median smoothing, 200 ms sampling, and a 12 m/s jump filter reduce jitter.",
            "Ball speed is apparent motion projected onto the court floor, not actual 3D or racket-launch speed. Airborne height and camera geometry can distort it in either direction.",
            "These estimates apply the displayed saved calibration to the selected report's observations. They do not modify its original published metrics.",
        ])


def _derive_impacts(players, ball, projection, calibration_revision):
    from squashvision.playback_impacts import derive_playback_impacts
    return derive_playback_impacts(players, ball, projection, calibration_revision=calibration_revision)


@router.get("/matches/{match_id}/reports/{revision}/tracking-timeline", response_model=TrackingTimelineDetail, operation_id="getTrackingTimeline")
def get_tracking_timeline(match_id: str, revision: int, request: Request,
                         start_us: int = Query(default=0, alias="startUs", ge=0),
                         end_us: int = Query(default=120_000_000, alias="endUs", ge=1),
                         calibration_revision: int | None = Query(default=None, alias="calibrationRevision", ge=1)) -> TrackingTimelineDetail:
    if end_us <= start_us or end_us-start_us > 120_000_000:
        raise ApiError("invalid_tracking_window", "playback windows must be positive and at most 120 seconds", 422)
    data = _tracking_inputs(match_id, revision, request, calibration_revision)
    # Ownership is folded over ordered impact history before response-window
    # filtering. Keep the future halo only for local velocity support.
    lower, upper = 0, end_us+1_000_000
    chunks = [chunk for chunk in data["player_chunks"] if chunk.start_us < upper and chunk.end_us > lower]
    try:
        pose = _rows(request.app.state.storage, chunks, _IMPACT_PLAYER_COLUMNS, start_us=lower, end_us=upper)
    except (OSError, ValueError, TypeError, KeyError, pa.ArrowException) as error:
        raise ApiError("tracking_stats_artifact_invalid", "selected report pose observations could not be verified", 409) from error
    ball = [row for row in data["ball"] if lower <= source_time(row) < upper]
    impacts = _derive_impacts(pose, ball, data["projection"], data["calibration_revision"])
    return build_tracking_timeline(data, impacts, start_us, end_us)
