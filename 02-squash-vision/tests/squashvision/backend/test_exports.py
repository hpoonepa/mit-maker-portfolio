from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))

from squashvision.app import create_app
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    Correction,
    CorrectionStatus,
    JobChunk,
    JobStatus,
    Match,
    MediaAsset,
    ModelAsset,
    ModelAssetState,
    PlayerSlot,
    PlayerTrack,
    ProcessingProfile,
    ReportRevision,
    Shot,
    ShotKind,
    Stage,
    StagePublication,
    StageStatus,
)
from squashvision.schemas import ExportSelection
from squashvision.settings import Settings


def _seed(app: FastAPI, *, unsafe_name: bool = False) -> str:
    source_name = "source-unsafe.mp4" if unsafe_name else "source.mp4"
    original = app.state.storage.root / "videos/original" / source_name
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"real-original-media")
    with app.state.database.session() as session:
        match = Match(
            name="../../Final\u0007<script>alert(1)</script>" if unsafe_name else "Final",
            player_a_name="-i" if unsafe_name else "Ada",
            player_b_name="Béa" if unsafe_name else "Bea",
            score="3-1",
        )
        source = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path=f"videos/original/{source_name}",
            checksum_sha256=hashlib.sha256(b"real-original-media").hexdigest(),
            byte_size=len(b"real-original-media"),
            duration_us=30_000_000,
            probe_metadata={"codec": "h264", "hostPath": "/private/secret"},
        )
        shot = Shot(
            match=match,
            prediction_revision=7,
            prediction_id="shot-1",
            frame_index=30,
            source_timestamp_us=2_000_000,
            source_evidence_ids=["evidence-1"],
            hitter=PlayerSlot.NEAR,
            kind=ShotKind.BOAST,
            outcome="in_play",
            contact_x_px=140.0,
            contact_y_px=80.0,
            contact_covariance=[[1.0, 0.0], [0.0, 1.0]],
            contact_provenance="observed",
            contact_source_width=640,
            contact_source_height=360,
            review_required=True,
            classification_payload={"confidence": 0.82},
            review_status="accepted",
            evidence_provenance="observed",
            speed_m_s=None,
            speed_unavailable_reason="calibration_required",
        )
        track = PlayerTrack(
            match=match,
            prediction_revision=7,
            prediction_id="track-1",
            slot=PlayerSlot.NEAR,
            source_timestamp_us=1_500_000,
            source_evidence_ids=["movement-1"],
            x_m=None,
            y_m=None,
            observed=False,
            calibration_revision=None,
            position_provenance="unavailable",
            position_unavailable_reason="not_observed",
        )
        correction = Correction(
            match=match,
            command_type="change_shot_type",
            target_type="shot",
            target_id="shot-1",
            prediction_revision=7,
            expected_report_revision=1,
            before_payload={"shot_type": "boast"},
            after_payload={"shot_type": "drop"},
            reason="Correct observed contact",
            source_timestamp_us=2_000_000,
            source_evidence_ids=["evidence-1"],
            status=CorrectionStatus.ACTIVE,
        )
        first = ReportRevision(
            match=match,
            revision=1,
            prediction_revision=7,
            schema_version=1,
            sections={
                "overview": {
                    "availability": {
                        "available": False,
                        "reason": "not_computed",
                    }
                }
            },
            section_hashes={"overview": "1" * 64},
            dependency_hashes={"overview": "2" * 64},
        )
        second = ReportRevision(
            match=match,
            correction_id=None,
            revision=2,
            prediction_revision=7,
            schema_version=1,
            sections={
                "overview": {
                    "rally_count": 0,
                    "_evidence_ids": ["evidence-1"],
                },
                "movement": {
                    "availability": {
                        "available": False,
                        "value": None,
                        "reason": "calibration_required",
                    },
                    "_evidence_ids": [],
                },
            },
            section_hashes={
                "overview": "3" * 64,
                "movement": "4" * 64,
            },
            dependency_hashes={
                "overview": "5" * 64,
                "movement": "6" * 64,
            },
        )
        session.add_all([
            match,
            source,
            shot,
            track,
            correction,
            first,
            second,
        ])
        session.flush()
        return match.public_id


