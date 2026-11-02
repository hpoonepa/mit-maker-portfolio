from __future__ import annotations

import fcntl
import bisect
import hashlib
import math
import os
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from threading import Lock
from typing import BinaryIO
from uuid import uuid4

import av
from imageio_ffmpeg._definitions import FNAME_PER_PLATFORM, get_platform
from imageio_ffmpeg._utils import _get_bin_dir

from squashvision.models import AssetKind
from squashvision.schemas import IngestedMedia, TimestampMap, TimestampPair, VideoProbe
from squashvision.settings import (
    DEFAULT_FFMPEG_TIMEOUT_SECONDS,
    DEFAULT_FFPROBE_TIMEOUT_SECONDS,
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_MAX_VIDEO_DURATION_SECONDS,
    DEFAULT_MIN_FREE_DISK_BYTES,
)
from squashvision.storage import LocalStorage

CHUNK_BYTES = 1024 * 1024
FFMPEG_VERIFY_TIMEOUT_SECONDS = 5.0
MAX_TIMESTAMP_POINTS = 4096
_MP4_FORMAT_NAMES = frozenset({"mov", "mp4", "m4v"})
_WEBM_VIDEO_CODECS = frozenset({"vp8", "vp9", "av1"})
SUPPORTED_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm"})
_FFMPEG_RESOLUTION_LOCK = Lock()
_FFMPEG_RESOLVED: Path | None = None
_FFMPEG_RESOLUTION_ERROR: tuple[str, str, int] | None = None


class MediaError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _bundled_ffmpeg_candidate() -> Path:
    filename = FNAME_PER_PLATFORM.get(get_platform())
    if not filename:
        raise MediaError(
            "media_tool_unavailable",
            "imageio-ffmpeg has no binary for this platform",
            503,
        )
    return Path(_get_bin_dir(), filename)


