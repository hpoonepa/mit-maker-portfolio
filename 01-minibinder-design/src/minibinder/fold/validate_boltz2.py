"""Boltz2 cross-validation for RBX1 minibinder candidates.

Takes a seed number and designed binder sequence, runs Boltz2 structure
prediction against a target, and outputs:
  - Binder pLDDT (Boltz2)
  - ipTM (Boltz2)
  - bt_ipSAE, tb_ipSAE (binder->target and target->binder)
  - min_ipSAE (minimum of bt and tb)

Usage:
    python validate_boltz2.py <seed> <sequence> [target_cif]

If target_cif is provided (e.g. 5G51.cif), loads that CIF with template.
Otherwise, loads 2LGV.cif and uses the PDB structure as template."""

import sys
import jax
import jax.numpy as jnp
import gemmi

from mosaic.models.boltz2 import Boltz2
from mosaic.structure_prediction import TargetChain
from mosaic.losses.structure_prediction import (
    IPTMLoss,
    BinderTargetIPSAE,
    TargetBinderIPSAE,
    IPSAE_min,
)

seed = int(sys.argv[1])
sequence = sys.argv[2]
target_cif = sys.argv[3] if len(sys.argv) > 3 else "2LGV.cif"
binder_len = len(sequence)

print(f"=== Boltz2 Validation: seed={seed}, len={binder_len} ===")

# Load Boltz2
print("Loading Boltz2...")
boltz2 = Boltz2()

# Build features — load CIF with template
print(f"Loading {target_cif}...")
target_st = gemmi.read_structure(target_cif)
target_st.setup_entities()
target_st.remove_ligands_and_waters()
target_chain = target_st[0][0]
target_seq = "".join(gemmi.one_letter_code([r.name for r in target_chain]))
print(f"Target: {len(target_seq)} residues (from {target_cif}, with template)")
features, writer = Boltz2.target_only_features([
    TargetChain(sequence, use_msa=True),
    TargetChain(target_seq, use_msa=True, template_chain=target_chain),
])

# Run Boltz2 inference with best-of-5 sampling
num_samples = 5
print(f"Running Boltz2 inference ({num_samples} samples, recycling=8)...")
print("(First call triggers JIT compilation — may take a few minutes)")

dummy_seq = jnp.zeros((binder_len, 20))
metric_key = jax.random.key(0)

best_output = None
best_iptm = -1.0

for i in range(num_samples):
    sample_key = jax.random.fold_in(jax.random.key(seed), i)
    sample_output = boltz2.model_output(
        PSSM=None,
        features=features,
        recycling_steps=8,
        key=sample_key,
    )
    # Compute ipTM for this sample to select the best
    _, aux = IPTMLoss()(dummy_seq, sample_output, key=metric_key)
    sample_iptm = float(aux["iptm"])
    print(f"  Sample {i+1}/{num_samples}: ipTM={sample_iptm:.4f}")

    if sample_iptm > best_iptm:
        best_iptm = sample_iptm
        best_output = sample_output

output = best_output
print(f"Selected best sample (ipTM={best_iptm:.4f})")

# Compute all metrics on the best sample
b2_plddt = float(output.plddt[:binder_len].mean())

_, aux = IPTMLoss()(dummy_seq, output, key=metric_key)
b2_iptm = float(aux["iptm"])

_, aux = BinderTargetIPSAE()(dummy_seq, output, key=metric_key)
b2_bt_ipsae = float(aux["bt_ipsae"])

_, aux = TargetBinderIPSAE()(dummy_seq, output, key=metric_key)
b2_tb_ipsae = float(aux["tb_ipsae"])

_, aux = IPSAE_min()(dummy_seq, output, key=metric_key)
b2_min_ipsae = float(aux["ipsae_min"])

# Save Boltz2-predicted structure
st = writer(output.structure_coordinates)
pdb_data = st.make_minimal_pdb()
target_name = target_cif.replace(".cif", "").lower()
pdb_path = f"{target_name}_boltz2_seed{seed:03d}.pdb"
with open(pdb_path, "w") as f:
    f.write(pdb_data)
print(f"Saved {pdb_path}")

# Results
print(f"\n=== RESULTS (seed={seed}) ===")
print(f"Boltz2 pLDDT:     {b2_plddt:.4f}")
print(f"Boltz2 ipTM:      {b2_iptm:.4f}")
print(f"Boltz2 bt_ipSAE:  {b2_bt_ipsae:.4f}")
print(f"Boltz2 tb_ipSAE:  {b2_tb_ipsae:.4f}")
print(f"Boltz2 min_ipSAE: {b2_min_ipsae:.4f}")

# CSV output for collection
print(f"\nCSV:{seed},{b2_plddt:.4f},{b2_iptm:.4f},{b2_bt_ipsae:.4f},{b2_tb_ipsae:.4f},{b2_min_ipsae:.4f}")
print("\nDone!")
