"""
2LGV (RBX1) minibinder design using Protenix 2025.
Mirrors the protenij.py workflow exactly, targeting PDB 2LGV (RBX1).
Accepts seed as CLI argument for batch campaigns.

Usage:
    python design_2lgv.py          # random seed
    python design_2lgv.py 42       # specific seed
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
from mosaic.proteinmpnn.mpnn import ProteinMPNN
from mosaic.structure_prediction import TargetChain
from mosaic.models.protenix import Protenix2025

# --- Seed handling ---
seed = int(sys.argv[1]) if len(sys.argv) > 1 else np.random.randint(1000000)
print(f"=== Seed: {seed} ===")

# --- Cell: Load model ---
print("Loading Protenix2025...")
protenix = Protenix2025()

# --- Cell: Binder length ---
binder_length = 75

# --- Cell: RBX1 construct target sequence (108aa) ---
target_sequence = "MAAAMDVDTPSGTNSGAGKKRFEVKKWNAVALWAWDIVVDNCAICRNHIMDLCIECQANQASATSEECTVAWGVCNHAFHFHCISRWLKTRQVCPLDNREWEFQKYGH"
print(f"Target: RBX1 construct ({len(target_sequence)} aa)")

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

# --- Cell: Construct loss function (exact protenij.py weights) ---
structure_loss = (
    sp.BinderTargetContact()
    + 1 * sp.WithinBinderContact()
    + 0.05 * sp.TargetBinderPAE()
    + 0.05 * sp.BinderTargetPAE()
    + 0.025 * sp.IPTMLoss()
    + 0.4 * sp.WithinBinderPAE()
    + 0.025 * sp.pTMEnergy()
    + 0.1 * sp.PLDDTLoss()
    + 10.0 * InverseFoldingSequenceRecovery(mpnn, temp=jax.numpy.array(0.001))
    + 0.00
    * sp.ActualRadiusOfGyration(target_radius=2.38 * binder_length**0.365)
    - 0.0 * sp.HelixLoss()
    + 0.0 * sp.BinderTargetIPSAE()
    + 0.0 * sp.TargetBinderIPSAE()
)

# --- Cell: Build multisample loss ---
print("Building multisample loss...")
loss = protenix.build_multisample_loss(
    loss=structure_loss,
    features=design_features,
    recycling_steps=1,
    sampling_steps=20,
)

# --- Cell: Phase 1 — continuous optimization ---
print("Phase 1: continuous optimization (100 steps)...")
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
    n_steps=100,
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
plt.title(f"Sharpened PSSM (seed={seed})")
plt.colorbar()
plt.savefig("rbx1_pssm.png", dpi=150, bbox_inches="tight")
print("Saved rbx1_pssm.png")

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
print(f"\n=== RESULTS (seed={seed}) ===")
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
plt.savefig("rbx1_pae.png", dpi=150, bbox_inches="tight")
print("Saved rbx1_pae.png")

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
plt.savefig("rbx1_plddt.png", dpi=150, bbox_inches="tight")
print("Saved rbx1_plddt.png")

# --- Cell: Export PDB ---
pdb_data = protenix_pred.st.make_minimal_pdb()
with open("rbx1_complex.pdb", "w") as f:
    f.write(pdb_data)
print("Saved rbx1_complex.pdb")

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
