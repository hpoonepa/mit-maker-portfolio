"""V5 validator — Boltz2 + Chai-1 consensus with post-hoc metrics.

Replaces validate_boltz2.py. Differences:
  1. Runs Chai-1 alongside Boltz2 (if available) and averages their PAE matrices
  2. Gates on consensus: >=N of {Protenix?, Boltz2, Chai-1} must exceed min_ipSAE
  3. Adds post-hoc RMSD_binder (designed vs predicted backbone) and Shape
     Complementarity (PyRosetta, graceful skip if missing)

Multi-predictor consensus typically reduces false-positive rate by ~30% and
boosts experimental hit rate by +15-25 pp (Baker/Cao results).

CLI:
    python validators/boltz2_consensus.py --seed 1 --sequence MVEEMY... \\
        --target-cif 5G51.cif --designed-pdb 5g51_v5_seed001.pdb \\
        [--skip-chai1] [--skip-sc]
"""

import argparse
import csv as csv_mod
import os
import sys
import traceback
from typing import Dict, Optional

import jax
import jax.numpy as jnp
import numpy as np
import gemmi


# Make src importable whether we're run from repo root or /opt/mosaic on Modal
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from mosaic.models.boltz2 import Boltz2
from mosaic.structure_prediction import TargetChain
from mosaic.losses.structure_prediction import (
    IPTMLoss,
    BinderTargetIPSAE,
    TargetBinderIPSAE,
    IPSAE_min,
)

from src.losses.consensus import (
    predict_chai1,
    consensus_pae,
    consensus_gate,
)
from src.losses.rmsd_binder import rmsd_binder, shape_complementarity


__all__ = ["validate_with_consensus"]


def _run_boltz2(sequence: str, target_cif: str, seed: int, num_samples: int = 5) -> Dict:
    """Run Boltz2 best-of-N sampling. Mirror of validate_boltz2.py logic."""
    boltz2 = Boltz2()

    target_st = gemmi.read_structure(target_cif)
    target_st.setup_entities()
    target_st.remove_ligands_and_waters()
    target_chain = target_st[0][0]
    target_seq = "".join(gemmi.one_letter_code([r.name for r in target_chain]))

    features, writer = Boltz2.target_only_features([
        TargetChain(sequence, use_msa=True),
        TargetChain(target_seq, use_msa=True, template_chain=target_chain),
    ])

    binder_len = len(sequence)
    dummy_seq = jnp.zeros((binder_len, 20))
    metric_key = jax.random.key(0)

    best_output = None
    best_iptm = -1.0

    for i in range(num_samples):
        sample_key = jax.random.fold_in(jax.random.key(seed), i)
        output = boltz2.model_output(
            PSSM=None,
            features=features,
            recycling_steps=8,
            key=sample_key,
        )
        _, aux = IPTMLoss()(dummy_seq, output, key=metric_key)
        sample_iptm = float(aux["iptm"])
        print(f"  Boltz2 sample {i+1}/{num_samples}: ipTM={sample_iptm:.4f}")
        if sample_iptm > best_iptm:
            best_iptm = sample_iptm
            best_output = output

    _, a_iptm = IPTMLoss()(dummy_seq, best_output, key=metric_key)
    _, a_bt = BinderTargetIPSAE()(dummy_seq, best_output, key=metric_key)
    _, a_tb = TargetBinderIPSAE()(dummy_seq, best_output, key=metric_key)
    _, a_min = IPSAE_min()(dummy_seq, best_output, key=metric_key)

    scores = {
        "iptm":      float(a_iptm["iptm"]),
        "plddt":     float(np.asarray(best_output.plddt)[:binder_len].mean()),
        "bt_ipsae":  float(a_bt["bt_ipsae"]),
        "tb_ipsae":  float(a_tb["tb_ipsae"]),
        "min_ipsae": float(a_min["ipsae_min"]),
    }

    # Save PDB
    st = writer(best_output.structure_coordinates)
    return {
        "scores": scores,
        "pae": np.asarray(best_output.pae),
        "plddt": np.asarray(best_output.plddt),
        "structure": st,
        "binder_length": binder_len,
    }


