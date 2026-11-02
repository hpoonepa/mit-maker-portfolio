"""Explicit structural screening, separate from sampling and ranking.

These cheap checks screen for gross defects. Force-field energy, stereochemistry,
docking readiness and equilibrium sampling require separate assessment. Defaults
are draft engineering thresholds; freeze on development systems before a scientific run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .geometry import QualityConfig, check_ca_quality
from .mapping import ChainMapping

HEAVY_ATOMS = {
    "A": "N CA C O CB",
    "C": "N CA C O CB SG",
    "D": "N CA C O CB CG OD1 OD2",
    "E": "N CA C O CB CG CD OE1 OE2",
    "F": "N CA C O CB CG CD1 CD2 CE1 CE2 CZ",
    "G": "N CA C O",
    "H": "N CA C O CB CG ND1 CD2 CE1 NE2",
    "I": "N CA C O CB CG1 CG2 CD1",
    "K": "N CA C O CB CG CD CE NZ",
    "L": "N CA C O CB CG CD1 CD2",
    "M": "N CA C O CB CG SD CE",
    "N": "N CA C O CB CG OD1 ND2",
    "P": "N CA C O CB CG CD",
    "Q": "N CA C O CB CG CD OE1 NE2",
    "R": "N CA C O CB CG CD NE CZ NH1 NH2",
    "S": "N CA C O CB OG",
    "T": "N CA C O CB OG1 CG2",
    "V": "N CA C O CB CG1 CG2",
    "W": "N CA C O CB CG CD1 CD2 NE1 CE2 CE3 CZ2 CZ3 CH2",
    "Y": "N CA C O CB CG CD1 CD2 CE1 CE2 CZ OH",
}


@dataclass(frozen=True)
class AllAtomQualityConfig:
    gross_nonlocal_clash_distance: float = 1.0
    maximum_gross_clashes: int = 0
    require_complete_sidechains: bool = True

    def __post_init__(self):
        if not np.isfinite(self.gross_nonlocal_clash_distance) or self.gross_nonlocal_clash_distance <= 0:
            raise ValueError("Invalid gross-clash threshold")
        if type(self.maximum_gross_clashes) is not int or self.maximum_gross_clashes < 0:
            raise ValueError("Maximum clashes must be a nonnegative integer")


def screen_structure(
    mapping: ChainMapping,
    *,
    ca_config: QualityConfig | None = None,
    atom_config: AllAtomQualityConfig | None = None,
) -> dict:
    ca_config = ca_config or QualityConfig()
    atom_config = atom_config or AllAtomQualityConfig()
    ca_report = check_ca_quality(mapping, ca_config)
    incomplete = []
    residues, names, coords = [], [], []
    for residue in mapping.residues:
        expected = set(HEAVY_ATOMS[residue.amino_acid].split())
        present = {atom.name for atom in residue.atoms if atom.element not in {"H", "D"}}
        missing = sorted(expected - present)
        if missing:
            incomplete.append({"canonical_index": residue.canonical_index, "missing_atoms": missing})
        for atom in residue.atoms:
            if atom.element not in {"H", "D"}:
                residues.append(residue.canonical_index)
                names.append(atom.name)
                coords.append(atom.coord)
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    indices = np.asarray(residues, dtype=int)
    clash_count = 0
    examples = []
    # Blocks bound memory; adjacent residues are excluded to avoid flagging
    # covalent bonds. This screen covers the selected nonadjacent atom pairs.
    for start in range(0, len(xyz), 128):
        stop = min(start + 128, len(xyz))
        distances = np.linalg.norm(xyz[start:stop, None, :] - xyz[None, :, :], axis=-1)
        eligible = np.abs(indices[start:stop, None] - indices[None, :]) > 1
        eligible &= np.arange(start, stop)[:, None] < np.arange(len(xyz))[None, :]
        pairs = np.argwhere(eligible & (distances < atom_config.gross_nonlocal_clash_distance))
        clash_count += len(pairs)
        for left, right in pairs[: max(0, 20 - len(examples))]:
            i, j = start + int(left), int(right)
            examples.append(
                {
                    "left_index": int(indices[i]),
                    "left_atom": names[i],
                    "right_index": int(indices[j]),
                    "right_atom": names[j],
                    "distance_angstrom": float(distances[left, right]),
                }
            )
    accepted = ca_report["accepted"] and clash_count <= atom_config.maximum_gross_clashes
    if atom_config.require_complete_sidechains:
        accepted = accepted and not incomplete
    return {
        "accepted": bool(accepted),
        "ca": ca_report,
        "incomplete_residues": incomplete,
        "gross_nonlocal_clash_count": clash_count,
        "clash_examples": examples,
        "ca_config": asdict(ca_config),
        "atom_config": asdict(atom_config),
        "thresholds_frozen": False,
        "scope": "Gross geometry screen only; energy, chirality and detailed bond geometry unvalidated.",
    }
