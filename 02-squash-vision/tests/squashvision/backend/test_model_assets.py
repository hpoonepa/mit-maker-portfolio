from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from squashvision.app import create_app
from squashvision.db import Database
from squashvision.model_assets import (
    APPLICATION_COMPATIBILITY_VERSION,
    AssetSpec,
    HuggingFaceDownloadedFile,
    ModelAssetError,
    ModelAssetManager,
    ModelManifest,
)
from squashvision.models import ModelAsset, ProcessingProfile
from squashvision.settings import Settings
from squashvision.storage import LocalStorage


class AssetServer:
    def __init__(self) -> None:
        self.payload = b"model-weights-" * 1024
        self.requests: list[dict[str, str]] = []
        self.mode = "ok"
        self.request_count = 0
        self.redirect_location: str | None = None
        self.request_started = threading.Event()
        self.delay_seconds = 0.0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:
                owner.request_count += 1
                owner.request_started.set()
                owner.requests.append({key.lower(): value for key, value in self.headers.items()})
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header(
                        "Location", owner.redirect_location or "/asset.bin"
                    )
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if owner.delay_seconds:
                    time.sleep(owner.delay_seconds)
                if owner.mode == "interrupted" or (
                    owner.mode == "retry" and owner.request_count == 1
                ):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(owner.payload) + 19))
                    self.end_headers()
                    self.wfile.write(owner.payload[:100])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(owner.payload)))
                self.send_header("ETag", '"asset-etag-1"')
                self.end_headers()
                for offset in range(0, len(owner.payload), 257):
                    self.wfile.write(owner.payload[offset : offset + 257])
                    self.wfile.flush()

            def log_message(self, _format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> AssetServer:
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def direct_spec(url: str, *, name: str = "test-model") -> AssetSpec:
    return AssetSpec(
        name=name,
        source="https",
        repo_id=url,
        filename="asset.bin",
        revision="release-1",
        required=True,
    )


def make_manager(
    tmp_path: Path,
    *,
    hf_adapter: Any = None,
    max_asset_bytes: int = 1024 * 1024,
    allowed_http_origins: set[str] | None = None,
) -> tuple[ModelAssetManager, Database, LocalStorage]:
    settings = Settings(data_dir=tmp_path)
    database = Database.open(settings)
    storage = LocalStorage(settings.storage_root)
    manager = ModelAssetManager(
        database,
        storage,
        hf_adapter=hf_adapter,
        max_asset_bytes=max_asset_bytes,
        allowed_http_origins=allowed_http_origins,
    )
    return manager, database, storage


def test_direct_https_streams_anonymously_through_redirect_with_exact_provenance(
    tmp_path: Path,
) -> None:
    with AssetServer() as server:
        manager, _, storage = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        resolved = manager.ensure(direct_spec(f"{server.base_url}/redirect"))

    assert resolved.state == "ready"
    assert resolved.byte_size == len(server.payload)
    assert resolved.sha256 == hashlib.sha256(server.payload).hexdigest()
    assert resolved.requested_revision == "release-1"
    assert resolved.resolved_revision == "release-1"
    assert resolved.etag == '"asset-etag-1"'
    assert resolved.local_path.name == f"{resolved.sha256}.bin"
    assert (storage.root / resolved.local_path).read_bytes() == server.payload
    assert resolved.downloaded_at is not None
    assert resolved.compatibility_version == APPLICATION_COMPATIBILITY_VERSION
    assert all("authorization" not in request for request in server.requests)
    assert all("cookie" not in request for request in server.requests)
    assert not list((storage.root / "models").glob("*.tmp"))


def test_production_manager_rejects_unapproved_loopback_source(
    tmp_path: Path,
) -> None:
    with AssetServer() as server:
        manager, _, _ = make_manager(tmp_path)
        with pytest.raises(ModelAssetError) as caught:
            manager.ensure(direct_spec(f"{server.base_url}/asset.bin"))

    assert caught.value.code == "model_source_not_allowed"
    assert server.request_count == 0


def test_manual_redirect_validation_blocks_unapproved_hop(tmp_path: Path) -> None:
    with AssetServer() as destination, AssetServer() as source:
        source.redirect_location = f"{destination.base_url}/asset.bin"
        manager, _, _ = make_manager(
            tmp_path, allowed_http_origins={source.base_url}
        )
        with pytest.raises(ModelAssetError) as caught:
            manager.ensure(direct_spec(f"{source.base_url}/redirect"))

    assert caught.value.code == "model_source_not_allowed"
    assert source.request_count == 1
    assert destination.request_count == 0


def test_direct_download_enforces_maximum_streamed_byte_count(tmp_path: Path) -> None:
    with AssetServer() as server:
        manager, _, storage = make_manager(
            tmp_path,
            max_asset_bytes=128,
            allowed_http_origins={server.base_url},
        )
        with pytest.raises(ModelAssetError) as caught:
            manager.ensure(direct_spec(f"{server.base_url}/asset.bin"))

    assert caught.value.code == "model_asset_too_large"
    assert not list((storage.root / "models").glob("*"))


def test_hugging_face_resolver_is_anonymous_and_persists_immutable_revision(
    tmp_path: Path,
) -> None:
    cached = tmp_path / "hf-cache" / "checkpoints" / "balltrack_best.pth"
    cached.parent.mkdir(parents=True)
    payload = b"hf-ball-weights"
    cached.write_bytes(payload)
    commit = "0123456789abcdef0123456789abcdef01234567"

    class FakeAdapter:
        def __init__(self) -> None:
            self.resolve_calls: list[dict[str, object]] = []
            self.download_calls: list[dict[str, object]] = []

        def resolve_revision(self, **kwargs: object) -> str:
            self.resolve_calls.append(kwargs)
            return commit

        def download(self, **kwargs: object) -> HuggingFaceDownloadedFile:
            self.download_calls.append(kwargs)
            return HuggingFaceDownloadedFile(path=cached, etag='"hf-etag"')

    adapter = FakeAdapter()
    manager, _, storage = make_manager(tmp_path, hf_adapter=adapter)
    spec = AssetSpec(
        name="ball",
        source="huggingface",
        repo_id="linfeng302/RacketVision-Models",
        filename="checkpoints/balltrack_best.pth",
        revision="main",
        required=True,
    )
    resolved = manager.ensure(spec)

    assert adapter.resolve_calls == [
        {
            "repo_id": "linfeng302/RacketVision-Models",
            "revision": "main",
            "token": False,
        }
    ]
    assert adapter.download_calls == [
        {
            "repo_id": "linfeng302/RacketVision-Models",
            "filename": "checkpoints/balltrack_best.pth",
            "revision": commit,
            "token": False,
        }
    ]
    assert resolved.requested_revision == "main"
    assert resolved.resolved_revision == commit
    assert resolved.etag == '"hf-etag"'
    assert resolved.declared_license == "not-declared"
    assert resolved.byte_size == len(payload)
    assert resolved.sha256 == hashlib.sha256(payload).hexdigest()
    assert (storage.root / resolved.local_path).read_bytes() == payload


def test_hugging_face_rejects_mutable_or_unparseable_resolved_revision(
    tmp_path: Path,
) -> None:
    class MutableAdapter:
        def __init__(self) -> None:
            self.resolve_calls = 0
            self.download_calls = 0

        def resolve_revision(self, **_kwargs: object) -> str:
            self.resolve_calls += 1
            return "main"

        def download(self, **_kwargs: object) -> HuggingFaceDownloadedFile:
            self.download_calls += 1
            raise AssertionError("mutable revision must never be downloaded")

    adapter = MutableAdapter()
    manager, _, _ = make_manager(tmp_path, hf_adapter=adapter)
    spec = AssetSpec(
        name="ball",
        source="huggingface",
        repo_id="linfeng302/RacketVision-Models",
        filename="checkpoints/balltrack_best.pth",
        revision="main",
        required=True,
    )

    with pytest.raises(ModelAssetError) as caught:
        manager.ensure(spec)

    assert caught.value.code == "model_revision_unavailable"
    assert adapter.resolve_calls == 1
    assert adapter.download_calls == 0
def test_concurrent_ensure_calls_publish_one_download(tmp_path: Path) -> None:
    with AssetServer() as server:
        server.delay_seconds = 0.15
        manager, _, _ = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        spec = direct_spec(f"{server.base_url}/asset.bin")
        with ThreadPoolExecutor(max_workers=6) as executor:
            resolved = list(executor.map(lambda _index: manager.ensure(spec), range(6)))

    assert server.request_count == 1
    assert {asset.sha256 for asset in resolved} == {
        hashlib.sha256(server.payload).hexdigest()
    }
    assert {asset.local_path for asset in resolved} == {resolved[0].local_path}


def test_interrupted_download_retries_once_and_cleans_temporary_siblings(
    tmp_path: Path,
) -> None:
    with AssetServer() as server:
        server.mode = "interrupted"
        manager, _, storage = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        with pytest.raises(ModelAssetError) as caught:
            manager.ensure(direct_spec(f"{server.base_url}/asset.bin"))

    assert caught.value.code == "model_download_failed"
    assert server.request_count == 2
    assert not list((storage.root / "models").glob("*"))


def test_manager_startup_removes_temporary_file_left_by_crash(tmp_path: Path) -> None:
    manager, database, storage = make_manager(tmp_path)
    del manager
    temporary = storage.create_model_temporary()
    temporary.write_bytes(b"partial-model")

    ModelAssetManager(database, storage)

    assert not temporary.exists()


def test_corrupt_download_gets_exactly_one_clean_retry(tmp_path: Path) -> None:
    with AssetServer() as server:
        server.mode = "retry"
        manager, _, storage = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        resolved = manager.ensure(direct_spec(f"{server.base_url}/asset.bin"))

    assert server.request_count == 2
    assert (storage.root / resolved.local_path).read_bytes() == server.payload
    assert not list((storage.root / "models").glob("*.tmp"))


def test_corrupt_ready_cache_is_removed_and_redownloaded_once(tmp_path: Path) -> None:
    with AssetServer() as server:
        manager, _, storage = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        spec = direct_spec(f"{server.base_url}/asset.bin")
        first = manager.ensure(spec)
        cached = storage.root / first.local_path
        cached.write_bytes(b"tampered")
        second = manager.ensure(spec)

    assert server.request_count == 2
    assert second.sha256 == hashlib.sha256(server.payload).hexdigest()
    assert cached.read_bytes() == server.payload


def test_manager_startup_rehashes_and_marks_corrupt_ready_records(
    tmp_path: Path,
) -> None:
    with AssetServer() as server:
        manager, database, storage = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        spec = direct_spec(f"{server.base_url}/asset.bin")
        resolved = manager.ensure(spec)
    cached = storage.root / resolved.local_path
    cached.write_bytes(b"corrupt-after-crash")

    ModelAssetManager(database, storage)

    with database.session() as session:
        record = session.execute(
            select(ModelAsset).where(ModelAsset.model_name == spec.name)
        ).scalar_one()
        state = record.state
        error_code = record.error_code
    assert state == "corrupt"
    assert error_code == "model_asset_corrupt"
    assert not cached.exists()


def test_offline_ready_cache_never_calls_network_after_restart(tmp_path: Path) -> None:
    with AssetServer() as server:
        manager, _, storage = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        spec = direct_spec(f"{server.base_url}/asset.bin")
        expected = manager.ensure(spec)

    class ForbiddenAdapter:
        def resolve_revision(self, **_kwargs: object) -> str:
            raise AssertionError("offline resolution must not call Hugging Face")

        def download(self, **_kwargs: object) -> HuggingFaceDownloadedFile:
            raise AssertionError("offline resolution must not call Hugging Face")

    restarted = ModelAssetManager(
        Database.open(Settings(data_dir=tmp_path)),
        storage,
        hf_adapter=ForbiddenAdapter(),
        http_client_factory=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("offline resolution must not create an HTTP client")
        ),
        allowed_http_origins={server.base_url},
    )
    actual = restarted.ensure(spec, offline=True)

    assert actual.sha256 == expected.sha256
    assert actual.resolved_revision == expected.resolved_revision


