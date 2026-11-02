"""pTMEnergy — predicted-TM-derived pseudo-free-energy.

Reference: Overath et al. (preprint), as catalogued in the Paper Crane
novel-metrics research sweep (docs/novel_binding_metrics_2025.md, memory
key `reference_novel_metrics_research_2026`). pTMEnergy converts the pTM
matrix entries into a Boltzmann-weighted interface energy proxy that
separates binders and non-binders better than raw pTM for small designs.

STATUS: PLACEHOLDER. Real implementation needs the per-residue pTM
matrix, which we don't yet standardize across tools.

TODO: implement once the validator contract includes the pTM matrix path.
See docs/novel_binding_metrics_2025.md for the exact formula.
"""

from __future__ import annotations

from typing import Mapping


def compute_ptmenergy(
    pdb_path: str,  # noqa: ARG001
    upstream_metrics: Mapping[str, float],
    ptm_matrix_path: str | None = None,  # noqa: ARG001 -- reserved for real impl
) -> float:
    """Return a float representing a pTM-derived pseudo-energy.

    Placeholder: derives from upstream ipTM. Lower is better in the real
    metric; we return a positive magnitude here so downstream filtering code
    can be exercised without type-check failures.
    """
    iptm = float(upstream_metrics.get("iptm", 0.0))
    iptm = max(1e-6, min(1.0, iptm))
    # Placeholder: "energy" ~ -log(iptm); stronger predicted interface ->
    # more negative energy in a real implementation, but we return the
    # positive magnitude for easy JSON serialization.
    import math

    return float(-math.log(iptm))
