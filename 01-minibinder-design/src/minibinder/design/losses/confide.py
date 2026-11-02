"""Compute the CONFIDE score from AlphaFold 3 diffusion embeddings.

Source: arxiv 2512.02033
This is an unimplemented local placeholder, not the paper authors' code.
The paper's CODE/CONFIDE results do not validate this function or its sketch.

STATUS: STUBBED. Protenix (used by Mosaic v4/v5) does not expose diffusion
timestep hidden states in its output dict — only final coords, pLDDT, pTM/ipTM,
and PAE. Full implementation requires model surgery: hooking into Protenix's
denoising trunk to capture per-timestep hidden states as an `output.embeddings`
field of shape (n_timesteps, N_residues, hidden_dim).

Reference implementation (for future v6):
    variance_per_residue = embeddings.var(axis=0).mean(axis=-1)  # (N,)
    mean_magnitude = abs(embeddings.mean(axis=0)).mean(axis=-1)  # (N,)
    frustration = variance_per_residue / (mean_magnitude + 1e-6)
    confide = frustration[binder_mask].mean()  # higher = more hallucinated

TODO: Revisit when either
  (a) Protenix upstream adds an `output_trajectory=True` flag, OR
  (b) Mosaic migrates to a predictor that exposes hidden states (direct AF3
      via Isomorphic API, or Boltz-2 full checkpoint with return_hidden_states).

Post-hoc scoring only — NOT a JAX loss term."""

__all__ = ["confide_score"]


def confide_score(model_output, binder_mask) -> float:
    """Topological frustration score from diffusion embeddings.

    Higher values indicate hallucinated/unstable folds.
    """
    raise NotImplementedError(
        "CONFIDE requires AF3 diffusion embeddings not exposed by Protenix. "
        "See arxiv 2512.02033. Planned for v6 with predictor model surgery."
    )
