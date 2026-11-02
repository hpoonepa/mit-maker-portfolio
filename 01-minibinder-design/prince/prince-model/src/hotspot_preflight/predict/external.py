# SPDX-License-Identifier: MIT
"""Use somebody else's predictor as the backend, via a file you produced.

Site ranking is published prior art and the published predictors are better
validated than our baseline (see :mod:`.base`). The right way to use this
package is therefore often: run DiscoTope-3.0, SEMA, ScanNet, PeSTo, MaSIF-site
or Site4Drug yourself, save its per-residue scores, and point this adapter at
the file. The project's claim is the improvement the downstream assembly-aware
filter makes to whatever you plug in — so plugging in a real predictor is the
intended path, not a fallback.

The file reading, the column rules and the percentile normalisation live in
:mod:`.scorefile`; this module is only the :class:`SitePredictor` adapter around
them. Names are re-exported so ``from ...predict.external import X`` keeps
working for callers that do not care where the parsing moved to.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from ..checks.sasa import BurialProfile
from ..residue import ResidueKey
from ..structure import Target, observed_residues
from .scorefile import (
    CHAIN_COLUMNS,
    ICODE_COLUMNS,
    MIN_MATCH_FRACTION,
    PDB_CHAIN_COLUMNS,
    REJECTED_COLUMNS,
    RESIDUE_COLUMNS,
    RESNUM_COLUMNS,
    SCORE_COLUMN_PREFERENCE,
    UNSCORED,
    ExternalScoreError,
    ExternalScoreFile,
    load_external_score_file,
    load_external_scores,
    midrank_percentiles,
)

__all__ = [
    "MIN_MATCH_FRACTION",
    "UNSCORED",
    "CHAIN_COLUMNS",
    "PDB_CHAIN_COLUMNS",
    "RESNUM_COLUMNS",
    "RESIDUE_COLUMNS",
    "SCORE_COLUMN_PREFERENCE",
    "ICODE_COLUMNS",
    "REJECTED_COLUMNS",
    "ExternalScoreError",
    "ExternalScoreFile",
    "LowResidueMatchWarning",
    "midrank_percentiles",
    "load_external_scores",
    "load_external_score_file",
    "ExternalPredictor",
]


class LowResidueMatchWarning(UserWarning):
    """Most residues in an external score file are absent from the structure."""


# ---------------------------------------------------------------------------
# The predictor
# ---------------------------------------------------------------------------


class ExternalPredictor:
    """Scores read from a file another tool produced.

    Args:
        name: how this backend is identified in output, e.g. ``"discotope3"``.
            Free text, because the whole point is that we do not know which
            tool it is and must not pretend to.
        path: a local CSV, TSV or JSON file. Parsed eagerly, so a malformed
            file fails at construction rather than part-way through a run.
        normalise: convert to within-target midrank percentiles before
            returning. Default ``True`` and it should stay true — see
            :func:`midrank_percentiles` for why raw values from these tools
            cannot be compared, blended or thresholded. ``False`` exists for
            inspecting a file as written, not for scoring.
    """

    name: str = "external"

    def __init__(
        self, name: str, path: str | Path, *, normalise: bool = True
    ) -> None:
        if not name:
            raise ValueError("an external predictor needs a name")
        self.name = name
        self.normalise = normalise
        self.file = load_external_score_file(path)
        self.path = self.file.path
        self.raw: dict[ResidueKey, float] = self.file.raw
        self.scores: dict[ResidueKey, float] = (
            self.file.percentiles if normalise else dict(self.file.raw)
        )

    @property
    def score_column(self) -> str:
        """Which column the scores were read from, for the run record."""
        return self.file.score_column

    def __repr__(self) -> str:
        return (
            f"ExternalPredictor(name={self.name!r}, path={str(self.path)!r}, "
            f"n_residues={len(self.scores)}, column={self.score_column!r}, "
            f"normalise={self.normalise})"
        )

    def coverage(self, profile: BurialProfile) -> tuple[int, int]:
        """``(n_covered, n_profiled)`` — how much of the site the prior covers.

        Reported rather than inferred because the join is a LEFT join: a
        predictor that scored 40 of 393 surface residues must produce a
        complete ranking with that gap visible, not a shorter ranking that
        looks complete.
        """
        covered = sum(1 for key in profile.relative_sasa if key in self.scores)
        return covered, len(profile.relative_sasa)

    def score_residues(
        self, target: Target, profile: BurialProfile
    ) -> dict[ResidueKey, float]:
        """Percentile scores for every residue in ``profile``; NaN if uncovered.

        A **LEFT** join on the profile: every profiled residue appears in the
        result, and one the file does not mention gets :data:`UNSCORED` (NaN).
        An inner join would silently shrink the candidate set, and a 0.0 default
        would rank an unmeasured residue as the worst possible site rather than
        as unknown — see :data:`UNSCORED`.

        Warns (:class:`LowResidueMatchWarning`) when fewer than
        :data:`MIN_MATCH_FRACTION` of the file's residues exist in the
        structure. That is the signature of a residue-numbering mismatch —
        label_seq_id read as author numbering, a renumbered construct, the
        wrong chain id — and it is otherwise *silent*: every lookup misses,
        every score goes NaN, and without this warning the ranking would come
        out plausible and meaningless. Counts go in the message because "most
        residues missing" is not actionable and "3 of 412 matched" is.
        """
        in_structure = observed_residues(target)
        matched = [key for key in self.scores if key in in_structure]
        total = len(self.scores)
        fraction = len(matched) / total if total else 0.0

        scored = {
            key: self.scores.get(key, UNSCORED) for key in profile.relative_sasa
        }
        n_covered, n_profiled = self.coverage(profile)

        if fraction < MIN_MATCH_FRACTION:
            file_chains = sorted({key.auth_asym_id for key in self.scores})
            warnings.warn(
                f"{self.path}: only {len(matched)} of {total} residues "
                f"({fraction:.1%}) exist in {target.entry_id}, and only "
                f"{n_covered} of {n_profiled} profiled residues are covered "
                f"(the rest are NaN). Score column read: "
                f"{self.score_column!r}. Chains in the file: {file_chains}; "
                f"chains in the structure: "
                f"{sorted({k.auth_asym_id for k in in_structure})}. This is "
                f"what a numbering-scheme mismatch looks like — scores keyed "
                f"by mmCIF label_seq_id, a renumbered construct, or the wrong "
                f"chain id — and the ranking will be meaningless rather than "
                f"merely noisy.",
                LowResidueMatchWarning,
                stacklevel=2,
            )
        return scored
