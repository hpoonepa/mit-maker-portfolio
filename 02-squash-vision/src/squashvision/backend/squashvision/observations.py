from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable
from uuid import uuid4

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from numpy.typing import NDArray

ARTIFACT_KIND = "player_observations"
SCHEMA_VERSION = 2
COORDINATE_CONVENTIONS = "image_bgr_pixels_xyxy_coco17"
COCO_KEYPOINT_COUNT = 17
APPEARANCE_DIMENSION = 72
BALL_MAX_CANDIDATES = 5


def _finite(*values: float) -> bool:
    return all(math.isfinite(float(value)) for value in values)


@dataclass(frozen=True, slots=True)
class Frame:
    timestamp_us: int
    source_frame_index: int
    image: NDArray[np.uint8]

    def __post_init__(self) -> None:
        if self.timestamp_us < 0 or self.source_frame_index < 0:
            raise ValueError("frame timestamp and source index must be nonnegative")
        if not isinstance(self.image, np.ndarray):
            raise TypeError("frame image must be a NumPy array")
        if self.image.ndim != 3 or self.image.shape[2] != 3 or self.image.dtype != np.uint8:
            raise ValueError("frame image must be an HxWx3 uint8 BGR array")
        if self.image.shape[0] == 0 or self.image.shape[1] == 0:
            raise ValueError("frame image must be nonempty")


@dataclass(frozen=True, slots=True)
class FrameBatch:
    frames: tuple[Frame, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", tuple(self.frames))
        if not self.frames:
            raise ValueError("frame batch must be nonempty")
        timestamps = tuple(frame.timestamp_us for frame in self.frames)
        indices = tuple(frame.source_frame_index for frame in self.frames)
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("frame timestamps must be strictly increasing")
        if any(current <= previous for previous, current in zip(indices, indices[1:])):
            raise ValueError("frame indices must be strictly increasing")

    def __len__(self) -> int:
        return len(self.frames)

    def __iter__(self):
        return iter(self.frames)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if not _finite(self.x1, self.y1, self.x2, self.y2):
            raise ValueError("bounding box values must be finite")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("bounding box must have positive area")

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


@dataclass(frozen=True, slots=True)
class Keypoint:
    x: float
    y: float
    confidence: float

    def __post_init__(self) -> None:
        if not _finite(self.x, self.y, self.confidence):
            raise ValueError("keypoint values must be finite")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("keypoint confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class PoseDetection:
    box: BoundingBox
    keypoints: tuple[Keypoint, ...]
    confidence: float
    frame_index: int
    timestamp_us: int
    appearance: tuple[float, ...]
    feet: tuple[float, float]
    feet_uncertainty_px: float
    court_overlap: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "keypoints", tuple(self.keypoints))
        object.__setattr__(self, "appearance", tuple(float(v) for v in self.appearance))
        if len(self.keypoints) != COCO_KEYPOINT_COUNT:
            raise ValueError("pose detection must contain 17 COCO keypoints")
        if self.frame_index < 0 or self.timestamp_us < 0:
            raise ValueError("pose source indices and timestamps must be nonnegative")
        if len(self.appearance) != APPEARANCE_DIMENSION:
            raise ValueError(
                f"appearance embedding must contain {APPEARANCE_DIMENSION} values"
            )
        if not _finite(
            self.confidence,
            *self.appearance,
            *self.feet,
            self.feet_uncertainty_px,
            self.court_overlap,
        ):
            raise ValueError("pose detection values must be finite")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("detection confidence must be between zero and one")
        if self.feet_uncertainty_px < 0:
            raise ValueError("feet uncertainty must be nonnegative")
        if not 0.0 <= self.court_overlap <= 1.0:
            raise ValueError("court overlap must be between zero and one")

    @property
    def pose_completeness(self) -> float:
        return sum(point.confidence >= 0.25 for point in self.keypoints) / COCO_KEYPOINT_COUNT


@dataclass(frozen=True, slots=True)
class PoseDetections:
    timestamp_us: int
    frame_index: int
    detections: tuple[PoseDetection, ...]
    device: str
    device_fallback: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "detections", tuple(self.detections))
        if self.timestamp_us < 0 or self.frame_index < 0:
            raise ValueError("pose result source values must be nonnegative")
        if self.device not in {"cpu", "mps"}:
            raise ValueError("pose result device must be cpu or mps")
        if any(item.timestamp_us != self.timestamp_us for item in self.detections):
            raise ValueError("pose detection timestamps must match their result")
        if any(item.frame_index != self.frame_index for item in self.detections):
            raise ValueError("pose detections must match their result source frame")


class EvidenceKind(StrEnum):
    OBSERVED = "observed"
    INTERPOLATED = "interpolated"

