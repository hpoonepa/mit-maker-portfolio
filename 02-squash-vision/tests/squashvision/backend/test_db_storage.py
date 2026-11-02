import os
import sys
from pathlib import Path
from uuid import UUID

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

import squashvision.routes.matches as matches_routes
from squashvision.app import create_app
from squashvision.db import Database
from squashvision.models import (
    AnalysisJob,
    AssetKind,
    JobStatus,
    JobChunk,
    Match,
    MediaAsset,
    PendingDeletion,
    ProcessingProfile,
    Stage,
    StageStatus,
)
from squashvision.settings import Settings
from squashvision.storage import LocalStorage

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError


CORE_TABLES = {
    "matches",
    "media_assets",
    "analysis_jobs",
    "job_chunks",
    "calibrations",
    "player_tracks",
    "shots",
    "rallies",
    "error_candidates",
    "corrections",
    "report_revisions",
    "model_assets",
    "pending_deletions",
    "stage_publications",
}


def test_database_enables_sqlite_safety_pragmas(tmp_path: Path) -> None:
    database = Database.open(Settings(data_dir=tmp_path))

    with database.session() as session:
        foreign_keys = session.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = session.execute(text("PRAGMA journal_mode")).scalar_one()
        busy_timeout = session.execute(text("PRAGMA busy_timeout")).scalar_one()

    assert foreign_keys == 1
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000


def test_migration_creates_all_canonical_tables(tmp_path: Path) -> None:
    database = Database.open(Settings(data_dir=tmp_path))

    table_names = set(inspect(database.engine).get_table_names())

    assert table_names == CORE_TABLES | {"alembic_version"}
    for table_name in CORE_TABLES:
        columns = {column["name"] for column in inspect(database.engine).get_columns(table_name)}
        assert {"id", "public_id", "created_at"} <= columns


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    database = Database.open(Settings(data_dir=tmp_path))

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.execute(
                text(
                    "INSERT INTO media_assets "
                    "(public_id, match_id, kind, relative_path, created_at) "
                    "VALUES (:public_id, 999999, 'original', 'videos/original/x.mp4', CURRENT_TIMESTAMP)"
                ),
                {"public_id": "00000000-0000-4000-8000-000000000001"},
            )


def test_sessions_commit_and_roll_back_atomically(tmp_path: Path) -> None:
    database = Database.open(Settings(data_dir=tmp_path))

    with database.session() as session:
        session.add(Match(name="committed"))

    with pytest.raises(RuntimeError):
        with database.session() as session:
            session.add(Match(name="rolled back"))
            session.flush()
            raise RuntimeError("abort")

    with database.session() as session:
        names = session.execute(text("SELECT name FROM matches ORDER BY name")).scalars().all()

    assert names == ["committed"]


def test_models_generate_uuid_public_ids(tmp_path: Path) -> None:
    database = Database.open(Settings(data_dir=tmp_path))

    with database.session() as session:
        match = Match(name="UUID match")
        asset = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path="videos/original/opaque.mp4",
        )
        session.add_all([match, asset])
        session.flush()
        public_ids = (match.public_id, asset.public_id)
        internal_ids = (match.id, asset.id)

    assert all(str(UUID(value)) == value for value in public_ids)
    assert len(set(public_ids)) == 2
    assert all(isinstance(value, int) for value in internal_ids)


