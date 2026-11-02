"""Inspectable experiment plan and readiness checks that emit configuration for later execution."""

from __future__ import annotations

from pathlib import Path

from .budget import DEFAULT_ALLOCATIONS
from .io import content_hash, file_hash, read_json


def implementation_hash(root: str | Path | None = None) -> str:
    root = Path(root) if root else Path(__file__).parent
    files = {
        str(path.relative_to(root)): file_hash(path)
        for path in sorted(root.rglob("*.py"))
        if not {"research", "tests", "model_checks"} & set(path.relative_to(root).parts)
    }
    return content_hash(files)


def experiment_plan() -> dict:
    return {
        "schema_version": "1",
        "experiment_id": "ember-pocket-v0-2026-09-28",
        "status": "implementation_authored_model_execution_pending",
        "spend_authorized": False,
        "model_execution_authorized": False,
        "implementation_sha256": implementation_hash(),
        "task": "apo_input_cryptic_site_prioritization",
        "scope": {
            "soluble_folded_monomers": True,
            "proposed_length_range": [80, 350],
            "explicit_chain_model_assembly": True,
            "eligibility_frozen": False,
        },
        "models": {
            "residue": {
                "kind": "residue_mlp",
                "encoder": "esm2_t30_150M_UR50D",
                "input_width": 640,
                "hidden_widths": [256, 128],
                "dropout": 0.1,
                "analytical_parameter_count": 198401,
                "parameter_count_measured": False,
            },
            "static": {"default": "site_linear", "comparison": "site_mlp", "hidden_widths": [64, 32]},
            "ensemble": {
                "default": "ensemble_linear",
                "comparison": "ensemble_mlp",
                "frozen_static": True,
                "zero_initialized_correction": True,
                "frequency_ablation": "required_before_claiming_geometry_gain",
            },
        },
        "candidates": {
            "grouping_jaccard": 0.35,
            "complete_link": True,
            "medoid_residues": True,
            "cap": 64,
            "rare_openings_retained": True,
            "dedup_jaccard": 0.5,
        },
        "evaluation": {
            "primary": "macro_protein_recall_at_3",
            "match_jaccard": 0.25,
            "matching": "maximum_cardinality_one_to_one",
            "failures": "miss",
            "reference_merge_jaccard": 0.75,
            "reference_merge_rule_frozen": False,
            "paired_bootstrap_unit": "family_group",
            "bootstrap_resamples": 10000,
            "official_protocol_separate": True,
            "protocol_frozen": False,
        },
        "sampling": {
            "generator": "bioemu-v1.1",
            "smoke_requested_frames": 16,
            "proposed_fixed_requested_frames": 32,
            "unordered": True,
            "topology_plus_xtc_required": True,
            "reconstruction_only_initial_plan": True,
            "all_atom_quality_gate_required": True,
        },
        "budget_usd": DEFAULT_ALLOCATIONS,
        "readiness": {
            "original_release_and_use_terms_verified": False,
            "eligible_manifest_and_relatedness_audit_frozen": False,
            "foundation_checkpoint_and_environment_hashes_verified": False,
            "real_external_adapters_smoke_passed": False,
            "model_contract_and_resume_checks_passed": False,
            "physical_quality_thresholds_frozen": False,
            "stratified_end_to_end_cost_measured": False,
            "provider_timeout_receipts_and_shutdown_verified": False,
            "benchmark_protocol_frozen": False,
        },
        "readiness_evidence": {},
        "stages": [
            {
                "stage": "local_contracts",
                "allowed_now": True,
                "deliverable": "Source audit, schemas, parsers, mapping, matching, cache, model code and plans.",
            },
            {
                "stage": "model_contracts_and_external_smoke",
                "allowed_now": False,
                "deliverable": "Tiny deterministic model checks and development-only tool profiling.",
            },
            {
                "stage": "cached_features_and_static_baselines",
                "allowed_now": False,
                "deliverable": "Frozen embeddings, grouped cross-fitted R0, static S0 and native baselines.",
            },
            {
                "stage": "ensemble_correction",
                "allowed_now": False,
                "deliverable": "Accepted conformers, E0, fixed-pool ablations and development decision.",
            },
            {
                "stage": "frozen_test",
                "allowed_now": False,
                "deliverable": "Once-per-release predictions, failure-inclusive results, paired uncertainty and cost.",
            },
        ],
        "guard_note": "The plan and ledger track proposed work and reservations; provider controls and billing authorization are separate requirements.",
    }


def preflight(plan: dict) -> dict:
    expected = experiment_plan()["readiness"]
    supplied = plan.get("readiness", {})
    missing = [name for name in expected if supplied.get(name) is not True]
    for name in expected:
        if supplied.get(name) is not True:
            continue
        evidence = plan.get("readiness_evidence", {}).get(name)
        if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}:
            missing.append(name + "_evidence_receipt")
            continue
        try:
            if file_hash(evidence["path"]) != evidence["sha256"]:
                missing.append(name + "_evidence_checksum")
                continue
            receipt = read_json(evidence["path"])
            if receipt.get("check") != name or receipt.get("status") != "passed":
                missing.append(name + "_evidence_failed_or_wrong_check")
        except (FileNotFoundError, ValueError):
            missing.append(name + "_evidence_unreadable")
    if plan.get("implementation_sha256") != implementation_hash():
        missing.append("implementation_hash_matches_current_code")
    if plan.get("model_execution_authorized") is not True:
        missing.append("explicit_model_execution_authorization")
    if plan.get("spend_authorized") is not True:
        missing.append("explicit_paid_compute_authorization_if_paid_execution_is_planned")
    return {
        "ready_for_full_paid_experiment": not missing,
        "unresolved": missing,
        "note": "Readiness flags summarize evidence artifacts; verify those artifacts before execution.",
    }


def research_inventory() -> dict:
    root = Path(__file__).parent / "research"
    report = root / "cryptobench-metadata/inventory-report.json"
    return {
        "sources": read_json(root / "sources.json"),
        "cryptobench": read_json(report) if report.exists() else None,
        "test_annotations_downloaded": False,
        "model_executions": 0,
        "cloud_jobs_launched": 0,
    }