@dataclass(frozen=True, slots=True)
class BallCandidate:
    x: float
    y: float
    peak_probability: float
    integrated_probability: float
    area: int
    circularity: float
    covariance: tuple[tuple[float, float], tuple[float, float]]

    def __post_init__(self) -> None:
        covariance = tuple(tuple(float(value) for value in row) for row in self.covariance)
        object.__setattr__(self, "covariance", covariance)
        if len(covariance) != 2 or any(len(row) != 2 for row in covariance):
            raise ValueError("ball candidate covariance must be 2x2")
        values = (
            self.x,
            self.y,
            self.peak_probability,
            self.integrated_probability,
            self.circularity,
            *covariance[0],
            *covariance[1],
        )
        if not _finite(*values):
            raise ValueError("ball candidate values must be finite")
        if not 0.0 <= self.peak_probability <= 1.0:
            raise ValueError("ball candidate peak probability must be between zero and one")
        if not 0.0 <= self.integrated_probability <= 1.0:
            raise ValueError("ball candidate integrated probability must be between zero and one")
        if self.area <= 0:
            raise ValueError("ball candidate area must be positive")
        if not 0.0 <= self.circularity <= 1.0:
            raise ValueError("ball candidate circularity must be between zero and one")
        if abs(covariance[0][1] - covariance[1][0]) > 1.0e-9:
            raise ValueError("ball candidate covariance must be symmetric")
        determinant = covariance[0][0] * covariance[1][1] - covariance[0][1] ** 2
        if covariance[0][0] < 0.0 or covariance[1][1] < 0.0 or determinant < -1.0e-9:
            raise ValueError("ball candidate covariance must be positive semidefinite")


@dataclass(frozen=True, slots=True)
class BallObservation:
    timestamp_us: int
    source_timestamp_us: int | None
    source_frame_index: int | None
    source_width: int
    source_height: int
    x: float | None
    y: float | None
    probability: float
    covariance: tuple[tuple[float, float], tuple[float, float]] | None
    visible: bool
    candidate_count: int
    candidates: tuple[BallCandidate, ...]
    evidence: EvidenceKind
    evidence_start_timestamp_us: int
    evidence_end_timestamp_us: int
    evidence_start_frame_index: int
    evidence_end_frame_index: int
    ambiguous: bool
    ambiguity_reason: str | None
    segment_id: str | None
    source_manifest_id: str
    model_manifest_id: str
    device: str
    device_fallback: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "evidence", EvidenceKind(self.evidence))
        if self.covariance is not None:
            covariance = tuple(
                tuple(float(value) for value in row) for row in self.covariance
            )
            object.__setattr__(self, "covariance", covariance)
        if self.timestamp_us < 0:
            raise ValueError("ball observation timestamp must be nonnegative")
        if self.source_width <= 0 or self.source_height <= 0:
            raise ValueError("ball observation source dimensions must be positive")
        if self.candidate_count < 0:
            raise ValueError("ball observation candidate count must be nonnegative")
        if len(self.candidates) > BALL_MAX_CANDIDATES:
            raise ValueError("ball observation exceeds the fixed candidate bound")
        if self.candidate_count < len(self.candidates):
            raise ValueError("ball observation candidate count is smaller than its evidence")
        if len(self.candidates) != min(
            self.candidate_count, BALL_MAX_CANDIDATES
        ):
            raise ValueError(
                "ball observation requires complete bounded candidate evidence"
            )
        if not _finite(self.probability) or not 0.0 <= self.probability <= 1.0:
            raise ValueError("ball probability must be finite and between zero and one")
        coordinates_present = self.x is not None and self.y is not None
        if (self.x is None) != (self.y is None):
            raise ValueError("ball visible coordinates must be both present or both absent")
        if self.visible != coordinates_present:
            raise ValueError("ball visible flag and coordinates must agree")
        if self.visible:
            if self.covariance is None or not _finite(float(self.x), float(self.y)):
                raise ValueError("visible ball observation requires finite coordinates and covariance")
            BallCandidate(
                x=float(self.x),
                y=float(self.y),
                peak_probability=self.probability,
                integrated_probability=self.probability,
                area=1,
                circularity=1.0,
                covariance=self.covariance,
            )
        elif self.covariance is not None or self.probability != 0.0:
            raise ValueError("non-visible ball observation cannot claim coordinates or probability")
        if self.ambiguous != (self.ambiguity_reason is not None):
            raise ValueError("ball ambiguity flag and reason must agree")
        if self.segment_id is not None and not self.segment_id.strip():
            raise ValueError("ball segment identifier cannot be blank")
        if not self.source_manifest_id.strip() or not self.model_manifest_id.strip():
            raise ValueError("ball observation requires source and model manifest identifiers")
        if self.device not in {"cpu", "mps"}:
            raise ValueError("ball observation device must be cpu or mps")
        endpoints = (
            self.evidence_start_timestamp_us,
            self.evidence_end_timestamp_us,
            self.evidence_start_frame_index,
            self.evidence_end_frame_index,
        )
        if min(endpoints) < 0:
            raise ValueError("ball evidence provenance must be nonnegative")
        if self.evidence is EvidenceKind.OBSERVED:
            if self.source_timestamp_us is None or self.source_frame_index is None:
                raise ValueError("observed ball evidence requires source provenance")
            if (
                self.timestamp_us != self.source_timestamp_us
                or self.evidence_start_timestamp_us != self.timestamp_us
                or self.evidence_end_timestamp_us != self.timestamp_us
                or self.evidence_start_frame_index != self.source_frame_index
                or self.evidence_end_frame_index != self.source_frame_index
            ):
                raise ValueError("observed ball evidence must identify one source frame")
        else:
            if self.source_timestamp_us is not None or self.source_frame_index is not None:
                raise ValueError("interpolated ball evidence cannot claim a source frame")
            if not (
                self.evidence_start_timestamp_us
                < self.timestamp_us
                < self.evidence_end_timestamp_us
                and self.evidence_start_frame_index < self.evidence_end_frame_index
            ):
                raise ValueError("interpolated ball evidence requires ordered real endpoints")


