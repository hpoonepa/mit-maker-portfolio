"""Tri-objective scoring: Protenix + Boltz2 + ESMFold.

THE MODEL, AND THE EVIDENCE BEHIND IT
=====================================
Ground truth: 35 designs across two Adaptyv campaigns (15 on 2026-07-16, 20 on
2026-09-15). 19 loaded onto the BLI sensor, 16 produced ZERO measured curves,
1 bound (l79_s469532_mpnn9, KD 546/666 nM).

Where the one binder ranked, out of the 17 designs with full metrics:
    protenix ipTM            0.9490   rank  1/17
    protenix seed spread     0.0006   rank  1/17  (lowest)
    esmfold2 ipTM            0.8004   rank  2/17
    ipSAE_min                0.8279   rank 10/20  <-- ipSAE FAILED

What predicts EXPRESSION (loaded vs zero curves):
    esmfold2 ipTM       AUC 0.653  p 0.32
    solublempnn delta   AUC 0.725  p 0.12
    solublempnn raw     AUC 0.463  p 0.83   <- noise
    protenix ipTM       AUC 0.500  p 1.00   <- ZERO expression signal

=> The axes are ORTHOGONAL. Protenix says whether it BINDS; ESMFold says
   whether it EXISTS. Score them separately, then gate on both.

=> ipSAE is demoted. src/losses/consensus.py::consensus_gate gates on
   min_ipsae, which would have ranked the only real binder 10th of 20. It is
   still computed and reported, but it is NOT the gate. See `LEGACY_IPSAE_GATE`.

HONESTY
=======
The binding axis rests on ONE positive, and those ranks were computed after the
fact. The expression axis has 17-18 outcomes and NOTHING reaches p<0.05 (n=17
with a 10/10 split has ~30% power for AUC 0.70). Thresholds marked CALIBRATED
come from that single binder; those marked UNCALIBRATED are placeholders.
Re-run calibrate() on every new batch of ground truth.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence
import math
import statistics

__all__ = [
    "Thresholds", "TriScore", "score_design", "seed_spread",
    "aggregate_protenix_seeds", "rank_designs", "LEGACY_IPSAE_GATE",
]

# consensus_gate(metric_key="min_ipsae") ranked the true binder 10/20.
# Kept only so older campaign configs keep running; never make it the gate.
LEGACY_IPSAE_GATE = False


@dataclass
class Thresholds:
    """Hard gates. `calib` records where each number came from."""
    protenix_iptm_min: float = 0.93          # CALIBRATED: binder 0.9490
    protenix_spread_max: float = 0.010       # CALIBRATED: binder 0.0006
    esmfold_iptm_min: float = 0.75           # CALIBRATED: binder 0.8004
    esmfold_binder_plddt_min: float = 0.70   # UNCALIBRATED: standard pLDDT confidence floor
    boltz2_iptm_min: float = 0.80            # UNCALIBRATED: no per-design boltz2 ground truth yet
    calib: Dict[str, str] = field(default_factory=lambda: {
        "protenix_iptm_min": "CALIBRATED (n=1 binder)",
        "protenix_spread_max": "CALIBRATED (n=1 binder)",
        "esmfold_iptm_min": "CALIBRATED (n=1 binder)",
        "esmfold_binder_plddt_min": "UNCALIBRATED",
        "boltz2_iptm_min": "UNCALIBRATED",
    })


# Within-axis weights (sum to 1 per axis).
W_BIND = {"protenix_iptm": 0.45, "protenix_spread": 0.35, "boltz2_iptm": 0.20}
W_EXPRESS = {"esmfold_iptm": 0.45, "esmfold_binder_plddt": 0.55}
# Between axes. Expression carries 45% because 16 of 35 designs never produced a
# single curve — a design that does not express cannot bind at any ipTM.
W_AXIS = {"bind": 0.55, "express": 0.45}

# Soft-normalisation ranges: value -> [0,1] before weighting. Chosen so the one
# real binder lands near the top of each range rather than saturating it.
NORM = {
    "protenix_iptm":        (0.70, 0.98),
    "protenix_spread":      (0.10, 0.0),    # inverted: 0.10 -> 0, 0.0 -> 1
    "boltz2_iptm":          (0.60, 0.95),
    "esmfold_iptm":         (0.50, 0.90),
    "esmfold_binder_plddt": (0.50, 0.95),
}


def _unit(value: Optional[float], key: str) -> Optional[float]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    lo, hi = NORM[key]
    if hi == lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


@dataclass
class TriScore:
    name: str
    bind: float = float("nan")
    express: float = float("nan")
    composite: float = float("nan")
    gates_failed: List[str] = field(default_factory=list)
    metrics: Dict[str, Optional[float]] = field(default_factory=dict)
    units: Dict[str, Optional[float]] = field(default_factory=dict)

    @property
    def passes(self) -> bool:
        return not self.gates_failed

    def as_row(self) -> Dict:
        d = {"name": self.name, "composite": self.composite, "bind": self.bind,
             "express": self.express, "passes": "PASS" if self.passes else "fail",
             "gates_failed": "; ".join(self.gates_failed)}
        d.update({k: v for k, v in self.metrics.items()})
        return d


def seed_spread(values: Sequence[float]) -> float:
    """Protenix seed spread = population stdev of ipTM across seeds.

    The one design that bound had 0.0006 across its seeds — the lowest of 17.
    A design whose predicted complex moves between random seeds is one the model
    is not actually confident about, whatever its mean ipTM looks like.
    Fewer than 2 seeds -> nan (unknown, not zero: a single seed has no spread
    and scoring it as perfectly stable would be a free pass).
    """
    vals = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    if len(vals) < 2:
        return float("nan")
    return statistics.pstdev(vals)


def aggregate_protenix_seeds(iptms: Sequence[float]) -> Dict[str, float]:
    """Collapse a multi-seed Protenix run into (mean ipTM, spread, min ipTM)."""
    vals = [float(v) for v in iptms if v is not None and not math.isnan(float(v))]
    if not vals:
        return {"protenix_iptm": float("nan"), "protenix_spread": float("nan"),
                "protenix_iptm_min": float("nan"), "n_seeds": 0}
    return {
        "protenix_iptm": sum(vals) / len(vals),
        "protenix_spread": seed_spread(vals),
        "protenix_iptm_min": min(vals),
        "n_seeds": len(vals),
    }


def score_design(
    name: str,
    protenix_iptm: Optional[float] = None,
    protenix_spread: Optional[float] = None,
    boltz2_iptm: Optional[float] = None,
    esmfold_iptm: Optional[float] = None,
    esmfold_binder_plddt: Optional[float] = None,
    ipsae_min: Optional[float] = None,
    thresholds: Optional[Thresholds] = None,
) -> TriScore:
    """Score one design on both axes and apply the gates.

    Missing metrics are tolerated: the axis is computed from whatever is
    present, and the absence is recorded as a gate failure so it is never
    silently treated as a pass.
    """
    th = thresholds or Thresholds()
    m = {"protenix_iptm": protenix_iptm, "protenix_spread": protenix_spread,
         "boltz2_iptm": boltz2_iptm, "esmfold_iptm": esmfold_iptm,
         "esmfold_binder_plddt": esmfold_binder_plddt, "ipsae_min": ipsae_min}
    u = {k: _unit(v, k) for k, v in m.items() if k in NORM}

    def axis(weights: Dict[str, float]) -> float:
        num = den = 0.0
        for k, w in weights.items():
            if u.get(k) is not None:
                num += w * u[k]; den += w
        return num / den if den > 0 else float("nan")

    bind, express = axis(W_BIND), axis(W_EXPRESS)
    parts, wts = [], []
    if not math.isnan(bind):
        parts.append(W_AXIS["bind"] * bind); wts.append(W_AXIS["bind"])
    if not math.isnan(express):
        parts.append(W_AXIS["express"] * express); wts.append(W_AXIS["express"])
    composite = sum(parts) / sum(wts) if wts else float("nan")

    failed = []
    checks = [
        ("protenix_iptm", ">=", th.protenix_iptm_min),
        ("protenix_spread", "<=", th.protenix_spread_max),
        ("esmfold_iptm", ">=", th.esmfold_iptm_min),
        ("esmfold_binder_plddt", ">=", th.esmfold_binder_plddt_min),
        ("boltz2_iptm", ">=", th.boltz2_iptm_min),
    ]
    for key, op, thr in checks:
        v = m.get(key)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            failed.append(f"{key}:missing")
        elif op == ">=" and v < thr:
            failed.append(f"{key}={v:.4g}<{thr:g}")
        elif op == "<=" and v > thr:
            failed.append(f"{key}={v:.4g}>{thr:g}")

    if LEGACY_IPSAE_GATE and ipsae_min is not None and ipsae_min < 0.80:
        failed.append(f"ipsae_min={ipsae_min:.4g}<0.8 (LEGACY GATE - known bad)")

    return TriScore(name=name, bind=bind, express=express, composite=composite,
                    gates_failed=failed, metrics=m, units=u)


def rank_designs(scores: List[TriScore]) -> List[TriScore]:
    """Sort best-first. Gate-passing designs always outrank failing ones."""
    def key(s: TriScore):
        c = s.composite if not math.isnan(s.composite) else -1.0
        return (0 if s.passes else 1, -c)
    return sorted(scores, key=key)


def calibrate(labelled: List[Dict]) -> Thresholds:
    """Re-derive gates from rows carrying bound=1.

    Threshold = the most permissive value seen among designs that actually
    bound, which is the only defensible choice from positives-only data.
    """
    pos = [r for r in labelled if int(r.get("bound", 0)) == 1]
    if not pos:
        raise ValueError("no rows with bound=1 — cannot calibrate")
    th = Thresholds()
    def _mn(k):
        v = [float(r[k]) for r in pos if r.get(k) not in (None, "")]
        return min(v) if v else None
    def _mx(k):
        v = [float(r[k]) for r in pos if r.get(k) not in (None, "")]
        return max(v) if v else None
    for attr, fn, key in (("protenix_iptm_min", _mn, "protenix_iptm"),
                          ("protenix_spread_max", _mx, "protenix_spread"),
                          ("esmfold_iptm_min", _mn, "esmfold_iptm"),
                          ("esmfold_binder_plddt_min", _mn, "esmfold_binder_plddt"),
                          ("boltz2_iptm_min", _mn, "boltz2_iptm")):
        v = fn(key)
        if v is not None:
            setattr(th, attr, round(v, 4))
            th.calib[attr] = f"CALIBRATED (n={len(pos)} binder(s))"
    return th
