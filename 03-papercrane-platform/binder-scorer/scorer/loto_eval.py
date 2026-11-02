"""loto_eval.py — The scoreboard: run the LOTO eval + three-zone verdict (Task A8).

This is the crux deliverable. It produces the FIRST real number: does a learned
global scorer (candidate, default B6) beat raw within-fold min_ipSAE (baseline,
default B0) *within fold*, and is there per-target headroom?

Flow (per well-powered target T, leave-one-target-out):
  1. Split: test = all designs with target==T, train = ALL other designs.
  2. Fold-adaptive k = min(20, n_pos_in_T).
  3. Run candidate + baseline scorers → ranked design_id lists.
  4. Primary endpoint  : Precision@k(T) of candidate vs baseline → delta.
     Co-primary        : Recall@budget(T) (budget defaults to k).
  5. Aggregate the per-target deltas with the target-clustered BCa bootstrap
     (resampling TARGETS, not designs), the one-sided sign test, the three-zone
     verdict, and the pre-registered power statement.
  6. Report Nipah-IN (the NIPAH fold) and Nipah-OUT (all folds except NIPAH)
     separately, since Nipah is the headline out-of-distribution stress target.
"""

from __future__ import annotations

from typing import Sequence

from scorer.baselines import BASELINE_BY_NAME
from scorer.bootstrap_ci import paired_bca_ci
from scorer.data_loader import load_designs
from scorer.eval_metrics import (
    fold_adaptive_k,
    precision_at_k,
    recall_at_budget,
)
from scorer.eval_types import is_real_binder
from scorer.loto_split import loto_folds
from scorer.power_analysis import power_statement

# Co-primary recall budget. Same as the fold-adaptive k unless overridden — a
# lab that can test k designs is the natural budget.
DEFAULT_BUDGET = 20

# Pre-registered decision rule (Task A8). Written BEFORE seeing the numbers so
# the verdict is not p-hacked after the fact.
THREE_ZONE_POLICY = (
    "PRE-REGISTERED THREE-ZONE POLICY (Task A8).\n"
    "Headline comparator = B5 (target-feature-conditioned LGBM), which is "
    "currently IDENTICAL to B6 (global LGBM) until target-side features exist. "
    "Primary endpoint = Delta Precision@k(target) of the candidate scorer minus "
    "the baseline (B0 = raw within-fold min_ipSAE). Recall@budget is the "
    "co-primary endpoint. The aggregate delta is a target-clustered BCa "
    "bootstrap over the well-powered LOTO folds.\n"
    "Zones (on the Precision@k aggregate):\n"
    "  real_product        : CI lower bound > 0  OR  per-target wins >= n-1.\n"
    "  fall_back_to_global : CI upper bound < 0  OR  wins <= (n//2 - 1).\n"
    "  inconclusive        : anything in between (underpowered / mixed).\n"
    "We additionally report Nipah-IN (the NIPAH fold alone) and Nipah-OUT "
    "(all folds except NIPAH) because NIPAH is the headline OOD stress target."
)


