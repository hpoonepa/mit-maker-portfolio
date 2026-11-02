from __future__ import annotations

import math
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
import av
import cv2
import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select, text

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))

from squashvision.app import create_app
from squashvision.calibration import (
    CALIBRATED_MEASUREMENT_THRESHOLD,
    CalibrationProposal,
    CourtCorrespondence,
    CourtKeypoints,
    CourtPoint,
    EvidenceLevel,
    ImagePoint,
    Size,
    detect_court,
    fit_calibration,
    VisibleSurface,
    project_floor,
)
from squashvision.db import Database
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    Calibration,
    JobChunk,
    JobStatus,
    Match,
    MediaAsset,
    ProcessingProfile,
    Stage,
    StageStatus,
)
from squashvision.media import create_proxy
from squashvision.settings import Settings


COURT = {
    "front_left": CourtPoint(0.0, 0.0),
    "front_right": CourtPoint(6.4, 0.0),
    "back_right": CourtPoint(6.4, 9.75),
    "back_left": CourtPoint(0.0, 9.75),
}
IMAGE = {
    "front_left": ImagePoint(280.0, 150.0),
    "front_right": ImagePoint(720.0, 170.0),
    "back_right": ImagePoint(930.0, 650.0),
    "back_left": ImagePoint(90.0, 630.0),
}


def keypoints(
    image: dict[str, ImagePoint] = IMAGE,
    court: dict[str, CourtPoint] = COURT,
) -> CourtKeypoints:
    return CourtKeypoints(
        tuple(
            CourtCorrespondence(label, image[label], court[label])
            for label in court
        )
    )


def render_court(
    *, partial: bool = False, internal_topology: bool = True
) -> np.ndarray:
    frame = np.zeros((720, 1024, 3), dtype=np.uint8)
    ordered = [
        (280, 150),
        (720, 170),
        (930, 650),
        (90, 630),
    ]
    edges = list(zip(ordered, ordered[1:] + ordered[:1], strict=True))
    if partial:
        edges = edges[:2]
    for start, end in edges:
        cv2.line(frame, start, end, (245, 245, 245), 7, cv2.LINE_AA)
    if internal_topology and not partial:
        short_left = (176, 414)
        short_right = (836, 434)
        short_center = (506, 424)
        back_center = (510, 640)
        cv2.line(
            frame, short_left, short_right, (245, 245, 245), 7, cv2.LINE_AA
        )
        cv2.line(
            frame, short_center, back_center, (245, 245, 245), 7, cv2.LINE_AA
        )
    return frame


