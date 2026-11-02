"""Reference-free, checksummed site feature bundles shared by training and inference."""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .features import ENSEMBLE_NAMES, FEATURE_SCHEMA, STATIC_NAMES
from .io import atomic_write_json, content_hash, file_hash, read_json
from .schema import Site, Target, from_dict, require_hash, unique_ids


@dataclass(frozen=True)
class PreparedTarget:
    target: Target
    sites: tuple[Site, ...]
    static: np.ndarray
    ensemble: np.ndarray
    valid_frame_ids: tuple[str, ...]
    requested_frames: int
    feature_policy_sha256: str
    r0_lineage: dict
    proposal_source: str

    def __post_init__(self) -> None:
        unique_ids(self.sites, "site_id")
        for array, names in ((self.static, STATIC_NAMES), (self.ensemble, ENSEMBLE_NAMES)):
            if (
                array.shape != (len(self.sites), len(names))
                or array.dtype != np.float32
                or np.isinf(array).any()
            ):
                raise ValueError(
                    "Prepared features require float32 [sites,features], with NaN only for missingness"
                )
        if (
            type(self.requested_frames) is not int
            or not 0 <= len(self.valid_frame_ids) <= self.requested_frames
        ):
            raise ValueError("Prepared frame accounting invalid")
        if len(set(self.valid_frame_ids)) != len(self.valid_frame_ids):
            raise ValueError("Duplicate prepared frame IDs")
        if self.proposal_source not in {"apo_only", "apo_and_ensemble", "sequence_surface"}:
            raise ValueError("Unknown proposal source")
        if self.proposal_source == "apo_only" and any(
            o.source == "ensemble" for s in self.sites for o in s.observations
        ):
            raise ValueError("Apo-only proposals cannot contain ensemble observations")
        for site in self.sites:
            if max(site.residues) >= len(self.target.sequence):
                raise ValueError("Prepared site outside sequence")
            if any(
                o.source == "ensemble" and o.frame_id not in self.valid_frame_ids for o in site.observations
            ):
                raise ValueError("Unaccepted frame in prepared site")
        require_hash(self.feature_policy_sha256, "feature_policy_sha256")
        allowed = {
            "checkpoint_sha256",
            "trained_group_ids",
            "selection_group_ids",
            "prediction_target_id",
            "role",
        }
        if set(self.r0_lineage) != allowed:
            raise ValueError("Unexpected or missing R0 lineage fields")
        require_hash(self.r0_lineage["checkpoint_sha256"], "R0 checkpoint_sha256")
        if self.r0_lineage["prediction_target_id"] != self.target.target_id:
            raise ValueError("R0 lineage target mismatch")


def write_prepared(directory: str | Path, bundle: PreparedTarget) -> dict:
    """One immutable directory per target/version; manifest is completion marker."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    arrays = root / "features.npz"
    fd, temporary = tempfile.mkstemp(prefix=".features-", dir=root)
    try:
        with os.fdopen(fd, "wb") as handle:
            np.savez(handle, static=bundle.static, ensemble=bundle.ensemble)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, arrays)
    finally:
        Path(temporary).unlink(missing_ok=True)
    manifest = {
        "schema": FEATURE_SCHEMA,
        "target": asdict(bundle.target),
        "target_sha256": content_hash(bundle.target),
        "sites": [asdict(site) for site in bundle.sites],
        "arrays_file": "features.npz",
        "arrays_sha256": file_hash(arrays),
        "static_names": list(STATIC_NAMES),
        "ensemble_names": list(ENSEMBLE_NAMES),
        "valid_frame_ids": list(bundle.valid_frame_ids),
        "requested_frames": bundle.requested_frames,
        "feature_policy_sha256": bundle.feature_policy_sha256,
        "r0_lineage": bundle.r0_lineage,
        "proposal_source": bundle.proposal_source,
        "complete": True,
    }
    atomic_write_json(root / "manifest.json", manifest)
    return manifest


def read_prepared(directory: str | Path) -> PreparedTarget:
    root = Path(directory).resolve()
    manifest = read_json(root / "manifest.json")
    allowed = {
        "schema",
        "target",
        "target_sha256",
        "sites",
        "arrays_file",
        "arrays_sha256",
        "static_names",
        "ensemble_names",
        "valid_frame_ids",
        "requested_frames",
        "feature_policy_sha256",
        "r0_lineage",
        "proposal_source",
        "complete",
    }
    if set(manifest) != allowed or manifest["schema"] != FEATURE_SCHEMA or manifest["complete"] is not True:
        raise ValueError("Unsupported/incomplete prepared manifest")
    if tuple(manifest["static_names"]) != STATIC_NAMES or tuple(manifest["ensemble_names"]) != ENSEMBLE_NAMES:
        raise ValueError("Prepared feature schema/order changed")
    path = (root / manifest["arrays_file"]).resolve()
    if path.parent != root or path.name != "features.npz":
        raise ValueError("Prepared array path must stay within its bundle")
    if file_hash(path) != manifest["arrays_sha256"]:
        raise ValueError("Prepared feature checksum mismatch")
    target = from_dict(Target, manifest["target"])
    if content_hash(target) != manifest["target_sha256"]:
        raise ValueError("Prepared input checksum mismatch")
    with np.load(path, allow_pickle=False) as arrays:
        if set(arrays.files) != {"static", "ensemble"}:
            raise ValueError("Unexpected prepared arrays (labels are forbidden here)")
        static, ensemble = arrays["static"], arrays["ensemble"]
    return PreparedTarget(
        target,
        tuple(from_dict(Site, site) for site in manifest["sites"]),
        static,
        ensemble,
        tuple(manifest["valid_frame_ids"]),
        manifest["requested_frames"],
        manifest["feature_policy_sha256"],
        manifest["r0_lineage"],
        manifest["proposal_source"],
    )
