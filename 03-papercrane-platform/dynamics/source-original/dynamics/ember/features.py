"""Small reference-free feature vectors; train-only masked normalization.

Static features use apo geometry and sequence scores. Ensemble features summarize
unique valid-frame observations. Missing values remain NaN until imputation; every
imputed scalar gets an explicit missingness indicator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .candidates import best_per_frame, jaccard
from .schema import Site

STATIC_NAMES = (
    "residue_logit_mean",
    "residue_logit_max",
    "residue_logit_std",
    "log_site_size",
    "apo_ca_observed_fraction",
    "hydrophobic_fraction",
    "charged_fraction",
    "aromatic_fraction",
    "apo_site_radius_gyration",
    "apo_nonlocal_contacts_per_residue",
    "apo_detector_score",
    "apo_volume",
    "apo_druggability",
    "apo_sasa",
)
ENSEMBLE_NAMES = (
    "log_valid_frames",
    "support_fraction",
    "log_support_frames",
    "detector_score_mean",
    "detector_score_max",
    "detector_score_std",
    "volume_mean",
    "volume_max",
    "volume_std",
    "druggability_mean",
    "druggability_max",
    "druggability_std",
    "sasa_mean",
    "sasa_max",
    "sasa_std",
    "quality_mean",
    "quality_max",
    "quality_std",
    "residue_overlap_mean",
    "residue_overlap_min",
    "volume_change_from_apo",
    "sasa_change_from_apo",
    "contact_change_mean",
    "contact_change_max",
    "contact_change_std",
)
FEATURE_SCHEMA = "ember-site-v1"


def ensemble_ablation(normalized: np.ndarray, variant: str) -> np.ndarray:
    """Remove explicit frame/support counts, including their missingness flags.

    Other missing detector features can still reveal whether a site was observed;
    this is an explicit-count ablation, not perfect removal of every proxy.
    """
    if normalized.ndim != 2 or normalized.shape[1] != 2 * len(ENSEMBLE_NAMES):
        raise ValueError("Expected normalized ensemble values and masks")
    if variant == "all":
        return normalized
    if variant != "no_support_counts":
        raise ValueError("Unknown ensemble ablation")
    result = normalized.copy()
    indices = [
        ENSEMBLE_NAMES.index(name) for name in ("log_valid_frames", "support_fraction", "log_support_frames")
    ]
    result[:, indices + [i + len(ENSEMBLE_NAMES) for i in indices]] = 0.0
    return result


def _stats(values) -> tuple[float, float, float]:
    array = np.asarray([x for x in values if x is not None], dtype=float)
    if not len(array):
        return (float("nan"),) * 3
    if not np.isfinite(array).all():
        raise ValueError("Observed feature values must be finite")
    return float(array.mean()), float(array.max()), float(array.std())


def static_features(
    site: Site,
    sequence: str,
    residue_logits: np.ndarray,
    apo_ca: np.ndarray,
    apo_mask: np.ndarray,
    *,
    contact_cutoff: float = 8.0,
) -> np.ndarray:
    """A static scorer on ensemble proposals is a matched-pool diagnostic only."""
    logits = np.asarray(residue_logits, dtype=float)
    coords, mask = np.asarray(apo_ca, dtype=float), np.asarray(apo_mask)
    length = len(sequence)
    if (
        logits.shape != (length,)
        or coords.shape != (length, 3)
        or mask.shape != (length,)
        or mask.dtype != bool
    ):
        raise ValueError("Static features require logits[L], apo_ca[L,3], boolean mask[L]")
    if not np.isfinite(logits).all() or not np.isfinite(coords[mask]).all():
        raise ValueError("Observed static inputs must be finite")
    if contact_cutoff <= 0 or not np.isfinite(contact_cutoff):
        raise ValueError("Contact cutoff must be finite and positive")
    if max(site.residues) >= length:
        raise ValueError("Site outside canonical sequence")
    indices = np.asarray(site.residues)
    observed = indices[mask[indices]]
    letters = [sequence[i] for i in indices]
    size = len(indices)
    radius = contacts = float("nan")
    if len(observed):
        local = coords[observed]
        radius = float(np.sqrt(np.mean(np.sum((local - local.mean(0)) ** 2, axis=1))))
        other = np.flatnonzero(mask)
        distances = np.linalg.norm(local[:, None, :] - coords[other][None, :, :], axis=-1)
        nonlocal_pairs = np.abs(observed[:, None] - other[None, :]) > 2
        contacts = float(((distances < contact_cutoff) & nonlocal_pairs).sum() / len(observed))
    apo = best_per_frame(site, source="apo")
    if len(apo) > 1:
        raise ValueError("Only one declared apo reference frame is supported")
    detector = apo[0] if apo else None
    scores = logits[indices]
    values = [
        float(scores.mean()),
        float(scores.max()),
        float(scores.std()),
        float(np.log1p(size)),
        len(observed) / size,
        sum(x in "AVILMFWY" for x in letters) / size,
        sum(x in "DEKR" for x in letters) / size,
        sum(x in "FWY" for x in letters) / size,
        radius,
        contacts,
    ]
    for name in ("detector_score", "volume", "druggability", "sasa"):
        value = getattr(detector, name) if detector else None
        values.append(float(value) if value is not None else float("nan"))
    return np.asarray(values, dtype=np.float32)


def ensemble_features(
    site: Site, valid_frame_ids: tuple[str, ...], *, contact_changes: dict[str, float | None] | None = None
) -> np.ndarray:
    if len(valid_frame_ids) != len(set(valid_frame_ids)):
        raise ValueError("Duplicate valid frame IDs")
    obs = best_per_frame(site)
    if any(o.frame_id not in valid_frame_ids for o in obs):
        raise ValueError("Site contains an ensemble observation from an unaccepted frame")
    n, support = len(valid_frame_ids), len(obs)
    values = [float(np.log1p(n)), support / n if n else float("nan"), float(np.log1p(support))]
    for name in ("detector_score", "volume", "druggability", "sasa", "quality"):
        values.extend(_stats(getattr(o, name) for o in obs))
    overlaps = [jaccard(o.residues, site.residues) for o in obs]
    values.extend([float(np.mean(overlaps)), float(min(overlaps))] if overlaps else [float("nan")] * 2)
    apo = best_per_frame(site, source="apo")
    if len(apo) > 1:
        raise ValueError("Only one apo frame is supported")
    for name in ("volume", "sasa"):
        baseline = getattr(apo[0], name) if apo else None
        present = [getattr(o, name) for o in obs if getattr(o, name) is not None]
        values.append(
            float(np.mean(present) - baseline) if present and baseline is not None else float("nan")
        )
    if contact_changes is not None and set(contact_changes) - set(valid_frame_ids):
        raise ValueError("Contact features contain invalid frame IDs")
    # Contact changes may be available even in valid frames with no detector hit.
    # Pool over all provided valid frames, rather than conditioning on opening.
    values.extend(_stats((contact_changes or {}).values()))
    return np.asarray(values, dtype=np.float32)


@dataclass(frozen=True)
class FeatureNormalizer:
    names: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    varying_columns: tuple[bool, ...]
    observed_columns: tuple[bool, ...]
    fit_target_ids: tuple[str, ...]
    split_sha256: str

    @classmethod
    def fit(
        cls,
        matrices: list[np.ndarray],
        *,
        names: tuple[str, ...],
        target_ids: list[str],
        partitions: list[str],
        split_sha256: str,
    ) -> "FeatureNormalizer":
        from .schema import require_hash

        require_hash(split_sha256, "normalizer split_sha256")
        if not matrices or not (len(matrices) == len(target_ids) == len(partitions)):
            raise ValueError("Normalizer requires one matrix/ID/partition per training protein")
        if set(partitions) != {"train"} or len(set(target_ids)) != len(target_ids):
            raise ValueError("Normalizer fits unique training proteins only")
        if len(set(names)) != len(names) or not names:
            raise ValueError("Feature names must be unique and nonempty")
        arrays, weights = [], []
        for matrix in matrices:
            array = np.asarray(matrix, dtype=float)
            if array.ndim != 2 or array.shape[1] != len(names) or np.isinf(array).any():
                raise ValueError("Feature matrix has wrong shape or infinite values")
            if len(array):
                arrays.append(array)
                weights.extend([1.0 / len(array)] * len(array))
        if not arrays:
            raise ValueError("No training candidates to normalize")
        data = np.concatenate(arrays)
        weight = np.asarray(weights)[:, None] * ~np.isnan(data)
        denom = weight.sum(0)
        safe = np.nan_to_num(data)
        mean = np.divide((safe * weight).sum(0), denom, out=np.zeros(len(names)), where=denom > 0)
        variance = np.divide(
            ((safe - mean) ** 2 * weight).sum(0), denom, out=np.zeros(len(names)), where=denom > 0
        )
        scale = np.sqrt(variance)
        scale[scale < 1e-8] = 1.0
        return cls(
            names,
            tuple(mean.tolist()),
            tuple(scale.tolist()),
            tuple((variance >= 1e-16).tolist()),
            tuple((denom > 0).tolist()),
            tuple(target_ids),
            split_sha256,
        )

    def transform(self, matrix: np.ndarray, *, names: tuple[str, ...]) -> np.ndarray:
        if tuple(names) != self.names:
            raise ValueError("Feature ordering/schema differs from fitted normalizer")
        array = np.asarray(matrix, dtype=float)
        if array.ndim != 2 or array.shape[1] != len(self.names) or np.isinf(array).any():
            raise ValueError("Invalid feature matrix")
        mean, scale = np.asarray(self.mean), np.asarray(self.scale)
        varying, observed = np.asarray(self.varying_columns), np.asarray(self.observed_columns)
        if (
            mean.shape != (len(self.names),)
            or scale.shape != mean.shape
            or not np.isfinite(mean).all()
            or not np.isfinite(scale).all()
            or (scale <= 0).any()
        ):
            raise ValueError("Corrupt fitted normalizer")
        if (
            varying.shape != mean.shape
            or observed.shape != mean.shape
            or varying.dtype != bool
            or observed.dtype != bool
        ):
            raise ValueError("Corrupt fitted feature-availability mask")
        missing = np.isnan(array) | ~observed
        filled = np.where(missing, mean, array)
        standardized = (filled - mean) / scale
        # A constant/unobserved training column cannot learn a numerical effect.
        # Do not expose random untrained weights to newly varying test values.
        standardized[:, ~varying] = 0.0
        # No statistics from the application partition are estimated here.
        return np.concatenate([standardized, missing.astype(float)], axis=1).astype(np.float32)