def write_proxy(
    path: Path,
    frame: np.ndarray,
    *,
    frame_count: int = 4,
    rate: int = 2,
) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=rate)
        stream.width = frame.shape[1]
        stream.height = frame.shape[0]
        stream.pix_fmt = "yuv420p"
        for _ in range(frame_count):
            video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
            for packet in stream.encode(video_frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def prepared_app(tmp_path: Path) -> tuple[object, str, Path]:
    app = create_app(Settings(data_dir=tmp_path))
    proxy_path = tmp_path / "storage/videos/proxy/court.mp4"
    proxy_path.parent.mkdir(parents=True, exist_ok=True)
    write_proxy(proxy_path, render_court())
    with app.state.database.session() as session:
        match = Match(name="Calibration test")
        proxy = MediaAsset(
            match=match,
            kind=AssetKind.PROXY,
            relative_path="videos/proxy/court.mp4",
        )
        session.add_all([match, proxy])
        session.flush()
        return app, match.public_id, proxy_path


def api_keypoints(points: CourtKeypoints) -> list[dict[str, object]]:
    return [
        {
            "label": point.label,
            "image": {"x": point.image.x, "y": point.image.y},
            "court": {"xM": point.court.x_m, "yM": point.court.y_m},
        }
        for point in points.points
    ]


def migrate(engine: object, revision: str) -> None:
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def test_exact_homography_recovers_corners_and_projection_tightly() -> None:
    result = fit_calibration(keypoints(), Size(1024, 720))

    assert result.calibrated
    assert result.confidence >= CALIBRATED_MEASUREMENT_THRESHOLD
    assert result.rms_error_px == pytest.approx(0.0, abs=1e-8)
    assert result.max_error_px == pytest.approx(0.0, abs=1e-8)
    assert result.inlier_mask == (True, True, True, True)
    assert result.capabilities.image_space
    assert result.capabilities.floor_position
    assert result.capabilities.movement_distance
    assert result.capabilities.speed
    assert result.condition_number is not None and math.isfinite(result.condition_number)
    assert result.parameter_covariance is not None
    assert all(math.isfinite(value) for row in result.parameter_covariance for value in row)

    estimate = project_floor(ImagePoint(500.0, 400.0), result)
    source = np.array([[[500.0, 400.0]]], dtype=np.float64)
    expected = cv2.perspectiveTransform(
        source, np.asarray(result.image_to_court, dtype=np.float64)
    )[0, 0]
    assert estimate.value is not None
    assert estimate.value.x_m == pytest.approx(expected[0], abs=1e-8)
    assert estimate.value.y_m == pytest.approx(expected[1], abs=1e-8)
    assert estimate.inside_court
    assert estimate.evidence is EvidenceLevel.MEASURED
    assert all(math.isfinite(value) for row in estimate.covariance for value in row)


def test_ransac_rejects_an_extra_outlier_and_refits_inliers() -> None:
    points = list(keypoints().points)
    points.append(
        CourtCorrespondence(
            "service_box",
            ImagePoint(980.0, 40.0),
            CourtPoint(3.2, 4.875),
        )
    )

    result = fit_calibration(CourtKeypoints(tuple(points)), Size(1024, 720))

    assert result.calibrated
    assert result.inlier_mask == (True, True, True, True, False)
    assert result.residuals_px[-1] > 100
    assert max(result.residuals_px[:4]) < 1e-7
    assert result.confidence >= CALIBRATED_MEASUREMENT_THRESHOLD


def test_confidence_ignores_blank_wall_crop_and_padding_when_floor_view_is_unchanged() -> None:
    compressed = {label: ImagePoint(point.x, point.y * 0.3 + 350) for label, point in IMAGE.items()}
    original = fit_calibration(keypoints(compressed), Size(1024, 720))
    cropped = fit_calibration(keypoints({label: ImagePoint(point.x, point.y - 350)
        for label, point in compressed.items()}), Size(1024, 370))
    padded = fit_calibration(keypoints({label: ImagePoint(point.x + 200, point.y + 250)
        for label, point in compressed.items()}), Size(1424, 1220))
    assert original.calibrated and cropped.calibrated and padded.calibrated
    assert original.confidence == pytest.approx(cropped.confidence, abs=1e-6)
    assert original.confidence == pytest.approx(padded.confidence, abs=1e-6)
    assert original.condition_number == pytest.approx(cropped.condition_number, rel=1e-6)
    for result in (original, cropped, padded):
        assert result.rms_error_px < 1e-6


def test_floor_footprint_rejects_horizon_crossing_despite_exact_inlier_fit() -> None:
    homography = np.asarray([[80., 0., 300.], [0., 30., 100.], [0., -0.15, 1.]])
    floor_points = ((0., 0.), (6.4, 0.), (6.4, 4.), (0., 4.), (3.2, 2.))
    rows = []
    for index, (x, y) in enumerate(floor_points):
        point = homography @ np.asarray([x, y, 1.])
        rows.append(CourtCorrespondence(str(index), ImagePoint(*(point[:2]/point[2])), CourtPoint(x, y)))
    result = fit_calibration(CourtKeypoints(tuple(rows)), Size(2500, 1500))
    assert not result.calibrated
    assert 'invalid_projected_floor_footprint' in result.warnings
    assert not result.capabilities.movement_distance


def test_confidence_uses_only_ransac_inlier_coverage() -> None:
    inlier_court = (
        CourtPoint(2.0, 3.0),
        CourtPoint(4.0, 3.0),
        CourtPoint(4.0, 5.0),
        CourtPoint(2.0, 5.0),
        CourtPoint(3.0, 3.5),
        CourtPoint(3.5, 4.5),
    )
    points = [
        CourtCorrespondence(
            f"inlier-{index}",
            ImagePoint(450 + 60 * point.x_m, 250 + 40 * point.y_m),
            point,
        )
        for index, point in enumerate(inlier_court)
    ]
    points.extend(
        (
            CourtCorrespondence(
                "outlier-front-left", ImagePoint(1800, 900), CourtPoint(0, 0)
            ),
            CourtCorrespondence(
                "outlier-front-right", ImagePoint(100, 900), CourtPoint(6.4, 0)
            ),
            CourtCorrespondence(
                "outlier-back-right", ImagePoint(100, 100), CourtPoint(6.4, 9.75)
            ),
            CourtCorrespondence(
                "outlier-back-left", ImagePoint(1800, 100), CourtPoint(0, 9.75)
            ),
        )
    )

    result = fit_calibration(CourtKeypoints(tuple(points)), Size(1920, 1080))

    assert result.image_to_court is not None
    assert result.inlier_mask[:6] == (True,) * 6
    assert result.inlier_mask[6:] == (False,) * 4
    assert result.confidence < CALIBRATED_MEASUREMENT_THRESHOLD
    assert not result.capabilities.movement_distance
    assert not result.capabilities.speed


def test_fit_rejects_any_court_correspondence_outside_regulation_floor() -> None:
    points = list(keypoints().points)
    points.append(
        CourtCorrespondence(
            "outside", ImagePoint(500, 400), CourtPoint(6.41, 4.0)
        )
    )

    result = fit_calibration(CourtKeypoints(tuple(points)), Size(1024, 720))

    assert result.image_to_court is None
    assert result.confidence == 0
    assert result.warnings == ("court_point_out_of_bounds",)


@pytest.mark.parametrize(
    "points",
    [
        CourtKeypoints(
            (
                CourtCorrespondence("a", ImagePoint(10, 10), CourtPoint(0, 0)),
                CourtCorrespondence("b", ImagePoint(10, 10), CourtPoint(6.4, 0)),
                CourtCorrespondence("c", ImagePoint(30, 30), CourtPoint(6.4, 9.75)),
                CourtCorrespondence("d", ImagePoint(40, 40), CourtPoint(0, 9.75)),
            )
        ),
        CourtKeypoints(
            tuple(
                CourtCorrespondence(
                    str(index),
                    ImagePoint(float(index * 100), float(100 + index * 0.01)),
                    CourtPoint(float(index), float(index * 0.001)),
                )
                for index in range(4)
            )
        ),
        CourtKeypoints(
            (
                CourtCorrespondence("a", ImagePoint(0, 0), CourtPoint(0, 0)),
                CourtCorrespondence("b", ImagePoint(1e-7, 0), CourtPoint(6.4, 0)),
                CourtCorrespondence("c", ImagePoint(2e-7, 1e-9), CourtPoint(6.4, 9.75)),
                CourtCorrespondence("d", ImagePoint(3e-7, 2e-9), CourtPoint(0, 9.75)),
            )
        ),
    ],
)
def test_degenerate_inputs_return_finite_degraded_results(points: CourtKeypoints) -> None:
    result = fit_calibration(points, Size(1024, 720))

    assert not result.calibrated
    assert result.image_to_court is None
    assert result.confidence == 0
    assert result.capabilities.image_space
    assert not result.capabilities.floor_position
    assert not result.capabilities.movement_distance
    assert not result.capabilities.speed
    assert not any(
        isinstance(value, float) and not math.isfinite(value)
        for value in result.numeric_values()
    )
    unavailable = project_floor(ImagePoint(100, 100), result)
    assert unavailable.value is None
    assert unavailable.evidence is EvidenceLevel.UNAVAILABLE
    assert unavailable.warnings


def test_projection_does_not_clamp_and_gates_measurement_capabilities() -> None:
    exact = fit_calibration(keypoints(), Size(1024, 720))
    outside = project_floor(ImagePoint(-500, 400), exact)
    assert outside.value is not None
    assert not outside.inside_court
    assert outside.value.x_m < 0
    assert "outside_court" in outside.warnings

    clustered_image = {
        "front_left": ImagePoint(400, 300),
        "front_right": ImagePoint(470, 302),
        "back_right": ImagePoint(480, 360),
        "back_left": ImagePoint(390, 358),
    }
    estimated = fit_calibration(keypoints(clustered_image), Size(1920, 1080))
    assert estimated.image_to_court is not None
    assert 0 < estimated.confidence < CALIBRATED_MEASUREMENT_THRESHOLD
    assert estimated.capabilities.floor_position
    assert not estimated.capabilities.movement_distance
    assert not estimated.capabilities.speed
    projection = project_floor(ImagePoint(430, 330), estimated)
    assert projection.value is not None
    assert projection.evidence is EvidenceLevel.ESTIMATED
    assert "low_calibration_confidence" in projection.warnings
    exact_projection = project_floor(ImagePoint(500, 400), exact)
    assert projection.uncertainty is not None
    assert exact_projection.uncertainty is not None
    assert projection.uncertainty > exact_projection.uncertainty


def test_court_proposal_is_deterministic_and_evidence_based() -> None:
    frame = render_court()
    first = detect_court(frame)
    second = detect_court(frame.copy())

    assert first == second
    assert isinstance(first, CalibrationProposal)
    assert first.confidence >= CALIBRATED_MEASUREMENT_THRESHOLD
    assert len(first.keypoints.points) == 4
    assert {point.label for point in first.keypoints.points} == set(COURT)
    for point in first.keypoints.points:
        expected = IMAGE[point.label]
        assert point.image.x == pytest.approx(expected.x, abs=12)
        assert point.image.y == pytest.approx(expected.y, abs=12)
    assert first.visible_surfaces == (VisibleSurface.FLOOR,)
    assert first.line_count >= 4
    assert first.intersection_count >= 4


def test_plain_quadrilateral_without_squash_floor_topology_degrades() -> None:
    proposal = detect_court(render_court(internal_topology=False))

    assert proposal.confidence < CALIBRATED_MEASUREMENT_THRESHOLD
    assert proposal.keypoints.points == ()
    assert proposal.visible_surfaces == ()
    assert "missing_internal_court_topology" in proposal.warnings


@pytest.mark.parametrize(
    "frame",
    [
        np.zeros((480, 640, 3), dtype=np.uint8),
        np.random.default_rng(42).integers(0, 256, (480, 640, 3), dtype=np.uint8),
        render_court(partial=True),
    ],
)
def test_blank_noisy_and_partial_frames_degrade_without_fabrication(
    frame: np.ndarray,
) -> None:
    proposal = detect_court(frame)

    assert proposal.confidence < CALIBRATED_MEASUREMENT_THRESHOLD
    assert len(proposal.keypoints.points) < 4
    assert "floor" not in proposal.visible_surfaces
    assert proposal.warnings

@pytest.mark.asyncio
async def test_migration_backfills_complete_readable_legacy_result(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    engine = create_engine(f"sqlite+pysqlite:///{settings.database_path}")
    Database._install_sqlite_pragmas(engine)
    migrate(engine, "0004")
    now = "2026-08-25 12:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO matches (id, public_id, created_at, name) "
                "VALUES (1, 'legacy-match', :now, 'Legacy match')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO media_assets "
                "(id, public_id, created_at, match_id, kind, relative_path) "
                "VALUES (1, 'legacy-proxy', :now, 1, 'proxy', "
                "'videos/proxy/legacy.mp4')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO calibrations "
                "(id, public_id, created_at, match_id, media_asset_id, version) "
                "VALUES (1, 'legacy-calibration', :now, 1, 1, 7)"
            ),
            {"now": now},
        )

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/matches/legacy-match/calibration")

    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == 7
    assert payload["result"] == {
        "calibrated": False,
        "imageToCourt": None,
        "courtToImage": None,
        "residualsPx": [],
        "rmsErrorPx": None,
        "maxErrorPx": None,
        "inlierMask": [],
        "conditionNumber": None,
        "parameterCovariance": None,
        "confidence": 0.0,
        "capabilities": {
            "imageSpace": True,
            "floorPosition": False,
            "movementDistance": False,
            "speed": False,
        },
        "warnings": ["legacy_calibration_incomplete"],
    }



