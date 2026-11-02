"""Post-hoc scoring: RMSD_binder and ShapeComplementarity.

Both are used AFTER design in validators/boltz2_consensus.py to filter out
false positives that PAE-based metrics miss. Neither is JAX-differentiable.

RMSD_binder:
    Aligns the designed binder backbone to the Boltz2/Chai/Protenix predicted
    binder backbone and returns CA-RMSD in Angstroms. Catches the failure mode
    where a high-ipTM prediction silently re-poses the binder off its designed
    pose — a problem orthogonal to every confidence metric.
    Interpretation: < 2.0 A = ideal, 2-5 A = borderline, > 5 A = predictor disagrees.

Shape Complementarity (Lawrence & Colman 1993):
    Standard interface SC via PyRosetta. Good binders typically SC > 0.65.
    Raises ImportError with install guidance if PyRosetta is absent.
"""

from typing import Dict, Optional

import numpy as np


__all__ = ["rmsd_binder", "shape_complementarity"]


def _extract_ca_coords(pdb_path: str, chain_id: str) -> np.ndarray:
    """Walk a PDB file with Biopython, return (N, 3) array of CA coords for chain_id."""
    from Bio.PDB import PDBParser

    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("x", pdb_path)
    coords = []
    for model in structure:
        chain = model[chain_id]
        for residue in chain:
            # Skip hetero-atoms and missing CAs
            if residue.id[0].strip():
                continue
            if "CA" not in residue:
                continue
            coords.append(residue["CA"].coord)
        break  # only first model
    if not coords:
        raise ValueError(f"No CA atoms found for chain {chain_id} in {pdb_path}")
    return np.asarray(coords, dtype=np.float64)


def _kabsch_rmsd(p: np.ndarray, q: np.ndarray) -> float:
    """CA-RMSD between two (N, 3) coord arrays after Kabsch alignment."""
    if p.shape != q.shape:
        raise ValueError(f"Shape mismatch: {p.shape} vs {q.shape}")
    p_c = p - p.mean(axis=0)
    q_c = q - q.mean(axis=0)
    h = p_c.T @ q_c
    u, _, vt = np.linalg.svd(h)
    # Correct for reflection if needed (ensure proper rotation, det = +1)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    s = np.diag([1.0, 1.0, d])
    r = vt.T @ s @ u.T
    p_aligned = p_c @ r.T
    diff = p_aligned - q_c
    return float(np.sqrt(np.mean(np.sum(diff * diff, axis=1))))


def rmsd_binder(
    designed_pdb: str,
    predicted_pdb: str,
    binder_chain: str = "A",
) -> float:
    """CA-RMSD between designed and predicted binder backbones (Kabsch-aligned).

    Args:
        designed_pdb: path to design output PDB (Protenix output from design_v5)
        predicted_pdb: path to validator prediction PDB (Boltz2/Chai-1)
        binder_chain: chain id of the binder in both PDBs (default 'A')

    Returns: CA-RMSD in Angstroms. Higher = predictor re-posed the binder.
    """
    p = _extract_ca_coords(designed_pdb, binder_chain)
    q = _extract_ca_coords(predicted_pdb, binder_chain)
    if len(p) != len(q):
        raise ValueError(
            f"Binder CA count mismatch: designed={len(p)}, predicted={len(q)}. "
            "Confirm both PDBs share the same binder length and chain id."
        )
    return _kabsch_rmsd(p, q)


def shape_complementarity(
    pdb_path: str,
    binder_chain: str = "A",
    target_chain: str = "B",
) -> Dict[str, float]:
    """Interface shape complementarity via PyRosetta SC calculator.

    Returns:
        {"sc": float in [0, 1], higher better,
         "dSASA": float, buried surface area,
         "d_mean": float, mean interface separation}

    Raises ImportError with install guidance if PyRosetta missing.
    """
    try:
        import pyrosetta
        from pyrosetta.rosetta.core.scoring.sc import ShapeComplementarityCalculator
    except ImportError as e:
        raise ImportError(
            "PyRosetta is required for shape_complementarity. Install via:\n"
            "  uv add pyrosetta   (after accepting license at https://www.pyrosetta.org)\n"
            "  OR: conda install -c https://conda.rosettacommons.org pyrosetta"
        ) from e

    pyrosetta.init(extra_options="-mute all", silent=True)
    pose = pyrosetta.pose_from_pdb(pdb_path)

    pdb_info = pose.pdb_info()
    group0, group1 = [], []
    for i in range(1, pose.total_residue() + 1):
        ch = pdb_info.chain(i)
        if ch == binder_chain:
            group0.append(i)
        elif ch == target_chain:
            group1.append(i)

    if not group0 or not group1:
        raise ValueError(
            f"Empty chain group: binder={binder_chain} n={len(group0)}, "
            f"target={target_chain} n={len(group1)} — check chain ids"
        )

    sc_calc = ShapeComplementarityCalculator()
    sc_calc.Init()
    for r in group0:
        sc_calc.AddResidue(0, pose.residue(r))
    for r in group1:
        sc_calc.AddResidue(1, pose.residue(r))
    if not sc_calc.Calc():
        raise RuntimeError("ShapeComplementarityCalculator failed to compute")

    results = sc_calc.GetResults()
    return {
        "sc": float(results.sc),
        "dSASA": float(results.surface[0].d_mean),   # conservative proxy
        "d_mean": float(results.surface[0].d_mean),
    }
