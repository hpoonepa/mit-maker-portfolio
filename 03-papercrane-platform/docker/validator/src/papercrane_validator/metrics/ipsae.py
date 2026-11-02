"""ipSAE — interprotein Score from Aligned Errors.

Reference: Dunbar et al., "ipSAE: an improved metric for ranking protein
binder designs" (2024). The method combines the interprotein PAE (Predicted
Aligned Error) sub-matrix with chain identity to produce a score that
correlates better with experimental binding than ipTM alone. See also the
Adaptyv `adaptyv:ipsae` skill card for ranking thresholds (AUC 0.806 vs
ipTM 0.628).

STATUS: PLACEHOLDER. Real implementation requires parsing the AF2/Boltz/
Chai PAE matrix and chain labels, both of which live in tool-specific
output formats we haven't unified yet. Until that is wired through, this
derives a plausible proxy from the upstream-reported `iptm` so the rest of
the validation pipeline can be tested end-to-end.

TODO: implement per https://doi.org/10.1101/2024.08.26.609775 once the
validator contract includes the PAE matrix path. Tracking issue: PC-0042.
"""

from __future__ import annotations

from typing import Mapping


def compute_ipsae(
    pdb_path: str,  # noqa: ARG001 -- used by real implementation
    upstream_metrics: Mapping[str, float],
    pae_matrix_path: str | None = None,  # noqa: ARG001 -- reserved for real impl
    target_chain: str = "A",  # noqa: ARG001
    binder_chain: str = "B",  # noqa: ARG001
) -> float:
    """Return a float in [0.0, 1.0] approximating the ipSAE score.

    Placeholder logic: ipSAE tracks ipTM closely when the interface is
    plausible (both high) and when PAE is well-calibrated. We map ipTM
    through a mild shrink factor so tests can assert the metric responds to
    upstream inputs but don't over-claim accuracy.
    """
    iptm = float(upstream_metrics.get("iptm", 0.0))
    # Clamp to [0,1] — some tools report ipTM outside the canonical range.
    iptm = max(0.0, min(1.0, iptm))
    # Placeholder: ipSAE is typically a bit lower than ipTM on weak
    # interfaces and a bit higher on strong ones. Fit by a gentle sigmoid-
    # adjacent map that preserves monotonicity.
    return float(iptm ** 1.1)
