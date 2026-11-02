from __future__ import annotations

import hashlib
import os
import re
import threading
from urllib.parse import urljoin, urlsplit
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy import select

from squashvision.db import Database
from squashvision.models import ModelAsset, ModelAssetState, ProcessingProfile, utc_now
from squashvision.storage import LocalStorage

APPLICATION_COMPATIBILITY_VERSION = 1
DEFAULT_MAX_MODEL_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_STREAM_CHUNK_BYTES = 64 * 1024
_MAX_REDIRECTS = 10
_PRODUCTION_HTTP_ORIGINS = frozenset(
    {
        "https://github.com",
        "https://release-assets.githubusercontent.com",
        "https://objects.githubusercontent.com",
    }
)
_HF_COMMIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HF_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


@dataclass(frozen=True, slots=True)
class AssetSpec:
    name: str
    source: str
    repo_id: str
    filename: str
    revision: str
    required: bool

    def __post_init__(self) -> None:
        if self.source not in {"https", "huggingface"}:
            raise ValueError(f"unsupported model source: {self.source}")
        if not all((self.name, self.repo_id, self.filename, self.revision)):
            raise ValueError("model asset specification fields must not be empty")


@dataclass(frozen=True, slots=True)
class HuggingFaceDownloadedFile:
    path: Path
    etag: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    name: str
    source: str
    url: str | None
    repository: str | None
    filename: str
    requested_revision: str
    resolved_revision: str | None
    etag: str | None
    local_path: Path | None
    byte_size: int | None
    sha256: str | None
    declared_license: str
    downloaded_at: datetime | None
    compatibility_version: int
    required: bool
    state: ModelAssetState
    error_code: str | None


def public_source_label(asset: ResolvedAsset) -> str:
    if (
        asset.source == "huggingface"
        and asset.repository is not None
        and _HF_REPOSITORY.fullmatch(asset.repository)
    ):
        return f"Hugging Face · {asset.repository}"
    if asset.source == "https" and asset.url is not None:
        parsed = urlsplit(asset.url)
        parts = tuple(part for part in parsed.path.split("/") if part)
        if (
            parsed.scheme == "https"
            and parsed.hostname == "github.com"
            and len(parts) >= 6
            and parts[2:4] == ("releases", "download")
        ):
            return f"GitHub · {parts[0]}/{parts[1]} · {asset.requested_revision}"
    return f"Approved model registry · {asset.name}"




class ModelAssetError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class HuggingFaceAdapter(Protocol):
    def resolve_revision(
        self, *, repo_id: str, revision: str, token: bool
    ) -> str: ...

    def download(
        self,
        *,
        repo_id: str,
        filename: str,
        revision: str,
        token: bool,
    ) -> HuggingFaceDownloadedFile: ...


@dataclass(frozen=True, slots=True)
class _PreparedAsset:
    path: Path
    byte_size: int
    sha256: str
    resolved_revision: str
    etag: str | None


class _RetriableDownload(Exception):
    pass


POSE_ASSET = AssetSpec(
    name="pose",
    source="https",
    repo_id=(
        "https://github.com/ultralytics/assets/releases/download/"
        "v8.3.0/yolo11n-pose.pt"
    ),
    filename="yolo11n-pose.pt",
    revision="v8.3.0",
    required=True,
)
BALL_ASSET = AssetSpec(
    name="ball",
    source="huggingface",
    repo_id="linfeng302/RacketVision-Models",
    filename="checkpoints/balltrack_best.pth",
    revision="main",
    required=True,
)
DEFAULT_ASSET_SPECS = (POSE_ASSET, BALL_ASSET)
_DECLARED_LICENSES = {
    POSE_ASSET.name: "AGPL-3.0",
    BALL_ASSET.name: "not-declared",
}


def _declared_license(spec: AssetSpec) -> str:
    return _DECLARED_LICENSES.get(spec.name, "not-declared")