def test_startup_reconciles_interrupted_downloading_state(tmp_path: Path) -> None:
    manager, database, storage = make_manager(tmp_path)
    del manager
    with database.session() as session:
        session.add(
            ModelAsset(
                model_name="interrupted",
                source="https",
                repository="https://github.com/approved/model.bin",
                filename="model.bin",
                requested_revision="v1",
                declared_license="not-declared",
                compatibility_version=APPLICATION_COMPATIBILITY_VERSION,
                state="downloading",
            )
        )
    temporary = storage.create_model_temporary()
    temporary.write_bytes(b"partial")

    ModelAssetManager(database, storage)

    with database.session() as session:
        record = session.execute(
            select(ModelAsset).where(ModelAsset.model_name == "interrupted")
        ).scalar_one()
        assert record.state == "corrupt"
        assert record.error_code == "download_interrupted"
    assert not temporary.exists()


@pytest.mark.parametrize("seed_corrupt", [False, True], ids=["missing", "corrupt"])
def test_offline_unavailable_has_typed_error_and_removes_corruption(
    tmp_path: Path, seed_corrupt: bool
) -> None:
    spec = direct_spec("https://127.0.0.1:1/never")
    manager, database, storage = make_manager(
        tmp_path, allowed_http_origins={"https://127.0.0.1:1"}
    )
    if seed_corrupt:
        with database.session() as session:
            record = ModelAsset(
                model_name=spec.name,
                source=spec.source,
                repository=spec.repo_id,
                filename=spec.filename,
                requested_revision=spec.revision,
                resolved_revision=spec.revision,
                etag='"stale"',
                relative_path="models/deadbeef.bin",
                byte_size=4,
                sha256="0" * 64,
                declared_license="not-declared",
                downloaded_at=datetime.now(timezone.utc),
                compatibility_version=APPLICATION_COMPATIBILITY_VERSION,
                state="ready",
            )
            session.add(record)
        corrupt = storage.root / "models" / "deadbeef.bin"
        corrupt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.write_bytes(b"evil")

    with pytest.raises(ModelAssetError) as caught:
        manager.ensure(spec, offline=True)

    assert caught.value.code == "model_unavailable_offline"
    if seed_corrupt:
        assert not corrupt.exists()
        listed = manager.list_assets([spec])[0]
        assert listed.state == "corrupt"
        assert listed.local_path is None
        assert listed.byte_size is None
        assert listed.sha256 is None
        assert listed.resolved_revision is None
        assert listed.etag is None
        assert listed.downloaded_at is None


