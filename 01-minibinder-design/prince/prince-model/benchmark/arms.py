# SPDX-License-Identifier: MIT
"""Arms: what a predictor proposes, what a filter kills, and how one arm scores.

An "arm" is one column of the spec section 4.1 comparison table: a predictor,
optionally wrapped in the reality filter. Keeping the arm definitions and the
single-arm scoring here — separate from the manifest loader and the
four-arm orchestration in :mod:`benchmark.evaluate` — means
:func:`evaluate_arm` can be exercised on a handful of synthetic instances
without a CSV, a structure, or a bootstrap anywhere in sight.

Predictors and filters are plain callables registered at import time, so this
module never imports a structure reader and the statistics stay testable
without one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Collection, Hashable, Mapping, Sequence

from .bootstrap import macro_average_by_cluster, micro_average
from .metrics import (
    false_rejection_rate,
    per_residue_auprc,
    per_residue_auroc,
    top_k_patch_recall,
)

__all__ = [
    "BenchmarkInstance", "PredictorOutput", "FilterOutput", "Predictor",
    "ResidueFilter", "FilterPolicy", "Arm", "ArmMetrics", "apply_filter",
    "normalise_filter_output", "call_filter", "PREDICTOR_REGISTRY",
    "FILTER_REGISTRY", "register_predictor", "register_filter",
    "BUILTIN_FILTERS", "install_builtins", "UNSPECIFIED_REASON",
    "DEFAULT_TOP_K",
]

# Spec 4.1 reports top-1/3/5 patch recall. Top-5 is the headline because that
# is roughly how many sites a team actually triages.
DEFAULT_TOP_K: tuple[int, ...] = (1, 3, 5)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BenchmarkInstance:
    """One antibody instance — one manifest row, not one structure.

    Counting structures inflates N roughly 2x (spec 4.2.1 guard 4), so the
    unit here is the instance while the unit of *resampling* is
    :attr:`cluster_id`.
    """

    pdb_id: str
    antibody_chains: tuple[str, ...]
    antigen_chains: tuple[str, ...]
    epitope_residues: frozenset[str]
    cluster_id: str
    split: str

    @property
    def instance_id(self) -> str:
        """Stable id: one PDB entry can appear once per antibody instance."""
        return f"{self.pdb_id}:{'+'.join(self.antibody_chains)}"


@dataclass(frozen=True)
class PredictorOutput:
    """Ranked candidate patches for one instance, best first.

    ``residue_scores`` is optional: predictors that emit only patches leave it
    empty, and AUROC/AUPRC are then NaN rather than invented.
    """

    ranked_patches: tuple[frozenset[str], ...]
    residue_scores: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FilterOutput:
    """What the reality filter killed on one instance, and under which reasons.

    The primary reported result is a false-rejection and kill-reason
    prevalence audit, which needs to know *why* each residue was killed — "how
    often does BURIED_BY_NEIGHBOUR fire, and how often does it fire on a
    residue a crystallographer watched an antibody touch" is answerable from
    the data we have, whereas a superiority claim against an external
    predictor is not.

    ``reasons`` maps a residue key to the stable finding codes that killed it,
    matching ``hotspot_preflight.findings.Finding.code``. It is a plain mapping
    rather than the ``Finding`` type so this module keeps no dependency on the
    structural checks and stays testable without them.
    """

    killed: frozenset[str]
    reasons: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Site-level codes that did NOT kill anything — WARN findings, chiefly
    #: NO_ASSEMBLY_DEFINED. Carried because the assembly-awareness advantage is
    #: only testable on antigens that actually declare an assembly: if most of
    #: the benchmark falls back to the isolated chain, that is a finding about
    #: the benchmark and must be reported, not absorbed into the kill rate.
    warnings: tuple[str, ...] = ()

    @property
    def codes(self) -> frozenset[str]:
        """Every distinct kill code that fired on this instance."""
        return frozenset(c for codes in self.reasons.values() for c in codes)


# A filter may return bare residue keys or a FilterOutput. The bare form is
# accepted because a null control or a one-line test double should not have to
# construct reasons; it is normalised to the code UNSPECIFIED so prevalence
# accounting never silently loses a kill.
UNSPECIFIED_REASON = "UNSPECIFIED"

Predictor = Callable[[BenchmarkInstance], PredictorOutput]

#: A filter takes the instance, and optionally the predictor's output as a
#: second argument. The two-argument form exists because patch-level checks
#: (``check_patch_geometry``) judge a *candidate patch*, not a residue in
#: isolation, so a filter that cannot see the proposed patches cannot run them
#: at all. One-argument filters remain valid and are the common case.
ResidueFilter = Callable[..., "Collection[str] | FilterOutput"]


def call_filter(
    filter_fn: ResidueFilter,
    instance: BenchmarkInstance,
    prediction: PredictorOutput,
) -> FilterOutput:
    """Invoke a filter with one or two arguments, whichever it accepts.

    Arity is inspected rather than demanded so that adding patch-awareness did
    not break every existing one-argument filter, including the built-in
    controls and every test double. A filter that declares ``*args`` or two
    positional parameters gets the prediction; anything else does not.

    A :class:`TypeError` raised *inside* the filter is deliberately not caught
    — only the arity decision is inferred, never the filter's own failure.
    """
    if _takes_prediction(filter_fn):
        return normalise_filter_output(filter_fn(instance, prediction))
    return normalise_filter_output(filter_fn(instance))


def _takes_prediction(filter_fn: ResidueFilter) -> bool:
    """True when ``filter_fn`` accepts a second positional argument.

    Falls back to False when the signature cannot be read (a builtin, a C
    callable, an exotic partial), because the one-argument form is the older
    and safer assumption.
    """
    import inspect

    try:
        signature = inspect.signature(filter_fn)
    except (TypeError, ValueError):
        return False
    positional = 0
    for parameter in signature.parameters.values():
        if parameter.kind is parameter.VAR_POSITIONAL:
            return True
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD):
            positional += 1
    return positional >= 2


def normalise_filter_output(raw: Collection[str] | FilterOutput) -> FilterOutput:
    """Coerce either filter return shape to a :class:`FilterOutput`.

    Raises:
        TypeError: on a string, which is a near-universal mistake — ``"C325"``
            is a collection of five characters, and silently killing five
            one-letter residue keys would corrupt every prevalence number
            downstream rather than failing.
    """
    if isinstance(raw, FilterOutput):
        return raw
    if isinstance(raw, str):
        raise TypeError(
            f"a filter returned the string {raw!r}; return a collection of "
            f"residue keys (e.g. [{raw!r}]) or a FilterOutput, not a bare "
            f"string, which would be read as one key per character"
        )
    killed = frozenset(raw)
    return FilterOutput(
        killed=killed,
        reasons={key: (UNSPECIFIED_REASON,) for key in killed},
    )


class FilterPolicy(str, Enum):
    """How a KILL verdict on a residue affects the patch containing it.

    ``DROP_PATCH`` matches what the tool does: any KILL gives the site an
    overall STOP, so the patch leaves the ranking. ``PRUNE_RESIDUES`` is the
    gentler reading, kept because reporting only the harsher one would
    understate patch recall.
    """

    DROP_PATCH = "drop_patch"
    PRUNE_RESIDUES = "prune_residues"


@dataclass(frozen=True)
class Arm:
    """One column of the comparison. ``filter_fn=None`` is predictor-alone."""

    name: str
    predictor: Predictor
    filter_fn: ResidueFilter | None = None
    note: str = ""

    @property
    def has_filter(self) -> bool:
        return self.filter_fn is not None


# ---------------------------------------------------------------------------
# Scoring one arm
# ---------------------------------------------------------------------------
def apply_filter(
    ranked_patches: Sequence[Collection[str]],
    killed: Collection[str],
    policy: FilterPolicy = FilterPolicy.DROP_PATCH,
) -> tuple[frozenset[str], ...]:
    """Rewrite a patch ranking given the residues the filter killed.

    Rank order is preserved: the filter removes candidates, it does not
    re-score them. A patch emptied by pruning is dropped — an empty patch is
    not a proposal.
    """
    kill_set = set(killed)
    out: list[frozenset[str]] = []
    for patch in ranked_patches:
        patch_set = frozenset(patch)
        if policy is FilterPolicy.DROP_PATCH:
            if not (patch_set & kill_set):
                out.append(patch_set)
        else:
            surviving = patch_set - kill_set
            if surviving:
                out.append(surviving)
    return tuple(out)


# ---------------------------------------------------------------------------
# Registries — how the real predictors and filters plug in
# ---------------------------------------------------------------------------
# Discovery is eager and idempotent, and the built-ins below are installed at
# import of *this* module — the one that owns the dicts — never as a side
# effect of importing something else that happens to call register_*. A
# registry that is complete only once the right module has been imported fails
# in CI, under a different test order, and for anyone who imports the library
# instead of running the CLI, and the error message blames the user's filter
# name for it.
PREDICTOR_REGISTRY: dict[str, Predictor] = {}
FILTER_REGISTRY: dict[str, ResidueFilter] = {}


def _register(
    registry: dict[str, object], kind: str, name: str, value: object
) -> None:
    """Idempotent registration: re-registering the same object is a no-op.

    Re-registration happens for mundane reasons — a module imported under two
    names, a plugin loaded twice, a test module re-imported — and raising
    there turns a harmless repeat into a crash. A *different* object under an
    existing name is a genuine collision and still raises, because silently
    replacing a predictor would change what a reported number means.
    """
    if not name or not name.strip():
        raise ValueError(f"{kind} name must be a non-empty string, got {name!r}")
    existing = registry.get(name)
    if existing is not None and existing is not value:
        raise ValueError(
            f"{kind} {name!r} is already registered to a different object "
            f"({existing!r}); pick another name or unregister it first"
        )
    registry[name] = value


def register_predictor(name: str, predictor: Predictor) -> None:
    """Add a predictor the CLI can name in ``--arms``.

    The external predictor and the ``geometric`` ranker register themselves
    rather than being hardcoded, so this module never imports a structure
    reader and stays testable without one.
    """
    _register(PREDICTOR_REGISTRY, "predictor", name, predictor)  # type: ignore[arg-type]


def register_filter(name: str, filter_fn: ResidueFilter) -> None:
    """Add a filter the CLI can name in ``--arms``."""
    _register(FILTER_REGISTRY, "filter", name, filter_fn)  # type: ignore[arg-type]


def _kill_nothing(instance: BenchmarkInstance) -> FilterOutput:
    """A filter that kills nothing — the null-effect control.

    Its delta against the unfiltered arm must be exactly zero; if it is not,
    the harness has a bug. The cheapest end-to-end check available.
    """
    del instance
    return FilterOutput(frozenset())


def _kill_everything(instance: BenchmarkInstance) -> FilterOutput:
    """A filter that kills the whole observed epitope — the saturated control.

    Its false-rejection rate must be exactly 1.0. Pairing it with
    ``kill_nothing`` brackets the primary metric at both ends, so a
    false-rejection rate that cannot reach 0.0 or 1.0 is caught by the suite
    rather than by a reader wondering why the audit looks flat.
    """
    return FilterOutput(
        killed=frozenset(instance.epitope_residues),
        reasons={key: ("SATURATED_CONTROL",) for key in instance.epitope_residues},
    )


#: The built-in controls, installed eagerly below. Not scientific baselines —
#: they exist so the harness can prove it still measures what it claims to.
BUILTIN_FILTERS: dict[str, ResidueFilter] = {
    "kill_nothing": _kill_nothing,
    "kill_everything": _kill_everything,
}


def install_builtins() -> None:
    """Install the built-in filters. Idempotent, and called at import."""
    for name, filter_fn in BUILTIN_FILTERS.items():
        register_filter(name, filter_fn)


install_builtins()
