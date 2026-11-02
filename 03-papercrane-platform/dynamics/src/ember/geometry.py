"""Angstrom-based geometry; coordinate masks remain explicit throughout."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .mapping import ChainMapping


@dataclass(frozen=True)
class RigidTransform:
    rotation: np.ndarray
    translation: np.ndarray
    rmsd: float
    n_atoms: int

    def apply(self, coordinates: np.ndarray) -> np.ndarray:
        return np.asarray(coordinates, dtype=float) @ self.rotation + self.translation

    def as_dict(self) -> dict:
        return {
            "rotation": self.rotation.tolist(),
            "translation": self.translation.tolist(),
            "rmsd_angstrom": self.rmsd,
            "n_atoms": self.n_atoms,
            "convention": "row_coordinates @ rotation + translation",
            "units": "angstrom",
        }


def align_coordinates(moving: np.ndarray, reference: np.ndarray) -> RigidTransform:
    moving, reference = np.asarray(moving, dtype=float), np.asarray(reference, dtype=float)
    if moving.shape != reference.shape or moving.ndim != 2 or moving.shape[1] != 3 or len(moving) < 3:
        raise ValueError("Alignment needs equal [N,3] arrays and at least three mapped atoms")
    if not np.isfinite(moving).all() or not np.isfinite(reference).all():
        raise ValueError("Alignment coordinates must be finite")
    x, y = moving - moving.mean(0), reference - reference.mean(0)
    if np.linalg.matrix_rank(x) < 2 or np.linalg.matrix_rank(y) < 2:
        raise ValueError("Alignment atoms must not be collinear")
    u, _, vt = np.linalg.svd(x.T @ y)
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ correction @ vt
    translation = reference.mean(0) - moving.mean(0) @ rotation
    residual = moving @ rotation + translation - reference
    rmsd = float(np.sqrt(np.mean(np.sum(residual * residual, axis=1))))
    return RigidTransform(rotation, translation, rmsd, len(moving))


def atom_coordinates(mapping: ChainMapping, atom_name: str = "CA") -> tuple[np.ndarray, np.ndarray]:
    coords = np.zeros((len(mapping.sequence), 3), dtype=float)
    mask = np.zeros(len(mapping.sequence), dtype=bool)
    for residue in mapping.residues:
        atoms = [a for a in residue.atoms if a.name == atom_name]
        if atoms:
            coords[residue.canonical_index] = atoms[0].coord
            mask[residue.canonical_index] = True
    return coords, mask


def align_mappings(
    moving: ChainMapping, reference: ChainMapping, site_indices: tuple[int, ...] | None = None
) -> RigidTransform:
    if moving.sequence != reference.sequence:
        raise ValueError("Alignment requires mappings into the same canonical sequence")
    a, amask = atom_coordinates(moving)
    b, bmask = atom_coordinates(reference)
    mask = amask & bmask
    if site_indices is not None:
        if not site_indices or min(site_indices) < 0 or max(site_indices) >= len(mask):
            raise ValueError("Local alignment site indices out of range")
        selected = np.zeros(len(mask), dtype=bool)
        selected[list(site_indices)] = True
        mask &= selected
    return align_coordinates(a[mask], b[mask])


@dataclass(frozen=True)
class QualityConfig:
    ca_min_distance: float = 2.8
    ca_max_distance: float = 4.5
    nonlocal_ca_clash_distance: float = 2.5
    minimum_ca_fraction: float = 0.8

    def __post_init__(self) -> None:
        values = (
            self.ca_min_distance,
            self.ca_max_distance,
            self.nonlocal_ca_clash_distance,
            self.minimum_ca_fraction,
        )
        if not all(np.isfinite(v) for v in values):
            raise ValueError("Quality thresholds must be finite")
        if not 0 < self.ca_min_distance < self.ca_max_distance:
            raise ValueError("Invalid CA continuity thresholds")
        if self.nonlocal_ca_clash_distance <= 0 or not 0 < self.minimum_ca_fraction <= 1:
            raise ValueError("Invalid clash/missingness threshold")


def check_ca_quality(mapping: ChainMapping, config: QualityConfig = QualityConfig()) -> dict:
    """Cheap necessary checks, NOT all-atom validity or a thermodynamic guarantee.

    Defaults are provisional engineering thresholds to freeze on development data.
    Gaps in the canonical sequence are not falsely treated as peptide bonds.
    """
    coords, mask = atom_coordinates(mapping)
    observed = np.flatnonzero(mask)
    fraction = float(mask.mean())
    breaks = []
    for i in range(len(mask) - 1):
        if mask[i] and mask[i + 1]:
            distance = float(np.linalg.norm(coords[i + 1] - coords[i]))
            if not config.ca_min_distance <= distance <= config.ca_max_distance:
                breaks.append({"indices": [i, i + 1], "distance_angstrom": distance})
    observed_xyz = coords[observed]
    distances = np.linalg.norm(observed_xyz[:, None, :] - observed_xyz[None, :, :], axis=-1)
    eligible = observed[None, :] - observed[:, None] > 2
    clashes = [
        {"indices": [int(observed[i]), int(observed[j])], "distance_angstrom": float(distances[i, j])}
        for i, j in np.argwhere(eligible & (distances < config.nonlocal_ca_clash_distance))
    ]
    return {
        "accepted": fraction >= config.minimum_ca_fraction and not breaks and not clashes,
        "ca_fraction": fraction,
        "continuity_violations": breaks,
        "nonlocal_ca_clashes": clashes,
        "all_atom_validated": False,
        "thresholds_provisional": True,
    }


def contact_change(
    apo: np.ndarray,
    frame: np.ndarray,
    apo_mask: np.ndarray,
    frame_mask: np.ndarray,
    site_indices: tuple[int, ...],
    cutoff: float = 8.0,
) -> float | None:
    """Fraction of site-to-protein nonlocal CA contacts that change (invariant)."""
    changed, eligible = contact_comparison(apo, frame, apo_mask, frame_mask, cutoff=cutoff)
    return site_contact_change(changed, eligible, site_indices)


def contact_comparison(
    apo: np.ndarray, frame: np.ndarray, apo_mask: np.ndarray, frame_mask: np.ndarray, *, cutoff: float = 8.0
) -> tuple[np.ndarray, np.ndarray]:
    """Compute once per frame, then reuse for every site (avoids Python pair loops)."""
    apo, frame = np.asarray(apo), np.asarray(frame)
    amask, fmask = np.asarray(apo_mask), np.asarray(frame_mask)
    if apo.shape != frame.shape or apo.ndim != 2 or apo.shape[1] != 3:
        raise ValueError("Contact coordinates must have matching [L,3] shapes")
    if amask.shape != (len(apo),) or fmask.shape != amask.shape or amask.dtype != bool or fmask.dtype != bool:
        raise ValueError("Contact masks must be boolean [L]")
    if cutoff <= 0 or not np.isfinite(cutoff):
        raise ValueError("Contact cutoff must be positive and finite")
    valid = amask & fmask
    if not np.isfinite(apo[valid]).all() or not np.isfinite(frame[valid]).all():
        raise ValueError("Observed contact coordinates must be finite")
    indices = np.arange(len(apo))
    eligible = valid[:, None] & valid[None, :] & (np.abs(indices[:, None] - indices[None, :]) > 2)
    eligible &= indices[:, None] < indices[None, :]
    a = np.linalg.norm(apo[:, None, :] - apo[None, :, :], axis=-1) < cutoff
    b = np.linalg.norm(frame[:, None, :] - frame[None, :, :], axis=-1) < cutoff
    return (a != b) & eligible, eligible


def site_contact_change(
    changed: np.ndarray, eligible: np.ndarray, site_indices: tuple[int, ...]
) -> float | None:
    if changed.ndim != 2 or changed.shape[0] != changed.shape[1] or changed.shape != eligible.shape:
        raise ValueError("Contact comparison arrays must be matching squares")
    if not site_indices or min(site_indices) < 0 or max(site_indices) >= len(changed):
        raise ValueError("Site indices outside contact arrays")
    membership = np.zeros(len(changed), dtype=bool)
    membership[list(site_indices)] = True
    relevant = eligible & (membership[:, None] | membership[None, :])
    count = int(relevant.sum())
    if not count:
        return None
    return float((changed & relevant).sum() / count)