def _members(bundle_path: Path) -> tuple[list[str], dict[str, bytes], dict[str, zipfile.ZipInfo]]:
    with zipfile.ZipFile(bundle_path) as archive:
        names = archive.namelist()
        return names, {name: archive.read(name) for name in names}, {item.filename: item for item in archive.infolist()}


def test_build_export_is_revision_pinned_deterministic_and_correction_folded(tmp_path: Path) -> None:
    from squashvision.exports import build_export

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    selection = ExportSelection(formats=("html", "json", "csv"))

    first = build_export(match_id, 2, selection, database=app.state.database, storage=app.state.storage)
    second = build_export(match_id, 2, selection, database=app.state.database, storage=app.state.storage)

    assert first.sha256 == second.sha256
    assert first.byte_size == second.byte_size
    names, members, infos = _members(first.path)
    assert names[:-1] == sorted(names[:-1])
    assert names == [
        "data/canonical_shots.csv",
        "data/errors_review.csv",
        "data/evidence.csv",
        "data/movement.csv",
        "data/rallies.csv",
        "report.html",
        "report.json",
        "manifest.json",
    ]
    assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos.values())
    report = json.loads(members["report.json"])
    assert report["schemaVersion"] == 1
    assert report["report"]["revision"] == 2
    assert report["report"]["sections"]["overview"]["rally_count"] == 0
    assert report["canonicalEvidence"]["shots"][0]["shot_type"] == "drop"
    assert report["canonicalEvidence"]["shots"][0]["speed_m_s"] is None
    assert report["canonicalEvidence"]["shots"][0]["speed_unavailable_reason"] == "calibration_required"
    assert report["provenance"]["predictionRevision"] == 7
    assert report["provenance"]["correctionIds"] == [report["provenance"]["correctionIds"][0]]
    assert "/private/secret" not in members["report.json"].decode()

    rows = list(csv.reader(io.StringIO(members["data/canonical_shots.csv"].decode())))
    assert rows[0] == [
        "prediction_id", "timestamp_us", "rally_id", "hitter", "shot_type", "is_volley",
        "outcome", "contact_x_m", "contact_y_m", "contact_metric_unavailable_reason",
        "contact_x_px", "contact_y_px", "contact_covariance_json", "contact_provenance",
        "image_point_unavailable_reason", "speed_m_s", "speed_unavailable_reason",
        "review_status", "evidence_provenance", "source_evidence_ids",
    ]
    assert rows[1][4] == "drop"
    assert rows[1][9] == "missing_coordinate"
    assert rows[1][15] == ""
    assert rows[1][16] == "calibration_required"
    movement_rows = list(csv.reader(io.StringIO(members["data/movement.csv"].decode())))
    assert movement_rows[0] == [
        "prediction_id", "player", "source_timestamp_us", "x_m", "y_m",
        "position_covariance", "position_uncertainty_m", "position_provenance",
        "coordinate_unavailable_reason", "observed", "calibration_revision",
        "source_evidence_ids",
    ]
    assert movement_rows[1][8] == "not_observed"
    html = members["report.html"].decode()
    assert "http://" not in html and "https://" not in html
    assert "<script src=" not in html and "<link" not in html
    manifest = json.loads(members["manifest.json"])
    assert manifest["schemaVersion"] == 1
    assert manifest["createdRevision"] == 2
    assert [item["name"] for item in manifest["members"]] == names[:-1]
    for item in manifest["members"]:
        assert item["bytes"] == len(members[item["name"]])
        assert item["sha256"] == hashlib.sha256(members[item["name"]]).hexdigest()


