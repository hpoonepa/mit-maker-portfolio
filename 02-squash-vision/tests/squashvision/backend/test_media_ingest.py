from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from collections import namedtuple
from io import BytesIO
from pathlib import Path
from threading import Event, Lock
from time import monotonic


import av
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))
import squashvision.app as app_module
import squashvision.media as media_module
import squashvision.routes.health as health_module
import squashvision.routes.matches as matches_routes

from squashvision.app import create_app
from squashvision.db import Database
from squashvision.media import (
    CHUNK_BYTES,
    IngestedMedia,
    MediaError,
    TimestampMap,
    TimestampPair,
    VideoProbe,
    create_proxy,
    ingest_upload,
    probe_video,
)
from squashvision.models import AssetKind, Match, MediaAsset
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
from starlette.requests import Request


class RecordingStream(BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        return super().read(size)


def video_probe(*, duration: float = 5.0, variable: bool = False) -> VideoProbe:
    return VideoProbe(
        format_names=("mov", "mp4", "m4a", "3gp", "3g2", "mj2"),
        duration=duration,
        width=1280,
        height=720,
        codec="h264",
        time_base="1/12800",
        average_frame_rate="25/1" if not variable else "48/2",
        real_frame_rate="25/1" if not variable else "30/1",
        rotation=0,
        has_video=True,
        has_audio=True,
        variable_frame_rate=variable,
    )


def generated_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


@pytest.fixture(scope="session")
def ffmpeg_tool() -> None:
    try:
        media_module.resolve_ffmpeg_binary()
    except MediaError:
        pytest.skip("real fixture tests require bundled FFmpeg")


@pytest.fixture(scope="session")
def media_tools(ffmpeg_tool: None) -> None:
    pass


@pytest.fixture(scope="session")
def squash_fixtures(
    tmp_path_factory: pytest.TempPathFactory, ffmpeg_tool: None
) -> tuple[Path, Path]:
    output_dir = tmp_path_factory.mktemp("squash-media")
    script = Path(__file__).resolve().parents[3] / "scripts/make_squash_fixture.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(output_dir)],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert "squash_fixture.mp4" in completed.stdout
    cfr = output_dir / "squash_fixture.mp4"
    vfr = output_dir / "squash_fixture_vfr.mp4"
    assert cfr.is_file() and vfr.is_file()
    return cfr, vfr


def test_fixture_generator_creates_real_deterministic_videos(
    squash_fixtures: tuple[Path, Path], tmp_path: Path
) -> None:
    cfr, vfr = squash_fixtures
    assert cfr.stat().st_size > 10_000
    assert vfr.stat().st_size > 10_000

    script = Path(__file__).resolve().parents[3] / "scripts/make_squash_fixture.py"
    subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    for fixture in (cfr, vfr):
        regenerated = tmp_path / fixture.name
        assert hashlib.sha256(regenerated.read_bytes()).digest() == hashlib.sha256(
            fixture.read_bytes()
        ).digest()



def test_ffmpeg_resolver_ignores_hanging_path_binary_and_caches_verified_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hanging_path_binary = tmp_path / "path-ffmpeg"
    bundled_binary = tmp_path / "bundled-ffmpeg"
    hanging_path_binary.write_bytes(b"wrong architecture")
    bundled_binary.write_bytes(b"native bundle")
    checks: list[list[str]] = []

    monkeypatch.setattr(
        media_module.shutil,
        "which",
        lambda _name: str(hanging_path_binary),
    )
    monkeypatch.setattr(
        media_module,
        "_bundled_ffmpeg_candidate",
        lambda: bundled_binary,
        raising=False,
    )

    def version_check(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        checks.append(arguments)
        if arguments[0] == str(hanging_path_binary):
            raise subprocess.TimeoutExpired(arguments, timeout=0.01)
        return subprocess.CompletedProcess(arguments, 0, stdout="ffmpeg version", stderr="")

    monkeypatch.setattr(media_module.subprocess, "run", version_check)
    media_module.resolve_ffmpeg_binary.cache_clear()
    try:
        assert media_module.resolve_ffmpeg_binary() == bundled_binary.resolve()
        assert media_module.resolve_ffmpeg_binary() == bundled_binary.resolve()
    finally:
        media_module.resolve_ffmpeg_binary.cache_clear()

    assert checks == [[str(bundled_binary.resolve()), "-version"]]


def test_concurrent_ffmpeg_resolution_runs_one_version_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled_binary = tmp_path / "bundled-ffmpeg"
    bundled_binary.write_bytes(b"native bundle")
    runner_entered = Event()
    duplicate_runner_entered = Event()
    release_runner = Event()
    count_lock = Lock()
    checks = 0

    monkeypatch.setattr(
        media_module,
        "_bundled_ffmpeg_candidate",
        lambda: bundled_binary,
    )

    def version_check(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal checks
        with count_lock:
            checks += 1
            if checks == 1:
                runner_entered.set()
            else:
                duplicate_runner_entered.set()
        assert release_runner.wait(timeout=2)
        return subprocess.CompletedProcess(
            arguments, 0, stdout="ffmpeg version", stderr=""
        )

    monkeypatch.setattr(media_module.subprocess, "run", version_check)
    media_module.resolve_ffmpeg_binary.cache_clear()
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(media_module.resolve_ffmpeg_binary)
                for _ in range(8)
            ]
            assert runner_entered.wait(timeout=1)
            duplicate_before_release = duplicate_runner_entered.wait(timeout=0.1)
            release_runner.set()
            results = [future.result(timeout=2) for future in futures]
    finally:
        release_runner.set()
        media_module.resolve_ffmpeg_binary.cache_clear()

    assert not duplicate_before_release
    assert checks == 1
    assert results == [bundled_binary.resolve()] * 8


def test_proxy_and_health_use_canonical_ffmpeg_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    safe_binary = (tmp_path / "safe-ffmpeg").resolve()
    source = tmp_path / "source.mp4"
    destination = tmp_path / "proxy.mp4"
    source.write_bytes(b"source")
    calls: list[list[str]] = []

    monkeypatch.setattr(media_module, "resolve_ffmpeg_binary", lambda: safe_binary)

    def media_command(
        arguments: list[str], *, timeout_seconds: float
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(media_module, "_run_media_command", media_command)
    monkeypatch.setattr(
        media_module,
        "_frame_timestamps",
        lambda path, _timeout: [5.0, 6.0]
        if path == source
        else [2.0, 3.0],
    )

    mapping = create_proxy(source, destination)
    arguments = calls[0]
    assert arguments[0] == str(safe_binary)
    assert arguments[arguments.index("-g") + 1] == "60"
    assert mapping.samples[-1] == TimestampPair(
        source_seconds=1.0, proxy_seconds=1.0
    )

    monkeypatch.setattr(
        health_module, "resolve_ffmpeg_binary", lambda: safe_binary
    )
    health = health_module._health_response(Settings(data_dir=tmp_path))
    assert health.ffmpeg.status == "ready"

@pytest.mark.asyncio
async def test_match_upload_rejects_oversized_content_length_without_receiving(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path, max_upload_bytes=4, min_free_disk_bytes=0)
    app = create_app(settings)
    receive_calls = 0
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal receive_calls
        receive_calls += 1
        raise AssertionError("oversized Content-Length must be rejected before receive")

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    raw_limit = settings.max_upload_bytes + app_module.MULTIPART_OVERHEAD_BYTES
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/matches",
            "raw_path": b"/api/v1/matches",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"content-length", str(raw_limit + 1).encode())],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 80),
        },
        receive,
        send,
    )

    assert receive_calls == 0
    assert messages[0]["status"] == 413
    assert json.loads(messages[1]["body"])["code"] == "upload_too_large"