@pytest.mark.asyncio
async def test_calibration_api_create_read_idempotence_revision_and_typed_errors(
    tmp_path: Path,
) -> None:
    app, match_id, _ = prepared_app(tmp_path)
    transport = ASGITransport(app=app)
    body = {
        "expectedRevision": 0,
        "frameSize": {"width": 1024, "height": 720},
        "keypoints": api_keypoints(keypoints()),
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing_match = await client.get("/api/v1/matches/not-a-match/calibration")
        assert missing_match.status_code == 404
        assert missing_match.json()["code"] == "match_not_found"

        absent = await client.get(f"/api/v1/matches/{match_id}/calibration")
        assert absent.status_code == 404
        assert absent.json()["code"] == "calibration_not_found"
        invalid = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={**body, "keypoints": body["keypoints"][:3]},
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "request_validation_failed"

        outside_points = api_keypoints(keypoints())
        outside_points[0]["court"]["xM"] = -0.01
        outside = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={**body, "keypoints": outside_points},
        )
        assert outside.status_code == 422
        assert outside.json()["code"] == "request_validation_failed"

        created = await client.put(
            f"/api/v1/matches/{match_id}/calibration", json=body
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["revision"] == 1
        assert payload["result"]["calibrated"] is True
        assert payload["result"]["capabilities"]["speed"] is True
        assert payload["frameSize"] == {"width": 1024, "height": 720}
        assert isinstance(payload["proxyId"], str)

        read = await client.get(f"/api/v1/matches/{match_id}/calibration")
        assert read.status_code == 200
        assert read.json() == payload

        unchanged = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={**body, "expectedRevision": 1},
        )
        assert unchanged.status_code == 200
        assert unchanged.json()["revision"] == 1

        changed_points = api_keypoints(keypoints())
        changed_points[0]["image"]["x"] = 282.0
        changed = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={
                **body,
                "expectedRevision": 1,
                "keypoints": changed_points,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["revision"] == 2

        stale = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={**body, "expectedRevision": 1},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "calibration_revision_conflict"

    with app.state.database.session() as session:
        revisions = session.scalars(
            select(Calibration)
            .join(Calibration.match)
            .where(Match.public_id == match_id)
            .order_by(Calibration.revision)
        ).all()
        assert [row.revision for row in revisions] == [1, 2]
        assert revisions[0].keypoints != revisions[1].keypoints


@pytest.mark.asyncio
async def test_idempotence_includes_proxy_identity_and_derived_frame_geometry(
    tmp_path: Path,
) -> None:
    app, match_id, _ = prepared_app(tmp_path)
    body = {
        "expectedRevision": 0,
        "frameSize": {"width": 1024, "height": 720},
        "keypoints": api_keypoints(keypoints()),
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.put(
            f"/api/v1/matches/{match_id}/calibration", json=body
        )
        assert created.status_code == 200

        wrong_geometry = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={
                **body,
                "expectedRevision": 1,
                "frameSize": {"width": 1000, "height": 700},
            },
        )
        assert wrong_geometry.status_code == 422
        assert wrong_geometry.json()["code"] == "frame_size_mismatch"

        replacement_relative = Path("videos/proxy/replacement.mp4")
        replacement_path = app.state.storage.root / replacement_relative
        replacement_frame = cv2.resize(render_court(), (800, 600))
        write_proxy(replacement_path, replacement_frame)
        with app.state.database.session() as session:
            match = session.scalar(select(Match).where(Match.public_id == match_id))
            assert match is not None
            replacement = MediaAsset(
                match=match,
                kind=AssetKind.PROXY,
                relative_path=str(replacement_relative),
            )
            session.add(replacement)
            session.flush()
            replacement_id = replacement.public_id

        changed_proxy = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={
                **body,
                "expectedRevision": 1,
                "frameSize": {"width": 800, "height": 600},
            },
        )
        assert changed_proxy.status_code == 200
        assert changed_proxy.json()["revision"] == 2
        assert changed_proxy.json()["proxyId"] == replacement_id
        assert changed_proxy.json()["frameSize"] == {"width": 800, "height": 600}

        unchanged = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={
                **body,
                "expectedRevision": 2,
                "frameSize": {"width": 800, "height": 600},
            },
        )
        assert unchanged.status_code == 200
        assert unchanged.json()["revision"] == 2

    with app.state.database.session() as session:
        revisions = session.scalars(
            select(Calibration)
            .join(Calibration.match)
            .where(Match.public_id == match_id)
            .order_by(Calibration.revision)
        ).all()
        assert [(row.frame_width, row.frame_height) for row in revisions] == [
            (1024, 720),
            (800, 600),
        ]