def test_original_requires_explicit_selection_and_unsafe_names_are_rejected(tmp_path: Path) -> None:
    from squashvision.exports import ExportError, build_export

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    ordinary = build_export(
        match_id,
        2,
        ExportSelection(formats=("json",)),
        database=app.state.database,
        storage=app.state.storage,
    )
    _, ordinary_members, _ = _members(ordinary.path)
    assert not any(name.startswith("original/") for name in ordinary_members)

    included = build_export(
        match_id,
        2,
        ExportSelection(formats=("json",), include_original=True),
        database=app.state.database,
        storage=app.state.storage,
    )
    _, included_members, _ = _members(included.path)
    assert included_members["original/source.mp4"] == b"real-original-media"

    unsafe_match_id = _seed(app, unsafe_name=True)
    with pytest.raises(ExportError, match="metadata cannot be exported safely"):
        build_export(
            unsafe_match_id,
            2,
            ExportSelection(formats=("json",)),
            database=app.state.database,
            storage=app.state.storage,
        )
    export_paths = set((app.state.storage.root / "exports").glob("*.zip"))
    assert export_paths == {ordinary.path, included.path}


def test_selected_evidence_uses_bounded_ffmpeg_argument_array(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import squashvision.exports as exports

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], output: Path) -> None:
        calls.append(arguments)
        output.write_bytes(b"clip")

    monkeypatch.setattr(exports, "_run_ffmpeg_clip", fake_run)
    bundle = exports.build_export(
        match_id,
        2,
        ExportSelection(formats=("json",), evidence_ids=("evidence-1",), evidence_duration_seconds=4.0),
        database=app.state.database,
        storage=app.state.storage,
    )
    _, members, _ = _members(bundle.path)
    assert members["evidence/clip-001.mp4"] == b"clip"
    assert len(calls) == 1
    arguments = calls[0]
    assert arguments[0] == "-nostdin"
    assert "-ss" in arguments and "-t" in arguments
    assert all(argument != "evidence-1" for argument in arguments)
    assert not any("shell" in argument for argument in arguments)


def test_build_failure_leaves_no_partial_export_or_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import squashvision.exports as exports

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)

    def fail_clip(_arguments: list[str], _output: Path) -> None:
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(exports, "_run_ffmpeg_clip", fail_clip)
    with pytest.raises(exports.ExportError, match="evidence clip generation failed"):
        exports.build_export(
            match_id,
            2,
            ExportSelection(formats=("json",), evidence_ids=("evidence-1",)),
            database=app.state.database,
            storage=app.state.storage,
        )
    export_dir = app.state.storage.root / "exports"
    assert not export_dir.exists() or list(export_dir.iterdir()) == []
    assert not list(app.state.storage.root.glob(".export-*"))


@pytest.mark.asyncio
async def test_routes_create_status_download_dedupe_persist_and_delete_with_match(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, min_free_disk_bytes=0)
    app = create_app(settings)
    match_id = _seed(app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"revision": 2, "selection": {"formats": ["json", "csv"]}}
        created = await client.post(f"/api/v1/matches/{match_id}/exports", json=payload)
        duplicate = await client.post(f"/api/v1/matches/{match_id}/exports", json=payload)
        assert created.status_code == 201
        assert duplicate.status_code == 200
        detail = created.json()
        assert duplicate.json()["id"] == detail["id"]
        assert detail["state"] == "completed" and detail["revision"] == 2

        status = await client.get(f"/api/v1/matches/{match_id}/exports/{detail['id']}")
        assert status.status_code == 200 and status.json()["sha256"] == detail["sha256"]
        download = await client.get(f"/api/v1/matches/{match_id}/exports/{detail['id']}/download")
        assert download.status_code == 200
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            assert json.loads(archive.read("report.json"))["report"]["revision"] == 2
        assert (await client.get(f"/api/v1/matches/not-owned/exports/{detail['id']}/download")).status_code == 404

    restarted = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=restarted), base_url="http://test") as client:
        persisted = await client.get(f"/api/v1/matches/{match_id}/exports/{detail['id']}")
        assert persisted.status_code == 200 and persisted.json()["state"] == "completed"
        path = restarted.state.storage.root / persisted.json()["relativePath"]
        assert path.is_file()
        deleted = await client.delete(f"/api/v1/matches/{match_id}")
        assert deleted.status_code == 204
        assert not path.exists()


def test_concurrent_identical_builds_publish_one_owned_bundle(tmp_path: Path) -> None:
    from squashvision.exports import build_export

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    selection = ExportSelection(formats=("json",))

    def create() -> str:
        return build_export(match_id, 2, selection, database=app.state.database, storage=app.state.storage).public_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _index: create(), range(4)))
    assert len(set(ids)) == 1
    with app.state.database.session() as session:
        exports = session.scalars(select(MediaAsset).where(MediaAsset.kind == AssetKind.EXPORT)).all()
        assert len(exports) == 1