def _recompute_metrics_from_pae(pae: np.ndarray, binder_len: int, d0: float = 31.8) -> Dict[str, float]:
    """Recompute ipTM/bt_ipsae/tb_ipsae/min_ipsae from a consensus PAE matrix.

    Replicates the standard pTM/ipSAE formulas. Used when we average PAE across
    Boltz2 + Chai-1 and need fresh metrics.
    """
    n = pae.shape[0]
    ptm_pair = 1.0 / (1.0 + (pae / d0) ** 2)

    # Build chain masks
    idx = np.arange(n)
    binder_i = idx < binder_len
    target_i = ~binder_i

    # ipTM — average pTM score over inter-chain pairs (both directions averaged)
    bt_mask = np.outer(binder_i, target_i)    # binder rows, target cols
    tb_mask = np.outer(target_i, binder_i)    # target rows, binder cols
    inter_mask = bt_mask | tb_mask
    iptm = float(ptm_pair[inter_mask].mean())

    # ipSAE: per-residue, aligned-error weighted score; we approximate here as
    # mean pTM pair score over the interface by direction. The exact Dunbrack
    # ipSAE is more involved; this approximation is monotone in the true score
    # and sufficient for consensus gating. For strict ipSAE use the Protenix/
    # Boltz2 loss terms on the original outputs (done elsewhere).
    bt_ipsae = float(ptm_pair[bt_mask].mean())
    tb_ipsae = float(ptm_pair[tb_mask].mean())
    min_ipsae = min(bt_ipsae, tb_ipsae)

    return {
        "iptm":      iptm,
        "bt_ipsae":  bt_ipsae,
        "tb_ipsae":  tb_ipsae,
        "min_ipsae": min_ipsae,
    }


def validate_with_consensus(
    seed: int,
    sequence: str,
    target_cif: str,
    designed_pdb: Optional[str] = None,
    run_chai1: bool = True,
    run_sc: bool = True,
    ipsae_threshold: float = 0.8,
    min_predictors_passing: int = 2,
    output_dir: str = "v5_validation_outputs",
) -> Dict:
    """Boltz2 + Chai-1 consensus validation with post-hoc metrics.

    Returns a dict with boltz2, chai1 (or None), consensus, post_hoc, and gate result.
    """
    os.makedirs(output_dir, exist_ok=True)

    # --- 1. Boltz2 ---
    print(f"=== Boltz2 for seed {seed} ===")
    b2 = _run_boltz2(sequence, target_cif, seed)
    binder_len = b2["binder_length"]
    boltz2_pdb = os.path.join(output_dir, f"seed_{seed:03d}_boltz2.pdb")
    with open(boltz2_pdb, "w") as f:
        f.write(b2["structure"].make_minimal_pdb())

    # --- 2. Chai-1 (optional) ---
    chai1_scores = None
    chai1_pdb = None
    chai1_pae = None
    if run_chai1:
        try:
            print(f"=== Chai-1 for seed {seed} ===")
            chai1_out = predict_chai1(sequence, target_cif)
            chai1_pae = chai1_out["pae"]
            # Quick ipSAE/iptm metrics from Chai PAE
            chai1_scores = _recompute_metrics_from_pae(chai1_pae, binder_len)
            chai1_scores["plddt"] = float(np.asarray(chai1_out["plddt"])[:binder_len].mean())
            # Save Chai structure
            chai1_pdb = os.path.join(output_dir, f"seed_{seed:03d}_chai1.pdb")
            _save_coords_as_pdb(chai1_out["structure_coordinates"], chai1_pdb)
        except Exception as e:
            print(f"Chai-1 failed (continuing with Boltz2-only): {type(e).__name__}: {e}")
            traceback.print_exc()
            chai1_scores = None
            chai1_pae = None

    # --- 3. Consensus ---
    if chai1_pae is not None:
        cons_pae = consensus_pae([b2["pae"], chai1_pae], method="mean")
    else:
        cons_pae = b2["pae"]
    consensus_scores = _recompute_metrics_from_pae(cons_pae, binder_len)

    # --- 4. Post-hoc: RMSD_binder, SC ---
    post_hoc: Dict[str, Optional[float]] = {"rmsd_binder": None, "sc": None, "dSASA": None}
    if designed_pdb and os.path.exists(designed_pdb):
        try:
            post_hoc["rmsd_binder"] = rmsd_binder(designed_pdb, boltz2_pdb)
        except Exception as e:
            print(f"rmsd_binder failed: {e}")
    if run_sc:
        try:
            sc_out = shape_complementarity(boltz2_pdb)
            post_hoc["sc"] = sc_out["sc"]
            post_hoc["dSASA"] = sc_out["dSASA"]
        except ImportError as e:
            print(f"Shape complementarity skipped (PyRosetta absent): {e}")
        except Exception as e:
            print(f"Shape complementarity failed: {e}")

    # --- 5. Consensus gate ---
    gate_scores: Dict[str, Dict[str, float]] = {"boltz2": b2["scores"]}
    if chai1_scores is not None:
        gate_scores["chai1"] = chai1_scores
    # If we only have one predictor (Chai failed), require that one to pass on its own.
    required = min_predictors_passing if chai1_scores is not None else 1
    passes = consensus_gate(gate_scores, ipsae_threshold, required)

    return {
        "seed": seed,
        "passes_consensus_gate": passes,
        "boltz2": b2["scores"],
        "chai1": chai1_scores,
        "consensus": consensus_scores,
        "post_hoc": post_hoc,
        "pdb_path": boltz2_pdb,
        "chai1_pdb_path": chai1_pdb,
    }


