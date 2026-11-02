"""Tri-objective validator: Protenix (multi-seed) + Boltz2 + ESMFold.

Replaces the ipSAE-gated consensus in validators/boltz2_consensus.py. On the
35-design VP3 ground truth, min_ipSAE ranked the one real binder 10th of 20;
Protenix ipTM ranked it 1st, Protenix seed spread 1st (lowest), ESMFold 2nd.
See src/tri_objective.py for the full derivation.

What each predictor contributes:
    Protenix  multi-seed ipTM  -> mean (binding) AND spread (confidence)
    Boltz2    best-of-N ipTM   -> independent binding cross-check
    ESMFold   complex ipTM + binder-alone pLDDT -> EXPRESSION axis

CLI:
    python validators/tri_consensus.py --sequences designs.fasta \
        --target-cif 5G51.cif --out tri_scores.csv [--protenix-seeds 5] \
        [--skip-boltz2] [--skip-esmfold]

Every predictor degrades gracefully: if one is unavailable the others still
run, the axis is computed from what is present, and the absence is recorded as
a gate failure rather than silently passing.
"""

import argparse, csv, json, os, sys, time, traceback
from typing import Dict, List, Optional

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.tri_objective import (
    score_design, aggregate_protenix_seeds, rank_designs, Thresholds, TriScore,
)

__all__ = ["run_protenix_seeds", "run_boltz2", "run_esmfold", "validate_all"]


def _read_fasta(path: str) -> List[Dict[str, str]]:
    out, name, buf = [], None, []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                if name:
                    out.append({"name": name, "sequence": "".join(buf)})
                name, buf = line[1:].split()[0], []
            elif line:
                buf.append(line.upper())
    if name:
        out.append({"name": name, "sequence": "".join(buf)})
    if not out:
        raise SystemExit(f"FATAL: no sequences parsed from {path}")
    return out


def _read_inputs(path: str) -> List[Dict[str, str]]:
    if path.lower().endswith((".fasta", ".fa", ".faa")):
        return _read_fasta(path)
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    keys = {k.lower(): k for k in (rows[0] if rows else {})}
    nk = keys.get("name") or keys.get("candidate_id") or keys.get("id")
    sk = keys.get("sequence") or keys.get("seq")
    if not (nk and sk):
        raise SystemExit(f"FATAL: {path} needs name+sequence columns; saw {list(keys)}")
    return [{"name": r[nk].strip(), "sequence": r[sk].strip().upper()} for r in rows if r.get(sk)]


def _target_sequence(target_cif: str):
    import gemmi
    st = gemmi.read_structure(target_cif)
    st.setup_entities()
    st.remove_ligands_and_waters()
    return st, "".join(gemmi.one_letter_code([r.name for r in st[0][0]])).upper()


def _onehot(sequence: str) -> "np.ndarray":
    from mosaic.common import TOKENS
    idx = {a: i for i, a in enumerate(TOKENS)}
    m = np.zeros((len(sequence), len(TOKENS)), dtype=np.float32)
    for i, a in enumerate(sequence):
        if a not in idx:
            raise ValueError(f"residue {a!r} at position {i} is not in TOKENS")
        m[i, idx[a]] = 1.0
    return m


def run_protenix_seeds(sequence: str, target_cif: str, n_seeds: int = 5,
                       recycling_steps: int = 4) -> Dict[str, float]:
    """Fold the complex under n_seeds random seeds.

    The SPREAD is the point. A design whose predicted complex moves between
    seeds is one the model is not actually confident about, whatever its mean
    ipTM says — the one design that bound had a spread of 0.0006, the lowest
    of 17. Needs >=2 seeds or the spread is undefined.
    """
    import jax
    import jax.numpy as jnp
    from mosaic.models.protenix import ProtenixV2
    from mosaic.structure_prediction import TargetChain

    st, target_seq = _target_sequence(target_cif)
    protenix = ProtenixV2()
    features, writer = protenix.binder_features(
        binder_length=len(sequence),
        chains=[TargetChain(target_seq, use_msa=True, template_chain=st[0][0])],
    )
    pssm = jnp.asarray(_onehot(sequence))

    iptms, plddts = [], []
    for i in range(n_seeds):
        pred = protenix.predict(PSSM=pssm, features=features,
                                recycling_steps=recycling_steps,
                                key=jax.random.key(1000 + i), writer=writer)
        iptms.append(float(pred.iptm))
        plddts.append(float(np.asarray(pred.plddt)[:len(sequence)].mean()))
        print(f"    protenix seed {i+1}/{n_seeds}: ipTM={iptms[-1]:.4f}", flush=True)

    agg = aggregate_protenix_seeds(iptms)
    agg["protenix_binder_plddt"] = float(np.mean(plddts))
    agg["protenix_iptms"] = iptms
    return agg