def test_settings_derive_injectable_database_and_storage_paths(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.database_path == tmp_path / "squashvision.sqlite3"
    assert settings.storage_root == tmp_path / "storage"

    custom_database = tmp_path / "custom" / "records.sqlite3"
    custom_storage = tmp_path / "custom-assets"
    injected = Settings(
        data_dir=tmp_path,
        database_path=custom_database,
        storage_root=custom_storage,
    )
    assert injected.database_path == custom_database
    assert injected.storage_root == custom_storage


def test_storage_never_uses_uploaded_filename(tmp_path: Path) -> None:
    stored = LocalStorage(tmp_path).allocate(AssetKind.ORIGINAL, ".mp4")
    assert stored.relative.parts[:2] == ("videos", "original")
    assert stored.relative.name.endswith(".mp4")
    assert ".." not in stored.relative.parts


@pytest.mark.parametrize(
    "suffix",
    ["mp4", "", ".", "../.mp4", ".mp4/evil", ".tar.gz", ".mp 4", ".💥"],
)
def test_storage_rejects_non_simple_suffixes(tmp_path: Path, suffix: str) -> None:
    storage = LocalStorage(tmp_path)

    with pytest.raises(ValueError, match="suffix"):
        storage.allocate(AssetKind.ORIGINAL, suffix)


def test_storage_rejects_unsafe_and_unowned_paths(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    stored = storage.allocate(AssetKind.ORIGINAL, ".mp4")

    with pytest.raises(ValueError):
        storage.resolve(Path("../escape.mp4"), owned_paths={stored.relative})
    with pytest.raises(ValueError):
        storage.resolve(tmp_path / "absolute.mp4", owned_paths={stored.relative})
    with pytest.raises(PermissionError):
        storage.resolve(stored.relative, owned_paths=set())


def test_storage_rejects_symlink_escape(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "storage")
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = outside / "escaped.mp4"
    escaped.write_bytes(b"outside")
    link = storage.root / "videos" / "original" / "linked.mp4"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(escaped)

    with pytest.raises(ValueError):
        storage.resolve(
            Path("videos/original/linked.mp4"),
            owned_paths={Path("videos/original/linked.mp4")},
        )

def test_database_deletion_rejects_in_root_symlink_alias(tmp_path: Path) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path / "storage")
    victim = storage.allocate(AssetKind.PROXY, ".mp4")
    source = tmp_path / "victim.mp4"
    source.write_bytes(b"victim")
    storage.publish(victim, source)
    alias = Path("videos/original/alias.mp4")
    alias_absolute = storage.root / alias
    alias_absolute.parent.mkdir(parents=True, exist_ok=True)
    alias_absolute.symlink_to(victim.absolute)
    with database.session() as session:
        match = Match(name="symlink")
        asset = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path=alias.as_posix(),
        )
        session.add(asset)
        session.flush()
        asset_public_id = asset.public_id

    with pytest.raises(ValueError, match="symlink"):
        storage.delete_media_asset(database, asset_public_id)

    with database.session() as session:
        persisted = session.scalar(
            select(MediaAsset).where(MediaAsset.public_id == asset_public_id)
        )
    assert persisted is not None
    assert victim.absolute.read_bytes() == b"victim"


def test_publication_uses_temporary_sibling_and_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    stored = storage.allocate(AssetKind.PROXY, ".mp4")
    source = tmp_path / "upload-name-is-ignored.mp4"
    source.write_bytes(b"video bytes")
    replacements: list[tuple[Path, Path]] = []

    real_replace = __import__("os").replace

    def capture_replace(
        source_path: str, destination_path: str, **kwargs: object
    ) -> None:
        source_candidate = Path(source_path)
        destination_candidate = Path(destination_path)
        if not source_candidate.is_absolute():
            source_candidate = stored.absolute.parent / source_candidate
        if not destination_candidate.is_absolute():
            destination_candidate = stored.absolute.parent / destination_candidate
        replacements.append((source_candidate, destination_candidate))
        real_replace(source_path, destination_path, **kwargs)

    monkeypatch.setattr("squashvision.storage.os.replace", capture_replace)

    published = storage.publish(stored, source)

    assert published == stored
    assert stored.absolute.read_bytes() == b"video bytes"
    assert len(replacements) == 1
    temporary, destination = replacements[0]
    assert temporary.parent == destination.parent == stored.absolute.parent
    assert temporary != destination
    assert destination == stored.absolute
    assert not temporary.exists()


def test_published_original_is_immutable(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "storage")
    stored = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    storage.publish(stored, first)

    with pytest.raises(FileExistsError):
        storage.publish(stored, second)

    assert stored.absolute.read_bytes() == b"first"

def test_original_publication_never_clobbers_a_concurrent_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    stored = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"our upload")
    real_copy = __import__("shutil").copyfileobj

    def race_after_copy(source_file: object, destination_file: object) -> None:
        real_copy(source_file, destination_file)
        stored.absolute.write_bytes(b"concurrent winner")

    monkeypatch.setattr("squashvision.storage.shutil.copyfileobj", race_after_copy)

    with pytest.raises(FileExistsError):
        storage.publish(stored, source)

    assert stored.absolute.read_bytes() == b"concurrent winner"


def test_explicit_deletion_rejects_database_record_path_escape(tmp_path: Path) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path / "storage")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"must survive")
    with database.session() as session:
        match = Match(name="unsafe")
        asset = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path="../outside.mp4",
        )
        session.add(asset)
        session.flush()
        asset_public_id = asset.public_id

    with pytest.raises(ValueError):
        storage.delete_media_asset(database, asset_public_id)

    with database.session() as session:
        persisted = session.scalar(
            select(MediaAsset).where(MediaAsset.public_id == asset_public_id)
        )
    assert persisted is not None
    assert outside.read_bytes() == b"must survive"