class AnonymousHuggingFaceAdapter:
    def resolve_revision(
        self, *, repo_id: str, revision: str, token: bool
    ) -> str:
        from huggingface_hub import HfApi

        info = HfApi(token=token).model_info(
            repo_id,
            revision=revision,
            token=token,
        )
        return info.sha or ""

    def download(
        self,
        *,
        repo_id: str,
        filename: str,
        revision: str,
        token: bool,
    ) -> HuggingFaceDownloadedFile:
        from huggingface_hub import hf_hub_download

        path = Path(
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                revision=revision,
                token=token,
            )
        )
        parts = path.parts
        try:
            snapshot_index = parts.index("snapshots")
        except ValueError as error:
            raise ModelAssetError(
                "model_revision_unavailable",
                "Hugging Face cache path did not identify an immutable snapshot",
            ) from error
        expected_tail = (revision, *Path(filename).parts)
        if (
            snapshot_index == 0
            or not parts[snapshot_index - 1].startswith("models--")
            or parts[snapshot_index + 1 :] != expected_tail
        ):
            raise ModelAssetError(
                "model_revision_unavailable",
                "Hugging Face cache path did not match the pinned revision",
            )
        return HuggingFaceDownloadedFile(path=path)


class ModelAssetManager:
    _locks_guard = threading.Lock()
    _locks: dict[tuple[str, str], threading.Lock] = {}

    def __init__(
        self,
        database: Database,
        storage: LocalStorage,
        *,
        hf_adapter: HuggingFaceAdapter | None = None,
        http_client_factory: Callable[..., Any] = httpx.Client,
        max_asset_bytes: int = DEFAULT_MAX_MODEL_ASSET_BYTES,
        allowed_http_origins: Iterable[str] | None = None,
    ) -> None:
        if max_asset_bytes <= 0:
            raise ValueError("max_asset_bytes must be positive")
        self.database = database
        self.storage = storage
        self.storage.cleanup_model_temporaries()
        self._reconcile_interrupted_downloads()
        self.hf_adapter = hf_adapter or AnonymousHuggingFaceAdapter()
        self.http_client_factory = http_client_factory
        self.max_asset_bytes = max_asset_bytes
        self._test_http_origins = (
            None
            if allowed_http_origins is None
            else frozenset(self._normalise_origin(origin) for origin in allowed_http_origins)
        )
        self._rehash_ready_records()

    def ensure(self, spec: AssetSpec, *, offline: bool = False) -> ResolvedAsset:
        self._validate_spec(spec)
        with self._lock_for(spec.name):
            current = self._current(spec)
            if current.state == ModelAssetState.READY:
                return current
            if current.state == ModelAssetState.INCOMPATIBLE:
                raise ModelAssetError(
                    "model_incompatible",
                    f"model asset {spec.name!r} is incompatible with this application",
                    status_code=409,
                )
            if offline:
                raise ModelAssetError(
                    "model_unavailable_offline",
                    f"model asset {spec.name!r} is not available in the local cache",
                    status_code=503,
                )

            self._set_downloading(spec)
            last_error: BaseException | None = None
            for _attempt in range(2):
                try:
                    prepared = self._download(spec)
                    stored = self.storage.publish_model(
                        prepared.path, prepared.sha256, self._suffix(spec.filename)
                    )
                    published_size, published_sha = self._hash_file(stored.absolute)
                    if (
                        published_size != prepared.byte_size
                        or published_sha != prepared.sha256
                    ):
                        self.storage.delete_model(stored.relative)
                        raise _RetriableDownload("published model failed verification")
                    self._set_ready(spec, prepared, stored.relative)
                    return self._current(spec)
                except ModelAssetError as error:
                    self._set_error(spec, ModelAssetState.CORRUPT, error.code)
                    raise
                except (OSError, httpx.HTTPError, _RetriableDownload) as error:
                    last_error = error

            self._set_error(spec, ModelAssetState.CORRUPT, "model_download_failed")
            raise ModelAssetError(
                "model_download_failed",
                f"model asset {spec.name!r} could not be downloaded safely",
            ) from last_error

    def list_assets(self, specs: Iterable[AssetSpec]) -> list[ResolvedAsset]:
        return [self._current(spec) for spec in specs]

    def _current(self, spec: AssetSpec) -> ResolvedAsset:
        with self.database.session() as session:
            record = session.execute(
                select(ModelAsset).where(ModelAsset.model_name == spec.name)
            ).scalar_one_or_none()
            if record is None:
                return self._missing(spec)
            if record.compatibility_version != APPLICATION_COMPATIBILITY_VERSION:
                record.state = ModelAssetState.INCOMPATIBLE
                record.error_code = "model_incompatible"
                return self._from_record(spec, record)
            if not self._record_matches_spec(record, spec):
                self._remove_cached(record)
                record.state = ModelAssetState.CORRUPT
                record.error_code = "model_spec_changed"
                self._clear_provenance(record)
                return self._from_record(spec, record)
            if record.state == ModelAssetState.READY and not self._record_is_valid(record):
                self._remove_cached(record)
                record.state = ModelAssetState.CORRUPT
                self._clear_provenance(record)
                record.error_code = "model_asset_corrupt"
            return self._from_record(spec, record)

    def _rehash_ready_records(self) -> None:
        with self.database.session() as session:
            records = session.execute(
                select(ModelAsset).where(
                    ModelAsset.state == ModelAssetState.READY
                )
            ).scalars()
            for record in records:
                if not self._record_is_valid(record):
                    self._remove_cached(record)
                    self._clear_provenance(record)
                    record.state = ModelAssetState.CORRUPT
                    record.error_code = "model_asset_corrupt"

    def _reconcile_interrupted_downloads(self) -> None:
        with self.database.session() as session:
            records = session.execute(
                select(ModelAsset).where(
                    ModelAsset.state == ModelAssetState.DOWNLOADING
                )
            ).scalars()
            for record in records:
                self._remove_cached(record)
                self._clear_provenance(record)
                record.state = ModelAssetState.CORRUPT
                record.error_code = "download_interrupted"

    def _record_matches_spec(self, record: ModelAsset, spec: AssetSpec) -> bool:
        return (
            record.source == spec.source
            and record.repository == spec.repo_id
            and record.filename == spec.filename
            and record.requested_revision == spec.revision
        )

    def _record_is_valid(self, record: ModelAsset) -> bool:
        if (
            record.relative_path is None
            or record.byte_size is None
            or record.sha256 is None
        ):
            return False
        relative = Path(record.relative_path)
        try:
            stored = self.storage.resolve(relative, owned_paths={relative})
            size, sha256 = self._hash_file(stored.absolute)
        except (OSError, ValueError):
            return False
        return size == record.byte_size and sha256 == record.sha256

    def _remove_cached(self, record: ModelAsset) -> None:
        if record.relative_path is None:
            return
        try:
            self.storage.delete_model(Path(record.relative_path))
        except (OSError, ValueError):
            pass

    @staticmethod
    def _clear_provenance(record: ModelAsset) -> None:
        record.resolved_revision = None
        record.etag = None
        record.relative_path = None
        record.byte_size = None
        record.sha256 = None
        record.downloaded_at = None

    def _set_downloading(self, spec: AssetSpec) -> None:
        with self.database.session() as session:
            record = session.execute(
                select(ModelAsset).where(ModelAsset.model_name == spec.name)
            ).scalar_one_or_none()
            if record is None:
                record = ModelAsset(
                    model_name=spec.name,
                    source=spec.source,
                    repository=spec.repo_id,
                    filename=spec.filename,
                    requested_revision=spec.revision,
                    declared_license=_declared_license(spec),
                    compatibility_version=APPLICATION_COMPATIBILITY_VERSION,
                    state=ModelAssetState.DOWNLOADING,
                )
                session.add(record)
            else:
                self._clear_provenance(record)
                record.source = spec.source
                record.repository = spec.repo_id
                record.filename = spec.filename
                record.requested_revision = spec.revision
                record.declared_license = _declared_license(spec)
                record.compatibility_version = APPLICATION_COMPATIBILITY_VERSION
                record.state = ModelAssetState.DOWNLOADING
                record.error_code = None

    def _set_ready(
        self, spec: AssetSpec, prepared: _PreparedAsset, relative_path: Path
    ) -> None:
        with self.database.session() as session:
            record = session.execute(
                select(ModelAsset).where(ModelAsset.model_name == spec.name)
            ).scalar_one()
            record.resolved_revision = prepared.resolved_revision
            record.etag = prepared.etag
            record.relative_path = relative_path.as_posix()
            record.byte_size = prepared.byte_size
            record.sha256 = prepared.sha256
            record.downloaded_at = utc_now()
            record.compatibility_version = APPLICATION_COMPATIBILITY_VERSION
            record.state = ModelAssetState.READY
            record.error_code = None

    def _set_error(
        self, spec: AssetSpec, state: ModelAssetState, error_code: str
    ) -> None:
        with self.database.session() as session:
            record = session.execute(
                select(ModelAsset).where(ModelAsset.model_name == spec.name)
            ).scalar_one_or_none()
            if record is None:
                record = ModelAsset(
                    model_name=spec.name,
                    source=spec.source,
                    repository=spec.repo_id,
                    filename=spec.filename,
                    requested_revision=spec.revision,
                    declared_license=_declared_license(spec),
                    compatibility_version=APPLICATION_COMPATIBILITY_VERSION,
                    state=state,
                    error_code=error_code,
                )
                session.add(record)
            else:
                if state == ModelAssetState.CORRUPT:
                    self._clear_provenance(record)
                record.state = state
                record.error_code = error_code

    def _download(self, spec: AssetSpec) -> _PreparedAsset:
        try:
            if spec.source == "https":
                return self._download_https(spec)
            return self._copy_hugging_face(spec)
        except ModelAssetError:
            raise
        except (OSError, httpx.HTTPError) as error:
            raise _RetriableDownload(str(error)) from error
        except Exception as error:
            raise _RetriableDownload(str(error)) from error

    def _download_https(self, spec: AssetSpec) -> _PreparedAsset:
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
        client = self.http_client_factory(
            follow_redirects=False,
            timeout=timeout,
            auth=None,
            cookies=None,
            trust_env=False,
        )
        url = spec.repo_id
        with client:
            for redirect_count in range(_MAX_REDIRECTS + 1):
                self._validate_http_url(url)
                client.cookies.clear()
                with client.stream(
                    "GET",
                    url,
                    headers={"Accept": "application/octet-stream"},
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if location is None:
                            raise ModelAssetError(
                                "model_download_failed",
                                "model redirect did not include a location",
                            )
                        if redirect_count == _MAX_REDIRECTS:
                            raise ModelAssetError(
                                "model_download_failed",
                                "model download exceeded the redirect limit",
                            )
                        url = urljoin(url, location)
                        self._validate_http_url(url)
                        continue
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if (
                        content_length is not None
                        and int(content_length) > self.max_asset_bytes
                    ):
                        raise ModelAssetError(
                            "model_asset_too_large",
                            f"model asset {spec.name!r} exceeds the configured byte limit",
                            status_code=413,
                        )
                    return self._write_chunks(
                        response.iter_bytes(chunk_size=_STREAM_CHUNK_BYTES),
                        resolved_revision=spec.revision,
                        etag=response.headers.get("etag"),
                        name=spec.name,
                    )
        raise ModelAssetError("model_download_failed", "model download did not resolve")

    def _validate_spec(self, spec: AssetSpec) -> None:
        if spec in DEFAULT_ASSET_SPECS:
            return
        if (
            self._test_http_origins is not None
            and spec.source == "https"
            and self._normalise_origin(spec.repo_id) in self._test_http_origins
        ):
            return
        raise ModelAssetError(
            "model_source_not_allowed",
            f"model asset {spec.name!r} is not an approved public asset",
            status_code=403,
        )

    def _validate_http_url(self, url: str) -> None:
        origin = self._normalise_origin(url)
        allowed = set(_PRODUCTION_HTTP_ORIGINS)
        if self._test_http_origins is not None:
            allowed.update(self._test_http_origins)
        if origin not in allowed:
            raise ModelAssetError(
                "model_source_not_allowed",
                f"model download origin {origin!r} is not approved",
                status_code=403,
            )

    @staticmethod
    def _normalise_origin(url: str) -> str:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ModelAssetError(
                "model_source_not_allowed",
                "model download URL is not a valid approved HTTP origin",
                status_code=403,
            )
        default_port = 443 if parsed.scheme == "https" else 80
        port = parsed.port or default_port
        suffix = "" if port == default_port else f":{port}"
        return f"{parsed.scheme}://{parsed.hostname.lower()}{suffix}"

    def _copy_hugging_face(self, spec: AssetSpec) -> _PreparedAsset:
        resolved_revision = self.hf_adapter.resolve_revision(
            repo_id=spec.repo_id,
            revision=spec.revision,
            token=False,
        )
        if not _HF_COMMIT_SHA.fullmatch(resolved_revision):
            raise ModelAssetError(
                "model_revision_unavailable",
                f"Hugging Face did not resolve {spec.revision!r} to an immutable commit",
            )
        downloaded = self.hf_adapter.download(
            repo_id=spec.repo_id,
            filename=spec.filename,
            revision=resolved_revision,
            token=False,
        )
        path = Path(downloaded.path)
        if path.stat().st_size > self.max_asset_bytes:
            raise ModelAssetError(
                "model_asset_too_large",
                f"model asset {spec.name!r} exceeds the configured byte limit",
                status_code=413,
            )

        def chunks() -> Iterator[bytes]:
            with path.open("rb") as source:
                while chunk := source.read(_STREAM_CHUNK_BYTES):
                    yield chunk

        return self._write_chunks(
            chunks(),
            resolved_revision=resolved_revision,
            etag=downloaded.etag,
            name=spec.name,
        )

    def _write_chunks(
        self,
        chunks: Iterable[bytes],
        *,
        resolved_revision: str,
        etag: str | None,
        name: str,
    ) -> _PreparedAsset:
        temporary = self.storage.create_model_temporary()
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with temporary.open("wb") as destination:
                for chunk in chunks:
                    byte_size += len(chunk)
                    if byte_size > self.max_asset_bytes:
                        raise ModelAssetError(
                            "model_asset_too_large",
                            f"model asset {name!r} exceeds the configured byte limit",
                            status_code=413,
                        )
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if byte_size == 0:
                raise _RetriableDownload("downloaded model asset is empty")
            return _PreparedAsset(
                path=temporary,
                byte_size=byte_size,
                sha256=digest.hexdigest(),
                resolved_revision=resolved_revision,
                etag=etag,
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _hash_file(path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as source:
            while chunk := source.read(_STREAM_CHUNK_BYTES):
                byte_size += len(chunk)
                digest.update(chunk)
        return byte_size, digest.hexdigest()

    @staticmethod
    def _suffix(filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        return suffix if suffix else ".bin"

    def _lock_for(self, name: str) -> threading.Lock:
        key = (str(self.storage.root), name)
        with type(self)._locks_guard:
            return type(self)._locks.setdefault(key, threading.Lock())

    @staticmethod
    def _missing(spec: AssetSpec) -> ResolvedAsset:
        return ResolvedAsset(
            name=spec.name,
            source=spec.source,
            url=spec.repo_id if spec.source == "https" else None,
            repository=spec.repo_id if spec.source == "huggingface" else None,
            filename=spec.filename,
            requested_revision=spec.revision,
            resolved_revision=None,
            etag=None,
            local_path=None,
            byte_size=None,
            sha256=None,
            declared_license=_declared_license(spec),
            downloaded_at=None,
            compatibility_version=APPLICATION_COMPATIBILITY_VERSION,
            required=spec.required,
            state=ModelAssetState.MISSING,
            error_code=None,
        )

    @staticmethod
    def _from_record(spec: AssetSpec, record: ModelAsset) -> ResolvedAsset:
        downloaded_at = record.downloaded_at
        if downloaded_at is not None and downloaded_at.tzinfo is None:
            downloaded_at = downloaded_at.replace(tzinfo=timezone.utc)
        return ResolvedAsset(
            name=spec.name,
            source=spec.source,
            url=spec.repo_id if spec.source == "https" else None,
            repository=spec.repo_id if spec.source == "huggingface" else None,
            filename=spec.filename,
            requested_revision=spec.revision,
            resolved_revision=record.resolved_revision,
            etag=record.etag,
            local_path=(Path(record.relative_path) if record.relative_path else None),
            byte_size=record.byte_size,
            sha256=record.sha256,
            declared_license=record.declared_license,
            downloaded_at=downloaded_at,
            compatibility_version=record.compatibility_version,
            required=spec.required,
            state=record.state,
            error_code=record.error_code,
        )


class ModelManifest:
    def __init__(
        self,
        manager: ModelAssetManager,
        *,
        specs: Iterable[AssetSpec] = DEFAULT_ASSET_SPECS,
    ) -> None:
        self.manager = manager
        self.specs = tuple(specs)
        if len({spec.name for spec in self.specs}) != len(self.specs):
            raise ValueError("model manifest names must be unique")

    def resolve(
        self, profile: ProcessingProfile, *, offline: bool = False
    ) -> list[ResolvedAsset]:
        ProcessingProfile(profile)
        return [self.manager.ensure(spec, offline=offline) for spec in self.specs]

    def states(self) -> list[ResolvedAsset]:
        return self.manager.list_assets(self.specs)

    def spec(self, name: str) -> AssetSpec:
        for spec in self.specs:
            if spec.name == name:
                return spec
        raise ModelAssetError(
            "model_not_found",
            f"model asset {name!r} is not in the manifest",
            status_code=404,
        )
