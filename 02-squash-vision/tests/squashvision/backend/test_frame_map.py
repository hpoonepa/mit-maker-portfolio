from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from squashvision.app import create_app
from squashvision.models import AssetKind, Match, MediaAsset
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
import squashvision.routes.frame_map as frame_map_routes


@pytest.fixture
def frame_map_client(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path))
    stored = app.state.storage.allocate_timestamp_index()
    # A 25 fps source represented by a 30 fps proxy: source frames may repeat.
    table = pa.table({
        "proxy_timestamp_us": pa.array([0, 33333, 66667, 100000, 133333, 166667, 200000], type=pa.int64()),
        "source_timestamp_us": pa.array([0, 40000, 80000, 120000, 120000, 160000, 200000], type=pa.int64()),
        "source_frame_index": pa.array([0, 1, 2, 3, 3, 4, 5], type=pa.int64()),
    })
    pq.write_table(table, stored.absolute, row_group_size=2)
    data = stored.absolute.read_bytes()
    with app.state.database.session() as session:
        match = Match(name="25 fps source / 30 fps proxy")
        proxy = MediaAsset(match=match, kind=AssetKind.PROXY,
            relative_path="videos/proxy/test.mp4", duration_us=240000,
            timestamp_index_path=str(stored.relative), timestamp_index_size=len(data),
            timestamp_index_sha256=hashlib.sha256(data).hexdigest())
        session.add(proxy)
        session.flush()
        match_id = match.public_id
    with TestClient(app) as client:
        yield client, app, match_id, stored


def endpoint(match_id: str) -> str:
    return f"/api/v1/matches/{match_id}/media/frame-map"


def test_frame_map_preserves_exact_25_to_30_fps_provenance_and_window_edges(frame_map_client):
    client, _, match_id, _ = frame_map_client
    response = client.get(endpoint(match_id), params={"startUs": 100000, "endUs": 200000})
    assert response.status_code == 200, response.text
    assert response.json() == {"startUs": 100000, "endUs": 200000, "items": [
        {"proxyTimestampUs": 100000, "sourceTimestampUs": 120000, "sourceFrameIndex": 3},
        {"proxyTimestampUs": 133333, "sourceTimestampUs": 120000, "sourceFrameIndex": 3},
        {"proxyTimestampUs": 166667, "sourceTimestampUs": 160000, "sourceFrameIndex": 4},
    ]}
    empty = client.get(endpoint(match_id), params={"startUs": 240000, "endUs": 300000})
    assert empty.status_code == 200 and empty.json()["items"] == []


@pytest.mark.parametrize("params", [
    {"startUs": -1, "endUs": 10}, {"startUs": 1, "endUs": 1},
    {"startUs": 2, "endUs": 1}, {"startUs": 0, "endUs": 120000001},
    {"endUs": 100}, {"startUs": 0, "endUs": "1.5"},
])
def test_frame_map_rejects_invalid_or_unbounded_windows(frame_map_client, params):
    client, _, match_id, _ = frame_map_client
    assert client.get(endpoint(match_id), params=params).status_code == 422


def test_frame_map_skips_parquet_groups_outside_requested_window(frame_map_client, monkeypatch):
    client, _, match_id, _ = frame_map_client
    original = pq.ParquetFile
    read_groups = []

    class RecordingParquet:
        def __init__(self, stream):
            self.inner = original(stream)
            self.schema_arrow = self.inner.schema_arrow
            self.metadata = self.inner.metadata

        def iter_batches(self, **kwargs):
            read_groups.extend(kwargs["row_groups"])
            return self.inner.iter_batches(**kwargs)

    monkeypatch.setattr(frame_map_routes.pq, "ParquetFile", RecordingParquet)
    response = client.get(endpoint(match_id), params={"startUs": 100000, "endUs": 133333})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert read_groups == [1]


