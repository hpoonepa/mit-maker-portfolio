# SPDX-License-Identifier: MIT
"""Named weight profiles for the geometric predictor, each carrying its own provenance.

A weight vector on its own is a number with no epistemic status: a reader cannot
tell a hand-set ordering from a fitted coefficient, and the package therefore
cannot tell the truth about itself. :class:`WeightProfile` pairs the weights with
a written account of where they came from and with a per-profile
``n_outcomes_fitted``, so the honesty block
(:data:`~.base.N_OUTCOMES_FITTED`) can become a statement about *the weights
actually in use* rather than a single global zero.

Three profiles ship, and they disagree with each other on purpose:

* :data:`DESIGNABILITY` — the historical hand-set weights. Unvalidated for the
  thing they were written for, and *measurably wrong* for antibody epitopes.
* :data:`ANTIBODY_EPITOPE` — fitted, on a declared training split, to observed
  antibody epitopes.
* :data:`EXPOSURE_ONLY` — relative solvent accessibility without fitted weights.

The current fit and test use connected accession/exact-sequence components.
This is a retrospective analysis of cached features. Coefficient signs describe
associations within the antibody-epitope dataset; prospective minibinder
evaluation remains pending.

Reproduce the current fit with ``scripts/train_ranker.py --out
data/eval/prince_connected.json``. Historical analyses in the documentation use
older splits and are explicitly not the current model's validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

__all__ = [
    "FEATURE_NAMES",
    "WeightProfile",
    "DESIGNABILITY",
    "ANTIBODY_EPITOPE",
    "EXPOSURE_ONLY",
    "PROFILES",
    "get_profile",
]

FEATURE_NAMES: tuple[str, ...] = (
    "exposure",
    "concavity",
    "hydrophobicity",
    "connectivity",
)
"""The features a profile may weight, in the order the baseline documents them.

Canonical here rather than derived from any one profile's keys, because
:data:`EXPOSURE_ONLY` names only one feature and deriving the feature list from
whichever profile happened to be the default would make an unknown-feature typo
undetectable in exactly the profile most likely to be hand-edited.
"""


@dataclass(frozen=True)
class WeightProfile:
    """A weight vector plus the account of where it came from.

    Args:
        name: the registry key, also what a run record should report.
        weights: per-feature weights keyed by :data:`FEATURE_NAMES`. A missing
            feature means weight zero. An unknown feature is rejected rather
            than ignored — a typo'd key that silently does nothing is
            indistinguishable from a feature that genuinely had no effect.
            Frozen on construction, so a caller cannot mutate a shared profile
            out from under every other caller.
        provenance: prose, meant to be read. Where the numbers came from, what
            they were fitted or not fitted to, and what is known about how well
            they work. Not optional, because a profile without this is the
            problem this class exists to fix. Kept out of ``repr`` — several
            paragraphs inside every log line and pytest failure would get a
            reader to skip the repr rather than read the provenance.
        n_outcomes_fitted: how many measured binding outcomes these weights were
            fitted to. **Zero for anything hand-set**, and zero is the honest
            answer for a profile that was reasoned into existence however
            carefully. See :data:`~.base.N_OUTCOMES_FITTED` for why this number
            is emitted whether or not it flatters us.
    """

    name: str
    weights: Mapping[str, float]
    provenance: str = field(repr=False)
    n_outcomes_fitted: int = 0

    def __post_init__(self) -> None:
        unknown = set(self.weights) - set(FEATURE_NAMES)
        if unknown:
            raise ValueError(
                f"profile {self.name!r} weights unknown feature(s) "
                f"{sorted(unknown)}; features are {list(FEATURE_NAMES)}"
            )
        if self.n_outcomes_fitted < 0:
            raise ValueError(
                f"profile {self.name!r} has n_outcomes_fitted="
                f"{self.n_outcomes_fitted}; a count cannot be negative"
            )
        if not self.provenance.strip():
            raise ValueError(f"profile {self.name!r} has empty provenance")
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))


# ---------------------------------------------------------------------------
# The profiles
# ---------------------------------------------------------------------------


DESIGNABILITY = WeightProfile(
    name="designability",
    weights={
        "exposure": 0.40,
        "concavity": 0.30,
        "hydrophobicity": 0.20,
        "connectivity": 0.10,
    },
    n_outcomes_fitted=0,
    provenance="""Hand-set. Round numbers chosen to express an ordering for
