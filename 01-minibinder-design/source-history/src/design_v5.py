"""V5 minibinder design — Mosaic pipeline with novel loss terms.

Rewrite of design_god_5g51_v4.py. Preserves all v4 fixes (template_chain,
MPNN weight 4.0, binder 85aa, IPSAE_min 2.5) and adds:

  * pTMEnergy upweighted 0.075 -> 1.5 (BindEnergyCraft, arXiv:2505.21241)
  * LIS — Local Interaction Score (Kim et al.; adapted objective), weight 0.5
  * actifpTM — contact-weighted ipTM (Bioinformatics 2025), weight 0.5

All loss weights and optimization hyperparameters live in DesignConfig
(src/design_config.py) loaded from YAML. Same output artifacts as v4 for
drop-in Modal compatibility.

Usage:
    python src/design_v5.py --seed 42 --config config/v5_default.yaml
    python src/design_v5.py --seed 42 --target-structure 5G51.cif    # defaults otherwise

Outputs written to {output_dir}/:
    seed_{seed:03d}_complex.pdb
    seed_{seed:03d}_pssm.png
    seed_{seed:03d}_pae.png
    seed_{seed:03d}_plddt.png
    seed_{seed:03d}_meta.json         # sequence, metrics, config echo
    and one CSV: line on stdout for Modal scraping
"""

import argparse
import json
import os
import sys
from typing import Optional

# Make src.losses and siblings importable regardless of cwd
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import importlib
import jax
import jax.numpy as jnp
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import gemmi

import mosaic
from mosaic.optimizers import simplex_APGM
import mosaic.losses.structure_prediction as sp
from mosaic.losses.protein_mpnn import InverseFoldingSequenceRecovery
from mosaic.proteinmpnn.mpnn import ProteinMPNN
from mosaic.structure_prediction import TargetChain
from mosaic.models.protenix import ProtenixV2
from mosaic.common import TOKENS

from src.design_config import DesignConfig
from src.losses.ptm_energy import pTMEnergy
from src.losses.ipsae_metrics import (
    IPSAE_min,
    BinderTargetIPSAE,
    TargetBinderIPSAE,
    LIS,
)
from src.losses.actifptm import actifpTM
from src.losses.hotspot_distance import HotspotDistance


# ----------------------------- Loss assembly ---------------------------------

def _build_structure_loss(cfg: DesignConfig, mpnn):
    """Assemble the weighted sum of LossTerms from the config.

    NOTE on weights: we pass every weight through config.loss_weights so campaigns
    can be re-tuned without code edits. Any weight absent from the dict is treated
    as 0 (term disabled).
    """
    w = cfg.loss_weights

    terms = (
        w.get("binder_target_contact", 0.0)  * sp.BinderTargetContact()
        + w.get("within_binder_contact", 0.0)* sp.WithinBinderContact()
        + w.get("target_binder_pae", 0.0)    * sp.TargetBinderPAE()
        + w.get("binder_target_pae", 0.0)    * sp.BinderTargetPAE()
        + w.get("iptm", 0.0)                 * sp.IPTMLoss()
        + w.get("within_binder_pae", 0.0)    * sp.WithinBinderPAE()
        + w.get("ptm_energy", 0.0)           * pTMEnergy()
        + w.get("plddt", 0.0)                * sp.PLDDTLoss()
        + w.get("rog", 0.0)                  * sp.ActualRadiusOfGyration(
                                                   target_radius=2.38 * cfg.binder_length ** 0.365)
        + w.get("binder_target_ipsae", 0.0)  * BinderTargetIPSAE()
        + w.get("target_binder_ipsae", 0.0)  * TargetBinderIPSAE()
        + w.get("ipsae_min", 0.0)            * IPSAE_min()
        # NEW v5 terms (binder_len inferred from sequence inside each loss)
        + w.get("lis", 0.0)                  * LIS()
        + w.get("actifptm", 0.0)             * actifpTM()
        + w.get("hotspot", 0.0)              * HotspotDistance(hotspots=tuple(cfg.hotspot_indices), distance_threshold=cfg.hotspot_threshold)
        # MPNN sequence recovery
        + w.get("mpnn", cfg.mpnn_weight)     * InverseFoldingSequenceRecovery(
                                                   mpnn, temp=jnp.array(cfg.mpnn_temperature))
    )

    # HelixLoss is subtracted (mild helical propensity bias)
    helix_w = w.get("helix", 0.0)
    if helix_w != 0.0:
        terms = terms + helix_w * sp.HelixLoss()

    # Optional NoCysteine (heavily penalized)
    if w.get("no_cysteine", 0.0) > 0.0:
        try:
            from mosaic.losses.structure_prediction import NoCysteine
            terms = terms + w["no_cysteine"] * NoCysteine()
            print(f"NoCysteine penalty active (weight={w['no_cysteine']})")
        except ImportError:
            print("NoCysteine unavailable in this mosaic build — skipping cysteine penalty")

    return terms


