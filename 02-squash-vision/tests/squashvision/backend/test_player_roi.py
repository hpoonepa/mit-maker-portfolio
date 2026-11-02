from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from squashvision.app import create_app
from squashvision.models import AnalysisJob, AssetKind, Calibration, Match, MediaAsset, ProcessingProfile
from squashvision.settings import Settings


@pytest.fixture
def roi_client(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path))
    with app.state.database.session() as session:
        match = Match(name="Real camera source")
        source = MediaAsset(match=match, kind=AssetKind.ORIGINAL,
            relative_path="videos/original/source.mp4", checksum_sha256="a" * 64,
            probe_metadata={"width": 1280, "height": 720, "rotation": 0})
        session.add(source)
        session.flush()
        match_id = match.public_id
    with TestClient(app) as client:
        yield client, app, match_id


def payload():
    return {"expectedRevision": 0, "sourceSha256": "a" * 64,
            "frameSize": {"width": 1280, "height": 720},
            "points": [{"x": x, "y": y} for x, y in [(374, 384), (902, 384), (1075, 719), (202, 719)]]}


def test_player_roi_persists_revision_source_and_never_creates_calibration(roi_client):
    client, app, match_id = roi_client
    path = f"/api/v1/matches/{match_id}/player-roi"
    assert client.get(path).json()["points"] is None
    response = client.put(path, json=payload())
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] == 1
    assert saved["purpose"] == "player_detection_only"
    assert client.get(path).json() == saved
    assert client.put(path, json=payload()).status_code == 409
    with app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Calibration)) == 0
    disabled = client.put(path, json={**payload(), "expectedRevision": 1, "points": None})
    assert disabled.status_code == 200
    assert disabled.json()["points"] is None and disabled.json()["revision"] == 2


@pytest.mark.parametrize("change,status", [
    ({"sourceSha256": "b" * 64}, 409),
    ({"frameSize": {"width": 640, "height": 360}}, 409),
    ({"points": [{"x": 0, "y": 0}, {"x": 1280, "y": 0}, {"x": 0, "y": 720}]}, 422),
    ({"points": [{"x": 0, "y": 0}, {"x": 100, "y": 100}, {"x": 100, "y": 0}, {"x": 0, "y": 100}]}, 422),
])
def test_player_roi_rejects_stale_source_bounds_and_crossed_polygon(roi_client, change, status):
    client, _, match_id = roi_client
    response = client.put(f"/api/v1/matches/{match_id}/player-roi", json={**payload(), **change})
    assert response.status_code == status, response.text


def test_player_roi_cannot_change_during_an_active_job(roi_client):
    client, app, match_id = roi_client
    with app.state.database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        source = session.scalar(select(MediaAsset).where(MediaAsset.match_id == match.id))
        session.add(AnalysisJob(match=match, source_media_asset=source, processing_profile=ProcessingProfile.MAXIMUM))
    response = client.put(f"/api/v1/matches/{match_id}/player-roi", json=payload())
    assert response.status_code == 409
    assert response.json()["code"] == "active_analysis_exists"
