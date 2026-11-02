"""V5 loss modules — novel metrics for minibinder design.

Differentiable JAX loss terms (used inside simplex_APGM optimization):
  - pTMEnergy (re-exported from mosaic; upweighted 0.075 -> 1.5 in v5)
  - IPSAE_min, BinderTargetIPSAE, TargetBinderIPSAE (re-exported from mosaic)
  - LIS — Local Interaction Score (NEW, v5)
  - actifpTM — contact-weighted ipTM (NEW, v5)

Post-hoc scoring (used in validators/boltz2_consensus.py):
  - rmsd_binder — CA-RMSD designed vs predicted
  - shape_complementarity — PyRosetta SC
  - confide_score — stubbed (requires AF3 diffusion embeddings)

Consensus utilities:
  - predict_chai1, consensus_pae, consensus_gate
"""
