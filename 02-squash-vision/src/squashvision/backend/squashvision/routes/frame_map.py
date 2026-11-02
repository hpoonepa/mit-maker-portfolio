"""Bounded, exact proxy-frame provenance for synchronized video overlays."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from squashvision.models import AssetKind, Match, MediaAsset
from squashvision.schemas import ApiError, ErrorResponse, FrameMapDetail, FrameMapItem

MAX_WINDOW_US = 120_000_000
MAX_WINDOW_ROWS = 3_600
_COLUMNS = ("proxy_timestamp_us", "source_timestamp_us", "source_frame_index")

router = APIRouter(tags=["matches"], responses={
    code: {"model": ErrorResponse} for code in (404, 409, 422, 500)
})


def _read_window(stream: BinaryIO, start_us: int, end_us: int) -> list[FrameMapItem]:
    parquet = pq.ParquetFile(stream)
    schema = parquet.schema_arrow
    if any(name not in schema.names or schema.field(name).type != pa.int64() for name in _COLUMNS):
        raise ValueError("invalid timestamp-index schema")
    proxy_column = schema.get_field_index(_COLUMNS[0])
    rows: list[FrameMapItem] = []
    for group_index in range(parquet.metadata.num_row_groups):
        statistics = parquet.metadata.row_group(group_index).column(proxy_column).statistics
        if statistics is not None and statistics.has_min_max:
            if statistics.max < start_us or statistics.min >= end_us:
                continue
        # Fixed-size batches keep decoding bounded even for older large row groups.
        for batch in parquet.iter_batches(batch_size=4096, row_groups=[group_index], columns=list(_COLUMNS)):
            values = batch.to_pydict()
            for proxy, source, frame in zip(*(values[name] for name in _COLUMNS), strict=True):
                if proxy is None:
                    raise ValueError("timestamp-index contains null timestamps")
                if start_us <= proxy < end_us:
                    rows.append(FrameMapItem(proxy_timestamp_us=proxy,
                        source_timestamp_us=source, source_frame_index=frame))
                    if len(rows) > MAX_WINDOW_ROWS:
                        raise ValueError("timestamp-index exceeds the 30 fps proxy bound")
    rows.sort(key=lambda row: row.proxy_timestamp_us)
    for previous, current in zip(rows, rows[1:]):
        if (current.proxy_timestamp_us <= previous.proxy_timestamp_us
            or current.source_timestamp_us < previous.source_timestamp_us
            or current.source_frame_index < previous.source_frame_index):
            raise ValueError("timestamp-index provenance is not ordered")
    return rows


@router.get("/matches/{match_id}/media/frame-map", response_model=FrameMapDetail,
            operation_id="getMatchFrameMap")
def get_match_frame_map(
    match_id: str,
    request: Request,
    start_us: int = Query(alias="startUs", ge=0, le=9_007_199_254_740_991),
    end_us: int = Query(alias="endUs", ge=0, le=9_007_199_254_740_991),
) -> FrameMapDetail:
    """Return all exact mappings in the half-open proxy-time window [startUs,endUs)."""
    if end_us <= start_us or end_us - start_us > MAX_WINDOW_US:
        raise ApiError("invalid_frame_map_window", "frame-map windows must be positive and at most 120 seconds", 422)
    with request.app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        if match is None:
            raise ApiError("match_not_found", "match was not found", 404)
        proxy = session.scalar(select(MediaAsset).where(
            MediaAsset.match_id == match.id, MediaAsset.kind == AssetKind.PROXY,
        ))
        if (proxy is None or proxy.timestamp_index_path is None
            or proxy.timestamp_index_sha256 is None or proxy.timestamp_index_size is None):
            raise ApiError("frame_map_unavailable", "the exact proxy frame map is not available yet", 409)
        relative = Path(proxy.timestamp_index_path)
        expected_size, expected_hash = proxy.timestamp_index_size, proxy.timestamp_index_sha256

    try:
        if relative.parts[:1] != ("timestamp-index",) or relative.suffix != ".parquet":
            raise ValueError("timestamp-index path is outside its managed directory")
        descriptor = request.app.state.storage.open_owned(relative, owned_paths=[relative])
        with os.fdopen(descriptor, "rb") as stream:
            if os.fstat(stream.fileno()).st_size != expected_size:
                raise ValueError("timestamp-index size changed")
            digest = hashlib.sha256()
            while block := stream.read(1024 * 1024):
                digest.update(block)
            if digest.hexdigest() != expected_hash:
                raise ValueError("timestamp-index checksum changed")
            stream.seek(0)
            items = _read_window(stream, start_us, end_us)
    except (OSError, ValueError, TypeError, pa.ArrowException):
        raise ApiError("frame_map_invalid", "the exact proxy frame map could not be verified; re-import the video", 409) from None
    return FrameMapDetail(start_us=start_us, end_us=end_us, items=items)
