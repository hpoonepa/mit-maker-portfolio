"""LIS — Local Interaction Score.

Reference: Kim et al., "LIS: predicting protein-protein interactions by
combining sequence and structure information" (2024). Averages the inverse
of inter-chain PAE values below a 12 A threshold, producing a score in
[0, 1] that correlates with genuine interaction likelihood.

STATUS: PLACEHOLDER. Same blocker as ipSAE / pTMEnergy — requires the PAE
matrix.

TODO: implement per Kim et al. once PAE is in the validator contract.
"""

from __future__ import annotations

from typing import Mapping


def compute_lis(
    pdb_path: str,  # noqa: ARG001
    upstream_metrics: Mapping[str, float],
    pae_matrix_path: str | None = None,  # noqa: ARG001
) -> float:
    """Placeholder LIS in [0.0, 1.0] derived from upstream iptm + i_pae."""
    iptm = float(upstream_metrics.get("iptm", 0.0))
    i_pae = float(upstream_metrics.get("i_pae", 30.0))
    iptm = max(0.0, min(1.0, iptm))
    # LIS is higher when ipTM is high AND interface PAE is low. Normalize
    # i_pae against a rough 0..30 range; clamp to avoid divide-by-zero.
    i_pae_norm = max(0.0, 1.0 - min(1.0, i_pae / 30.0))
    return float(0.5 * iptm + 0.5 * i_pae_norm)