@dataclass(frozen=True, slots=True)
class FloorEstimate:
    point_m: tuple[float, float]
    uncertainty_m: float
    calibration_revision: str
    calibration_provenance: str

    def __post_init__(self) -> None:
        if not _finite(*self.point_m, self.uncertainty_m):
            raise ValueError("floor estimate values must be finite")
        if self.uncertainty_m < 0:
            raise ValueError("floor uncertainty must be nonnegative")
        if not self.calibration_revision or not self.calibration_provenance:
            raise ValueError("floor estimate requires calibration provenance")


@dataclass(frozen=True, slots=True)
class PlayerObservation:
    player_id: str
    timestamp_us: int
    source_timestamp_us: int | None
    source_frame_index: int | None
    box: BoundingBox
    keypoints: tuple[Keypoint, ...]
    detection_confidence: float
    appearance: tuple[float, ...]
    feet: tuple[float, float]
    feet_uncertainty_px: float
    evidence: EvidenceKind
    evidence_start_timestamp_us: int
    evidence_end_timestamp_us: int
    evidence_start_frame_index: int
    evidence_end_frame_index: int
    association_confidence: float
    ambiguous: bool
    ambiguity_reason: str | None
    floor: FloorEstimate | None
    source_manifest_id: str
    model_manifest_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "keypoints", tuple(self.keypoints))
        object.__setattr__(self, "appearance", tuple(float(v) for v in self.appearance))
        object.__setattr__(self, "evidence", EvidenceKind(self.evidence))
        if self.player_id not in {"A", "B"}:
            raise ValueError("player identity must be A or B")
        if len(self.keypoints) != COCO_KEYPOINT_COUNT:
            raise ValueError("player observation must contain 17 COCO keypoints")
        if len(self.appearance) != APPEARANCE_DIMENSION:
            raise ValueError(
                f"appearance embedding must contain {APPEARANCE_DIMENSION} values"
            )
        required_source_values = (
            self.timestamp_us,
            self.evidence_start_timestamp_us,
            self.evidence_end_timestamp_us,
            self.evidence_start_frame_index,
            self.evidence_end_frame_index,
        )
        optional_source_values = (self.source_timestamp_us, self.source_frame_index)
        if min(required_source_values) < 0 or any(
            value is not None and value < 0 for value in optional_source_values
        ):
            raise ValueError("observation source values must be nonnegative")
        if self.evidence is EvidenceKind.OBSERVED:
            if self.source_timestamp_us is None or self.source_frame_index is None:
                raise ValueError("observed evidence requires a real source frame and timestamp")
            if (
                self.source_timestamp_us != self.timestamp_us
                or self.evidence_start_timestamp_us != self.timestamp_us
                or self.evidence_end_timestamp_us != self.timestamp_us
                or self.evidence_start_frame_index != self.source_frame_index
                or self.evidence_end_frame_index != self.source_frame_index
            ):
                raise ValueError("observed source provenance must identify the same frame")
        elif self.source_timestamp_us is not None or self.source_frame_index is not None:
            raise ValueError("interpolated evidence cannot claim a real source frame")
        if self.evidence_start_timestamp_us > self.timestamp_us:
            raise ValueError("evidence start cannot follow observation")
        if self.evidence_end_timestamp_us < self.timestamp_us:
            raise ValueError("evidence end cannot precede observation")
        if self.evidence is EvidenceKind.INTERPOLATED and not (
            self.evidence_start_timestamp_us
            < self.timestamp_us
            < self.evidence_end_timestamp_us
            and self.evidence_start_frame_index < self.evidence_end_frame_index
        ):
            raise ValueError("interpolated evidence requires ordered real endpoints")
        if not _finite(
            self.detection_confidence,
            *self.appearance,
            *self.feet,
            self.feet_uncertainty_px,
            self.association_confidence,
        ):
            raise ValueError("player observation values must be finite")
        if not 0.0 <= self.detection_confidence <= 1.0:
            raise ValueError("detection confidence must be between zero and one")
        if not 0.0 <= self.association_confidence <= 1.0:
            raise ValueError("association confidence must be between zero and one")
        if self.feet_uncertainty_px < 0:
            raise ValueError("feet uncertainty must be nonnegative")
        if self.ambiguous != (self.ambiguity_reason is not None):
            raise ValueError("ambiguity flag and reason must agree")
        if not self.source_manifest_id or not self.model_manifest_id:
            raise ValueError("observation requires source and model manifest identifiers")


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    path: Path
    artifact_kind: str
    schema_version: int
    row_count: int
    min_timestamp_us: int | None
    max_timestamp_us: int | None
    byte_size: int
    sha256: str


