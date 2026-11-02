"""Shared interface-class taxonomy and dataclass contracts for pc_contracts."""
from dataclasses import dataclass, field
from typing import Optional

INTERFACE_CLASSES: tuple[str, ...] = (
    "helical",
    "sheet_flat",
    "mixed",
    "ligand_present",
)


@dataclass
class TargetFeatures:
    # ``hotspots`` is a mutable list; consumers must deep-copy before mutating.
    target_id: str
    pdb_id: str
    chain: str
    hotspots: Optional[list[int]]
    log_length: float
    disorder_fraction: float
    frac_helix: float
    frac_strand: float
    frac_loop: float
    epitope_planarity_rmsd: Optional[float]
    pocket_volume: Optional[float]
    druggability: Optional[float]
    epitope_hydrophobicity: Optional[float]
    epitope_net_charge: Optional[float]
    frac_polar: float
    interface_class: str

    def __post_init__(self) -> None:
        if self.interface_class not in INTERFACE_CLASSES:
            raise ValueError(
                f"interface_class must be one of {INTERFACE_CLASSES!r}; "
                f"got {self.interface_class!r}"
            )


@dataclass
class DesignRow:
    # ``metrics`` / ``metric_blocks_present`` are mutable dicts; consumers must
    # deep-copy before mutating.
    design_id: str
    target_id: str
    tool: str
    tool_version: str
    config_hash: str
    seed: int
    sequence: str
    metrics: dict[str, float]
    metric_blocks_present: dict[str, bool]
    cost_usd: float
    wallclock_sec: float


@dataclass
class LabelRow:
    design_id: str
    target_id: str
    sequence: str
    binds: Optional[bool]
    binding_strength: Optional[str]
    kd_nm: Optional[float]
    expressed: Optional[bool]
    source: str
    license: str
    provenance: str
    metric_blind_sampled: bool


_VALID_METRIC_PRIOR_SOURCES = frozenset({"llm", "corrector", "global_default"})


@dataclass
class MetricPrior:
    # ``weights`` / ``emphasized_metrics`` are mutable containers; consumers must
    # deep-copy before mutating.
    target_id: str
    weights: dict[str, float]
    emphasized_metrics: list[str]
    rationale: str
    source: str
    confidence: float

    def __post_init__(self) -> None:
        if self.source not in _VALID_METRIC_PRIOR_SOURCES:
            raise ValueError(
                f"source must be one of {sorted(_VALID_METRIC_PRIOR_SOURCES)!r}; "
                f"got {self.source!r}"
            )


@dataclass(frozen=True)
class ScoredDesign:
    # Final-ranking result object — immutable; no reason to mutate after scoring.
    design_id: str
    score: float
    rank: int