def test_database_coordinated_deletion_commits_record_and_file(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path / "storage")
    stored = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    storage.publish(stored, source)
    with database.session() as session:
        match = Match(name="delete")
        asset = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path=stored.relative.as_posix(),
        )
        session.add(asset)
        session.flush()
        asset_public_id = asset.public_id

    storage.delete_media_asset(database, asset_public_id)

    with database.session() as session:
        persisted = session.scalar(
            select(MediaAsset).where(MediaAsset.public_id == asset_public_id)
        )
    assert persisted is None
    assert not stored.absolute.exists()


def test_database_coordinated_deletion_restores_file_when_commit_fails(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path / "storage")
    stored = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    storage.publish(stored, source)
    with database.session() as session:
        match = Match(name="protected")
        asset = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path=stored.relative.as_posix(),
        )
        session.add(
            AnalysisJob(
                match=match,
                source_media_asset=asset,
                processing_profile=ProcessingProfile.BALANCED,
            )
        )
        session.flush()
        asset_public_id = asset.public_id

    with pytest.raises(IntegrityError):
        storage.delete_media_asset(database, asset_public_id)

    with database.session() as session:
        persisted = session.scalar(
            select(MediaAsset).where(MediaAsset.public_id == asset_public_id)
        )
    assert persisted is not None
    assert stored.absolute.read_bytes() == b"original"


def test_database_deletion_restores_rejected_directory_entry(
    tmp_path: Path,
) -> None:
    database = Database.open(Settings(data_dir=tmp_path))
    storage = LocalStorage(tmp_path / "storage")
    relative = Path("videos/original/not-a-file.mp4")
    directory = storage.root / relative
    directory.mkdir(parents=True)
    with database.session() as session:
        match = Match(name="directory")
        asset = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path=relative.as_posix(),
        )
        session.add(asset)
        session.flush()
        asset_public_id = asset.public_id

    with pytest.raises(ValueError, match="non-file"):
        storage.delete_media_asset(database, asset_public_id)

    with database.session() as session:
        persisted = session.scalar(
            select(MediaAsset).where(MediaAsset.public_id == asset_public_id)
        )
    assert persisted is not None
    assert directory.is_dir()


def test_direct_alembic_requires_injected_database_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = Config(str(backend_root / "alembic.ini"))

    with pytest.raises(RuntimeError, match="Database.open"):
        command.upgrade(config, "head")

    assert not (tmp_path / "squashvision.sqlite3").exists()


@pytest.mark.asyncio
async def test_live_match_deletion_commit_failure_restores_and_clears_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    stored = app.state.storage.allocate(AssetKind.ORIGINAL, ".mp4")
    stored.absolute.write_bytes(b"original")
    with app.state.database.session() as session:
        match = Match(name="Rollback")
        session.add(
            MediaAsset(
                match=match,
                kind=AssetKind.ORIGINAL,
                relative_path=str(stored.relative),
                byte_size=len(b"original"),
            )
        )
        session.flush()
        match_id = match.public_id

    monkeypatch.setattr(
        matches_routes,
        "_commit_deletion",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("simulated commit failure")
        ),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/api/v1/matches/{match_id}")

    assert response.status_code == 503
    assert response.json()["code"] == "deletion_commit_failed"
    assert stored.absolute.read_bytes() == b"original"
    with app.state.database.session() as session:
        restored = session.scalar(
            select(Match).where(Match.public_id == match_id)
        )
        assert restored is not None
        assert restored.deletion_state == "active"
        assert session.scalars(select(PendingDeletion)).all() == []