def test_corrupt_completed_bundle_is_removed_before_atomic_rebuild(tmp_path: Path) -> None:
    from squashvision.exports import build_export

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    selection = ExportSelection(formats=("json",))
    first = build_export(
        match_id,
        2,
        selection,
        database=app.state.database,
        storage=app.state.storage,
    )
    first.path.write_bytes(b"corrupt")

    rebuilt = build_export(
        match_id,
        2,
        selection,
        database=app.state.database,
        storage=app.state.storage,
    )

    assert rebuilt.public_id != first.public_id
    assert not first.path.exists()
    with app.state.database.session() as session:
        exports = session.scalars(
            select(MediaAsset).where(MediaAsset.kind == AssetKind.EXPORT)
        ).all()
        assert [asset.public_id for asset in exports] == [rebuilt.public_id]


def test_restart_cleanup_removes_only_managed_export_staging(tmp_path: Path) -> None:
    from squashvision.exports import cleanup_export_staging

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    stage = app.state.storage.root / ".export-orphan123"
    stage.mkdir()
    (stage / "partial").write_bytes(b"partial")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = app.state.storage.root / ".export-link123"
    link.symlink_to(outside, target_is_directory=True)

    cleanup_export_staging(app.state.storage)

    assert not stage.exists()
    assert link.is_symlink()
    assert outside.is_dir()


def test_rebuild_ignores_mutable_current_model_rows_for_revision_snapshot(
    tmp_path: Path,
) -> None:
    from squashvision.exports import build_export

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    with app.state.database.session() as session:
        session.add(
            ModelAsset(
                model_name="pose",
                source="https",
                repository="https://github.com/example/models",
                filename="pose.pt",
                requested_revision="v1",
                resolved_revision="immutable-v1",
                declared_license="test",
                compatibility_version=1,
                state=ModelAssetState.READY,
                sha256="1" * 64,
                byte_size=10,
            )
        )
    selection = ExportSelection(formats=("json",))
    first = build_export(
        match_id,
        2,
        selection,
        database=app.state.database,
        storage=app.state.storage,
    )
    first_signature = first.sha256
    first.path.write_bytes(b"corrupt")
    with app.state.database.session() as session:
        model = session.scalar(
            select(ModelAsset).where(ModelAsset.model_name == "pose")
        )
        assert model is not None
        model.resolved_revision = "mutable-v2"
        model.sha256 = "2" * 64

    rebuilt = build_export(
        match_id,
        2,
        selection,
        database=app.state.database,
        storage=app.state.storage,
    )

    assert rebuilt.sha256 == first_signature


def test_open_download_stream_survives_concurrent_owned_path_deletion(
    tmp_path: Path,
) -> None:
    from squashvision.exports import build_export, open_export_download

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    bundle = build_export(
        match_id,
        2,
        ExportSelection(formats=("json",)),
        database=app.state.database,
        storage=app.state.storage,
    )
    expected = bundle.path.read_bytes()

    opened, stream = open_export_download(
        match_id,
        bundle.public_id,
        database=app.state.database,
        storage=app.state.storage,
    )
    opened.path.unlink()

    assert b"".join(stream) == expected