# ----------------------------- Main ------------------------------------------

def run(cfg: DesignConfig) -> dict:
    cfg.validate()
    os.makedirs(cfg.output_dir, exist_ok=True)

    seed = cfg.seed
    bl = cfg.binder_length
    print(f"=== V5 Design | seed={seed} target={cfg.target_structure} binder_len={bl} ===")

    # Load target structure (template_chain is CRITICAL — v3b bug)
    print(f"Loading {cfg.target_structure}...")
    target_structure = gemmi.read_structure(cfg.target_structure)
    target_structure.setup_entities()
    target_structure.remove_ligands_and_waters()
    target_sequence = gemmi.one_letter_code([r.name for r in target_structure[0][0]])
    print(f"Target ({len(target_sequence)} aa): {target_sequence}")

    # ProtenixV2 — image is pinned to mosaic commit bca3152 which has V2 +
    # the pre-refactor protenix loader that's compatible with the pickled weights.
    print("Loading ProtenixV2...")
    protenix = ProtenixV2()

    print("Generating binder-target features (template_chain set)...")
    design_features, design_structure = protenix.binder_features(
        binder_length=bl,
        chains=[
            TargetChain(
                target_sequence,
                use_msa=True,
                template_chain=target_structure[0][0],   # CRITICAL — keep from v4
            )
        ],
    )

    # Load soluble ProteinMPNN
    print("Loading soluble ProteinMPNN...")
    mpnn = ProteinMPNN.from_pretrained(
        importlib.resources.files(mosaic) / "proteinmpnn/weights/soluble_v_48_020.pt"
    )

    # Build loss
    print("Building loss (v5: pTMEnergy^20x, +LIS, +actifpTM)...")
    structure_loss = _build_structure_loss(cfg, mpnn)

    loss = protenix.build_multisample_loss(
        loss=structure_loss,
        features=design_features,
        recycling_steps=cfg.recycling_steps_design,
        sampling_steps=cfg.sampling_steps,
    )

    # Phase 1 — continuous simplex
    print(f"Phase 1: continuous optimization ({cfg.phase1_steps} steps)")
    print("(First call triggers JIT compilation — may take up to 5 minutes)")
    PSSM = jax.nn.softmax(
        0.5 * jax.random.gumbel(key=jax.random.key(seed), shape=(bl, 20))
    )
    _, PSSM = simplex_APGM(
        loss_function=loss,
        x=PSSM,
        n_steps=cfg.phase1_steps,
        stepsize=0.15 * np.sqrt(bl),
        momentum=0.3,
        scale=1.0,
        update_loss_state=False,
        max_gradient_norm=1.0,
    )

    # Phase 2 — sharpening
    print(f"Phase 2: sharpening ({cfg.phase2_steps} steps)")
    PSSM_sharp, _ = simplex_APGM(
        loss_function=loss,
        x=jnp.log(PSSM + 1e-5),
        n_steps=cfg.phase2_steps,
        stepsize=0.5 * np.sqrt(bl),
        momentum=0.0,
        scale=1.3,
        update_loss_state=False,
        logspace=False,
        max_gradient_norm=1.0,
    )

    # Visualize PSSM
    pssm_png = os.path.join(cfg.output_dir, f"seed_{seed:03d}_pssm.png")
    plt.figure(figsize=(10, 4))
    plt.imshow(PSSM_sharp, aspect="auto")
    plt.xlabel("Amino Acid")
    plt.ylabel("Position")
    plt.title(f"V5 Sharpened PSSM (seed={seed})")
    plt.colorbar()
    plt.savefig(pssm_png, dpi=150, bbox_inches="tight")
    plt.close()

    # Final prediction with more recycling steps
    print(f"Repredicting with {cfg.recycling_steps_predict} recycling steps...")
    protenix_pred = protenix.predict(
        PSSM=PSSM_sharp,
        features=design_features,
        recycling_steps=cfg.recycling_steps_predict,
        key=jax.random.key(0),
        writer=design_structure,
    )

    binder_plddt = float(protenix_pred.plddt[:bl].mean())
    target_plddt = float(protenix_pred.plddt[bl:].mean())
    iptm = float(protenix_pred.iptm)

    # PAE plot
    pae_png = os.path.join(cfg.output_dir, f"seed_{seed:03d}_pae.png")
    plt.figure(figsize=(8, 6))
    plt.imshow(protenix_pred.pae, vmin=0, vmax=30)
    plt.axhline(bl, color="red", linestyle="--", alpha=0.7)
    plt.axvline(bl, color="red", linestyle="--", alpha=0.7)
    plt.title(f"PAE (seed={seed}, ipTM={iptm:.3f})")
    plt.colorbar()
    plt.savefig(pae_png, dpi=150, bbox_inches="tight")
    plt.close()

    # pLDDT plot
    plddt_png = os.path.join(cfg.output_dir, f"seed_{seed:03d}_plddt.png")
    plt.figure(figsize=(10, 3))
    plt.plot(protenix_pred.plddt)
    plt.vlines([bl], protenix_pred.plddt.min(), protenix_pred.plddt.max(),
               linestyle="dashed", color="red")
    plt.title(f"pLDDT per residue (seed={seed})")
    plt.xlabel("Residue")
    plt.ylabel("pLDDT")
    plt.savefig(plddt_png, dpi=150, bbox_inches="tight")
    plt.close()

    # PDB
    pdb_path = os.path.join(cfg.output_dir, f"seed_{seed:03d}_complex.pdb")
    with open(pdb_path, "w") as f:
        f.write(protenix_pred.st.make_minimal_pdb())

    # Designed sequence
    designed_seq = "".join([TOKENS[i] for i in PSSM_sharp.argmax(-1)])
    cys_count = designed_seq.count("C")

    # Metadata dump
    meta = {
        "seed": seed,
        "designed_sequence": designed_seq,
        "binder_length": bl,
        "cysteine_count": cys_count,
        "target_structure": cfg.target_structure,
        "binder_plddt": binder_plddt,
        "target_plddt": target_plddt,
        "iptm": iptm,
        "config": {
            "phase1_steps": cfg.phase1_steps,
            "phase2_steps": cfg.phase2_steps,
            "mpnn_weight": cfg.mpnn_weight,
            "mpnn_temperature": cfg.mpnn_temperature,
            "loss_weights": cfg.loss_weights,
        },
        "paths": {
            "pdb": pdb_path,
            "pae_png": pae_png,
            "plddt_png": plddt_png,
            "pssm_png": pssm_png,
        },
    }
    meta_path = os.path.join(cfg.output_dir, f"seed_{seed:03d}_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n=== V5 RESULTS (seed={seed}) ===")
    print(f"Binder pLDDT: {binder_plddt:.4f}")
    print(f"Target pLDDT: {target_plddt:.4f}")
    print(f"ipTM:         {iptm:.4f}")
    print(f"Designed seq ({len(designed_seq)} aa, {cys_count} Cys): {designed_seq}")
    # Modal log scraper relies on this exact prefix.
    print(f"\nCSV:{seed},{designed_seq},{len(designed_seq)},{cys_count},"
          f"{binder_plddt:.4f},{target_plddt:.4f},{iptm:.4f}")
    print("Done.")

    return meta


# ----------------------------- CLI -------------------------------------------

def _parse_args() -> DesignConfig:
    parser = argparse.ArgumentParser(description="V5 minibinder design")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (overrides config)")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config")
    parser.add_argument("--target-structure", type=str, default=None,
                        help="Target CIF path (overrides config)")
    parser.add_argument("--binder-length", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    if args.config:
        cfg = DesignConfig.from_yaml(args.config)
    else:
        # Minimal defaults if no YAML. Seed and target required.
        if args.seed is None or args.target_structure is None:
            parser.error("--seed and --target-structure required when --config omitted")
        cfg = DesignConfig(seed=args.seed, target_structure=args.target_structure)

    # CLI overrides win over YAML
    if args.seed is not None:
        cfg.seed = args.seed
    if args.target_structure is not None:
        cfg.target_structure = args.target_structure
    if args.binder_length is not None:
        cfg.binder_length = args.binder_length
    if args.output_dir is not None:
        cfg.output_dir = args.output_dir
    return cfg


if __name__ == "__main__":
    cfg = _parse_args()
    run(cfg)
