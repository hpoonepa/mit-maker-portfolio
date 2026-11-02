"""
5G51 V4 minibinder design — beta-optimized loss for DWV-VP3 jellyroll capsid.

Based on 23-agent deep research into why V3b (RBX1-optimized) failed on 5G51:
- V3b hit rate: 23% (vs 54% on RBX1) — weights tuned for helical, not beta-rich targets
- Root causes: missing template_chain, MPNN alanine repeats, contact overpressure,
  insufficient ipSAE floor, binder too short for flat beta surface

V4 changes from V3b:
  1. CRITICAL: Restore template_chain from 5G51.cif (was missing in god_5g51.py!)
  2. Binder length: 65 → 85 (more surface area for flat beta jellyroll)
  3. MPNN: 8.0 → 4.0, temp 0.01 → 0.1 (eliminate alanine repeats on hard targets)
  4. BinderTargetContact: 1.5 → 0.8 (less contact pressure on flat beta surface)
  5. WithinBinderContact: 1.0 → 1.2 (stronger internal packing for beta binders)
  6. Cross-chain PAE: 0.1 → 0.2 bidirectional (more interface confidence)
  7. IPTMLoss: 0.1 → 0.15 (slightly more ipTM pressure)
  8. WithinBinderPAE: 0.4 → 0.6 (better internal confidence for extended beta binders)
  9. pTMEnergy: 0.025 → 0.075 (3x — dense gradients help beta targets converge)
 10. RadiusOfGyration: 0.1 → 0.05 (beta binders can be more extended than helical)
 11. BinderTargetIPSAE: 0.5 → 0.7 (stronger ipSAE for hard targets)
 12. TargetBinderIPSAE: 0.5 → 0.4 (asymmetric — binder→target direction matters more)
 13. IPSAE_min: 1.5 → 2.5 (higher floor — prevents asymmetric ipSAE failures)
 14. HelixLoss: 0 → -0.08 (mild helix propensity — natural beta-binding mode in capsids)
 15. Phase 1: 120 → 160 steps, Phase 2: 20 → 30 steps (more optimization for harder target)

Loss budget rebalancing (V3b → V4):
  Interface terms: 2.6 → 2.15 (less contact, more PAE/ipSAE)
  Confidence terms: 0.625 → 0.925 (pTMEnergy 3x, WithinBinderPAE 1.5x)
  Sequence terms: 8.0 → 4.0 (MPNN halved, temp 10x — diversity over recovery)
  ipSAE terms: 2.5 → 3.6 (43% increase — addresses #1 failure mode)

Usage:
    python design_god_5g51_v4.py          # random seed
    python design_god_5g51_v4.py 42       # specific seed
"""

import sys
import jax
import jax.numpy as jnp
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import gemmi
import importlib
import mosaic

from mosaic.optimizers import simplex_APGM
import mosaic.losses.structure_prediction as sp
from mosaic.losses.protein_mpnn import InverseFoldingSequenceRecovery
from mosaic.proteinmpnn.mpnn import ProteinMPNN
from mosaic.structure_prediction import TargetChain
from mosaic.models.protenix import Protenix2025

# Try to import NoCysteine
try:
    from mosaic.losses.structure_prediction import NoCysteine
    HAS_NOCYSTEINE = True
    print("NoCysteine loss available — will penalize cysteine residues")
except ImportError:
    HAS_NOCYSTEINE = False
    print("NoCysteine not available — skipping cysteine penalty")

# --- Seed handling ---
seed = int(sys.argv[1]) if len(sys.argv) > 1 else np.random.randint(1000000)
print(f"=== 5G51 V4 Beta-Optimized Design | Seed: {seed} ===")

# --- Cell: Load model ---
print("Loading Protenix2025...")
protenix = Protenix2025()

# --- Cell: Binder length ---
# V4: 65 → 85aa — flat beta jellyroll needs more binder surface area
# Literature: capsid binders typically 70-100aa for effective beta-sheet engagement
binder_length = 85