*designed minibinder sites*: a site must first be reachable (exposure), then
shaped to be gripped (concavity), then chemically willing (hydrophobicity), with
compactness as a tie-breaker. The ordering, not the exact numbers, was ever the
assertion.

Never validated on any outcome. No labelled set of designed-binder successes and
failures at the scale needed to fit or test these exists, so the claim they
encode remains an argument rather than a result.

On the current connected-component held-out subset, these weights score
cluster-macro AUROC 0.5069, compared with 0.6479 for the fitted model and
0.6450 for exposure only. Metrics and uncertainty are recorded in
data/eval/prince_connected.json. Earlier pooled-residue analyses used leaky
splits and are historical, not current validation.""",
)
"""The historical hand-set weights. Sums to 1.0, so a score lands in [0, 1].

Unvalidated for designed minibinder sites and measurably wrong for antibody
epitopes — read :attr:`~WeightProfile.provenance` before using it for either.
"""


ANTIBODY_EPITOPE = WeightProfile(
    name="antibody_epitope",
    weights={
        "exposure": 1.0756266877590568,
        "concavity": -2.3035477542532203,
        "hydrophobicity": -0.0943157861683642,
        "connectivity": 0.9803490089433473,
    },
    n_outcomes_fitted=340,
    provenance="""L2 logistic regression (lambda=1), not an LLM. Refit with
scripts/train_ranker.py after merging antigen accession and exact-sequence
identities transitively before capping and assigning splits. 340 training
complexes (116 components); 139 validation complexes were not used to fit or
tune; evaluation uses 110 separate complexes (34 components).

Retrospective reanalysis of 649 cached feature records from earlier exploratory
work, not a previously untouched external test. 60 cached records were excluded
by the new per-component cap. The 8,241-interface source manifest contains
6,937 retained interfaces after connected-component capping, but only the cached
subset was used to train or evaluate this model. Component overlap is zero.
Homologous sequences can occur across the identity-disjoint splits.
Before fitting, all cached feature identities were uniquely recovered as
explicit chain:seq:icode keys. 27,074 symmetry-copy rows were removed and 28
incorrect declared-antigen labels repaired against explicit manifest keys.
Features themselves were not recomputed. See feature_identity_repair.json.

Held-out cluster-macro AUROC 0.6479 (bootstrap 95% CI 0.6218–0.6722);
AUPRC 0.1361. Exposure-only AUROC is 0.6450, close to the fitted result.
Metrics are computed per instance, averaged within and then across components,
so they are not directly comparable to historical pooled-residue metrics.
Intercept -3.0953482864844784 is omitted from ranking because it is constant.

This evaluation measures residue ranking. Patch recovery is evaluated in a
separate artifact; minibinder-outcome validation remains pending.
Full counts, input hashes, split membership and limitations are recorded in
data/eval/prince_connected.json.""",
)
"""Logistic-regression coefficients fitted to observed antibody epitopes.

Unlike the other two profiles these are log-odds coefficients, not a convex
combination: they do not sum to 1 and a residue score is not confined to
[0, 1]. Only the ranking is meaningful.
"""


EXPOSURE_ONLY = WeightProfile(
    name="exposure_only",
    weights={"exposure": 1.0},
    n_outcomes_fitted=0,
    provenance="""Relative solvent accessibility, and nothing else. Not fitted —
there is nothing to fit, which is the point.

On the current connected-component held-out subset this scores cluster-macro
AUROC 0.6450 (bootstrap 95% CI 0.6193–0.6682), compared with 0.6479 for the
fitted four-feature model. Neither number establishes superiority. The
evaluation is retrospective and antibody-specific; no designed-minibinder
efficacy or evidence-layer improvement is established. Historical patch-level
claims used an older model and split and do not describe this refit.""",
)
"""Relative solvent accessibility alone: the mandatory simple comparator."""


PROFILES: dict[str, WeightProfile] = {
    profile.name: profile
    for profile in (DESIGNABILITY, ANTIBODY_EPITOPE, EXPOSURE_ONLY)
}
"""Every shipped profile, keyed by :attr:`WeightProfile.name`."""


def get_profile(name: str) -> WeightProfile:
    """Look up a profile by name.

    Raises:
        ValueError: if ``name`` is not a shipped profile. The message names the
            available profiles, because the caller is usually a CLI user or a
            config file and the useful response to a typo is the list.
    """
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"unknown weight profile {name!r}; available profiles are "
            f"{sorted(PROFILES)}"
        ) from None