def test_compatibility_mismatch_never_reports_ready_or_downloads(tmp_path: Path) -> None:
    with AssetServer() as server:
        manager, database, _ = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        spec = direct_spec(f"{server.base_url}/asset.bin")
        manager.ensure(spec)
        with database.session() as session:
            record = session.execute(
                select(ModelAsset).where(ModelAsset.model_name == spec.name)
            ).scalar_one()
            record.compatibility_version = APPLICATION_COMPATIBILITY_VERSION + 1

        with pytest.raises(ModelAssetError) as caught:
            manager.ensure(spec)
        listed = manager.list_assets([spec])[0]

    assert caught.value.code == "model_incompatible"
    assert listed.state == "incompatible"
    assert server.request_count == 1


def test_replacement_clears_stale_provenance_before_network_io(
    tmp_path: Path,
) -> None:
    with AssetServer() as server:
        manager, _, storage = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        spec = direct_spec(f"{server.base_url}/asset.bin")
        ready = manager.ensure(spec)
        (storage.root / ready.local_path).write_bytes(b"corrupt")
        server.request_started.clear()
        server.delay_seconds = 0.2
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(manager.ensure, spec)
            assert server.request_started.wait(timeout=1)
            downloading = manager.list_assets([spec])[0]
            resolved = future.result()

    assert downloading.state == "downloading"
    assert downloading.local_path is None
    assert downloading.byte_size is None
    assert downloading.sha256 is None
    assert downloading.resolved_revision is None
    assert downloading.etag is None
    assert downloading.downloaded_at is None
    assert resolved.state == "ready"