def run_boltz2(sequence: str, target_cif: str, seed: int = 0,
               num_samples: int = 3) -> Dict[str, float]:
    """Boltz2 best-of-N — independent binding cross-check."""
    import jax, jax.numpy as jnp
    from mosaic.models.boltz2 import Boltz2
    from mosaic.structure_prediction import TargetChain
    from mosaic.losses.structure_prediction import IPTMLoss, IPSAE_min

    st, target_seq = _target_sequence(target_cif)
    features, _writer = Boltz2.target_only_features([
        TargetChain(sequence, use_msa=True),
        TargetChain(target_seq, use_msa=True, template_chain=st[0][0]),
    ])
    dummy = jnp.zeros((len(sequence), 20))
    mkey = jax.random.key(0)
    best, best_iptm = None, -1.0
    for i in range(num_samples):
        out = Boltz2().model_output(PSSM=None, features=features,
                                    recycling_steps=8,
                                    key=jax.random.fold_in(jax.random.key(seed), i))
        _, aux = IPTMLoss()(dummy, out, key=mkey)
        v = float(aux["iptm"])
        print(f"    boltz2 sample {i+1}/{num_samples}: ipTM={v:.4f}", flush=True)
        if v > best_iptm:
            best_iptm, best = v, out
    _, a_min = IPSAE_min()(dummy, best, key=mkey)
    return {"boltz2_iptm": best_iptm,
            "ipsae_min": float(a_min["ipsae_min"]),
            "boltz2_binder_plddt": float(np.asarray(best.plddt)[:len(sequence)].mean())}


def run_esmfold(sequence: str, target_cif: str, model=None) -> Dict[str, float]:
    """ESMFold — the expression axis. Complex ipTM plus binder-alone pLDDT."""
    from src.losses.esmfold_score import (predict_esmfold_auto, esmfold_binder_quality_auto,
                                          load_esmfold, ESMFOLD_PYTHON_ENV)
    m = model  # None when the worker venv is doing the folding
    cx = predict_esmfold_auto(sequence, target_cif, model=m)
    solo = esmfold_binder_quality_auto(sequence, model=m)
    return {"esmfold_iptm": cx["iptm"],
            "esmfold_complex_binder_plddt": cx["binder_plddt"],
            "esmfold_binder_plddt": solo["binder_plddt"],
            "esmfold_frac_confident": solo["frac_confident"],
            "esmfold_ptm": solo["ptm"]}