@pytest.mark.asyncio
async def test_match_upload_stops_chunked_body_at_raw_cap() -> None:
    received_by_inner = 0
    messages: list[dict[str, object]] = []
    chunks = [b"x" * 12, b"y"]

    async def inner(
        _scope: dict[str, object],
        receive: object,
        _send: object,
    ) -> None:
        nonlocal received_by_inner
        while True:
            message = await receive()
            received_by_inner += len(message.get("body", b""))
            if not message.get("more_body", False):
                return

    middleware = app_module.MatchUploadLimitMiddleware(
        inner, max_upload_bytes=4, multipart_overhead_bytes=8
    )

    async def receive() -> dict[str, object]:
        chunk = chunks.pop(0)
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": bool(chunks),
        }

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/matches",
            "headers": [],
        },
        receive,
        send,
    )

    assert received_by_inner == 12
    assert messages[0]["status"] == 413


def test_concurrent_ingests_hold_disk_reserve_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    first_read_started = Event()
    release_first = Event()
    second_read_started = Event()

    class BlockingStream(BytesIO):
        def read(self, size: int = -1) -> bytes:
            first_read_started.set()
            assert release_first.wait(timeout=2)
            return super().read(size)

    class NotifyingStream(BytesIO):
        def read(self, size: int = -1) -> bytes:
            second_read_started.set()
            return super().read(size)

    usage = namedtuple("usage", "total used free")

    def disk_usage(_path: Path) -> object:
        originals = storage.root / "videos/original"
        used = sum(path.stat().st_size for path in originals.glob("*")) if originals.exists() else 0
        return usage(100, used, 9 - used)

    monkeypatch.setattr("squashvision.media.shutil.disk_usage", disk_usage)
    monkeypatch.setattr(
        "squashvision.media.probe_video",
        lambda _path, **_kwargs: video_probe(),
    )

    def ingest(stream: BytesIO) -> str:
        try:
            ingest_upload(
                stream,
                "video.mp4",
                storage,
                max_bytes=4,
                min_free_disk_bytes=5,
            )
        except MediaError as error:
            return error.code
        return "stored"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(ingest, BlockingStream(b"1234"))
        assert first_read_started.wait(timeout=1)
        second = executor.submit(ingest, NotifyingStream(b"5678"))
        second_entered_while_locked = second_read_started.wait(timeout=0.1)
        release_first.set()
        outcomes = sorted([first.result(timeout=2), second.result(timeout=2)])

    assert not second_entered_while_locked
    assert outcomes == ["insufficient_disk", "stored"]