def test_frame_map_reports_missing_match_and_missing_index(frame_map_client):
    client, app, match_id, _ = frame_map_client
    params = {"startUs": 0, "endUs": 120000000}
    assert client.get(endpoint("missing"), params=params).status_code == 404
    with app.state.database.session() as session:
        proxy = session.scalar(select(MediaAsset).where(MediaAsset.kind == AssetKind.PROXY))
        proxy.timestamp_index_path = None
    response = client.get(endpoint(match_id), params=params)
    assert response.status_code == 409 and response.json()["code"] == "frame_map_unavailable"


@pytest.mark.parametrize("damage", ["checksum", "missing", "symlink", "parent_symlink", "traversal", "invalid_parquet"])
def test_frame_map_rejects_corrupt_or_unsafe_index(frame_map_client, tmp_path, damage):
    client, app, match_id, stored = frame_map_client
    original = stored.absolute.read_bytes()
    if damage == "checksum":
        stored.absolute.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    elif damage == "missing":
        stored.absolute.unlink()
    elif damage == "symlink":
        target = tmp_path / "outside.parquet"
        target.write_bytes(original)
        stored.absolute.unlink()
        stored.absolute.symlink_to(target)
    elif damage == "parent_symlink":
        target = tmp_path / "outside-index"
        stored.absolute.parent.rename(target)
        stored.absolute.parent.symlink_to(target, target_is_directory=True)
    elif damage == "traversal":
        with app.state.database.session() as session:
            proxy = session.scalar(select(MediaAsset).where(MediaAsset.kind == AssetKind.PROXY))
            proxy.timestamp_index_path = "timestamp-index/../../outside.parquet"
    else:
        stored.absolute.write_bytes(b"not parquet")
        with app.state.database.session() as session:
            proxy = session.scalar(select(MediaAsset).where(MediaAsset.kind == AssetKind.PROXY))
            proxy.timestamp_index_size = len(b"not parquet")
            proxy.timestamp_index_sha256 = hashlib.sha256(b"not parquet").hexdigest()
    response = client.get(endpoint(match_id), params={"startUs": 0, "endUs": 1000000})
    assert response.status_code == 409 and response.json()["code"] == "frame_map_invalid"


def test_frame_map_reads_verified_open_descriptor_after_path_replacement(frame_map_client, monkeypatch):
    client, app, match_id, stored = frame_map_client
    original_open = LocalStorage.open_owned

    def swap_after_open(self, relative, *, owned_paths):
        descriptor = original_open(self, relative, owned_paths=owned_paths)
        replacement = stored.absolute.with_suffix(".replacement")
        replacement.write_bytes(b"untrusted replacement")
        replacement.replace(stored.absolute)
        return descriptor

    monkeypatch.setattr(LocalStorage, "open_owned", swap_after_open)
    response = client.get(endpoint(match_id), params={"startUs": 0, "endUs": 1000000})
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 7


def test_frame_map_sorts_rows_and_rejects_duplicate_proxy_timestamps(frame_map_client):
    client, app, match_id, stored = frame_map_client
    rows = pq.read_table(stored.absolute).to_pylist()
    for duplicate in (False, True):
        selected = list(reversed(rows)) + ([rows[0]] if duplicate else [])
        pq.write_table(pa.Table.from_pylist(selected), stored.absolute)
        data = stored.absolute.read_bytes()
        with app.state.database.session() as session:
            proxy = session.scalar(select(MediaAsset).where(MediaAsset.kind == AssetKind.PROXY))
            proxy.timestamp_index_size = len(data)
            proxy.timestamp_index_sha256 = hashlib.sha256(data).hexdigest()
        response = client.get(endpoint(match_id), params={"startUs": 0, "endUs": 1000000})
        if duplicate:
            assert response.status_code == 409
        else:
            assert response.status_code == 200
            assert [row["proxyTimestampUs"] for row in response.json()["items"]] == sorted(row["proxy_timestamp_us"] for row in rows)
