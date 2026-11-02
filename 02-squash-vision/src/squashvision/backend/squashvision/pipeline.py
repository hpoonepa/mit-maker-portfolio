from __future__ import annotations

import stat
from bisect import bisect_left, bisect_right
import hashlib
import json
import fcntl
import math
import time
import os
import pickle
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar
from uuid import uuid4

from squashvision.jobs import PlannedChunk, TimeRange
from squashvision.models import AnalysisJob, BallInputMode, Match, ProcessingProfile, Stage
from squashvision.storage import LocalStorage
from squashvision.taxonomy import canonical_shot_kind, canonical_shot_outcome

if TYPE_CHECKING:
    from squashvision.calibration import CalibrationResult

def _calibration_result_from_record(
    raw: Mapping[str, object],
) -> CalibrationResult:
    from squashvision.calibration import (
        CalibrationCapabilities,
        CalibrationResult,
    )
    from squashvision.schemas import CalibrationResultDetail

    parsed = CalibrationResultDetail.model_validate(raw)
    return CalibrationResult(
        calibrated=parsed.calibrated,
        image_to_court=parsed.image_to_court,
        court_to_image=parsed.court_to_image,
        residuals_px=parsed.residuals_px,
        rms_error_px=parsed.rms_error_px,
        max_error_px=parsed.max_error_px,
        inlier_mask=parsed.inlier_mask,
        condition_number=parsed.condition_number,
        parameter_covariance=parsed.parameter_covariance,
        confidence=parsed.confidence,
        capabilities=CalibrationCapabilities(
            image_space=parsed.capabilities.image_space,
            floor_position=parsed.capabilities.floor_position,
            movement_distance=parsed.capabilities.movement_distance,
            speed=parsed.capabilities.speed,
        ),
        warnings=parsed.warnings,
    )


class _EvidenceObservation(Protocol):
    timestamp_us: int
    ambiguous: bool
    evidence: object
    source_frame_index: int | None



_IndexedRow = TypeVar("_IndexedRow")


class _TimestampIndex(Generic[_IndexedRow]):
    __slots__ = ("_items", "_timestamps")

    def __init__(
        self,
        items: Sequence[_IndexedRow],
        timestamp: Callable[[_IndexedRow], int] | None = None,
    ) -> None:
        timestamp_for = (
            timestamp
            if timestamp is not None
            else lambda item: int(getattr(item, "timestamp_us"))
        )
        timestamps = tuple(timestamp_for(item) for item in items)
        if any(
            current < previous
            for previous, current in zip(
                timestamps, timestamps[1:], strict=False
            )
        ):
            raise ValueError("timestamp index input must be ordered")
        self._items = items
        self._timestamps = timestamps

    def between(self, start_us: int, end_us: int) -> tuple[_IndexedRow, ...]:
        if end_us < start_us:
            return ()
        start = bisect_left(self._timestamps, start_us)
        end = bisect_right(self._timestamps, end_us)
        return tuple(self._items[index] for index in range(start, end))

    def nearest(self, timestamp_us: int) -> _IndexedRow | None:
        if not self._timestamps:
            return None
        position = bisect_left(self._timestamps, timestamp_us)
        if position == len(self._timestamps):
            position -= 1
        elif position and (
            timestamp_us - self._timestamps[position - 1]
            <= self._timestamps[position] - timestamp_us
        ):
            position -= 1
        return self._items[position]


class _EvidenceIndex:
    __slots__ = ("_indexes",)

    def __init__(
        self,
        *groups: Sequence[_EvidenceObservation],
    ) -> None:
        self._indexes = tuple(_TimestampIndex(group) for group in groups)

    def supporting(
        self, timestamps: Sequence[int]
    ) -> tuple[_EvidenceObservation, ...]:
        selected: dict[int, _EvidenceObservation] = {}
        for timestamp_us in timestamps:
            for index in self._indexes:
                for point in index.between(
                    int(timestamp_us) - 120_000,
                    int(timestamp_us) + 120_000,
                ):
                    selected[id(point)] = point
        return tuple(selected.values())


def _support_provenance(
    timestamps: Sequence[int],
    observations: Sequence[_EvidenceObservation] | _EvidenceIndex,
    *,
    competing: bool = False,
) -> str:
    if competing:
        return "ambiguous"
    support = tuple(int(value) for value in timestamps)
    if not support:
        return "unavailable"
    selected = (
        observations.supporting(support)
        if isinstance(observations, _EvidenceIndex)
        else tuple(
            point
            for point in observations
            if any(
                abs(point.timestamp_us - timestamp) <= 120_000
                for timestamp in support
            )
        )
    )
    if not selected:
        return "unavailable"
    if any(point.ambiguous for point in selected):
        return "ambiguous"
    evidence = {
        str(getattr(point.evidence, "value", point.evidence))
        for point in selected
    }
    if evidence == {"observed"}:
        return "observed"
    if evidence == {"interpolated"}:
        return "reconstructed"
    return "ambiguous"
def _nearest_source_frame(
    timestamp_us: int, observations: Sequence[_EvidenceObservation]
) -> int:
    candidate = min(
        (
            point
            for point in observations
            if point.source_frame_index is not None
        ),
        key=lambda point: abs(point.timestamp_us - timestamp_us),
        default=None,
    )
    return 0 if candidate is None else int(candidate.source_frame_index)

def _rally_racket_contexts(
    rackets: Sequence[object],
    rallies: Sequence[Mapping[str, object]],
) -> dict[str, tuple[int, bool]]:
    contexts: dict[str, tuple[int, bool]] = {}
    for rally in rallies:
        start = rally.get("start")
        end = rally.get("end")
        if not isinstance(start, Mapping) or not isinstance(end, Mapping):
            continue
        start_us = start.get("selected_us")
        end_us = end.get("selected_us")
        if not isinstance(start_us, int) or not isinstance(end_us, int):
            continue
        contained = (
            contact
            for contact in rackets
            if start_us <= int(getattr(contact, "timestamp_us")) <= end_us
        )
        for position, contact in enumerate(contained):
            contexts[str(getattr(contact, "contact_id"))] = (
                position,
                position == 0,
            )
    return contexts




