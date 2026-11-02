"""ipSAE + LIS loss module.

Re-exports existing ipSAE classes from the mosaic package (already in v4 at
weights 0.7 / 0.4 / 2.5 for BinderTargetIPSAE / TargetBinderIPSAE / IPSAE_min)
and adds the NEW v5 LIS loss class.

ipSAE is imported from Mosaic; credit the DunbrackLab/IPSAE implementation.
This campaign does not establish a general binder-success threshold.

LIS (Local Interaction Score; Kim et al., AFM-LIS):
    For binder->target residue pairs, weight each by contact_probability
    (from the distogram) and score by clip(1 - pae/pae_cutoff, 0, 1).
    Higher LIS = stronger local interaction confidence.

    This contact-probability-weighted adaptation is not the original AFM-LIS
    reference implementation. See CITATIONS.md for the source distinction.
    Implementation follows mosaic conventions: binder_len derived from
    sequence.shape[0], distogram_logits used for soft contact probability,
    output.pae used for the linear PAE-cutoff score."""

from dataclasses import dataclass

import jax
import jax.numpy as jnp

import mosaic.losses.structure_prediction as sp
from mosaic.losses.structure_prediction import (
    IPSAE_min,
    BinderTargetIPSAE,
    TargetBinderIPSAE,
)


@dataclass
class LIS(sp.LossTerm):
    """Local Interaction Score — distogram-weighted PAE score over binder->target pairs.

    Loss returned is NEGATIVE LIS (we minimize). aux dict reports the raw LIS.
    """

    distance_cutoff: float = 8.0
    pae_cutoff: float = 12.0

    def __call__(self, sequence, output, key):
        binder_len = sequence.shape[0]

        # Soft inter-chain contact probability from distogram (binder rows, target cols).
        # distogram_logits: (N, N, n_bins); distogram_bins: (n_bins,)
        log_dist = jax.nn.log_softmax(
            output.distogram_logits[:binder_len, binder_len:],
            axis=-1,
        )
        contact_bin_mask = output.distogram_bins < self.distance_cutoff
        log_contact_prob = jax.nn.logsumexp(log_dist, where=contact_bin_mask, axis=-1)
        contact_prob = jnp.exp(log_contact_prob)            # (binder_len, target_len)

        # Linear PAE-cutoff score per inter-chain pair.
        pae_bt = output.pae[:binder_len, binder_len:]       # (binder_len, target_len)
        lis_pair = jnp.clip(1.0 - pae_bt / self.pae_cutoff, 0.0, 1.0)

        # Weighted mean (protect against zero contacts)
        num = jnp.sum(contact_prob * lis_pair)
        den = jnp.sum(contact_prob) + 1e-6
        lis_score = num / den

        return -lis_score, {"lis": lis_score}


__all__ = [
    "IPSAE_min",
    "BinderTargetIPSAE",
    "TargetBinderIPSAE",
    "LIS",
]
