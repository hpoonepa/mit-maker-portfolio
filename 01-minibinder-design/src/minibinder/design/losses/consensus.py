"""Chai-1 wrapper + multi-predictor consensus utilities.

Used by validators/boltz2_consensus.py to run a second structure predictor
(Chai-1) alongside Boltz2, average their PAE matrices, and decide pass/fail
based on how many predictors agree that the interface is confident.

Theory: Baker/Cao work shows multi-model consensus roughly halves the
false-positive rate vs single-predictor confidence. Gate: require >=N of
{Protenix, Boltz2, Chai-1} to exceed min_ipSAE threshold."""

from typing import Dict, List, Optional
import os
import tempfile

import numpy as np


__all__ = ["load_chai1", "predict_chai1", "consensus_pae", "consensus_gate"]


# Module-level singleton — Chai-1 model weights are ~1.5 GB, load once per process.
_CHAI1_MODEL = None


def load_chai1():
    """Load Chai-1 model (lazy singleton).

    Raises ImportError with install guidance if chai_lab missing.
    """
    global _CHAI1_MODEL
    if _CHAI1_MODEL is not None:
        return _CHAI1_MODEL

    try:
        # chai_lab exposes `run_inference` as the main entry point; no separate model handle
        # is strictly needed, but we cache the module import so repeated inference is fast.
        import chai_lab.chai1 as chai1_mod
    except ImportError as e:
        raise ImportError(
            "chai_lab is required for Chai-1 consensus validation. Install via:\n"
            "  uv add chai_lab torch\n"
            "See https://github.com/chaidiscovery/chai-lab for license terms."
        ) from e

    _CHAI1_MODEL = chai1_mod
    return _CHAI1_MODEL


def _build_chai_fasta(binder_sequence: str, target_sequence: str) -> str:
    """Build a 2-chain FASTA string for Chai-1."""
    return (
        f">binder|protein\n{binder_sequence}\n"
        f">target|protein\n{target_sequence}\n"
    )


def predict_chai1(
    sequence: str,
    target_cif: str,
    model=None,
    num_diffn_timesteps: int = 200,
) -> Dict:
    """Run Chai-1 on binder + target complex.

    Args:
        sequence: binder amino-acid sequence
        target_cif: path to target PDB/CIF (used to extract target sequence)
        model: optional pre-loaded chai_lab.chai1 module; else loaded via load_chai1
        num_diffn_timesteps: Chai-1 diffusion steps (default 200)

    Returns (matching the Protenix/Boltz2 contract used elsewhere in v5):
        {
            "pae":                    np.ndarray (N, N),
            "plddt":                  np.ndarray (N,),
            "iptm":                   float,
            "structure_coordinates":  np.ndarray (N, 3),  # CA coords
            "chain_ids":              np.ndarray (N,),
            "binder_length":          int,
        }
    """
    chai = model or load_chai1()

    import gemmi

    target_st = gemmi.read_structure(target_cif)
    target_st.setup_entities()
    target_st.remove_ligands_and_waters()
    target_seq = "".join(gemmi.one_letter_code([r.name for r in target_st[0][0]]))

    binder_length = len(sequence)

    with tempfile.TemporaryDirectory() as tmp:
        fasta_path = os.path.join(tmp, "complex.fasta")
        output_dir = os.path.join(tmp, "chai_out")
        os.makedirs(output_dir, exist_ok=True)
        with open(fasta_path, "w") as f:
            f.write(_build_chai_fasta(sequence, target_seq))

        # chai_lab.chai1.run_inference is the canonical entrypoint.
        # Argument names are stable across recent versions; adjust if chai_lab API changes.
        chai.run_inference(
            fasta_file=fasta_path,
            output_dir=output_dir,
            num_trunk_recycles=3,
            num_diffn_timesteps=num_diffn_timesteps,
            seed=42,
            device="cuda",
            use_esm_embeddings=True,
        )

        # Parse outputs — Chai writes scores to scores.model_idx_0.npz and structure
        # to pred.model_idx_0.cif (model_idx_0 = best-ranked).
        scores_path = os.path.join(output_dir, "scores.model_idx_0.npz")
        cif_path = os.path.join(output_dir, "pred.model_idx_0.cif")
        scores = np.load(scores_path, allow_pickle=True)

        pae = np.asarray(scores["pae"])             # (N, N)
        plddt = np.asarray(scores["plddt"])         # (N,)
        iptm = float(scores["iptm"])

        pred_st = gemmi.read_structure(cif_path)
        ca_coords = []
        chain_ids = []
        for chain_idx, chain in enumerate(pred_st[0]):
            for residue in chain:
                ca = residue.find_atom("CA", "*")
                if ca is None:
                    continue
                ca_coords.append([ca.pos.x, ca.pos.y, ca.pos.z])
                chain_ids.append(chain_idx)

        coords = np.asarray(ca_coords, dtype=np.float64)
        chains = np.asarray(chain_ids, dtype=np.int32)

    return {
        "pae": pae,
        "plddt": plddt,
        "iptm": iptm,
        "structure_coordinates": coords,
        "chain_ids": chains,
        "binder_length": binder_length,
    }


def consensus_pae(
    pae_list: List[np.ndarray],
    method: str = "mean",
) -> np.ndarray:
    """Aggregate PAE matrices across predictors.

    Args:
        pae_list: list of (N, N) PAE matrices, must share shape
        method: 'mean' (default), 'max' (conservative upper bound),
                'min' (optimistic lower bound)
    """
    if not pae_list:
        raise ValueError("pae_list is empty")
    stack = np.stack(pae_list, axis=0)
    if method == "mean":
        return stack.mean(axis=0)
    if method == "max":
        return stack.max(axis=0)
    if method == "min":
        return stack.min(axis=0)
    raise ValueError(f"Unknown consensus method: {method!r}")


def consensus_gate(
    scores: Dict[str, Dict[str, float]],
    ipsae_threshold: float = 0.8,
    min_predictors_passing: int = 2,
    metric_key: str = "min_ipsae",
) -> bool:
    """Pass/fail gate across multiple predictors.

    Args:
        scores: e.g. {"boltz2": {"min_ipsae": 0.82},
                      "chai1":  {"min_ipsae": 0.79},
                      "protenix":{"min_ipsae": 0.84}}
        ipsae_threshold: per-predictor cutoff
        min_predictors_passing: N out of len(scores) must pass
        metric_key: which metric to gate on (default 'min_ipsae')

    Returns: True if enough predictors pass.
    """
    passing = sum(
        1
        for per_pred in scores.values()
        if per_pred.get(metric_key, 0.0) > ipsae_threshold
    )
    return passing >= min_predictors_passing
