"""Join declared caches with training-only references for future authorized fits."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from .data import load_references, load_targets
from .embeddings import EmbeddingCache, EmbeddingKey
from .execution import ExecutionPolicy
from .features import ENSEMBLE_NAMES, STATIC_NAMES, FeatureNormalizer
from .io import atomic_write_json, content_hash, file_hash, read_jsonl
from .predict import load_release, normalizer_from_dict
from .prepared import read_prepared
from .release_contract import release_binding, validate_release_checkpoint
from .schema import Target, from_dict
from .splits import validate_oof_lineage
from .supervision import site_overlap_targets, training_positive_weight
from .train import TrainingConfig, TrainingExample, fit, load_checkpoint


def _load_training_contract(target_path, reference_path):
    targets = load_targets(target_path)
    if not targets or any(t.partition not in {"train", "development"} or not t.eligible for t in targets):
        raise ValueError("Training manifest must contain eligible train/development targets only")
    references = load_references(reference_path)
    lookup = {r.target_id: r for r in references}
    if set(lookup) != {t.target_id for t in targets}:
        raise ValueError(
            "Training reference cohort differs from declared targets; no test references allowed"
        )
    if any(not r.valid for r in references):
        raise ValueError("Resolve invalid training references before feature/training work")
    return targets, lookup


def _release(
    output: Path,
    report: dict,
    config: TrainingConfig,
    *,
    method_id: str,
    targets: list[Target],
    split_sha256: str,
    code_sha256: str,
    static_normalizer=None,
    ensemble_normalizer=None,
    feature_policy_sha256=None,
    base_kind=None,
    proposal_source=None,
    residue_encoder=None,
    policy: ExecutionPolicy,
) -> dict | None:
    best = output / "best-development.pt"
    if not report["best_checkpoint_available"]:
        return None
    checkpoint = load_checkpoint(best, policy=policy)
    release = {
        "schema_version": "1",
        "method_id": method_id,
        "kind": config.kind,
        "checkpoint_file": best.name,
        "checkpoint_sha256": file_hash(best),
        "width": checkpoint["width"],
        "ensemble_width": checkpoint["ensemble_width"],
        "dropout": config.dropout,
        "base_kind": base_kind,
        "static_normalizer": asdict(static_normalizer) if static_normalizer else None,
        "ensemble_normalizer": asdict(ensemble_normalizer) if ensemble_normalizer else None,
        "feature_policy_sha256": feature_policy_sha256,
        "split_sha256": split_sha256,
        "training_groups": sorted({t.group_id for t in targets if t.partition == "train"}),
        "selection_groups": sorted({t.group_id for t in targets if t.partition == "development"}),
        "code_sha256": code_sha256,
        "proposal_source": proposal_source,
        "residue_encoder": residue_encoder,
        "status": "trained_development_selected",
        "test_benchmark_evaluated": False,
        "fit_signature": checkpoint["signature"],
        "ensemble_variant": config.ensemble_variant,
    }
    validate_release_checkpoint(release, checkpoint)
    atomic_write_json(output / "release.json", release)
    return release


def _binding_metadata(
    targets,
    split_sha256,
    code_sha256,
    *,
    static_normalizer=None,
    ensemble_normalizer=None,
    feature_policy_sha256=None,
    base_kind=None,
    proposal_source=None,
    residue_encoder=None,
):
    return {
        "base_kind": base_kind,
        "static_normalizer": asdict(static_normalizer) if static_normalizer else None,
        "ensemble_normalizer": asdict(ensemble_normalizer) if ensemble_normalizer else None,
        "feature_policy_sha256": feature_policy_sha256,
        "split_sha256": split_sha256,
        "training_groups": sorted({t.group_id for t in targets if t.partition == "train"}),
        "selection_groups": sorted({t.group_id for t in targets if t.partition == "development"}),
        "code_sha256": code_sha256,
        "proposal_source": proposal_source,
        "residue_encoder": residue_encoder,
    }


def fit_residue_from_cache(
    target_path: str | Path,
    reference_path: str | Path,
    embedding_keys_path: str | Path,
    embedding_cache: str | Path,
    *,
    output_dir: str | Path,
    config: TrainingConfig,
    policy: ExecutionPolicy,
    code_sha256: str,
    method_id: str = "ember-r0",
    resume: str | Path | None = None,
) -> dict:
    policy.require_model_execution("R0 cached-feature training")
    if not config.kind.startswith("residue"):
        raise ValueError("Residue workflow requires residue model kind")
    targets, refs = _load_training_contract(target_path, reference_path)
    keys = {}
    for row in read_jsonl(embedding_keys_path):
        if set(row) != {"target_id", "key"} or row["target_id"] in keys:
            raise ValueError("Invalid/duplicate embedding key record")
        keys[row["target_id"]] = from_dict(EmbeddingKey, row["key"])
    if set(keys) != {t.target_id for t in targets}:
        raise ValueError("Embedding keys differ from allowed target cohort")
    encoder_specs = {
        content_hash({k: v for k, v in asdict(key).items() if k != "sequence"}) for key in keys.values()
    }
    if len(encoder_specs) != 1:
        raise ValueError("Mixed encoder versions in training embeddings")
    cache = EmbeddingCache(embedding_cache)
    examples = []
    for target in targets:
        key, ref = keys[target.target_id], refs[target.target_id]
        if (
            key.sequence != target.sequence
            or ref.residue_labels is None
            or len(ref.residue_labels) != len(target.sequence)
        ):
            raise ValueError("Residue feature/reference/sequence mismatch")
        examples.append(
            TrainingExample(
                target.target_id,
                target.group_id,
                target.partition,
                cache.load(key),
                np.asarray(ref.residue_labels, dtype=np.float32),
                np.asarray(ref.residue_label_mask, dtype=bool),
            )
        )
    actual = replace(
        config, positive_weight=training_positive_weight([t for t in targets if t.partition == "train"], refs)
    )
    split_hash = content_hash(sorted(targets, key=lambda t: t.target_id))
    first = next(iter(keys.values()))
    encoder = {k: v for k, v in asdict(first).items() if k != "sequence"}
    report = fit(
        [e for e in examples if e.partition == "train"],
        [e for e in examples if e.partition == "development"],
        config=actual,
        output_dir=output_dir,
        policy=policy,
        split_sha256=split_hash,
        code_sha256=code_sha256,
        release_binding_sha256=release_binding(
            _binding_metadata(targets, split_hash, code_sha256, residue_encoder=encoder)
        ),
        resume=resume,
    )
    release = _release(
        Path(output_dir),
        report,
        actual,
        method_id=method_id,
        targets=targets,
        split_sha256=split_hash,
        code_sha256=code_sha256,
        residue_encoder=encoder,
        policy=policy,
    )
    return {"training": report, "release": release}


def fit_ranker_from_cache(
    target_path: str | Path,
    reference_path: str | Path,
    bundle_index_path: str | Path,
    *,
    output_dir: str | Path,
    config: TrainingConfig,
    policy: ExecutionPolicy,
    code_sha256: str,
    method_id: str = "ember-s0",
    base_release: str | Path | None = None,
    resume: str | Path | None = None,
) -> dict:
    policy.require_model_execution("Site ranker cached-feature training")
    if config.kind.startswith("residue"):
        raise ValueError("Site workflow requires site or ensemble model kind")
    targets, refs = _load_training_contract(target_path, reference_path)
    rows = read_jsonl(bundle_index_path)
    if any(set(row) != {"target_id", "directory", "manifest_sha256"} for row in rows):
        raise ValueError("Invalid prepared bundle index")
    index = {row["target_id"]: row for row in rows}
    if len(index) != len(rows) or set(index) != {t.target_id for t in targets}:
        raise ValueError("Bundle index differs from training target universe")
    allowed_groups = {t.group_id for t in targets if t.partition == "train"}
    bundles = []
    for target in targets:
        row = index[target.target_id]
        if file_hash(Path(row["directory"]) / "manifest.json") != row["manifest_sha256"]:
            raise ValueError("Bundle completion manifest checksum differs")
        bundle = read_prepared(row["directory"])
        if bundle.target != target:
            raise ValueError("Prepared target differs from frozen training record")
        validate_oof_lineage(target, bundle.r0_lineage, allowed_groups)
        bundles.append(bundle)
    policies = {b.feature_policy_sha256 for b in bundles}
    proposals = {b.proposal_source for b in bundles}
    if len(policies) != 1 or len(proposals) != 1:
        raise ValueError("Mixed feature policies or proposal tracks in one training run")
    feature_policy = policies.pop()
    proposal_source = proposals.pop()
    split_hash = content_hash(sorted(targets, key=lambda t: t.target_id))
    training = [b for b in bundles if b.target.partition == "train"]
    normalization_args = {
        "target_ids": [b.target.target_id for b in training],
        "partitions": ["train"] * len(training),
        "split_sha256": split_hash,
    }
    static_model = None
    static_checkpoint_sha256 = base_kind = None
    ensemble_norm = None
    if config.kind.startswith("ensemble"):
        if base_release is None:
            raise ValueError("E0 requires a trained static release")
        static_model, base = load_release(base_release, policy=policy, device=config.device)
        if (
            base["kind"] not in {"site_linear", "site_mlp"}
            or base["split_sha256"] != split_hash
            or base["feature_policy_sha256"] != feature_policy
        ):
            raise ValueError("S0 release does not match E0 training split/feature policy")
        if set(base["training_groups"]) != allowed_groups:
            raise ValueError("S0 training groups differ from E0")
        static_norm = normalizer_from_dict(base["static_normalizer"])
        if static_norm.split_sha256 != split_hash or set(static_norm.fit_target_ids) != {
            t.target_id for t in targets if t.partition == "train"
        }:
            raise ValueError("S0 normalizer was fitted on a different target population")
        base_kind, static_checkpoint_sha256 = base["kind"], base["checkpoint_sha256"]
        ensemble_norm = FeatureNormalizer.fit(
            [b.ensemble for b in training], names=ENSEMBLE_NAMES, **normalization_args
        )
    else:
        static_norm = FeatureNormalizer.fit(
            [b.static for b in training], names=STATIC_NAMES, **normalization_args
        )
    examples = []
    for bundle in bundles:
        target = bundle.target
        ref = refs[target.target_id]
        examples.append(
            TrainingExample(
                target.target_id,
                target.group_id,
                target.partition,
                static_norm.transform(bundle.static, names=STATIC_NAMES),
                site_overlap_targets(list(bundle.sites), ref),
                ensemble=ensemble_norm.transform(bundle.ensemble, names=ENSEMBLE_NAMES)
                if ensemble_norm
                else None,
                ensemble_available=bool(bundle.valid_frame_ids),
                site_ids=tuple(s.site_id for s in bundle.sites),
                site_residues=tuple(s.residues for s in bundle.sites),
                reference_residues=tuple(s.residues for s in ref.sites),
            )
        )
    report = fit(
        [e for e in examples if e.partition == "train"],
        [e for e in examples if e.partition == "development"],
        config=config,
        output_dir=output_dir,
        policy=policy,
        split_sha256=split_hash,
        code_sha256=code_sha256,
        static_model=static_model,
        static_checkpoint_sha256=static_checkpoint_sha256,
        release_binding_sha256=release_binding(
            _binding_metadata(
                targets,
                split_hash,
                code_sha256,
                static_normalizer=static_norm,
                ensemble_normalizer=ensemble_norm,
                feature_policy_sha256=feature_policy,
                base_kind=base_kind,
                proposal_source=proposal_source,
            )
        ),
        resume=resume,
    )
    release = _release(
        Path(output_dir),
        report,
        config,
        method_id=method_id,
        targets=targets,
        split_sha256=split_hash,
        code_sha256=code_sha256,
        static_normalizer=static_norm,
        ensemble_normalizer=ensemble_norm,
        feature_policy_sha256=feature_policy,
        base_kind=base_kind,
        proposal_source=proposal_source,
        policy=policy,
    )
    return {"training": report, "release": release}