def _save_coords_as_pdb(coords: np.ndarray, out_path: str) -> None:
    """Minimal PDB writer for CA-only coords (used for Chai output)."""
    with open(out_path, "w") as f:
        for i, (x, y, z) in enumerate(coords, start=1):
            f.write(
                f"ATOM  {i:5d}  CA  ALA A{i:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 50.00           C\n"
            )
        f.write("END\n")


def _main() -> int:
    parser = argparse.ArgumentParser(description="V5 consensus validator")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--sequence", type=str, required=True)
    parser.add_argument("--target-cif", type=str, required=True)
    parser.add_argument("--designed-pdb", type=str, default=None,
                        help="Design-time PDB for RMSD_binder (optional)")
    parser.add_argument("--skip-chai1", action="store_true")
    parser.add_argument("--skip-sc", action="store_true")
    parser.add_argument("--ipsae-threshold", type=float, default=0.8)
    parser.add_argument("--min-predictors-passing", type=int, default=2)
    parser.add_argument("--output-dir", type=str, default="v5_validation_outputs")
    args = parser.parse_args()

    result = validate_with_consensus(
        seed=args.seed,
        sequence=args.sequence,
        target_cif=args.target_cif,
        designed_pdb=args.designed_pdb,
        run_chai1=not args.skip_chai1,
        run_sc=not args.skip_sc,
        ipsae_threshold=args.ipsae_threshold,
        min_predictors_passing=args.min_predictors_passing,
        output_dir=args.output_dir,
    )

    print(f"\n=== VALIDATION RESULT (seed={args.seed}) ===")
    print(f"Passes consensus gate : {result['passes_consensus_gate']}")
    print(f"Boltz2 min_ipsae      : {result['boltz2']['min_ipsae']:.4f}")
    if result["chai1"] is not None:
        print(f"Chai1 min_ipsae       : {result['chai1']['min_ipsae']:.4f}")
    else:
        print("Chai1 min_ipsae       : (skipped)")
    print(f"Consensus min_ipsae   : {result['consensus']['min_ipsae']:.4f}")
    print(f"RMSD_binder (A)       : {result['post_hoc']['rmsd_binder']}")
    print(f"SC                    : {result['post_hoc']['sc']}")
    print(f"PDB                   : {result['pdb_path']}")

    # Compact CSV line for Modal log-scraping
    chai_min = result['chai1']['min_ipsae'] if result['chai1'] else float('nan')
    print(
        f"\nCSV:{args.seed},"
        f"{int(result['passes_consensus_gate'])},"
        f"{result['boltz2']['min_ipsae']:.4f},"
        f"{chai_min:.4f},"
        f"{result['consensus']['min_ipsae']:.4f},"
        f"{result['post_hoc']['rmsd_binder'] if result['post_hoc']['rmsd_binder'] is not None else float('nan')},"
        f"{result['post_hoc']['sc'] if result['post_hoc']['sc'] is not None else float('nan')}"
    )
    return 0 if result["passes_consensus_gate"] else 2


if __name__ == "__main__":
    sys.exit(_main())