def test_provenance_and_state_survive_manager_and_database_restart(tmp_path: Path) -> None:
    with AssetServer() as server:
        manager, _, storage = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        spec = direct_spec(f"{server.base_url}/asset.bin")
        original = manager.ensure(spec)

    restarted = ModelAssetManager(Database.open(Settings(data_dir=tmp_path)), storage)
    restored = restarted.list_assets([spec])[0]

    assert restored.state == "ready"
    assert restored.sha256 == original.sha256
    assert restored.byte_size == original.byte_size
    assert restored.etag == original.etag
    assert restored.requested_revision == "release-1"
    assert restored.resolved_revision == "release-1"
    assert restored.downloaded_at == original.downloaded_at


def test_manifest_resolves_profile_assets_and_preserves_required_flag(tmp_path: Path) -> None:
    with AssetServer() as server:
        manager, _, _ = make_manager(
            tmp_path, allowed_http_origins={server.base_url}
        )
        required = direct_spec(f"{server.base_url}/asset.bin", name="required")
        optional = AssetSpec(
            name="optional",
            source="https",
            repo_id=f"{server.base_url}/asset.bin",
            filename="asset.bin",
            revision="release-1",
            required=False,
        )
        manifest = ModelManifest(manager, specs=(required, optional))
        resolved = manifest.resolve(ProcessingProfile.FAST)

    assert [asset.name for asset in resolved] == ["required", "optional"]
    assert [asset.required for asset in resolved] == [True, False]