# --- Cell: Load target structure ---
# CRITICAL FIX: Load crystal structure for template_chain
# V3b was MISSING template_chain — Protenix had to predict 5G51 fold from sequence alone,
# likely misfolding the complex jellyroll beta-barrel topology
print("Loading 5G51.cif...")
target_structure = gemmi.read_structure("5G51.cif")
target_structure.setup_entities()
target_structure.remove_ligands_and_waters()
target_sequence = gemmi.one_letter_code(
    [r.name for r in target_structure[0][0]]
)
print(f"Target sequence ({len(target_sequence)} aa): {target_sequence}")

# --- Cell: Generate binder-target features ---
# CRITICAL FIX: template_chain=target_structure[0][0] restores crystal structure guidance
# This is essential for beta-rich targets where MSA-only prediction is unreliable
print("Generating features...")
design_features, design_structure = protenix.binder_features(
    binder_length=binder_length,
    chains=[
        TargetChain(
            target_sequence,
            use_msa=True,
            template_chain=target_structure[0][0],
        )
    ],
)

# --- Cell: Load soluble ProteinMPNN ---
print("Loading soluble ProteinMPNN...")
mpnn = ProteinMPNN.from_pretrained(
    importlib.resources.files(mosaic)
    / "proteinmpnn/weights/soluble_v_48_020.pt"
)

# --- Cell: Construct loss function (V4 — beta-optimized for 5G51) ---
structure_loss = (
    0.8 * sp.BinderTargetContact()                                               # 1.5 → 0.8 — less contact pressure on flat beta surface (prevents hallucinated contacts)
    + 1.2 * sp.WithinBinderContact()                                             # 1.0 → 1.2 — stronger internal packing (beta binders need more self-contact)
    + 0.2 * sp.TargetBinderPAE()                                                # 0.1 → 0.2 — stronger interface confidence (flat beta needs more PAE signal)
    + 0.2 * sp.BinderTargetPAE()                                                # 0.1 → 0.2 — bidirectional PAE increase
    + 0.15 * sp.IPTMLoss()                                                       # 0.1 → 0.15 — slightly more ipTM pressure for hard targets
    + 0.6 * sp.WithinBinderPAE()                                                # 0.4 → 0.6 — extended beta binders need stronger internal confidence
    + 0.075 * sp.pTMEnergy()                                                     # 0.025 → 0.075 (3x) — dense gradients help beta targets converge
    + 0.1 * sp.PLDDTLoss()                                                       # unchanged — already correct at 0.1
    + 4.0 * InverseFoldingSequenceRecovery(mpnn, temp=jax.numpy.array(0.1))      # 8.0 → 4.0, temp 0.01 → 0.1 — eliminates alanine repeats, increases diversity
    + 0.05 * sp.ActualRadiusOfGyration(target_radius=2.38 * binder_length**0.365)# 0.1 → 0.05 — beta binders can be more extended (helix-on-sheet geometry)
    + 0.7 * sp.BinderTargetIPSAE()                                              # 0.5 → 0.7 — #1 failure mode (AUC 0.806), stronger for hard targets
    + 0.4 * sp.TargetBinderIPSAE()                                              # 0.5 → 0.4 — asymmetric: binder→target direction more predictive
    + 2.5 * sp.IPSAE_min()                                                       # 1.5 → 2.5 — higher floor prevents asymmetric ipSAE failures (14% of V3b fails)
    - 0.08 * sp.HelixLoss()                                                      # 0 → -0.08 — mild helix propensity (natural capsid binding mode from literature)
)

# Add NoCysteine penalty if available
if HAS_NOCYSTEINE:
    structure_loss = structure_loss + 5.0 * NoCysteine()
    print("Added NoCysteine penalty (weight=5.0)")

# --- Cell: Build multisample loss ---
print("Building multisample loss...")
loss = protenix.build_multisample_loss(
    loss=structure_loss,
    features=design_features,
    recycling_steps=1,
    sampling_steps=20,
)

# --- Cell: Phase 1 — continuous optimization (160 steps, up from 120) ---
# V4: More steps for harder beta target — allows loss landscape to be explored more thoroughly
print("Phase 1: continuous optimization (160 steps)...")
print("(First call triggers JIT compilation — may take up to 5 minutes)")
PSSM = jax.nn.softmax(
    0.5
    * jax.random.gumbel(
        key=jax.random.key(seed),
        shape=(binder_length, 20),
    )
)

