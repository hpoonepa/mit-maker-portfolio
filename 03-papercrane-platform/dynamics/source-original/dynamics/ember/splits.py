"""Metadata-only partitioning and auditable relatedness/cross-fitting rules."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from .io import content_hash
from .schema import Target, unique_ids


@dataclass(frozen=True)
class SimilarityEdge:
    left: str
    right: str
    identity: float
    shorter_coverage: float
    source: str

    def __post_init__(self) -> None:
        for value in (self.identity, self.shorter_coverage):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Similarity fractions must be in [0,1]")
        if not self.left or not self.right or not self.source:
            raise ValueError("Similarity IDs and source are required")


def parse_mmseqs_tsv(path: str | Path) -> list[SimilarityEdge]:
    """Read explicit columns query,target,fident,qcov,tcov,qlen,tlen.

    Use MMseqs2 --format-output 'query,target,fident,qcov,tcov,qlen,tlen'.
    fident is fractional identity, NOT pident in percent. No search runs here.
    """
    edges = []
    with Path(path).open() as handle:
        for number, row in enumerate(csv.reader(handle, delimiter="\t"), 1):
            if not row:
                continue
            if len(row) != 7:
                raise ValueError(f"Similarity row {number} must have seven explicit columns")
            left, right, identity, qcov, tcov, qlen, tlen = row
            qlength, tlength = int(qlen), int(tlen)
            if qlength <= 0 or tlength <= 0:
                raise ValueError("Sequence lengths must be positive")
            coverage = float(qcov) if qlength <= tlength else float(tcov)
            edges.append(SimilarityEdge(left, right, float(identity), coverage, "mmseqs2_tsv"))
    return edges


def relatedness_groups(
    target_ids: list[str],
    edges: list[SimilarityEdge],
    *,
    identity: float = 0.4,
    shorter_coverage: float = 0.8,
) -> dict[str, str]:
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("Duplicate target IDs")
    if not 0 <= identity <= 1 or not 0 <= shorter_coverage <= 1:
        raise ValueError("Relatedness thresholds must be fractions")
    parent = {target_id: target_id for target_id in target_ids}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for edge in sorted(edges, key=lambda e: (e.left, e.right)):
        if edge.left not in parent or edge.right not in parent:
            raise ValueError("Similarity edge contains a target outside the audit universe")
        if edge.identity >= identity and edge.shorter_coverage >= shorter_coverage:
            a, b = sorted((find(edge.left), find(edge.right)))
            parent[b] = a
    members: dict[str, list[str]] = {}
    for target_id in sorted(parent):
        members.setdefault(find(target_id), []).append(target_id)
    names = {root: "group-" + content_hash(ids)[:16] for root, ids in members.items()}
    return {target_id: names[find(target_id)] for target_id in sorted(parent)}


def partition_conflicts(targets: list[Target]) -> dict:
    """Report conflicts and purge recommendations; never silently moves test IDs."""
    unique_ids(targets, "target_id")
    grouped = {}
    for target in targets:
        grouped.setdefault(target.group_id, []).append(target)
    conflicts = []
    for group_id, members in sorted(grouped.items()):
        parts = {m.partition for m in members}
        if len(parts) > 1:
            conflicts.append(
                {
                    "group_id": group_id,
                    "partitions": sorted(parts),
                    "target_ids": sorted(m.target_id for m in members),
                    "training_relatives_to_purge": sorted(
                        m.target_id
                        for m in members
                        if m.partition in {"train", "development"} and parts & {"test", "external"}
                    ),
                    "test_external_overlap": {"test", "external"} <= parts,
                }
            )
    sequences = {}
    for target in targets:
        sequences.setdefault(target.sequence, []).append(target)
    exact_duplicates = [
        sorted(m.target_id for m in members)
        for members in sequences.values()
        if len({m.partition for m in members}) > 1
    ]
    return {
        "group_conflicts": conflicts,
        "cross_partition_identical_sequences": sorted(exact_duplicates),
        "passed": not conflicts and not exact_duplicates,
        "note": "Requires a completed similarity search; singleton groups alone prove nothing about homology.",
    }


def crossfit_folds(targets: list[Target], *, folds: int = 3, seed: int = 1729) -> dict[str, int]:
    if type(folds) is not int or folds < 2:
        raise ValueError("Cross-fitting needs at least two folds")
    unique_ids(targets, "target_id")
    if not targets or any(t.partition != "train" for t in targets):
        raise ValueError("Cross-fitting partitions training targets only")
    groups = sorted({t.group_id for t in targets}, key=lambda g: content_hash([seed, g]))
    if len(groups) < folds:
        raise ValueError("Fewer independent training groups than cross-fitting folds")
    assigned = {group: i % folds for i, group in enumerate(groups)}
    return {t.target_id: assigned[t.group_id] for t in targets}


def validate_oof_lineage(target: Target, lineage: dict, allowed_training_groups: set[str]) -> None:
    """Reject optimistic in-sample R0 scores when stacking the site ranker."""
    required = {
        "checkpoint_sha256",
        "trained_group_ids",
        "selection_group_ids",
        "prediction_target_id",
        "role",
    }
    if not required <= set(lineage):
        raise ValueError("Incomplete R0 prediction lineage")
    from .schema import require_hash

    require_hash(lineage["checkpoint_sha256"], "R0 checkpoint_sha256")
    trained = set(lineage["trained_group_ids"])
    selected = set(lineage["selection_group_ids"])
    if not selected or trained & selected:
        raise ValueError("R0 fitting and model-selection groups must be nonempty and disjoint")
    if (
        lineage["prediction_target_id"] != target.target_id
        or not trained
        or not trained <= allowed_training_groups
    ):
        raise ValueError("R0 lineage does not match allowed training universe")
    if target.group_id in trained:
        raise ValueError("R0 predictions include a group seen during R0 training")
    if target.partition == "train" and (
        target.group_id in selected or not selected <= allowed_training_groups
    ):
        raise ValueError("Out-of-fold R0 predictions used held-out labels for model selection")
    if target.partition in {"test", "external"} and target.group_id in selected:
        raise ValueError("Held-out evaluation group was used for model selection")
    expected = "out_of_fold" if target.partition == "train" else "full_train_inference"
    if lineage["role"] != expected:
        raise ValueError(f"Expected R0 lineage role {expected}")


def crossfit_plan(
    targets: list[Target], *, folds: int = 3, seed: int = 1729, selection_fraction: float = 0.2
) -> dict:
    """Describe nested held-out predictions without reading a single label.

    The scored outer group is excluded from both optimization and epoch selection.
    Inner selection records must be explicitly copied with partition=development
    for each R0 fit, never by mutating the global training manifest.
    """
    if not math.isfinite(selection_fraction) or not 0 < selection_fraction < 1:
        raise ValueError("Inner selection fraction must lie strictly between zero and one")
    assignments = crossfit_folds(targets, folds=folds, seed=seed)
    all_groups = {t.group_id for t in targets}
    runs = []
    for outer in range(folds):
        prediction_groups = {t.group_id for t in targets if assignments[t.target_id] == outer}
        remaining = sorted(all_groups - prediction_groups, key=lambda g: content_hash([seed, outer, g]))
        if len(remaining) < 2:
            raise ValueError("Each cross-fit run needs distinct optimization and inner-selection groups")
        count = max(1, min(len(remaining) - 1, math.ceil(len(remaining) * selection_fraction)))
        selection_groups = set(remaining[:count])
        training_groups = set(remaining[count:])
        run = {"outer_fold": outer}
        for name, groups in (
            ("training", training_groups),
            ("selection", selection_groups),
            ("prediction", prediction_groups),
        ):
            run[name + "_groups"] = sorted(groups)
            run[name + "_target_ids"] = sorted(t.target_id for t in targets if t.group_id in groups)
        runs.append(run)
    return {
        "schema_version": "1",
        "input_sha256": content_hash(sorted(targets, key=lambda t: t.target_id)),
        "seed": seed,
        "selection_fraction": selection_fraction,
        "folds": assignments,
        "runs": runs,
        "executed": False,
        "note": "Outer prediction labels must never select epochs or hyperparameters for that run.",
    }


def metadata_subset(targets: list[Target], maximum_groups: int, *, seed: int = 1729) -> list[Target]:
    """Choose complete groups without scores or annotations; keep all group members."""
    if type(maximum_groups) is not int or maximum_groups < 1:
        raise ValueError("maximum_groups must be positive")
    unique_ids(targets, "target_id")
    groups = sorted({t.group_id for t in targets if t.eligible}, key=lambda g: content_hash([seed, g]))
    selected = set(groups[:maximum_groups])
    return sorted([t for t in targets if t.eligible and t.group_id in selected], key=lambda t: t.target_id)