_SCHEMA = pa.schema(
    [
        pa.field("player_id", pa.string(), nullable=False),
        pa.field("timestamp_us", pa.int64(), nullable=False),
        pa.field("source_timestamp_us", pa.int64()),
        pa.field("source_frame_index", pa.int64()),
        pa.field("box_x1", pa.float64(), nullable=False),
        pa.field("box_y1", pa.float64(), nullable=False),
        pa.field("box_x2", pa.float64(), nullable=False),
        pa.field("box_y2", pa.float64(), nullable=False),
        pa.field("keypoints_x", pa.list_(pa.float64(), COCO_KEYPOINT_COUNT), nullable=False),
        pa.field("keypoints_y", pa.list_(pa.float64(), COCO_KEYPOINT_COUNT), nullable=False),
        pa.field("keypoints_confidence", pa.list_(pa.float64(), COCO_KEYPOINT_COUNT), nullable=False),
        pa.field("detection_confidence", pa.float64(), nullable=False),
        pa.field(
            "appearance",
            pa.list_(pa.float64(), APPEARANCE_DIMENSION),
            nullable=False,
        ),
        pa.field("feet_x", pa.float64(), nullable=False),
        pa.field("feet_y", pa.float64(), nullable=False),
        pa.field("feet_uncertainty_px", pa.float64(), nullable=False),
        pa.field("evidence", pa.string(), nullable=False),
        pa.field("evidence_start_timestamp_us", pa.int64(), nullable=False),
        pa.field("evidence_end_timestamp_us", pa.int64(), nullable=False),
        pa.field("evidence_start_frame_index", pa.int64(), nullable=False),
        pa.field("evidence_end_frame_index", pa.int64(), nullable=False),
        pa.field("association_confidence", pa.float64(), nullable=False),
        pa.field("ambiguous", pa.bool_(), nullable=False),
        pa.field("ambiguity_reason", pa.string()),
        pa.field("floor_x_m", pa.float64()),
        pa.field("floor_y_m", pa.float64()),
        pa.field("floor_uncertainty_m", pa.float64()),
        pa.field("calibration_revision", pa.string()),
        pa.field("calibration_provenance", pa.string()),
        pa.field("source_manifest_id", pa.string(), nullable=False),
        pa.field("model_manifest_id", pa.string(), nullable=False),
    ]
)
_REQUIRED_METADATA = {
    b"artifact_kind",
    b"schema_version",
    b"coordinate_conventions",
    b"row_count",
    b"min_timestamp_us",
    b"max_timestamp_us",
    b"source_manifest_id",
    b"model_manifest_id",
}


def _row_dict(row: PlayerObservation) -> dict[str, object]:
    floor = row.floor
    return {
        "player_id": row.player_id,
        "timestamp_us": row.timestamp_us,
        "source_timestamp_us": row.source_timestamp_us,
        "source_frame_index": row.source_frame_index,
        "box_x1": row.box.x1,
        "box_y1": row.box.y1,
        "box_x2": row.box.x2,
        "box_y2": row.box.y2,
        "keypoints_x": [point.x for point in row.keypoints],
        "keypoints_y": [point.y for point in row.keypoints],
        "keypoints_confidence": [point.confidence for point in row.keypoints],
        "detection_confidence": row.detection_confidence,
        "appearance": list(row.appearance),
        "feet_x": row.feet[0],
        "feet_y": row.feet[1],
        "feet_uncertainty_px": row.feet_uncertainty_px,
        "evidence": row.evidence.value,
        "evidence_start_timestamp_us": row.evidence_start_timestamp_us,
        "evidence_end_timestamp_us": row.evidence_end_timestamp_us,
        "evidence_start_frame_index": row.evidence_start_frame_index,
        "evidence_end_frame_index": row.evidence_end_frame_index,
        "association_confidence": row.association_confidence,
        "ambiguous": row.ambiguous,
        "ambiguity_reason": row.ambiguity_reason,
        "floor_x_m": None if floor is None else floor.point_m[0],
        "floor_y_m": None if floor is None else floor.point_m[1],
        "floor_uncertainty_m": None if floor is None else floor.uncertainty_m,
        "calibration_revision": None if floor is None else floor.calibration_revision,
        "calibration_provenance": None if floor is None else floor.calibration_provenance,
        "source_manifest_id": row.source_manifest_id,
        "model_manifest_id": row.model_manifest_id,
    }


def _single_manifest(rows: tuple[PlayerObservation, ...], field: str) -> str:
    values = {getattr(row, field) for row in rows}
    if len(values) > 1:
        raise ValueError(f"all rows must share one {field}")
    return next(iter(values), "")


def _required_manifest(
    rows: tuple[PlayerObservation, ...], field: str, explicit: str | None
) -> str:
    row_value = _single_manifest(rows, field)
    if explicit is not None and row_value and explicit != row_value:
        raise ValueError(f"explicit {field} does not match observation rows")
    value = explicit if explicit is not None else row_value
    if not value or not value.strip():
        raise ValueError(f"a nonempty {field} manifest identifier is required")
    return value


