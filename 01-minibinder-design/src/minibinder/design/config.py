"""Load the V5 design settings from a dataclass and campaign YAML.

Centralizes all tunable parameters for design_v5.py. Replaces the argparse-only
config in design_god_5g51_v4.py. Load defaults, override per-campaign via YAML.

Usage:
    from minibinder.design.config import DesignConfig
    cfg = DesignConfig.from_yaml("config/my_campaign.yaml")
    cfg.validate()

    # or build programmatically:
    cfg = DesignConfig(seed=42, target_structure="5G51.cif")"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Optional
import yaml


@dataclass
class DesignConfig:
    # ===== Campaign =====
    seed: int
    target_structure: str                        # path to target CIF (e.g., "5G51.cif")
    target_chain: str = "A"
    binder_length: int = 85

    # ===== Optimization =====
    phase1_steps: int = 160                      # v4 default (was 120 in v3b)
    phase2_steps: int = 30                       # v4 default (was 20 in v3b)
    mpnn_weight: float = 4.0                     # v4 dropped 8.0 -> 4.0 (avoid alanine repeats)
    mpnn_temperature: float = 0.1                # v4 raised 0.01 -> 0.1 (sequence diversity)
    recycling_steps_design: int = 1
    sampling_steps: int = 20
    recycling_steps_predict: int = 4             # final prediction (post-optimization)

    # ===== Loss weights =====
    # v4 values preserved for existing terms; v5 additions marked NEW.
    loss_weights: Dict[str, float] = field(default_factory=lambda: {
        "binder_target_contact":    0.8,
        "within_binder_contact":    1.2,
        "target_binder_pae":        0.2,
        "binder_target_pae":        0.2,
        "iptm":                     0.15,
        "within_binder_pae":        0.6,
        "ptm_energy":               1.5,    # UPGRADED from 0.075 -> 1.5 (dense-gradient primary)
        "plddt":                    0.1,
        "rog":                      0.05,
        "binder_target_ipsae":      0.7,
        "target_binder_ipsae":      0.4,
        "ipsae_min":                2.5,
        "lis":                      0.5,    # NEW (v5)
        "actifptm":                 0.5,    # NEW (v5)
        "hotspot":                  0.0,    # NEW (v5): disabled by default
        "helix":                    -0.08,
        "no_cysteine":              5.0,
    })

    hotspot_indices: list[int] = field(default_factory=list)
    hotspot_threshold: float = 8.0

    # ===== Validation =====
    run_chai1_consensus: bool = True
    ipsae_consensus_threshold: float = 0.8
    min_predictors_passing: int = 2
    run_rmsd_binder: bool = True
    run_shape_complementarity: bool = True      # requires PyRosetta; graceful skip if absent
    rmsd_binder_threshold_angstrom: float = 5.0  # designs with RMSD_binder above this fail filter
    sc_threshold: float = 0.55                   # SC below this fails filter (Lawrence & Colman 1993: good binders >0.65)

    # ===== Output =====
    output_dir: str = "v5_outputs"
    save_intermediate_structures: bool = False

    @classmethod
    def from_yaml(cls, path: str) -> "DesignConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_yaml(self, path: str) -> None:
        with open(path, "w") as f:
            yaml.safe_dump(asdict(self), f, sort_keys=False)

    def validate(self) -> None:
        """Sanity-check invariants. Raises ValueError on bad config."""
        if self.binder_length < 30 or self.binder_length > 200:
            raise ValueError(f"binder_length {self.binder_length} outside [30, 200]")
        if self.mpnn_temperature <= 0:
            raise ValueError("mpnn_temperature must be > 0")
        if self.phase1_steps < 1 or self.phase2_steps < 1:
            raise ValueError("phase1_steps and phase2_steps must be >= 1")
        required = {"binder_target_contact", "iptm", "ipsae_min", "ptm_energy"}
        missing = required - set(self.loss_weights)
        if missing:
            raise ValueError(f"Required loss weights missing: {missing}")
        if self.min_predictors_passing < 1:
            raise ValueError("min_predictors_passing must be >= 1")


__all__ = ["DesignConfig"]


if __name__ == "__main__":
    # Smoke test
    cfg = DesignConfig(seed=1, target_structure="5G51.cif")
    cfg.validate()
    print("DesignConfig OK:", cfg.seed, cfg.target_structure, len(cfg.loss_weights), "loss terms")