@dataclass(frozen=True, slots=True)
class ExactTimestampIndex:
    proxy_timestamps_us: tuple[int, ...]
    source_timestamps_us: tuple[int, ...]
    source_frame_indices: tuple[int, ...]
    source_raw_origin_us: int = 0
    proxy_raw_origin_us: int = 0

    def __post_init__(self) -> None:
        count = len(self.proxy_timestamps_us)
        if (
            count == 0
            or len(self.source_timestamps_us) != count
            or len(self.source_frame_indices) != count
        ):
            raise ValueError("timestamp index columns must be nonempty and equal")
        if any(
            current <= previous
            for previous, current in zip(
                self.proxy_timestamps_us, self.proxy_timestamps_us[1:]
            )
        ):
            raise ValueError("proxy timestamps must be strictly ordered")
        if any(
            current < previous
            for previous, current in zip(
                self.source_timestamps_us, self.source_timestamps_us[1:]
            )
        ) or any(
            current < previous
            for previous, current in zip(
                self.source_frame_indices, self.source_frame_indices[1:]
            )
        ):
            raise ValueError("source timestamp provenance must be ordered")

    @classmethod
    def from_samples(
        cls,
        *,
        source: Sequence[tuple[int, int]],
        proxy: Sequence[int],
    ) -> ExactTimestampIndex:
        import bisect

        if not source or not proxy:
            raise ValueError("timestamp samples must be nonempty")
        mapped: list[tuple[int, int]] = []
        source_times = [int(item[0]) for item in source]
        source_origin = source_times[0]
        proxy_origin = int(proxy[0])
        source_span = max(1, source_times[-1] - source_origin)
        proxy_span = max(1, int(proxy[-1]) - proxy_origin)
        for proxy_us in proxy:
            target = source_origin + int(
                round(
                    (int(proxy_us) - proxy_origin)
                    * source_span
                    / proxy_span
                )
            )
            index = bisect.bisect_left(source_times, target)
            if index == len(source_times):
                index -= 1
            elif index and (
                target - source_times[index - 1]
                <= source_times[index] - target
            ):
                index -= 1
            mapped.append(source[index])
        return cls(
            tuple(int(value) - proxy_origin for value in proxy),
            tuple(int(value[0]) - source_origin for value in mapped),
            tuple(int(value[1]) for value in mapped),
            source_raw_origin_us=source_origin,
            proxy_raw_origin_us=proxy_origin,
        )

    def source_for_proxy(self, timestamp_us: int) -> tuple[int, int]:
        import bisect

        index = bisect.bisect_left(self.proxy_timestamps_us, timestamp_us)
        if index == len(self.proxy_timestamps_us):
            index -= 1
        elif index and (
            timestamp_us - self.proxy_timestamps_us[index - 1]
            <= self.proxy_timestamps_us[index] - timestamp_us
        ):
            index -= 1
        return self.source_timestamps_us[index], self.source_frame_indices[index]

    def write(self, path: Path) -> Path:
        import pyarrow as pa
        import pyarrow.parquet as pq

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "proxy_timestamp_us": self.proxy_timestamps_us,
                "source_timestamp_us": self.source_timestamps_us,
                "source_frame_index": self.source_frame_indices,
            }
        )
        table = table.replace_schema_metadata(
            {
                b"source_raw_origin_us": str(
                    self.source_raw_origin_us
                ).encode(),
                b"proxy_raw_origin_us": str(
                    self.proxy_raw_origin_us
                ).encode(),
            }
        )
        temporary = destination.with_name(
            f".{destination.name}.{uuid4().hex}.tmp"
        )
        try:
            pq.write_table(table, temporary, compression="zstd")
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    @classmethod
    def read(cls, path: Path) -> ExactTimestampIndex:
        import pyarrow.parquet as pq

        table = pq.read_table(Path(path))
        if table.column_names != [
            "proxy_timestamp_us",
            "source_timestamp_us",
            "source_frame_index",
        ]:
            raise ValueError("timestamp index schema is incompatible")
        values = table.to_pydict()
        metadata = table.schema.metadata or {}
        return cls(
            tuple(values["proxy_timestamp_us"]),
            tuple(values["source_timestamp_us"]),
            tuple(values["source_frame_index"]),
            source_raw_origin_us=int(
                metadata.get(b"source_raw_origin_us", b"0")
            ),
            proxy_raw_origin_us=int(
                metadata.get(b"proxy_raw_origin_us", b"0")
            ),
        )
    @staticmethod
    def _video_samples(path: Path):
        import av

        with av.open(str(path), mode="r") as container:
            stream = container.streams.video[0]
            ordinal = 0
            for frame in container.decode(stream):
                if frame.pts is None:
                    continue
                yield (
                    int(round(float(frame.pts * stream.time_base) * 1_000_000)),
                    ordinal,
                )
                ordinal += 1

    @classmethod
    def _build_to_sink(
        cls,
        source: Path,
        proxy: Path,
        sink: object,
    ) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        def summary(path: Path) -> tuple[int, int, int]:
            count = 0
            first = 0
            last = 0
            for timestamp_us, _index in cls._video_samples(path):
                if count == 0:
                    first = timestamp_us
                last = timestamp_us
                count += 1
            return count, first, last

        source_count, source_origin, source_last = summary(source)
        proxy_count, proxy_origin, proxy_last = summary(proxy)
        if source_count == 0 or proxy_count == 0:
            raise ValueError(
                "timestamp index requires decodable source and proxy"
            )
        source_span = max(1, source_last - source_origin)
        proxy_span = max(1, proxy_last - proxy_origin)
        schema = pa.schema(
            [
                ("proxy_timestamp_us", pa.int64()),
                ("source_timestamp_us", pa.int64()),
                ("source_frame_index", pa.int64()),
            ],
            metadata={
                b"source_raw_origin_us": str(source_origin).encode(),
                b"proxy_raw_origin_us": str(proxy_origin).encode(),
            },
        )
        source_iterator = iter(cls._video_samples(source))
        current_source = next(source_iterator)
        next_source = next(source_iterator, None)
        rows: list[tuple[int, int, int]] = []
        writer = pq.ParquetWriter(sink, schema, compression="zstd")
        try:
            for proxy_us, _proxy_index in cls._video_samples(proxy):
                target = source_origin + int(
                    round(
                        (proxy_us - proxy_origin)
                        * source_span
                        / proxy_span
                    )
                )
                while (
                    next_source is not None
                    and abs(next_source[0] - target)
                    < abs(current_source[0] - target)
                ):
                    current_source = next_source
                    next_source = next(source_iterator, None)
                rows.append(
                    (
                        proxy_us - proxy_origin,
                        current_source[0] - source_origin,
                        current_source[1],
                    )
                )
                if len(rows) == 4096:
                    writer.write_table(
                        pa.table(
                            {
                                "proxy_timestamp_us": [
                                    row[0] for row in rows
                                ],
                                "source_timestamp_us": [
                                    row[1] for row in rows
                                ],
                                "source_frame_index": [
                                    row[2] for row in rows
                                ],
                            },
                            schema=schema,
                        )
                    )
                    rows.clear()
            if rows:
                writer.write_table(
                    pa.table(
                        {
                            "proxy_timestamp_us": [
                                row[0] for row in rows
                            ],
                            "source_timestamp_us": [
                                row[1] for row in rows
                            ],
                            "source_frame_index": [
                                row[2] for row in rows
                            ],
                        },
                        schema=schema,
                    )
                )
        finally:
            writer.close()

    @classmethod
    def build(
        cls, source: Path, proxy: Path, destination: Path
    ) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as stream:
                cls._build_to_sink(source, proxy, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    @classmethod
    def build_to_descriptor(
        cls,
        source: Path,
        proxy: Path,
        descriptor: int,
    ) -> int:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("timestamp index destination must be a regular file")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            cls._build_to_sink(source, proxy, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor

    @classmethod
    def raw_origins(cls, path: Path) -> tuple[int, int]:
        import pyarrow.parquet as pq

        metadata = (
            pq.read_schema(Path(path)).metadata or {}
        )
        return (
            int(metadata.get(b"source_raw_origin_us", b"0")),
            int(metadata.get(b"proxy_raw_origin_us", b"0")),
        )

    @classmethod
    def range_mapping(
        cls, path: Path, start_us: int, end_us: int
    ) -> dict[int, tuple[int, int]]:
        import pyarrow.dataset as ds

        dataset = ds.dataset(Path(path), format="parquet")
        table = dataset.to_table(
            filter=(
                (ds.field("proxy_timestamp_us") >= start_us)
                & (ds.field("proxy_timestamp_us") < end_us)
            )
        )
        values = table.to_pydict()
        return {
            int(proxy): (int(source), int(frame))
            for proxy, source, frame in zip(
                values["proxy_timestamp_us"],
                values["source_timestamp_us"],
                values["source_frame_index"],
                strict=True,
            )
        }


def normalize_audio_frame(
    samples: object, *, channels: int, planar: bool
):
    import numpy as np

    values = np.asarray(samples)
    if channels <= 0 or values.ndim not in {1, 2}:
        raise ValueError("audio frame layout is invalid")
    if values.ndim == 1:
        return np.ascontiguousarray(values, dtype=np.float64)
    channel_axis = 0 if planar else 1
    if values.shape[channel_axis] != channels:
        raise ValueError("audio channel count does not match frame layout")
    return np.ascontiguousarray(
        values.mean(axis=channel_axis), dtype=np.float64
    )


class PlayerBoundaryState:
    def __init__(self) -> None:
        self._mapping: dict[str, str] | None = None
        self._initialized = False

    def initialize(self, players: Sequence[str]) -> None:
        if tuple(players) != ("A", "B"):
            raise ValueError("player boundary state requires A and B")
        self._mapping = {"A": "A", "B": "B"}
        self._initialized = True

    def reconcile(
        self,
        *,
        previous: Sequence[Mapping[str, object]],
        current: Sequence[Mapping[str, object]],
    ) -> PlayerBoundaryResult:
        if not self._initialized:
            self.initialize(("A", "B"))
        result = reconcile_player_boundary(previous, current)
        self._mapping = None if result.ambiguous else dict(result.mapping)
        return result

    def map_player(self, player_id: str) -> str | None:
        if self._mapping is None:
            return None
        return self._mapping[player_id]


ARTIFACT_SCHEMA_VERSIONS: Mapping[Stage, int] = MappingProxyType(
    {stage: 1 for stage in Stage}
)
PIPELINE_CODE_VERSION = "pipeline-3"
_STAGE_ORDER = (
    Stage.PREPARE,
    Stage.CALIBRATION,
    Stage.PLAYERS,
    Stage.BALL,
    Stage.EVENTS,
    Stage.CLASSIFICATION,
    Stage.REPORT,
)
_DEPENDENCIES: Mapping[Stage, tuple[Stage, ...]] = MappingProxyType(
    {
        Stage.PREPARE: (),
        Stage.CALIBRATION: (),
        Stage.PLAYERS: (),
        Stage.BALL: (Stage.CALIBRATION,),
        Stage.EVENTS: (Stage.PLAYERS, Stage.BALL, Stage.CALIBRATION),
        Stage.CLASSIFICATION: (Stage.EVENTS, Stage.PLAYERS, Stage.BALL),
        Stage.REPORT: (Stage.CLASSIFICATION, Stage.EVENTS),
    }
)


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    player_stride: int
    player_chunk_us: int
    ball_chunk_us: int
    overlap_us: int
    inference_batch_size: int
    full_candidates: bool
    audio_fusion: bool
    resolution: str


PROFILE_CONFIGS: Mapping[ProcessingProfile, ProfileConfig] = MappingProxyType(
    {
        ProcessingProfile.FAST: ProfileConfig(
            player_stride=2,
            player_chunk_us=120_000_000,
            ball_chunk_us=60_000_000,
            overlap_us=1_000_000,
            inference_batch_size=4,
            full_candidates=False,
            audio_fusion=False,
            resolution="proxy",
        ),
        ProcessingProfile.BALANCED: ProfileConfig(
            player_stride=1,
            player_chunk_us=90_000_000,
            ball_chunk_us=45_000_000,
            overlap_us=2_000_000,
            inference_batch_size=8,
            full_candidates=True,
            audio_fusion=True,
            resolution="proxy",
        ),
        ProcessingProfile.MAXIMUM: ProfileConfig(
            player_stride=1,
            player_chunk_us=60_000_000,
            ball_chunk_us=30_000_000,
            overlap_us=3_000_000,
            inference_batch_size=16,
            full_candidates=True,
            audio_fusion=True,
            resolution="highest_supported",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class PipelineContext:
    match_public_id: str
    duration_us: int
    source_checksum: str
    proxy_checksum: str
    timestamp_map_hash: str
    models: Mapping[str, Mapping[str, object]]
    calibration_revision: int | None
    calibration_capabilities: Mapping[str, bool]
    calibration_record_hash: str | None = None
    player_roi: Mapping[str, object] | None = None
    source_frame_size: tuple[int, int] | None = None
    source_rotation: int = 0
    ball_input_mode: BallInputMode = BallInputMode.ORIGINAL
    source_path: Path | None = None
    proxy_path: Path | None = None
    timestamp_map_path: Path | None = None
    calibration: object | None = field(default=None, compare=False, repr=False)
    model_assets: Mapping[str, object] = field(
        default_factory=dict, compare=False, repr=False
    )
    exact_timestamp_index_path: Path | None = field(
        default=None, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        if not self.match_public_id.strip():
            raise ValueError("pipeline context requires a match public ID")
        if self.duration_us <= 0:
            raise ValueError("pipeline context duration must be positive")
        for name, value in (
            ("source", self.source_checksum),
            ("proxy", self.proxy_checksum),
            ("timestamp map", self.timestamp_map_hash),
        ):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"{name} checksum must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class PipelinePlan:
    profile: ProcessingProfile
    profile_config: ProfileConfig
    duration_us: int
    stage_order: tuple[Stage, ...]
    chunks: tuple[PlannedChunk, ...]
    plan_hash: str

    def __iter__(self):
        return iter(self.chunks)


@dataclass(frozen=True, slots=True)
class StagePayload:
    data: bytes
    suffix: str
    availability: str
    evidence: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    row_count: int = 0

    def __post_init__(self) -> None:
        if self.availability not in {"available", "partial", "unavailable"}:
            raise ValueError("artifact availability is invalid")
        if not self.suffix.startswith(".") or "/" in self.suffix or "\\" in self.suffix:
            raise ValueError("artifact suffix is invalid")
        if self.row_count < 0:
            raise ValueError("artifact row count must be nonnegative")


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope:
    schema_version: int
    stage: str
    match_id: str
    job_id: str
    profile: str
    start_us: int
    end_us: int
    source_checksum: str
    proxy_checksum: str
    timestamp_map_hash: str
    model_manifests: Mapping[str, Mapping[str, object]]
    calibration_revision: int | None
    calibration_capabilities: Mapping[str, bool]
    upstream_artifact_hashes: tuple[str, ...]
    stage_config_hash: str
    input_hash: str
    availability: str
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    row_count: int
    payload_name: str
    payload_sha256: str
    payload_size: int
    artifact_sha256: str
    artifact_size: int
    player_roi: Mapping[str, object] | None = None
    ball_preprocessing: Mapping[str, object] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ArtifactEnvelope:
        models = value.get("model_manifests")
        capabilities = value.get("calibration_capabilities")
        if not isinstance(models, dict) or not isinstance(capabilities, dict):
            raise ValueError("artifact envelope mappings are invalid")
        return cls(
            schema_version=int(value["schema_version"]),
            stage=str(value["stage"]),
            match_id=str(value["match_id"]),
            job_id=str(value["job_id"]),
            profile=str(value["profile"]),
            start_us=int(value["start_us"]),
            end_us=int(value["end_us"]),
            source_checksum=str(value["source_checksum"]),
            proxy_checksum=str(value["proxy_checksum"]),
            timestamp_map_hash=str(value["timestamp_map_hash"]),
            model_manifests=models,
            calibration_revision=(
                None
                if value.get("calibration_revision") is None
                else int(value["calibration_revision"])
            ),
            calibration_capabilities={str(k): bool(v) for k, v in capabilities.items()},
            upstream_artifact_hashes=tuple(
                str(item) for item in value["upstream_artifact_hashes"]  # type: ignore[index]
            ),
            stage_config_hash=str(value["stage_config_hash"]),
            input_hash=str(value["input_hash"]),
            availability=str(value["availability"]),
            evidence=tuple(str(item) for item in value["evidence"]),  # type: ignore[index]
            warnings=tuple(str(item) for item in value["warnings"]),  # type: ignore[index]
            errors=tuple(str(item) for item in value["errors"]),  # type: ignore[index]
            row_count=int(value["row_count"]),
            payload_name=str(value["payload_name"]),
            payload_sha256=str(value["payload_sha256"]),
            payload_size=int(value["payload_size"]),
            artifact_sha256=str(value["artifact_sha256"]),
            artifact_size=int(value["artifact_size"]),
            player_roi=value.get("player_roi"),
            ball_preprocessing=value.get("ball_preprocessing"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    path: Path
    payload_path: Path
    envelope: ArtifactEnvelope
    byte_size: int
    sha256: str
    reused: bool = False


@dataclass(frozen=True, slots=True)
class StageExecution:
    job: AnalysisJob
    stage: Stage
    chunk: TimeRange
    profile_config: ProfileConfig
    context: PipelineContext
    upstream: tuple[ArtifactInfo, ...]
    input_hash: str
    config_hash: str

    def upstream_available(self, stage: Stage) -> bool:
        return any(
            item.envelope.stage == stage.value
            and item.envelope.availability != "unavailable"
            for item in self.upstream
        )


class StageAdapter(Protocol):
    def __call__(self, execution: StageExecution) -> StagePayload: ...


class PipelineStageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class EssentialStageError(PipelineStageError):
    pass


class DegradableStageError(PipelineStageError):
    pass


def _chunks(duration_us: int, size_us: int, overlap_us: int) -> tuple[TimeRange, ...]:
    if duration_us <= 0 or size_us <= 0 or overlap_us < 0 or overlap_us >= size_us:
        raise ValueError("invalid chunk geometry")
    result: list[TimeRange] = []
    start = 0
    while start < duration_us:
        end = min(start + size_us, duration_us)
        result.append(TimeRange(start, end))
        if end == duration_us:
            break
        start = end - overlap_us
    return tuple(result)


def _relevant_models(stage: Stage, models: Mapping[str, Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    if stage is Stage.PREPARE:
        names = ("pose", "ball")
    elif stage is Stage.CALIBRATION:
        names = ()
    elif stage is Stage.PLAYERS:
        names = ("pose",)
    elif stage is Stage.BALL:
        names = ("ball",)
    else:
        names = ("pose", "ball")
    return {name: models[name] for name in names if name in models}

def _hash_models(
    stage: Stage, models: Mapping[str, Mapping[str, object]]
) -> dict[str, Mapping[str, object]]:
    if stage is Stage.PREPARE:
        names: tuple[str, ...] = ("pose", "ball")
    elif stage is Stage.CALIBRATION:
        names = ()
    elif stage is Stage.PLAYERS:
        names = ("pose",)
    elif stage is Stage.BALL:
        names = ("ball",)
    else:
        names = ("pose", "ball")
    return {name: models[name] for name in names if name in models}


def stage_input_hash(
    stage: Stage,
    context: PipelineContext,
    profile: ProcessingProfile,
    upstream_hashes: Iterable[str],
    *,
    config_hash: str | None = None,
    artifact_schema_version: int | None = None,
) -> str:
    profile = ProcessingProfile(profile)
    dependencies: dict[str, object] = {
        "stage": stage.value,
        "source_checksum": context.source_checksum,
        "proxy_checksum": context.proxy_checksum,
        "timestamp_map_hash": context.timestamp_map_hash,
        "profile": profile.value,
        "profile_config": asdict(PROFILE_CONFIGS[profile]),
        "code_version": PIPELINE_CODE_VERSION,
        "artifact_schema_version": (
            ARTIFACT_SCHEMA_VERSIONS[stage]
            if artifact_schema_version is None
            else artifact_schema_version
        ),
        "models": _hash_models(stage, context.models),
        "upstream_artifact_hashes": sorted(upstream_hashes),
    }
    # Streaming preserves the existing model inputs and checkpoint contract for
    # <=720p sources. Only the changed high-resolution/rotation geometry needs
    # a new contract; do not discard compatible completed long-match chunks.
    if profile is ProcessingProfile.MAXIMUM and (
        context.source_rotation != 0
        or (context.source_frame_size is not None and (
            context.source_frame_size[0] > 1280
            or context.source_frame_size[1] > 720
        ))
    ):
        dependencies["decode_geometry"] = "bounded-proxy-v1"
    if stage in {
        Stage.CALIBRATION,
        Stage.BALL,
        Stage.EVENTS,
        Stage.CLASSIFICATION,
        Stage.REPORT,
    }:
        dependencies["calibration_revision"] = context.calibration_revision
        dependencies["calibration_capabilities"] = dict(
            context.calibration_capabilities
        )
        dependencies["calibration_record_hash"] = (
            context.calibration_record_hash
        )
    if config_hash is not None:
        dependencies["stage_config_hash"] = config_hash
    if context.player_roi is not None and stage in {
        Stage.PLAYERS, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT,
    }:
        dependencies["player_roi"] = dict(context.player_roi)
    if stage is Stage.PLAYERS:
        from squashvision.vision.players import PLAYER_IDENTITY_POLICY_VERSION
        dependencies["player_identity_policy"] = PLAYER_IDENTITY_POLICY_VERSION
        dependencies["player_boundary_policy"] = "preserve-row-ambiguity-v2"
    if stage in {Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT}:
        dependencies["player_overlap_policy"] = "observed-first-v2"
    if stage in {Stage.BALL, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT}:
        preprocessing = _ball_preprocessing(context)
        if preprocessing is not None:
            dependencies["ball_preprocessing"] = preprocessing
    return canonical_hash(dependencies)


def _ball_preprocessing(context: PipelineContext) -> dict[str, object] | None:
    if context.ball_input_mode != BallInputMode.INVERTED:
        return None
    from squashvision.vision.ball.contrast_support import CONTRAST_SUPPORT_POLICY_VERSION
    return {
        "mode": "inverted",
        "input_transform": "uint8_invert_all_frames_and_median_v1",
        "support_policy": CONTRAST_SUPPORT_POLICY_VERSION,
    }


def _stage_dependencies(stage: Stage, context: PipelineContext) -> tuple[Stage, ...]:
    dependencies = _DEPENDENCIES[stage]
    if stage is Stage.BALL and context.ball_input_mode == BallInputMode.INVERTED:
        return (*dependencies, Stage.PLAYERS)
    return dependencies


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        self.root.mkdir(parents=True, exist_ok=True)

    def _directory(
        self, match_id: str, stage: Stage, input_hash: str
    ) -> Path:
        if len(input_hash) != 64 or any(c not in "0123456789abcdef" for c in input_hash):
            raise ValueError("artifact input hash must be lowercase SHA-256")
        namespace = canonical_hash({"match_id": match_id})
        directory = (
            self.root / namespace / stage.value / input_hash
        ).resolve(strict=False)
        if self.root not in directory.parents:
            raise ValueError("artifact cache path escaped cache root")
        return directory
    @staticmethod
    def _signature(path: Path) -> tuple[int, str] | None:
        try:
            if not path.is_file():
                return None
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    size += len(block)
                    digest.update(block)
            return size, digest.hexdigest()
        except OSError:
            return None

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def load(
        self, match_id: str, stage: Stage, input_hash: str
    ) -> ArtifactInfo | None:
        directory = self._directory(match_id, stage, input_hash)
        envelope_path = directory / "envelope.json"
        try:
            raw = json.loads(envelope_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            envelope = ArtifactEnvelope.from_dict(raw)
            if (
                envelope.stage != stage.value
                or envelope.input_hash != input_hash
                or envelope.schema_version != ARTIFACT_SCHEMA_VERSIONS[stage]
                or envelope.availability not in {"available", "partial", "unavailable"}
                or envelope.start_us < 0
                or envelope.start_us >= envelope.end_us
                or Path(envelope.payload_name).name != envelope.payload_name
            ):
                return None
            payload_path = (directory / envelope.payload_name).resolve(strict=False)
            if directory not in payload_path.parents:
                return None
            payload_signature = self._signature(payload_path)
            if payload_signature != (envelope.payload_size, envelope.payload_sha256):
                return None
            if (envelope.artifact_size, envelope.artifact_sha256) != payload_signature:
                return None
            envelope_signature = self._signature(envelope_path)
            if envelope_signature is None:
                return None
            return ArtifactInfo(
                path=envelope_path,
                payload_path=payload_path,
                envelope=envelope,
                byte_size=envelope_signature[0],
                sha256=envelope_signature[1],
                reused=True,
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None


    @staticmethod
    def matches_publication(
        artifact: ArtifactInfo,
        *,
        stage: Stage,
        match_id: str,
        profile: ProcessingProfile,
        chunk: TimeRange,
        context: PipelineContext,
        upstream_hashes: Iterable[str],
        config_hash: str,
    ) -> bool:
        envelope = artifact.envelope
        return (
            envelope.stage == stage.value
            and envelope.match_id == match_id
            and envelope.profile == profile.value
            and (envelope.start_us, envelope.end_us)
            == (chunk.start_us, chunk.end_us)
            and envelope.source_checksum == context.source_checksum
            and envelope.proxy_checksum == context.proxy_checksum
            and envelope.timestamp_map_hash == context.timestamp_map_hash
            and envelope.player_roi == (context.player_roi if stage in {
                Stage.PLAYERS, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT,
            } else None)
            and envelope.ball_preprocessing == (_ball_preprocessing(context) if stage in {
                Stage.BALL, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT,
            } else None)
            and dict(envelope.model_manifests)
            == _relevant_models(stage, context.models)
            and envelope.calibration_revision
            == (
                context.calibration_revision
                if stage
                in {
                    Stage.CALIBRATION,
                    Stage.BALL,
                    Stage.EVENTS,
                    Stage.CLASSIFICATION,
                    Stage.REPORT,
                }
                else None
            )
            and envelope.upstream_artifact_hashes
            == tuple(sorted(upstream_hashes))
            and envelope.stage_config_hash == config_hash
        )

    def publish(
        self,
        *,
        stage: Stage,
        input_hash: str,
        match_id: str,
        job_id: str,
        profile: ProcessingProfile,
        chunk: TimeRange,
        context: PipelineContext,
        upstream_hashes: Iterable[str],
        config_hash: str,
        payload: StagePayload,
    ) -> ArtifactInfo:
        del job_id
        upstream_hashes = tuple(upstream_hashes)
        directory = self._directory(match_id, stage, input_hash)
        directory.parent.mkdir(parents=True, exist_ok=True)
        lock_path = directory.parent / f".{input_hash}.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            reusable = self.load(match_id, stage, input_hash)
            if reusable is not None:
                if self.matches_publication(
                    reusable,
                    stage=stage,
                    match_id=match_id,
                    profile=profile,
                    chunk=chunk,
                    context=context,
                    upstream_hashes=upstream_hashes,
                    config_hash=config_hash,
                ):
                    return reusable
                raise OSError("content-addressed artifact metadata collision")
            if directory.exists():
                quarantine = directory.with_name(
                    f".{directory.name}.corrupt-{uuid4().hex}"
                )
                os.replace(directory, quarantine)
            directory.mkdir(parents=True, exist_ok=False)
            return self._write_new(
                directory=directory,
                stage=stage,
                input_hash=input_hash,
                match_id=match_id,
                profile=profile,
                chunk=chunk,
                context=context,
                upstream_hashes=upstream_hashes,
                config_hash=config_hash,
                payload=payload,
            )

    def _write_new(
        self,
        *,
        directory: Path,
        stage: Stage,
        input_hash: str,
        match_id: str,
        profile: ProcessingProfile,
        chunk: TimeRange,
        context: PipelineContext,
        upstream_hashes: tuple[str, ...],
        config_hash: str,
        payload: StagePayload,
    ) -> ArtifactInfo:
        payload_name = f"payload{payload.suffix}"
        payload_path = directory / payload_name
        payload_hash = hashlib.sha256(payload.data).hexdigest()
        self._atomic_write(payload_path, payload.data)
        if self._signature(payload_path) != (len(payload.data), payload_hash):
            raise OSError("published artifact payload failed integrity validation")
        calibration_dependent = stage in {
            Stage.CALIBRATION,
            Stage.BALL,
            Stage.EVENTS,
            Stage.CLASSIFICATION,
            Stage.REPORT,
        }
        envelope = ArtifactEnvelope(
            schema_version=ARTIFACT_SCHEMA_VERSIONS[stage],
            stage=stage.value,
            match_id=match_id,
            job_id="content-addressed",
            profile=profile.value,
            start_us=chunk.start_us,
            end_us=chunk.end_us,
            source_checksum=context.source_checksum,
            proxy_checksum=context.proxy_checksum,
            timestamp_map_hash=context.timestamp_map_hash,
            model_manifests=_relevant_models(stage, context.models),
            calibration_revision=(
                context.calibration_revision if calibration_dependent else None
            ),
            calibration_capabilities=(
                dict(context.calibration_capabilities)
                if calibration_dependent
                else {"image_space": True}
            ),
            upstream_artifact_hashes=tuple(sorted(upstream_hashes)),
            stage_config_hash=config_hash,
            input_hash=input_hash,
            availability=payload.availability,
            evidence=payload.evidence,
            warnings=payload.warnings,
            errors=payload.errors,
            row_count=payload.row_count,
            payload_name=payload_name,
            payload_sha256=payload_hash,
            payload_size=len(payload.data),
            artifact_sha256=payload_hash,
            artifact_size=len(payload.data),
            player_roi=(context.player_roi if stage in {
                Stage.PLAYERS, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT,
            } else None),
            ball_preprocessing=(_ball_preprocessing(context) if stage in {
                Stage.BALL, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT,
            } else None),
        )
        envelope_data = json.dumps(
            asdict(envelope),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        envelope_path = directory / "envelope.json"
        self._atomic_write(envelope_path, envelope_data)
        loaded = self.load(match_id, stage, input_hash)
        if loaded is None:
            raise OSError("published artifact envelope failed validation")
        return ArtifactInfo(
            path=loaded.path,
            payload_path=loaded.payload_path,
            envelope=loaded.envelope,
            byte_size=loaded.byte_size,
            sha256=loaded.sha256,
            reused=False,
        )


@dataclass(frozen=True, slots=True)
class PlayerBoundaryResult:
    mapping: Mapping[str, str]
    confidence: float
    ambiguous: bool
    warning: str | None


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return 0.0 if left_norm == 0.0 or right_norm == 0.0 else dot / (left_norm * right_norm)


def reconcile_player_boundary(
    previous: Sequence[Mapping[str, object]],
    current: Sequence[Mapping[str, object]],
) -> PlayerBoundaryResult:
    previous_by_id: dict[str, list[Sequence[float]]] = {}
    current_by_id: dict[str, list[Sequence[float]]] = {}
    for row in previous:
        player_id = str(row.get("player_id", ""))
        appearance = row.get("appearance")
        if player_id and isinstance(appearance, Sequence):
            previous_by_id.setdefault(player_id, []).append(
                tuple(float(value) for value in appearance)
            )
    for row in current:
        player_id = str(row.get("player_id", ""))
        appearance = row.get("appearance")
        if player_id and isinstance(appearance, Sequence):
            current_by_id.setdefault(player_id, []).append(
                tuple(float(value) for value in appearance)
            )
    if set(previous_by_id) != {"A", "B"} or set(current_by_id) != {"A", "B"}:
        return PlayerBoundaryResult({}, 0.0, True, "insufficient_overlap_identity_evidence")

    def score(first: str, second: str) -> float:
        values = [
            _cosine(left, right)
            for left in previous_by_id[first]
            for right in current_by_id[second]
        ]
        return sum(values) / len(values) if values else 0.0

    identity = score("A", "A") + score("B", "B")
    swapped = score("A", "B") + score("B", "A")
    margin = abs(identity - swapped) / 2.0
    if margin < 0.1:
        return PlayerBoundaryResult({}, margin, True, "ambiguous_overlap_assignment")
    mapping = {"A": "A", "B": "B"} if identity > swapped else {"A": "B", "B": "A"}
    return PlayerBoundaryResult(mapping, min(1.0, margin), False, None)


@dataclass(frozen=True, slots=True)
class BallSeamResult:
    rows: tuple[Mapping[str, object], ...]
    segments: tuple[tuple[int, ...], ...]
    warnings: tuple[str, ...]


def reconcile_ball_seam(rows: Sequence[Mapping[str, object]]) -> BallSeamResult:
    selected: dict[tuple[int, int, str], Mapping[str, object]] = {}
    warnings: list[str] = []
    for row in rows:
        key = (
            int(row["timestamp_us"]),
            int(row["frame_index"]),
            str(row["model_manifest_id"]),
        )
        existing = selected.get(key)
        if existing is None or float(row.get("confidence", 0.0)) > float(
            existing.get("confidence", 0.0)
        ):
            selected[key] = row
    ordered = tuple(
        sorted(selected.values(), key=lambda item: (int(item["timestamp_us"]), int(item["frame_index"])))
    )
    segments: list[list[int]] = []
    for row in ordered:
        timestamp = int(row["timestamp_us"])
        if not segments or timestamp - segments[-1][-1] > 250_000:
            segments.append([timestamp])
        else:
            segments[-1].append(timestamp)
    return BallSeamResult(
        rows=ordered,
        segments=tuple(tuple(segment) for segment in segments),
        warnings=tuple(warnings),
    )


class AnalysisPipeline:
    def __init__(
        self,
        *,
        storage_root: Path,
        context_provider: Callable[[Match, ProcessingProfile], PipelineContext] | None = None,
        stage_adapters: Mapping[Stage, StageAdapter] | None = None,
        database: object | None = None,
        model_manifest: object | None = None,
    ) -> None:
        self.storage_root = Path(storage_root).expanduser().resolve(strict=False)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._storage = LocalStorage(self.storage_root)
        self.artifacts = ArtifactStore(self.storage_root / "analysis-cache")
        self.database = database
        self.model_manifest = model_manifest
        self._context_provider = context_provider or self._production_context
        self._custom_context_provider = context_provider is not None
        supplied = dict(stage_adapters or {})
        self._adapters: dict[Stage, StageAdapter] = {
            Stage.PREPARE: self._prepare,
            Stage.CALIBRATION: self._calibration,
            Stage.PLAYERS: self._players,
            Stage.BALL: self._ball,
            Stage.EVENTS: self._events,
            Stage.CLASSIFICATION: self._classification,
            Stage.REPORT: self._report,
            **supplied,
        }
        self._latest: dict[tuple[str, str, Stage], list[ArtifactInfo]] = {}
        self._automatic_calibrations: dict[str, tuple[int, object]] = {}
        self._context_cache: dict[
            str, tuple[str, tuple[tuple[int, int, int, int, int], ...], PipelineContext]
        ] = {}
        self._player_boundary_states: dict[
            tuple[str, str], PlayerBoundaryState
        ] = {}

    def _resolve_job(self, job: AnalysisJob) -> AnalysisJob:
        if self.database is None or not job.public_id:
            return job
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        def load() -> AnalysisJob | None:
            with self.database.session() as session:
                return session.scalar(
                    select(AnalysisJob)
                    .where(AnalysisJob.public_id == job.public_id)
                    .options(
                        selectinload(AnalysisJob.match).selectinload(
                            Match.media_assets
                        ),
                        selectinload(AnalysisJob.match).selectinload(
                            Match.calibrations
                        ),
                        selectinload(AnalysisJob.source_media_asset),
                    )
                )

        resolved = load()
        if resolved is None:
            return job
        if not self._custom_context_provider:
            self._ensure_media_metadata(resolved.match.public_id)
            refreshed = load()
            if refreshed is not None:
                resolved = refreshed
        resolved.worker_id = job.worker_id
        resolved.claim_token = job.claim_token
        return resolved

    def _ensure_media_metadata(self, match_id: str) -> None:
        if self.database is None:
            return
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from squashvision.media import probe_video
        from squashvision.models import AssetKind

        with self.database.session() as session:
            match = session.scalar(
                select(Match)
                .where(Match.public_id == match_id)
                .options(selectinload(Match.media_assets))
            )
            if match is None:
                raise EssentialStageError(
                    "match_missing", "analysis match no longer exists"
                )
            assets = {asset.kind: asset for asset in match.media_assets}
            try:
                original = assets[AssetKind.ORIGINAL]
                proxy = assets[AssetKind.PROXY]
                timestamp_map = assets[AssetKind.TIMESTAMP_MAP]
            except KeyError as error:
                raise EssentialStageError(
                    "media_asset_missing",
                    "original, proxy, and timestamp map are required",
                ) from error
            for asset in (original, proxy, timestamp_map):
                if asset.checksum_sha256 is None or asset.byte_size is None:
                    _path, size, digest, _data = self._verified_owned_file(
                        asset.relative_path,
                        expected_size=asset.byte_size,
                        expected_sha256=asset.checksum_sha256,
                        code="media_asset_corrupt",
                    )
                    asset.byte_size = size
                    asset.checksum_sha256 = digest
            for asset in (original, proxy):
                if asset.duration_us is None or asset.probe_metadata is None:
                    probe = probe_video(
                        self._safe_asset_path(asset.relative_path)
                    )
                    asset.duration_us = int(
                        round(probe.duration * 1_000_000)
                    )
                    asset.probe_metadata = probe.model_dump(mode="json")

            if proxy.timestamp_index_path is None:
                if (
                    proxy.timestamp_index_sha256 is not None
                    or proxy.timestamp_index_size is not None
                ):
                    raise EssentialStageError(
                        "timestamp_index_corrupt",
                        "timestamp index metadata is incomplete",
                    )
                try:
                    index_stored = self._storage.allocate_timestamp_index()
                    with self._storage.create_timestamp_index_stage() as (
                        _index_stage,
                        index_descriptor,
                    ):
                        ExactTimestampIndex.build_to_descriptor(
                            self._safe_asset_path(original.relative_path),
                            self._safe_asset_path(proxy.relative_path),
                            index_descriptor,
                        )
                        index_digest_builder = hashlib.sha256()
                        index_size = 0
                        descriptor_position = os.lseek(
                            index_descriptor, 0, os.SEEK_CUR
                        )
                        try:
                            os.lseek(index_descriptor, 0, os.SEEK_SET)
                            while block := os.read(
                                index_descriptor, 1024 * 1024
                            ):
                                index_size += len(block)
                                index_digest_builder.update(block)
                        finally:
                            os.lseek(
                                index_descriptor,
                                descriptor_position,
                                os.SEEK_SET,
                            )
                        index_digest = index_digest_builder.hexdigest()
                        self._storage.publish_descriptor(
                            index_stored, index_descriptor
                        )
                except (OSError, PermissionError, ValueError) as error:
                    raise EssentialStageError(
                        "timestamp_index_corrupt",
                        "timestamp index could not be safely generated",
                    ) from error
                proxy.timestamp_index_path = str(index_stored.relative)
                proxy.timestamp_index_size = index_size
                proxy.timestamp_index_sha256 = index_digest
            if proxy.timestamp_index_path is None:
                raise EssentialStageError(
                    "timestamp_index_corrupt",
                    "timestamp index path was not published",
                )
            _path, index_size, index_digest, _data = self._verified_owned_file(
                proxy.timestamp_index_path,
                expected_size=proxy.timestamp_index_size,
                expected_sha256=proxy.timestamp_index_sha256,
                code="timestamp_index_corrupt",
            )
            proxy.timestamp_index_size = index_size
            proxy.timestamp_index_sha256 = index_digest

    def _context_for_job(
        self, job: AnalysisJob, profile: ProcessingProfile
    ) -> PipelineContext:
        if self._custom_context_provider:
            return replace(self._context_provider(job.match, profile),
                ball_input_mode=BallInputMode(job.ball_input_mode or BallInputMode.ORIGINAL))
        assets = sorted(
            (
                asset.kind.value,
                asset.checksum_sha256,
                asset.byte_size,
                asset.duration_us,
                asset.timestamp_index_sha256,
                asset.timestamp_index_size,
            )
            for asset in job.match.media_assets
        )
        calibrations = sorted(
            (
                item.revision,
                canonical_hash(item.result),
                canonical_hash(item.capabilities),
            )
            for item in job.match.calibrations
        )
        model_rows: list[tuple[object, ...]] = []
        if self.database is not None:
            from sqlalchemy import select
            from squashvision.models import ModelAsset

            with self.database.session() as session:
                model_rows = [
                    (
                        row.model_name,
                        row.state.value,
                        row.sha256,
                        row.byte_size,
                        row.resolved_revision,
                        row.compatibility_version,
                    )
                    for row in session.scalars(
                        select(ModelAsset).order_by(ModelAsset.model_name)
                    )
                ]
        fingerprint = canonical_hash(
            {
                "assets": assets,
                "calibrations": calibrations,
                "player_roi": job.match.player_roi,
                "models": model_rows,
                "profile": profile.value,
                "ball_input_mode": job.ball_input_mode or BallInputMode.ORIGINAL,
            }
        )
        media_state = self._media_descriptor_state(job.match)
        cached = self._context_cache.get(job.public_id)
        if (
            cached is not None
            and cached[0] == fingerprint
            and cached[1] == media_state
        ):
            return cached[2]
        context = replace(self._production_context(job.match, profile),
            ball_input_mode=BallInputMode(job.ball_input_mode or BallInputMode.ORIGINAL))
        self._context_cache[job.public_id] = (
            fingerprint,
            self._media_descriptor_state(job.match),
            context,
        )
        return context
    @contextmanager
    def _publication_session(self, execution: StageExecution):
        if self.database is None:
            yield None, None, None
            return
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from squashvision.jobs import ClaimLostError
        from squashvision.models import (
            JobStatus,
            StagePublication,
        )

        connection = self.database.engine.connect()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            job = session.scalar(
                select(AnalysisJob).where(
                    AnalysisJob.public_id == execution.job.public_id
                )
            )
            if (
                job is None
                or job.status is not JobStatus.RUNNING
                or not execution.job.worker_id
                or not execution.job.claim_token
                or job.worker_id != execution.job.worker_id
                or job.claim_token != execution.job.claim_token
            ):
                raise ClaimLostError(
                    f"worker no longer owns job {execution.job.public_id}"
                )
            existing = session.scalar(
                select(StagePublication).where(
                    StagePublication.analysis_job_id == job.id,
                    StagePublication.stage == execution.stage,
                    StagePublication.input_hash == execution.input_hash,
                )
            )
            yield session, job, existing
            session.flush()
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            session.close()
            connection.close()


    def plan(
        self,
        match: Match | AnalysisJob,
        profile: ProcessingProfile | None = None,
    ) -> PipelinePlan:
        if isinstance(match, AnalysisJob):
            job_row = self._resolve_job(match)
            profile = job_row.processing_profile
            match_row = job_row.match
            profile = ProcessingProfile(profile)
            context = self._context_for_job(job_row, profile)
        else:
            match_row = match
            if profile is None:
                raise TypeError("profile is required when planning a match")
            profile = ProcessingProfile(profile)
            context = self._context_provider(match_row, profile)
        config = PROFILE_CONFIGS[profile]
        raw_chunks: list[tuple[Stage, TimeRange]] = []
        full = TimeRange(0, context.duration_us)
        for stage in _STAGE_ORDER:
            ranges = (
                _chunks(context.duration_us, config.player_chunk_us, config.overlap_us)
                if stage is Stage.PLAYERS
                else _chunks(context.duration_us, config.ball_chunk_us, config.overlap_us)
                if stage is Stage.BALL
                else (full,)
            )
            raw_chunks.extend((stage, item) for item in ranges)
        plan_hash = canonical_hash(
            {
                "match_id": context.match_public_id,
                "duration_us": context.duration_us,
                "source_checksum": context.source_checksum,
                "proxy_checksum": context.proxy_checksum,
                "timestamp_map_hash": context.timestamp_map_hash,
                "profile": profile.value,
                "profile_config": asdict(config),
                "schema_versions": {
                    stage.value: ARTIFACT_SCHEMA_VERSIONS[stage] for stage in _STAGE_ORDER
                },
                "chunks": [
                    [stage.value, item.start_us, item.end_us]
                    for stage, item in raw_chunks
                ],
            }
        )
        contracts: dict[Stage, list[str]] = {stage: [] for stage in Stage}
        chunks: list[PlannedChunk] = []
        for stage, item in raw_chunks:
            config_hash = self._config_hash(stage, profile, config, item)
            upstream_contracts = tuple(
                contract
                for dependency in _stage_dependencies(stage, context)
                for contract in contracts[dependency]
            )
            dependency_hash = stage_input_hash(
                stage,
                context,
                profile,
                upstream_contracts,
                config_hash=config_hash,
            )
            contracts[stage].append(dependency_hash)
            chunks.append(
                PlannedChunk(
                    stage,
                    item,
                    plan_hash=plan_hash,
                    dependency_hash=dependency_hash,
                    config_hash=config_hash,
                    artifact_schema_version=ARTIFACT_SCHEMA_VERSIONS[stage],
                )
            )
        return PipelinePlan(
            profile=profile,
            profile_config=config,
            duration_us=context.duration_us,
            stage_order=_STAGE_ORDER,
            chunks=tuple(chunks),
            plan_hash=plan_hash,
        )

    @staticmethod
    def _config_hash(
        stage: Stage,
        profile: ProcessingProfile,
        config: ProfileConfig,
        chunk: TimeRange,
    ) -> str:
        return canonical_hash(
            {
                "stage": stage.value,
                "profile": profile.value,
                "config": asdict(config),
                "range": [chunk.start_us, chunk.end_us],
            }
        )

    @staticmethod
    def _artifact_matches_context(
        artifact: ArtifactInfo, context: PipelineContext
    ) -> bool:
        envelope = artifact.envelope
        if (
            envelope.source_checksum != context.source_checksum
            or envelope.proxy_checksum != context.proxy_checksum
            or envelope.timestamp_map_hash != context.timestamp_map_hash
        ):
            return False
        if envelope.stage in {
            Stage.CALIBRATION.value,
            Stage.BALL.value,
            Stage.EVENTS.value,
            Stage.CLASSIFICATION.value,
            Stage.REPORT.value,
        } and envelope.calibration_revision != context.calibration_revision:
            return False
        if envelope.stage in {
            Stage.PLAYERS.value, Stage.EVENTS.value, Stage.CLASSIFICATION.value, Stage.REPORT.value,
        } and envelope.player_roi != context.player_roi:
            return False
        if envelope.stage in {
            Stage.BALL.value, Stage.EVENTS.value, Stage.CLASSIFICATION.value, Stage.REPORT.value,
        } and envelope.ball_preprocessing != _ball_preprocessing(context):
            return False
        for name, identity in envelope.model_manifests.items():
            current = context.models.get(name)
            if current is None or dict(current) != dict(identity):
                return False
        return True

    def _upstream(
        self, job: AnalysisJob, stage: Stage, context: PipelineContext
    ) -> tuple[ArtifactInfo, ...]:
        dependencies = _stage_dependencies(stage, context)
        result: list[ArtifactInfo] = []
        planned_rows = []
        if self.database is not None and job.id is not None:
            from sqlalchemy import select
            from squashvision.models import JobChunk, StageStatus

            with self.database.session() as session:
                planned_rows = session.scalars(
                    select(JobChunk)
                    .where(
                        JobChunk.analysis_job_id == job.id,
                        JobChunk.stage.in_(dependencies),
                        JobChunk.status == StageStatus.COMPLETED,
                    )
                    .order_by(JobChunk.chunk_index)
                ).all()
        if planned_rows:
            for row in planned_rows:
                if (
                    row.input_hash is None
                    or row.config_hash is None
                    or row.artifact_schema_version
                    != ARTIFACT_SCHEMA_VERSIONS[row.stage]
                ):
                    raise EssentialStageError(
                        "upstream_contract_invalid",
                        f"{row.stage.value} chunk lacks its exact contract",
                    )
                artifact = self.artifacts.load(
                    context.match_public_id, row.stage, row.input_hash
                )
                if (
                    artifact is None
                    or not self._artifact_matches_context(artifact, context)
                    or artifact.envelope.stage_config_hash != row.config_hash
                ):
                    raise EssentialStageError(
                        "upstream_artifact_invalid",
                        f"{row.stage.value} exact upstream artifact is unavailable",
                    )
                result.append(artifact)
            present = {item.envelope.stage for item in result}
            missing = {
                dependency.value for dependency in dependencies
            }.difference(present)
            if missing:
                raise EssentialStageError(
                    "upstream_artifact_missing",
                    f"missing exact dependencies: {sorted(missing)}",
                )
        else:
            for dependency in dependencies:
                key = (
                    job.match.public_id,
                    job.processing_profile.value,
                    dependency,
                )
                candidates = tuple(self._latest.get(key, ()))
                result.extend(
                    item
                    for item in candidates
                    if self._artifact_matches_context(item, context)
                )
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.envelope.stage,
                    item.envelope.start_us,
                    item.envelope.end_us,
                    item.envelope.input_hash,
                ),
            )
        )

    def chunk_contract(
        self, job: AnalysisJob, stage: Stage, chunk: TimeRange
    ) -> PlannedChunk:
        stage = Stage(stage)
        job = self._resolve_job(job)
        plan = self.plan(job)
        base = next(
            (
                item
                for item in plan.chunks
                if item.stage is stage and item.time_range == chunk
            ),
            None,
        )
        if base is None or base.config_hash is None:
            raise ValueError("chunk is not part of the current pipeline plan")
        context = self._context_for_job(job, job.processing_profile)
        upstream = self._upstream(job, stage, context)
        input_hash = stage_input_hash(
            stage,
            context,
            job.processing_profile,
            (item.sha256 for item in upstream),
            config_hash=base.config_hash,
        )
        return replace(base, input_hash=input_hash)

    def run_chunk(
        self, job: AnalysisJob, stage: Stage, chunk: TimeRange
    ) -> ArtifactInfo:
        stage = Stage(stage)
        job = self._resolve_job(job)
        context = self._context_for_job(job, job.processing_profile)
        if chunk.end_us > context.duration_us:
            raise ValueError("chunk exceeds media duration")
        config = PROFILE_CONFIGS[job.processing_profile]
        config_hash = self._config_hash(
            stage, job.processing_profile, config, chunk
        )
        upstream = self._upstream(job, stage, context)
        upstream_hashes = tuple(item.sha256 for item in upstream)
        input_hash = stage_input_hash(
            stage,
            context,
            job.processing_profile,
            upstream_hashes,
            config_hash=config_hash,
        )
        cached = self.artifacts.load(context.match_public_id, stage, input_hash)
        if cached is not None and self.artifacts.matches_publication(
            cached,
            stage=stage,
            match_id=context.match_public_id,
            profile=job.processing_profile,
            chunk=chunk,
            context=context,
            upstream_hashes=upstream_hashes,
            config_hash=config_hash,
        ):
            self._remember(job, stage, cached)
            return cached
        execution = StageExecution(
            job,
            stage,
            chunk,
            config,
            context,
            upstream,
            input_hash,
            config_hash,
        )
        try:
            payload = self._adapters[stage](execution)
        except DegradableStageError as error:
            if stage not in {Stage.CALIBRATION, Stage.BALL, Stage.EVENTS, Stage.CLASSIFICATION, Stage.REPORT}:
                raise
            payload = StagePayload(
                data=b"",
                suffix=".bin",
                availability="unavailable",
                evidence=("typed-degraded-stage",),
                warnings=(),
                errors=(f"{error.code}: {error.message}",),
                row_count=0,
            )
        artifact = self.artifacts.publish(
            stage=stage,
            input_hash=input_hash,
            match_id=context.match_public_id,
            job_id=job.public_id,
            profile=job.processing_profile,
            chunk=chunk,
            context=context,
            upstream_hashes=upstream_hashes,
            config_hash=config_hash,
            payload=payload,
        )
        self._remember(job, stage, artifact)
        return artifact

    def _remember(self, job: AnalysisJob, stage: Stage, artifact: ArtifactInfo) -> None:
        key = (job.match.public_id, job.processing_profile.value, stage)
        current = [
            item
            for item in self._latest.get(key, ())
            if (item.envelope.start_us, item.envelope.end_us)
            != (artifact.envelope.start_us, artifact.envelope.end_us)
        ]
        current.append(artifact)
        self._latest[key] = current

    def run(
        self,
        job: AnalysisJob,
        stage: Stage,
        chunk: TimeRange,
        artifact: Path,
    ) -> Path:
        del artifact
        started = time.perf_counter()
        completed = self.run_chunk(job, stage, chunk)
        if os.environ.get("SQUASHVISION_PROFILE_METRICS") == "1":
            print(
                "SQUASHVISION_STAGE_METRIC "
                + json.dumps(
                    {
                        "stage": stage.value,
                        "startUs": chunk.start_us,
                        "endUs": chunk.end_us,
                        "wallSeconds": time.perf_counter() - started,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                flush=True,
            )
        if self.artifacts.load(
            completed.envelope.match_id,
            stage,
            completed.envelope.input_hash,
        ) is None:
            raise OSError("artifact failed pre-checkpoint integrity validation")
        return completed.path

    def _production_context(
        self, match: Match, profile: ProcessingProfile
    ) -> PipelineContext:
        from squashvision.calibration import CalibrationCapabilities, CalibrationResult
        from squashvision.models import AssetKind
        from squashvision.schemas import TimestampMap

        assets = {asset.kind: asset for asset in match.media_assets}
        try:
            source_asset = assets[AssetKind.ORIGINAL]
            proxy_asset = assets[AssetKind.PROXY]
            timestamp_asset = assets[AssetKind.TIMESTAMP_MAP]
        except KeyError as error:
            raise EssentialStageError(
                "media_asset_missing", "original, proxy, and timestamp map are required"
            ) from error
        if (
            source_asset.checksum_sha256 is None
            or source_asset.byte_size is None
            or proxy_asset.checksum_sha256 is None
            or proxy_asset.byte_size is None
            or timestamp_asset.checksum_sha256 is None
            or timestamp_asset.byte_size is None
            or source_asset.duration_us is None
            or source_asset.duration_us <= 0
            or proxy_asset.duration_us is None
            or proxy_asset.duration_us <= 0
            or proxy_asset.timestamp_index_path is None
            or proxy_asset.timestamp_index_sha256 is None
            or proxy_asset.timestamp_index_size is None
        ):
            raise EssentialStageError(
                "media_metadata_missing",
                "immutable media provenance was not prepared",
            )
        source, _size, source_hash, _data = self._verified_owned_file(
            source_asset.relative_path,
            expected_size=source_asset.byte_size,
            expected_sha256=source_asset.checksum_sha256,
            code="media_asset_corrupt",
        )
        proxy, _size, proxy_hash, _data = self._verified_owned_file(
            proxy_asset.relative_path,
            expected_size=proxy_asset.byte_size,
            expected_sha256=proxy_asset.checksum_sha256,
            code="media_asset_corrupt",
        )
        timestamp, _size, timestamp_hash, timestamp_data = (
            self._verified_owned_file(
                timestamp_asset.relative_path,
                expected_size=timestamp_asset.byte_size,
                expected_sha256=timestamp_asset.checksum_sha256,
                code="timestamp_map_corrupt",
                capture=True,
            )
        )
        exact_index, _size, _index_hash, _data = self._verified_owned_file(
            proxy_asset.timestamp_index_path,
            expected_size=proxy_asset.timestamp_index_size,
            expected_sha256=proxy_asset.timestamp_index_sha256,
            code="timestamp_index_corrupt",
        )
        duration_us = source_asset.duration_us
        models: dict[str, Mapping[str, object]] = {}
        model_assets: dict[str, object] = {}
        if self.model_manifest is not None:
            for asset in self.model_manifest.states():
                models[asset.name] = {
                    "manifest_id": asset.name,
                    "digest": asset.sha256,
                    "revision": asset.resolved_revision,
                    "requested_revision": asset.requested_revision,
                    "state": asset.state.value,
                    "compatibility_version": asset.compatibility_version,
                    "required": asset.required,
                    "error_code": asset.error_code,
                }
                model_assets[asset.name] = asset
        try:
            TimestampMap.model_validate_json(timestamp_data)
        except (UnicodeDecodeError, ValueError) as error:
            raise EssentialStageError(
                "timestamp_map_corrupt",
                "timestamp map is missing, corrupt, or incompatible",
            ) from error
        calibration_revision: int | None = None
        calibration_object: object | None = None
        calibration_record_hash: str | None = None
        capabilities: Mapping[str, bool] = asdict(
            CalibrationCapabilities(
                image_space=True,
                floor_position=False,
                movement_distance=False,
                speed=False,
            )
        )
        if match.calibrations:
            latest = max(match.calibrations, key=lambda item: item.revision)
            calibration_revision = latest.revision
            calibration_record_hash = canonical_hash(
                {
                    "revision": latest.revision,
                    "result": latest.result,
                    "capabilities": latest.capabilities,
                    "confidence": latest.confidence,
                }
            )
            calibration_object = _calibration_result_from_record(
                latest.result
            )
            capabilities = asdict(calibration_object.capabilities)
        automatic = self._automatic_calibrations.get(match.public_id)
        if automatic is not None and (
            calibration_revision is None or automatic[0] > calibration_revision
        ):
            calibration_revision, calibration_object = automatic
            capabilities = asdict(calibration_object.capabilities)
        player_roi = None
        if match.player_roi is not None:
            from squashvision.schemas import PlayerRoiDetail

            region = PlayerRoiDetail.model_validate(match.player_roi)
            if region.source_sha256 != source_hash:
                raise EssentialStageError("player_roi_source_mismatch", "playing area belongs to different source media")
            if region.points is not None:
                player_roi = region.model_dump(mode="json", by_alias=True)
        return PipelineContext(
            match_public_id=match.public_id,
            duration_us=duration_us,
            source_checksum=source_hash,
            proxy_checksum=proxy_hash,
            timestamp_map_hash=timestamp_hash,
            models=models,
            calibration_revision=calibration_revision,
            calibration_capabilities=capabilities,
            calibration_record_hash=calibration_record_hash,
            player_roi=player_roi,
            source_frame_size=(
                (int(source_asset.probe_metadata["width"]), int(source_asset.probe_metadata["height"]))
                if source_asset.probe_metadata else None
            ),
            source_rotation=int((source_asset.probe_metadata or {}).get("rotation", 0)),
            source_path=source,
            proxy_path=proxy,
            timestamp_map_path=timestamp,
            calibration=calibration_object,
            model_assets=model_assets,
            exact_timestamp_index_path=exact_index,
        )

    def _verified_owned_file(
        self,
        relative: str,
        *,
        expected_size: int | None,
        expected_sha256: str | None,
        code: str,
        capture: bool = False,
    ) -> tuple[Path, int, str, bytes]:
        relative_path = Path(relative)
        try:
            stored = self._storage.resolve(
                relative_path,
                owned_paths={relative_path},
            )
            descriptor = self._storage.open_owned(
                relative_path,
                owned_paths={relative_path},
            )
        except (OSError, PermissionError, ValueError) as error:
            raise EssentialStageError(
                code, "managed media asset is missing or unsafe"
            ) from error
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise EssentialStageError(
                    code, "managed media asset is not a regular file"
                )
            if capture and before.st_size > 16 * 1024 * 1024:
                raise EssentialStageError(
                    code, "managed timestamp metadata exceeds its safe bound"
                )
            digest = hashlib.sha256()
            size = 0
            captured = bytearray()
            while block := os.read(descriptor, 1024 * 1024):
                size += len(block)
                digest.update(block)
                if capture:
                    captured.extend(block)
            after = os.fstat(descriptor)
            if (
                (before.st_dev, before.st_ino)
                != (after.st_dev, after.st_ino)
                or before.st_size != after.st_size
                or size != after.st_size
            ):
                raise EssentialStageError(
                    code, "managed media asset changed during verification"
                )
            actual_sha256 = digest.hexdigest()
            if (
                expected_size is not None
                and size != expected_size
            ) or (
                expected_sha256 is not None
                and actual_sha256 != expected_sha256
            ):
                raise EssentialStageError(
                    code, "managed media asset failed immutable integrity verification"
                )
            return stored.absolute, size, actual_sha256, bytes(captured)
        finally:
            os.close(descriptor)

    def _media_descriptor_state(
        self, match: Match
    ) -> tuple[tuple[int, int, int, int, int], ...]:
        from squashvision.models import AssetKind

        assets = {asset.kind: asset for asset in match.media_assets}
        try:
            paths = (
                assets[AssetKind.ORIGINAL].relative_path,
                assets[AssetKind.PROXY].relative_path,
                assets[AssetKind.TIMESTAMP_MAP].relative_path,
                assets[AssetKind.PROXY].timestamp_index_path,
            )
        except KeyError as error:
            raise EssentialStageError(
                "media_asset_missing",
                "original, proxy, and timestamp map are required",
            ) from error
        if paths[-1] is None:
            raise EssentialStageError(
                "timestamp_index_corrupt", "timestamp index metadata is incomplete"
            )
        states: list[tuple[int, int, int, int, int]] = []
        for raw_path in paths:
            if raw_path is None:
                raise EssentialStageError(
                    "timestamp_index_corrupt",
                    "timestamp index metadata is incomplete",
                )
            relative = Path(raw_path)
            try:
                descriptor = self._storage.open_owned(
                    relative,
                    owned_paths={relative},
                )
                try:
                    info = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
            except (OSError, PermissionError, ValueError) as error:
                raise EssentialStageError(
                    "media_asset_corrupt",
                    "managed media asset is missing or unsafe",
                ) from error
            states.append(
                (
                    info.st_dev,
                    info.st_ino,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )
            )
        return tuple(states)

    def _safe_asset_path(self, relative: str) -> Path:
        relative_path = Path(relative)
        try:
            stored = self._storage.resolve(
                relative_path,
                owned_paths={relative_path},
            )
            descriptor = self._storage.open_owned(
                relative_path,
                owned_paths={relative_path},
            )
            os.close(descriptor)
        except (OSError, PermissionError, ValueError) as error:
            raise EssentialStageError(
                "media_asset_corrupt",
                "managed media asset is missing or escapes storage",
            ) from error
        return stored.absolute

    @staticmethod
    def _file_hash(path: Path) -> str:
        signature = ArtifactStore._signature(path)
        if signature is None:
            raise EssentialStageError("media_asset_corrupt", f"asset is unreadable: {path.name}")
        return signature[1]

    @staticmethod
    def _json_safe(value: object) -> object:
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return {
                item.name: AnalysisPipeline._json_safe(getattr(value, item.name))
                for item in fields(value)
            }
        if isinstance(value, Mapping):
            return {
                str(key.value if isinstance(key, Enum) else key): AnalysisPipeline._json_safe(item)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [AnalysisPipeline._json_safe(item) for item in value]
        return value

    @staticmethod
    def _json_payload(value: object, *, availability: str = "available", evidence: tuple[str, ...], warnings: tuple[str, ...] = (), errors: tuple[str, ...] = (), row_count: int = 1) -> StagePayload:
        return StagePayload(
            data=json.dumps(
                AnalysisPipeline._json_safe(value),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8"),
            suffix=".json",
            availability=availability,
            evidence=evidence,
            warnings=warnings,
            errors=errors,
            row_count=row_count,
        )

    def _prepare(self, execution: StageExecution) -> StagePayload:
        context = execution.context
        for path in (context.source_path, context.proxy_path, context.timestamp_map_path):
            if path is None or not path.is_file():
                raise EssentialStageError("media_asset_missing", "prepared media asset is missing")
        pose = context.model_assets.get("pose")
        if pose is None or getattr(getattr(pose, "state", None), "value", None) != "ready":
            raise EssentialStageError("pose_model_unavailable", "approved pose model is not ready")
        ball = context.model_assets.get("ball")
        ball_state = getattr(getattr(ball, "state", None), "value", "missing")
        return self._json_payload(
            {
                "source_checksum": context.source_checksum,
                "proxy_checksum": context.proxy_checksum,
                "timestamp_map_hash": context.timestamp_map_hash,
                "duration_us": context.duration_us,
                "pose_state": "ready",
                "ball_state": ball_state,
            },
            evidence=("media-hashes-verified", "pose-model-verified"),
        )

    def _representative_frame(self, execution: StageExecution):
        frames = self._decode_frames(execution, stride=max(1, execution.profile_config.player_stride), maximum=1, representative=True)
        if not frames.frames:
            raise EssentialStageError("media_decode_failed", "proxy yielded no representative frame")
        return frames.frames[0]

    def _calibration(self, execution: StageExecution) -> StagePayload:
        from squashvision.calibration import CALIBRATED_MEASUREMENT_THRESHOLD, Size, detect_court, fit_calibration

        if execution.context.calibration_revision is not None:
            return self._json_payload(
                {
                    "revision": execution.context.calibration_revision,
                    "capabilities": dict(execution.context.calibration_capabilities),
                    "source": "saved",
                },
                evidence=("saved-calibration",),
            )
        frame = self._representative_frame(execution)
        proposal = detect_court(frame.image)
        height, width = frame.image.shape[:2]
        fitted = fit_calibration(proposal.keypoints, Size(width, height))
        available = fitted.confidence >= CALIBRATED_MEASUREMENT_THRESHOLD and fitted.calibrated
        capabilities = asdict(fitted.capabilities)
        revision = (
            self._persist_automatic_calibration(execution, frame, proposal, fitted)
            if available
            else None
        )
        return self._json_payload(
            {
                "revision": revision,
                "capabilities": capabilities,
                "source": "automatic" if available else "image-space-degraded",
                "confidence": fitted.confidence,
                "warnings": list(fitted.warnings),
            },
            availability="available" if available else "partial",
            evidence=("automatic-court-fit",) if available else ("image-space-only",),
            warnings=tuple(fitted.warnings),
        )

    def _persist_automatic_calibration(
        self,
        execution: StageExecution,
        frame: object,
        proposal: object,
        fitted: object,
    ) -> int | None:
        if self.database is None:
            return None
        from sqlalchemy import func, select

        from squashvision.models import (
            AssetKind,
            Calibration,
            MediaAsset,
            StagePublication,
        )

        with self._publication_session(execution) as (
            session,
            analysis_job,
            existing,
        ):
            assert session is not None and analysis_job is not None
            if existing is not None:
                if existing.calibration_revision is None:
                    raise EssentialStageError(
                        "stage_publication_invalid",
                        "calibration publication lacks its revision",
                    )
                return existing.calibration_revision
            match = session.scalar(
                select(Match).where(
                    Match.public_id == execution.context.match_public_id
                )
            )
            if match is None:
                return None
            proxy = session.scalar(
                select(MediaAsset).where(
                    MediaAsset.match_id == match.id,
                    MediaAsset.kind == AssetKind.PROXY,
                )
            )
            if proxy is None:
                raise EssentialStageError(
                    "proxy_missing",
                    "automatic calibration cannot identify its proxy asset",
                )
            latest = session.scalar(
                select(func.max(Calibration.revision)).where(
                    Calibration.match_id == match.id
                )
            )
            revision = (latest or 0) + 1
            height, width = frame.image.shape[:2]
            session.add(
                Calibration(
                    match=match,
                    media_asset=proxy,
                    revision=revision,
                    frame_width=width,
                    frame_height=height,
                    keypoints=self._json_safe(proposal.keypoints.points),
                    result=self._json_safe(fitted),
                    confidence=fitted.confidence,
                    capabilities=self._json_safe(fitted.capabilities),
                )
            )
            session.flush()
            session.add(
                StagePublication(
                    match_id=match.id,
                    analysis_job_id=analysis_job.id,
                    stage=Stage.CALIBRATION,
                    input_hash=execution.input_hash,
                    worker_id=execution.job.worker_id,
                    claim_token=execution.job.claim_token,
                    calibration_revision=revision,
                )
            )
        self._automatic_calibrations[execution.context.match_public_id] = (
            revision,
            fitted,
        )
        return revision

    def _decode_frames(
        self,
        execution: StageExecution,
        *,
        stride: int,
        maximum: int | None = None,
        representative: bool = False,
        sample_count: int | None = None,
    ):
        from squashvision.observations import FrameBatch

        return FrameBatch(tuple(self._iter_decoded_frames(
            execution, stride=stride, maximum=maximum,
            representative=representative, sample_count=sample_count,
        )))

    def _iter_decoded_frames(
        self,
        execution: StageExecution,
        *,
        stride: int,
        maximum: int | None = None,
        representative: bool = False,
        sample_count: int | None = None,
    ):
        import av
        import numpy as np
        from squashvision.observations import Frame

        use_original = (
            execution.job.processing_profile is ProcessingProfile.MAXIMUM
            and execution.context.source_path is not None
            and execution.context.exact_timestamp_index_path is not None
            and execution.context.source_rotation == 0
            and (execution.context.source_frame_size is None or (
                execution.context.source_frame_size[0] <= 1280
                and execution.context.source_frame_size[1] <= 720
            ))
        )
        path = (
            execution.context.source_path
            if use_original
            else execution.context.proxy_path
        )
        index_path = execution.context.exact_timestamp_index_path
        if path is None or index_path is None:
            raise EssentialStageError(
                "timestamp_index_missing",
                "decode requires managed media and exact timestamp index",
            )
        target_us = (
            execution.context.duration_us // 2
            if representative
            else execution.chunk.start_us
        )
        end_us = (
            target_us + 1_000_000
            if representative
            else execution.chunk.end_us
        )
        indexed = ExactTimestampIndex.range_mapping(
            index_path,
            max(0, target_us - 1_000_000),
            min(execution.context.duration_us + 1, end_us + 1_000_000),
        )
        provenance = (
            {source_us: (source_us, frame) for source_us, frame in indexed.values()}
            if use_original
            else indexed
        )
        source_origin_us, proxy_origin_us = ExactTimestampIndex.raw_origins(
            index_path
        )
        raw_origin_us = (
            source_origin_us if use_original else proxy_origin_us
        )
        sample_keys = None
        if sample_count is not None:
            from squashvision.vision.ball.tracker import uniform_sample_indices
            eligible = []
            previous_index = -1
            for media_us, (_source_us, frame_index) in sorted(provenance.items()):
                if target_us <= media_us < end_us and frame_index > previous_index:
                    eligible.append(media_us)
                    previous_index = frame_index
            sample_keys = {eligible[index] for index in uniform_sample_indices(len(eligible), sample_count)}
        yielded = 0
        last_selected_index = -1
        with av.open(str(path), mode="r") as container:
            stream = container.streams.video[0]
            seek_pts = int(
                ((target_us + raw_origin_us) / 1_000_000)
                / float(stream.time_base)
            )
            container.seek(
                max(0, seek_pts), stream=stream, any_frame=False, backward=True
            )
            seen = 0
            for decoded in container.decode(stream):
                if decoded.pts is None:
                    continue
                raw_media_us = int(
                    round(
                        float(decoded.pts * stream.time_base)
                        * 1_000_000
                    )
                )
                media_us = raw_media_us - raw_origin_us
                if media_us < target_us:
                    continue
                if not representative and media_us >= execution.chunk.end_us:
                    break
                source = provenance.get(media_us)
                if source is None:
                    continue
                if source[1] <= last_selected_index:
                    continue
                if seen % stride == 0 and (sample_keys is None or media_us in sample_keys):
                    image = np.asarray(
                        decoded.to_ndarray(format="bgr24"), dtype=np.uint8
                    )
                    yield Frame(timestamp_us=source[0], source_frame_index=source[1], image=image)
                    yielded += 1
                    last_selected_index = source[1]
                    if maximum is not None and yielded >= maximum:
                        break
                seen += 1
        if not yielded:
            raise EssentialStageError(
                "media_decode_failed",
                f"media yielded no exactly mapped frames for {execution.chunk.start_us}-{execution.chunk.end_us}",
            )

    def _iter_frame_batches(
        self, execution: StageExecution, *, stride: int, batch_size: int,
        overlap_frames: int = 0, max_bytes: int = 128 * 1024 * 1024,
    ):
        """Decode bounded image buffers; preserve temporal overlap for TrackNet."""
        from squashvision.observations import FrameBatch

        if batch_size <= overlap_frames or overlap_frames < 0 or max_bytes <= 0:
            raise ValueError("frame batches require a positive non-overlapping capacity")
        buffered = []
        capacity = batch_size
        new_frames = 0
        for frame in self._iter_decoded_frames(execution, stride=stride):
            if not buffered:
                capacity = max(overlap_frames + 1, min(batch_size, max_bytes // frame.image.nbytes))
            buffered.append(frame)
            new_frames += 1
            if len(buffered) >= capacity:
                yield FrameBatch(tuple(buffered))
                buffered = buffered[-overlap_frames:] if overlap_frames else []
                new_frames = 0
        if buffered and new_frames:
            yield FrameBatch(tuple(buffered))

    def _players(self, execution: StageExecution) -> StagePayload:
        import numpy as np
        from squashvision.observations import write_player_observations
        from squashvision.vision.players import PlayerDetector, PlayerIdentityTracker

        asset = execution.context.model_assets.get("pose")
        if asset is None:
            raise EssentialStageError("pose_model_unavailable", "approved pose model is unavailable")
        batches = self._iter_frame_batches(execution,
            stride=execution.profile_config.player_stride,
            batch_size=execution.profile_config.inference_batch_size)
        detector = None
        tracker = PlayerIdentityTracker(
            source_manifest_id=execution.context.proxy_checksum,
            model_manifest_id=str(execution.context.models["pose"]["manifest_id"]),
        )
        # Reacquisition can emit interpolated observations for earlier frames.
        # Preserve those estimates while publishing in canonical time order.
        collected = []
        devices = set()
        fallback = False
        for frames in batches:
            if detector is None:
                detector_options = {"inference_batch_size": execution.profile_config.inference_batch_size}
                if execution.context.player_roi is not None:
                    region = execution.context.player_roi
                    source_size = region["frameSize"]
                    frame_height, frame_width = frames.frames[0].image.shape[:2]
                    detector_options["playing_area_polygon"] = np.asarray([
                        [point["x"] * frame_width / source_size["width"],
                         point["y"] * frame_height / source_size["height"]]
                        for point in region["points"]
                    ], dtype=np.float32)
                detector = PlayerDetector(asset, storage_root=self.storage_root, **detector_options)
            for result in detector.detect(frames):
                devices.add(result.device)
                fallback |= result.device_fallback
                collected.extend(tracker.update(result.timestamp_us, result))
        rows = tuple(sorted(collected, key=lambda row: (row.timestamp_us, row.player_id)))
        rows, boundary_warnings = self._reconcile_player_chunk(execution, rows)
        temporary = self.storage_root / f".players-{uuid4().hex}.parquet"
        try:
            info = write_player_observations(
                temporary,
                rows,
                source_manifest_id=execution.context.proxy_checksum,
                model_manifest_id=str(execution.context.models["pose"]["manifest_id"]),
            )
            data = temporary.read_bytes()
            if len(data) != info.byte_size or hashlib.sha256(data).hexdigest() != info.sha256:
                raise OSError("player Parquet failed post-write validation")
        finally:
            temporary.unlink(missing_ok=True)
        devices = tuple(sorted(devices))
        return StagePayload(
            data=data,
            suffix=".parquet",
            availability="available",
            evidence=(
                "pose-inference",
                "player-identity-tracking",
                f"device:{','.join(devices) if devices else 'none'}",
                f"device-fallback:{str(fallback).lower()}",
                *( (f"manual-image-playing-area:{canonical_hash(execution.context.player_roi)}",)
                   if execution.context.player_roi is not None else () ),
            ),
            warnings=boundary_warnings,
            row_count=len(rows),
        )

    def _reconcile_player_chunk(
        self, execution: StageExecution, rows: tuple[object, ...]
    ) -> tuple[tuple[object, ...], tuple[str, ...]]:
        key = (
            execution.context.match_public_id,
            execution.job.processing_profile.value,
        )
        state = self._player_boundary_states.setdefault(
            key, PlayerBoundaryState()
        )
        if execution.chunk.start_us == 0:
            state.initialize(("A", "B"))
            return rows, ()
        from squashvision.observations import read_player_observations

        candidates = list(
            self._latest.get(
                (
                    execution.context.match_public_id,
                    execution.job.processing_profile.value,
                    Stage.PLAYERS,
                ),
                (),
            )
        )
        if self.database is not None and execution.job.id is not None:
            from sqlalchemy import select
            from squashvision.models import JobChunk, StageStatus

            with self.database.session() as session:
                prior = session.scalar(
                    select(JobChunk)
                    .where(
                        JobChunk.analysis_job_id == execution.job.id,
                        JobChunk.stage == Stage.PLAYERS,
                        JobChunk.status == StageStatus.COMPLETED,
                        JobChunk.start_us < execution.chunk.start_us,
                        JobChunk.end_us > execution.chunk.start_us,
                    )
                    .order_by(JobChunk.start_us.desc())
                )
                if prior is not None and prior.input_hash is not None:
                    artifact = self.artifacts.load(
                        execution.context.match_public_id,
                        Stage.PLAYERS,
                        prior.input_hash,
                    )
                    if artifact is not None:
                        candidates.append(artifact)
        candidates = [
            artifact
            for artifact in candidates
            if artifact.envelope.start_us < execution.chunk.start_us
            and artifact.envelope.end_us > execution.chunk.start_us
            and self._artifact_matches_context(
                artifact, execution.context
            )
        ]
        previous = (
            max(candidates, key=lambda item: item.envelope.start_us)
            if candidates
            else None
        )
        if previous is None:
            state.reconcile(previous=[], current=[])
            return (
                tuple(
                    replace(
                        row,
                        ambiguous=True,
                        ambiguity_reason="chunk_boundary_without_overlap",
                    )
                    for row in rows
                ),
                ("player-boundary-ambiguity:no-overlap-artifact",),
            )
        prior_rows = read_player_observations(previous.payload_path)
        overlap_end = min(
            previous.envelope.end_us,
            execution.chunk.start_us
            + execution.profile_config.overlap_us,
        )
        prior_evidence = [
            {
                "timestamp_us": row.timestamp_us,
                "frame_index": row.source_frame_index,
                "player_id": row.player_id,
                "appearance": row.appearance,
            }
            for row in prior_rows
            if execution.chunk.start_us <= row.timestamp_us < overlap_end
        ]
        current_evidence = [
            {
                "timestamp_us": row.timestamp_us,
                "frame_index": row.source_frame_index,
                "player_id": row.player_id,
                "appearance": row.appearance,
            }
            for row in rows
            if execution.chunk.start_us <= row.timestamp_us < overlap_end
        ]
        boundary = state.reconcile(
            previous=prior_evidence, current=current_evidence
        )
        if boundary.ambiguous:
            return (
                tuple(
                    replace(
                        row,
                        ambiguous=True,
                        ambiguity_reason="ambiguous_chunk_boundary",
                    )
                    for row in rows
                ),
                (f"player-boundary-ambiguity:{boundary.warning}",),
            )
        return (
            tuple(
                replace(
                    row,
                    player_id=state.map_player(row.player_id),
                )
                for row in rows
            ),
            (
                f"player-boundary-mapping:{boundary.mapping['A']}:{boundary.mapping['B']}:{boundary.confidence:.6f}",
            ),
        )

    def _ball(self, execution: StageExecution) -> StagePayload:
        import torch
        from squashvision.observations import FrameBatch, write_ball_observations
        from squashvision.vision.ball import BallTracker, TrackNetV3, median_background
        from squashvision.vision.ball.tracker import MAX_MEDIAN_SAMPLES, WINDOW_SIZE

        asset = execution.context.model_assets.get("ball")
        if asset is None:
            raise DegradableStageError("ball_model_unavailable", "approved ball model is unavailable")
        # Select exactly the same uniform background samples without retaining
        # every decoded frame in a long chunk. Larger sources use the bounded
        # proxy, preserving exact source timing and image-coordinate provenance.
        samples = self._decode_frames(execution, stride=1, sample_count=MAX_MEDIAN_SAMPLES)
        background = median_background(samples)
        del samples
        inverted = execution.context.ball_input_mode == BallInputMode.INVERTED
        model_background = 255 - background if inverted else background
        device = torch.device(
            "mps" if torch.backends.mps.is_available() else "cpu"
        )
        try:
            model = TrackNetV3.load(
                asset, device, storage_root=self.storage_root
            )
            tracker = BallTracker(
                model=model,
                source_manifest_id=execution.context.proxy_checksum,
                model_manifest_id=str(
                    execution.context.models["ball"]["manifest_id"]
                ),
                device=device,
                inference_batch_size=execution.profile_config.inference_batch_size,
            )
            collected = []
            for frames in self._iter_frame_batches(execution, stride=1,
                batch_size=execution.profile_config.inference_batch_size + WINDOW_SIZE - 1,
                overlap_frames=WINDOW_SIZE - 1):
                if inverted:
                    frames = FrameBatch(tuple(replace(frame, image=255 - frame.image) for frame in frames))
                collected.extend(tracker.track(frames, model_background))
            rows = tuple(collected)
            raw_visible_count = sum(row.visible for row in rows)
            if inverted:
                from squashvision.vision.ball.contrast_support import DarkBallSupport
                player_rows, _ = self._player_rows(execution)
                if not player_rows:
                    raise DegradableStageError("dark_ball_support_unavailable",
                        "dark-ball input requires player exclusion evidence")
                guard = DarkBallSupport(background, player_rows)
                rows = guard.filter_rows(rows, self._iter_decoded_frames(execution, stride=1))
        except (
            FileNotFoundError,
            pickle.UnpicklingError,
            ValueError,
            RuntimeError,
            NotImplementedError,
        ) as error:
            raise DegradableStageError(
                "ball_inference_failed", str(error)
            ) from error
        temporary = self.storage_root / f".ball-{uuid4().hex}.parquet"
        try:
            info = write_ball_observations(
                temporary,
                rows,
                source_manifest_id=execution.context.proxy_checksum,
                model_manifest_id=str(
                    execution.context.models["ball"]["manifest_id"]
                ),
            )
            data = temporary.read_bytes()
            if (
                len(data) != info.byte_size
                or hashlib.sha256(data).hexdigest() != info.sha256
            ):
                raise OSError("ball Parquet failed post-write validation")
        finally:
            temporary.unlink(missing_ok=True)
        return StagePayload(
            data=data,
            suffix=".parquet",
            availability="available",
            evidence=(
                "tracknet-inference",
                "no-ball-evidence-retained",
                f"device:{tracker.device.type}",
                f"device-fallback:{str(tracker.device_fallback).lower()}",
            ) + ((
                "input-transform:uint8_invert_all_frames_and_median_v1",
                f"image-support-policy:{_ball_preprocessing(execution.context)['support_policy']}",
                f"image-supported-observations:{sum(row.visible for row in rows)}/{raw_visible_count}",
            ) if inverted else ()),
            warnings=(("experimental-dark-ball-input:partial-observation-coverage",) if inverted else ()),
            row_count=len(rows),
        )

    @staticmethod
    def _player_rows(execution: StageExecution):
        from squashvision.observations import read_player_observations

        selected: dict[tuple[int, str, str, str], object] = {}
        warnings: list[str] = []
        provenance: dict[tuple[int, str], tuple[str, str]] = {}
        for artifact in execution.upstream:
            if (
                artifact.envelope.stage != Stage.PLAYERS.value
                or artifact.envelope.availability == "unavailable"
            ):
                continue
            for row in read_player_observations(artifact.payload_path):
                source_key = (
                    row.timestamp_us,
                    row.player_id,
                )
                identity = (row.source_manifest_id, row.model_manifest_id)
                prior_identity = provenance.setdefault(source_key, identity)
                if prior_identity != identity:
                    warnings.append("player-overlap-provenance-conflict")
                key = (*source_key, *identity)
                current = selected.get(key)
                # Overlapping chunks may reconstruct a frame that another
                # chunk observed. They are one logical track position, and an
                # actual observation takes precedence over interpolation.
                def rank(candidate):
                    return (candidate.evidence.value == "observed",
                            candidate.association_confidence * candidate.detection_confidence)
                if current is None or rank(row) > rank(current):
                    selected[key] = row
        return (
            tuple(
                sorted(
                    selected.values(),
                    key=lambda row: (
                        row.timestamp_us,
                        row.player_id,
                        row.model_manifest_id,
                    ),
                )
            ),
            tuple(sorted(set(warnings))),
        )

    @staticmethod
    def _ball_rows(execution: StageExecution):
        from squashvision.observations import read_ball_observations
        from squashvision.vision.ball import repair_track

        selected: dict[tuple[int, int | None, str, str], object] = {}
        warnings: list[str] = []
        provenance: dict[tuple[int, int | None], tuple[str, str]] = {}
        for artifact in execution.upstream:
            if (
                artifact.envelope.stage != Stage.BALL.value
                or artifact.envelope.availability == "unavailable"
            ):
                continue
            for row in read_ball_observations(artifact.payload_path):
                source_key = (row.timestamp_us, row.source_frame_index)
                identity = (row.source_manifest_id, row.model_manifest_id)
                prior_identity = provenance.setdefault(source_key, identity)
                if prior_identity != identity:
                    warnings.append("ball-overlap-provenance-conflict")
                key = (*source_key, *identity)
                current = selected.get(key)
                if current is None or row.probability > current.probability:
                    selected[key] = row
        ordered = tuple(
            sorted(
                selected.values(),
                key=lambda row: (
                    row.timestamp_us,
                    row.source_frame_index
                    if row.source_frame_index is not None
                    else -1,
                    row.model_manifest_id,
                ),
            )
        )
        repaired = repair_track(ordered, execution.context.calibration)
        points = tuple(
            point for segment in repaired.segments for point in segment.points
        )
        if repaired.max_pending_gap_count:
            warnings.append(
                f"ball-pending-gap-max:{repaired.max_pending_gap_count}"
            )
        return points, repaired.segments, tuple(sorted(set(warnings)))

    @staticmethod
    def _audio_impacts(execution: StageExecution):
        if not execution.profile_config.audio_fusion:
            return (), ("audio-skipped-profile",)
        import av
        import numpy as np
        from squashvision.vision.contacts import detect_audio_impacts

        path = execution.context.proxy_path
        if path is None:
            return (), ("audio-unavailable",)
        impacts = []
        try:
            with av.open(str(path), mode="r") as container:
                streams = tuple(container.streams.audio)
                if not streams:
                    return (), ("audio-unavailable",)
                stream = streams[0]
                for frame in container.decode(stream):
                    raw = np.asarray(frame.to_ndarray())
                    samples = normalize_audio_frame(
                        raw,
                        channels=len(frame.layout.channels),
                        planar=bool(frame.format.is_planar),
                    )
                    detected = detect_audio_impacts(
                        samples, int(frame.sample_rate)
                    )
                    origin_us = (
                        0
                        if frame.pts is None
                        else int(
                            round(
                                float(frame.pts * frame.time_base) * 1_000_000
                            )
                        )
                    )
                    impacts.extend(
                        replace(item, timestamp_us=origin_us + item.timestamp_us)
                        for item in detected
                    )
        except (av.error.FFmpegError, OSError, ValueError):
            return (), ("audio-unavailable",)
        return tuple(impacts), ()

    @staticmethod
    def _contact_from_dict(value: Mapping[str, object]):
        from squashvision.vision.contacts import (
            ContactEvent,
            ContactEvidence,
            ContactType,
            Hitter,
        )

        type_probabilities = {
            ContactType(str(key)): float(item)
            for key, item in dict(value["type_probabilities"]).items()
        }
        hitter_probabilities = {
            Hitter(str(key)): float(item)
            for key, item in dict(value["hitter_probabilities"]).items()
        }
        evidence = dict(value["evidence"])
        return ContactEvent(
            segment_id=str(value["segment_id"]),
            contact_id=str(value["contact_id"]),
            timestamp_us=int(value["timestamp_us"]),
            uncertainty_us=int(value["uncertainty_us"]),
            type_probabilities=type_probabilities,
            selected_type=ContactType(str(value["selected_type"])),
            hitter_probabilities=hitter_probabilities,
            selected_hitter=Hitter(str(value["selected_hitter"])),
            confidence=float(value["confidence"]),
            review_required=bool(value["review_required"]),
            review_reasons=tuple(str(item) for item in value["review_reasons"]),
            evidence=ContactEvidence(
                audio=float(evidence["audio"]),
                direction_change=float(evidence["direction_change"]),
                speed_change=float(evidence["speed_change"]),
                ball_uncertainty=float(evidence["ball_uncertainty"]),
                ball_gap=float(evidence["ball_gap"]),
                wrist_proximity=float(evidence["wrist_proximity"]),
                topology_proximity=float(evidence["topology_proximity"]),
            ),
            supporting_ball_timestamps_us=tuple(
                int(item) for item in value["supporting_ball_timestamps_us"]
            ),
            supporting_player_timestamps_us=tuple(
                int(item) for item in value["supporting_player_timestamps_us"]
            ),
        )

    def _events(self, execution: StageExecution) -> StagePayload:
        from bisect import bisect_left

        from squashvision.vision.contacts import fuse_contacts
        from squashvision.vision.rallies import ActivitySample, segment_rallies

        players, player_warnings = self._player_rows(execution)
        ball_available = execution.upstream_available(Stage.BALL)
        if not ball_available:
            return self._json_payload(
                {
                    "mode": "player-only",
                    "contacts": [],
                    "rallies": [],
                    "audio": "unavailable",
                    "player_observation_count": len(players),
                    "ball_observation_count": 0,
                },
                availability="partial",
                evidence=("overlap-deduplicated", "player-evidence-retained"),
                warnings=tuple(
                    sorted(
                        {
                            *player_warnings,
                            "ball-unavailable-player-only-events",
                        }
                    )
                ),
                row_count=0,
            )
        ball, _segments, ball_warnings = self._ball_rows(execution)
        audio, audio_warnings = self._audio_impacts(execution)
        contacts = fuse_contacts(
            ball, players, audio, execution.context.calibration
        )
        player_times = [row.timestamp_us for row in players]
        activity = []
        for point in ball:
            index = bisect_left(player_times, point.timestamp_us)
            nearby = players[max(0, index - 2) : index + 2]
            player_activity = max(
                (
                    row.association_confidence
                    for row in nearby
                    if abs(row.timestamp_us - point.timestamp_us) <= 100_000
                ),
                default=0.0,
            )
            activity.append(
                ActivitySample(
                    timestamp_us=point.timestamp_us,
                    ball_visible=point.visible,
                    ball_confidence=point.probability if point.visible else 0.0,
                    player_activity=player_activity,
                )
            )
        rallies = segment_rallies(contacts, activity)
        warnings = tuple(
            sorted({*player_warnings, *ball_warnings, *audio_warnings})
        )
        return self._json_payload(
            {
                "mode": "ball-and-player",
                "contacts": contacts,
                "rallies": rallies,
                "audio": "available" if not audio_warnings else "unavailable",
                "player_observation_count": len(players),
                "ball_observation_count": len(ball),
            },
            evidence=(
                "overlap-deduplicated",
                "ball-seams-repaired",
                "contact-fusion",
                "rally-state-machine",
            ),
            warnings=warnings,
            row_count=len(contacts) + len(rallies),
        )

    def _classification(self, execution: StageExecution) -> StagePayload:
        from squashvision.vision.contacts import ContactType, Hitter
        from squashvision.vision.shots import (
            ShotContext,
            ShotWindowBoundary,
            TerminalContext,
            TrajectoryContactConstraint,
            classify_shot,
            classify_terminal_event,
            estimate_speed,
            estimate_trajectory,
        )

        event_artifact = next(
            (
                item
                for item in execution.upstream
                if item.envelope.stage == Stage.EVENTS.value
            ),
            None,
        )
        if event_artifact is None:
            raise EssentialStageError(
                "events_missing", "classification requires events artifact"
            )
        event_payload = json.loads(
            event_artifact.payload_path.read_text(encoding="utf-8")
        )
        players, player_warnings = self._player_rows(execution)
        ball_available = (
            event_payload.get("mode") == "ball-and-player"
            and execution.upstream_available(Stage.BALL)
        )
        shot_rows: list[dict[str, object]] = []
        rally_rows = list(event_payload.get("rallies", []))
        warnings = list(player_warnings)
        trajectory_rows: dict[str, dict[str, object]] = {}
        error_rows: list[dict[str, object]] = []
        evidence_frames: list[tuple[int, int]] = []
        if ball_available:
            ball, segments, ball_warnings = self._ball_rows(execution)
            warnings.extend(ball_warnings)
            contacts = tuple(
                sorted(
                    (
                        self._contact_from_dict(item)
                        for item in event_payload.get("contacts", [])
                    ),
                    key=lambda item: (item.timestamp_us, item.contact_id),
                )
            )
            evidence_index = _EvidenceIndex(ball, players)
            frame_index = _TimestampIndex(
                tuple(
                    point
                    for point in ball
                    if point.source_frame_index is not None
                )
            )
            player_indexes = {
                player_id: _TimestampIndex(
                    tuple(
                        row
                        for row in players
                        if row.player_id == player_id
                    )
                )
                for player_id in ("A", "B")
            }

            contact_by_id = {contact.contact_id: contact for contact in contacts}
            for rally_row in rally_rows:
                contact_rows = [
                    contact_by_id[contact_id]
                    for contact_id in rally_row.get("supporting_contact_ids", [])
                    if contact_id in contact_by_id
                ]
                timestamps = [
                    timestamp
                    for contact in contact_rows
                    for timestamp in (
                        *contact.supporting_ball_timestamps_us,
                        *contact.supporting_player_timestamps_us,
                    )
                ]
                rally_row["provenance"] = _support_provenance(
                    timestamps,
                    evidence_index,
                    competing=any(contact.review_required for contact in contact_rows),
                )
            evidence_frames = [
                (point.timestamp_us, point.source_frame_index)
                for point in ball
                if point.source_frame_index is not None
            ]
            contacts_by_segment: dict[str, list[object]] = {}
            for item in contacts:
                contacts_by_segment.setdefault(item.segment_id, []).append(
                    item
                )
            contact_indexes = {
                segment_id: _TimestampIndex(tuple(rows))
                for segment_id, rows in contacts_by_segment.items()
            }
            segment_indexes = {
                segment.segment_id: _TimestampIndex(segment.points)
                for segment in segments
            }
            next_racket_by_id: dict[str, object | None] = {}
            for segment_contacts in contacts_by_segment.values():
                segment_rackets = tuple(
                    item
                    for item in segment_contacts
                    if item.selected_type is ContactType.RACKET
                    and item.selected_hitter in {Hitter.A, Hitter.B}
                )
                for index, item in enumerate(segment_rackets):
                    next_racket_by_id[item.contact_id] = (
                        segment_rackets[index + 1]
                        if index + 1 < len(segment_rackets)
                        else None
                    )
            for segment in segments:
                segment_contacts = tuple(
                    contacts_by_segment.get(segment.segment_id, ())
                )
                if execution.context.calibration is None:
                    trajectory_rows[segment.segment_id] = {
                        "trajectory": {
                            "available": False,
                            "unavailability_reason": "calibration_unavailable",
                            "segment_id": segment.segment_id,
                        },
                        "speed": {
                            "available": False,
                            "reason": "calibration_unavailable",
                            "segment_id": segment.segment_id,
                        },
                    }
                else:
                    constraints = tuple(
                        TrajectoryContactConstraint(
                            segment_id=item.segment_id,
                            contact_id=item.contact_id,
                            timestamp_us=item.timestamp_us,
                            confidence=item.confidence,
                        )
                        for item in segment_contacts[:126]
                    )
                    trajectory = estimate_trajectory(
                        replace(
                            segment,
                            points=segment.points[-4096:],
                        ),
                        execution.context.calibration,
                        contact_constraints=constraints,
                    )
                    speed = estimate_speed(trajectory)
                    trajectory_rows[segment.segment_id] = {
                        "trajectory": trajectory,
                        "speed": speed,
                    }
                terminal = (
                    segment_contacts[-1] if segment_contacts else None
                )
                originating_racket = (
                    next(
                        (
                            item
                            for item in reversed(segment_contacts)
                            if item.timestamp_us < terminal.timestamp_us
                            and item.selected_type is ContactType.RACKET
                            and item.selected_hitter
                            in {Hitter.A, Hitter.B}
                        ),
                        None,
                    )
                    if terminal is not None
                    else None
                )
                if terminal is not None and originating_racket is not None:
                    terminal_start = max(
                        segment.points[0].timestamp_us,
                        terminal.timestamp_us - 3_000_000,
                    )
                    terminal_segment = replace(
                        segment,
                        points=segment_indexes[
                            segment.segment_id
                        ].between(
                            terminal_start,
                            terminal.timestamp_us,
                        )[-4096:],
                    )
                    terminal_contacts = contact_indexes[
                        segment.segment_id
                    ].between(
                        terminal_start,
                        terminal.timestamp_us,
                    )
                    error_prediction = classify_terminal_event(
                        TerminalContext(
                            contacts=terminal_contacts,
                            ball_segment=terminal_segment,
                            calibration=execution.context.calibration,
                            terminal_player=originating_racket.selected_hitter,
                            window_start_us=terminal_start,
                            window_end_us=terminal.timestamp_us,
                            terminal_contact_id=terminal.contact_id,
                            max_contact_tolerance_us=120_000,
                        )
                    )
                    error_rows.append(
                        {
                            "segment_id": segment.segment_id,
                            "contact_id": terminal.contact_id,
                            "shot_contact_id": originating_racket.contact_id,
                            "source_timestamp_us": terminal.timestamp_us,
                            "prediction": error_prediction,
                            "provenance": _support_provenance(
                                error_prediction.support_timestamps_us,
                                evidence_index,
                                competing=(
                                    terminal.review_required
                                    or originating_racket.review_required
                                ),
                            ),
                        }
                    )
                elif terminal is not None:
                    warnings.append(
                        f"terminal-outcome-unavailable:no-preceding-shot:{terminal.contact_id}"
                    )
            racket = tuple(
                item
                for item in contacts
                if item.selected_type is ContactType.RACKET
                and item.selected_hitter in {Hitter.A, Hitter.B}
            )
            rally_contexts = _rally_racket_contexts(racket, rally_rows)
            by_segment = {segment.segment_id: segment for segment in segments}
            for position, contact in enumerate(racket):
                segment = by_segment.get(contact.segment_id)
                if segment is None:
                    warnings.append(
                        f"shot-contact-missing-segment:{contact.contact_id}"
                    )
                    continue
                next_racket = next_racket_by_id.get(contact.contact_id)
                segment_start = segment.points[0].timestamp_us
                segment_end = segment.points[-1].timestamp_us
                window_start = max(segment_start, contact.timestamp_us - 1_000_000)
                window_end = (
                    next_racket.timestamp_us
                    if next_racket is not None
                    else min(segment_end, contact.timestamp_us + 2_000_000)
                )
                if window_end <= contact.timestamp_us:
                    warnings.append(
                        f"shot-window-unavailable:{contact.contact_id}"
                    )
                    continue
                bounded_segment = replace(
                    segment,
                    points=segment_indexes[
                        segment.segment_id
                    ].between(window_start, window_end)[-4096:],
                )
                hitter_id = contact.selected_hitter.value
                opponent_id = "B" if hitter_id == "A" else "A"
                window_contacts = contact_indexes[
                    contact.segment_id
                ].between(window_start, window_end)
                post_contacts = tuple(
                    item
                    for item in window_contacts
                    if contact.timestamp_us < item.timestamp_us < window_end
                    and item.selected_type is not ContactType.RACKET
                )
                prior_contacts = tuple(
                    item
                    for item in window_contacts
                    if item.timestamp_us < contact.timestamp_us
                )
                prediction = classify_shot(
                    ShotContext(
                        hitter_contact=contact,
                        post_hit_contacts=post_contacts,
                        ball_segment=bounded_segment,
                        hitter_observations=player_indexes[
                            hitter_id
                        ].between(window_start, window_end),
                        opponent_observations=player_indexes[
                            opponent_id
                        ].between(window_start, window_end),
                        calibration=execution.context.calibration,
                        rally_position=rally_contexts.get(
                            contact.contact_id, (position, False)
                        )[0],
                        serve_context=rally_contexts.get(
                            contact.contact_id, (position, False)
                        )[1],
                        window_start_us=window_start,
                        hit_timestamp_us=contact.timestamp_us,
                        window_end_us=window_end,
                        max_hit_tolerance_us=120_000,
                        max_player_tolerance_us=120_000,
                        prior_contacts=prior_contacts,
                        wall_geometry_supported=execution.context.calibration is not None,
                        calibration_revision=(
                            None
                            if execution.context.calibration_revision is None
                            else str(execution.context.calibration_revision)
                        ),
                        window_boundary=(
                            ShotWindowBoundary.NEXT_RACKET
                            if next_racket is not None
                            else ShotWindowBoundary.TERMINAL
                        ),
                        boundary_contact=next_racket,
                    )
                )
                contact_ball = min(
                    (
                        point
                        for point in segment_indexes[
                            segment.segment_id
                        ].between(
                            contact.timestamp_us - 120_000,
                            contact.timestamp_us + 120_000,
                        )
                        if point.visible
                        and point.x is not None
                        and point.y is not None
                        and point.covariance is not None
                    ),
                    key=lambda point: abs(
                        point.timestamp_us - contact.timestamp_us
                    ),
                    default=None,
                )
                nearest_frame = frame_index.nearest(contact.timestamp_us)
                shot_rows.append(
                    {
                        "contact_id": contact.contact_id,
                        "segment_id": contact.segment_id,
                        "source_timestamp_us": contact.timestamp_us,
                        "source_frame_index": (
                            0
                            if nearest_frame is None
                            or nearest_frame.source_frame_index is None
                            else int(nearest_frame.source_frame_index)
                        ),
                        "prediction": prediction,
                        "trajectory": trajectory_rows.get(
                            contact.segment_id
                        ),
                        "contact_ball": contact_ball,
                        "provenance": _support_provenance(
                            [
                                *prediction.sample_timestamps_us,
                                *contact.supporting_ball_timestamps_us,
                                *contact.supporting_player_timestamps_us,
                            ],
                            evidence_index,
                            competing=contact.review_required,
                        ),
                    }
                )
            generated_shots = {
                str(row["contact_id"]) for row in shot_rows
            }
            retained_errors = [
                row
                for row in error_rows
                if str(row["shot_contact_id"]) in generated_shots
            ]
            retained_error_contacts = {
                str(row["contact_id"]) for row in retained_errors
            }
            for row in error_rows:
                if str(row["contact_id"]) not in retained_error_contacts:
                    warnings.append(
                        f"terminal-outcome-unavailable:no-generated-shot:{row['contact_id']}"
                    )
            error_rows = retained_errors
        revision = self._publish_prediction_revision(
            execution,
            players=players,
            rallies=rally_rows if ball_available else (),
            shots=shot_rows if ball_available else (),
            errors=error_rows if ball_available else (),
            evidence_frames=evidence_frames,
        )
        partial = not ball_available
        if partial:
            warnings.append("ball-unavailable-no-fabricated-shots")
        return self._json_payload(
            {
                "prediction_revision": revision,
                "player_rows": len(players),
                "shots": shot_rows if ball_available else [],
                "rallies": rally_rows if ball_available else [],
                "errors": error_rows if ball_available else [],
                "trajectories": (
                    trajectory_rows if ball_available else {}
                ),
                "trajectory_available": any(
                    bool(
                        row["trajectory"].available
                        if hasattr(row["trajectory"], "available")
                        else row["trajectory"].get("available", False)
                    )
                    for row in trajectory_rows.values()
                ),
            },
            availability="partial" if partial else "available",
            evidence=("immutable-unified-prediction-revision", "shot-classifier"),
            warnings=tuple(sorted(set(warnings))),
            row_count=len(players) + len(shot_rows) + len(rally_rows) + len(error_rows),
        )

    def _publish_prediction_revision(
        self,
        execution: StageExecution,
        *,
        players: Sequence[object],
        rallies: Sequence[Mapping[str, object]],
        shots: Sequence[Mapping[str, object]],
        errors: Sequence[Mapping[str, object]],
        evidence_frames: Sequence[tuple[int, int]],
    ) -> int:
        if self.database is None:
            return 1
        import bisect

        from sqlalchemy import func, select
        from squashvision.models import (
            ErrorCandidate,
            ErrorKind,
            PlayerSlot,
            PlayerTrack,
            Rally,
            Shot,
            ShotKind,
            StagePublication,
        )
        from squashvision.corrections import reapply_corrections_in_session

        from squashvision.calibration import (
            EvidenceLevel,
            ImagePoint,
            MAX_PLAYER_FLOOR_UNCERTAINTY_M,
            project_floor,
        )
        with self._publication_session(execution) as (
            session,
            analysis_job,
            existing,
        ):
            assert session is not None and analysis_job is not None
            if existing is not None:
                if existing.prediction_revision is None:
                    raise EssentialStageError(
                        "stage_publication_invalid",
                        "classification publication lacks its revision",
                    )
                return existing.prediction_revision
            match = session.scalar(
                select(Match).where(
                    Match.public_id == execution.context.match_public_id
                )
            )
            if match is None:
                raise EssentialStageError(
                    "match_missing", "prediction match no longer exists"
                )
            maxima = [
                session.scalar(
                    select(func.max(model.prediction_revision)).where(
                        model.match_id == match.id
                    )
                )
                for model in (PlayerTrack, Rally, Shot, ErrorCandidate)
            ]
            previous_revision = max(
                (value or 0 for value in maxima), default=0
            )
            revision = previous_revision + 1
            ordered_frames = sorted(evidence_frames)
            frame_times = [item[0] for item in ordered_frames]

            def nearest_frame(timestamp_us: int) -> int:
                if not ordered_frames:
                    raise EssentialStageError(
                        "source_frame_provenance_missing",
                        "prediction lacks exact source frame evidence",
                    )
                index = bisect.bisect_left(frame_times, timestamp_us)
                if index == len(ordered_frames):
                    index -= 1
                elif index and (
                    timestamp_us - frame_times[index - 1]
                    <= frame_times[index] - timestamp_us
                ):
                    index -= 1
                return ordered_frames[index][1]

            track_rows = []
            for row in players:
                position = None
                position_reason: str | None = None
                calibration = execution.context.calibration
                if (
                    calibration is None
                    or execution.context.calibration_revision is None
                ):
                    position_reason = "calibration_unavailable"
                elif (
                    not calibration.calibrated
                    or not calibration.capabilities.floor_position
                    or not calibration.capabilities.movement_distance
                ):
                    position_reason = "calibration_capability_unavailable"
                elif row.ambiguous:
                    position_reason = "ambiguous_identity"
                elif row.evidence.value != "observed":
                    position_reason = "reconstructed_player_observation"
                else:
                    estimate = project_floor(
                        ImagePoint(*row.feet),
                        calibration,
                        image_uncertainty_px=row.feet_uncertainty_px,
                    )
                    if estimate.value is None or estimate.uncertainty is None:
                        position_reason = "projection_unavailable"
                    elif estimate.inside_court is not True:
                        position_reason = "outside_court"
                    elif estimate.evidence is not EvidenceLevel.MEASURED:
                        position_reason = "calibration_estimated"
                    elif (
                        not math.isfinite(estimate.uncertainty)
                        or estimate.uncertainty
                        > MAX_PLAYER_FLOOR_UNCERTAINTY_M
                    ):
                        position_reason = "projection_uncertainty_exceeded"
                    else:
                        position = estimate
                track_rows.append(
                    PlayerTrack(
                        match=match,
                        analysis_job=analysis_job,
                        prediction_revision=revision,
                        prediction_id=(
                            f"track-{canonical_hash({
                                'player': row.player_id,
                                'timestamp': row.timestamp_us,
                                'model': row.model_manifest_id,
                            })[:24]}"
                        ),
                        slot=(
                            PlayerSlot.NEAR
                            if row.player_id == "A"
                            else PlayerSlot.FAR
                        ),
                        source_timestamp_us=row.timestamp_us,
                        source_evidence_ids=[
                            f"{row.source_manifest_id}:{row.model_manifest_id}:{row.evidence_start_frame_index}-{row.evidence_end_frame_index}"
                        ],
                        x_m=(
                            None
                            if position is None
                            else position.value.x_m
                        ),
                        y_m=(
                            None
                            if position is None
                            else position.value.y_m
                        ),
                        observed=row.evidence.value == "observed",
                        calibration_revision=execution.context.calibration_revision,
                        position_covariance=(
                            None
                            if position is None
                            else [
                                list(position.covariance[0]),
                                list(position.covariance[1]),
                            ]
                        ),
                        position_uncertainty_m=(
                            None
                            if position is None
                            else position.uncertainty
                        ),
                        position_provenance=(
                            "measured"
                            if position is not None
                            else "unavailable"
                        ),
                        position_unavailable_reason=position_reason,
                    )
                )
            session.add_all(track_rows)
            rally_models = []
            for ordinal, row in enumerate(rallies, start=1):
                start = dict(row["start"])
                end = dict(row["end"])
                start_us = int(start["selected_us"])
                end_us = int(end["selected_us"])
                rally_models.append(
                    Rally(
                        match=match,
                        prediction_revision=revision,
                        review_status=(
                            "pending"
                            if bool(row.get("review_required", False))
                            else "not_required"
                        ),
                        evidence_provenance=str(
                            row.get("provenance", "unavailable")
                        ),
                        prediction_id=str(row["rally_id"]),
                        ordinal=ordinal,
                        start_frame=nearest_frame(start_us),
                        end_frame=nearest_frame(end_us),
                        start_timestamp_us=start_us,
                        end_timestamp_us=end_us,
                        timing_available=True,
                        source_evidence_ids=[
                            str(item)
                            for item in row["supporting_contact_ids"]
                        ],
                        review_required=bool(row.get("review_required", False)),
                        review_reasons=[
                            str(value)
                            for value in row.get("review_reasons", [])
                        ],
                    )
                )
            session.add_all(rally_models)
            session.flush()
            timed_rallies = tuple(
                sorted(
                    (
                        model
                        for model in rally_models
                        if model.start_timestamp_us is not None
                        and model.end_timestamp_us is not None
                    ),
                    key=lambda model: model.start_timestamp_us,
                )
            )
            rally_starts = tuple(
                int(model.start_timestamp_us)
                for model in timed_rallies
                if model.start_timestamp_us is not None
            )
            shot_models = []
            for row in shots:
                prediction = row["prediction"]
                shot_kind = canonical_shot_kind(prediction.primary_type)
                timestamp = int(row["source_timestamp_us"])
                rally_index = bisect.bisect_right(
                    rally_starts, timestamp
                ) - 1
                containing = (
                    timed_rallies[rally_index]
                    if rally_index >= 0
                    and timed_rallies[rally_index].end_timestamp_us
                    is not None
                    and timestamp
                    <= int(timed_rallies[rally_index].end_timestamp_us)
                    else None
                )
                trajectory = row.get("trajectory") or {}
                speed = trajectory.get("speed")
                speed_available = hasattr(speed, "median_m_s")
                origin = prediction.features.origin_court_m
                contact_ball = row.get("contact_ball")
                classification_value = self._json_safe(prediction)
                classification_payload = (
                    dict(classification_value)
                    if isinstance(classification_value, dict)
                    else {}
                )
                shot_review_required = (
                    shot_kind is ShotKind.UNKNOWN
                    or any(
                        "insufficient" in str(reason).lower()
                        for reason in getattr(prediction, "reasons", ())
                    )
                    or float(getattr(prediction, "confidence", 1.0))
                    < float(getattr(prediction, "required_probability", 0.0))
                    or float(getattr(prediction, "margin", 1.0))
                    < float(getattr(prediction, "required_margin", 0.0))
                )
                shot_models.append(
                    Shot(
                        match=match,
                        rally=containing,
                        prediction_revision=revision,
                        prediction_id=f"shot-{row['contact_id']}",
                        frame_index=int(row["source_frame_index"]),
                        source_timestamp_us=timestamp,
                        source_evidence_ids=[
                            str(row["contact_id"]),
                            str(row["segment_id"]),
                        ],
                        hitter=(
                            PlayerSlot.NEAR
                            if prediction.hitter.value == "A"
                            else PlayerSlot.FAR
                            if prediction.hitter.value == "B"
                            else None
                        ),
                        kind=shot_kind,
                        is_volley=bool(prediction.volley),
                        outcome=canonical_shot_outcome(prediction.outcome),
                        contact_x_m=None if origin is None else origin[0],
                        contact_y_m=None if origin is None else origin[1],
                        contact_x_px=(
                            None if contact_ball is None else float(contact_ball.x)
                        ),
                        contact_y_px=(
                            None if contact_ball is None else float(contact_ball.y)
                        ),
                        contact_covariance=(
                            None
                            if contact_ball is None
                            else [
                                list(contact_ball.covariance[0]),
                                list(contact_ball.covariance[1]),
                            ]
                        ),
                        review_status=(
                            "pending" if shot_review_required else "not_required"
                        ),
                        evidence_provenance=str(
                            row.get("provenance", "unavailable")
                        ),
                        contact_provenance=(
                            None
                            if contact_ball is None
                            else contact_ball.evidence.value
                        ),
                        contact_source_width=(
                            None if contact_ball is None else contact_ball.source_width
                        ),
                        contact_source_height=(
                            None if contact_ball is None else contact_ball.source_height
                        ),
                        review_required=shot_review_required,
                        classification_payload=classification_payload,
                        speed_m_s=(
                            speed.median_m_s.estimate
                            if speed_available
                            else None
                        ),
                        speed_unavailable_reason=(
                            None
                            if speed_available
                            else getattr(
                                speed,
                                "reason",
                                "trajectory_unavailable",
                            )
                            if speed is not None
                            else "trajectory_unavailable"
                        ),
                    )
                )
            session.add_all(shot_models)
            error_models = []
            for row in errors:
                prediction = row["prediction"]
                serialized = self._json_safe(prediction)
                evidence_payload = (
                    dict(serialized) if isinstance(serialized, dict) else {}
                )
                source_timestamp_us = int(row["source_timestamp_us"])
                support_value = evidence_payload.get("support_timestamps_us")
                support_timestamps = [
                    int(value)
                    for value in support_value
                    if isinstance(value, int) and value >= 0
                ] if isinstance(support_value, list) else []
                anchor_timestamps = support_timestamps or [source_timestamp_us]
                evidence_start_timestamp_us = min(anchor_timestamps)
                evidence_end_timestamp_us = max(anchor_timestamps)
                evidence_payload.update(
                    {
                        "issue": "outcome",
                        "provenance": str(
                            row.get("provenance", "unavailable")
                        ),
                        "evidence_start_timestamp_us": evidence_start_timestamp_us,
                        "evidence_end_timestamp_us": evidence_end_timestamp_us,
                        "evidence_start_frame_index": nearest_frame(
                            evidence_start_timestamp_us
                        ),
                        "evidence_end_frame_index": nearest_frame(
                            evidence_end_timestamp_us
                        ),
                    }
                )
                error_models.append(
                    ErrorCandidate(
                        match=match,
                        analysis_job=analysis_job,
                        prediction_revision=revision,
                        prediction_id=f"error-{row['contact_id']}",
                        kind=ErrorKind.SHOT,
                        target_type="shot",
                        target_prediction_id=f"shot-{row['shot_contact_id']}",
                        source_timestamp_us=source_timestamp_us,
                        source_evidence_ids=[
                            str(row["contact_id"]),
                            str(row["shot_contact_id"]),
                            str(row["segment_id"]),
                        ],
                        evidence_version=1,
                        evidence_payload=evidence_payload,
                        review_status="pending",
                    )
                )
            session.add_all(error_models)
            session.flush()
            if previous_revision:
                reapply_corrections_in_session(
                    session,
                    match,
                    previous_revision,
                    revision,
                )
            session.add(
                StagePublication(
                    match_id=match.id,
                    analysis_job_id=analysis_job.id,
                    stage=Stage.CLASSIFICATION,
                    input_hash=execution.input_hash,
                    worker_id=execution.job.worker_id,
                    claim_token=execution.job.claim_token,
                    prediction_revision=revision,
                )
            )
            session.flush()
            return revision
    def _report(self, execution: StageExecution) -> StagePayload:
        classification = next(
            (item for item in execution.upstream if item.envelope.stage == Stage.CLASSIFICATION.value),
            None,
        )
        if classification is None:
            raise EssentialStageError("classification_missing", "report requires classification artifact")
        payload = json.loads(classification.payload_path.read_text(encoding="utf-8"))
        prediction_revision = int(payload["prediction_revision"])
        partial = classification.envelope.availability != "available"
        unavailable_dependencies = (
            ("shots", "rallies", "errors", "trajectory", "coaching")
            if partial
            else ()
        )
        if self.database is None:
            report_value: dict[str, object] = {
                "prediction_revision": prediction_revision,
                "partial": partial,
            }
        else:
            from sqlalchemy import func, select

            from squashvision.analytics import (
                _report_from_row,
                build_report_in_session,
            )
            from squashvision.models import (
                ReportRevision,
                StagePublication,
            )

            with self._publication_session(execution) as (
                session,
                analysis_job,
                existing,
            ):
                assert session is not None and analysis_job is not None
                match = session.scalar(
                    select(Match).where(
                        Match.public_id
                        == execution.context.match_public_id
                    )
                )
                if match is None:
                    raise EssentialStageError(
                        "match_missing", "report match no longer exists"
                    )
                if existing is not None:
                    if existing.report_revision is None:
                        raise EssentialStageError(
                            "stage_publication_invalid",
                            "report publication lacks its revision",
                        )
                    report_row = session.scalar(
                        select(ReportRevision).where(
                            ReportRevision.match_id == match.id,
                            ReportRevision.revision
                            == existing.report_revision,
                        )
                    )
                    if report_row is None:
                        raise EssentialStageError(
                            "stage_publication_invalid",
                            "published report revision is missing",
                        )
                    built = _report_from_row(
                        match.public_id, report_row
                    )
                else:
                    latest = session.scalar(
                        select(func.max(ReportRevision.revision)).where(
                            ReportRevision.match_id == match.id
                        )
                    )
                    report_revision = (latest or 0) + 1
                    built = build_report_in_session(
                        session,
                        match,
                        report_revision,
                        prediction_revision=prediction_revision,
                    )
                    session.add(
                        StagePublication(
                            match_id=match.id,
                            analysis_job_id=analysis_job.id,
                            stage=Stage.REPORT,
                            input_hash=execution.input_hash,
                            worker_id=execution.job.worker_id,
                            claim_token=execution.job.claim_token,
                            report_revision=report_revision,
                            prediction_revision=prediction_revision,
                        )
                    )
                report_value = built.model_dump(mode="json")
        report_value["analysis_availability"] = {
            "mode": "player-only" if partial else "complete",
            "unavailable_dependencies": list(unavailable_dependencies),
            "reason": "ball_unavailable" if partial else None,
        }
        return self._json_payload(
            report_value,
            availability="partial" if partial else "available",
            evidence=("exact-prediction-and-calibration-revision",),
            warnings=("player-only-report",) if partial else (),
        )


__all__ = [
    "ARTIFACT_SCHEMA_VERSIONS",
    "AnalysisPipeline",
    "ArtifactEnvelope",
    "ArtifactInfo",
    "ArtifactStore",
    "BallSeamResult",
    "ExactTimestampIndex",
    "DegradableStageError",
    "EssentialStageError",
    "PIPELINE_CODE_VERSION",
    "PROFILE_CONFIGS",
    "PipelineContext",
    "PipelinePlan",
    "PlayerBoundaryResult",
    "PlayerBoundaryState",
    "ProfileConfig",
    "StageExecution",
    "StagePayload",
    "canonical_hash",
    "reconcile_ball_seam",
    "reconcile_player_boundary",
    "normalize_audio_frame",
    "stage_input_hash",
]