def test_probed_container_not_filename_controls_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(
        "squashvision.media.probe_video",
        lambda _path, **_kwargs: video_probe().model_copy(
            update={"format_names": ("avi",)}
        ),
    )

    with pytest.raises(MediaError) as raised:
        ingest_upload(
            BytesIO(b"avi bytes"),
            "misleading.mp4",
            storage,
            min_free_disk_bytes=0,
        )

    assert raised.value.code == "unsupported_container"
    assert generated_files(storage.root) == []


def test_timestamp_collection_is_bounded_and_preserves_endpoints() -> None:
    timestamps = media_module._bounded_timestamps(
        (float(value) for value in range(100_000)),
        maximum=media_module.MAX_TIMESTAMP_POINTS,
    )

    assert len(timestamps) <= media_module.MAX_TIMESTAMP_POINTS
    assert timestamps[0] == 0.0
    assert timestamps[-1] == 99_999.0
    assert timestamps == sorted(timestamps)

    endpoint_only = media_module._bounded_timestamps(
        (float(value) for value in range(10)), maximum=2
    )
    assert endpoint_only == [0.0, 9.0]


def test_timestamp_mapping_normalizes_nonzero_origins() -> None:
    mapping = media_module._build_timestamp_map(
        source_timestamps=[10.0, 11.0, 12.0],
        proxy_timestamps=[3.0, 4.0, 5.0],
    )

    assert mapping.samples == [
        TimestampPair(source_seconds=0.0, proxy_seconds=0.0),
        TimestampPair(source_seconds=1.0, proxy_seconds=1.0),
        TimestampPair(source_seconds=2.0, proxy_seconds=2.0),
    ]