@pytest.mark.asyncio
async def test_proposal_decodes_stored_proxy_at_a_bounded_timestamp(
    tmp_path: Path,
) -> None:
    app, match_id, proxy_path = prepared_app(tmp_path)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        proposed = await client.post(
            f"/api/v1/matches/{match_id}/calibration/propose",
            json={"timestampSeconds": 0.5},
        )
        assert proposed.status_code == 200
        assert proposed.json()["confidence"] >= CALIBRATED_MEASUREMENT_THRESHOLD
        assert len(proposed.json()["keypoints"]) == 4

        out_of_range = await client.post(
            f"/api/v1/matches/{match_id}/calibration/propose",
            json={"timestampSeconds": 99},
        )
        assert out_of_range.status_code == 422
        assert out_of_range.json()["code"] == "timestamp_out_of_range"

        no_frame_at_target = await client.post(
            f"/api/v1/matches/{match_id}/calibration/propose",
            json={"timestampSeconds": 1.75},
        )
        assert no_frame_at_target.status_code == 422
        assert no_frame_at_target.json()["code"] == "timestamp_out_of_range"

        at_video_end = await client.post(
            f"/api/v1/matches/{match_id}/calibration/propose",
            json={"timestampSeconds": 2.0},
        )
        assert at_video_end.status_code == 422
        assert at_video_end.json()["code"] == "timestamp_out_of_range"

        proxy_path.write_bytes(b"not a video")
        corrupt = await client.post(
            f"/api/v1/matches/{match_id}/calibration/propose",
            json={"timestampSeconds": 0},
        )
        assert corrupt.status_code == 422
        assert corrupt.json()["code"] == "invalid_proxy"


