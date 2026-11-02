"""ESMFold wrapper — the EXPRESSION axis of the tri-objective.

WHY ESMFOLD IS HERE AND WHAT IT IS FOR
--------------------------------------
Derived 2026-09-21 from the two Adaptyv BLI packages (35 designs, 19 loaded,
16 produced zero curves, 1 bound) joined to 5G51_FINAL_20_DOCUMENTED.csv:

    predictor              vs EXPRESSION (loaded onto sensor)
    esmfold2 ipTM          AUC 0.653   p 0.32
    solublempnn delta      AUC 0.725   p 0.12
    solublempnn raw        AUC 0.463   p 0.83   <- noise
    protenix ipTM          AUC 0.500   p 1.00   <- ZERO expression signal

Protenix and Boltz2 are MSA/structure models: they tell you whether the
interface is real. ESMFold is a pure language model with no MSA, so its
confidence tracks how "natural" and self-foldable a sequence is on its own —
which is why it is the only one of the three that carries expression signal.

Use it for the expression axis. Do NOT use it as a binding discriminator; on
this panel it ranked the one true binder 2nd, but Protenix ranked it 1st and
the two are measuring different things.

CAVEAT: nothing above reaches p<0.05. n=17-18 with a 10/10 split has roughly
30% power for AUC 0.70. This is the best available signal, not a validated one.

CONTRACT
--------
Returns the same dict shape as predict_chai1() / _run_boltz2() so it drops into
validators/tri_consensus.py without special-casing.
"""

from typing import Dict, Optional
import os

import numpy as np

__all__ = [
    "load_esmfold",
    "predict_esmfold",
    "esmfold_binder_quality",
    "CHAIN_LINKER_LEN",
]

# ESMFold represents a chain break by jumping the residue index. 25 is the
# value used by the reference implementation; keep it in sync if esm changes.
CHAIN_LINKER_LEN = 25

_ESMFOLD_MODEL = None


def load_esmfold(chunk_size: Optional[int] = 128, device: str = "cuda"):
    """Load ESMFold v1 (lazy singleton, ~2.6 GB of weights).

    chunk_size trades speed for memory; 128 keeps a ~300-residue complex inside
    a 24 GB card. Set None to disable chunking (fastest, most memory).
    """
    global _ESMFOLD_MODEL
    if _ESMFOLD_MODEL is not None:
        return _ESMFOLD_MODEL
    try:
        import torch
        import esm
    except ImportError as e:
        raise ImportError(
            "ESMFold needs fair-esm and torch:\n"
            "  uv add 'fair-esm[esmfold]' torch\n"
            "  # plus openfold deps; see runpod/Dockerfile which pins a working set"
        ) from e

    model = esm.pretrained.esmfold_v1()
    model = model.eval()
    if device == "cuda" and torch.cuda.is_available():
        model = model.cuda()
    if chunk_size is not None:
        model.set_chunk_size(chunk_size)
    _ESMFOLD_MODEL = model
    return model


def _target_sequence(target_cif: str) -> str:
    import gemmi
    st = gemmi.read_structure(target_cif)
    st.setup_entities()
    st.remove_ligands_and_waters()
    return gemmi.one_letter_code([r.name for r in st[0][0]]).upper()


def _interface_mask(n_total: int, binder_len: int) -> np.ndarray:
    m = np.zeros((n_total, n_total), dtype=bool)
    m[:binder_len, binder_len:] = True
    m[binder_len:, :binder_len] = True
    return m


def predict_esmfold(
    sequence: str,
    target_cif: str,
    model=None,
    num_recycles: int = 3,
    device: str = "cuda",
) -> Dict:
    """Fold binder + target as a two-chain complex.

    ESMFold encodes the chain break with a residue-index jump (the ':' separator
    in infer()), NOT a physical linker, so no glycine spacer is added and the
    returned PAE has no linker rows to strip.

    Returns:
        pae                   (N, N) float
        plddt                 (N,)   float, 0-1
        iptm                  float, interface pTM recomputed from PAE
        binder_plddt          float, mean pLDDT over binder residues ONLY
                              (this is the expression-axis number)
        ptm                   float, global pTM as reported by ESMFold
        structure_coordinates (N, 3) CA coords
        chain_ids             (N,)   0 = binder, 1 = target
        binder_length         int
    """
    import torch

    m = model or load_esmfold(device=device)
    target_seq = _target_sequence(target_cif)
    binder_len = len(sequence)
    n_total = binder_len + len(target_seq)

    with torch.no_grad():
        out = m.infer([f"{sequence}:{target_seq}"], num_recycles=num_recycles)

    def _np(x):
        return x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)

    plddt = _np(out["plddt"])[0]
    # esm returns per-atom pLDDT (L, 37) in some versions; collapse to per-residue CA
    if plddt.ndim == 2:
        plddt = plddt[:, 1]
    plddt = np.asarray(plddt, dtype=np.float64)
    if plddt.max() > 1.5:                      # some builds report 0-100
        plddt = plddt / 100.0

    pae = np.asarray(_np(out["predicted_aligned_error"])[0], dtype=np.float64)
    ptm = float(_np(out["ptm"]))

    positions = _np(out["positions"])
    # positions: (recycles, batch, L, 37, 3) or (batch, L, 37, 3)
    while positions.ndim > 4:
        positions = positions[-1]
    coords = np.asarray(positions[0][:, 1, :], dtype=np.float64)   # CA

    if pae.shape[0] != n_total:
        raise RuntimeError(
            f"ESMFold returned a {pae.shape[0]}-residue PAE for a {n_total}-residue "
            f"complex ({binder_len} binder + {len(target_seq)} target). The ':' "
            f"chain separator may not be supported by this esm build."
        )

    iptm = _iptm_from_pae(pae, binder_len)
    chain_ids = np.concatenate([np.zeros(binder_len, np.int32),
                                np.ones(n_total - binder_len, np.int32)])

    return {
        "pae": pae,
        "plddt": plddt,
        "iptm": iptm,
        "ptm": ptm,
        "binder_plddt": float(plddt[:binder_len].mean()),
        "structure_coordinates": coords,
        "chain_ids": chain_ids,
        "binder_length": binder_len,
    }