def test_probe_video_never_invokes_hanging_path_ffprobe(
    squash_fixtures: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _vfr = squash_fixtures
    monkeypatch.setattr(
        media_module.shutil, "which", lambda _name: "/usr/local/bin/ffprobe"
    )

    def forbidden_subprocess(
        _arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("probe_video must not invoke PATH ffprobe")

    monkeypatch.setattr(media_module.subprocess, "run", forbidden_subprocess)
    started = monotonic()
    result = probe_video(source)

    assert monotonic() - started < 5
    assert result.has_video
    assert result.duration == pytest.approx(5.0, abs=0.1)


def test_ffprobe_json_compatibility_parser_is_pure() -> None:
    payload = {
        "format": {
            "duration": "5.000000",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1280,
                "height": 720,
                "time_base": "1/12800",
                "avg_frame_rate": "24000/1001",
                "r_frame_rate": "30/1",
                "duration": "5.000000",
                "tags": {"rotate": "0"},
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }

    result = media_module._video_probe_from_ffprobe_payload(payload)

    assert result == video_probe(variable=True).model_copy(
        update={"average_frame_rate": "24000/1001"}
    )


def test_ingest_streams_one_mib_chunks_hashes_and_ignores_unsafe_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"a" * (CHUNK_BYTES + 17)
    stream = RecordingStream(data)
    storage = LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(
        "squashvision.media.probe_video", lambda _path, **_kwargs: video_probe()
    )

    ingested = ingest_upload(
        stream,
        "../../victim.MP4",
        storage,
        max_bytes=len(data),
        min_free_disk_bytes=0,
    )

    assert isinstance(ingested, IngestedMedia)
    assert stream.requested_sizes == [CHUNK_BYTES, CHUNK_BYTES, CHUNK_BYTES]
    assert ingested.sha256 == hashlib.sha256(data).hexdigest()
    assert ingested.bytes == len(data)
    assert ingested.suffix == ".mp4"
    assert ingested.stored_path.relative.parts[:2] == ("videos", "original")
    assert "victim" not in ingested.stored_path.relative.name
    assert ingested.stored_path.absolute.read_bytes() == data
    assert ingested.stored_path.absolute.stat().st_mode & 0o222 == 0


@pytest.mark.parametrize("filename", ["video.avi", "video.mkv", "video", "video.mp4.exe"])
def test_ingest_rejects_unsupported_container_without_writing(
    tmp_path: Path, filename: str
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    with pytest.raises(MediaError, match="supported") as raised:
        ingest_upload(BytesIO(b"data"), filename, storage)

    assert raised.value.code == "unsupported_container"
    assert generated_files(storage.root) == []


def test_ingest_enforces_exact_byte_limit_and_removes_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    monkeypatch.setattr("squashvision.media.probe_video", lambda _path: video_probe())

    with pytest.raises(MediaError) as raised:
        ingest_upload(
            BytesIO(b"x" * 11),
            "video.mp4",
            storage,
            max_bytes=10,
            min_free_disk_bytes=0,
        )

    assert raised.value.code == "upload_too_large"
    assert generated_files(storage.root) == []


def test_ingest_rejects_low_disk_before_reading_or_allocating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    stream = RecordingStream(b"video")
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "squashvision.media.shutil.disk_usage", lambda _path: usage(100, 96, 4)
    )

    with pytest.raises(MediaError) as raised:
        ingest_upload(
            stream,
            "video.mp4",
            storage,
            max_bytes=100,
            min_free_disk_bytes=5,
        )

    assert raised.value.code == "insufficient_disk"
    assert stream.requested_sizes == []
    assert generated_files(storage.root) == []


def test_invalid_probe_and_no_video_leave_no_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")

    def invalid(_path: Path, **_kwargs: object) -> VideoProbe:
        raise MediaError("invalid_media", "not a readable media file", 422)

    monkeypatch.setattr("squashvision.media.probe_video", invalid)
    with pytest.raises(MediaError) as invalid_error:
        ingest_upload(
            BytesIO(b"not video"),
            "bad.mp4",
            storage,
            min_free_disk_bytes=0,
        )
    assert invalid_error.value.code == "invalid_media"
    assert generated_files(storage.root) == []

    monkeypatch.setattr(
        "squashvision.media.probe_video",
        lambda _path, **_kwargs: video_probe().model_copy(update={"has_video": False}),
    )
    with pytest.raises(MediaError) as no_video_error:
        ingest_upload(
            BytesIO(b"audio only"),
            "audio.mp4",
            storage,
            min_free_disk_bytes=0,
        )
    assert no_video_error.value.code == "no_video_stream"
    assert generated_files(storage.root) == []
def test_primary_video_duration_precedes_overstated_container_duration() -> None:
    payload = {
        "format": {"format_name": "mov,mp4", "duration": "3605.0"},
        "streams": [
            {
                "codec_type": "audio",
                "duration": "3605.0",
            },
            {
                "codec_type": "video",
                "duration": "3599.5",
                "width": 1280,
                "height": 720,
                "codec_name": "h264",
                "time_base": "1/1000",
                "avg_frame_rate": "30/1",
                "r_frame_rate": "30/1",
            },
        ],
    }
    assert media_module._video_probe_from_ffprobe_payload(payload).duration == 3599.5
    payload["streams"][1]["duration"] = None
    assert media_module._video_probe_from_ffprobe_payload(payload).duration == 3605.0
    payload["streams"][1]["duration"] = "3601.0"
    assert media_module._video_probe_from_ffprobe_payload(payload).duration == 3601.0


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("duration_exceeded", "60-minute"),
        ("invalid_duration", "duration"),
        ("no_video_stream", "video track"),
        ("invalid_media", "decoded"),
        ("unsupported_container", "MP4, MOV, M4V, or WebM"),
        ("proxy_failed", "timestamps"),
    ],
)
def test_media_api_errors_are_stable_and_hide_tool_stderr(
    code: str, expected: str
) -> None:
    converted = matches_routes._safe_media_error(
        MediaError(code, "/private/tool stderr secret", 422)
    )
    assert converted.code == code
    assert expected in converted.message
    assert "private" not in converted.message
    assert "stderr" not in converted.message


def test_ingest_rejects_zero_duration_without_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(
        "squashvision.media.probe_video",
        lambda _path, **_kwargs: video_probe(duration=0.0),
    )

    with pytest.raises(MediaError) as raised:
        ingest_upload(
            BytesIO(b"zero duration"),
            "zero.mp4",
            storage,
            min_free_disk_bytes=0,
        )

    assert raised.value.code == "invalid_duration"
    assert generated_files(storage.root) == []




def test_duration_limit_accepts_three_hours_and_rejects_longer_without_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(
        "squashvision.media.probe_video",
        lambda _path, **_kwargs: video_probe(duration=10_800.0),
    )
    accepted = ingest_upload(
        BytesIO(b"boundary"),
        "boundary.mp4",
        storage,
        min_free_disk_bytes=0,
    )
    assert accepted.stored_path.absolute.exists()

    monkeypatch.setattr(
        "squashvision.media.probe_video",
        lambda _path, **_kwargs: video_probe(duration=10_801.0),
    )
    with pytest.raises(MediaError) as raised:
        ingest_upload(
            BytesIO(b"too long"),
            "long.mp4",
            storage,
            min_free_disk_bytes=0,
        )
    assert raised.value.code == "duration_exceeded"
    assert generated_files(storage.root) == [accepted.stored_path.absolute]


def test_real_invalid_bytes_and_audio_only_are_rejected(
    tmp_path: Path, media_tools: None
) -> None:
    storage = LocalStorage(tmp_path / "storage")
    with pytest.raises(MediaError) as invalid:
        ingest_upload(
            BytesIO(b"not a media file"),
            "invalid.mp4",
            storage,
            min_free_disk_bytes=0,
        )
    assert invalid.value.code == "invalid_media"

    audio_path = tmp_path / "audio.m4a"
    subprocess.run(
        [
            str(media_module.resolve_ffmpeg_binary()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.25",
            "-c:a",
            "aac",
            "-y",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    with pytest.raises(MediaError) as no_video:
        ingest_upload(
            audio_path.open("rb"),
            "audio.mp4",
            storage,
            min_free_disk_bytes=0,
        )
    assert no_video.value.code == "no_video_stream"
    assert generated_files(storage.root) == []


def test_cfr_proxy_is_playable_and_timestamp_mapping_is_persistable(
    tmp_path: Path, squash_fixtures: tuple[Path, Path], media_tools: None
) -> None:
    source, _vfr = squash_fixtures
    destination = tmp_path / "proxy.mp4"

    mapping = create_proxy(source, destination, timeout_seconds=60)
    proxy_probe = probe_video(destination)

    assert destination.is_file()
    assert proxy_probe.has_video
    assert proxy_probe.codec == "h264"
    assert proxy_probe.has_audio
    assert proxy_probe.duration == pytest.approx(5.0, abs=0.1)
    assert mapping.version == 1
    assert mapping.samples[0].source_seconds == pytest.approx(0.0, abs=0.05)
    assert mapping.samples[-1].proxy_seconds <= proxy_probe.duration
    restored = TimestampMap.model_validate_json(mapping.model_dump_json())
    assert restored == mapping


@pytest.mark.parametrize("width,height", [(1920, 1080), (1080, 1920), (320, 180)])
def test_proxy_bounds_both_dimensions_without_upscaling(
    tmp_path: Path, media_tools: None, width: int, height: int
) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "proxy.mp4"
    subprocess.run(
        [
            str(media_module.resolve_ffmpeg_binary()),
            "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            f"color=c=black:s={width}x{height}:r=10:d=0.3",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
        ],
        check=True, capture_output=True, text=True, timeout=30,
    )
    create_proxy(source, destination, timeout_seconds=60)
    proxy = probe_video(destination)
    assert 0 < proxy.width <= min(1280, width)
    assert 0 < proxy.height <= min(720, height)
    assert proxy.width % 2 == proxy.height % 2 == 0
    assert proxy.width / proxy.height == pytest.approx(width / height, abs=0.005)
    if width <= 1280 and height <= 720:
        assert (proxy.width, proxy.height) == (width, height)


def test_long_proxy_default_timeout_is_bounded_and_explicit_config_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MOSAIC_SQUASH_FFMPEG_TIMEOUT_SECONDS", raising=False)
    settings = Settings(data_dir=tmp_path)
    assert settings.proxy_timeout_for_duration(25) == 900
    assert settings.proxy_timeout_for_duration(3600) == 1800
    assert settings.proxy_timeout_for_duration(10800) == 3600
    assert settings.proxy_timeout_for_duration(100000) == 3600
    assert Settings(data_dir=tmp_path, ffmpeg_timeout_seconds=42).proxy_timeout_for_duration(10800) == 42
    monkeypatch.setenv("MOSAIC_SQUASH_FFMPEG_TIMEOUT_SECONDS", "77")
    assert Settings(data_dir=tmp_path).proxy_timeout_for_duration(10800) == 77


def test_proxy_keeps_only_primary_audio_stream(
    tmp_path: Path, media_tools: None
) -> None:
    source = tmp_path / "two-audio.mov"
    destination = tmp_path / "two-audio-proxy.mp4"
    subprocess.run(
        [
            str(media_module.resolve_ffmpeg_binary()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=30:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000:duration=0.5",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "2:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    with av.open(str(source), mode="r") as container:
        assert len(container.streams.audio) == 2

    mapping = create_proxy(source, destination, timeout_seconds=60)

    with av.open(str(destination), mode="r") as container:
        video_stream = container.streams.video[0]
        audio_streams = tuple(container.streams.audio)
        assert video_stream.codec_context.name == "h264"
        assert video_stream.codec_context.format.name == "yuv420p"
        assert video_stream.average_rate == 30
        assert len(audio_streams) == 1
        assert audio_streams[0].codec_context.name == "aac"
        assert sum(1 for _frame in container.decode(video_stream)) > 0
    with av.open(str(destination), mode="r") as container:
        decoded_audio_frames = sum(
            1 for _frame in container.decode(container.streams.audio[0])
        )
        assert decoded_audio_frames > 0

    source_times = [sample.source_seconds for sample in mapping.samples]
    proxy_times = [sample.proxy_seconds for sample in mapping.samples]
    assert source_times == sorted(source_times)
    assert proxy_times == sorted(proxy_times)


def test_proxy_accepts_video_without_audio(
    tmp_path: Path, media_tools: None
) -> None:
    source = tmp_path / "video-only.mov"
    destination = tmp_path / "video-only-proxy.mp4"
    subprocess.run(
        [
            str(media_module.resolve_ffmpeg_binary()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=30:d=0.5",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    mapping = create_proxy(source, destination, timeout_seconds=60)

    with av.open(str(destination), mode="r") as container:
        video_stream = container.streams.video[0]
        assert len(container.streams.audio) == 0
        assert sum(1 for _frame in container.decode(video_stream)) > 0
    source_times = [sample.source_seconds for sample in mapping.samples]
    proxy_times = [sample.proxy_seconds for sample in mapping.samples]
    assert source_times == sorted(source_times)
    assert proxy_times == sorted(proxy_times)


def test_vfr_timestamp_mapping_remains_ordered(
    tmp_path: Path, squash_fixtures: tuple[Path, Path], media_tools: None
) -> None:
    _cfr, source = squash_fixtures
    assert probe_video(source).variable_frame_rate

    mapping = create_proxy(source, tmp_path / "vfr-proxy.mp4", timeout_seconds=60)
    source_times = [sample.source_seconds for sample in mapping.samples]
    proxy_times = [sample.proxy_seconds for sample in mapping.samples]

    assert len(mapping.samples) > 10
    assert source_times == sorted(source_times)
    assert proxy_times == sorted(proxy_times)
    assert len(set(round(value, 4) for value in source_times)) > 10


def test_timestamp_map_rejects_unordered_samples() -> None:
    with pytest.raises(ValueError, match="ordered"):
        TimestampMap(
            samples=[
                TimestampPair(source_seconds=1.0, proxy_seconds=1.0),
                TimestampPair(source_seconds=0.5, proxy_seconds=1.1),
            ]
        )


@pytest.mark.asyncio
async def test_route_returns_typed_error_and_leaves_no_rows_or_files(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path, min_free_disk_bytes=0)
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/matches",
            files={"video": ("unsafe.avi", b"bytes", "video/x-msvideo")},
            data={"title": "Rejected"},
        )

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_container"
    assert response.json()["message"] == "supported containers are MP4, MOV, M4V, or WebM"
    database: Database = app.state.database
    with database.session() as session:
        assert session.scalars(select(Match)).all() == []
        assert session.scalars(select(MediaAsset)).all() == []
    assert generated_files(Path(settings.storage_root)) == []


@pytest.mark.asyncio
async def test_valid_fixture_route_creates_canonical_rows_and_artifacts(
    tmp_path: Path, squash_fixtures: tuple[Path, Path], media_tools: None
) -> None:
    source, _vfr = squash_fixtures
    settings = Settings(data_dir=tmp_path, min_free_disk_bytes=0)
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/matches",
            files={"video": ("../../court.MP4", source.read_bytes(), "video/mp4")},
            data={
                "title": "League Night",
                "playerOne": "Asha",
                "playerTwo": "Ben",
                "playedOn": "2026-08-25",
                "score": "11-8 9-11 11-6",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "League Night"
    assert body["preparationState"] == "prepared"
    assert body["metadata"] == {
        "playerOne": "Asha",
        "playerTwo": "Ben",
        "playedOn": "2026-08-25",
        "score": "11-8 9-11 11-6",
    }
    assert [asset["kind"] for asset in body["assets"]] == [
        "original",
        "proxy",
        "timestamp_map",
    ]

    database: Database = app.state.database
    with database.session() as session:
        matches = session.scalars(select(Match)).all()
        assets = session.scalars(select(MediaAsset).order_by(MediaAsset.id)).all()
    assert len(matches) == 1 and matches[0].name == "League Night"
    assert matches[0].player_a_name == "Asha"
    assert matches[0].player_b_name == "Ben"
    assert matches[0].played_on.isoformat() == "2026-08-25"
    assert matches[0].score == "11-8 9-11 11-6"
    assert len(assets) == 3
    assert all(asset.match_id == matches[0].id for asset in assets)

    storage: LocalStorage = app.state.storage
    paths = [storage.root / asset.relative_path for asset in assets]
    assert all(path.is_file() for path in paths)
    assert paths[0].read_bytes() == source.read_bytes()
    assert paths[0].stat().st_mode & 0o222 == 0
    timestamp_payload = json.loads(paths[2].read_text())
    mapping = TimestampMap.model_validate(timestamp_payload)
    assert mapping.version == 1 and len(mapping.samples) > 10


@pytest.mark.asyncio
async def test_route_failure_after_ingest_cleans_files_and_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path, min_free_disk_bytes=0)
    app = create_app(settings)
    staged = LocalStorage(Path(settings.storage_root)).allocate(AssetKind.ORIGINAL, ".mp4")
    staged.absolute.write_bytes(b"original")
    staged.absolute.chmod(0o444)

    monkeypatch.setattr(
        "squashvision.routes.matches.ingest_upload",
        lambda *_args, **_kwargs: IngestedMedia(
            stored_path=staged,
            sha256=hashlib.sha256(b"original").hexdigest(),
            bytes=8,
            suffix=".mp4",
            probe=video_probe(),
        ),
    )

    def fail_proxy(_source: Path, _destination: Path, **_kwargs: object) -> TimestampMap:
        raise MediaError("proxy_failed", "proxy generation failed", 422)

    monkeypatch.setattr("squashvision.routes.matches.create_proxy", fail_proxy)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/matches",
            files={"video": ("video.mp4", b"ignored", "video/mp4")},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "proxy_failed"
    with app.state.database.session() as session:
        assert session.scalars(select(Match)).all() == []
        assert session.scalars(select(MediaAsset)).all() == []
    assert generated_files(Path(settings.storage_root)) == []


@pytest.mark.asyncio
async def test_proxy_stream_holds_verified_descriptor_across_path_swap(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    stored = app.state.storage.allocate(AssetKind.PROXY, ".mp4")
    stored.absolute.write_bytes(b"verified-proxy")
    with app.state.database.session() as session:
        match = Match(name="Descriptor proxy")
        session.add(
            MediaAsset(
                match=match,
                kind=AssetKind.PROXY,
                relative_path=str(stored.relative),
                byte_size=len(b"verified-proxy"),
                checksum_sha256=hashlib.sha256(b"verified-proxy").hexdigest(),
            )
        )
        session.flush()
        match_id = match.public_id

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/v1/matches/{match_id}/media/proxy",
            "headers": [],
            "app": app,
            "state": {"request_id": "proxy-swap"},
        }
    )
    response = matches_routes.stream_match_proxy(match_id, request)
    replacement = tmp_path / "replacement.mp4"
    replacement.write_bytes(b"attacker-proxy")
    os.replace(replacement, stored.absolute)

    body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b"verified-proxy"


@pytest.mark.asyncio
async def test_timestamp_index_rejects_symlinked_managed_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path, min_free_disk_bytes=0)
    app = create_app(settings)
    original = app.state.storage.allocate(AssetKind.ORIGINAL, ".mp4")
    original.absolute.write_bytes(b"original")
    original.absolute.chmod(0o444)
    outside = tmp_path / "outside-index"
    outside.mkdir()
    (app.state.storage.root / "timestamp-index").symlink_to(
        outside, target_is_directory=True
    )

    monkeypatch.setattr(
        matches_routes,
        "ingest_upload",
        lambda *_args, **_kwargs: IngestedMedia(
            stored_path=original,
            sha256=hashlib.sha256(b"original").hexdigest(),
            bytes=len(b"original"),
            suffix=".mp4",
            probe=video_probe(),
        ),
    )

    def fake_proxy(
        _source: Path, destination: Path, **_kwargs: object
    ) -> TimestampMap:
        destination.write_bytes(b"proxy")
        return TimestampMap(
            samples=[
                TimestampPair(source_seconds=0.0, proxy_seconds=0.0),
                TimestampPair(source_seconds=1.0, proxy_seconds=1.0),
            ]
        )

    monkeypatch.setattr(matches_routes, "create_proxy", fake_proxy)
    monkeypatch.setattr(
        matches_routes,
        "probe_video",
        lambda *_args, **_kwargs: video_probe(),
    )

    from squashvision.pipeline import ExactTimestampIndex

    def fake_index(
        _cls: type[ExactTimestampIndex],
        _source: Path,
        _proxy: Path,
        destination: Path,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"index")
        return destination

    monkeypatch.setattr(
        ExactTimestampIndex, "build", classmethod(fake_index)
    )

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/matches",
            files={"video": ("video.mp4", b"ignored", "video/mp4")},
        )

    assert response.status_code == 500
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_timestamp_index_stage_swap_cannot_redirect_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path, min_free_disk_bytes=0)
    app = create_app(settings)
    storage: LocalStorage = app.state.storage
    original = storage.allocate(AssetKind.ORIGINAL, ".mp4")
    original.absolute.write_bytes(b"original")
    original.absolute.chmod(0o444)
    outside = tmp_path / "outside-stage"
    outside.mkdir()
    relocated = storage.root / ".relocated-timestamp-stage"

    monkeypatch.setattr(
        matches_routes,
        "ingest_upload",
        lambda *_args, **_kwargs: IngestedMedia(
            stored_path=original,
            sha256=hashlib.sha256(b"original").hexdigest(),
            bytes=len(b"original"),
            suffix=".mp4",
            probe=video_probe(),
        ),
    )

    def fake_proxy(
        _source: Path, destination: Path, **_kwargs: object
    ) -> TimestampMap:
        destination.write_bytes(b"proxy")
        return TimestampMap(
            samples=[
                TimestampPair(source_seconds=0.0, proxy_seconds=0.0),
                TimestampPair(source_seconds=1.0, proxy_seconds=1.0),
            ]
        )

    monkeypatch.setattr(matches_routes, "create_proxy", fake_proxy)
    monkeypatch.setattr(
        matches_routes,
        "probe_video",
        lambda *_args, **_kwargs: video_probe(),
    )

    from squashvision.pipeline import ExactTimestampIndex

    swapped = False

    def fake_video_samples(_path: Path):
        nonlocal swapped
        if not swapped:
            stages = list(storage.root.glob(".timestamp-index-*"))
            assert len(stages) == 1
            os.replace(stages[0], relocated)
            stages[0].symlink_to(outside, target_is_directory=True)
            swapped = True
        yield 0, 0
        yield 1_000_000, 1

    monkeypatch.setattr(
        ExactTimestampIndex,
        "_video_samples",
        staticmethod(fake_video_samples),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/matches",
            files={"video": ("video.mp4", b"ignored", "video/mp4")},
        )

    assert swapped
    assert response.status_code in {201, 500}
    assert list(outside.iterdir()) == []
