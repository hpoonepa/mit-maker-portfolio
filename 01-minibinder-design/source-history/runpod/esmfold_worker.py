#!/usr/bin/env python3
"""Standalone ESMFold worker — runs inside /opt/esmfold/.venv, prints JSON.

Exists so PyTorch never enters the JAX venv. mosaic pins jax==0.9.1 because
jax 0.10 removed ShapeDtypeStruct.vma and breaks unpickling the protenix
weights; ESMFold drags in its own torch + CUDA stack. One venv for both is how
ProtenixV2 silently dies three weeks later.

Called by src/losses/esmfold_score.py when MOSAIC_ESMFOLD_PYTHON is set.
Emits exactly one JSON object on the LAST line of stdout.
"""
import argparse, json, sys

import numpy as np


def _plddt(out):
    p = out["plddt"]
    p = p.detach().cpu().numpy() if hasattr(p, "detach") else np.asarray(p)
    p = p[0]
    if p.ndim == 2:
        p = p[:, 1]                       # per-atom -> CA
    p = np.asarray(p, dtype=np.float64)
    return p / 100.0 if p.max() > 1.5 else p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["complex", "solo"], required=True)
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--target-cif")
    ap.add_argument("--num-recycles", type=int, default=3)
    ap.add_argument("--chunk-size", type=int, default=128)
    a = ap.parse_args()

    import torch, esm
    model = esm.pretrained.esmfold_v1().eval()
    if torch.cuda.is_available():
        model = model.cuda()
    if a.chunk_size:
        model.set_chunk_size(a.chunk_size)

    if a.mode == "solo":
        with torch.no_grad():
            out = model.infer([a.sequence], num_recycles=a.num_recycles)
        p = _plddt(out)
        res = {"binder_plddt": float(p.mean()),
               "ptm": float(out["ptm"].detach().cpu().numpy()),
               "frac_confident": float((p > 0.70).mean())}
    else:
        if not a.target_cif:
            print("--target-cif required for --mode complex", file=sys.stderr)
            return 2
        import gemmi
        st = gemmi.read_structure(a.target_cif)
        st.setup_entities(); st.remove_ligands_and_waters()
        tgt = "".join(gemmi.one_letter_code([r.name for r in st[0][0]])).upper()
        bl, n_total = len(a.sequence), len(a.sequence) + len(tgt)
        with torch.no_grad():
            out = model.infer([f"{a.sequence}:{tgt}"], num_recycles=a.num_recycles)
        p = _plddt(out)
        pae = np.asarray(out["predicted_aligned_error"].detach().cpu().numpy()[0],
                         dtype=np.float64)
        if pae.shape[0] != n_total:
            print(f"ESMFold returned {pae.shape[0]} residues, expected {n_total}; "
                  f"the ':' chain separator may be unsupported in this esm build.",
                  file=sys.stderr)
            return 3
        d0 = 31.8
        ptm_pair = 1.0 / (1.0 + (pae / d0) ** 2)
        mask = np.zeros_like(pae, dtype=bool)
        mask[:bl, bl:] = True; mask[bl:, :bl] = True
        res = {"iptm": float(ptm_pair[mask].mean()),
               "ptm": float(out["ptm"].detach().cpu().numpy()),
               "binder_plddt": float(p[:bl].mean()),
               "binder_length": bl,
               "pae": None}        # full PAE omitted: megabytes through a pipe
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