def test_startup_reconciles_only_allowlisted_unowned_artifacts_without_following_symlinks(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path, min_free_disk_bytes=0)
    app = create_app(settings)
    storage = app.state.storage
    owned = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    owned.absolute.write_bytes(b"owned")
    owned_export = storage.allocate(AssetKind.EXPORT, ".zip")
    owned_export.absolute.write_bytes(b"owned export")
    with app.state.database.session() as session:
        match = Match(name="Owned")
        source = MediaAsset(
            match=match,
            kind=AssetKind.ORIGINAL,
            relative_path=str(owned.relative),
            byte_size=len(b"owned"),
        )
        export = MediaAsset(
            match=match,
            kind=AssetKind.EXPORT,
            relative_path=str(owned_export.relative),
            byte_size=len(b"owned export"),
        )
        job = AnalysisJob(
            match=match,
            source_media_asset=source,
            processing_profile=ProcessingProfile.FAST,
            status=JobStatus.RUNNING,
        )
        session.add_all([match, source, export, job])
        session.flush()
        job_id = job.public_id
        owned_checkpoint_relative = (
            Path("checkpoints")
            / job_id
            / "calibration"
            / "0-10.bin"
        )
        owned_payload_relative = owned_checkpoint_relative.with_suffix(
            ".payload.json"
        )
        session.add(
            JobChunk(
                analysis_job=job,
                chunk_index=0,
                stage=Stage.CALIBRATION,
                start_us=0,
                end_us=10,
                status=StageStatus.COMPLETED,
                artifact_path=str(owned_checkpoint_relative),
                artifact_payload_path=str(owned_payload_relative),
            )
        )

    root_orphans = [
        storage.root / f".upload-{'1' * 32}.tmp",
        storage.root / f".proxy-{'2' * 32}.mp4",
        storage.root / f".timestamp-{'3' * 32}.json",
    ]
    for path in root_orphans:
        path.write_bytes(b"staging")
    published_orphans = [
        storage.root / "videos" / "original" / f"{'4' * 32}.mp4",
        storage.root / "timestamp-maps" / f"{'5' * 32}.json",
        storage.root / "timestamp-index" / f"{'6' * 32}.parquet",
        storage.root / "exports" / f"{'7' * 32}.zip",
    ]
    for path in published_orphans:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"orphan")
    publication_staging = [
        storage.root
        / "videos"
        / "original"
        / f".{'8' * 32}.mp4.{'9' * 32}.tmp",
        storage.root
        / "videos"
        / "proxy"
        / f".{'a' * 32}.mp4.{'b' * 32}.tmp",
        storage.root
        / "timestamp-maps"
        / f".{'c' * 32}.json.{'d' * 32}.tmp",
        storage.root
        / "timestamp-index"
        / f".{'e' * 32}.parquet.{'f' * 32}.tmp",
    ]
    for path in publication_staging:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"publication staging")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    proxy_link = (
        storage.root / "videos" / "proxy" / f"{'7' * 32}.mp4"
    )
    proxy_link.parent.mkdir(parents=True, exist_ok=True)
    proxy_link.symlink_to(outside)
    obsolete_checkpoint = (
        storage.root / "checkpoints" / "obsolete-job" / "old.parquet"
    )
    obsolete_checkpoint.parent.mkdir(parents=True)
    obsolete_checkpoint.write_bytes(b"obsolete")
    active_job_orphan = (
        storage.root / "checkpoints" / job_id / "in-progress.tmp"
    )
    active_job_orphan.parent.mkdir(parents=True)
    active_job_orphan.write_bytes(b"orphan")
    owned_checkpoint = storage.root / owned_checkpoint_relative
    owned_payload = storage.root / owned_payload_relative
    owned_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    owned_checkpoint.write_bytes(b"owned checkpoint")
    owned_payload.write_bytes(b"owned payload")
    unrelated = storage.root / "keep-me.txt"
    unrelated.write_bytes(b"unrelated")

    create_app(settings)

    assert owned.absolute.read_bytes() == b"owned"
    assert owned_export.absolute.read_bytes() == b"owned export"
    assert not active_job_orphan.exists()
    assert owned_checkpoint.read_bytes() == b"owned checkpoint"
    assert owned_payload.read_bytes() == b"owned payload"
    assert unrelated.read_bytes() == b"unrelated"
    assert all(not path.exists() for path in root_orphans)
    assert all(not path.exists() for path in published_orphans)
    assert all(not path.exists() for path in publication_staging)
    assert not proxy_link.exists() and not proxy_link.is_symlink()
    assert outside.read_bytes() == b"outside"
    assert not obsolete_checkpoint.exists()


def test_timestamp_index_publication_rejects_parent_directory_swap(
    tmp_path: Path,
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    allocated = storage.allocate_timestamp_index()
    source = tmp_path / "index.parquet"
    source.write_bytes(b"verified index")
    original_parent = storage.root / "timestamp-index"
    displaced_parent = storage.root / "displaced-index"
    outside = tmp_path / "outside-index"
    outside.mkdir()
    original_parent.rename(displaced_parent)
    original_parent.symlink_to(outside, target_is_directory=True)

    descriptor = os.open(
        source,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        with pytest.raises(ValueError, match="symlink|unsafe"):
            storage.publish_descriptor(allocated, descriptor)
    finally:
        os.close(descriptor)

    assert list(outside.iterdir()) == []