def validate_all(designs: List[Dict[str, str]], target_cif: str,
                 protenix_seeds: int = 5, boltz2_samples: int = 3,
                 skip_protenix: bool = False, skip_boltz2: bool = False,
                 skip_esmfold: bool = False,
                 thresholds: Optional[Thresholds] = None) -> List[TriScore]:
    esm_model = None
    if not skip_esmfold:
        try:
            import os as _os
            from src.losses.esmfold_score import load_esmfold, ESMFOLD_PYTHON_ENV
            if _os.environ.get(ESMFOLD_PYTHON_ENV):
                print(f"  ESMFold: using worker venv {_os.environ[ESMFOLD_PYTHON_ENV]}")
                esm_model = None                # worker loads it per call
            else:
                esm_model = load_esmfold()      # load once, reuse across designs
        except Exception as e:
            print(f"WARNING: ESMFold unavailable ({e}); expression axis disabled.")
            skip_esmfold = True

    out = []
    for n, d in enumerate(designs, 1):
        name, seq = d["name"], d["sequence"]
        print(f"\n[{n}/{len(designs)}] {name}  ({len(seq)} aa)", flush=True)
        met: Dict[str, float] = {}
        t0 = time.time()
        for label, skip, fn in (
            ("protenix", skip_protenix,
             lambda: run_protenix_seeds(seq, target_cif, protenix_seeds)),
            ("boltz2", skip_boltz2,
             lambda: run_boltz2(seq, target_cif, num_samples=boltz2_samples)),
            ("esmfold", skip_esmfold,
             lambda: run_esmfold(seq, target_cif, model=esm_model)),
        ):
            if skip:
                print(f"  {label}: skipped"); continue
            try:
                met.update(fn())
            except Exception as e:
                print(f"  {label} FAILED: {e}")
                traceback.print_exc(limit=2)

        s = score_design(
            name=name,
            protenix_iptm=met.get("protenix_iptm"),
            protenix_spread=met.get("protenix_spread"),
            boltz2_iptm=met.get("boltz2_iptm"),
            esmfold_iptm=met.get("esmfold_iptm"),
            esmfold_binder_plddt=met.get("esmfold_binder_plddt"),
            ipsae_min=met.get("ipsae_min"),
            thresholds=thresholds,
        )
        s.metrics.update(met)
        s.metrics["sequence"] = seq
        s.metrics["length"] = len(seq)
        print(f"  -> composite={s.composite:.3f} bind={s.bind:.3f} "
              f"express={s.express:.3f} {'PASS' if s.passes else 'fail'} "
              f"({time.time()-t0:.0f}s)")
        if not s.passes:
            print(f"     gates: {'; '.join(s.gates_failed)}")
        out.append(s)
    return rank_designs(out)


def _write(scores: List[TriScore], path: str):
    cols = ["rank", "name", "composite", "bind", "express", "passes",
            "protenix_iptm", "protenix_spread", "protenix_iptm_min", "n_seeds",
            "boltz2_iptm", "ipsae_min", "esmfold_iptm", "esmfold_binder_plddt",
            "esmfold_frac_confident", "length", "gates_failed", "sequence"]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for i, s in enumerate(scores, 1):
            r = s.as_row()
            row = [i]
            for c in cols[1:]:
                v = r.get(c, s.metrics.get(c, ""))
                if isinstance(v, float):
                    v = "" if v != v else f"{v:.4f}"
                row.append(v)
            w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sequences", required=True, help="FASTA or CSV (name,sequence)")
    ap.add_argument("--target-cif", required=True)
    ap.add_argument("--out", default="tri_scores.csv")
    ap.add_argument("--protenix-seeds", type=int, default=5,
                    help=">=2 required for a defined seed spread")
    ap.add_argument("--boltz2-samples", type=int, default=3)
    ap.add_argument("--skip-protenix", action="store_true")
    ap.add_argument("--skip-boltz2", action="store_true")
    ap.add_argument("--skip-esmfold", action="store_true")
    a = ap.parse_args()

    if a.protenix_seeds < 2 and not a.skip_protenix:
        print("WARNING: --protenix-seeds < 2 leaves the seed spread undefined, "
              "which forfeits the strongest single discriminator in this panel.")
    if not os.path.exists(a.target_cif):
        raise SystemExit(f"FATAL: target not found: {a.target_cif}")

    designs = _read_inputs(a.sequences)
    print(f"{len(designs)} designs | target {a.target_cif} | "
          f"protenix x{a.protenix_seeds}, boltz2 x{a.boltz2_samples}")
    scores = validate_all(designs, a.target_cif, a.protenix_seeds, a.boltz2_samples,
                          a.skip_protenix, a.skip_boltz2, a.skip_esmfold)
    _write(scores, a.out)

    npass = sum(1 for s in scores if s.passes)
    print(f"\n{'='*78}\n{len(scores)} scored, {npass} pass all gates -> {a.out}\n{'='*78}")
    print(f"{'#':>3} {'design':<28}{'comp':>7}{'bind':>7}{'expr':>7}  gate")
    for i, s in enumerate(scores[:25], 1):
        f = lambda v: "  --  " if v != v else f"{v:6.3f}"
        print(f"{i:>3} {s.name[:27]:<28}{f(s.composite)}{f(s.bind)}{f(s.express)}  "
              f"{'PASS' if s.passes else 'fail'}")
    json.dump([s.as_row() for s in scores],
              open(os.path.splitext(a.out)[0] + ".json", "w"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