def write_player_observations(
    path: Path,
    rows: Iterable[PlayerObservation],
    *,
    source_manifest_id: str | None = None,
    model_manifest_id: str | None = None,
) -> ArtifactInfo:
    destination = Path(path)
    materialized = tuple(rows)
    timestamps = tuple(row.timestamp_us for row in materialized)
    if any(current < previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("observation timestamps must be ordered")
    source_manifest = _required_manifest(
        materialized, "source_manifest_id", source_manifest_id
    )
    model_manifest = _required_manifest(
        materialized, "model_manifest_id", model_manifest_id
    )
    minimum = min(timestamps) if timestamps else None
    maximum = max(timestamps) if timestamps else None
    metadata = {
        b"artifact_kind": ARTIFACT_KIND.encode(),
        b"schema_version": str(SCHEMA_VERSION).encode(),
        b"coordinate_conventions": COORDINATE_CONVENTIONS.encode(),
        b"row_count": str(len(materialized)).encode(),
        b"min_timestamp_us": ("" if minimum is None else str(minimum)).encode(),
        b"max_timestamp_us": ("" if maximum is None else str(maximum)).encode(),
        b"source_manifest_id": source_manifest.encode(),
        b"model_manifest_id": model_manifest.encode(),
    }
    table = pa.Table.from_pylist(
        [_row_dict(row) for row in materialized], schema=_SCHEMA
    ).replace_schema_metadata(metadata)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        pq.write_table(table, temporary, compression="zstd")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    payload = destination.read_bytes()
    return ArtifactInfo(
        path=destination,
        artifact_kind=ARTIFACT_KIND,
        schema_version=SCHEMA_VERSION,
        row_count=len(materialized),
        min_timestamp_us=minimum,
        max_timestamp_us=maximum,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _validate_metadata(table: pa.Table) -> dict[bytes, bytes]:
    metadata = table.schema.metadata or {}
    missing = _REQUIRED_METADATA.difference(metadata)
    if missing:
        raise ValueError("player observation Parquet is missing required schema metadata")
    if metadata[b"artifact_kind"] != ARTIFACT_KIND.encode():
        raise ValueError("wrong player observation artifact kind")
    if metadata[b"schema_version"] != str(SCHEMA_VERSION).encode():
        raise ValueError("unsupported player observation schema version")
    if metadata[b"coordinate_conventions"] != COORDINATE_CONVENTIONS.encode():
        raise ValueError("wrong player observation coordinate conventions")
    if int(metadata[b"row_count"]) != table.num_rows:
        raise ValueError("player observation row count metadata mismatch")
    if not metadata[b"source_manifest_id"].decode().strip() or not metadata[
        b"model_manifest_id"
    ].decode().strip():
        raise ValueError("player observation Parquet contains blank manifest metadata")
    return metadata


def _floor_from_dict(item: dict[str, object]) -> FloorEstimate | None:
    values = (
        item["floor_x_m"],
        item["floor_y_m"],
        item["floor_uncertainty_m"],
        item["calibration_revision"],
        item["calibration_provenance"],
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("partial floor estimate in player observation Parquet")
    return FloorEstimate(
        point_m=(float(values[0]), float(values[1])),
        uncertainty_m=float(values[2]),
        calibration_revision=str(values[3]),
        calibration_provenance=str(values[4]),
    )


def _observation_from_dict(item: dict[str, object]) -> PlayerObservation:
    try:
        keypoints = tuple(
            Keypoint(float(x), float(y), float(confidence))
            for x, y, confidence in zip(
                item["keypoints_x"],
                item["keypoints_y"],
                item["keypoints_confidence"],
                strict=True,
            )
        )
        return PlayerObservation(
            player_id=str(item["player_id"]),
            timestamp_us=int(item["timestamp_us"]),
            source_timestamp_us=(
                None
                if item["source_timestamp_us"] is None
                else int(item["source_timestamp_us"])
            ),
            source_frame_index=(
                None
                if item["source_frame_index"] is None
                else int(item["source_frame_index"])
            ),
            box=BoundingBox(
                float(item["box_x1"]),
                float(item["box_y1"]),
                float(item["box_x2"]),
                float(item["box_y2"]),
            ),
            keypoints=keypoints,
            detection_confidence=float(item["detection_confidence"]),
            appearance=tuple(float(value) for value in item["appearance"]),
            feet=(float(item["feet_x"]), float(item["feet_y"])),
            feet_uncertainty_px=float(item["feet_uncertainty_px"]),
            evidence=EvidenceKind(str(item["evidence"])),
            evidence_start_timestamp_us=int(item["evidence_start_timestamp_us"]),
            evidence_end_timestamp_us=int(item["evidence_end_timestamp_us"]),
            evidence_start_frame_index=int(item["evidence_start_frame_index"]),
            evidence_end_frame_index=int(item["evidence_end_frame_index"]),
            association_confidence=float(item["association_confidence"]),
            ambiguous=bool(item["ambiguous"]),
            ambiguity_reason=(
                None if item["ambiguity_reason"] is None else str(item["ambiguity_reason"])
            ),
            floor=_floor_from_dict(item),
            source_manifest_id=str(item["source_manifest_id"]),
            model_manifest_id=str(item["model_manifest_id"]),
        )
    except (TypeError, ValueError, OverflowError) as error:
        message = str(error)
        if "finite" in message:
            raise ValueError("nonfinite required value in player observation Parquet") from error
        raise ValueError(f"invalid player observation Parquet row: {message}") from error


def read_player_observations(path: Path) -> tuple[PlayerObservation, ...]:
    table = pq.read_table(Path(path))
    metadata = _validate_metadata(table)
    if table.schema.remove_metadata() != _SCHEMA:
        raise ValueError("player observation Parquet column schema does not match")
    rows = tuple(_observation_from_dict(item) for item in table.to_pylist())
    timestamps = tuple(row.timestamp_us for row in rows)
    if any(current < previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("invalid unordered timestamps in player observation Parquet")
    minimum = "" if not timestamps else str(min(timestamps))
    maximum = "" if not timestamps else str(max(timestamps))
    if metadata[b"min_timestamp_us"].decode() != minimum or metadata[
        b"max_timestamp_us"
    ].decode() != maximum:
        raise ValueError("player observation timestamp metadata mismatch")
    if any(row.source_manifest_id != metadata[b"source_manifest_id"].decode() for row in rows):
        raise ValueError("source manifest metadata mismatch")
    if any(row.model_manifest_id != metadata[b"model_manifest_id"].decode() for row in rows):
        raise ValueError("model manifest metadata mismatch")
    return rows


_BALL_ARTIFACT_KIND = "ball_observations"
_BALL_SCHEMA_VERSION = 1
_BALL_COORDINATE_CONVENTIONS = "image_bgr_pixels_xy_covariance"
_BALL_COVARIANCE_TYPE = pa.struct(
    [
        pa.field("xx", pa.float64(), nullable=False),
        pa.field("xy", pa.float64(), nullable=False),
        pa.field("yx", pa.float64(), nullable=False),
        pa.field("yy", pa.float64(), nullable=False),
    ]
)
_BALL_CANDIDATE_TYPE = pa.struct(
    [
        pa.field("x", pa.float64(), nullable=False),
        pa.field("y", pa.float64(), nullable=False),
        pa.field("peak_probability", pa.float64(), nullable=False),
        pa.field("integrated_probability", pa.float64(), nullable=False),
        pa.field("area", pa.int32(), nullable=False),
        pa.field("circularity", pa.float64(), nullable=False),
        pa.field("covariance_xx", pa.float64(), nullable=False),
        pa.field("covariance_xy", pa.float64(), nullable=False),
        pa.field("covariance_yx", pa.float64(), nullable=False),
        pa.field("covariance_yy", pa.float64(), nullable=False),
    ]
)
_BALL_SCHEMA = pa.schema(
    [
        pa.field("timestamp_us", pa.int64(), nullable=False),
        pa.field("source_timestamp_us", pa.int64()),
        pa.field("source_frame_index", pa.int64()),
        pa.field("source_width", pa.int32(), nullable=False),
        pa.field("source_height", pa.int32(), nullable=False),
        pa.field("x", pa.float64()),
        pa.field("y", pa.float64()),
        pa.field("probability", pa.float64(), nullable=False),
        pa.field("covariance", _BALL_COVARIANCE_TYPE),
        pa.field("visible", pa.bool_(), nullable=False),
        pa.field("candidate_count", pa.int32(), nullable=False),
        pa.field(
            "candidates",
            pa.list_(_BALL_CANDIDATE_TYPE, BALL_MAX_CANDIDATES),
            nullable=False,
        ),
        pa.field("evidence", pa.string(), nullable=False),
        pa.field("evidence_start_timestamp_us", pa.int64(), nullable=False),
        pa.field("evidence_end_timestamp_us", pa.int64(), nullable=False),
        pa.field("evidence_start_frame_index", pa.int64(), nullable=False),
        pa.field("evidence_end_frame_index", pa.int64(), nullable=False),
        pa.field("ambiguous", pa.bool_(), nullable=False),
        pa.field("ambiguity_reason", pa.string()),
        pa.field("segment_id", pa.string()),
        pa.field("source_manifest_id", pa.string(), nullable=False),
        pa.field("model_manifest_id", pa.string(), nullable=False),
        pa.field("device", pa.string(), nullable=False),
        pa.field("device_fallback", pa.bool_(), nullable=False),
    ]
)
_BALL_REQUIRED_METADATA = {
    b"artifact_kind",
    b"schema_version",
    b"coordinate_conventions",
    b"candidate_bound",
    b"row_count",
    b"min_timestamp_us",
    b"max_timestamp_us",
    b"source_manifest_id",
    b"model_manifest_id",
}


def _flat_covariance(
    covariance: tuple[tuple[float, float], tuple[float, float]] | None,
) -> dict[str, float] | None:
    if covariance is None:
        return None
    return {
        "xx": covariance[0][0],
        "xy": covariance[0][1],
        "yx": covariance[1][0],
        "yy": covariance[1][1],
    }


def _ball_candidate_dict(candidate: BallCandidate) -> dict[str, object]:
    return {
        "x": candidate.x,
        "y": candidate.y,
        "peak_probability": candidate.peak_probability,
        "integrated_probability": candidate.integrated_probability,
        "area": candidate.area,
        "circularity": candidate.circularity,
        "covariance_xx": candidate.covariance[0][0],
        "covariance_xy": candidate.covariance[0][1],
        "covariance_yx": candidate.covariance[1][0],
        "covariance_yy": candidate.covariance[1][1],
    }


def _ball_row_dict(row: BallObservation) -> dict[str, object]:
    candidates: list[dict[str, object] | None] = [
        _ball_candidate_dict(candidate) for candidate in row.candidates
    ]
    candidates.extend([None] * (BALL_MAX_CANDIDATES - len(candidates)))
    return {
        "timestamp_us": row.timestamp_us,
        "source_timestamp_us": row.source_timestamp_us,
        "source_frame_index": row.source_frame_index,
        "source_width": row.source_width,
        "source_height": row.source_height,
        "x": row.x,
        "y": row.y,
        "probability": row.probability,
        "covariance": _flat_covariance(row.covariance),
        "visible": row.visible,
        "candidate_count": row.candidate_count,
        "candidates": candidates,
        "evidence": row.evidence.value,
        "evidence_start_timestamp_us": row.evidence_start_timestamp_us,
        "evidence_end_timestamp_us": row.evidence_end_timestamp_us,
        "evidence_start_frame_index": row.evidence_start_frame_index,
        "evidence_end_frame_index": row.evidence_end_frame_index,
        "ambiguous": row.ambiguous,
        "ambiguity_reason": row.ambiguity_reason,
        "segment_id": row.segment_id,
        "source_manifest_id": row.source_manifest_id,
        "model_manifest_id": row.model_manifest_id,
        "device": row.device,
        "device_fallback": row.device_fallback,
    }


def _validate_ball_order(rows: tuple[BallObservation, ...]) -> None:
    timestamps = tuple(row.timestamp_us for row in rows)
    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("ball observation timestamps must be strictly ordered")
    source_rows = tuple(row for row in rows if row.source_frame_index is not None)
    source_timestamps = tuple(int(row.source_timestamp_us) for row in source_rows)
    source_indices = tuple(int(row.source_frame_index) for row in source_rows)
    if any(
        current <= previous
        for previous, current in zip(source_timestamps, source_timestamps[1:])
    ) or any(
        current <= previous for previous, current in zip(source_indices, source_indices[1:])
    ):
        raise ValueError("ball observations contain unordered source provenance")


def write_ball_observations(
    path: Path,
    rows: Iterable[BallObservation],
    *,
    source_manifest_id: str | None = None,
    model_manifest_id: str | None = None,
) -> ArtifactInfo:
    destination = Path(path)
    materialized = tuple(rows)
    _validate_ball_order(materialized)
    source_manifest = _required_manifest(
        materialized, "source_manifest_id", source_manifest_id
    )
    model_manifest = _required_manifest(
        materialized, "model_manifest_id", model_manifest_id
    )
    timestamps = tuple(row.timestamp_us for row in materialized)
    minimum = min(timestamps) if timestamps else None
    maximum = max(timestamps) if timestamps else None
    metadata = {
        b"artifact_kind": _BALL_ARTIFACT_KIND.encode(),
        b"schema_version": str(_BALL_SCHEMA_VERSION).encode(),
        b"coordinate_conventions": _BALL_COORDINATE_CONVENTIONS.encode(),
        b"candidate_bound": str(BALL_MAX_CANDIDATES).encode(),
        b"row_count": str(len(materialized)).encode(),
        b"min_timestamp_us": ("" if minimum is None else str(minimum)).encode(),
        b"max_timestamp_us": ("" if maximum is None else str(maximum)).encode(),
        b"source_manifest_id": source_manifest.encode(),
        b"model_manifest_id": model_manifest.encode(),
    }
    table = pa.Table.from_pylist(
        [_ball_row_dict(row) for row in materialized], schema=_BALL_SCHEMA
    ).replace_schema_metadata(metadata)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        pq.write_table(table, temporary, compression="zstd")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    payload = destination.read_bytes()
    return ArtifactInfo(
        path=destination,
        artifact_kind=_BALL_ARTIFACT_KIND,
        schema_version=_BALL_SCHEMA_VERSION,
        row_count=len(materialized),
        min_timestamp_us=minimum,
        max_timestamp_us=maximum,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _covariance_from_list(
    values: object,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if values is None:
        return None
    if not isinstance(values, dict) or set(values) != {"xx", "xy", "yx", "yy"}:
        raise ValueError("ball covariance must contain exact xx/xy/yx/yy values")
    return (
        (float(values["xx"]), float(values["xy"])),
        (float(values["yx"]), float(values["yy"])),
    )


def _ball_candidate_from_dict(item: dict[str, object]) -> BallCandidate:
    return BallCandidate(
        x=float(item["x"]),
        y=float(item["y"]),
        peak_probability=float(item["peak_probability"]),
        integrated_probability=float(item["integrated_probability"]),
        area=int(item["area"]),
        circularity=float(item["circularity"]),
        covariance=(
            (float(item["covariance_xx"]), float(item["covariance_xy"])),
            (float(item["covariance_yx"]), float(item["covariance_yy"])),
        ),
    )


def _ball_observation_from_dict(item: dict[str, object]) -> BallObservation:
    try:
        candidate_count = int(item["candidate_count"])
        slots = tuple(item["candidates"])
        if len(slots) != BALL_MAX_CANDIDATES:
            raise ValueError("ball candidate slots do not match fixed candidate bound")
        if candidate_count < 0:
            raise ValueError("ball candidate count must be nonnegative")
        populated_count = next(
            (
                index
                for index, slot in enumerate(slots)
                if slot is None
            ),
            BALL_MAX_CANDIDATES,
        )
        if any(slot is not None for slot in slots[populated_count:]):
            raise ValueError("ball candidate slots contain a hole")
        if candidate_count < populated_count:
            raise ValueError("ball candidate count is smaller than candidate evidence")
        if populated_count != min(candidate_count, BALL_MAX_CANDIDATES):
            raise ValueError(
                "ball observation requires complete bounded candidate evidence"
            )
        candidates = tuple(
            _ball_candidate_from_dict(slot)
            for slot in slots[:populated_count]
            if slot is not None
        )
        return BallObservation(
            timestamp_us=int(item["timestamp_us"]),
            source_timestamp_us=(
                None
                if item["source_timestamp_us"] is None
                else int(item["source_timestamp_us"])
            ),
            source_frame_index=(
                None
                if item["source_frame_index"] is None
                else int(item["source_frame_index"])
            ),
            source_width=int(item["source_width"]),
            source_height=int(item["source_height"]),
            x=None if item["x"] is None else float(item["x"]),
            y=None if item["y"] is None else float(item["y"]),
            probability=float(item["probability"]),
            covariance=_covariance_from_list(item["covariance"]),
            visible=bool(item["visible"]),
            candidate_count=candidate_count,
            candidates=candidates,
            evidence=EvidenceKind(str(item["evidence"])),
            evidence_start_timestamp_us=int(item["evidence_start_timestamp_us"]),
            evidence_end_timestamp_us=int(item["evidence_end_timestamp_us"]),
            evidence_start_frame_index=int(item["evidence_start_frame_index"]),
            evidence_end_frame_index=int(item["evidence_end_frame_index"]),
            ambiguous=bool(item["ambiguous"]),
            ambiguity_reason=(
                None if item["ambiguity_reason"] is None else str(item["ambiguity_reason"])
            ),
            segment_id=None if item["segment_id"] is None else str(item["segment_id"]),
            source_manifest_id=str(item["source_manifest_id"]),
            model_manifest_id=str(item["model_manifest_id"]),
            device=str(item["device"]),
            device_fallback=bool(item["device_fallback"]),
        )
    except (TypeError, ValueError, OverflowError) as error:
        if "finite" in str(error):
            raise ValueError("nonfinite value in ball observation Parquet") from error
        raise ValueError(f"invalid ball observation Parquet row: {error}") from error


def read_ball_observations(path: Path) -> tuple[BallObservation, ...]:
    table = pq.read_table(Path(path))
    metadata = table.schema.metadata or {}
    if _BALL_REQUIRED_METADATA.difference(metadata):
        raise ValueError("ball observation Parquet is missing required schema metadata")
    if metadata[b"artifact_kind"] != _BALL_ARTIFACT_KIND.encode():
        raise ValueError("wrong ball observation artifact kind")
    if metadata[b"schema_version"] != str(_BALL_SCHEMA_VERSION).encode():
        raise ValueError("unsupported ball observation schema version")
    if metadata[b"coordinate_conventions"] != _BALL_COORDINATE_CONVENTIONS.encode():
        raise ValueError("wrong ball observation coordinate conventions")
    if metadata[b"candidate_bound"] != str(BALL_MAX_CANDIDATES).encode():
        raise ValueError("wrong ball observation candidate bound")
    if table.schema.remove_metadata() != _BALL_SCHEMA:
        raise ValueError("ball observation Parquet column schema does not match")
    if int(metadata[b"row_count"]) != table.num_rows:
        raise ValueError("ball observation row count metadata mismatch")
    if not metadata[b"source_manifest_id"].decode().strip() or not metadata[
        b"model_manifest_id"
    ].decode().strip():
        raise ValueError("ball observation Parquet contains blank manifest metadata")
    rows = tuple(_ball_observation_from_dict(item) for item in table.to_pylist())
    _validate_ball_order(rows)
    timestamps = tuple(row.timestamp_us for row in rows)
    minimum = "" if not timestamps else str(min(timestamps))
    maximum = "" if not timestamps else str(max(timestamps))
    if (
        metadata[b"min_timestamp_us"].decode() != minimum
        or metadata[b"max_timestamp_us"].decode() != maximum
    ):
        raise ValueError("ball observation timestamp metadata mismatch")
    source_manifest = metadata[b"source_manifest_id"].decode()
    model_manifest = metadata[b"model_manifest_id"].decode()
    if any(row.source_manifest_id != source_manifest for row in rows):
        raise ValueError("ball source manifest metadata mismatch")
    if any(row.model_manifest_id != model_manifest for row in rows):
        raise ValueError("ball model manifest metadata mismatch")
    return rows


__all__ = [
    "APPEARANCE_DIMENSION",
    "BALL_MAX_CANDIDATES",
    "ArtifactInfo",
    "BallCandidate",
    "BallObservation",
    "BoundingBox",
    "EvidenceKind",
    "FloorEstimate",
    "Frame",
    "FrameBatch",
    "Keypoint",
    "PlayerObservation",
    "PoseDetection",
    "PoseDetections",
    "read_ball_observations",
    "read_player_observations",
    "write_ball_observations",
    "write_player_observations",
]