@pytest.mark.asyncio
async def test_model_routes_list_without_network_and_ensure_anonymously(
    tmp_path: Path,
) -> None:
    with AssetServer() as server:
        app = create_app(Settings(data_dir=tmp_path))
        spec = direct_spec(f"{server.base_url}/asset.bin", name="route-model")
        manager = ModelAssetManager(
            app.state.database,
            app.state.storage,
            allowed_http_origins={server.base_url},
        )
        app.state.model_assets = manager
        app.state.model_manifest = ModelManifest(manager, specs=(spec,))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            listed = await client.get("/api/v1/models")
            requests_after_list = server.request_count
            ensured = await client.post("/api/v1/models/route-model/ensure")
            missing = await client.post("/api/v1/models/unknown/ensure")

    assert listed.status_code == 200
    assert listed.json() == [
        {
            "name": "route-model",
            "filename": "asset.bin",
            "requestedRevision": "release-1",
            "resolvedRevision": None,
            "sourceLabel": "Approved model registry · route-model",
            "byteSize": None,
            "sha256": None,
            "declaredLicense": "not-declared",
            "downloadedAt": None,
            "compatibilityVersion": 1,
            "required": True,
            "state": "missing",
            "errorCode": None,
        }
    ]
    assert requests_after_list == 0
    assert ensured.status_code == 200
    assert ensured.json()["state"] == "ready"
    assert ensured.json()["sha256"] == hashlib.sha256(server.payload).hexdigest()
    assert missing.status_code == 404
    assert missing.json()["code"] == "model_not_found"


@pytest.mark.asyncio
async def test_health_aggregates_required_asset_state_without_network(tmp_path: Path) -> None:
    with AssetServer() as server:
        app = create_app(Settings(data_dir=tmp_path))
        required = direct_spec(f"{server.base_url}/asset.bin", name="required")
        optional = AssetSpec(
            name="optional",
            source="https",
            repo_id=f"{server.base_url}/asset.bin",
            filename="asset.bin",
            revision="release-1",
            required=False,
        )
        manager = ModelAssetManager(
            app.state.database,
            app.state.storage,
            allowed_http_origins={server.base_url},
        )
        app.state.model_assets = manager
        app.state.model_manifest = ModelManifest(manager, specs=(required, optional))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            before = await client.get("/api/v1/health")
            await client.post("/api/v1/models/required/ensure")
            after = await client.get("/api/v1/health")

    assert server.request_count == 1
    assert set(before.json()) == {
        "status",
        "version",
        "ffmpeg",
        "worker",
        "models",
    }
    assert before.json()["models"] == {
        "status": "missing",
        "assets": [
            {
                "name": "required",
                "required": True,
                "state": "missing",
                "errorCode": None,
            },
            {
                "name": "optional",
                "required": False,
                "state": "missing",
                "errorCode": None,
            },
        ],
    }
    assert after.json()["models"] == {
        "status": "ready",
        "assets": [
            {
                "name": "required",
                "required": True,
                "state": "ready",
                "errorCode": None,
            },
            {
                "name": "optional",
                "required": False,
                "state": "missing",
                "errorCode": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_health_file_verification_does_not_block_event_loop(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    original_states = app.state.model_manifest.states

    def slow_states() -> list[Any]:
        time.sleep(0.2)
        return original_states()

    app.state.model_manifest.states = slow_states
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = time.perf_counter()
        health_task = asyncio.create_task(client.get("/api/v1/health"))
        await asyncio.sleep(0.03)
        loop_delay = time.perf_counter() - started
        response = await health_task

    assert response.status_code == 200
    assert loop_delay < 0.12
