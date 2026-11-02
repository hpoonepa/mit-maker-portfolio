"""Weight interface confidence by predicted residue-contact probabilities.

Source: Bioinformatics 2025, doi.org/10.1093/bioinformatics/btaf107
ColabFold exposes it via `--calc_extra_ptm`.
This local JAX objective adapts the contact-weighting idea; numerical parity
with the published ColabFold metric has not been established.

Fixes ipTM suppression by flexible tails/loops by weighting each inter-chain
residue pair by its contact probability — only confident interface residues
contribute. Particularly valuable when designing binders with flexible termini
(common in RFdiffusion outputs).

Math (matches mosaic differentiable conventions):
    contact_prob(i,j) = exp(logsumexp(log_softmax(distogram_logits)[i,j,b]
                              for bins b with center < contact_threshold))
    g(b)              = 1 / (1 + (pae_bin_center[b] / d0)^2)
    ptm_pair(i,j)     = sum_b softmax(pae_logits)[i,j,b] * g(b)
    actifpTM          = mean over (binder, target) pairs weighted by contact_prob

d0 follows the same dynamic formula as upstream pTMEnergy:
    d0 = 1.24 * (clip(N, min=19) - 15)^(1/3) - 1.8

Loss returned is NEGATIVE actifpTM."""

from dataclasses import dataclass

import jax
import jax.numpy as jnp

import mosaic.losses.structure_prediction as sp


@dataclass
class actifpTM(sp.LossTerm):
    """Contact-probability-weighted ipTM (PAE-logit native, fully differentiable)."""

    contact_threshold_angstrom: float = 8.0

    def __call__(self, sequence, output, key):
        binder_len = sequence.shape[0]
        n_res = output.pae_logits.shape[0]

        # Soft contact probability from distogram (binder rows, target cols).
        log_dist = jax.nn.log_softmax(
            output.distogram_logits[:binder_len, binder_len:],
            axis=-1,
        )
        contact_bin_mask = output.distogram_bins < self.contact_threshold_angstrom
        log_contact_prob = jax.nn.logsumexp(log_dist, where=contact_bin_mask, axis=-1)
        contact_prob = jnp.exp(log_contact_prob)              # (bl, tl)

        # Differentiable per-pair pTM score from pae_logits (matches upstream pTMEnergy).
        clipped_n = max(n_res, 19)
        d0 = 1.24 * (clipped_n - 15) ** (1.0 / 3) - 1.8
        g_per_bin = 1.0 / (1.0 + (output.pae_bins / d0) ** 2)  # (n_bins,)

        pae_log_softmax = jax.nn.log_softmax(
            output.pae_logits[:binder_len, binder_len:],
            axis=-1,
        )
        # ptm_pair[i,j] = sum_b exp(log_softmax) * g(b)
        ptm_pair = jnp.sum(jnp.exp(pae_log_softmax) * g_per_bin[None, None, :], axis=-1)

        num = jnp.sum(contact_prob * ptm_pair)
        den = jnp.sum(contact_prob) + 1e-6
        actifptm_score = num / den

        return -actifptm_score, {"actifptm": actifptm_score}


__all__ = ["actifpTM"]
