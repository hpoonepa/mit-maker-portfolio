"""Prepare one target from already cached evidence, without executing models."""

from __future__ import annotations

import numpy as np

from .candidates import GroupingConfig, cap_candidates, group_observations
from .features import ENSEMBLE_NAMES, STATIC_NAMES, ensemble_features, static_features
from .geometry import atom_coordinates, contact_comparison, site_contact_change
from .io import content_hash
from .mapping import ChainMapping
from .prepared import PreparedTarget
from .schema import Observation, Target


def prepare_target(
    target: Target,
    apo_mapping: ChainMapping,
    residue_logits: np.ndarray,
    observations: list[Observation],
    *,
    valid_frame_ids: tuple[str, ...],
    requested_frames: int,
    r0_lineage: dict,
    feature_policy_sha256: str,
    grouping: GroupingConfig = GroupingConfig(),
    frame_mappings: dict[str, ChainMapping] | None = None,
    proposal_source: str = "apo_and_ensemble",
    coordinates_aligned_to_apo_sha256: str | None = None,
) -> tuple[PreparedTarget, dict]:
    if not target.eligible:
        raise ValueError("Do not prepare an ineligible target")
    if (
        target.sequence != apo_mapping.sequence
        or target.chain_id != apo_mapping.chain_id
        or target.model_id != apo_mapping.model_index
    ):
        raise ValueError("Apo mapping and target disagree")
    if (
        grouping.maximum_center_distance is not None
        and coordinates_aligned_to_apo_sha256 != target.apo_sha256
    ):
        raise ValueError("Spatial grouping requires explicit alignment to this apo coordinate frame")
    if len(set(valid_frame_ids)) != len(valid_frame_ids) or not 0 <= len(valid_frame_ids) <= requested_frames:
        raise ValueError("Invalid accepted-frame accounting")
    for observation in observations:
        if max(observation.residues) >= len(target.sequence):
            raise ValueError("Observation outside canonical sequence")
        if observation.source == "ensemble" and observation.frame_id not in valid_frame_ids:
            raise ValueError("Observation from unaccepted frame")
    groups = group_observations(observations, grouping)
    sites, dropped = cap_candidates(groups, grouping.candidate_cap)
    apo, apo_mask = atom_coordinates(apo_mapping)
    frames = {}
    for key, mapping in (frame_mappings or {}).items():
        if key not in valid_frame_ids or mapping.sequence != target.sequence:
            raise ValueError("Invalid frame mapping identity")
        coords, mask = atom_coordinates(mapping)
        frames[key] = contact_comparison(apo, coords, apo_mask, mask)
    static, ensemble = [], []
    for site in sites:
        static.append(static_features(site, target.sequence, residue_logits, apo, apo_mask))
        changes = {
            key: site_contact_change(changed, eligible, site.residues)
            for key, (changed, eligible) in frames.items()
        }
        ensemble.append(ensemble_features(site, valid_frame_ids, contact_changes=changes))
    bundle = PreparedTarget(
        target,
        tuple(sites),
        np.asarray(static, dtype=np.float32).reshape(-1, len(STATIC_NAMES)),
        np.asarray(ensemble, dtype=np.float32).reshape(-1, len(ENSEMBLE_NAMES)),
        valid_frame_ids,
        requested_frames,
        feature_policy_sha256,
        r0_lineage,
        proposal_source,
    )
    audit = {
        "target_id": target.target_id,
        "target_sha256": content_hash(target),
        "n_observations": len(observations),
        "groups_before_cap": len(groups),
        "groups_after_cap": len(sites),
        "dropped_site_ids": dropped,
        "grouping": vars(grouping),
        "uncapped_sites": [{"site_id": site.site_id, "residues": list(site.residues)} for site in groups],
        "valid_frame_ids": list(valid_frame_ids),
        "proposal_source": proposal_source,
        "note": "No reference annotations read. Candidate coverage is evaluator-only.",
    }
    return bundle, audit
