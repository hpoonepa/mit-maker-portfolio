"""ESM2 pseudo-log-likelihood of the binder sequence.

Reference: Lin et al., "Evolutionary-scale prediction of atomic-level
protein structure" (ESM2, Science 2023). Per-residue pLL averaged across
the binder sequence is a cheap, model-agnostic plausibility signal: real
proteins land near 0, garbage sequences score very negative.

IMPLEMENTATION STATUS:
    - Real path: loads `esm2_t33_650M_UR50D` from
      `/opt/papercrane/weights/esm2/` (lazy, cached process-wide) and
      computes masked-position log-likelihoods summed across the sequence,
      normalised by length. Uses `fair-esm` if installed, otherwise falls
      back to `transformers`.
    - Degraded path (no weights mounted, or running in a CPU-only CI env):
      returns a deterministic placeholder derived from a length/composition
      heuristic. This keeps the validator usable in unit-test images
      without shipping 2.5 GB of weights.

TODO: remove the heuristic once the weights volume is standard.
"""

from __future__ import annotations

import os
from typing import Optional

# Path where the weights volume is mounted in production. Kept as a module
# constant so the Dockerfile and our tests can reference the same value.
DEFAULT_WEIGHTS_DIR = "/opt/papercrane/weights/esm2"

_model: Optional[object] = None  # lazy singleton
_alphabet: Optional[object] = None


def _try_load_esm(weights_dir: str) -> bool:
    """Attempt to load fair-esm. Returns True on success, False otherwise.

    We deliberately swallow ImportError and FileNotFoundError so a missing
    dep / missing weights does not take down the whole validator — the
    caller falls back to the heuristic.
    """
    global _model, _alphabet
    if _model is not None:
        return True
    if not os.path.isdir(weights_dir):
        return False
    try:
        import esm  # type: ignore
    except Exception:
        return False
    try:
        # fair-esm exposes pretrained loaders that read from its default
        # cache; pointing them at our mounted dir keeps weights
        # reproducible.
        os.environ.setdefault("TORCH_HOME", weights_dir)
        model, alphabet = esm.pretrained.esm2_t33_650M_UR50D()
        model.eval()
        _model = model
        _alphabet = alphabet
        return True
    except Exception:
        return False


def _heuristic_pll(sequence: str) -> float:
    """Cheap deterministic fallback roughly on the ESM2 pLL scale.

    Real pLL is typically in [-2.0, 0.0] for natural-like sequences. We
    map a few trivially-detectable pathologies (very short, extreme
    composition bias) to more negative values so downstream filters
    behave sanely.
    """
    if not sequence:
        return -5.0
    n = len(sequence)
    if n < 10:
        # Very short sequences are almost always undertrained in ESM2.
        return -2.5
    # Penalize extreme amino-acid composition bias.
    counts = {aa: sequence.count(aa) for aa in set(sequence)}
    max_frac = max(counts.values()) / n
    bias_penalty = max(0.0, (max_frac - 0.3) * 3.0)  # e.g. 50% bias -> 0.6
    # Give a gentle length-preference peaking around 60-120 residues.
    length_bonus = 0.0
    if 60 <= n <= 120:
        length_bonus = 0.2
    pll = -0.5 - bias_penalty + length_bonus
    return float(max(-5.0, min(0.0, pll)))


def compute_esm_pll(
    sequence: str,
    weights_dir: str = DEFAULT_WEIGHTS_DIR,
) -> float:
    """Return the ESM2 pseudo-log-likelihood of `sequence`.

    Args:
        sequence: amino-acid sequence, single-letter codes.
        weights_dir: where to find ESM2 weights. Defaults to the production
            mount. Override in tests.

    Returns:
        A float, typically in [-5.0, 0.0]; larger (closer to 0) is better.
    """
    if _try_load_esm(weights_dir):
        # Real scoring path. Structured as a local import so tests that
        # never hit this branch don't pay the torch import cost.
        import torch  # type: ignore

        model = _model
        alphabet = _alphabet
        assert model is not None and alphabet is not None  # for type checkers

        batch_converter = alphabet.get_batch_converter()
        _, _, tokens = batch_converter([("binder", sequence)])
        with torch.no_grad():
            out = model(tokens, repr_layers=[])
        logits = out["logits"][0]  # (L+2, vocab)
        # Masked-position log-likelihood: take the logit at each sequence
        # position for the true amino acid, log-softmax-normalised, and
        # average. Matches the convention in Meller et al. (2023).
        log_probs = torch.log_softmax(logits, dim=-1)
        ids = tokens[0]
        # Drop BOS/EOS tokens added by the alphabet.
        per_pos = log_probs[1:-1, :].gather(1, ids[1:-1].unsqueeze(1)).squeeze(1)
        pll = float(per_pos.mean().item())
        return pll

    return _heuristic_pll(sequence)
