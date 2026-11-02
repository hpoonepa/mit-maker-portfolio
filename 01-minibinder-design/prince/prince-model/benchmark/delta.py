# SPDX-License-Identifier: MIT
"""Comparing two arms: a paired delta, its interval, and what it is allowed to say.

One module for the step where the project's claim is actually made or
withheld. The pairing is instance-by-instance and the resampling is by antigen
cluster, in that order, because the two arms saw the same antigens: pairing
first cancels the between-antigen variance that would otherwise swamp the
filter's effect, and collapsing second stops a heavily-crystallised antigen
voting once per deposited complex.

:meth:`ArmDelta.sentence` is deliberately the only place a delta is turned
into prose, so the rule that a zero-spanning interval must be reported as
INCONCLUSIVE — in those words — is enforced in one place rather than trusted
to each caller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .score import ArmMetrics
from typing import Mapping

from .bootstrap import (
    BcaInterval,
    Zone,
    cluster_means,
    paired_bca_ci,
    power_statement,
    three_zone_verdict,
)

__all__ = [
    "ArmDelta", "paired_delta", "delta_to_dict", "PrimaryAudit",
    "audit_filter", "SUPERIORITY_COMPUTED", "SUPERIORITY_NO_EXTERNAL_ARM",
    "SUPERIORITY_NO_PAIR",
]


@dataclass(frozen=True)
class ArmDelta:
    """A paired delta between two arms on one endpoint, with its interval."""

    baseline: str
    candidate: str
    endpoint: str
    interval: BcaInterval
    verdict: Zone
    power: str

    @property
    def inconclusive(self) -> bool:
        return self.verdict is Zone.INCONCLUSIVE

    def sentence(self) -> str:
        """One line stating the delta and, when it applies, that it is null.

        The phrase "spans zero" is required wording: a reader scanning the
        report must not be able to take away a point estimate from a result
        that has none.
        """
        ci = self.interval
        head = (
            f"{self.candidate} - {self.baseline} on {self.endpoint}: "
            f"delta = {ci.point:+.4f}, 95% BCa CI "
            f"[{ci.lo:+.4f}, {ci.hi:+.4f}] over n = {ci.n} clusters"
        )
        if ci.spans_zero:
            return (
                f"{head}. The confidence interval spans zero, so this result "
                f"is INCONCLUSIVE: we cannot say the filter helps or hurts on "
                f"this endpoint. {self.power}"
            )
        direction = "improves" if ci.point > 0 else "degrades"
        return (
            f"{head}. The interval excludes zero; the filter {direction} this "
            f"endpoint."
        )


def paired_delta(
    baseline: ArmMetrics,
    candidate: ArmMetrics,
    endpoint: str,
    *,
    n_boot: int,
    seed: int,
) -> ArmDelta:
    """Pair two arms instance-by-instance, collapse by cluster, bootstrap.

    Pairing before collapsing is what makes this a paired test: both arms saw
    the same antigens, so between-antigen variance cancels instead of swamping
    the filter's effect.
    """
    base_by_id = {r["instance_id"]: r for r in baseline.per_instance}
    deltas: list[float] = []
    clusters: list[str] = []
    for row in candidate.per_instance:
        base_row = base_by_id.get(row["instance_id"])
        if base_row is None:
            continue
        a = float(base_row[endpoint])  # type: ignore[arg-type]
        b = float(row[endpoint])  # type: ignore[arg-type]
        if math.isfinite(a) and math.isfinite(b):
            deltas.append(b - a)
            clusters.append(str(row["cluster_id"]))

    per_cluster = cluster_means(deltas, clusters)
    interval = paired_bca_ci(
        [per_cluster[key] for key in sorted(per_cluster, key=str)],
        n_boot=n_boot,
        seed=seed,
    )
    return ArmDelta(
        baseline=baseline.arm,
        candidate=candidate.arm,
        endpoint=endpoint,
        interval=interval,
        verdict=three_zone_verdict(interval),
        power=power_statement(interval.point, interval.n),
    )


# ---------------------------------------------------------------------------


def delta_to_dict(delta: ArmDelta) -> dict[str, object]:
    return {
        "baseline": delta.baseline,
        "candidate": delta.candidate,
        "endpoint": delta.endpoint,
        "verdict": delta.verdict.value,
        "power": delta.power,
        "sentence": delta.sentence(),
        **delta.interval.to_dict(),
    }


# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrimaryAudit:
    """**The primary reported result**: false rejection and kill-reason prevalence.

    This is the primary result rather than the superiority delta because it is
    answerable from the data we actually hold. "How often does each kill
    reason fire, and how often does it fire on a residue an antibody was
    observed to touch" needs only the manifest and our own filter. "Our filter
    improves a SOTA predictor's top-k" additionally needs that predictor, and
    the external arm may not be runnable at all.

    ``false_rejection_ci`` is a one-sample cluster bootstrap of the mean
    per-cluster false-rejection rate. Its ``sign_test_p`` and ``wilcoxon_p``
    are meaningless here — those test a paired delta against zero, and this is
    not a delta — so they are omitted from the summary rather than printed as
    if they meant something.
    """

    arm: str
    false_rejection_rate: float
    false_rejection_ci: BcaInterval
    kill_reason_prevalence: Mapping[str, float]
    false_rejection_by_reason: Mapping[str, float]
    n_instances: int
    n_clusters: int

    @property
    def clean(self) -> bool:
        """True when the filter killed no observed epitope residue anywhere."""
        return self.false_rejection_rate == 0.0

    def to_dict(self) -> dict[str, object]:
        ci = self.false_rejection_ci
        return {
            "arm": self.arm,
            "false_rejection_rate": self.false_rejection_rate,
            "false_rejection_ci": {
                "point": ci.point, "lo": ci.lo, "hi": ci.hi, "n_clusters": ci.n
            },
            "kill_reason_prevalence": dict(sorted(self.kill_reason_prevalence.items())),
            "false_rejection_by_reason": dict(
                sorted(self.false_rejection_by_reason.items())
            ),
            "n_instances": self.n_instances,
            "n_clusters": self.n_clusters,
            "clean": self.clean,
        }


# Why the SOTA superiority delta was or was not computed. Reported verbatim:
# a comparison that did not run must never read as a zero or go missing.
SUPERIORITY_COMPUTED = "computed"
SUPERIORITY_NO_EXTERNAL_ARM = (
    "NOT RUN: no external predictor arm was declared, so there is no "
    "state-of-the-art baseline to improve on. The superiority comparison in "
    "spec section 4.1 requires one (pass external_arms=/--external with an "
    "arm whose predictor reads a prior file). This is not a null result and "
    "must not be reported as a delta of zero."
)
SUPERIORITY_NO_PAIR = (
    "NOT RUN: the declared external arm has no filtered counterpart sharing "
    "its predictor object, so nothing isolates the filter's contribution."
)



def audit_filter(metrics: ArmMetrics, *, n_boot: int, seed: int) -> PrimaryAudit:
    """Build the primary audit, bootstrapping the false-rejection rate by cluster.

    The bootstrap resamples the per-cluster mean false-rejection rates, so one
    heavily-crystallised antigen contributes one observation. With spike at
    15.0% of instances (1,930 of 12,892, measured), resampling instances would
    put a sixth of the weight of the primary metric on a single glycoprotein.
    """
    per_cluster = cluster_means(
        [float(r["false_rejection_rate"]) for r in metrics.per_instance],  # type: ignore[arg-type]
        [str(r["cluster_id"]) for r in metrics.per_instance],
    )
    interval = paired_bca_ci(
        [per_cluster[key] for key in sorted(per_cluster, key=str)],
        n_boot=n_boot,
        seed=seed,
    )
    return PrimaryAudit(
        arm=metrics.arm,
        false_rejection_rate=metrics.false_rejection_rate,
        false_rejection_ci=interval,
        kill_reason_prevalence=dict(metrics.kill_reason_prevalence),
        false_rejection_by_reason=dict(metrics.false_rejection_by_reason),
        n_instances=metrics.n_instances,
        n_clusters=metrics.n_clusters,
    )