_, PSSM = simplex_APGM(
    loss_function=loss,
    x=PSSM,
    n_steps=160,
    stepsize=0.15 * np.sqrt(binder_length),
    momentum=0.3,
    scale=1.0,
    update_loss_state=False,
    max_gradient_norm=1.0,
)

# --- Cell: Phase 2 — sharpening (30 steps, up from 20) ---
print("Phase 2: sharpening (30 steps)...")
PSSM_sharper, _ = simplex_APGM(
    loss_function=loss,
    x=jnp.log(PSSM + 1e-5),
    n_steps=30,
    stepsize=0.5 * np.sqrt(binder_length),
    momentum=0.0,
    scale=1.3,
    update_loss_state=False,
    logspace=False,
    max_gradient_norm=1.0,
)

# --- Cell: Save PSSM visualization ---
plt.figure(figsize=(10, 4))
plt.imshow(PSSM_sharper, aspect="auto")
plt.xlabel("Amino Acid")
plt.ylabel("Position")
plt.title(f"5G51 V4 Sharpened PSSM (seed={seed})")
plt.colorbar()
plt.savefig("5g51_v4_pssm.png", dpi=150, bbox_inches="tight")
print("Saved 5g51_v4_pssm.png")

# --- Cell: Repredict with recycling ---
print("Repredicting with 4 recycling steps...")
protenix_pred = protenix.predict(
    PSSM=PSSM_sharper,
    features=design_features,
    recycling_steps=4,
    key=jax.random.key(0),
    writer=design_structure,
)

# --- Cell: Print metrics ---
binder_plddt = float(protenix_pred.plddt[:binder_length].mean())
target_plddt = float(protenix_pred.plddt[binder_length:].mean())
iptm = float(protenix_pred.iptm)
print(f"\n=== 5G51 V4 RESULTS (seed={seed}) ===")
print(f"Binder pLDDT: {binder_plddt:.3f}")
print(f"Target pLDDT: {target_plddt:.3f}")
print(f"ipTM: {iptm:.3f}")

# --- Cell: Save PAE heatmap ---
plt.figure(figsize=(8, 6))
plt.imshow(protenix_pred.pae, vmin=0, vmax=30)
plt.axhline(binder_length, color="red", linestyle="--", alpha=0.7)
plt.axvline(binder_length, color="red", linestyle="--", alpha=0.7)
plt.title(f"PAE (seed={seed}, ipTM={iptm:.3f})")
plt.colorbar()
plt.savefig("5g51_v4_pae.png", dpi=150, bbox_inches="tight")
print("Saved 5g51_v4_pae.png")

# --- Cell: Save pLDDT plot ---
plt.figure(figsize=(10, 3))
plt.plot(protenix_pred.plddt)
plt.vlines(
    [binder_length],
    protenix_pred.plddt.min(),
    protenix_pred.plddt.max(),
    linestyle="dashed",
    color="red",
)
plt.title(f"pLDDT per residue (seed={seed})")
plt.xlabel("Residue")
plt.ylabel("pLDDT")
plt.savefig("5g51_v4_plddt.png", dpi=150, bbox_inches="tight")
print("Saved 5g51_v4_plddt.png")

# --- Cell: Export PDB ---
pdb_data = protenix_pred.st.make_minimal_pdb()
with open("5g51_v4_complex.pdb", "w") as f:
    f.write(pdb_data)
print("Saved 5g51_v4_complex.pdb")

# --- Print designed sequence ---
from mosaic.common import TOKENS
designed_seq = "".join([TOKENS[i] for i in PSSM_sharper.argmax(-1)])
cys_count = designed_seq.count("C")
print(f"\nDesigned binder sequence ({len(designed_seq)} aa):")
print(designed_seq)
print(f"Cysteine count: {cys_count}")

# --- CSV-friendly summary line ---
print(f"\nCSV:{seed},{designed_seq},{len(designed_seq)},{cys_count},{binder_plddt:.4f},{target_plddt:.4f},{iptm:.4f}")

print("\nDone!")
