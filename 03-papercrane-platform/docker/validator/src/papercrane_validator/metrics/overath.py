"""Overath model — composite binder-plausibility score.

Reference: the Overath lab's composite model (see
docs/novel_binding_metrics_2025.md — novel-metrics sweep, memory
`reference_novel_metrics_research_2026`). Combines ipTM, pLDDT, interface
PAE, hotspot contact fraction, and ESM2 pLL into a single 0..1 ranking
score using a fitted logistic regression. Outperformed individual metrics
in Paper Crane internal benchmarks.

STATUS: PLACEHOLDER. Real implementation requires loading the fitted
coefficients from `/opt/papercrane/weights/overath/overath_v1.json` (not
yet mounted). Until then we combine the upstream inputs with hand-picked
weights that approximate the published model.

TODO: load real coefficients once the weights volume is populated; pin
the hash in the manifest so scoring is reproducible.
"""

from __future__ import annotations

from typing import Mapping


def compute_overath(
    upstream_metrics: Mapping[str, float],
    hotspot_contact: float,
    esm_pll: float,
) -> float:
    """Return a composite score in [0.0, 1.0].

    Weights are placeholder-level (hand-picked, roughly matching the sign
    and magnitude of the fitted model). Do NOT depend on the exact numbers
    here — they will move when real coefficients land.
    """
    iptm = float(upstream_metrics.get("iptm", 0.0))
    plddt = float(upstream_metrics.get("plddt", 0.0))
    i_pae = float(upstream_metrics.get("i_pae", 30.0))

    iptm = max(0.0, min(1.0, iptm))
    # pLDDT typically reported 0..100; normalize to 0..1.
    plddt_norm = max(0.0, min(1.0, plddt / 100.0))
    # Lower i_pae = better; fold to 0..1 (0 A -> 1.0, 30 A -> 0.0).
    i_pae_norm = max(0.0, 1.0 - min(1.0, i_pae / 30.0))
    hs = max(0.0, min(1.0, float(hotspot_contact)))
    # ESM2 pLL comes in as a negative log-likelihood (usually -1 to 0 for
    # plausible sequences). Clip and flip sign so larger -> better.
    esm_norm = max(0.0, min(1.0, 1.0 + max(-1.0, float(esm_pll))))

    score = (
        0.30 * iptm
        + 0.20 * plddt_norm
        + 0.15 * i_pae_norm
        + 0.20 * hs
        + 0.15 * esm_norm
    )
    return float(max(0.0, min(1.0, score)))
