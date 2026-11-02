"""
God-tier DWV-VP3 (PDB 5G51) minibinder design using Protenix 2025.
Optimized loss weights derived from Proteinbase analysis of 5000+ de novo binders.

Key optimizations over protenij.py defaults:
- 4x IPTMLoss (0.025 -> 0.1): targets ipTM validation failures
- 2.5x PLDDTLoss (0.1 -> 0.25): targets pLDDT filter failures (15% fail rate)
- Enabled BinderTargetIPSAE + TargetBinderIPSAE (0.0 -> 0.2): #1 failure mode (28%)
- Enabled HelixLoss (-0.15): helix propensity correlates with binding success
- Enabled RadiusOfGyration (0.1): compact binders fold better
- NoCysteine penalty: eliminates 15% cysteine-related failures
- Reduced binder length (75 -> 65): shorter binders bind better (Proteinbase AUC=0.597)

V2 changes (fixing E/L bias from v1 campaign):
- MPNN weight 10.0 -> 5.0, temp 0.001 -> 0.01 (mosaic validated defaults)
- Added ESM2 pseudo-likelihood loss wrapped in ClippedLoss

V3 changes (best-of-three synthesis: our V1 data + Vedant's weights + 5-agent analysis):
- MPNN weight 5.0 -> 8.0 (top predictor r=0.658, safe at temp=0.01)
- PLDDTLoss 0.25 -> 0.1 (was #1 E/L bias driver; default campaign had better hit rates)
- HelixLoss removed (sign controversy, contributed to E/L bias)
- ipSAE 0.2 -> 0.5 + IPSAE_min 1.5 (addresses #1 failure mode at 28%)
- BinderTargetContact 1.0 -> 1.5 (stronger interface for flat RBX1 surface)
- Cross-chain PAE 0.05 -> 0.1 (underweighted interface confidence)
- ESM2 PLL 0.5 -> 0.3 (reduce tension with higher MPNN weight)

Usage:
    python design_god.py          # random seed
    python design_god.py 42       # specific seed
"""

import sys
import jax
import jax.numpy as jnp
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import importlib
import mosaic

from mosaic.optimizers import simplex_APGM
import mosaic.losses.structure_prediction as sp
from mosaic.losses.protein_mpnn import InverseFoldingSequenceRecovery
from mosaic.losses.transformations import ClippedLoss
from mosaic.proteinmpnn.mpnn import ProteinMPNN
from mosaic.structure_prediction import TargetChain
from mosaic.models.protenix import Protenix2025
from mosaic.common import LossTerm


# Try to import NoCysteine (available in mosaic but not used in protenij.py)
try:
    from mosaic.losses.structure_prediction import NoCysteine
    HAS_NOCYSTEINE = True
    print("NoCysteine loss available — will penalize cysteine residues")
except ImportError:
    HAS_NOCYSTEINE = False
    print("NoCysteine not available — skipping cysteine penalty")

# --- Seed handling ---
seed = int(sys.argv[1]) if len(sys.argv) > 1 else np.random.randint(1000000)
print(f"=== God-tier Design | Seed: {seed} ===")

# --- Cell: Load model ---
print("Loading Protenix2025...")
protenix = Protenix2025()

# --- Cell: Binder length ---
# Proteinbase: shorter binders bind better (AUC=0.597). 65 aa validated in RBX1 campaign.
binder_length = 65

# --- Cell: Target sequence ---
# DWV-VP3-P-DOMAIN sequence (157aa) — PDB 5G51 entity 1
target_sequence = "EEYRAKTGYAPYYAGVWHSFNNSNSLVFRWGSASDQIAQWPTISVPRGELAFLRIKDGKQAAVGTQPWRTMVVWPSGHGYNIGIPTYNAERARQLAQHLYGGGSLTDEKAKQLFVPANQQGPGKVSNGNPVWEVMRAPLATQRAHIQDFEFIEAIPE"
print(f"Target sequence ({len(target_sequence)} aa): {target_sequence}")

# --- Cell: Generate binder-target features ---
print("Generating features...")
design_features, design_structure = protenix.binder_features(
    binder_length=binder_length,
    chains=[
        TargetChain(
            target_sequence,
            use_msa=True,
        )
    ],
)

