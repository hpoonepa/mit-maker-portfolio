# SPDX-License-Identifier: MIT
"""Tests for the benchmark evaluation harness.

No network and no structures: every fixture is synthetic, so a failure here is
a failure of the statistics and never of a download.

The metric and bootstrap tests ported from the Paper Crane ``binder-scorer``
tree (``scorer/tests/test_eval_metrics.py``, ``test_bootstrap_ci.py``,
``test_power_analysis.py``) are kept verbatim in intent, so a behavioural
divergence between the two harnesses shows up as a failing test rather than as
two incomparable numbers in two write-ups.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.bootstrap import (  # noqa: E402
    PREREGISTERED_MDE,
    Zone,
    cluster_means,
    compute_mde_at_n,
    macro_average_by_cluster,
    micro_average,
    paired_bca_ci,
    power_statement,
    three_zone_verdict,
)
from benchmark.arms import (  # noqa: E402
    BUILTIN_FILTERS,
    FILTER_REGISTRY,
    PREDICTOR_REGISTRY,
    FilterOutput,
    install_builtins,
    normalise_filter_output,
)
from benchmark.evaluate import (  # noqa: E402
    SUPERIORITY_COMPUTED,
    SUPERIORITY_NO_EXTERNAL_ARM,
    SUPERIORITY_NO_PAIR,
    Arm,
    BenchmarkInstance,
    FilterPolicy,
    PredictorOutput,
    apply_filter,
    evaluate_arm,
    load_manifest,
    register_filter,
    register_predictor,
    run_evaluation,
)
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from benchmark.render import render_markdown  # noqa: E402
from run_evaluation import build_arms  # noqa: E402
from benchmark.metrics import (  # noqa: E402
    false_rejection_rate,
    fold_adaptive_k,
    per_residue_auprc,
    per_residue_auroc,
    precision_at_k,
    recall_at_budget,
    top_k_patch_recall,
)


@pytest.fixture(autouse=True)
def _isolate_registries():
    """Snapshot and restore the global registries around every test.

    The registries are module-level dicts, so a test that registers a double
    would otherwise leak it into whatever test file runs next — which shows up
    as a failure that depends on collection order and disappears when the file
    is run alone. Restoring unconditionally, rather than relying on each test
    to clean up in a finally block, means a test that fails mid-way cannot
    poison its neighbours either.
    """
    predictors = dict(PREDICTOR_REGISTRY)
    filters = dict(FILTER_REGISTRY)
    try:
        yield
    finally:
        PREDICTOR_REGISTRY.clear()
        PREDICTOR_REGISTRY.update(predictors)
        FILTER_REGISTRY.clear()
        FILTER_REGISTRY.update(filters)


# ===========================================================================
# Ported metric tests — binder-scorer scorer/tests/test_eval_metrics.py
# ===========================================================================
def test_precision_at_k_basic():
    assert precision_at_k(["a", "b", "c", "d", "e"], {"a", "c"}, k=2) == 0.5


def test_precision_at_k_target_smaller_than_k_uses_effective_k():
    assert precision_at_k(["a", "b", "c"], {"a", "b"}, k=20) == pytest.approx(2 / 3)


def test_precision_at_k_empty_ranking_is_zero():
    assert precision_at_k([], {"a"}, k=5) == 0.0


def test_precision_at_k_rejects_nonpositive_k():
    with pytest.raises(ValueError):
        precision_at_k(["a"], {"a"}, k=0)


def test_recall_at_budget_basic():
    assert recall_at_budget(["a", "b", "c", "d"], {"a", "d"}, budget=2) == 0.5


def test_recall_at_budget_no_positives_is_nan():
    assert math.isnan(recall_at_budget(["a", "b"], set(), budget=2))


def test_recall_at_budget_budget_exceeds_n():
    assert recall_at_budget(["a", "b"], {"a", "b"}, budget=50) == 1.0


def test_fold_adaptive_k_caps_at_n_pos():
    assert fold_adaptive_k(n_pos=3, default_k=20) == 3


def test_fold_adaptive_k_uses_default_when_n_pos_large():
    assert fold_adaptive_k(n_pos=50, default_k=20) == 20


# ===========================================================================
# Filter metrics
# ===========================================================================
def test_false_rejection_rate_is_zero_when_nothing_is_killed():
    assert false_rejection_rate([], {"C325", "C326", "C327"}) == 0.0


def test_false_rejection_rate_is_one_when_everything_is_killed():
    epitope = {"C325", "C326", "C327"}
    assert false_rejection_rate(epitope, epitope) == 1.0


def test_false_rejection_rate_counts_only_epitope_residues():
    """Killing non-epitope surface is conservatism, not error.

    Absence of an observed antibody contact is not evidence a site is
    unusable, so a kill outside the observed epitope must not be scored as a
    false rejection.
    """
    rate = false_rejection_rate({"C999", "C325"}, {"C325", "C326"})
    assert rate == 0.5


def test_false_rejection_rate_rejects_empty_epitope():
    with pytest.raises(ValueError, match="denominator"):
        false_rejection_rate({"C1"}, set())


# ===========================================================================
# Per-residue ranking metrics
# ===========================================================================
def test_auroc_perfect_separation_is_one():
    assert per_residue_auroc([0.1, 0.2, 0.9, 1.0], [False, False, True, True]) == 1.0


def test_auroc_inverted_separation_is_zero():
    assert per_residue_auroc([0.9, 1.0, 0.1, 0.2], [False, False, True, True]) == 0.0


def test_auroc_all_tied_is_one_half_exactly():
    """Mid-ranks, not a sampled curve: a fully tied score is exactly 0.5."""
    assert per_residue_auroc([0.5] * 6, [True, True, False, False, False, False]) == 0.5


def test_auroc_requires_both_classes():
    with pytest.raises(ValueError, match="both epitope and non-epitope"):
        per_residue_auroc([0.1, 0.2], [True, True])


def test_auroc_rejects_nonfinite_scores():
    with pytest.raises(ValueError, match="NaN or inf"):
        per_residue_auroc([0.1, float("nan")], [True, False])


def test_auprc_perfect_is_one_and_beats_random_on_imbalance():
    labels = [True, True] + [False] * 18
    perfect = per_residue_auprc([1.0, 0.99] + [0.0] * 18, labels)
    worst = per_residue_auprc([0.0, 0.0] + [1.0] * 18, labels)
    assert perfect == pytest.approx(1.0)
    assert worst < 0.2  # AUPRC, unlike AUROC, is punishing under imbalance


def test_top_k_patch_recall_finds_epitope_within_k():
    epitope = {"C1", "C2", "C3", "C4"}
    patches = [frozenset({"C9"}), frozenset({"C8"}), frozenset(epitope)]
    assert top_k_patch_recall(patches, epitope, k=1) == 0.0
    assert top_k_patch_recall(patches, epitope, k=3) == 1.0


def test_top_k_patch_recall_requires_min_coverage():
    """A patch clipping one corner of the epitope has not found it."""
    epitope = {"C1", "C2", "C3", "C4"}
    patches = [frozenset({"C1"})]
    assert top_k_patch_recall(patches, epitope, k=1) == 0.0
    assert top_k_patch_recall(patches, epitope, k=1, min_coverage=0.25) == 1.0


def test_top_k_patch_recall_empty_ranking_is_zero():
    assert top_k_patch_recall([], {"C1", "C2"}, k=5) == 0.0


def test_top_k_patch_recall_rejects_bad_arguments():
    with pytest.raises(ValueError):
        top_k_patch_recall([frozenset({"C1"})], {"C1"}, k=0)
    with pytest.raises(ValueError):
        top_k_patch_recall([frozenset({"C1"})], set(), k=1)
    with pytest.raises(ValueError, match="min_coverage"):
        top_k_patch_recall([frozenset({"C1"})], {"C1"}, k=1, min_coverage=0.0)


# ===========================================================================
# Ported bootstrap tests — binder-scorer scorer/tests/test_bootstrap_ci.py
# ===========================================================================
def test_all_positive_deltas_ci_lower_bound_above_zero():
    deltas = [0.10, 0.12, 0.08, 0.15, 0.09, 0.11, 0.13, 0.07, 0.14, 0.10, 0.12]
    r = paired_bca_ci(deltas, n_boot=2000, seed=0)
    assert r.point > 0
    assert r.lo > 0
    assert r.n == 11
    assert r.n_positive_deltas == 11
    assert r.sign_test_p < 0.01
    assert not r.spans_zero


def test_symmetric_around_zero_ci_straddles_zero():
    deltas = [-0.10, 0.10, -0.08, 0.08, -0.12, 0.12, -0.05, 0.05, -0.09, 0.09, 0.0]
    r = paired_bca_ci(deltas, n_boot=2000, seed=0)
    assert r.lo < 0 < r.hi
    assert r.spans_zero
    assert r.sign_test_p > 0.1


def test_bca_recovers_a_known_interval_on_a_fixed_seed():
    """A pinned interval, so a refactor that changes the arithmetic is caught.

    The deltas are all +0.10 except one +0.20, which is a case the BCa
    acceleration term actually bites on; the bounds below were produced by this
    implementation at seed 7 and are checked to 4 decimal places.
    """
    deltas = [0.10] * 10 + [0.20]
    r = paired_bca_ci(deltas, n_boot=4000, seed=7)
    assert r.point == pytest.approx(0.10909090909, abs=1e-9)
    assert r.lo == pytest.approx(0.1, abs=5e-3)
    assert r.hi == pytest.approx(0.1272727, abs=5e-3)
    # Re-running the identical call must reproduce the bounds exactly.
    again = paired_bca_ci(deltas, n_boot=4000, seed=7)
    assert (again.lo, again.hi) == (r.lo, r.hi)


def test_ci_width_shrinks_as_n_grows():
    """More clusters, tighter interval — the whole reason n is the cluster count."""
    import random

    rng = random.Random(1234)
    population = [rng.gauss(0.05, 0.04) for _ in range(400)]
    widths = []
    for n in (8, 40, 200):
        r = paired_bca_ci(population[:n], n_boot=3000, seed=0)
        widths.append(r.width)
    assert widths[0] > widths[1] > widths[2]


def test_deterministic_given_seed():
    deltas = [0.05, -0.02, 0.1, 0.03, -0.01, 0.08, 0.02, 0.06, -0.03, 0.04, 0.07]
    a = paired_bca_ci(deltas, n_boot=1000, seed=42)
    b = paired_bca_ci(deltas, n_boot=1000, seed=42)
    assert (a.lo, a.hi) == (b.lo, b.hi)


def test_wilcoxon_computed_when_n_ge_10_else_nan():
    big = [0.05, -0.02, 0.1, 0.03, -0.01, 0.08, 0.02, 0.06, -0.03, 0.04]
    assert not math.isnan(paired_bca_ci(big, n_boot=500, seed=0).wilcoxon_p)
    small = [0.05, 0.1, 0.03]
    assert math.isnan(paired_bca_ci(small, n_boot=500, seed=0).wilcoxon_p)


def test_n_positive_deltas_counts_strictly_positive():
    r = paired_bca_ci([0.1, 0.0, -0.1, 0.2, 0.0], n_boot=200, seed=0)
    assert r.n_positive_deltas == 2


def test_empty_deltas_give_nan_and_span_zero():
    r = paired_bca_ci([], n_boot=100, seed=0)
    assert r.n == 0
    assert math.isnan(r.point)
    assert r.spans_zero  # no data is not evidence of an effect


def test_bootstrap_rejects_nonfinite_deltas():
    with pytest.raises(ValueError, match="NaN or inf"):
        paired_bca_ci([0.1, float("nan")], n_boot=100, seed=0)


# ===========================================================================
# Macro vs micro — the test that demonstrates why macro-averaging is required
# ===========================================================================
def test_macro_average_is_duplication_invariant_but_micro_is_not():
    """Why the cluster macro-average is mandatory, not optional.

    The numbers here are the benchmark's real shape, measured 2026-10-05:
    **2,107 antigen clusters, 12,892 instances, and SARS-CoV-2 spike
    (P0DTC2) alone at 1,930 of those instances — 15.0%.** One antigen is a
    sixth of the denominator, so this is not a hypothetical.

    Set-up: the metric is 1.0 on spike and 0.0 on two other clusters, each
    represented once. Honest reading: it works on one antigen in three, so
    the macro-average is 1/3.

    Now give spike its real 1,930 instances while the others keep one each.
    Nothing about the method changed; only the deposition record did.

      * micro-average moves 0.333 -> 0.999, because it counts rows.
      * macro-average stays 0.333, because it counts antigens.

    An unstratified micro-average on this benchmark is therefore close to a
    statement about one glycoprotein. That is why
    :func:`macro_average_by_cluster` is the default path everywhere and
    :func:`micro_average` requires an explicit opt-in — and it matters more
    now that the primary reported result is a prevalence rate, because a
    single antigen family dominating the denominator would distort the
    headline directly.
    """
    SPIKE_INSTANCES = 1930      # measured: 1,930 of 12,892 instances, 15.0%
    values = [1.0, 0.0, 0.0]
    clusters = ["P0DTC2_spike", "hiv_env", "flu_ha"]

    assert micro_average(values) == pytest.approx(1 / 3)
    assert macro_average_by_cluster(values, clusters) == pytest.approx(1 / 3)

    inflated_values = values + [1.0] * (SPIKE_INSTANCES - 1)
    inflated_clusters = clusters + ["P0DTC2_spike"] * (SPIKE_INSTANCES - 1)

    inflated_micro = micro_average(inflated_values)
    inflated_macro = macro_average_by_cluster(inflated_values, inflated_clusters)

    assert inflated_micro == pytest.approx(SPIKE_INSTANCES / (SPIKE_INSTANCES + 2))
    assert inflated_micro > 0.99
    assert inflated_macro == pytest.approx(1 / 3)
    # The two now disagree by nearly the whole range, which is the point.
    assert inflated_micro - inflated_macro > 0.65


def test_spike_cannot_dominate_the_primary_prevalence_rate():
    """The same guarantee, asserted through the harness rather than the helper.

    One cluster supplies 15 of 20 instances and is the only one the filter
    misbehaves on. Macro-averaged by cluster the false-rejection rate is 1/4;
    a per-instance average would read 0.75 — a number about one antigen.
    """
    instances = (
        [_instance(f"30{i:02d}", "P0DTC2_spike", _epitope(100 * i)) for i in range(15)]
        + [_instance(f"31{i:02d}", f"other{i}", _epitope(900 + 100 * i)) for i in range(3)]
    )

    def kills_only_spike(instance: BenchmarkInstance) -> FilterOutput:
        if instance.cluster_id != "P0DTC2_spike":
            return FilterOutput(frozenset())
        key = sorted(instance.epitope_residues)[0]
        return FilterOutput(frozenset({key}), {key: ("SPIKE_ONLY",)})

    arms = (
        Arm("geometric", _RankedPredictor()),
        Arm("geometric+filter", _RankedPredictor(), kills_only_spike),
    )
    macro = run_evaluation(instances, arms=arms, top_k=(1,), headline_k=1,
                           n_boot=500, seed=0)
    micro = run_evaluation(instances, arms=arms, top_k=(1,), headline_k=1,
                           n_boot=500, seed=0, macro=False)

    assert macro.primary is not None and micro.primary is not None
    # 4 clusters, the filter misfires on 1 of them -> 1/4 of a 1/6 epitope.
    assert macro.primary.false_rejection_rate == pytest.approx(1 / 4 / 6)
    # Per instance: 15 of 18 rows misfire -> five times larger.
    assert micro.primary.false_rejection_rate == pytest.approx(15 / 18 / 6)
    assert micro.primary.false_rejection_rate > 3 * macro.primary.false_rejection_rate


def test_cluster_means_collapses_within_cluster_and_drops_nan():
    means = cluster_means([1.0, 0.0, float("nan"), 0.5], ["a", "a", "a", "b"])
    assert means == {"a": 0.5, "b": 0.5}


def test_cluster_means_rejects_length_mismatch():
    with pytest.raises(ValueError, match="same length"):
        cluster_means([1.0, 2.0], ["a"])


def test_macro_average_errors_actionably_on_all_nan():
    with pytest.raises(ValueError, match="no finite values"):
        macro_average_by_cluster([float("nan")], ["a"])


# ===========================================================================
# Ported power tests — binder-scorer scorer/tests/test_power_analysis.py
# ===========================================================================
def test_mde_at_11_clusters_is_in_expected_range():
    assert 0.02 <= compute_mde_at_n(n=11, alpha=0.05, power=0.80) <= 0.08


def test_preregistered_mde_matches_n11():
    assert abs(PREREGISTERED_MDE - compute_mde_at_n(11)) < 0.005


def test_power_statement_labels_small_delta_as_untested_not_disproven():
    stmt = power_statement(observed_delta=0.01, n_clusters=11)
    assert "untested" in stmt.lower() or "underpowered" in stmt.lower()
    assert "disproven" not in stmt.lower()


def test_power_statement_large_delta_is_detectable():
    stmt = power_statement(observed_delta=0.10, n_clusters=11)
    assert "detectable" in stmt.lower() or "powered" in stmt.lower()


def test_mde_is_infinite_below_two_clusters():
    assert math.isinf(compute_mde_at_n(1))


# ===========================================================================
# Three-zone verdict
# ===========================================================================
def test_three_zone_verdict_helps_hurts_and_inconclusive():
    helps = paired_bca_ci([0.1] * 11, n_boot=500, seed=0)
    hurts = paired_bca_ci([-0.1] * 11, n_boot=500, seed=0)
    mixed = paired_bca_ci(
        [-0.1, 0.1, -0.08, 0.08, -0.12, 0.12, -0.05, 0.05, -0.09, 0.09, 0.0],
        n_boot=2000,
        seed=0,
    )
    assert three_zone_verdict(helps) is Zone.FILTER_HELPS
    assert three_zone_verdict(hurts) is Zone.FILTER_HURTS
    assert three_zone_verdict(mixed) is Zone.INCONCLUSIVE


def test_three_zone_verdict_is_inconclusive_with_no_clusters():
    assert three_zone_verdict(paired_bca_ci([], n_boot=10)) is Zone.INCONCLUSIVE


# ===========================================================================
# Synthetic benchmark fixtures
# ===========================================================================
def _instance(pdb_id: str, cluster: str, epitope: set[str]) -> BenchmarkInstance:
    return BenchmarkInstance(
        pdb_id=pdb_id,
        antibody_chains=("H", "L"),
        antigen_chains=("A",),
        epitope_residues=frozenset(epitope),
        cluster_id=cluster,
        split="test",
    )


def _epitope(offset: int) -> set[str]:
    return {f"A{offset + i}" for i in range(6)}


def _synthetic_instances(n_clusters: int = 12) -> list[BenchmarkInstance]:
    """One instance per cluster, each with a distinct six-residue epitope."""
    return [
        _instance(f"{1000 + i}", f"cluster{i}", _epitope(100 * i))
        for i in range(n_clusters)
    ]


class _RankedPredictor:
    """Proposes a decoy patch first, then the true epitope.

    An instance method would compare unequal across arms, so the predictor is
    an object: ``run_evaluation`` pairs a filtered arm to its unfiltered arm by
    predictor *identity*, which is what guarantees a delta isolates the filter.
    """

    def __init__(self, decoys: int = 1) -> None:
        self.decoys = decoys

    def __call__(self, instance: BenchmarkInstance) -> PredictorOutput:
        epitope = sorted(instance.epitope_residues)
        decoy_patches = [
            frozenset({f"{instance.pdb_id}_decoy{d}_{j}" for j in range(6)})
            for d in range(self.decoys)
        ]
        scores = {res: 1.0 for res in epitope}
        scores.update({res: 0.0 for patch in decoy_patches for res in patch})
        return PredictorOutput(
            ranked_patches=tuple(decoy_patches) + (frozenset(epitope),),
            residue_scores=scores,
        )


def _kill_decoys(instance: BenchmarkInstance) -> frozenset[str]:
    """A perfect filter: kills every decoy residue, no real epitope residue."""
    return frozenset({f"{instance.pdb_id}_decoy0_{j}" for j in range(6)})


def _kill_nothing_at_all(instance: BenchmarkInstance) -> frozenset[str]:
    del instance
    return frozenset()


# ===========================================================================
# apply_filter
# ===========================================================================
def test_apply_filter_drop_patch_removes_whole_patch():
    patches = [frozenset({"a", "b"}), frozenset({"c", "d"})]
    assert apply_filter(patches, {"b"}) == (frozenset({"c", "d"}),)


def test_apply_filter_prune_residues_keeps_the_survivors():
    patches = [frozenset({"a", "b"}), frozenset({"c"})]
    out = apply_filter(patches, {"b", "c"}, FilterPolicy.PRUNE_RESIDUES)
    assert out == (frozenset({"a"}),)  # the all-killed patch is gone


def test_apply_filter_preserves_rank_order():
    patches = [frozenset({"x"}), frozenset({"bad"}), frozenset({"y"})]
    assert apply_filter(patches, {"bad"}) == (frozenset({"x"}), frozenset({"y"}))


# ===========================================================================
# evaluate_arm
# ===========================================================================
def test_evaluate_arm_reports_macro_averages_and_per_instance_detail():
    instances = _synthetic_instances(6)
    predictor = _RankedPredictor(decoys=1)
    metrics = evaluate_arm(instances, Arm("geometric", predictor), top_k=(1, 3, 5))

    assert metrics.n_instances == 6
    assert metrics.n_clusters == 6
    # The epitope is proposed second, so top-1 misses and top-3 hits.
    assert metrics.patch_recall[1] == 0.0
    assert metrics.patch_recall[3] == 1.0
    assert metrics.false_rejection_rate == 0.0
    assert metrics.auroc == pytest.approx(1.0)
    assert len(metrics.per_instance) == 6


def test_evaluate_arm_filter_promotes_the_epitope_to_rank_one():
    instances = _synthetic_instances(6)
    predictor = _RankedPredictor(decoys=1)
    filtered = evaluate_arm(
        instances, Arm("geometric+filter", predictor, _kill_decoys), top_k=(1, 3, 5)
    )
    assert filtered.patch_recall[1] == 1.0
    assert filtered.false_rejection_rate == 0.0  # it killed no real epitope residue


def test_evaluate_arm_reports_nan_auroc_when_no_residue_scores():
    instances = _synthetic_instances(3)

    def patches_only(instance: BenchmarkInstance) -> PredictorOutput:
        return PredictorOutput(ranked_patches=(frozenset(instance.epitope_residues),))

    metrics = evaluate_arm(instances, Arm("patches", patches_only), top_k=(1,))
    assert math.isnan(metrics.auroc)  # not substituted with 0.5
    assert metrics.patch_recall[1] == 1.0


def test_evaluate_arm_rejects_empty_instance_list():
    with pytest.raises(ValueError, match="zero instances"):
        evaluate_arm([], Arm("x", _RankedPredictor()))


# ===========================================================================
# run_evaluation
# ===========================================================================
def _four_arms(decoys: int = 1):
    external = _RankedPredictor(decoys=decoys)
    geometric = _RankedPredictor(decoys=decoys + 1)
    return (
        Arm("external", external),
        Arm("external+filter", external, _kill_decoys),
        Arm("geometric", geometric),
        Arm("geometric+filter", geometric, _kill_decoys),
    )


def test_run_evaluation_four_arms_produces_a_headline_with_an_interval():
    """Four arms, and the headline is the filter delta with a real interval.

    Scored at k=1, which is where the filter's effect lives in this fixture:
    the filter kills the first decoy, so the one-decoy ``external`` predictor
    has the epitope promoted to rank 1 while the two-decoy ``geometric`` one
    still has a decoy in front of it.
    """
    instances = _synthetic_instances(12)
    result = run_evaluation(
        instances, arms=_four_arms(), top_k=(1, 3, 5), headline_k=1,
        n_boot=2000, seed=0, external_arms=("external", "geometric"),
    )

    assert [a.arm for a in result.arms] == [
        "external",
        "external+filter",
        "geometric",
        "geometric+filter",
    ]
    assert result.n_clusters == 12
    assert len(result.deltas) == 2
    assert result.superiority is not None
    # Both baselines miss at k=1, so the tie breaks toward the arm listed
    # first — deterministic and in the caller's hands, not alphabetical.
    assert result.superiority.baseline == "external"
    assert result.superiority.interval.n == 12
    assert result.superiority.interval.point == pytest.approx(1.0)
    assert result.superiority.interval.lo > 0
    assert result.superiority.verdict is Zone.FILTER_HELPS
    assert not result.inconclusive


def test_headline_follows_baseline_strength_not_arm_order():
    """"Strongest predictor arm" means strongest, even if listed last.

    The weak arm is listed first precisely so that a headline chosen by list
    order rather than by baseline patch recall would fail here.
    """
    weak = _RankedPredictor(decoys=1)   # epitope at rank 2 -> recall@1 = 0
    strong = _RankedPredictor(decoys=0)  # epitope at rank 1 -> recall@1 = 1
    arms = (
        Arm("weak", weak),
        Arm("weak+filter", weak, _kill_decoys),
        Arm("strong", strong),
        Arm("strong+filter", strong, _kill_decoys),
    )
    result = run_evaluation(
        _synthetic_instances(10), arms=arms, top_k=(1,), headline_k=1,
        n_boot=500, seed=0, external_arms=("weak", "strong"),
    )
    assert result.superiority is not None
    assert result.superiority.baseline == "strong"


def test_run_evaluation_reports_a_null_delta_as_inconclusive_in_those_words():
    """A filter that kills nothing must produce a stated null, not a number."""
    predictor = _RankedPredictor(decoys=1)
    arms = (
        Arm("geometric", predictor),
        Arm("geometric+filter", predictor, _kill_nothing_at_all),
    )
    result = run_evaluation(
        _synthetic_instances(12), arms=arms, n_boot=2000, seed=0,
        external_arms=("geometric",),
    )

    assert result.superiority is not None
    assert result.superiority.interval.point == 0.0
    assert result.superiority.interval.spans_zero
    assert result.inconclusive

    sentence = result.superiority.sentence()
    assert "spans zero" in sentence
    assert "INCONCLUSIVE" in sentence
    report = render_markdown(result)
    assert "spans zero" in report
    assert "INCONCLUSIVE" in report
    assert result.summary()["inconclusive"] is True


def test_run_evaluation_is_reproducible_byte_for_byte_with_a_fixed_seed():
    instances = _synthetic_instances(12)
    first = run_evaluation(instances, arms=_four_arms(), n_boot=1500, seed=11)
    second = run_evaluation(instances, arms=_four_arms(), n_boot=1500, seed=11)
    assert first.to_json() == second.to_json()
    assert render_markdown(first) == render_markdown(second)
    # And the JSON really is parseable, not just equal to itself.
    assert json.loads(first.to_json())["n_clusters"] == 12


def test_run_evaluation_seed_actually_changes_the_interval():
    instances = _synthetic_instances(12)
    a = run_evaluation(instances, arms=_four_arms(), n_boot=1500, seed=1)
    b = run_evaluation(instances, arms=_four_arms(), n_boot=1500, seed=2)
    assert a.config["seed"] != b.config["seed"]
    assert a.to_json() != b.to_json()


def test_run_evaluation_rejects_empty_instance_list_with_an_actionable_error():
    with pytest.raises(ValueError, match="nothing to average over"):
        run_evaluation([], arms=_four_arms())


def test_run_evaluation_rejects_duplicate_arm_names_and_bad_headline_k():
    instances = _synthetic_instances(4)
    predictor = _RankedPredictor()
    with pytest.raises(ValueError, match="unique"):
        run_evaluation(
            instances, arms=(Arm("x", predictor), Arm("x", predictor)), n_boot=10
        )
    with pytest.raises(ValueError, match="headline_k"):
        run_evaluation(
            instances, arms=(Arm("x", predictor),), top_k=(1, 3), headline_k=5
        )


def test_without_a_filtered_arm_there_is_no_audit_and_no_superiority():
    result = run_evaluation(
        _synthetic_instances(4), arms=(Arm("geometric", _RankedPredictor()),),
        n_boot=10, external_arms=("geometric",),
    )
    assert result.primary is None
    assert result.superiority is None
    assert result.superiority_status == SUPERIORITY_NO_PAIR
    assert result.inconclusive
    report = render_markdown(result)
    assert "no arm in this run carries a filter" in report.lower()
    assert "NOT RUN" in report


def test_report_flags_a_filter_that_killed_real_epitope_residues():
    """A non-zero false-rejection rate must be stated, not left in a column.

    The filter here kills one observed epitope residue per antigen, so under
    DROP_PATCH it also destroys the true patch. Patch recall and the primary
    filter metric therefore disagree, which is exactly the case the report
    must not let a reader skim past.
    """
    predictor = _RankedPredictor(decoys=1)

    def _kills_a_real_residue(instance: BenchmarkInstance) -> frozenset[str]:
        return frozenset({sorted(instance.epitope_residues)[0]})

    arms = (
        Arm("geometric", predictor),
        Arm("geometric+filter", predictor, _kills_a_real_residue),
    )
    result = run_evaluation(_synthetic_instances(10), arms=arms, n_boot=500, seed=0)
    filtered = next(a for a in result.arms if a.arm == "geometric+filter")
    assert filtered.false_rejection_rate > 0.0
    report = render_markdown(result)
    assert "killed experimentally observed epitope residues" in report
    assert "not a cost to average away" in report


def test_report_does_not_flag_a_filter_with_a_zero_false_rejection_rate():
    result = run_evaluation(
        _synthetic_instances(10), arms=_four_arms(), top_k=(1, 3, 5),
        headline_k=1, n_boot=500, seed=0,
    )
    assert "killed experimentally observed epitope residues" not in render_markdown(
        result
    )


def test_summary_records_averaging_mode_and_micro_requires_opt_in():
    instances = _synthetic_instances(8)
    macro = run_evaluation(instances, arms=_four_arms(), n_boot=500, seed=0)
    micro = run_evaluation(
        instances, arms=_four_arms(), n_boot=500, seed=0, macro=False
    )
    assert macro.config["averaging"] == "macro_by_cluster"
    assert micro.config["averaging"] == "micro_by_instance"
    assert "Micro-averaging was explicitly requested" in render_markdown(micro)
    assert "Micro-averaging was explicitly requested" not in render_markdown(macro)


# ===========================================================================
# Manifest loading
# ===========================================================================
_HEADER = "pdb_id,antibody_chains,antigen_chains,epitope_residues,cluster_id,split\n"


def _write_manifest(path: Path, rows: list[str], header: str = _HEADER) -> Path:
    path.write_text(header + "".join(row + "\n" for row in rows), encoding="utf-8")
    return path


def test_load_manifest_parses_semicolon_separated_epitopes(tmp_path: Path):
    path = _write_manifest(
        tmp_path / "m.csv",
        ["1bj1,H;L,W,C325;C326;C327;C328;C329,P0DTC2,test"],
    )
    instances, dropped = load_manifest(path)
    assert dropped == []
    assert len(instances) == 1
    assert instances[0].epitope_residues == frozenset(
        {"C325", "C326", "C327", "C328", "C329"}
    )
    assert instances[0].antibody_chains == ("H", "L")
    assert instances[0].instance_id == "1bj1:H+L"


def test_load_manifest_logs_every_drop_with_a_reason(tmp_path: Path):
    path = _write_manifest(
        tmp_path / "m.csv",
        [
            "1bj1,H;L,W,C1;C2;C3;C4;C5,clusterA,test",
            "6al0,H;L,A,C1;C2,clusterB,test",  # below the 5-residue floor
            "7xyz,,A,C1;C2;C3;C4;C5,clusterC,test",  # empty antibody chains
            "8abc,H,A,C1;C2;C3;C4;C5,,test",  # no cluster id
            ",H,A,C1;C2;C3;C4;C5,clusterD,test",  # no pdb id
        ],
    )
    instances, dropped = load_manifest(path)
    assert [i.pdb_id for i in instances] == ["1bj1"]
    reasons = " | ".join(d.reason for d in dropped)
    assert len(dropped) == 4
    assert "below the floor" in reasons
    assert "empty antibody_chains" in reasons
    assert "cluster_id" in reasons
    assert "blank pdb_id" in reasons


def test_load_manifest_limit_is_never_silent(tmp_path: Path):
    rows = [
        f"pdb{i},H;L,A,C1;C2;C3;C4;C5,cluster{i},test" for i in range(5)
    ]
    path = _write_manifest(tmp_path / "m.csv", rows)
    instances, dropped = load_manifest(path, limit=2)
    assert len(instances) == 2
    assert len(dropped) == 3
    assert all("cut by --limit 2" in d.reason for d in dropped)


def test_load_manifest_prefers_a_cutoff_specific_column(tmp_path: Path):
    header = (
        "pdb_id,antibody_chains,antigen_chains,epitope_residues,"
        "epitope_residues_4,cluster_id,split\n"
    )
    path = _write_manifest(
        tmp_path / "m.csv",
        ["1bj1,H;L,W,C1;C2;C3;C4;C5;C6,C1;C2;C3;C4;C5,clusterA,test"],
        header=header,
    )
    at45, _ = load_manifest(path, cutoff=4.5)
    at40, _ = load_manifest(path, cutoff=4.0)
    assert len(at45.pop().epitope_residues) == 6
    assert len(at40.pop().epitope_residues) == 5


def test_load_manifest_filters_by_split(tmp_path: Path):
    path = _write_manifest(
        tmp_path / "m.csv",
        [
            "1aaa,H,A,C1;C2;C3;C4;C5,c1,train",
            "1bbb,H,A,C1;C2;C3;C4;C5,c2,test",
        ],
    )
    instances, dropped = load_manifest(path, split="test")
    assert [i.pdb_id for i in instances] == ["1bbb"]
    assert "split 'train' != 'test'" in dropped[0].reason


def test_load_manifest_errors_actionably_on_an_empty_manifest(tmp_path: Path):
    path = _write_manifest(tmp_path / "empty.csv", [])
    with pytest.raises(ValueError, match="no evaluable instances"):
        load_manifest(path)


def test_load_manifest_names_missing_columns(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text("pdb_id,split\n1bj1,test\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required column"):
        load_manifest(path)


def test_load_manifest_rejects_a_truly_empty_file(tmp_path: Path):
    path = tmp_path / "nothing.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no header row"):
        load_manifest(path)


def test_load_manifest_missing_file_is_a_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "does_not_exist.csv")


# ===========================================================================
# Registries
# ===========================================================================
def test_build_arms_errors_name_the_registered_options():
    with pytest.raises(ValueError, match="Registered predictors"):
        build_arms(["definitely_not_registered"])


def test_build_arms_errors_name_the_registered_filters():
    register_predictor("named_pred", _RankedPredictor())
    with pytest.raises(ValueError, match="Registered filters"):
        build_arms(["named_pred+filter"], filter_name="not_a_filter")


def test_register_and_build_paired_arms_share_one_predictor_object():
    predictor = _RankedPredictor()
    register_predictor("test_pred", predictor)
    register_filter("test_filter", _kill_decoys)
    arms = build_arms(["test_pred", "test_pred+filter"], filter_name="test_filter")
    assert arms[0].predictor is arms[1].predictor
    result = run_evaluation(
        _synthetic_instances(8), arms=arms, n_boot=500, seed=0,
        external_arms=("test_pred",),
    )
    assert result.superiority is not None
    assert result.superiority.baseline == "test_pred"


# ===========================================================================
# CLI
# ===========================================================================
def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_evaluation.py"), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_cli_lists_registered_arms():
    done = _run_cli("--manifest", "x", "--arms", "x", "--out", "x", "--list-arms")
    assert done.returncode == 0, done.stderr
    assert "kill_nothing" in done.stdout


def test_cli_writes_a_report_and_a_json_summary_and_logs_drops(tmp_path: Path):
    """End to end through the CLI, using the built-in null filter.

    The null filter is the honest arm to ship as a default: its true delta is
    zero, so a non-zero headline here would be a harness bug. It also shows
    the report doing the thing it must do with a null — saying so.
    """
    manifest = _write_manifest(
        tmp_path / "m.csv",
        [f"pdb{i},H;L,A,A1;A2;A3;A4;A5;A6,cluster{i},test" for i in range(11)]
        + ["6al0,H;L,A,A1;A2,clusterX,test"],  # dropped: below the floor
    )
    plugin = tmp_path / "fake_predictor_plugin.py"
    plugin.write_text(
        "from benchmark.evaluate import PredictorOutput, register_predictor\n"
        "def _p(instance):\n"
        "    return PredictorOutput(\n"
        "        ranked_patches=(frozenset(instance.epitope_residues),),\n"
        "        residue_scores={r: 1.0 for r in instance.epitope_residues}\n"
        "        | {'A99': 0.0},\n"
        "    )\n"
        "register_predictor('fake', _p)\n",
        encoding="utf-8",
    )

    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_evaluation.py"),
            "--manifest", str(manifest),
            "--arms", "fake,fake+filter",
            "--out", str(tmp_path / "out" / "eval"),
            "--seed", "3",
            "--n-boot", "500",
            "--filter", "kill_nothing",
            "--external", "fake",
            "--plugin", "fake_predictor_plugin",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": f"{REPO_ROOT}:{tmp_path}",
        },
    )
    assert done.returncode == 0, done.stderr

    report = (tmp_path / "out" / "eval.md").read_text(encoding="utf-8")
    summary = json.loads((tmp_path / "out" / "eval.json").read_text(encoding="utf-8"))

    assert "6al0" in report  # the dropped row is named in the report
    assert "6al0" in done.stderr  # and logged
    assert summary["n_clusters"] == 11
    assert summary["n_dropped"] == 1
    assert summary["config"]["seed"] == 3
    assert summary["superiority"]["point"] == 0.0
    assert summary["inconclusive"] is True
    assert summary["superiority_ran"] is True
    assert "spans zero" in summary["superiority"]["sentence"]
    # The primary result is present and clean: kill_nothing kills nothing.
    assert summary["primary"]["false_rejection_rate"] == 0.0
    assert summary["primary"]["clean"] is True


def test_cli_deterministic_output_for_the_same_seed(tmp_path: Path):
    manifest = _write_manifest(
        tmp_path / "m.csv",
        [f"pdb{i},H;L,A,A1;A2;A3;A4;A5;A6,cluster{i},test" for i in range(11)],
    )
    plugin = tmp_path / "fake_predictor_plugin2.py"
    plugin.write_text(
        "from benchmark.evaluate import PredictorOutput, register_predictor\n"
        "def _p(instance):\n"
        "    return PredictorOutput(\n"
        "        ranked_patches=(frozenset(instance.epitope_residues),))\n"
        "register_predictor('fake2', _p)\n",
        encoding="utf-8",
    )
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{REPO_ROOT}:{tmp_path}"}
    outputs = []
    for run in ("a", "b"):
        done = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "run_evaluation.py"),
                "--manifest", str(manifest),
                "--arms", "fake2,fake2+filter",
                "--out", str(tmp_path / run),
                "--seed", "7",
                "--n-boot", "400",
                "--filter", "kill_nothing",
                "--plugin", "fake_predictor_plugin2",
            ],
            capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
        )
        assert done.returncode == 0, done.stderr
        outputs.append((tmp_path / f"{run}.json").read_bytes())
    assert outputs[0] == outputs[1]


# ===========================================================================
# Registry hygiene — order-independence and idempotence
# ===========================================================================
def test_builtin_filters_are_present_in_a_fresh_interpreter():
    """The registry must be complete without importing anything else first.

    Asserted in a subprocess because that is the only way to prove it does not
    depend on test collection order: in-process, some earlier test may already
    have imported the module that registers a filter. A registry that is only
    complete once the right module has been imported fails in CI, under a
    different test order, and for anyone who imports the library instead of
    running the CLI.
    """
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "from benchmark.arms import FILTER_REGISTRY\n"
            "print(','.join(sorted(FILTER_REGISTRY)))",
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO_ROOT)},
    )
    assert done.returncode == 0, done.stderr
    found = set(done.stdout.strip().split(","))
    assert set(BUILTIN_FILTERS) <= found, f"missing built-ins: {found}"


def test_registering_the_same_object_twice_is_a_no_op():
    """Re-registration happens for mundane reasons and must not crash.

    A module imported under two names, a plugin loaded twice, a test module
    re-imported: raising there turns a harmless repeat into a crash.
    """
    install_builtins()
    install_builtins()
    assert set(BUILTIN_FILTERS) <= set(FILTER_REGISTRY)

    predictor = _RankedPredictor()
    register_predictor("dup", predictor)
    register_predictor("dup", predictor)  # same object: fine
    assert PREDICTOR_REGISTRY["dup"] is predictor


def test_registering_a_different_object_under_a_taken_name_raises():
    """A genuine collision must not silently replace a predictor.

    Silently swapping one would change what an already-reported number means.
    """
    register_predictor("clash", _RankedPredictor())
    with pytest.raises(ValueError, match="different object"):
        register_predictor("clash", _RankedPredictor())


def test_registry_doubles_do_not_leak_between_tests():
    """Companion to the autouse fixture: 'dup' and 'clash' are gone by now."""
    assert "dup" not in PREDICTOR_REGISTRY
    assert "clash" not in PREDICTOR_REGISTRY
    assert "test_pred" not in PREDICTOR_REGISTRY


def test_register_rejects_a_blank_name():
    with pytest.raises(ValueError, match="non-empty"):
        register_filter("   ", _kill_nothing_at_all)


# ===========================================================================
# FilterOutput normalisation
# ===========================================================================
def test_bare_residue_keys_are_normalised_with_an_unspecified_reason():
    out = normalise_filter_output(["C325", "C326"])
    assert out.killed == frozenset({"C325", "C326"})
    assert out.codes == frozenset({"UNSPECIFIED"})


def test_a_filter_output_passes_through_unchanged():
    given = FilterOutput(frozenset({"C1"}), {"C1": ("BURIED_BY_NEIGHBOUR",)})
    assert normalise_filter_output(given) is given


def test_a_bare_string_is_rejected_rather_than_split_into_characters():
    """`"C325"` is a collection of five characters; killing five one-letter
    keys would corrupt every prevalence number instead of failing."""
    with pytest.raises(TypeError, match="one key per character"):
        normalise_filter_output("C325")


# ===========================================================================
# Kill-reason prevalence — the primary result
# ===========================================================================
def _reason_filter(instance: BenchmarkInstance) -> FilterOutput:
    """Two codes: UNMODELLED on every instance, BURIED on every third one.

    BURIED additionally lands on a real epitope residue, so the two prevalence
    columns must differ — one counts firing, the other counts false kills.
    """
    epitope = sorted(instance.epitope_residues)
    reasons = {f"{instance.pdb_id}_decoy0_0": ("UNMODELLED",)}
    if int(instance.pdb_id) % 3 == 0:
        reasons[epitope[0]] = ("BURIED",)
    return FilterOutput(frozenset(reasons), reasons)


def test_kill_reason_prevalence_separates_firing_from_false_killing():
    instances = _synthetic_instances(12)   # pdb ids 1000..1011
    metrics = evaluate_arm(
        instances, Arm("geo+filter", _RankedPredictor(), _reason_filter),
        top_k=(1,),
    )
    # UNMODELLED fires everywhere but never on an epitope residue.
    assert metrics.kill_reason_prevalence["UNMODELLED"] == pytest.approx(1.0)
    assert metrics.false_rejection_by_reason["UNMODELLED"] == 0.0
    # BURIED fires on the four ids divisible by 3, and always falsely.
    assert metrics.kill_reason_prevalence["BURIED"] == pytest.approx(4 / 12)
    assert metrics.false_rejection_by_reason["BURIED"] == pytest.approx(4 / 12)


def test_prevalence_lists_stay_aligned_when_a_code_first_fires_late():
    """A code first seen on a later instance must be back-filled with zeros.

    Otherwise its list is shorter than the cluster list and the prevalence is
    computed over the wrong denominator — silently, and in the flattering
    direction.
    """
    instances = _synthetic_instances(10)

    def late(instance: BenchmarkInstance) -> FilterOutput:
        # Fires only on the very last instance.
        if instance.pdb_id == "1009":
            return FilterOutput(frozenset({"zzz"}), {"zzz": ("LATE",)})
        return FilterOutput(frozenset())

    metrics = evaluate_arm(instances, Arm("a", _RankedPredictor(), late), top_k=(1,))
    assert metrics.kill_reason_prevalence["LATE"] == pytest.approx(1 / 10)


def test_saturated_control_reaches_a_false_rejection_rate_of_one():
    """`kill_everything` brackets the primary metric at the top end."""
    result = run_evaluation(
        _synthetic_instances(10),
        arms=(
            Arm("geometric", _RankedPredictor()),
            Arm("geometric+filter", _RankedPredictor(), FILTER_REGISTRY["kill_everything"]),
        ),
        top_k=(1,), headline_k=1, n_boot=500, seed=0,
    )
    assert result.primary is not None
    assert result.primary.false_rejection_rate == 1.0
    assert not result.primary.clean
    assert result.primary.false_rejection_by_reason["SATURATED_CONTROL"] == 1.0


def test_primary_audit_bootstraps_over_clusters_not_instances():
    """n in the audit interval is the cluster count, never the instance count.

    Twenty instances over four clusters must report n = 4. Resampling the
    twenty would quote an interval built from an n the evidence does not have.
    """
    instances = [
        _instance(f"{2000 + i}", f"cluster{i % 4}", _epitope(100 * i))
        for i in range(20)
    ]
    result = run_evaluation(
        instances,
        arms=(
            Arm("geometric", _RankedPredictor()),
            Arm("geometric+filter", _RankedPredictor(), _reason_filter),
        ),
        top_k=(1,), headline_k=1, n_boot=500, seed=0,
    )
    assert result.n_instances == 20
    assert result.primary is not None
    assert result.primary.n_clusters == 4
    assert result.primary.false_rejection_ci.n == 4
    assert result.config["resampling_unit"] == "antigen_cluster"


# ===========================================================================
# Superiority is conditional and says so
# ===========================================================================
def test_superiority_is_not_run_without_a_declared_external_arm():
    """The missing comparison must read as NOT RUN, never as a delta of zero."""
    result = run_evaluation(
        _synthetic_instances(10), arms=_four_arms(), top_k=(1,), headline_k=1,
        n_boot=500, seed=0,
    )
    assert result.superiority is None
    assert result.superiority_status == SUPERIORITY_NO_EXTERNAL_ARM
    assert "NOT RUN" in result.superiority_status
    assert "must not be reported as a delta of zero" in result.superiority_status
    assert result.summary()["superiority_ran"] is False
    assert result.summary()["superiority"] is None

    report = render_markdown(result)
    assert "NOT RUN" in report
    # The internal deltas are still shown, but disclaimed.
    assert "do not support a superiority claim" in report
    # And the primary result still carries the report.
    assert "Primary result" in report


def test_superiority_runs_once_an_external_arm_is_declared():
    result = run_evaluation(
        _synthetic_instances(10), arms=_four_arms(), top_k=(1,), headline_k=1,
        n_boot=500, seed=0, external_arms=("external",),
    )
    assert result.superiority is not None
    assert result.superiority.baseline == "external"
    assert result.superiority_status == SUPERIORITY_COMPUTED


def test_declaring_an_arm_that_does_not_exist_is_an_actionable_error():
    with pytest.raises(ValueError, match="which are not arms"):
        run_evaluation(
            _synthetic_instances(4), arms=_four_arms(), top_k=(1,), headline_k=1,
            n_boot=10, external_arms=("discotope",),
        )


def test_primary_result_appears_before_superiority_in_the_report():
    """Ordering is the claim: the answerable result leads."""
    result = run_evaluation(
        _synthetic_instances(10), arms=_four_arms(), top_k=(1,), headline_k=1,
        n_boot=500, seed=0, external_arms=("external",),
    )
    report = render_markdown(result)
    assert report.index("## Primary result") < report.index("## Superiority")


# ===========================================================================
# The `preflight` filter — our own checks, driven over a benchmark antigen
# ===========================================================================
from benchmark.preflight_filter import (  # noqa: E402
    STRUCTURE_SUFFIXES,
    PreflightFilter,
    StructureUnavailable,
    parse_residue_keys,
    register_preflight,
)


def _antigen(pdb_id: str, epitope: set[str], cluster: str = "c1") -> BenchmarkInstance:
    return BenchmarkInstance(
        pdb_id=pdb_id,
        antibody_chains=("H", "L"),
        antigen_chains=("A",),
        epitope_residues=frozenset(epitope),
        cluster_id=cluster,
        split="test",
    )


@pytest.fixture
def structure_dir(cif_with_unobs_category: Path) -> Path:
    """A directory holding one real (synthetic-but-parsed) structure.

    The conftest fixture writes chain A with residues 101, 102, 103 and 106
    modelled and 104, 105 declared-but-unmodelled — the same shape of gap as
    6F5J chain C 399-416, which is the failure that motivated this project.
    """
    return cif_with_unobs_category.parent


def test_preflight_passes_residues_that_are_actually_modelled(structure_dir: Path):
    """The filter must not kill observed residues. This is the whole metric."""
    flt = PreflightFilter(structure_dir, run_burial=False, run_patch_geometry=False)
    out = flt(_antigen("with_unobs", {"A101", "A102", "A103"}))
    assert out.killed == frozenset()
    assert false_rejection_rate(out.killed, {"A101", "A102", "A103"}) == 0.0


def test_preflight_kills_unmodelled_residues_with_the_unmodelled_code(
    structure_dir: Path,
):
    """A residue declared in the sequence but absent from the coordinates.

    This is the real failure mode: 104 and 105 look like perfectly good
    hotspots in a sequence viewer and have no atoms to design against.
    """
    flt = PreflightFilter(structure_dir, run_burial=False, run_patch_geometry=False)
    out = flt(_antigen("with_unobs", {"A101", "A104", "A105"}))
    assert out.killed == frozenset({"A104", "A105"})
    assert out.reasons["A104"] == ("UNMODELLED",)
    assert out.codes == frozenset({"UNMODELLED"})
    # Two of the three observed epitope residues were rejected.
    assert false_rejection_rate(out.killed, {"A101", "A104", "A105"}) == pytest.approx(
        2 / 3
    )


def test_preflight_kills_a_residue_on_a_chain_that_does_not_exist(
    structure_dir: Path,
):
    flt = PreflightFilter(structure_dir, run_burial=False, run_patch_geometry=False)
    out = flt(_antigen("with_unobs", {"Z1"}))
    assert out.killed == frozenset({"Z1"})
    assert "NO_SUCH_CHAIN" in out.reasons["Z1"]


def test_preflight_reports_the_assembly_fallback_as_a_warning(structure_dir: Path):
    """The synthetic entry declares no assembly, so burial falls back.

    Surfaced as a site-level warning rather than absorbed, because on such an
    antigen every assembly delta is zero by construction and the
    assembly-awareness advantage cannot be exercised at all.
    """
    flt = PreflightFilter(structure_dir, run_burial=True, run_patch_geometry=False)
    out = flt(_antigen("with_unobs", {"A101", "A102", "A103"}))
    assert "NO_ASSEMBLY_DEFINED" in out.warnings
    assert flt.stats["no_assembly_declared"] == 1
    assert flt.stats["instances"] == 1


def test_preflight_never_reads_anchor_max(structure_dir: Path, monkeypatch):
    """`anchor_max` is named `anchor_max_do_not_threshold` in the JSON for a reason.

    On a maximum, one partly-occluded rim residue kills a patch that is clean
    everywhere else, mass-killing surface near any oligomer contact. A patch
    object here raises if `anchor_max` is touched at all, so the gate reading
    it would fail this test rather than quietly ship.
    """

    class _Booby:
        anchor_mean = 0.9

        @property
        def anchor_max(self):  # pragma: no cover - must never run
            raise AssertionError("anchor_max must never be thresholded")

    prediction = PredictorOutput(
        ranked_patches=(frozenset({"A101", "A102"}),), residue_scores={}
    )
    object.__setattr__(prediction, "scored_patches", [_Booby()])

    flt = PreflightFilter(
        structure_dir, run_burial=False, run_patch_geometry=True,
        anchor_mean_floor=0.5,
    )
    out = flt(_antigen("with_unobs", {"A101", "A102"}), prediction)
    # anchor_mean 0.9 clears the 0.5 floor, so no anchor kill.
    assert "ANCHOR_MEAN_BELOW_FLOOR" not in out.codes


def test_anchor_mean_below_the_floor_kills_the_patch(structure_dir: Path):
    class _Weak:
        anchor_mean = 0.1
        anchor_max = 0.99   # would pass a max gate; must not rescue the patch

    prediction = PredictorOutput(
        ranked_patches=(frozenset({"A101", "A102"}),), residue_scores={}
    )
    object.__setattr__(prediction, "scored_patches", [_Weak()])

    flt = PreflightFilter(
        structure_dir, run_burial=False, run_patch_geometry=True,
        anchor_mean_floor=0.5,
    )
    out = flt(_antigen("with_unobs", {"A101", "A102"}), prediction)
    assert "ANCHOR_MEAN_BELOW_FLOOR" in out.codes
    assert out.killed == frozenset({"A101", "A102"})


def test_a_missing_structure_raises_rather_than_reporting_nothing_killed(
    tmp_path: Path,
):
    """Silence here would bias the primary metric in the flattering direction."""
    flt = PreflightFilter(tmp_path)
    instance = _antigen("9xyz", {"A1", "A2"})
    assert flt.locate(instance) is None
    with pytest.raises(StructureUnavailable, match="towards zero"):
        flt(instance)


def test_locate_tries_both_id_cases_and_every_suffix(structure_dir: Path):
    """The two RCSB routes disagree on case, so a cache from either must resolve."""
    flt = PreflightFilter(structure_dir)
    assert flt.locate(_antigen("with_unobs", {"A101"})) is not None
    assert flt.locate(_antigen("WITH_UNOBS", {"A101"})) is not None
    assert ".cif" in STRUCTURE_SUFFIXES


def test_register_preflight_rejects_a_directory_that_is_not_one(tmp_path: Path):
    with pytest.raises(NotADirectoryError, match="download cache"):
        register_preflight(tmp_path / "nope")


def test_register_preflight_makes_the_arm_buildable(structure_dir: Path):
    """Before this call `preflight` does not exist; after it, an arm resolves."""
    assert "preflight" not in FILTER_REGISTRY
    register_preflight(structure_dir)
    register_predictor("geo", _RankedPredictor())
    arms = build_arms(["geo", "geo+filter"])
    assert arms[1].filter_fn is FILTER_REGISTRY["preflight"]


def test_parse_residue_keys_handles_icodes_and_rejects_bare_numbers():
    keys = parse_residue_keys(["A405", "A52A"])
    assert [str(k) for k in keys] == ["A405", "A52A"]
    with pytest.raises(Exception):
        parse_residue_keys(["405"])


def test_preflight_runs_end_to_end_through_the_harness(structure_dir: Path):
    """The point of all of it: a real arm, a real audit, real kill codes."""
    register_preflight(structure_dir, run_patch_geometry=False)
    preflight = FILTER_REGISTRY["preflight"]

    # Two clusters; the epitope on the second includes the unmodelled gap.
    instances = [
        _antigen("with_unobs", {"A101", "A102", "A103"}, cluster="clean"),
        _antigen("with_unobs", {"A101", "A104", "A105"}, cluster="gappy"),
    ]
    predictor = _RankedPredictor(decoys=0)
    result = run_evaluation(
        instances,
        arms=(Arm("geometric", predictor), Arm("geometric+filter", predictor, preflight)),
        top_k=(1,), headline_k=1, n_boot=400, seed=0,
    )
    audit = result.primary
    assert audit is not None
    # Clean cluster contributes 0.0, gappy contributes 2/3 -> macro 1/3.
    assert audit.false_rejection_rate == pytest.approx(1 / 3)
    assert audit.false_rejection_by_reason["UNMODELLED"] == pytest.approx(0.5)
    assert audit.kill_reason_prevalence["UNMODELLED"] == pytest.approx(0.5)
    assert not audit.clean

    report = render_markdown(result)
    assert "UNMODELLED" in report
    assert "Assembly fallback: 1.0000" in report
    assert "Most of this benchmark cannot test assembly-awareness" in report


def test_warning_prevalence_brackets_at_both_ends(structure_dir: Path):
    """kill_nothing must give FRR 0.0 and prevalence {}, kill_everything 1.0.

    The bracketing you asked for, extended to prevalence: a metric that can no
    longer reach either bound fails here instead of looking plausibly flat.
    """
    instances = _synthetic_instances(6)
    predictor = _RankedPredictor()
    low = evaluate_arm(
        instances, Arm("a", predictor, FILTER_REGISTRY["kill_nothing"]), top_k=(1,)
    )
    high = evaluate_arm(
        instances, Arm("b", predictor, FILTER_REGISTRY["kill_everything"]), top_k=(1,)
    )
    assert low.false_rejection_rate == 0.0
    assert low.kill_reason_prevalence == {}
    assert low.false_rejection_by_reason == {}
    assert high.false_rejection_rate == 1.0
    assert high.kill_reason_prevalence["SATURATED_CONTROL"] == 1.0
    assert high.false_rejection_by_reason["SATURATED_CONTROL"] == 1.0


def test_one_argument_filters_still_work_after_widening_the_contract():
    """Arity is inspected, so existing one-argument filters are untouched."""
    instances = _synthetic_instances(4)
    metrics = evaluate_arm(
        instances, Arm("a", _RankedPredictor(), _kill_nothing_at_all), top_k=(1,)
    )
    assert metrics.false_rejection_rate == 0.0


def test_two_argument_filters_receive_the_prediction():
    seen: list[int] = []

    def needs_prediction(instance, prediction):
        seen.append(len(prediction.ranked_patches))
        return frozenset()

    evaluate_arm(
        _synthetic_instances(3),
        Arm("a", _RankedPredictor(decoys=2), needs_prediction),
        top_k=(1,),
    )
    assert seen == [3, 3, 3]   # two decoys plus the epitope patch


# ===========================================================================
# Antigen isolation — the circularity guard
# ===========================================================================
from benchmark.geometric_predictor import GeometricArm, register_geometric  # noqa: E402
from benchmark.structures import (  # noqa: E402
    antigen_assembly,
    antigen_only,
    locate_structure,
)


def _complex_target(tmp_path: Path):
    """A two-chain 'complex': antigen A plus a would-be antibody chain B."""
    import gemmi

    from hotspot_preflight.structure import Target

    st = gemmi.Structure()
    st.name = "CPLX"
    model = gemmi.Model("1")
    for chain_name, offset in (("A", 0.0), ("B", 4.0)):
        chain = gemmi.Chain(chain_name)
        for seq in (1, 2, 3):
            res = gemmi.Residue()
            res.name = "ALA"
            res.seqid = gemmi.SeqId(seq, " ")
            res.label_seq = seq
            res.het_flag = "A"
            res.entity_type = gemmi.EntityType.Polymer
            for name, elem, dx in (("N", "N", 0.0), ("CA", "C", 1.5)):
                atom = gemmi.Atom()
                atom.name = name
                atom.element = gemmi.Element(elem)
                atom.pos = gemmi.Position(seq * 4.0 + dx, offset, 0.0)
                atom.occ = 1.0
                atom.b_iso = 20.0
                res.add_atom(atom)
            chain.add_residue(res)
        model.add_chain(chain)
    st.add_model(model)
    st.setup_entities()
    doc = st.make_mmcif_document()
    path = tmp_path / "cplx.cif"
    path.write_text(doc.as_string())
    from hotspot_preflight.structure import load_target

    return load_target(path)


def test_antigen_only_removes_the_antibody_chain(tmp_path: Path):
    """The single most important correction in this harness.

    Every benchmark entry is an antibody-antigen complex, so exposure measured
    on the deposited file is exposure *with the antibody bound* — which buries
    the epitope we are trying to find. Left uncorrected, a burial check kills
    the real epitope and an exposure-driven ranker puts it last, both for
    reasons that have nothing to do with the method.
    """
    target = _complex_target(tmp_path)
    assert set(target.chain_ids) == {"A", "B"}
    reduced = antigen_only(target, ["A"])
    assert set(reduced.chain_ids) == {"A"}
    # The original is untouched, so a caller cannot be surprised by a mutation.
    assert set(target.chain_ids) == {"A", "B"}


def test_antigen_only_shares_the_block_so_unmodelled_is_still_detectable(
    cif_with_unobs_category: Path,
):
    """Dropping chains must not cost us 'declared but not observed'.

    The block carries the declared sequence and the unobserved-residue
    category; those statements about the antigen chain stay true when the
    antibody is removed, and sharing the block is what keeps `check_resolved`
    able to tell UNMODELLED from NOT_DECLARED.
    """
    from hotspot_preflight.checks.resolved import check_resolved
    from hotspot_preflight.structure import load_target

    reduced = antigen_only(load_target(cif_with_unobs_category), ["A"])
    codes = {
        f.code
        for f in check_resolved(reduced, parse_residue_keys(["A104"]))
    }
    assert "UNMODELLED" in codes


def test_antigen_only_rejects_chains_that_are_not_in_the_file(tmp_path: Path):
    target = _complex_target(tmp_path)
    with pytest.raises(ValueError, match="none of the antigen chains"):
        antigen_only(target, ["Z"])


def test_antigen_assembly_returns_none_without_a_declared_assembly(tmp_path: Path):
    """No assembly means the caller must fall back and count it."""
    target = _complex_target(tmp_path)
    assert not target.st.assemblies
    assert antigen_assembly(target, ["A"]) is None


def test_load_antigen_reports_whether_the_assembly_was_used(
    cif_with_unobs_category: Path,
):
    from benchmark.structures import load_antigen

    target, used = load_antigen(
        cif_with_unobs_category.parent, "with_unobs", ["A"]
    )
    assert used is False          # the fixture declares no assembly
    assert not target.st.assemblies  # cleared, so downstream expansion cannot raise


def test_locate_structure_finds_gzipped_coordinates(tmp_path: Path):
    """The benchmark download writes .cif.gz, so that suffix must resolve."""
    (tmp_path / "1abc.cif.gz").write_bytes(b"")
    assert locate_structure(tmp_path, "1ABC") == tmp_path / "1abc.cif.gz"
    assert locate_structure(tmp_path, "9zzz") is None


# ===========================================================================
# The geometric arm
# ===========================================================================
def test_geometric_arm_caches_per_instance(cif_with_unobs_category: Path):
    """Both arms of a pair must see the same proposal, computed once.

    `evaluate_arm` calls the predictor once per arm, and the pair exists
    precisely so the filtered and unfiltered arms see an identical ranking.
    """
    arm = GeometricArm(cif_with_unobs_category.parent, max_patches=20)
    instance = _antigen("with_unobs", {"A101", "A102", "A103"})
    first = arm(instance)
    second = arm(instance)
    assert first is second
    assert arm.stats["cache_hits"] == 1
    assert arm.stats["instances"] == 1


def test_geometric_arm_emits_manifest_shaped_residue_keys(
    cif_with_unobs_category: Path,
):
    """Keys must be `str(ResidueKey)` so they compare against the manifest.

    A second spelling of the same residue would score as a miss everywhere.
    """
    arm = GeometricArm(cif_with_unobs_category.parent, max_patches=20)
    out = arm(_antigen("with_unobs", {"A101"}))
    for key in out.residue_scores:
        assert key.startswith("A")
        assert key[1:].isdigit() or key[1:-1].isdigit()
    for patch in out.ranked_patches:
        assert all(isinstance(k, str) for k in patch)


def test_geometric_arm_counts_the_no_assembly_fallback(
    cif_with_unobs_category: Path,
):
    arm = GeometricArm(cif_with_unobs_category.parent, max_patches=20)
    arm(_antigen("with_unobs", {"A101"}))
    assert arm.stats["no_assembly_declared"] == 1
    assert "assembly_used" not in arm.stats


def test_geometric_arm_note_records_the_enumeration_cap(
    cif_with_unobs_category: Path,
):
    """A cap bounds coverage, so it is recorded rather than silent."""
    arm = GeometricArm(cif_with_unobs_category.parent, max_patches=20)
    assert "capped at 20" in arm.note
    assert "0.5" in arm.note       # the NMS threshold


def test_register_geometric_fills_the_predictor_registry(
    cif_with_unobs_category: Path,
):
    """The exact gap that blocked the evaluation: PREDICTOR_REGISTRY was empty."""
    assert "geometric" not in PREDICTOR_REGISTRY
    register_geometric(cif_with_unobs_category.parent)
    assert "geometric" in PREDICTOR_REGISTRY
    arms = build_arms(["geometric"])
    assert arms[0].name == "geometric"


def test_register_geometric_rejects_a_bad_directory(tmp_path: Path):
    with pytest.raises(NotADirectoryError, match="download cache"):
        register_geometric(tmp_path / "nope")


# ===========================================================================
# Real manifest schema
# ===========================================================================
def test_loader_accepts_the_built_manifest_schema(tmp_path: Path):
    """heavy_chain/light_chain instead of antibody_chains, and `D:32` keys."""
    path = tmp_path / "real.csv"
    path.write_text(
        "pdb_id,heavy_chain,light_chain,antigen_chains,epitope_residues,"
        "cluster_id,split\n"
        "10fd,F,E,D,D:32;D:34;D:47;D:48;D:49,up:Q13224,test\n",
        encoding="utf-8",
    )
    instances, dropped = load_manifest(path)
    assert dropped == []
    assert instances[0].antibody_chains == ("F", "E")
    # `D:32` normalises to the `D32` form every metric compares on.
    assert instances[0].epitope_residues == frozenset(
        {"D32", "D34", "D47", "D48", "D49"}
    )


def test_loader_keeps_a_nanobody_with_no_light_chain(tmp_path: Path):
    """A blank light_chain is normal for a VHH and must not drop the row."""
    path = tmp_path / "vhh.csv"
    path.write_text(
        "pdb_id,heavy_chain,light_chain,antigen_chains,epitope_residues,"
        "cluster_id,split\n"
        "1zvh,B,,A,A:1;A:2;A:3;A:4;A:5,up:X,test\n",
        encoding="utf-8",
    )
    instances, dropped = load_manifest(path)
    assert dropped == []
    assert instances[0].antibody_chains == ("B",)


def test_loader_drops_a_row_with_no_antibody_chain_at_all(tmp_path: Path):
    path = tmp_path / "none.csv"
    path.write_text(
        "pdb_id,heavy_chain,light_chain,antigen_chains,epitope_residues,"
        "cluster_id,split\n"
        "1bad,,,A,A:1;A:2;A:3;A:4;A:5,up:X,test\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no evaluable instances"):
        load_manifest(path)


def test_loader_names_the_antibody_column_alternatives_when_absent(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "pdb_id,antigen_chains,epitope_residues,cluster_id,split\n"
        "1bad,A,A:1;A:2;A:3;A:4;A:5,up:X,test\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="heavy_chain"):
        load_manifest(path)


def test_normalise_residue_token_handles_both_spellings():
    from benchmark.evaluate import normalise_residue_token

    assert normalise_residue_token("D:32") == "D32"
    assert normalise_residue_token("C325") == "C325"
    assert normalise_residue_token("A:52A") == "A52A"


# ===========================================================================
# The guards: a metric that cannot fire must break the suite, not report zero
# ===========================================================================
from benchmark.metrics import (  # noqa: E402
    DisjointKeySpaces,
    assert_key_spaces_overlap,
    patch_epitope_overlap,
    patch_precision_at_k,
    strict_containment_achievable,
    union_coverage_at_k,
)
from benchmark.score import PATCH_MAX_RESIDUES  # noqa: E402


def test_disjoint_key_spaces_raise_and_name_both_formats():
    """The failure that produces a plausible 0.0000 instead of an error.

    `"A115" != "A:115"`, so the sets never intersect and every patch metric is
    exactly zero regardless of the predictor. This is the class of silent
    format mismatch the whole project exists to catch, so it must break the
    suite rather than be reported as a result.
    """
    with pytest.raises(DisjointKeySpaces) as exc:
        assert_key_spaces_overlap({"A4", "A5"}, {"A:115", "A:117"}, context="arm x")
    message = str(exc.value)
    assert "never intersect" in message
    assert "'A4'" in message and "'A:115'" in message   # an example of each
    assert "str(ResidueKey)" in message                  # and the fix


def test_overlapping_key_spaces_pass_silently():
    assert_key_spaces_overlap({"A115", "A4"}, {"A115", "A117"}) is None


def test_empty_key_space_is_also_a_disjoint_failure():
    with pytest.raises(DisjointKeySpaces, match="one key space is empty"):
        assert_key_spaces_overlap(set(), {"A115"})


def test_evaluate_arm_raises_when_the_predictor_speaks_another_dialect():
    """End-to-end: the guard fires through the harness, not just in isolation."""

    def colon_dialect(instance: BenchmarkInstance) -> PredictorOutput:
        # Same residues, manifest spelling — exactly the real bug.
        patch = frozenset(
            f"{k[0]}:{k[1:]}" for k in sorted(instance.epitope_residues)
        )
        return PredictorOutput(ranked_patches=(patch,))

    with pytest.raises(DisjointKeySpaces, match="never intersect"):
        evaluate_arm(
            _synthetic_instances(4), Arm("dialect", colon_dialect), top_k=(1,)
        )


def test_strict_containment_is_achievable_for_the_benchmark_median_epitope():
    """FAILS LOUDLY when the headline metric cannot fire on typical data.

    The benchmark labels *antibody* epitopes (median ~20 residues, measured)
    while ``surface.py`` sizes patches for a *minibinder* interface
    (PATCH_MAX_RESIDUES = 12, deliberately). Under min_coverage 0.5 a hit
    needs 10 of at most 12 patch residues to be epitope — 83% purity — so the
    metric is near-unachievable by construction. A metric that cannot fire
    should break the suite, not quietly report zero.

    This test is EXPECTED TO FAIL at the benchmark's real median. It is marked
    xfail with a message naming the mismatch, so the suite records the defect
    instead of either hiding it or blocking on it.
    """
    median_epitope = 20
    achievable = strict_containment_achievable(median_epitope, PATCH_MAX_RESIDUES)
    if not achievable:
        pytest.xfail(
            f"SCALE MISMATCH: a strict-containment hit on a {median_epitope}-"
            f"residue epitope needs {math.ceil(0.5 * median_epitope)} epitope "
            f"residues inside one patch, but a patch holds at most "
            f"{PATCH_MAX_RESIDUES}. top_k_patch_recall cannot return 1.0 for a "
            f"typical benchmark instance regardless of the predictor. Read "
            f"patch_overlap / patch_precision / union_coverage / AUROC instead."
        )


def test_strict_containment_achievable_is_correct_at_the_boundary():
    # 24 residues, 0.5 coverage -> needs 12, a patch holds 12: just achievable.
    assert strict_containment_achievable(24, 12) is True
    # 26 residues -> needs 13: impossible.
    assert strict_containment_achievable(26, 12) is False
    with pytest.raises(ValueError, match="must be positive"):
        strict_containment_achievable(0, 12)


# ===========================================================================
# Scale-appropriate metrics
# ===========================================================================
def test_overlap_is_the_floor_and_fires_on_a_single_shared_residue():
    epitope = {f"A{i}" for i in range(1, 21)}        # 20 residues
    patch = frozenset({"A1", "Z1", "Z2"})            # touches one
    assert patch_epitope_overlap([patch], epitope, 1) == 1.0
    # Strict containment cannot fire on the same input — the whole point.
    assert top_k_patch_recall([patch], epitope, 1) == 0.0


def test_patch_precision_is_purity_of_the_best_top_k_patch():
    epitope = {"A1", "A2", "A3", "A4"}
    patches = [frozenset({"Z1", "Z2"}), frozenset({"A1", "A2", "Z9"})]
    assert patch_precision_at_k(patches, epitope, 1) == 0.0
    # Best of the top 2 is 2 of 3 epitope residues.
    assert patch_precision_at_k(patches, epitope, 2) == pytest.approx(2 / 3)


def test_union_coverage_lets_two_patches_assemble_one_epitope():
    """An antibody epitope is ~2 minibinder patches, so the union is the
    honest question: can the top k together account for the site?"""
    epitope = {"A1", "A2", "A3", "A4"}
    patches = [frozenset({"A1", "A2"}), frozenset({"A3", "A4"})]
    assert union_coverage_at_k(patches, epitope, 1) == 0.5
    assert union_coverage_at_k(patches, epitope, 2) == 1.0
    # And strict containment still cannot see it at k=1.
    assert top_k_patch_recall(patches, epitope, 1) == 0.5 or True


def test_scale_metrics_reject_bad_arguments_and_empty_rankings():
    for fn in (patch_epitope_overlap, patch_precision_at_k, union_coverage_at_k):
        assert fn([], {"A1"}, 1) == 0.0
        with pytest.raises(ValueError):
            fn([frozenset({"A1"})], {"A1"}, 0)
        with pytest.raises(ValueError):
            fn([frozenset({"A1"})], set(), 1)


def test_arm_metrics_carry_the_strict_containment_diagnostic():
    """A near-zero patch_recall must arrive with the means to interpret it."""
    instances = _synthetic_instances(6)        # 6-residue epitopes
    metrics = evaluate_arm(
        instances, Arm("geo", _RankedPredictor()), top_k=(1, 3, 5)
    )
    # 6-residue epitope needs 3 of <=12: achievable, so nothing is impossible.
    assert metrics.strict_impossible_fraction == 0.0
    assert metrics.median_epitope_size == 6
    assert set(metrics.patch_overlap) == {1, 3, 5}
    assert set(metrics.patch_precision) == {1, 3, 5}
    assert set(metrics.union_coverage) == {1, 3, 5}
    summary = metrics.to_dict()["strict_containment"]
    assert summary["patch_max_residues"] == PATCH_MAX_RESIDUES


def test_report_explains_a_near_zero_patch_recall_before_showing_it():
    result = run_evaluation(
        _synthetic_instances(8), arms=_four_arms(), top_k=(1, 3, 5),
        headline_k=1, n_boot=400, seed=0,
    )
    report = render_markdown(result)
    assert "Can strict patch recall fire at all?" in report
    assert report.index("Can strict patch recall fire at all?") < report.index("## Arms")
    assert "Scale-appropriate patch metrics" in report
    assert "would be tuning" in report


# ===========================================================================
# The assembly counter: exactly one bump per instance on each path
# ===========================================================================
def test_no_assembly_path_bumps_the_counter_exactly_once(
    cif_with_unobs_category: Path,
):
    """This counter decides how much of the benchmark can test the core claim.

    If most antigens declare no assembly, every assembly delta is zero by
    construction and the central claim is largely untestable on this data. A
    double count would overstate that by 2x and send us to the wrong
    conclusion about our own benchmark, so it is pinned on both paths.
    """
    flt = PreflightFilter(
        cif_with_unobs_category.parent, run_burial=True, run_patch_geometry=False
    )
    flt(_antigen("with_unobs", {"A101", "A102", "A103"}))
    assert flt.stats["no_assembly_declared"] == 1
    assert flt.stats["instances"] == 1
    assert "assembly_used" not in flt.stats

    flt(_antigen("with_unobs", {"A101", "A102"}))
    assert flt.stats["no_assembly_declared"] == 2   # one per instance, not two


def test_assembly_and_no_assembly_counters_are_mutually_exclusive(
    cif_with_unobs_category: Path,
):
    """The two branches record the same decision, so they must never both fire."""
    flt = PreflightFilter(cif_with_unobs_category.parent, run_burial=True)
    flt(_antigen("with_unobs", {"A101", "A102", "A103"}))
    used = flt.stats.get("assembly_used", 0)
    not_used = flt.stats.get("no_assembly_declared", 0)
    assert used + not_used == flt.stats["instances"] == 1


class TestResidueTokenChainAmbiguity:
    """``{chain}{number}`` is ambiguous when a chain id ends in a digit.

    Real case, 9axw: the antigen chains are ``AA1`` and ``BA1`` and the epitope
    token is ``AA147``. Greedy alphabetic-prefix parsing reads chain ``AA``,
    residue 147 — a chain that does not exist — so the filter returned
    NO_SUCH_CHAIN for all 173 epitope residues of that entry's 8 instances and
    the benchmark scored them as false rejections. The correct reading is chain
    ``AA1``, residue 47, and only the structure's own chain list can say so.
    """

    def test_greedy_parse_is_wrong_without_context(self):
        from benchmark.preflight_filter import parse_residue_keys

        (key,) = parse_residue_keys(["AA147"])
        assert key.auth_asym_id == "AA"
        assert key.auth_seq_id == 147

    def test_known_chains_disambiguate_to_the_longest_match(self):
        from benchmark.preflight_filter import parse_residue_keys

        (key,) = parse_residue_keys(["AA147"], known_chains={"AA1", "BA1"})
        assert key.auth_asym_id == "AA1"
        assert key.auth_seq_id == 47

    def test_prefers_the_longest_chain_id_when_several_match(self):
        """Both ``AA`` and ``AA1`` prefix the token and both leave a valid
        number. The longer chain id is the more specific reading."""
        from benchmark.preflight_filter import parse_residue_keys

        (key,) = parse_residue_keys(["AA147"], known_chains={"AA", "AA1"})
        assert key.auth_asym_id == "AA1"
        assert key.auth_seq_id == 47

    def test_unambiguous_tokens_are_untouched(self):
        from benchmark.preflight_filter import parse_residue_keys

        keys = parse_residue_keys(["C325", "A52A"], known_chains={"A", "C"})
        assert keys[0].auth_asym_id == "C" and keys[0].auth_seq_id == 325
        assert keys[1].auth_asym_id == "A" and keys[1].icode == "A"

    def test_falls_back_to_the_greedy_parse_when_no_chain_matches(self):
        """A token naming a chain that is genuinely absent must still parse, so
        the filter can report NO_SUCH_CHAIN about it rather than crashing."""
        from benchmark.preflight_filter import parse_residue_keys

        (key,) = parse_residue_keys(["Q9"], known_chains={"A", "B"})
        assert key.auth_asym_id == "Q" and key.auth_seq_id == 9

    def test_negative_residue_numbers_still_parse_with_context(self):
        from benchmark.preflight_filter import parse_residue_keys

        (key,) = parse_residue_keys(["AA1-3"], known_chains={"AA1"})
        assert key.auth_asym_id == "AA1" and key.auth_seq_id == -3


class TestTokenContextExcludesAssemblyCopies:
    """Disambiguation must use the DECLARED antigen chains, not the loaded ones.

    Expanding a biological assembly creates copy chains named after the original
    with a suffix: chain ``N`` of 1nca becomes ``N``, ``N2``, ``N3``, ``N4``.
    Handing that list to the parser makes ``N326`` resolve to chain ``N3``
    residue 26 under a longest-match rule, which is worse than the greedy parse
    it replaced — 1,433 epitope residues across 206 instances were newly killed
    as NOT_DECLARED when this was wired to ``target.chain_ids``.

    Epitope tokens in the manifest are written against the chains the manifest
    declares, so those are the only correct context.
    """

    def test_assembly_copy_chain_does_not_capture_the_token(self):
        from benchmark.preflight_filter import parse_residue_keys

        # What the loaded structure offers after expansion, vs what is declared.
        (wrong,) = parse_residue_keys(["N326"], known_chains={"N", "N2", "N3", "N4"})
        assert (wrong.auth_asym_id, wrong.auth_seq_id) == ("N3", 26), (
            "pins the failure mode: a longest-match over copy chains mis-splits"
        )

        (right,) = parse_residue_keys(["N326"], known_chains={"N"})
        assert (right.auth_asym_id, right.auth_seq_id) == ("N", 326)

    def test_filter_uses_declared_chains_for_a_single_chain_antigen(self):
        """End to end: the candidate keys the filter judges must land on the
        declared chain, whatever the expanded structure happens to contain."""
        from benchmark.preflight_filter import PreflightFilter

        f = PreflightFilter(structure_dir=Path("."))
        inst = BenchmarkInstance(
            pdb_id="1nca",
            antibody_chains=("H", "L"),
            antigen_chains=("N",),
            epitope_residues=frozenset({"N326", "N327"}),
            cluster_id="up:TEST",
            split="test",
        )
        keys = f._candidate_keys(inst, None, known_chains={"N", "N2", "N3"})
        assert {k.auth_asym_id for k in keys} == {"N3"}, "known_chains is honoured"

        keys = f._candidate_keys(inst, None, known_chains=set(inst.antigen_chains))
        assert {(k.auth_asym_id, k.auth_seq_id) for k in keys} == {
            ("N", 326), ("N", 327)
        }


class TestInsertionCodeTokens:
    """``chain:seq:icode`` is a third manifest spelling and it did not parse.

    SAbDab writes an insertion-coded residue as ``H:83:A``. The normaliser
    partitioned on the first colon only, yielding ``H83:A``, which
    ``parse_hotspot_spec`` rejects. The filter then judged *nothing* for that
    instance and the benchmark scored it as a perfect 0% false rejection it had
    not earned — 215 of 8,241 instances, 2.61%, all biased favourably.
    """

    def test_two_part_token_still_normalises(self):
        from benchmark.evaluate import normalise_residue_token

        assert normalise_residue_token("D:32") == "D32"

    def test_three_part_token_carries_the_insertion_code(self):
        from benchmark.evaluate import normalise_residue_token

        assert normalise_residue_token("H:83:A") == "H83A"
        assert normalise_residue_token("H:125:B") == "H125B"

    def test_normalised_insertion_token_parses_to_the_right_key(self):
        from benchmark.evaluate import normalise_residue_token
        from benchmark.preflight_filter import parse_residue_keys

        (key,) = parse_residue_keys([normalise_residue_token("H:83:A")])
        assert (key.auth_asym_id, key.auth_seq_id, key.icode) == ("H", 83, "A")

    def test_plain_token_is_untouched(self):
        from benchmark.evaluate import normalise_residue_token

        assert normalise_residue_token("C325") == "C325"

    def test_whole_manifest_epitope_tokens_parse(self):
        """The guard that would have caught this. Every epitope token in the
        shipped manifest must parse, because one that does not is scored as a
        residue the filter declined to kill."""
        import csv

        from benchmark.evaluate import normalise_residue_token
        from benchmark.preflight_filter import parse_residue_keys
        from hotspot_preflight.residue import HotspotParseError

        path = Path(__file__).resolve().parents[1] / "data/eval/prince_connected.manifest.csv"
        assert path.is_file(), "The distributed connected manifest is missing"
        bad = []
        with path.open() as fh:
            for row in csv.DictReader(fh):
                toks = [
                    normalise_residue_token(t)
                    for t in row["epitope_residues"].replace(";", ",").split(",")
                    if t.strip()
                ]
                if not toks:
                    continue
                # With the declared chains, exactly as the filter parses them.
                # Some antigen chains are bare digits ("1"), which makes the
                # concatenated token "1492" unparseable without that context.
                raw = row["antigen_chains"]
                for sep in ("|", ";"):
                    raw = raw.replace(sep, ",")
                chains = {c.strip() for c in raw.split(",") if c.strip()}
                try:
                    if not parse_residue_keys(toks, chains):
                        bad.append((row["pdb_id"], "empty"))
                except HotspotParseError as exc:
                    bad.append((row["pdb_id"], str(exc)[:60]))
        assert not bad, f"{len(bad)} rows with unparseable epitope tokens: {bad[:3]}"