def test_proxy_encoding_bounds_keyframe_gap_for_bounded_proposal_seek(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    proxy = tmp_path / "proxy.mp4"
    write_proxy(
        source,
        np.zeros((120, 160, 3), dtype=np.uint8),
        frame_count=150,
        rate=30,
    )

    create_proxy(source, proxy)

    with av.open(str(proxy), mode="r") as container:
        stream = next(item for item in container.streams if item.type == "video")
        frames = list(container.decode(stream))
    keyframes = [index for index, frame in enumerate(frames) if frame.key_frame]
    assert keyframes
    gaps = [
        later - earlier
        for earlier, later in zip(keyframes, keyframes[1:], strict=False)
    ]
    gaps.append(len(frames) - keyframes[-1])
    assert max(gaps) <= 60


@pytest.mark.asyncio
async def test_changed_save_invalidates_only_existing_derived_court_chunks(
    tmp_path: Path,
) -> None:
    app, match_id, _ = prepared_app(tmp_path)
    database: Database = app.state.database
    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        proxy = next(asset for asset in match.media_assets if asset.kind is AssetKind.PROXY)
        job = AnalysisJob(
            match=match,
            source_media_asset=proxy,
            processing_profile=ProcessingProfile.BALANCED,
            status=JobStatus.COMPLETED,
        )
        chunks = [
            JobChunk(
                analysis_job=job,
                chunk_index=index,
                stage=stage,
                start_us=index * 10,
                end_us=index * 10 + 10,
                status=StageStatus.COMPLETED,
                artifact_path=f"exports/{stage.value}.json",
            )
            for index, stage in enumerate(Stage)
        ]
        session.add_all([job, *chunks])
        session.flush()
        original_asset_count = len(match.media_assets)

    body = {
        "expectedRevision": 0,
        "frameSize": {"width": 1024, "height": 720},
        "keypoints": api_keypoints(keypoints()),
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.put(
            f"/api/v1/matches/{match_id}/calibration", json=body
        )
        assert created.status_code == 200

        unchanged = await client.put(
            f"/api/v1/matches/{match_id}/calibration",
            json={**body, "expectedRevision": 1},
        )
        assert unchanged.status_code == 200

    with database.session() as session:
        match = session.scalar(select(Match).where(Match.public_id == match_id))
        assert match is not None
        statuses = {
            chunk.stage: chunk.status
            for job in match.analysis_jobs
            for chunk in job.chunks
        }
        assert statuses[Stage.PREPARE] is StageStatus.COMPLETED
        assert statuses[Stage.CALIBRATION] is StageStatus.COMPLETED
        assert statuses[Stage.PLAYERS] is StageStatus.COMPLETED
        assert all(
            statuses[stage] is StageStatus.INVALIDATED
            for stage in (
                Stage.BALL,
                Stage.EVENTS,
                Stage.CLASSIFICATION,
                Stage.REPORT,
            )
        )
        assert len(match.media_assets) == original_asset_count
        assert sum(len(job.chunks) for job in match.analysis_jobs) == len(Stage)