# --- Cell: Load soluble ProteinMPNN ---
print("Loading soluble ProteinMPNN...")
mpnn = ProteinMPNN.from_pretrained(
    importlib.resources.files(mosaic)
    / "proteinmpnn/weights/soluble_v_48_020.pt"
)

# --- Cell: Construct loss function (GOD V3b — ESM2 REMOVED) ---
# V3b: Removed ESM2 PLL — caused JIT hangs/OOM even with sequential workaround
# Remaining V3 changes: MPNN 5→8, PLDDTLoss 0.25→0.1, HelixLoss removed,
#   ipSAE 0.2→0.5 + IPSAE_min, contact 1→1.5, PAE 0.05→0.1
structure_loss = (
    1.5 * sp.BinderTargetContact()                                               # 1.0 -> 1.5 — stronger contact for flat RBX1 surface (Vedant)
    + 1 * sp.WithinBinderContact()                                               # 1.0  — internal packing (unchanged)
    + 0.1 * sp.TargetBinderPAE()                                                 # 0.05 -> 0.1 — stronger interface confidence (Vedant)
    + 0.1 * sp.BinderTargetPAE()                                                 # 0.05 -> 0.1 — bidirectional PAE (Vedant)
    + 0.1 * sp.IPTMLoss()                                                        # 0.025 -> 0.1 (4x) — directly optimizes success metric (ours)
    + 0.4 * sp.WithinBinderPAE()                                                 # 0.4  — internal confidence (unchanged)
    + 0.025 * sp.pTMEnergy()                                                     # 0.025 — fold quality (unchanged)
    + 0.1 * sp.PLDDTLoss()                                                       # 0.25 -> 0.1 — high PLDDTLoss was #1 E/L bias driver (fixed)
    + 8.0 * InverseFoldingSequenceRecovery(mpnn, temp=jax.numpy.array(0.01))     # 5.0 -> 8.0 — #1 predictor (r=0.658), safe at temp=0.01 (Vedant)
    + 0.1 * sp.ActualRadiusOfGyration(target_radius=2.38 * binder_length**0.365) # 0.1  — compact binders fold better (ours)
    + 0.5 * sp.BinderTargetIPSAE()                                               # 0.2 -> 0.5 — #1 failure mode at 28% (Vedant)
    + 0.5 * sp.TargetBinderIPSAE()                                               # 0.2 -> 0.5 — bidirectional ipSAE (Vedant)
    + 1.5 * sp.IPSAE_min()                                                       # NEW — floor guarantee, prevents asymmetric ipSAE failures (Vedant)
)

# Add NoCysteine penalty if available (18% of designs fail for cysteines)
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

# --- Cell: Phase 1 — continuous optimization (120 steps, up from 100) ---
print("Phase 1: continuous optimization (120 steps)...")
print("(First call triggers JIT compilation — may take up to 4 minutes)")
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
    n_steps=120,
    stepsize=0.15 * np.sqrt(binder_length),
    momentum=0.3,
    scale=1.0,
    update_loss_state=False,
    max_gradient_norm=1.0,
)

# --- Cell: Phase 2 — sharpening ---
print("Phase 2: sharpening (20 steps)...")
PSSM_sharper, _ = simplex_APGM(
    loss_function=loss,
    x=jnp.log(PSSM + 1e-5),
    n_steps=20,
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
plt.title(f"God-tier Sharpened PSSM (seed={seed})")
plt.colorbar()
plt.savefig("god_pssm.png", dpi=150, bbox_inches="tight")
print("Saved god_pssm.png")

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
print(f"\n=== GOD-TIER RESULTS (seed={seed}) ===")
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
plt.savefig("god_pae.png", dpi=150, bbox_inches="tight")
print("Saved god_pae.png")

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
plt.savefig("god_plddt.png", dpi=150, bbox_inches="tight")
print("Saved god_plddt.png")

# --- Cell: Export PDB ---
pdb_data = protenix_pred.st.make_minimal_pdb()
with open("god_complex.pdb", "w") as f:
    f.write(pdb_data)
print("Saved god_complex.pdb")

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
