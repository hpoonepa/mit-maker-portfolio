"""metric_power.py — WITHIN-TARGET discriminative power of scoring metrics.

We measure how well each metric separates real binders from non-binders
*inside a single target*, then average across targets. Pooled / cross-target
AUC is Simpson-inflated (a metric can look great pooled merely by ranking easy
targets above hard ones) and is therefore misleading for per-metric weighting —
so we never pool.

LEAKAGE-SAFETY CONTRACT
-----------------------
Every function here computes ONLY on the ``designs`` list it is handed. The
caller is expected to pass TRAIN-ONLY designs (the held-out target excluded).
This module performs NO file I/O and never reads the full dataset — the single
exception is the dedicated real-data *smoke test*, which calls
``scorer.data_loader.load_designs`` itself. Excluding a target from the input
provably changes the result (see ``test_leakage_only_uses_passed_designs``).

Design dict shape (from ``scorer.data_loader.load_designs``)::

    {"design_id","target","sequence","binds":bool,"best_ipsae":float,
     "features":{<key>:float}}

ipSAE is aliased: the metric ``computational__boltz2_min_ipsae`` reads from
``d["best_ipsae"]`` (that column is folded into best_ipsae upstream); every
other metric reads from ``d["features"]``.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict

# The 25 metrics to score = the LLM menu minus aliasing.
_COMPUTATIONAL_KEYS = (
    "computational__boltz2_min_ipsae",
    "computational__boltz2_iptm",
    "computational__boltz2_lis",
    "computational__actifptm",
    "computational__interface_residues",
    "computational__boltz2_complex_iplddt",
    "computational__proteinmpnn_score",
    "computational__esmfold_plddt",
)
_STRUCT_KEYS = ("shape_complementarity", "rmsd_binder")
_SEQ_KEYS = (
    "seq_length",
    "isoelectric_point",
    "cysteine_fraction",
    "hydrophobic_fraction",
    "aromatic_fraction",
    "net_charge_ph7",
)
_BIO_KEYS = (
    "bio__aggregation_propensity",
    "bio__ptm_site_density",
    "bio__phospho_site_density",
    "bio__disulfide_potential",
    "bio__disorder_fraction",
    "bio__topology_helix_frac",
    "bio__topology_strand_frac",
    "bio__topology_loop_frac",
    "bio__immunogenicity_proxy",
)

METRIC_KEYS: tuple[str, ...] = (
    _COMPUTATIONAL_KEYS + _STRUCT_KEYS + _SEQ_KEYS + _BIO_KEYS
)

_IPSAE_ALIAS = "computational__boltz2_min_ipsae"


def _metric_value(design: dict, key: str) -> float:
    """Read a metric value with the ipSAE alias; always returns a float (NaN-safe)."""
    raw = design.get("best_ipsae") if key == _IPSAE_ALIAS else design.get("features", {}).get(key)
    if raw is None:
        return float("nan")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float("nan")


def _auc(pairs: list[tuple[float, bool]]) -> float | None:
    """Mann-Whitney U AUC over finite-score (score, label) pairs.

    Rank-based and tie-aware (ties earn 0.5 credit). DIRECTIONAL: higher score
    => predicted binder, so a lower-is-better metric correctly yields AUC < 0.5.
    Never abs()'d here. Returns None if either class is empty.
    """
    pos = [s for s, l in pairs if l]
    neg = sorted(s for s, l in pairs if not l)
    if not pos or not neg:
        return None
    c = 0.0
    for p in pos:
        lo = bisect.bisect_left(neg, p)
        hi = bisect.bisect_right(neg, p)
        c += lo + 0.5 * (hi - lo)
    return c / (len(pos) * len(neg))


def within_target_auc(designs: list[dict], min_per_class: int = 1) -> dict[str, float]:
    """Mean of per-target directional AUCs for each metric.

    For every metric, compute its AUC within each target that has >= min_per_class
    finite values in BOTH the binder and non-binder classes, then average those
    per-target AUCs. A metric with no scoreable target is omitted entirely.
    """
    by_target: dict[str, list[dict]] = defaultdict(list)
    for d in designs:
        by_target[d.get("target", "")].append(d)

    per_metric_aucs: dict[str, list[float]] = defaultdict(list)
    for target_designs in by_target.values():
        for key in METRIC_KEYS:
            pairs = [
                (v, bool(d.get("binds")))
                for d in target_designs
                if not math.isnan(v := _metric_value(d, key))
            ]
            n_pos = sum(1 for _, l in pairs if l)
            n_neg = sum(1 for _, l in pairs if not l)
            if n_pos < min_per_class or n_neg < min_per_class:
                continue
            auc = _auc(pairs)
            if auc is not None:
                per_metric_aucs[key].append(auc)

    return {k: sum(v) / len(v) for k, v in per_metric_aucs.items() if v}


def discriminative_power(designs: list[dict], min_per_class: int = 1) -> dict[str, float]:
    """Direction-agnostic separation strength: abs(auc - 0.5) * 2 in [0, 1].

    0 = useless, 1 = perfect. A lower-is-better metric (AUC < 0.5) still scores
    HIGH because we measure distance from chance, not direction.
    """
    return {k: abs(a - 0.5) * 2 for k, a in within_target_auc(designs, min_per_class).items()}


def format_power_table(
    within_auc: dict[str, float], discrim: dict[str, float]
) -> str:
    """Compact, prompt-ready table sorted by discriminative power (desc).

    One line per metric, e.g.::

        actifptm  AUC=0.735  power=0.47  (higher=better)

    Direction is inferred from the AUC: > 0.5 => higher=better, else lower=better.
    """
    order = sorted(discrim, key=lambda k: discrim[k], reverse=True)
    lines = []
    for k in order:
        auc = within_auc.get(k, 0.5)
        direction = "higher=better" if auc >= 0.5 else "lower=better"
        lines.append(f"{k}  AUC={auc:.3f}  power={discrim[k]:.2f}  ({direction})")
    return "\n".join(lines)
