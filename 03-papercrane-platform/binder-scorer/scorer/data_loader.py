"""data_loader.py — Load the real labeled feature table into design dicts.

The plan did not anticipate the real schema, so this module reconciles it:

  * ``binds`` is the string "True"/"False"  -> parsed to a real bool.
  * No ``design_id`` column                 -> synthesised, stable & unique:
        design_id = f"{target}:{sha1(sequence)[:12]}"
  * ipSAE is SPLIT across two columns. Proteinbase rows populate
    ``computational__boltz2_min_ipsae``; Overath rows populate
    ``ipsae_min_native``. We build a unified **best-available ipSAE** per
    design (boltz2 if present else native; higher = better) exposed as the
    ``best_ipsae`` feature, used as both the B0 baseline and an LGBM feature.
  * Empty / "nan" / "NA" / "None" cells -> float NaN. We DO NOT impute here;
    LightGBM consumes NaN natively. (LR baselines impute per-fold themselves.)

Each returned design is a plain dict:
    {
      "design_id": str, "target": str, "sequence": str,
      "binds": bool, "best_ipsae": float,
      "features": {feature_key: float, ...},  # all LGBM_FEATURE_KEYS, NaN-filled
    }
"""

from __future__ import annotations

import csv
import hashlib
import math
from typing import Any

# Overath validated 3-feature set (Task A5 / B3). rmsd lower=better; the LR
# learns the sign, so we pass the raw value.
OVERATH_FEATURE_KEYS: tuple[str, ...] = (
    "best_ipsae",
    "shape_complementarity",
    "rmsd_binder",
)

# 7 sequence/biophysical features.
_SEQ_FEATURE_KEYS: tuple[str, ...] = (
    "seq_length",
    "molecular_weight",
    "isoelectric_point",
    "cysteine_fraction",
    "hydrophobic_fraction",
    "aromatic_fraction",
    "net_charge_ph7",
)

# Full numeric feature set for the global LightGBM baseline (B6):
# best_ipsae + the 7 other computational__ metric columns
# + shape_complementarity + rmsd_binder + the 7 sequence features.
_OTHER_COMPUTATIONAL_KEYS: tuple[str, ...] = (
    "computational__boltz2_iptm",
    "computational__boltz2_lis",
    "computational__actifptm",
    "computational__interface_residues",
    "computational__boltz2_complex_iplddt",
    "computational__proteinmpnn_score",
    "computational__esmfold_plddt",
)

LGBM_FEATURE_KEYS: tuple[str, ...] = (
    ("best_ipsae",)
    + _OTHER_COMPUTATIONAL_KEYS
    + ("shape_complementarity", "rmsd_binder")
    + _SEQ_FEATURE_KEYS
)

_MISSING_TOKENS = {"", "nan", "na", "none", "null"}


def parse_binds(value: Any) -> bool:
    """A confirmed REAL binder iff the cell is literally True / "True"."""
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() == "true"


def synth_design_id(target: str, sequence: str) -> str:
    h = hashlib.sha1(sequence.encode()).hexdigest()[:12]
    return f"{target}:{h}"


def _to_float(value: Any) -> float:
    if value is None:
        return float("nan")
    s = str(value).strip()
    if s.lower() in _MISSING_TOKENS:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _best_ipsae(row: dict) -> float:
    boltz = _to_float(row.get("computational__boltz2_min_ipsae"))
    if not math.isnan(boltz):
        return boltz
    return _to_float(row.get("ipsae_min_native"))


def load_designs(csv_path: str) -> list[dict]:
    designs: list[dict] = []
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        # Generic: pick up any Orbion bio__* column present in this CSV.
        bio_keys = [f for f in (reader.fieldnames or []) if f.startswith("bio__")]
        for row in reader:
            target = (row.get("target") or "").strip()
            sequence = (row.get("sequence") or "").strip()
            best = _best_ipsae(row)
            features: dict[str, float] = {}
            for key in LGBM_FEATURE_KEYS:
                if key == "best_ipsae":
                    features[key] = best
                else:
                    features[key] = _to_float(row.get(key))
            for key in bio_keys:
                features[key] = _to_float(row.get(key))
            designs.append(
                {
                    "design_id": synth_design_id(target, sequence),
                    "target": target,
                    "sequence": sequence,
                    "binds": parse_binds(row.get("binds")),
                    "best_ipsae": best,
                    "features": features,
                }
            )
    return designs