def test_openapi_documents_both_new_and_deduplicated_export_successes(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    responses = app.openapi()["paths"][
        "/api/v1/matches/{match_id}/exports"
    ]["post"]["responses"]

    assert set(responses) >= {"200", "201"}
    for status in ("200", "201"):
        assert responses[status]["content"]["application/json"]["schema"][
            "$ref"
        ] == "#/components/schemas/ExportDetail"


@pytest.mark.parametrize("model_name", ["pose", "ball"])
def test_export_uses_exact_immutable_pipeline_model_snapshot(
    tmp_path: Path,
    model_name: str,
) -> None:
    from squashvision.exports import build_export

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    envelope = {
        "model_manifests": {
            model_name: {
                "manifest_id": model_name,
                "digest": "7" * 64,
                "requested_revision": "v1",
                "revision": "commit-immutable",
                "state": "ready",
                "compatibility_version": 1,
                "required": True,
                "error_code": None,
            }
        }
    }
    if model_name == "ball":
        envelope["ball_preprocessing"] = {
            "mode": "inverted", "input_transform": "uint8_invert_all_frames_and_median_v1",
            "support_policy": "dark-motion-trajectory-v1",
        }
    with app.state.database.session() as session:
        match = session.scalar(
            select(Match).where(Match.public_id == match_id)
        )
        assert match is not None
        source = session.scalar(
            select(MediaAsset).where(
                MediaAsset.match_id == match.id,
                MediaAsset.kind == AssetKind.ORIGINAL,
            )
        )
        assert source is not None
        job = AnalysisJob(
            match=match,
            source_media_asset=source,
            processing_profile=ProcessingProfile.BALANCED,
            status=JobStatus.COMPLETED,
        )
        session.add(job)
        session.flush()
        relative = Path(
            "checkpoints",
            job.public_id,
            "report-envelope.json",
        )
        artifact = app.state.storage.root / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(envelope, sort_keys=True).encode()
        artifact.write_bytes(data)
        session.add_all([
            JobChunk(
                analysis_job=job,
                chunk_index=0,
                stage=Stage.REPORT,
                start_us=0,
                end_us=30_000_000,
                status=StageStatus.COMPLETED,
                artifact_path=relative.as_posix(),
                artifact_size=len(data),
                artifact_sha256=hashlib.sha256(data).hexdigest(),
            ),
            StagePublication(
                match_id=match.id,
                analysis_job_id=job.id,
                stage=Stage.REPORT,
                input_hash="a" * 64,
                worker_id="worker",
                claim_token="00000000-0000-0000-0000-000000000001",
                prediction_revision=7,
                report_revision=2,
            ),
        ])

    bundle = build_export(
        match_id,
        2,
        ExportSelection(formats=("json",)),
        database=app.state.database,
        storage=app.state.storage,
    )
    _, members, _ = _members(bundle.path)
    document = json.loads(members["report.json"])

    assert document["modelSnapshotAvailability"] == {
        "available": True,
        "reason": None,
    }
    assert document["models"] == [{
        "name": model_name,
        "manifestId": model_name,
        "sha256": "7" * 64,
        "requestedRevision": "v1",
        "resolvedRevision": "commit-immutable",
        "compatibilityVersion": 1,
        "required": True,
        "state": "ready",
        "errorCode": None,
        **({"inputPreprocessing": envelope["ball_preprocessing"]} if model_name == "ball" else {}),
    }]


def test_export_rejects_original_with_stored_integrity_mismatch(
    tmp_path: Path,
) -> None:
    from squashvision.exports import ExportError, build_export

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    original = app.state.storage.root / "videos/original/source.mp4"
    original.write_bytes(b"corrupt-original")

    with pytest.raises(ExportError) as error:
        build_export(
            match_id,
            2,
            ExportSelection(formats=("json",)),
            database=app.state.database,
            storage=app.state.storage,
        )

    assert error.value.code == "original_integrity_failed"
    assert not list((app.state.storage.root / "exports").glob("*.zip"))


def test_export_stages_original_before_storage_path_can_be_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from squashvision.exports import build_export

    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    match_id = _seed(app)
    storage = app.state.storage
    original_relative = Path("videos/original/source.mp4")
    replacement = tmp_path / "replacement.mp4"
    replacement.write_bytes(b"attacker-media")
    original_resolve = storage.resolve

    def resolve_and_swap(
        relative: Path, *, owned_paths: object
    ) -> object:
        stored = original_resolve(relative, owned_paths=owned_paths)
        if Path(relative) == original_relative:
            os.replace(replacement, stored.absolute)
        return stored

    monkeypatch.setattr(storage, "resolve", resolve_and_swap)
    bundle = build_export(
        match_id,
        2,
        ExportSelection(formats=("json",), include_original=True),
        database=app.state.database,
        storage=storage,
    )

    _, members, _ = _members(bundle.path)
    assert members["original/source.mp4"] == b"real-original-media"
