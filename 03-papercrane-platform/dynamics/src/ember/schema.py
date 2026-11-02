"""Small, strict contracts shared by ingestion, inference and evaluation.

All residue indices are ZERO-BASED positions in the full submitted sequence.
Author numbering belongs in residue mappings and is never used as an array index.
Reference records are deliberately a separate type and artifact.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, TypeVar

PARTITIONS = frozenset({"train", "development", "test", "external"})
STATUSES = frozenset({"ok", "static_fallback", "no_candidates", "failed", "unsupported"})
AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
T = TypeVar("T")


def require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def require_hash(value: str, name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def require_indices(values: tuple[int, ...], name: str, length: int | None = None) -> None:
    if not values or any(type(i) is not int or i < 0 for i in values):
        raise ValueError(f"{name} must contain nonnegative integer indices")
    if tuple(sorted(set(values))) != tuple(values):
        raise ValueError(f"{name} must be sorted and unique")
    if length is not None and values[-1] >= length:
        raise ValueError(f"{name} exceeds sequence length {length}")


def finite(value: float, name: str, nonnegative: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")


@dataclass(frozen=True)
class Target:
    target_id: str
    sequence: str
    source: str
    release_sha256: str
    apo_path: str
    apo_sha256: str
    model_id: int
    chain_id: str
    assembly_id: str
    group_id: str
    partition: str
    eligible: bool
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("target_id", "source", "apo_path", "assembly_id", "group_id"):
            require_text(getattr(self, name), name)
        # A blank PDB author chain is legitimate, but must be explicitly supplied.
        if not isinstance(self.chain_id, str):
            raise ValueError("chain_id must be explicitly supplied text")
        if type(self.model_id) is not int or self.model_id < 0:
            raise ValueError("model_id is a zero-based nonnegative model index")
        require_hash(self.release_sha256, "release_sha256")
        require_hash(self.apo_sha256, "apo_sha256")
        if not self.sequence or set(self.sequence) - AMINO_ACIDS:
            raise ValueError("v0 requires an uppercase sequence of the 20 standard amino acids")
        if self.partition not in PARTITIONS:
            raise ValueError(f"Invalid partition: {self.partition}")
        if type(self.eligible) is not bool:
            raise ValueError("eligible must be boolean")
        if self.eligible and self.exclusion_reason is not None:
            raise ValueError("Eligible target cannot have an exclusion reason")
        if not self.eligible:
            require_text(self.exclusion_reason, "exclusion_reason")


@dataclass(frozen=True)
class ResidueID:
    chain: str
    number: int
    insertion_code: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.chain, str) or type(self.number) is not int:
            raise ValueError("Author chain and integer residue number required")
        if not isinstance(self.insertion_code, str) or len(self.insertion_code) > 1:
            raise ValueError("PDB insertion code must be at most one character")


@dataclass(frozen=True)
class Observation:
    observation_id: str
    frame_id: str
    source: str
    residues: tuple[int, ...]
    center: tuple[float, float, float]
    detector_score: float
    volume: float | None = None
    druggability: float | None = None
    sasa: float | None = None
    enclosure: float | None = None
    quality: float | None = None
    structure_path: str | None = None

    def __post_init__(self) -> None:
        require_text(self.observation_id, "observation_id")
        require_text(self.frame_id, "frame_id")
        if self.source not in {"apo", "ensemble", "surface"}:
            raise ValueError(f"Invalid observation source: {self.source}")
        require_indices(self.residues, "observation residues")
        if len(self.center) != 3:
            raise ValueError("Pocket center requires three coordinates in angstroms")
        for coord in self.center:
            finite(coord, "center coordinate")
        finite(self.detector_score, "detector_score")
        for name in ("volume", "druggability", "sasa", "enclosure", "quality"):
            value = getattr(self, name)
            if value is not None:
                finite(value, name, nonnegative=name in {"volume", "sasa"})


@dataclass(frozen=True)
class Site:
    site_id: str
    residues: tuple[int, ...]
    observations: tuple[Observation, ...]
    medoid_observation_id: str

    def __post_init__(self) -> None:
        require_text(self.site_id, "site_id")
        require_indices(self.residues, "site residues")
        if not self.observations:
            raise ValueError("A site requires observations")
        unique_ids(self.observations, "observation_id")
        medoids = [o for o in self.observations if o.observation_id == self.medoid_observation_id]
        if len(medoids) != 1 or medoids[0].residues != self.residues:
            raise ValueError("Site residues must equal its medoid observation")


@dataclass(frozen=True)
class RankedSite:
    site_id: str
    residues: tuple[int, ...]
    score: float
    evidence: str
    representative_observation_id: str | None = None
    representative_path: str | None = None

    def __post_init__(self) -> None:
        require_text(self.site_id, "site_id")
        require_indices(self.residues, "prediction residues")
        finite(self.score, "site score")
        if self.evidence not in {"apo", "ensemble", "static_fallback", "sequence"}:
            raise ValueError("Unknown evidence type")
        if self.representative_path is not None and self.representative_observation_id is None:
            raise ValueError("Representative path requires observation identity")


@dataclass(frozen=True)
class Prediction:
    target_id: str
    method_id: str
    status: str
    sites: tuple[RankedSite, ...]
    input_sha256: str
    method_sha256: str
    requested_frames: int = 0
    valid_frames: int = 0
    runtime_seconds: float | None = None
    cost_usd: float | None = None
    failure_reason: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.target_id, "target_id")
        require_text(self.method_id, "method_id")
        require_hash(self.input_sha256, "input_sha256")
        require_hash(self.method_sha256, "method_sha256")
        if self.status not in STATUSES:
            raise ValueError(f"Unknown prediction status: {self.status}")
        unique_ids(self.sites, "site_id")
        if self.status in {"failed", "unsupported", "no_candidates"} and self.sites:
            raise ValueError("Unsuccessful output cannot contain scored sites")
        if self.status in {"ok", "static_fallback"} and not self.sites:
            raise ValueError("Successful output needs at least one site")
        if self.status in {"failed", "unsupported", "static_fallback"}:
            require_text(self.failure_reason, "failure_reason")
        elif self.failure_reason is not None:
            raise ValueError("Failure reason contradicts prediction status")
        if (
            type(self.requested_frames) is not int
            or type(self.valid_frames) is not int
            or not 0 <= self.valid_frames <= self.requested_frames
        ):
            raise ValueError("Frame counts must satisfy 0 <= valid <= requested")
        if self.status == "static_fallback" and self.valid_frames != 0:
            raise ValueError("Static fallback cannot claim valid ensemble frames")
        if any(s.evidence == "ensemble" for s in self.sites) and self.valid_frames == 0:
            raise ValueError("Ensemble evidence requires valid ensemble frames")
        for name in ("runtime_seconds", "cost_usd"):
            value = getattr(self, name)
            if value is not None:
                finite(value, name, nonnegative=True)


@dataclass(frozen=True)
class ReferenceSite:
    site_id: str
    residues: tuple[int, ...]

    def __post_init__(self) -> None:
        require_text(self.site_id, "reference site_id")
        require_indices(self.residues, "reference residues")


@dataclass(frozen=True)
class Reference:
    target_id: str
    sites: tuple[ReferenceSite, ...]
    source_sha256: str
    valid: bool = True
    invalid_reason: str | None = None
    residue_labels: tuple[int, ...] | None = None
    residue_label_mask: tuple[bool, ...] | None = None

    def __post_init__(self) -> None:
        require_text(self.target_id, "reference target_id")
        require_hash(self.source_sha256, "reference source_sha256")
        unique_ids(self.sites, "site_id")
        if type(self.valid) is not bool:
            raise ValueError("reference valid must be boolean")
        if self.valid and self.invalid_reason is not None:
            raise ValueError("Valid reference cannot have invalid_reason")
        if not self.valid:
            require_text(self.invalid_reason, "invalid_reason")
        if (self.residue_labels is None) != (self.residue_label_mask is None):
            raise ValueError("Residue labels and mask must be supplied together")
        if self.residue_labels is not None:
            if len(self.residue_labels) != len(self.residue_label_mask):
                raise ValueError("Residue labels and masks must have equal length")
            if any(type(x) is not int or x not in (0, 1) for x in self.residue_labels):
                raise ValueError("Residue labels must be binary integers")
            if any(type(x) is not bool for x in self.residue_label_mask):
                raise ValueError("Residue label mask must be boolean")


def unique_ids(records, field_name: str) -> None:
    values = [getattr(record, field_name) for record in records]
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {field_name}")


def from_dict(cls: type[T], value: Mapping[str, Any]) -> T:
    """Reject unknown fields instead of accidentally accepting reference inputs."""
    value = dict(value)
    fields = cls.__dataclass_fields__
    extra = set(value) - set(fields)
    if extra:
        raise ValueError(f"Unknown {cls.__name__} fields: {sorted(extra)}")
    if "residues" in value:
        value["residues"] = tuple(value["residues"])
    if cls is Observation:
        value["center"] = tuple(value["center"])
    if cls is Site:
        value["observations"] = tuple(from_dict(Observation, x) for x in value["observations"])
    if cls in (Prediction, Reference):
        child = RankedSite if cls is Prediction else ReferenceSite
        value["sites"] = tuple(from_dict(child, x) for x in value["sites"])
    for name in ("warnings", "residue_labels", "residue_label_mask"):
        if name in value and value[name] is not None:
            value[name] = tuple(value[name])
    return cls(**value)


def to_dict(record) -> dict:
    return asdict(record)


def validate_targets(targets: list[Target]) -> None:
    unique_ids(targets, "target_id")
    groups: dict[str, set[str]] = {}
    sequences: dict[str, set[str]] = {}
    for target in targets:
        groups.setdefault(target.group_id, set()).add(target.partition)
        sequences.setdefault(target.sequence, set()).add(target.partition)
    if any(len(parts) > 1 for parts in groups.values()):
        raise ValueError("A relatedness group crosses partitions")
    if any(len(parts) > 1 for parts in sequences.values()):
        raise ValueError("An identical sequence crosses partitions")
