"""Bind inference preprocessing and group provenance to the fitted checkpoint."""

from __future__ import annotations

from .io import content_hash

BOUND_FIELDS = (
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
)


def release_binding(metadata: dict) -> str:
    return content_hash({name: metadata[name] for name in BOUND_FIELDS})


def validate_release_checkpoint(release: dict, checkpoint: dict) -> None:
    """Pure contract check; no tensor framework import or model execution."""
    signature, config = checkpoint["signature"], checkpoint["config"]
    if signature != release["fit_signature"]:
        raise ValueError("Release and training checkpoint provenance differ")
    if signature.get("release_binding_sha256") != release_binding(release):
        raise ValueError("Release preprocessing or group provenance differs from checkpoint")
    if (
        config["kind"] != release["kind"]
        or checkpoint["width"] != release["width"]
        or checkpoint["ensemble_width"] != release["ensemble_width"]
        or config["dropout"] != release["dropout"]
        or config["ensemble_variant"] != release["ensemble_variant"]
        or signature["config"] != content_hash(config)
        or signature["split_sha256"] != release["split_sha256"]
        or signature["code_sha256"] != release["code_sha256"]
    ):
        raise ValueError("Release architecture differs from checkpoint")
