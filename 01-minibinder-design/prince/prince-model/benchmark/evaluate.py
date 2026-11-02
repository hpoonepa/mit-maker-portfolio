# SPDX-License-Identifier: MIT
"""The four-arm evaluation: what is the reality filter actually worth?

Spec section 4.1 asks *how much does assembly-aware reality checking improve
an existing state-of-the-art epitope predictor?* and answers it with four
arms: ``external`` alone (the SOTA baseline), ``external`` + filter (**the
headline**), ``geometric`` alone (our baseline, for transparency) and
``geometric`` + filter (the full default pipeline).

The headline is the delta from adding the filter to the strongest predictor
arm, with a cluster-clustered BCa interval. If that interval spans zero the
verdict is INCONCLUSIVE and the report says so in those words — a
clearly-stated null is a finding, because nobody has measured this, whereas a
point estimate without its interval is not a result.

This module owns the manifest loader, the result object and the orchestration.
Arm definitions and single-arm scoring live in :mod:`benchmark.arms`, the
paired comparison in :mod:`benchmark.delta`, and rendering in
``scripts/run_evaluation.py``. :func:`load_manifest` is the only I/O in any of
them.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .arms import (
    DEFAULT_TOP_K,
    FILTER_REGISTRY,
    PREDICTOR_REGISTRY,
    Arm,
    BenchmarkInstance,
    FilterPolicy,
    Predictor,
    PredictorOutput,
    ResidueFilter,
    apply_filter,
    register_filter,
    register_predictor,
)
from .score import ArmMetrics, evaluate_arm
from .bootstrap import PREREGISTERED_MDE, THREE_ZONE_POLICY
from .delta import (
    SUPERIORITY_COMPUTED,
    SUPERIORITY_NO_EXTERNAL_ARM,
    SUPERIORITY_NO_PAIR,
    ArmDelta,
    PrimaryAudit,
    audit_filter,
    delta_to_dict,
    paired_delta,
)

# Re-exported so callers have one import site for the whole harness; the split
# into arms/delta is an authoring concern, not an API change.
__all__ = [
    "BenchmarkInstance", "PredictorOutput", "Predictor", "ResidueFilter",
    "Arm", "ArmMetrics", "ArmDelta", "EvaluationResult", "PrimaryAudit",
    "DroppedRow", "SUPERIORITY_COMPUTED", "SUPERIORITY_NO_EXTERNAL_ARM",
    "SUPERIORITY_NO_PAIR",
    "FilterPolicy", "load_manifest", "apply_filter", "evaluate_arm",
    "run_evaluation", "PREDICTOR_REGISTRY", "FILTER_REGISTRY",
    "register_predictor", "register_filter", "DEFAULT_TOP_K", "HEADLINE_K",
    "MIN_EPITOPE_RESIDUES", "normalise_residue_token",
]

HEADLINE_K: int = 5
# Spec 4.2.1 guard 3: 6al0 yields 2 residues, a lattice contact, not a site.
MIN_EPITOPE_RESIDUES: int = 5


@dataclass(frozen=True)
class DroppedRow:
    """A row that was not evaluated, and why.

    No silent caps: a benchmark that quietly discards the hard instances
    reports a number about the easy ones.
    """

    source: str
    identifier: str
    reason: str


# ---------------------------------------------------------------------------


# -------------------------------------------------------------------------
# Manifest loading — the only I/O in the harness
# -------------------------------------------------------------------------
# Both schemas are accepted: the brief's single ``antibody_chains`` column and
# the built manifest's separate heavy/light columns. Adapting the loader
# rather than the statistics is why they are separate modules.
_REQUIRED_COLUMNS = ("pdb_id", "antigen_chains", "epitope_residues", "cluster_id", "split")
_ANTIBODY_COLUMNS = ("antibody_chains", "heavy_chain", "light_chain")


def _split_field(raw: str) -> tuple[str, ...]:
    """Split a multi-value cell on ``;`` or ``|``, dropping blanks."""
    return tuple(p.strip() for p in raw.replace("|", ";").split(";") if p.strip())


def _antibody_chains(row: Mapping[str, str]) -> tuple[str, ...]:
    """Antibody chains from either schema, de-duplicated, order preserved.

    A VHH has a heavy chain and no light chain, so a blank ``light_chain`` is
    normal and must not drop the row; only *both* being blank is the
    empty-antibody-atom-set trap of spec 4.2.1 guard 1.
    """
    if row.get("antibody_chains"):
        return _split_field(row["antibody_chains"])
    out: list[str] = []
    for column in ("heavy_chain", "light_chain"):
        for chain in _split_field(row.get(column) or ""):
            if chain not in out:
                out.append(chain)
    return tuple(out)


def normalise_residue_token(token: str) -> str:
    """Canonicalise a manifest residue token to the ``C325`` form.

    The built manifest writes ``D:32``, the brief's schema wrote ``C325``, and
    both normalise to ``str(ResidueKey)`` — what every metric compares on and
    what the predictors emit. Normalising once at the boundary keeps one
    residue-key vocabulary: two spellings of the same residue would silently
    score as a miss.
    """
    token = token.strip()
    if ":" not in token:
        return token
    # Three parts is a real third spelling, not a malformed two-part token:
    # SAbDab writes an insertion-coded residue as "H:83:A" (chain, number,
    # insertion code). Partitioning on the first colon alone left "H83:A",
    # which parse_hotspot_spec rejects — and a rejected epitope token means the
    # filter judges nothing for that instance and the benchmark records a
    # false-rejection rate of zero it never earned. 215 of 8,241 instances.
    parts = [p.strip() for p in token.split(":")]
    if len(parts) > 3:
        # Not a spelling we know. Return it unchanged so it fails loudly at the
        # parser rather than being silently mangled into a plausible key.
        return token
    return "".join(parts)


def _row_problem(
    row: Mapping[str, str], epitope: Sequence[str], split: str | None
) -> str | None:
    """Why this row cannot be evaluated, or None if it can.

    One function so every rejection reason is written once and all of them
    reach the report. Each check is a trap the spec's probe actually hit.
    """
    if not (row.get("pdb_id") or "").strip():
        return "blank pdb_id"
    row_split = (row.get("split") or "").strip()
    if split is not None and row_split != split:
        return f"split {row_split!r} != {split!r}"
    if len(epitope) < MIN_EPITOPE_RESIDUES:
        return (
            f"epitope has {len(epitope)} residues, below the floor of "
            f"{MIN_EPITOPE_RESIDUES} (likely a lattice contact, not an interface)"
        )
    if not _antibody_chains(row):
        # Spec 4.2.1 guard 1: scFv chain+domain naming silently produced empty
        # antibody atom sets in the probe.
        return "empty antibody_chains"
    if not _split_field(row.get("antigen_chains") or ""):
        return "empty antigen_chains"
    if not (row.get("cluster_id") or "").strip():
        # Holding out by complex instead of by cluster is the headline
        # methodological error this benchmark exists to avoid.
        return "blank cluster_id; cannot hold out by cluster"
    return None


def load_manifest(
    path: str | Path,
    *,
    cutoff: float = 4.5,
    split: str | None = None,
    limit: int | None = None,
) -> tuple[list[BenchmarkInstance], list[DroppedRow]]:
    """Read the benchmark manifest CSV, returning ``(instances, dropped)``.

    ``cutoff`` prefers a cutoff-specific column such as
    ``epitope_residues_4`` when the manifest has one — that is how the spec's
    4.0 A sensitivity analysis runs — else ``epitope_residues``, with the
    cutoff recorded as provenance. ``limit`` records every row it cut, so a
    truncated run cannot be mistaken for a full one.

    Raises:
        FileNotFoundError: if the manifest is missing.
        ValueError: on a missing header, missing required columns, or when
            every row was dropped.
    """
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    instances: list[BenchmarkInstance] = []
    dropped: list[DroppedRow] = []

    with manifest_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"manifest {manifest_path} is empty (no header row)")
        missing = [c for c in _REQUIRED_COLUMNS if c not in reader.fieldnames]
        if not any(c in reader.fieldnames for c in _ANTIBODY_COLUMNS):
            missing.append(f"one of {list(_ANTIBODY_COLUMNS)}")
        if missing:
            raise ValueError(
                f"manifest {manifest_path} is missing required column(s) "
                f"{missing}; it has {sorted(reader.fieldnames)}"
            )
        cutoff_column = f"epitope_residues_{cutoff:g}"
        column = (
            cutoff_column if cutoff_column in reader.fieldnames
            else "epitope_residues"
        )

        for lineno, row in enumerate(reader, start=2):
            epitope = tuple(
                normalise_residue_token(t) for t in _split_field(row.get(column) or "")
            )
            problem = _row_problem(row, epitope, split)
            identifier = (row.get("pdb_id") or "").strip() or f"line {lineno}"
            if problem is not None:
                dropped.append(DroppedRow("manifest", identifier, problem))
                continue
            instances.append(
                BenchmarkInstance(
                    pdb_id=(row["pdb_id"]).strip(),
                    antibody_chains=_antibody_chains(row),
                    antigen_chains=_split_field(row["antigen_chains"]),
                    epitope_residues=frozenset(epitope),
                    cluster_id=row["cluster_id"].strip(),
                    split=(row.get("split") or "").strip(),
                )
            )

    if limit is not None and len(instances) > limit:
        dropped += [
            DroppedRow("manifest", extra.instance_id, f"cut by --limit {limit}")
            for extra in instances[limit:]
        ]
        instances = instances[:limit]

    if not instances:
        reasons = sorted({d.reason for d in dropped}) or ["file had no data rows"]
        raise ValueError(
            f"no evaluable instances in {manifest_path}: {len(dropped)} row(s) "
            f"were dropped. Reasons: {reasons}. Fix the manifest or relax "
            f"--split/--limit; there is nothing to average over."
        )
    return instances, dropped


# ---------------------------------------------------------------------------


# -------------------------------------------------------------------------
# Result
# -------------------------------------------------------------------------
@dataclass(frozen=True)
class EvaluationResult:
    """Everything a report needs, and nothing it has to recompute.

    Shape note: :attr:`primary` is the headline, and :attr:`superiority` is
    conditional. ``superiority is None`` always comes with a
    :attr:`superiority_status` sentence explaining which comparison did not
    run and why.
    """

    arms: tuple[ArmMetrics, ...]
    deltas: tuple[ArmDelta, ...]
    primary: PrimaryAudit | None
    superiority: ArmDelta | None
    superiority_status: str
    n_clusters: int
    n_instances: int
    dropped: tuple[DroppedRow, ...]
    config: Mapping[str, object]
    policy: str = THREE_ZONE_POLICY

    @property
    def superiority_ran(self) -> bool:
        return self.superiority is not None

    @property
    def inconclusive(self) -> bool:
        """True when the superiority delta did not run, or its CI spans zero."""
        return self.superiority is None or self.superiority.inconclusive

    def summary(self) -> dict[str, object]:
        """Machine-readable summary. Key order fixed so the JSON is stable."""
        return {
            "config": dict(sorted(self.config.items(), key=lambda kv: kv[0])),
            "n_instances": self.n_instances,
            "n_clusters": self.n_clusters,
            "n_dropped": len(self.dropped),
            "dropped": [
                {"source": d.source, "identifier": d.identifier, "reason": d.reason}
                for d in self.dropped
            ],
            "primary": None if self.primary is None else self.primary.to_dict(),
            "arms": [a.to_dict() for a in self.arms],
            "deltas": [delta_to_dict(d) for d in self.deltas],
            "superiority_ran": self.superiority_ran,
            "superiority_status": self.superiority_status,
            "superiority": (
                None if self.superiority is None else delta_to_dict(self.superiority)
            ),
            "inconclusive": self.inconclusive,
            "preregistered_mde": PREREGISTERED_MDE,
            "policy": self.policy,
        }

    def to_json(self) -> str:
        """Deterministic JSON: byte-identical for identical inputs and seed."""
        return json.dumps(self.summary(), indent=2, sort_keys=False, allow_nan=True)


# -------------------------------------------------------------------------
# Orchestration
# -------------------------------------------------------------------------
def run_evaluation(
    manifest: Sequence[BenchmarkInstance] | str | Path,
    *,
    arms: Sequence[Arm],
    cutoff: float = 4.5,
    top_k: Sequence[int] = DEFAULT_TOP_K,
    headline_k: int = HEADLINE_K,
    policy: FilterPolicy = FilterPolicy.DROP_PATCH,
    macro: bool = True,
    n_boot: int = 10000,
    seed: int = 0,
    split: str | None = None,
    limit: int | None = None,
    external_arms: Sequence[str] = (),
) -> EvaluationResult:
    """Run the arms, audit the filter, and compute the superiority delta if it can.

    The **primary result** is :class:`PrimaryAudit` on the first filtered arm:
    false-rejection rate with a cluster bootstrap, plus kill-reason
    prevalence. It is computed from the manifest and our own filter alone.

    The **superiority delta** — spec section 4.1's "does our layer improve a
    SOTA predictor" — is computed only when ``external_arms`` names an arm
    that has a filtered counterpart sharing its predictor object. Otherwise
    :attr:`EvaluationResult.superiority` is None and
    :attr:`superiority_status` says the comparison was not run and why; it is
    never reported as a delta of zero. Internal filter deltas are still
    computed and reported, labelled as internal.

    Each filtered arm is paired against the unfiltered arm sharing its
    *predictor object*, which isolates the filter's contribution from the
    predictor's quality. Resampling is over antigen clusters throughout —
    never over patches, which share residues, assembly and reference table on
    one antigen and would give an interval far narrower than the evidence
    supports. ``manifest`` may be loaded instances or a path. Identical inputs
    and ``seed`` give byte-identical output.

    Raises:
        ValueError: on no arms, duplicate arm names, ``headline_k`` outside
            ``top_k``, an ``external_arms`` name that is not an arm, or a
            manifest with no evaluable instances.
    """
    if not arms:
        raise ValueError("run_evaluation needs at least one arm")
    if headline_k not in tuple(top_k):
        raise ValueError(
            f"headline_k={headline_k} must be one of top_k={tuple(top_k)}"
        )
    names = [a.name for a in arms]
    if len(set(names)) != len(names):
        raise ValueError(f"arm names must be unique, got {names}")
    unknown_external = [n for n in external_arms if n not in names]
    if unknown_external:
        raise ValueError(
            f"external_arms names {unknown_external} which are not arms; "
            f"arms are {names}"
        )

    if isinstance(manifest, (str, Path)):
        instances, dropped = load_manifest(
            manifest, cutoff=cutoff, split=split, limit=limit
        )
    else:
        instances = list(manifest)
        dropped = []
        if not instances:
            raise ValueError(
                "run_evaluation received an empty instance list; there is "
                "nothing to average over. Load a manifest with at least one "
                "evaluable row, or check your --split / --limit filters."
            )

    scored = tuple(
        evaluate_arm(instances, arm, top_k=top_k, policy=policy, macro=macro)
        for arm in arms
    )
    by_name = {m.arm: m for m in scored}
    endpoint = f"patch_recall_at_{headline_k}"

    deltas: list[ArmDelta] = []
    for arm in arms:
        partner = _unfiltered_partner(arm, arms) if arm.has_filter else None
        if partner is not None:
            deltas.append(
                paired_delta(
                    by_name[partner.name], by_name[arm.name], endpoint,
                    n_boot=n_boot, seed=seed,
                )
            )

    # Primary result: the audit on the first filtered arm, caller-ordered.
    filtered = [a for a in arms if a.has_filter]
    primary = (
        audit_filter(by_name[filtered[0].name], n_boot=n_boot, seed=seed)
        if filtered
        else None
    )

    external = [n for n in external_arms if n in by_name]
    if not external:
        superiority, status = None, SUPERIORITY_NO_EXTERNAL_ARM
    else:
        candidates = [d for d in deltas if d.baseline in external]
        if not candidates:
            superiority, status = None, SUPERIORITY_NO_PAIR
        else:
            superiority = _pick_headline(candidates, by_name, headline_k, names)
            status = SUPERIORITY_COMPUTED

    return EvaluationResult(
        arms=scored,
        deltas=tuple(deltas),
        primary=primary,
        superiority=superiority,
        superiority_status=status,
        n_clusters=len({i.cluster_id for i in instances}),
        n_instances=len(instances),
        dropped=tuple(dropped),
        config={
            "cutoff": cutoff,
            "top_k": list(top_k),
            "headline_k": headline_k,
            "headline_endpoint": endpoint,
            "filter_policy": policy.value,
            "averaging": "macro_by_cluster" if macro else "micro_by_instance",
            "resampling_unit": "antigen_cluster",
            "n_boot": n_boot,
            "seed": seed,
            "split": split,
            "limit": limit,
            "arms": names,
            "external_arms": list(external_arms),
            "primary_arm": None if primary is None else primary.arm,
        },
    )



def _unfiltered_partner(arm: Arm, arms: Sequence[Arm]) -> Arm | None:
    """The predictor-alone arm sharing ``arm``'s predictor, if present.

    Matched on the predictor object, not a name convention: an arm pair must
    be the *same* predictor, or the delta mixes the filter's effect with a
    predictor change.
    """
    for other in arms:
        if not other.has_filter and other.predictor is arm.predictor:
            return other
    return None


def _pick_headline(
    deltas: Sequence[ArmDelta],
    by_name: Mapping[str, ArmMetrics],
    headline_k: int,
    arm_order: Sequence[str],
) -> ArmDelta | None:
    """The delta on the strongest predictor arm, per spec section 4.1.

    "Strongest" is measured on the unfiltered baseline's own patch recall, so
    the headline cannot be picked by whichever filter happened to win. Ties
    break toward the arm listed first — deterministic and in the caller's
    hands, rather than alphabetical.
    """
    if not deltas:
        return None
    order = {name: i for i, name in enumerate(arm_order)}

    def strength(delta: ArmDelta) -> tuple[float, int]:
        value = by_name[delta.baseline].patch_recall.get(headline_k, float("nan"))
        return (
            value if math.isfinite(value) else -1.0,
            -order.get(delta.baseline, len(order)),
        )

    return max(deltas, key=strength)


# ---------------------------------------------------------------------------