def _three_zone_verdict(head_ci: dict, n_pos_deltas: int, n_targets: int) -> str:
    """Pre-registered three-zone verdict.

    Args:
        head_ci: dict with at least ``lo`` and ``hi`` (the aggregate CI on the
            primary Precision@k delta).
        n_pos_deltas: number of targets where the candidate strictly beat the
            baseline (delta > 0) — the "wins".
        n_targets: number of well-powered folds.

    Returns one of: "real_product", "fall_back_to_global", "inconclusive".
    """
    lo = head_ci.get("lo", float("nan"))
    hi = head_ci.get("hi", float("nan"))

    # Epsilon tolerance: subnormal bootstrap dust (e.g. lo=5.55e-18 when most
    # deltas are exactly 0) must not flip a verdict on a floating-point knife-
    # edge. (x == x guards are NaN checks — keep them.)
    EPS = 1e-9
    if (lo == lo and lo > EPS) or n_pos_deltas >= n_targets - 1:
        return "real_product"
    if (hi == hi and hi < -EPS) or n_pos_deltas <= (n_targets // 2 - 1):
        return "fall_back_to_global"
    return "inconclusive"


def _positive_ids(designs: Sequence[dict]) -> set[str]:
    return {d["design_id"] for d in designs if is_real_binder(d)}


def _eval_fold(target: str, train: list[dict], test: list[dict],
               candidate_fn, baseline_fn, budget: int) -> dict:
    """Compute one fold's per-target row."""
    train_labels = [is_real_binder(d) for d in train]
    pos_ids = _positive_ids(test)
    n_pos = len(pos_ids)
    k = fold_adaptive_k(n_pos, default_k=20)

    cand_ranked = [s["design_id"] for s in candidate_fn(train_labels, train, test)]
    base_ranked = [s["design_id"] for s in baseline_fn(train_labels, train, test)]

    cand_p = precision_at_k(cand_ranked, pos_ids, k)
    base_p = precision_at_k(base_ranked, pos_ids, k)
    cand_r = recall_at_budget(cand_ranked, pos_ids, budget)
    base_r = recall_at_budget(base_ranked, pos_ids, budget)

    return {
        "target": target,
        "k": k,
        "n_pos": n_pos,
        "n_test": len(test),
        "candidate_precision_at_k": cand_p,
        "baseline_precision_at_k": base_p,
        "delta_precision": cand_p - base_p,
        "candidate_recall_at_budget": cand_r,
        "baseline_recall_at_budget": base_r,
        "delta_recall": (cand_r - base_r),
    }


def _aggregate(rows: list[dict]) -> dict:
    """Aggregate per-target rows into CI + sign test + verdict inputs."""
    p_deltas = [r["delta_precision"] for r in rows]
    r_deltas = [
        r["delta_recall"] for r in rows
        if r["delta_recall"] == r["delta_recall"]  # drop nan recalls
    ]
    n_targets = len(rows)
    p_ci = paired_bca_ci(p_deltas)
    r_ci = paired_bca_ci(r_deltas) if r_deltas else None
    wins = sum(1 for d in p_deltas if d > 0)
    verdict = _three_zone_verdict(p_ci, wins, n_targets)
    return {
        "precision": p_ci,
        "recall": r_ci,
        "wins": wins,
        "n_targets": n_targets,
        "deltas": p_deltas,
        "verdict": verdict,
    }


def run_loto_eval(csv_path: str, candidate: str = "B6", baseline: str = "B0",
                  budget: int = DEFAULT_BUDGET) -> dict:
    """Run the full LOTO eval and return a structured result dict.

    Keys: ``candidate``, ``baseline``, ``per_target`` (list of fold rows),
    ``aggregate`` (precision/recall CI + verdict inputs), ``verdict``,
    ``power_statement``, ``nipah_in``, ``nipah_out``.
    """
    if candidate not in BASELINE_BY_NAME:
        raise ValueError(f"unknown candidate {candidate!r}; "
                         f"choose from {sorted(BASELINE_BY_NAME)}")
    if baseline not in BASELINE_BY_NAME:
        raise ValueError(f"unknown baseline {baseline!r}; "
                         f"choose from {sorted(BASELINE_BY_NAME)}")

    candidate_fn = BASELINE_BY_NAME[candidate]
    baseline_fn = BASELINE_BY_NAME[baseline]

    designs = load_designs(csv_path)

    rows: list[dict] = []
    for target, train, test in loto_folds(designs):
        rows.append(
            _eval_fold(target, train, test, candidate_fn, baseline_fn, budget)
        )

    agg = _aggregate(rows)

    # Nipah-IN: the NIPAH fold alone. Nipah-OUT: everything except NIPAH.
    nipah_rows = [r for r in rows if r["target"].upper() == "NIPAH"]
    out_rows = [r for r in rows if r["target"].upper() != "NIPAH"]
    nipah_in = nipah_rows[0] if nipah_rows else None
    nipah_out = _aggregate(out_rows) if out_rows else None

    point = agg["precision"]["point"]
    pstmt = power_statement(point, agg["deltas"])

    return {
        "candidate": candidate,
        "baseline": baseline,
        "per_target": rows,
        "aggregate": agg,
        "verdict": agg["verdict"],
        "power_statement": pstmt,
        "nipah_in": nipah_in,
        "nipah_out": nipah_out,
        "policy": THREE_ZONE_POLICY,
    }


# ---------------------------------------------------------------------------
# Pretty-printing main
# ---------------------------------------------------------------------------
def _fmt(x: float, nd: int = 3) -> str:
    if x is None or x != x:  # None or nan
        return "  nan"
    return f"{x:.{nd}f}"


def _print_run(res: dict) -> None:
    cand, base = res["candidate"], res["baseline"]
    print(f"\n{'='*72}")
    print(f"LOTO EVAL  —  candidate={cand}  vs  baseline={base}")
    print(f"{'='*72}")
    print(f"{'target':<12}{'k':>4}{'n_pos':>7}"
          f"{base+'_P@k':>14}{cand+'_P@k':>14}{'deltaP':>10}")
    print("-" * 72)
    for r in res["per_target"]:
        print(f"{r['target']:<12}{r['k']:>4}{r['n_pos']:>7}"
              f"{_fmt(r['baseline_precision_at_k']):>14}"
              f"{_fmt(r['candidate_precision_at_k']):>14}"
              f"{_fmt(r['delta_precision']):>10}")
    print("-" * 72)
    agg = res["aggregate"]
    ci = agg["precision"]
    print(f"mean delta Precision@k = {_fmt(ci['point'])}  "
          f"95% BCa CI = [{_fmt(ci['lo'])}, {_fmt(ci['hi'])}]")
    print(f"wins (delta>0): {agg['wins']}/{agg['n_targets']}   "
          f"sign-test p = {_fmt(ci['sign_test_p'])}   "
          f"wilcoxon p = {_fmt(ci['wilcoxon_p'])}")
    rec = agg["recall"]
    if rec is not None:
        print(f"mean delta Recall@budget = {_fmt(rec['point'])}  "
              f"95% BCa CI = [{_fmt(rec['lo'])}, {_fmt(rec['hi'])}]")
    print(f"THREE-ZONE VERDICT: {res['verdict'].upper()}")
    print(f"POWER: {res['power_statement']}")

    ni = res["nipah_in"]
    if ni is not None:
        print(f"Nipah-IN  (NIPAH fold): {base} P@k={_fmt(ni['baseline_precision_at_k'])} "
              f"{cand} P@k={_fmt(ni['candidate_precision_at_k'])} "
              f"delta={_fmt(ni['delta_precision'])}")
    no = res["nipah_out"]
    if no is not None:
        nci = no["precision"]
        print(f"Nipah-OUT (all except NIPAH): mean delta P@k={_fmt(nci['point'])} "
              f"CI=[{_fmt(nci['lo'])},{_fmt(nci['hi'])}] "
              f"wins={no['wins']}/{no['n_targets']} verdict={no['verdict'].upper()}")


def main() -> None:
    csv_path = "data/processed/labeled_features.csv"

    # Primary: B6 (global LGBM) vs B0 (raw within-fold min_ipSAE).
    res_b6 = run_loto_eval(csv_path, candidate="B6", baseline="B0")
    _print_run(res_b6)

    # Secondary: B3 (Overath 3-feature LR) vs B0.
    res_b3 = run_loto_eval(csv_path, candidate="B3", baseline="B0")
    _print_run(res_b3)


if __name__ == "__main__":
    main()
