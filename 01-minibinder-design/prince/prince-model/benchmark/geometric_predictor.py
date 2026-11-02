"""The `geometric` arm: our own site proposer, driven over benchmark antigens.

Bridges ``hotspot_preflight.predict`` to ``benchmark.arms.register_predictor``.
For one antigen it isolates the antigen from the complex, measures exposure,
enumerates surface patches, scores and ranks them with
:class:`GeometricPredictor`, and returns the result as a
:class:`~benchmark.arms.PredictorOutput` keyed by ``str(ResidueKey)`` — the
same ``C325`` strings the manifest uses after normalisation.

Three things this module is careful about:

* **The antigen is isolated first.** See :mod:`benchmark.structures`: exposure
  measured on the deposited complex is exposure with the antibody still bound,
  which buries the epitope we are trying to find and would make an
  exposure-driven ranker systematically anti-correlated with the truth.
* **One reference table per antigen**, built once by ``reference_max_sasa`` and
  passed to every ``compute_burial`` call. Relative SASA stays inside 0-1 and
  keeps its ordering across a rescale, so a per-context recompute is invisible
  in the output and only ``BurialProfile.reference_id`` would catch it.
* **NMS happens before anything positional.** ``GeometricPredictor.rank``
  suppresses near-duplicate patches at residue-Jaccard 0.50 internally and
  does it *before* computing anchors, so the returned order is already
  post-NMS — which matters because ``top_k_patch_recall`` reads that order.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path

from hotspot_preflight.checks.sasa import compute_burial, reference_max_sasa
from hotspot_preflight.predict.base import (
    NMS_JACCARD_THRESHOLD,
    rank_patches,
    suppress_overlapping,
)
from hotspot_preflight.predict.geometric import GeometricPredictor
from hotspot_preflight.structure import Target
from hotspot_preflight.surface import enumerate_patches

from .arms import PredictorOutput, register_predictor
from .evaluate import BenchmarkInstance
from .structures import StructureUnavailable, load_antigen

__all__ = ["GeometricArm", "register_geometric", "DEFAULT_MAX_PATCHES"]

LOGGER = logging.getLogger(__name__)

#: Patch enumeration grows one patch per exposed seed residue, so a 600-residue
#: antigen yields hundreds of heavily-overlapping candidates. Capping the
#: enumeration keeps a 1,158-instance run tractable; ``enumerate_patches``
#: returns widest-exposure first, so the cap keeps the most promising
#: candidates rather than an arbitrary prefix. Any cap is a bound on coverage,
#: so it is recorded in the arm's note and logged.
DEFAULT_MAX_PATCHES = 400


@dataclass(frozen=True)
class GeometricArm:
    """Rank candidate patches on one benchmark antigen.

    Args:
        structure_dir: directory of downloaded coordinates. Never fetched
            here — a predictor that hit the network mid-run would make the
            timings meaningless and the run non-reproducible.
        use_assembly: measure exposure on the biological assembly when the
            entry declares one. Benchmark antigens mostly do not, in which
            case this falls back to the isolated chain explicitly and counts
            it.
        max_patches: enumeration cap, see :data:`DEFAULT_MAX_PATCHES`.
    """

    structure_dir: Path
    use_assembly: bool = True
    max_patches: int | None = DEFAULT_MAX_PATCHES
    #: Compute the per-residue feature breakdown once instead of letting
    #: ``GeometricPredictor.rank`` recompute it. ``rank`` calls
    #: ``score_residues`` and ``score_components`` separately and
    #: ``score_residues`` calls ``score_components`` again, so the quadratic
    #: concavity/connectivity pass runs three times per antigen, plus a fourth
    #: for our own residue scores. On a 1,000-residue antigen that is the
    #: whole runtime. The fast path reproduces ``rank`` exactly —
    #: ``rank_patches`` then ``suppress_overlapping`` at the same threshold —
    #: minus the anchor annotation, which only the anchor gate needs. There is
    #: a test asserting the two paths return identical patch orders.
    fast: bool = True
    predictor: GeometricPredictor = field(default_factory=GeometricPredictor)
    stats: dict[str, int] = field(default_factory=dict)
    #: Memoised per instance, **bounded**. ``evaluate_arm`` calls the
    #: predictor once per arm, so an unfiltered/filtered pair would otherwise
    #: recompute an identical prediction twice — and the pair exists precisely
    #: so both arms see the same proposal. The bound is not optional: arms are
    #: evaluated one at a time over the whole benchmark, so an unbounded cache
    #: holds every prediction for every instance at once. At 1,158 test
    #: instances that exhausted memory and the process was killed with no
    #: traceback. FIFO eviction trades some recomputation for a run that
    #: finishes.
    cache_size: int = 256
    _cache: "OrderedDict[str, PredictorOutput]" = field(
        default_factory=OrderedDict
    )

    @property
    def note(self) -> str:
        parts = [f"patch enumeration capped at {self.max_patches}"] if self.max_patches else []
        if not self.use_assembly:
            parts.append("exposure measured on the isolated chain only")
        parts.append(f"NMS residue-Jaccard {NMS_JACCARD_THRESHOLD}")
        return "; ".join(parts)

    def locate(self, instance: BenchmarkInstance) -> Path | None:
        from .structures import locate_structure

        return locate_structure(self.structure_dir, instance.pdb_id)

    def __call__(self, instance: BenchmarkInstance) -> PredictorOutput:
        cached = self._cache.get(instance.instance_id)
        if cached is not None:
            self._bump("cache_hits")
            return cached
        out = self._predict(instance)
        if self.cache_size > 0:
            self._cache[instance.instance_id] = out
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return out

    def _predict(self, instance: BenchmarkInstance) -> PredictorOutput:
        target, used_assembly = load_antigen(
            self.structure_dir, instance.pdb_id, instance.antigen_chains,
            use_assembly=self.use_assembly,
        )
        self._bump("assembly_used" if used_assembly else "no_assembly_declared")
        self._bump("instances")

        profile = self._exposure(target, instance)
        # Assembly partners provide context, not extra candidate antigens.
        # Keeping symmetry-copy chains here invents residue labels and can
        # collide under the legacy chain+number display format.
        original = set(instance.antigen_chains)
        candidate_profile = replace(
            profile,
            relative_sasa={k: v for k, v in profile.relative_sasa.items() if k.auth_asym_id in original},
            absolute_sasa={k: v for k, v in profile.absolute_sasa.items() if k.auth_asym_id in original},
        )
        patches = enumerate_patches(target, candidate_profile, max_patches=self.max_patches)
        if not patches:
            # A fully buried or unparseable antigen proposes nothing. Returning
            # an empty ranking scores as a miss, which is correct and honest;
            # it is counted so a run that proposed nothing anywhere cannot
            # read as a run that proposed badly.
            self._bump("no_patches")
            return PredictorOutput(ranked_patches=())

        if self.fast:
            components = self.predictor.score_components(target, profile)
            scores = {
                key: sum(parts.values()) for key, parts in components.items()
            }
            ranked = suppress_overlapping(
                rank_patches(
                    patches, scores, predictor_name=self.predictor.name,
                    aggregate="mean", residue_components=components,
                ),
                NMS_JACCARD_THRESHOLD,
            )
        else:
            ranked = self.predictor.rank(target, profile, patches)
            scores = self.predictor.score_residues(target, profile)
        self._bump("ranked")
        scores = {key: value for key, value in scores.items() if key.auth_asym_id in original}
        if len({str(key) for key in scores}) != len(scores):
            raise StructureUnavailable("Ambiguous concatenated residue IDs on declared antigen chains")

        return PredictorOutput(
            ranked_patches=tuple(
                frozenset(str(key) for key in scored.residues) for scored in ranked
            ),
            residue_scores={str(key): value for key, value in scores.items()},
        )

    # -- internals ---------------------------------------------------------
    def _bump(self, name: str) -> None:
        self.stats[name] = self.stats.get(name, 0) + 1

    def _exposure(self, target: Target, instance: BenchmarkInstance):
        """Measure exposure on the already-reduced antigen structure.

        The reference table is built **once here** and handed to the single
        ``compute_burial`` call, so the denominator cannot drift between
        contexts within this antigen. ``load_antigen`` has already decided
        assembly-versus-asymmetric-unit and counted it, so there is no
        assembly handling left to do and nothing to get inconsistent.
        """
        reference = reference_max_sasa(target.st)
        focus = instance.antigen_chains[0] if instance.antigen_chains else None
        if focus is not None and focus not in set(target.chain_ids):
            # Assembly expansion may have renamed the focus copy; measuring
            # the whole reduced structure is right when it has.
            focus = None
        return compute_burial(
            target.st, context="chain", focus_chain=focus, reference=reference
        )


def register_geometric(
    structure_dir: str | Path,
    *,
    name: str = "geometric",
    use_assembly: bool = True,
    max_patches: int | None = DEFAULT_MAX_PATCHES,
) -> GeometricArm:
    """Build and register the predictor, returning it so its stats stay readable."""
    directory = Path(structure_dir)
    if not directory.is_dir():
        raise NotADirectoryError(
            f"structure_dir {directory} is not a directory; the geometric "
            f"predictor reads downloaded coordinates and never fetches them "
            f"mid-run, so point it at the download cache"
        )
    arm = GeometricArm(
        structure_dir=directory, use_assembly=use_assembly, max_patches=max_patches
    )
    register_predictor(name, arm)
    return arm
