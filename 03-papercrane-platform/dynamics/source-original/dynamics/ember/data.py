"""Read declared local releases; no fetching, pickle execution or label-derived features."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .candidates import jaccard
from .io import content_hash, file_hash, read_json, read_jsonl
from .mapping import ChainMapping, map_author_sites, parse_author_selection
from .schema import Reference, ReferenceSite, Target, from_dict, unique_ids, validate_targets


def load_targets(path: str | Path, *, verify_files: bool = False) -> list[Target]:
    targets = [from_dict(Target, row) for row in read_jsonl(path)]
    validate_targets(targets)
    if verify_files:
        for target in targets:
            if file_hash(target.apo_path) != target.apo_sha256:
                raise ValueError(f"Apo file hash mismatch: {target.target_id}")
    return targets


def load_references(path: str | Path) -> list[Reference]:
    references = [from_dict(Reference, row) for row in read_jsonl(path)]
    unique_ids(references, "target_id")
    return references


def manifest_summary(targets: list[Target]) -> dict:
    unique_ids(targets, "target_id")
    return {
        "targets": len(targets),
        "groups": len({t.group_id for t in targets}),
        "partitions": dict(Counter(t.partition for t in targets)),
        "eligible": sum(t.eligible for t in targets),
        "exclusions": dict(Counter(t.exclusion_reason for t in targets if not t.eligible)),
        "sha256": content_hash(sorted(targets, key=lambda t: t.target_id)),
    }


def inspect_cryptobench_schema(dataset_path: str | Path) -> dict:
    """Inventory schema/counts only; use training release for development work."""
    dataset = read_json(dataset_path)
    if not isinstance(dataset, dict):
        raise ValueError("CryptoBench release must map apo PDB IDs to pair records")
    required = {
        "apo_chain",
        "holo_pdb_id",
        "holo_chain",
        "ligand",
        "ligand_index",
        "ligand_chain",
        "apo_pocket_selection",
        "holo_pocket_selection",
    }
    chains = set()
    total = multichain = 0
    for apo_id, pairs in dataset.items():
        if not isinstance(apo_id, str) or len(apo_id) != 4 or not isinstance(pairs, list) or not pairs:
            raise ValueError("Malformed CryptoBench apo entry")
        for pair in pairs:
            if not isinstance(pair, dict) or not required <= set(pair):
                raise ValueError(f"CryptoBench pair missing fields for {apo_id}")
            selected_chains = {parse_author_selection(s).chain for s in pair["apo_pocket_selection"]}
            if not selected_chains:
                raise ValueError(f"Empty site annotation: {apo_id}")
            total += 1
            multichain += len(selected_chains) > 1
            chains.update((apo_id, chain) for chain in selected_chains)
    return {
        "apo_structures": len(dataset),
        "apo_chain_identities_in_labels": len(chains),
        "pair_records": total,
        "multichain_site_records": multichain,
        "source_sha256": file_hash(dataset_path),
        "note": "Source inventory; eligibility and independent analysis groups require separate audits.",
    }


def build_cryptobench_reference(
    target: Target,
    pairs: list[dict],
    mapping: ChainMapping,
    *,
    source_sha256: str,
    reference_merge_jaccard: float = 0.75,
) -> tuple[Reference, dict]:
    """Convert author annotations, preserving exact holo/ligand identities.

    Duplicate ligand/pair observations are grouped by complete-link residue
    overlap. The medoid is the representative reference site. This is a CUSTOM
    site-level adaptation, not CryptoBench's official pooled residue protocol.
    References crossing the selected chain fail rather than silently truncating.
    Freeze this merge rule before evaluating model outputs.
    """
    if target.sequence != mapping.sequence or target.chain_id != mapping.chain_id:
        raise ValueError("Reference mapping differs from target")
    if not 0 < reference_merge_jaccard <= 1:
        raise ValueError("Reference merge threshold must be in (0,1]")
    records = []
    for pair in pairs:
        selections = pair["apo_pocket_selection"]
        chains = {parse_author_selection(s).chain for s in selections}
        if target.chain_id not in chains:
            continue
        if chains != {target.chain_id}:
            raise ValueError("Unsupported multi-chain annotated site; resolve eligibility before freeze")
        residues = map_author_sites(selections, mapping)
        provenance = {
            key: pair[key] for key in ("holo_pdb_id", "holo_chain", "ligand", "ligand_index", "ligand_chain")
        }
        identity = content_hash({"provenance": provenance, "residues": residues})
        records.append({"id": identity, "residues": residues, "provenance": provenance})
    if not records:
        raise ValueError("No mapped cryptic-site annotations for selected apo chain")
    unique = {record["id"]: record for record in records}
    groups = []
    for record in sorted(unique.values(), key=lambda r: r["id"]):
        choices = [
            (-min(jaccard(record["residues"], other["residues"]) for other in group), i)
            for i, group in enumerate(groups)
            if all(
                jaccard(record["residues"], other["residues"]) >= reference_merge_jaccard for other in group
            )
        ]
        if choices:
            groups[min(choices)[1]].append(record)
        else:
            groups.append([record])
    sites, audit = [], []
    for group in groups:
        medoid = min(
            group, key=lambda r: (-sum(jaccard(r["residues"], other["residues"]) for other in group), r["id"])
        )
        site_id = "ref-" + content_hash([r["id"] for r in group])[:16]
        sites.append(ReferenceSite(site_id, medoid["residues"]))
        audit.append({"site_id": site_id, "medoid_pair_id": medoid["id"], "pairs": group})
    # All supplied positive residue annotations supervise the residue task, even
    # if the medoid for the separate site metric uses a smaller residue set.
    positive = set().union(*(set(r["residues"]) for r in records))
    labels = tuple(int(i in positive) for i in range(len(target.sequence)))
    mask = mapping.observed_mask
    return Reference(
        target.target_id, tuple(sites), source_sha256, residue_labels=labels, residue_label_mask=mask
    ), {
        "reference_merge_jaccard": reference_merge_jaccard,
        "input_pair_records": len(records),
        "unique_pair_records": len(unique),
        "grouped_sites": audit,
    }
