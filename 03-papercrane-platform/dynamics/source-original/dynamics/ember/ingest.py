"""Convert reviewed structural metadata into typed input/reference manifests.

Eligibility attestations come from human/source metadata review. Biological
monomer status requires assembly metadata; asymmetric-unit chain counts and
predicted hit counts are separate fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .data import build_cryptobench_reference, manifest_summary
from .io import atomic_write_json, content_hash, file_hash, read_json, write_jsonl
from .mapping import mmcif_canonical_mapping
from .schema import Target, validate_targets


@dataclass(frozen=True)
class ReviewedTarget:
    target_id: str
    apo_pdb_id: str
    apo_path: str
    chain_id: str
    model_index: int
    assembly_id: str
    group_id: str
    partition: str
    soluble_folded_monomer_supported: bool
    unsupported_chemistry_present: bool
    review_evidence: str


def ingest_cryptobench(
    dataset_path: str | Path,
    official_folds_path: str | Path,
    records: list[ReviewedTarget],
    output_directory: str | Path,
    *,
    minimum_length: int = 80,
    maximum_length: int = 350,
    reference_merge_jaccard: float = 0.75,
) -> dict:
    if minimum_length < 1 or maximum_length < minimum_length:
        raise ValueError("Invalid eligibility length range")
    if len({r.target_id for r in records}) != len(records):
        raise ValueError("Duplicate reviewed target IDs")
    dataset = read_json(dataset_path)
    folds = read_json(official_folds_path)
    if "test" not in folds:
        raise ValueError("Official test split is required")
    official = {}
    for fold, ids in folds.items():
        for pdb_id in ids:
            if pdb_id in official:
                raise ValueError("Duplicate structure across official folds")
            official[pdb_id] = "test" if fold == "test" else "train"
    source_hash = file_hash(dataset_path)
    targets, references, mappings, failures, annotations = [], [], [], [], []
    for record in sorted(records, key=lambda r: r.target_id):
        if not record.review_evidence.strip():
            raise ValueError("Every target needs documented eligibility-review evidence")
        pdb_id = record.apo_pdb_id.lower()
        if pdb_id not in official or pdb_id not in dataset:
            raise ValueError(f"Reviewed target absent from declared release/split: {pdb_id}")
        if (official[pdb_id] == "test") != (record.partition == "test"):
            raise ValueError("Official test assignment must be preserved")
        if record.partition not in {"train", "development", "test"}:
            raise ValueError("CryptoBench importer supports train/development/test only")
        try:
            mapping = mmcif_canonical_mapping(
                record.apo_path, model_index=record.model_index, chain_id=record.chain_id
            )
        except (ValueError, KeyError) as error:
            failures.append(
                {
                    "target_id": record.target_id,
                    "status": "mapping_failed_before_freeze",
                    "reason": str(error),
                    "review": asdict(record),
                }
            )
            continue
        reason = None
        if not record.soluble_folded_monomer_supported:
            reason = "unsupported_biological_scope"
        elif record.unsupported_chemistry_present:
            reason = "unsupported_required_chemistry"
        elif not minimum_length <= len(mapping.sequence) <= maximum_length:
            reason = "outside_prespecified_length_range"
        target = Target(
            record.target_id,
            mapping.sequence,
            "CryptoBench",
            source_hash,
            record.apo_path,
            file_hash(record.apo_path),
            record.model_index,
            record.chain_id,
            record.assembly_id,
            record.group_id,
            record.partition,
            reason is None,
            reason,
        )
        if reason is None:
            try:
                reference, annotation_audit = build_cryptobench_reference(
                    target,
                    dataset[pdb_id],
                    mapping,
                    source_sha256=source_hash,
                    reference_merge_jaccard=reference_merge_jaccard,
                )
                references.append(reference)
                annotations.append({"target_id": target.target_id, **annotation_audit})
            except ValueError as error:
                failures.append(
                    {
                        "target_id": target.target_id,
                        "status": "reference_invalid_before_freeze",
                        "reason": str(error),
                        "review": asdict(record),
                    }
                )
                # Do not silently revise eligibility based on an invalid reference.
                # Audit must be resolved before this manifest can be frozen.
        targets.append(target)
        mappings.append({"target_id": target.target_id, "mapping": asdict(mapping)})
    validate_targets(targets)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(output / "inputs/targets.jsonl", [asdict(t) for t in targets])
    write_jsonl(output / "inputs/mappings.jsonl", mappings)
    write_jsonl(output / "references/sites.jsonl", [asdict(r) for r in references])
    write_jsonl(output / "references/annotation-audit.jsonl", annotations)
    report = {
        "manifest": manifest_summary(targets),
        "reviewed_records": len(records),
        "failures": failures,
        "ingestion_checks_passed": not failures,
        "protocol_frozen": False,
        "eligibility_rules": {"minimum_length": minimum_length, "maximum_length": maximum_length},
        "official_folds_sha256": file_hash(official_folds_path),
        "review_sha256": content_hash(records),
        "note": "Relatedness and source-model exposure audits are separate requirements.",
    }
    atomic_write_json(output / "ingestion-report.json", report)
    return report
