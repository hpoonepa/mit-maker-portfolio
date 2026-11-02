# SPDX-License-Identifier: MIT
"""Scoring one arm: per-instance metrics, macro-averaged by antigen cluster.

Split out of :mod:`benchmark.arms` so that the arm *definitions* (what a
predictor is, what a filter may return) stay readable apart from the loop that
drives them. :func:`evaluate_arm` is the only place a predictor or filter is
actually called, which is why it is also the only place that has to care about
kill-reason bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Collection, Hashable, Sequence

from .arms import (
    DEFAULT_TOP_K,
    Arm,
    BenchmarkInstance,
    FilterOutput,
    FilterPolicy,
    PredictorOutput,
    apply_filter,
    call_filter,
    normalise_filter_output,
)
from .bootstrap import macro_average_by_cluster, micro_average

LOGGER = __import__("logging").getLogger(__name__)

#: Log progress every N instances. A run that prints nothing for twenty
#: minutes and then dies tells you nothing about where it died.
PROGRESS_EVERY = 50
from .metrics import (
    assert_key_spaces_overlap,
    false_rejection_rate,
    patch_epitope_overlap,
    patch_precision_at_k,
    per_residue_auprc,
    per_residue_auroc,
    strict_containment_achievable,
    top_k_patch_recall,
    union_coverage_at_k,
)

#: ``surface.PATCH_MAX_RESIDUES``. Hardcoded rather than imported so this
#: module keeps no dependency on the structural library and stays testable
#: without it; the achievability diagnostic below fails loudly if the real
#: value drifts below what the benchmark's epitopes need.
PATCH_MAX_RESIDUES = 12

__all__ = ["ArmMetrics", "evaluate_arm"]


@dataclass(frozen=True)
class ArmMetrics:
    """Aggregated metrics for one arm, plus the per-instance detail.

    Headline fields are cluster macro-averages by default; ``micro`` holds the
    per-instance means of the same quantities, for comparison.
    """

    arm: str
    n_instances: int
    n_clusters: int
    patch_recall: dict[int, float]
    false_rejection_rate: float
    auroc: float
    auprc: float
    #: Scale-appropriate companions to ``patch_recall``. The benchmark labels
    #: antibody epitopes (median ~20 residues) while patches are sized for a
    #: minibinder interface (<=12), so strict containment asks the wrong
    #: question; these ask ones the units support. See benchmark.metrics.
    patch_overlap: dict[int, float] = field(default_factory=dict)
    patch_precision: dict[int, float] = field(default_factory=dict)
    union_coverage: dict[int, float] = field(default_factory=dict)
    #: Fraction of instances where strict containment is arithmetically
    #: IMPOSSIBLE given PATCH_MAX_RESIDUES. A reader seeing a near-zero
    #: ``patch_recall`` must be able to tell "could not fire" from "failed".
    strict_impossible_fraction: float = 0.0
    median_epitope_size: float = 0.0
    # Kill-reason prevalence: per code, the macro-averaged fraction of
    # instances on which that code fired at all, and the fraction on which it
    # killed an experimentally observed epitope residue. The second is the
    # triage list — it names which check is responsible for each false
    # rejection, instead of leaving one aggregate rate to argue about.
    kill_reason_prevalence: dict[str, float] = field(default_factory=dict)
    false_rejection_by_reason: dict[str, float] = field(default_factory=dict)
    #: Site-level WARN codes, chiefly NO_ASSEMBLY_DEFINED. Reported so a
    #: benchmark where most antigens declare no assembly cannot quietly look
    #: like one where assembly-awareness was exercised.
    warning_prevalence: dict[str, float] = field(default_factory=dict)
    per_instance: tuple[dict[str, object], ...] = ()
    micro: dict[str, float] = field(default_factory=dict)
    note: str = ""

    def to_dict(self, *, include_per_instance: bool = False) -> dict[str, object]:
        out: dict[str, object] = {
            "arm": self.arm,
            "n_instances": self.n_instances,
            "n_clusters": self.n_clusters,
            "patch_recall": {
                str(k): v for k, v in sorted(self.patch_recall.items())
            },
            "patch_overlap": {str(k): v for k, v in sorted(self.patch_overlap.items())},
            "patch_precision": {
                str(k): v for k, v in sorted(self.patch_precision.items())
            },
            "union_coverage": {
                str(k): v for k, v in sorted(self.union_coverage.items())
            },
            "strict_containment": {
                "impossible_fraction": self.strict_impossible_fraction,
                "median_epitope_size": self.median_epitope_size,
                "patch_max_residues": PATCH_MAX_RESIDUES,
            },
            "false_rejection_rate": self.false_rejection_rate,
            "auroc": self.auroc,
            "auprc": self.auprc,
            "kill_reason_prevalence": dict(sorted(self.kill_reason_prevalence.items())),
            "false_rejection_by_reason": dict(
                sorted(self.false_rejection_by_reason.items())
            ),
            "warning_prevalence": dict(sorted(self.warning_prevalence.items())),
            "note": self.note,
        }
        if self.micro:
            out["micro"] = dict(sorted(self.micro.items()))
        if include_per_instance:
            out["per_instance"] = [
                dict(sorted(r.items())) for r in self.per_instance
            ]
        return out


def _macro_or_nan(values: Sequence[float], clusters: Sequence[Hashable]) -> float:
    """Macro-average, NaN instead of raising when nothing is finite.

    An arm whose predictor emits no residue scores has no AUROC: a legitimate
    NaN to carry into the report, not an error to abort on.
    """
    try:
        return macro_average_by_cluster(values, clusters)
    except ValueError:
        return float("nan")


def _micro_or_nan(values: Sequence[float]) -> float:
    try:
        return micro_average(values)
    except ValueError:
        return float("nan")


def _score_residues(
    instance: BenchmarkInstance, prediction: PredictorOutput
) -> tuple[float, float]:
    """Per-residue AUROC/AUPRC for one instance, or NaN when undefined.

    NaN rather than a substituted 0.5: a filled-in value would be
    indistinguishable from a measured one in the report.
    """
    scores_map = prediction.residue_scores
    if not scores_map:
        return float("nan"), float("nan")
    keys = sorted(scores_map)
    scores = [float(scores_map[key]) for key in keys]
    labels = [key in instance.epitope_residues for key in keys]
    try:
        return per_residue_auroc(scores, labels), per_residue_auprc(scores, labels)
    except ValueError:
        return float("nan"), float("nan")


def evaluate_arm(
    instances: Sequence[BenchmarkInstance],
    arm: Arm,
    *,
    top_k: Sequence[int] = DEFAULT_TOP_K,
    policy: FilterPolicy = FilterPolicy.DROP_PATCH,
    macro: bool = True,
) -> ArmMetrics:
    """Score one arm over the benchmark.

    ``arm.predictor`` and ``arm.filter_fn`` are the only things that could
    touch the world; injecting them keeps this testable on synthetic data.
    ``macro=False`` opts into the per-instance micro-average for the headline
    fields too, and is labelled as such in the report.
    """
    if not instances:
        raise ValueError(
            f"arm {arm.name!r} received zero instances; nothing to average over"
        )

    clusters: list[str] = []
    recall_rows: dict[int, list[float]] = {k: [] for k in top_k}
    overlap_rows: dict[int, list[float]] = {k: [] for k in top_k}
    precision_rows: dict[int, list[float]] = {k: [] for k in top_k}
    union_rows: dict[int, list[float]] = {k: [] for k in top_k}
    epitope_sizes: list[int] = []
    impossible: list[float] = []
    pooled_predicted: set[str] = set()
    pooled_epitope: set[str] = set()
    frr_rows: list[float] = []
    auroc_rows: list[float] = []
    auprc_rows: list[float] = []
    detail: list[dict[str, object]] = []

    # code -> per-instance 0/1, one list per code, so prevalence can be
    # macro-averaged by cluster exactly like every other metric.
    fired_rows: dict[str, list[float]] = {}
    false_kill_rows: dict[str, list[float]] = {}
    warned_rows: dict[str, list[float]] = {}

    for position, instance in enumerate(instances):
        if position and position % PROGRESS_EVERY == 0:
            LOGGER.info(
                "arm %s: %d/%d instances", arm.name, position, len(instances)
            )
        prediction = arm.predictor(instance)
        verdict = (
            call_filter(arm.filter_fn, instance, prediction)
            if arm.filter_fn is not None
            else FilterOutput(frozenset())
        )
        killed = verdict.killed
        patches = (
            apply_filter(prediction.ranked_patches, killed, policy)
            if arm.filter_fn is not None
            else tuple(frozenset(p) for p in prediction.ranked_patches)
        )

        clusters.append(instance.cluster_id)
        row: dict[str, object] = {
            "instance_id": instance.instance_id,
            "cluster_id": instance.cluster_id,
            "n_epitope_residues": len(instance.epitope_residues),
            "n_patches_proposed": len(prediction.ranked_patches),
            "n_patches_surviving": len(patches),
            "n_killed_residues": len(killed),
        }
        epitope_sizes.append(len(instance.epitope_residues))
        impossible.append(
            0.0
            if strict_containment_achievable(
                len(instance.epitope_residues), PATCH_MAX_RESIDUES
            )
            else 1.0
        )
        pooled_epitope |= set(instance.epitope_residues)
        # Pooled from the PREDICTOR's proposals, before the filter. The join
        # question is whether the predictor's key space and the manifest's can
        # intersect at all, which is a property of the two formats and nothing
        # to do with the filter. A filter that legitimately removes every
        # epitope-containing patch would otherwise make the surviving keys
        # disjoint and trip the guard for the wrong reason.
        for patch in prediction.ranked_patches:
            pooled_predicted |= set(patch)

        for k in top_k:
            value = top_k_patch_recall(patches, instance.epitope_residues, k)
            recall_rows[k].append(value)
            row[f"patch_recall_at_{k}"] = value
            overlap_rows[k].append(
                patch_epitope_overlap(patches, instance.epitope_residues, k)
            )
            precision_rows[k].append(
                patch_precision_at_k(patches, instance.epitope_residues, k)
            )
            union_rows[k].append(
                union_coverage_at_k(patches, instance.epitope_residues, k)
            )
        frr = false_rejection_rate(killed, instance.epitope_residues)
        frr_rows.append(frr)
        row["false_rejection_rate"] = frr

        # Back-fill any code first seen on a later instance with zeros for the
        # instances already walked, so every code's list stays aligned with
        # `clusters`. A ragged list would silently compute a prevalence over
        # the wrong denominator.
        fired = verdict.codes
        false_kill_codes = {
            code
            for key, codes in verdict.reasons.items()
            if key in instance.epitope_residues
            for code in codes
        }
        warned = set(verdict.warnings)
        for code in fired | false_kill_codes:
            fired_rows.setdefault(code, [0.0] * position)
            false_kill_rows.setdefault(code, [0.0] * position)
        for code in warned:
            warned_rows.setdefault(code, [0.0] * position)
        for code, values in fired_rows.items():
            values.append(1.0 if code in fired else 0.0)
        for code, values in false_kill_rows.items():
            values.append(1.0 if code in false_kill_codes else 0.0)
        for code, values in warned_rows.items():
            values.append(1.0 if code in warned else 0.0)
        row["kill_reasons"] = sorted(fired)
        row["false_kill_reasons"] = sorted(false_kill_codes)
        row["warnings"] = sorted(warned)

        auroc, auprc = _score_residues(instance, prediction)
        auroc_rows.append(auroc)
        auprc_rows.append(auprc)
        row["auroc"] = auroc
        row["auprc"] = auprc
        detail.append(row)

    # One guard per run over the POOLED keys. A single antigen legitimately
    # has patches that miss its epitope; a whole benchmark whose two key
    # spaces never intersect is a format mismatch producing a plausible 0.0000
    # on every instance, which is the failure class this project exists to
    # catch. Only checked when the arm actually proposed something.
    if pooled_predicted:
        assert_key_spaces_overlap(
            pooled_predicted, pooled_epitope, context=f"arm {arm.name!r}"
        )

    def aggregate(values: Sequence[float]) -> float:
        return _macro_or_nan(values, clusters) if macro else _micro_or_nan(values)

    return ArmMetrics(
        arm=arm.name,
        n_instances=len(instances),
        n_clusters=len(set(clusters)),
        patch_recall={k: aggregate(recall_rows[k]) for k in top_k},
        patch_overlap={k: aggregate(overlap_rows[k]) for k in top_k},
        patch_precision={k: aggregate(precision_rows[k]) for k in top_k},
        union_coverage={k: aggregate(union_rows[k]) for k in top_k},
        strict_impossible_fraction=_micro_or_nan(impossible),
        median_epitope_size=(
            float(sorted(epitope_sizes)[len(epitope_sizes) // 2])
            if epitope_sizes else 0.0
        ),
        false_rejection_rate=aggregate(frr_rows),
        auroc=aggregate(auroc_rows),
        auprc=aggregate(auprc_rows),
        kill_reason_prevalence={
            code: aggregate(values) for code, values in sorted(fired_rows.items())
        },
        false_rejection_by_reason={
            code: aggregate(values)
            for code, values in sorted(false_kill_rows.items())
        },
        warning_prevalence={
            code: aggregate(values) for code, values in sorted(warned_rows.items())
        },
        per_instance=tuple(detail),
        micro={
            **{
                f"patch_recall_at_{k}": _micro_or_nan(recall_rows[k])
                for k in top_k
            },
            "false_rejection_rate": _micro_or_nan(frr_rows),
            "auroc": _micro_or_nan(auroc_rows),
            "auprc": _micro_or_nan(auprc_rows),
        },
        note=arm.note,
    )
