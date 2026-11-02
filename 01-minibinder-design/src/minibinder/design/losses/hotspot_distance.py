"""Hotspot-distance loss for V5 minibinder design.

Rewards binder residues being within `distance_threshold` Å of designated
hotspot positions on the target chain.  Uses a soft-min over binder residues
(log-sum-exp trick) so the loss is everywhere differentiable and JIT-safe.

Math:
    For each hotspot h (0-indexed within the target chain):
        d_vec[h] = expected distance from every binder residue to hotspot h
                   computed as Σ_b p_b · bin_b  (probability-weighted distogram)
        soft_min[h] = -temperature * logsumexp(-d_vec[h] / temperature)
    loss = max(0, mean(soft_min) - distance_threshold)

Lower loss is better (0 when all hotspots are within threshold).

Usage in V5 loss config (config/v5_default.yaml):
    - !HotspotDistance
      hotspots: [14, 22, 37]   # 0-indexed positions WITHIN the target chain
      distance_threshold: 8.0  # Å
      temperature: 1.0
      weight: 1.25             # recommended range: 1.0 – 1.5"""

from dataclasses import dataclass
from typing import Tuple

import jax
import jax.numpy as jnp

import mosaic.losses.structure_prediction as sp


@dataclass
class HotspotDistance(sp.LossTerm):
    """Differentiable hotspot-proximity loss over the binder→target distogram.

    Parameters
    ----------
    hotspots:
        0-indexed positions *within the target chain* (i.e. position 0 is the
        first target residue, not position ``binder_len`` in the concatenated
        sequence).  The class converts to global indices internally.
    distance_threshold:
        Ångström threshold.  Pairs whose soft-min distance is below this value
        contribute ~0 loss; pairs above it contribute the excess.
    temperature:
        Softness parameter for the soft-min over binder residues.
        Smaller values → harder min; larger values → softer.
        Recommended: 1.0 (matches typical binder-length scales).

    Use weight ~1.0–1.5 in V5's loss config.
    """

    hotspots: Tuple[int, ...] = ()
    distance_threshold: float = 8.0
    temperature: float = 1.0

    def __call__(self, sequence, output, key):
        """Compute hotspot-distance loss.

        Parameters
        ----------
        sequence : jnp.ndarray, shape (N,)
            Full (binder + target) one-hot or token sequence; binder_len is
            inferred as ``sequence.shape[0] - target_len`` where
            ``target_len = output.distogram_logits.shape[0] - sequence.shape[0]``
            — equivalently we use the standard Mosaic convention that
            ``binder_len = sequence.shape[0]`` because ``sequence`` contains
            ONLY the binder tokens (see design_v5.py / LIS reference).
        output : Protenix output namespace
            Must expose ``output.distogram_logits`` (N, N, n_bins) and
            ``output.distogram_bins`` (n_bins,).
        key : jax.random.PRNGKey
            Unused; kept for API compatibility with LossTerm.

        Returns
        -------
        (loss_scalar, {})
        """
        if len(self.hotspots) == 0:
            return jnp.array(0.0), {}

        # binder_len follows the same convention as LIS: sequence is binder-only.
        binder_len = sequence.shape[0]

        # Slice binder→target distogram block: (binder_len, target_len, n_bins)
        logits_bt = output.distogram_logits[:binder_len, binder_len:]   # (B, T, n_bins)

        # Soft probability over bins → expected distance per pair (B, T)
        probs = jax.nn.softmax(logits_bt, axis=-1)                      # (B, T, n_bins)
        bins = output.distogram_bins                                      # (n_bins,)
        expected_dist = jnp.sum(probs * bins[None, None, :], axis=-1)   # (B, T)

        # For each hotspot, compute soft-min over binder residues.
        T = self.temperature

        def soft_min_to_hotspot(h_local):
            """Soft-min distance from any binder residue to target position h_local."""
            d_vec = expected_dist[:, h_local]                           # (B,)
            return -T * jax.scipy.special.logsumexp(-d_vec / T)

        # Stack soft-mins across all hotspots, then take mean.
        hotspot_array = jnp.array(self.hotspots, dtype=jnp.int32)       # (H,)
        soft_mins = jax.vmap(soft_min_to_hotspot)(hotspot_array)        # (H,)
        mean_soft_min = jnp.mean(soft_mins)

        loss = jnp.maximum(jnp.array(0.0), mean_soft_min - self.distance_threshold)
        return loss, {}


__all__ = ["HotspotDistance"]