def _iptm_from_pae(pae: np.ndarray, binder_len: int, d0: float = 31.8) -> float:
    """Interface pTM from a PAE matrix — same transform validators/ uses."""
    ptm_pair = 1.0 / (1.0 + (pae / d0) ** 2)
    mask = _interface_mask(pae.shape[0], binder_len)
    return float(ptm_pair[mask].mean())


def esmfold_binder_quality(
    sequence: str,
    model=None,
    num_recycles: int = 3,
    device: str = "cuda",
) -> Dict[str, float]:
    """Fold the binder ALONE — the cleanest expression signal available.

    A binder that will not fold by itself will not survive translation and
    purification, whatever its complex ipTM says. Cheap: no target, one chain.

    Returns: {binder_plddt, ptm, frac_confident}
      frac_confident = fraction of residues with pLDDT > 0.70, which catches a
      design that folds a confident core and leaves a disordered tail — the mean
      alone hides that.
    """
    import torch
    m = model or load_esmfold(device=device)
    with torch.no_grad():
        out = m.infer([sequence], num_recycles=num_recycles)

    def _np(x):
        return x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)

    plddt = _np(out["plddt"])[0]
    if plddt.ndim == 2:
        plddt = plddt[:, 1]
    plddt = np.asarray(plddt, dtype=np.float64)
    if plddt.max() > 1.5:
        plddt = plddt / 100.0
    return {
        "binder_plddt": float(plddt.mean()),
        "ptm": float(_np(out["ptm"])),
        "frac_confident": float((plddt > 0.70).mean()),
    }


# ---------------------------------------------------------------------------
# Subprocess bridge — keeps PyTorch out of the JAX environment
# ---------------------------------------------------------------------------
# mosaic pins jax==0.9.1 (jax 0.10 removed ShapeDtypeStruct.vma, which breaks
# unpickling the protenix weights). ESMFold is PyTorch and drags in its own
# CUDA/cuDNN stack. Installing both in one venv is how you silently break
# ProtenixV2 weeks later.
#
# So on RunPod, ESMFold lives in its own venv and we shell out to it. Set
#     MOSAIC_ESMFOLD_PYTHON=/opt/esmfold/.venv/bin/python
# and predict_esmfold_auto() routes through the worker instead of importing
# torch in-process. Unset, it imports directly (fine on a single-stack box).

ESMFOLD_PYTHON_ENV = "MOSAIC_ESMFOLD_PYTHON"
_WORKER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "runpod", "esmfold_worker.py")


def _run_worker(sequence: str, target_cif: Optional[str], mode: str) -> Dict:
    import json as _json
    import subprocess
    py = os.environ[ESMFOLD_PYTHON_ENV]
    if not os.path.exists(_WORKER):
        raise FileNotFoundError(f"esmfold worker not found at {_WORKER}")
    cmd = [py, _WORKER, "--mode", mode, "--sequence", sequence]
    if target_cif:
        cmd += ["--target-cif", target_cif]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"esmfold worker failed (exit {p.returncode}).\n"
            f"stderr tail:\n{p.stderr[-1500:]}")
    try:
        return _json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:
        raise RuntimeError(f"esmfold worker returned unparseable output: {e}\n"
                           f"stdout tail:\n{p.stdout[-800:]}") from e


def predict_esmfold_auto(sequence: str, target_cif: str, model=None, **kw) -> Dict:
    """predict_esmfold, routed through the worker venv when one is configured."""
    if os.environ.get(ESMFOLD_PYTHON_ENV):
        d = _run_worker(sequence, target_cif, "complex")
        d["pae"] = np.asarray(d["pae"]) if d.get("pae") is not None else None
        return d
    return predict_esmfold(sequence, target_cif, model=model, **kw)


def esmfold_binder_quality_auto(sequence: str, model=None, **kw) -> Dict[str, float]:
    """esmfold_binder_quality, routed through the worker venv when configured."""
    if os.environ.get(ESMFOLD_PYTHON_ENV):
        return _run_worker(sequence, None, "solo")
    return esmfold_binder_quality(sequence, model=model, **kw)