def _verify_ffmpeg_binary() -> Path:
    candidate = _bundled_ffmpeg_candidate().expanduser().resolve(strict=False)
    if not candidate.is_file():
        raise MediaError(
            "media_tool_unavailable",
            "the bundled FFmpeg binary is unavailable",
            503,
        )
    try:
        subprocess.run(
            [str(candidate), "-version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=FFMPEG_VERIFY_TIMEOUT_SECONDS,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        raise MediaError(
            "media_tool_unavailable",
            "the bundled FFmpeg binary failed verification",
            503,
        ) from error
    return candidate


def resolve_ffmpeg_binary() -> Path:
    global _FFMPEG_RESOLVED, _FFMPEG_RESOLUTION_ERROR
    with _FFMPEG_RESOLUTION_LOCK:
        if _FFMPEG_RESOLVED is not None:
            return _FFMPEG_RESOLVED
        if _FFMPEG_RESOLUTION_ERROR is not None:
            raise MediaError(*_FFMPEG_RESOLUTION_ERROR)
        try:
            _FFMPEG_RESOLVED = _verify_ffmpeg_binary()
        except MediaError as error:
            _FFMPEG_RESOLUTION_ERROR = (
                error.code,
                error.message,
                error.status_code,
            )
            raise
        return _FFMPEG_RESOLVED


def _clear_ffmpeg_binary_cache() -> None:
    global _FFMPEG_RESOLVED, _FFMPEG_RESOLUTION_ERROR
    with _FFMPEG_RESOLUTION_LOCK:
        _FFMPEG_RESOLVED = None
        _FFMPEG_RESOLUTION_ERROR = None


setattr(resolve_ffmpeg_binary, "cache_clear", _clear_ffmpeg_binary_cache)


def _run_media_command(
    arguments: list[str], *, timeout_seconds: float
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise MediaError(
            "media_tool_unavailable",
            f"required media tool is unavailable: {arguments[0]}",
            503,
        ) from error
    except subprocess.TimeoutExpired as error:
        raise MediaError(
            "media_tool_timeout", f"{arguments[0]} exceeded its time limit", 504
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip().splitlines()
        message = detail[-1] if detail else "media could not be decoded"
        raise MediaError("invalid_media", message, 422) from error


def _rate(value: object) -> Fraction | None:
    if not isinstance(value, str) or not value or value in {"0/0", "N/A"}:
        return None
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate > 0 else None


def _rotation(stream: dict[str, object]) -> int:
    tags = stream.get("tags")
    if isinstance(tags, dict):
        value = tags.get("rotate")
        if value is not None:
            try:
                return int(round(float(str(value)))) % 360
            except ValueError:
                pass
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, dict) and item.get("rotation") is not None:
                try:
                    return int(round(float(str(item["rotation"])))) % 360
                except ValueError:
                    pass
    return 0


def _duration(
    format_data: dict[str, object], video_stream: dict[str, object] | None
) -> float:
    candidates = (
        [video_stream.get("duration"), format_data.get("duration")]
        if video_stream is not None
        else [format_data.get("duration")]
    )
    for value in candidates:
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            return parsed
    return 0.0


def _video_probe_from_ffprobe_payload(payload: dict[str, object]) -> VideoProbe:
    streams = payload.get("streams", [])
    format_data = payload.get("format", {})
    if not isinstance(streams, list) or not isinstance(format_data, dict):
        raise MediaError("invalid_media", "ffprobe metadata is invalid", 422)

    format_names = tuple(
        part.strip()
        for part in str(format_data.get("format_name") or "").split(",")
        if part.strip()
    )
    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        None,
    )
    has_audio = any(
        isinstance(stream, dict) and stream.get("codec_type") == "audio"
        for stream in streams
    )
    if video_stream is None:
        return VideoProbe(
            format_names=format_names,
            duration=_duration(format_data, None),
            width=0,
            height=0,
            codec=None,
            time_base=None,
            average_frame_rate=None,
            real_frame_rate=None,
            rotation=0,
            has_video=False,
            has_audio=has_audio,
            variable_frame_rate=False,
        )

    average_frame_rate = video_stream.get("avg_frame_rate")
    real_frame_rate = video_stream.get("r_frame_rate")
    average = _rate(average_frame_rate)
    real = _rate(real_frame_rate)
    return VideoProbe(
        format_names=format_names,
        duration=_duration(format_data, video_stream),
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        codec=str(video_stream["codec_name"])
        if video_stream.get("codec_name") is not None
        else None,
        time_base=str(video_stream["time_base"])
        if video_stream.get("time_base") is not None
        else None,
        average_frame_rate=str(average_frame_rate)
        if average_frame_rate is not None
        else None,
        real_frame_rate=str(real_frame_rate) if real_frame_rate is not None else None,
        rotation=_rotation(video_stream),
        has_video=True,
        has_audio=has_audio,
        variable_frame_rate=average is not None and real is not None and average != real,
    )


def _probe_video_pyav(path: Path, timeout_seconds: float) -> VideoProbe:
    try:
        with av.open(
            str(path),
            mode="r",
            options={"rw_timeout": str(int(timeout_seconds * 1_000_000))},
        ) as container:
            format_names = tuple(
                part.strip()
                for part in str(container.format.name or "").split(",")
                if part.strip()
            )
            video_stream = next(
                (stream for stream in container.streams if stream.type == "video"),
                None,
            )
            has_audio = any(
                stream.type == "audio" for stream in container.streams
            )
            container_duration = (
                float(container.duration / av.time_base)
                if container.duration is not None
                else 0.0
            )
            if video_stream is None:
                return VideoProbe(
                    format_names=format_names,
                    duration=container_duration,
                    width=0,
                    height=0,
                    codec=None,
                    time_base=None,
                    average_frame_rate=None,
                    real_frame_rate=None,
                    rotation=0,
                    has_video=False,
                    has_audio=has_audio,
                    variable_frame_rate=False,
                )
            duration = (
                float(video_stream.duration * video_stream.time_base)
                if video_stream.duration is not None
                and video_stream.time_base is not None
                else container_duration
            )
            average = video_stream.average_rate
            real = video_stream.base_rate
            rotation_value = video_stream.metadata.get("rotate", "0")
            try:
                rotation = int(round(float(rotation_value))) % 360
            except ValueError:
                rotation = 0
            return VideoProbe(
                format_names=format_names,
                duration=duration,
                width=video_stream.codec_context.width,
                height=video_stream.codec_context.height,
                codec=video_stream.codec_context.name,
                time_base=str(video_stream.time_base)
                if video_stream.time_base is not None
                else None,
                average_frame_rate=str(average) if average is not None else None,
                real_frame_rate=str(real) if real is not None else None,
                rotation=rotation,
                has_video=True,
                has_audio=has_audio,
                variable_frame_rate=(
                    average is not None and real is not None and average != real
                ),
            )
    except MediaError:
        raise
    except Exception as error:
        raise MediaError("invalid_media", "media could not be decoded", 422) from error


def probe_video(
    path: Path, *, timeout_seconds: float = DEFAULT_FFPROBE_TIMEOUT_SECONDS
) -> VideoProbe:
    return _probe_video_pyav(Path(path), timeout_seconds)


def _require_free_disk(storage: LocalStorage, reserve_bytes: int) -> None:
    if shutil.disk_usage(storage.root).free < reserve_bytes:
        raise MediaError(
            "insufficient_disk",
            "insufficient free disk space for upload",
            507,
        )


@contextmanager
def _ingest_reservation(storage: LocalStorage) -> Iterator[None]:
    root_fd = storage._open_root_fd()
    try:
        fcntl.flock(root_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(root_fd, fcntl.LOCK_UN)
        os.close(root_fd)


def _is_supported_container(probe: VideoProbe) -> bool:
    formats = set(probe.format_names)
    if formats & _MP4_FORMAT_NAMES:
        return True
    return (
        "webm" in formats
        and probe.codec is not None
        and probe.codec.lower() in _WEBM_VIDEO_CODECS
    )


def ingest_upload(
    stream: BinaryIO,
    filename: str,
    storage: LocalStorage,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    max_duration_seconds: float = DEFAULT_MAX_VIDEO_DURATION_SECONDS,
    min_free_disk_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES,
    probe_timeout_seconds: float = DEFAULT_FFPROBE_TIMEOUT_SECONDS,
) -> IngestedMedia:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise MediaError(
            "unsupported_container",
            "supported containers are MP4, MOV, M4V, and WebM",
            415,
        )

    with _ingest_reservation(storage):
        _require_free_disk(storage, min_free_disk_bytes)
        staging = storage.root / f".upload-{uuid4().hex}.tmp"
        digest = hashlib.sha256()
        total = 0
        try:
            with staging.open("xb") as output:
                while True:
                    chunk = stream.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise MediaError(
                            "upload_too_large",
                            f"upload exceeds the {max_bytes}-byte limit",
                            413,
                        )
                    if min_free_disk_bytes:
                        _require_free_disk(storage, min_free_disk_bytes + len(chunk))
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()

            probe = probe_video(staging, timeout_seconds=probe_timeout_seconds)
            if not _is_supported_container(probe):
                raise MediaError(
                    "unsupported_container",
                    "detected container is not MP4, MOV, M4V, or WebM",
                    415,
                )
            if not probe.has_video:
                raise MediaError("no_video_stream", "media has no video stream", 422)
            if probe.duration <= 0:
                raise MediaError(
                    "invalid_duration", "video duration must be greater than zero", 422
                )
            if probe.duration > max_duration_seconds:
                raise MediaError(
                    "duration_exceeded",
                    f"video duration exceeds {max_duration_seconds:g} seconds",
                    422,
                )

            stored = storage.allocate(AssetKind.ORIGINAL, suffix)
            storage.publish(stored, staging)
            return IngestedMedia(
                stored_path=stored,
                sha256=digest.hexdigest(),
                bytes=total,
                suffix=suffix,
                probe=probe,
            )
        finally:
            staging.unlink(missing_ok=True)


def _bounded_timestamps(
    values: Iterable[float], *, maximum: int = MAX_TIMESTAMP_POINTS
) -> list[float]:
    if maximum < 2:
        raise ValueError("timestamp bound must preserve first and last points")
    points: list[float] = []
    for raw_value in values:
        value = float(raw_value)
        if value < 0 or (points and value < points[-1]):
            continue
        if maximum == 2 and len(points) == 2:
            points[-1] = value
            continue
        if len(points) >= maximum:
            previous_last = points[-1]
            points = points[::2]
            if points[-1] != previous_last:
                points.append(previous_last)
        points.append(value)
    return points


def _frame_timestamps(path: Path, timeout_seconds: float) -> list[float]:
    try:
        with av.open(
            str(path),
            mode="r",
            options={"rw_timeout": str(int(timeout_seconds * 1_000_000))},
        ) as container:
            video_stream = next(
                (stream for stream in container.streams if stream.type == "video"),
                None,
            )
            if video_stream is None:
                return []
            return _bounded_timestamps(
                float(frame.pts * frame.time_base)
                for frame in container.decode(video_stream)
                if frame.pts is not None and frame.time_base is not None
            )
    except Exception as error:
        raise MediaError("invalid_media", "video timestamps could not be decoded", 422) from error


def _build_timestamp_map(
    source_timestamps: list[float], proxy_timestamps: list[float]
) -> TimestampMap:
    if not source_timestamps or not proxy_timestamps:
        raise MediaError("proxy_failed", "could not derive video timestamps", 422)
    source_origin = source_timestamps[0]
    proxy_origin = proxy_timestamps[0]
    normalized_source = [
        max(0.0, timestamp - source_origin) for timestamp in source_timestamps
    ]
    normalized_proxy = [
        max(0.0, timestamp - proxy_origin) for timestamp in proxy_timestamps
    ]
    return TimestampMap(
        samples=[
            TimestampPair(
                source_seconds=source_timestamp,
                proxy_seconds=_nearest_timestamp(
                    source_timestamp, normalized_proxy
                ),
            )
            for source_timestamp in normalized_source
        ]
    )


def _nearest_timestamp(value: float, timestamps: list[float]) -> float:
    index = bisect.bisect_left(timestamps, value)
    if index == 0:
        return timestamps[0]
    if index == len(timestamps):
        return timestamps[-1]
    before = timestamps[index - 1]
    after = timestamps[index]
    return before if value - before <= after - value else after


def create_proxy(
    source: Path,
    destination: Path,
    *,
    timeout_seconds: float = DEFAULT_FFMPEG_TIMEOUT_SECONDS,
) -> TimestampMap:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_media_command(
            [
                str(resolve_ffmpeg_binary()),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-g",
                "60",
                "-keyint_min",
                "60",
                "-sc_threshold",
                "0",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-y",
                str(destination),
            ],
            timeout_seconds=timeout_seconds,
        )
        return _build_timestamp_map(
            _frame_timestamps(source, timeout_seconds),
            _frame_timestamps(destination, timeout_seconds),
        )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


__all__ = [
    "CHUNK_BYTES",
    "MAX_TIMESTAMP_POINTS",
    "IngestedMedia",
    "resolve_ffmpeg_binary",
    "MediaError",
    "TimestampMap",
    "TimestampPair",
    "VideoProbe",
    "create_proxy",
    "ingest_upload",
    "probe_video",
]
