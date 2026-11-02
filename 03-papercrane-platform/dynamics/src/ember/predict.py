"""Reference-free inference on prepared caches; no target labels are accepted."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np

from .candidates import ranked_unique, representative
from .embeddings import EmbeddingKey
from .execution import ExecutionPolicy
from .features import ENSEMBLE_NAMES, STATIC_NAMES, FeatureNormalizer, ensemble_ablation
from .io import content_hash, file_hash, read_json
from .prepared import PreparedTarget
from .release_contract import validate_release_checkpoint
from .schema import Prediction, RankedSite, Target


def normalizer_from_dict(value: dict) -> FeatureNormalizer:
    allowed = {
        "names",
        "mean",
        "scale",
        "varying_columns",
        "observed_columns",
        "fit_target_ids",
        "split_sha256",
    }
    if set(value) != allowed:
        raise ValueError("Invalid normalizer manifest")
    return FeatureNormalizer(
        tuple(value["names"]),
        tuple(value["mean"]),
        tuple(value["scale"]),
        tuple(value["varying_columns"]),
        tuple(value["observed_columns"]),
        tuple(value["fit_target_ids"]),
        value["split_sha256"],
    )


def load_release(directory: str | Path, *, policy: ExecutionPolicy, device: str = "cpu"):
    policy.require_model_execution("Ember model loading")
    from .models import EnsembleRanker, ResidueLinearProbe, ResidueMLP, SiteRanker
    from .train import load_checkpoint

    root = Path(directory).resolve()
    release = read_json(root / "release.json")
    allowed = {
        "schema_version",
        "method_id",
        "kind",
        "checkpoint_file",
        "checkpoint_sha256",
        "width",
        "ensemble_width",
        "dropout",
        "base_kind",
        "static_normalizer",
        "ensemble_normalizer",
        "feature_policy_sha256",
        "split_sha256",
        "training_groups",
        "selection_groups",
        "code_sha256",
        "proposal_source",
        "residue_encoder",
        "status",
        "test_benchmark_evaluated",
        "fit_signature",
        "ensemble_variant",
    }
    if (
        set(release) != allowed
        or release["schema_version"] != "1"
        or release["status"] != "trained_development_selected"
    ):
        raise ValueError("Unsupported or untrained model release")
    if Path(release["checkpoint_file"]).name != release["checkpoint_file"]:
        raise ValueError("Release checkpoint must be a local alias name")
    path = root / release["checkpoint_file"]
    if file_hash(path) != release["checkpoint_sha256"]:
        raise ValueError("Release checkpoint path/checksum mismatch")
    checkpoint = load_checkpoint(path, policy=policy)
    validate_release_checkpoint(release, checkpoint)
    kind, width, dropout = release["kind"], release["width"], release["dropout"]
    if kind == "residue_mlp":
        model = ResidueMLP(width, dropout)
    elif kind == "residue_linear":
        model = ResidueLinearProbe(width)
    elif kind in {"site_linear", "site_mlp"}:
        model = SiteRanker(width, nonlinear=kind.endswith("mlp"), dropout=dropout)
    elif kind in {"ensemble_linear", "ensemble_mlp"}:
        if release["base_kind"] not in {"site_linear", "site_mlp"}:
            raise ValueError("Invalid ensemble base architecture")
        static = SiteRanker(width, nonlinear=release["base_kind"].endswith("mlp"), dropout=dropout)
        model = EnsembleRanker(
            static, release["ensemble_width"], nonlinear=kind.endswith("mlp"), dropout=dropout
        )
    else:
        raise ValueError("Unknown release architecture")
    model.load_state_dict(checkpoint["model"], strict=True)
    return model.eval().to(device), release


def residue_predictions(
    embeddings: np.ndarray,
    target: Target,
    *,
    embedding_key: EmbeddingKey,
    release_directory: str | Path,
    policy: ExecutionPolicy,
    device: str = "cpu",
) -> tuple[np.ndarray, dict]:
    policy.require_model_execution("Residue head inference")
    import torch

    model, release = load_release(release_directory, policy=policy, device=device)
    if not release["kind"].startswith("residue"):
        raise ValueError("A residue model release is required")
    encoder = {key: value for key, value in asdict(embedding_key).items() if key != "sequence"}
    if embedding_key.sequence != target.sequence or encoder != release["residue_encoder"]:
        raise ValueError("Embedding sequence/encoder differs from this target and trained R0 release")
    group_id, partition = target.group_id, target.partition
    role = "out_of_fold" if partition == "train" else "full_train_inference"
    if group_id in release["training_groups"]:
        raise ValueError("Use held-out cross-fitted R0 weights for downstream training features")
    if group_id in release["selection_groups"] and (
        role == "out_of_fold" or partition in {"test", "external"}
    ):
        raise ValueError("Held-out R0 prediction group was used for model selection")
    values = np.asarray(embeddings)
    if (
        values.ndim != 2
        or len(values) != len(target.sequence)
        or values.shape[1] != release["width"]
        or values.dtype != np.float32
        or not np.isfinite(values).all()
    ):
        raise ValueError("Invalid residue embeddings")
    with torch.inference_mode():
        logits = model(torch.as_tensor(values, device=device)).float().cpu().numpy()
    return logits, {
        "checkpoint_sha256": release["checkpoint_sha256"],
        "trained_group_ids": release["training_groups"],
        "selection_group_ids": release["selection_groups"],
        "prediction_target_id": target.target_id,
        "role": role,
    }


def predict_prepared(
    bundle: PreparedTarget,
    *,
    release_directory: str | Path,
    policy: ExecutionPolicy,
    device: str = "cpu",
    top_k: int = 3,
    runtime_seconds: float | None = None,
    cost_usd: float | None = None,
) -> Prediction:
    """Return three by default; explicitly request five for research recall@5.

    The API accepts input caches and checkpoints. OS-level isolation requires a
    worker with reference storage unmounted.
    """
    policy.require_model_execution("Site ranking inference")
    if type(top_k) is not int or top_k < 1:
        raise ValueError("Prediction top_k must be a positive integer")
    import torch

    model, release = load_release(release_directory, policy=policy, device=device)
    if release["kind"].startswith("residue"):
        raise ValueError("Site-ranking inference requires an S0/E0 release")
    if bundle.feature_policy_sha256 != release["feature_policy_sha256"]:
        raise ValueError("Feature policy differs from trained release")
    if bundle.target.group_id in release["training_groups"]:
        raise ValueError("Held-out prediction refuses a training-related group")
    if (
        bundle.target.partition in {"test", "external"}
        and bundle.target.group_id in release["selection_groups"]
    ):
        raise ValueError("Test/external group was used for model selection")
    static_norm = normalizer_from_dict(release["static_normalizer"])
    static = static_norm.transform(bundle.static, names=STATIC_NAMES)
    use_ensemble = release["kind"].startswith("ensemble")
    if not bundle.target.eligible:
        return Prediction(
            bundle.target.target_id,
            release["method_id"],
            "unsupported",
            (),
            content_hash(bundle.target),
            content_hash(release),
            failure_reason=bundle.target.exclusion_reason,
        )
    if not bundle.sites:
        return Prediction(
            bundle.target.target_id,
            release["method_id"],
            "no_candidates",
            (),
            content_hash(bundle.target),
            content_hash(release),
            bundle.requested_frames,
            len(bundle.valid_frame_ids),
            runtime_seconds,
            cost_usd,
        )
    with torch.inference_mode():
        x = torch.as_tensor(static, device=device)
        if use_ensemble:
            norm = normalizer_from_dict(release["ensemble_normalizer"])
            e = torch.as_tensor(
                ensemble_ablation(
                    norm.transform(bundle.ensemble, names=ENSEMBLE_NAMES), release["ensemble_variant"]
                ),
                device=device,
            )
            scores = model(x, e, bool(bundle.valid_frame_ids))
        else:
            scores = model(x)
        scores = scores.float().cpu().tolist()
    fallback = use_ensemble and not bundle.valid_frame_ids
    warnings = []
    if not use_ensemble and bundle.proposal_source == "apo_and_ensemble":
        warnings.append(
            "Static scorer on ensemble proposals: ranking-only diagnostic, not apo-only end-to-end."
        )
    ranked = []
    for site, score in zip(bundle.sites, scores):
        rep = representative(site, ensemble_available=bool(bundle.valid_frame_ids))
        evidence = (
            "static_fallback"
            if fallback
            else "ensemble"
            if rep.source == "ensemble"
            else "sequence"
            if rep.source == "surface"
            else "apo"
        )
        ranked.append(
            RankedSite(site.site_id, site.residues, score, evidence, rep.observation_id, rep.structure_path)
        )
    selected = ranked_unique(ranked, top_k=top_k, dedup_jaccard=0.5)
    return Prediction(
        bundle.target.target_id,
        release["method_id"],
        "static_fallback" if fallback else "ok",
        tuple(selected),
        content_hash(bundle.target),
        content_hash(release),
        bundle.requested_frames,
        len(bundle.valid_frame_ids),
        runtime_seconds,
        cost_usd,
        "No accepted ensemble frames; frozen S0 used" if fallback else None,
        tuple(warnings),
    )


def fpocket_baseline_prediction(
    bundle: PreparedTarget, *, method_id: str, method_sha256: str, top_k: int = 5, apo_only: bool = True
) -> Prediction:
    """Score existing detector output; this function never runs fpocket or a model."""
    if apo_only and bundle.proposal_source != "apo_only":
        raise ValueError("Native apo baseline requires its own apo-only grouping/candidate cap")
    ranked = []
    for site in bundle.sites:
        observations = (
            [o for o in site.observations if o.source == "apo"] if apo_only else list(site.observations)
        )
        if not observations:
            continue
        observation = min(observations, key=lambda o: (-o.detector_score, o.observation_id))
        # An apo-native baseline must use apo pocket membership, not an ensemble
        # medoid that could secretly improve its candidate geometry.
        residues = observation.residues if apo_only else site.residues
        ranked.append(
            RankedSite(
                site.site_id,
                residues,
                observation.detector_score,
                "apo" if observation.source == "apo" else "ensemble",
                observation.observation_id,
                observation.structure_path,
            )
        )
    selected = ranked_unique(ranked, top_k=top_k)
    return Prediction(
        bundle.target.target_id,
        method_id,
        "ok" if selected else "no_candidates",
        tuple(selected),
        content_hash(bundle.target),
        method_sha256,
        0 if apo_only else bundle.requested_frames,
        0 if apo_only else len(bundle.valid_frame_ids),
        warnings=("Existing cached detector scores only; runtime/cost not supplied.",),
    )


def sequence_mean_baseline_prediction(
    bundle: PreparedTarget, *, method_sha256: str, top_k: int = 5
) -> Prediction:
    """Mean cached R0 logit: a cheap control for whether ranker geometry adds value.

    This only reads an existing feature bundle. The R0 feature-generation cost
    still belongs in an end-to-end cost comparison; it is not zero-cost inference.
    """
    ranked = []
    for site, row in zip(bundle.sites, bundle.static):
        rep = representative(site, ensemble_available=bool(bundle.valid_frame_ids))
        evidence = (
            "ensemble" if rep.source == "ensemble" else "sequence" if rep.source == "surface" else "apo"
        )
        ranked.append(
            RankedSite(
                site.site_id,
                site.residues,
                float(row[STATIC_NAMES.index("residue_logit_mean")]),
                evidence,
                rep.observation_id,
                rep.structure_path,
            )
        )
    selected = tuple(ranked_unique(ranked, top_k=top_k))
    return Prediction(
        bundle.target.target_id,
        "r0-mean-logit-" + bundle.proposal_source,
        "ok" if selected else "no_candidates",
        selected,
        content_hash(bundle.target),
        method_sha256,
        bundle.requested_frames,
        len(bundle.valid_frame_ids),
        warnings=(
            "Ranks existing candidates by mean cached R0 logits; feature-generation cost remains unreported.",
        ),
    )
