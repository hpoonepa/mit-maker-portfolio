#!/usr/bin/env python
"""Mosaic binder design against 5G51 (DWV VP3 P-domain), two epitope groups.

Runs as a SUBPROCESS under `uv run` inside the cloned mosaic repo, so that
[tool.uv.sources] is honoured. Never import this from a Colab kernel.

Every design is written to disk the moment it finishes, so an interrupted run
loses at most one design. Re-running resumes from what is already on disk.
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

import gemmi
import jax
import jax.numpy as jnp
import numpy as np

import mosaic.losses.structure_prediction as sp
from mosaic.common import TOKENS
from mosaic.losses.protein_mpnn import InverseFoldingSequenceRecovery
from mosaic.losses.transformations import NoCys
from mosaic.optimizers import simplex_APGM
from mosaic.proteinmpnn.mpnn import load_mpnn_sol
from mosaic.structure_prediction import TargetChain

# 5G51 chain A spans PDB residues 260-416, so index = PDB number - 260.
PDB_OFFSET = 260
GROUPS = {
    "A_ridge": [325, 326, 384, 386],   # Q325 P326 V384 N386
    "B_triad": [277, 294],             # H277 D294
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def atomic_write(path: Path, text: str) -> None:
    """Write via temp file + fsync + rename so a crash never leaves a partial file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def load_target(pdb_path: Path):
    st = gemmi.read_structure(str(pdb_path))
    st.remove_ligands_and_waters()
    chain = st[0][0]
    seq = gemmi.one_letter_code([r.name for r in chain])
    return seq, chain


def build_model(name: str):
    if name == "protenix_v2":
        from mosaic.models.protenix import ProtenixV2
        return ProtenixV2(), "multisample"
    if name == "protenix_2025":
        from mosaic.models.protenix import Protenix2025
        return Protenix2025(), "multisample"
    if name == "boltz2":
        # Boltz2 is a CLASS, not a function - capital B.
        from mosaic.models.boltz2 import Boltz2
        return Boltz2(), "single"
    raise SystemExit(f"unknown model {name!r}")


def build_loss(model, mode, features, epitope_idx, mpnn, recycling_steps,
               sampling_steps, no_cys):
    """Author-tuned Protenix recipe (examples/protenij.py) + epitope targeting + solubility.

    Weights are copied verbatim from the authors' own example - do not retune blind.
    The only addition is `epitope_idx`, which aims BinderTargetContact at our hotspots.
    Solubility comes from soluble-ProteinMPNN inverse-folding recovery (weight 10.0),
    which pushes sequences toward the regime soluble MPNN was trained on.
    """
    structure_loss = (
        1.0 * sp.BinderTargetContact(epitope_idx=epitope_idx)
        + 1.0 * sp.WithinBinderContact()
        + 0.05 * sp.TargetBinderPAE()
        + 0.05 * sp.BinderTargetPAE()
        + 0.025 * sp.IPTMLoss()
        + 0.4 * sp.WithinBinderPAE()
        + 0.025 * sp.pTMEnergy()
        + 0.1 * sp.PLDDTLoss()
        + 10.0 * InverseFoldingSequenceRecovery(mpnn, temp=jnp.array(0.001))
    )
    if mode == "multisample":
        loss = model.build_multisample_loss(
            loss=structure_loss,
            features=features,
            recycling_steps=recycling_steps,
            sampling_steps=sampling_steps,
        )
    else:
        loss = model.build_loss(
            loss=structure_loss,
            features=features,
            recycling_steps=recycling_steps,
            sampling_steps=sampling_steps,
        )
    # NoCys wraps the OUTER (sequence-level) loss and makes it take an (N, 19)
    # simplex with cysteine removed. The optimizer variable changes shape too.
    return NoCys(loss) if no_cys else loss


def optimize(loss, binder_length, seed, no_cys):
    """Two-stage schedule from examples/protenij.py: soft solve, then sharpen."""
    key = jax.random.key(seed)
    n_tokens = 19 if no_cys else 20
    pssm = jax.nn.softmax(
        0.5 * jax.random.gumbel(key=key, shape=(binder_length, n_tokens))
    )

    _, pssm = simplex_APGM(
        loss_function=loss,
        x=pssm,
        n_steps=100,
        stepsize=0.15 * np.sqrt(binder_length),
        momentum=0.3,
        scale=1.0,
        max_gradient_norm=1.0,
    )
    pssm_sharp, _ = simplex_APGM(
        loss_function=loss,
        x=jnp.log(pssm + 1e-5),
        n_steps=20,
        stepsize=0.5 * np.sqrt(binder_length),
        momentum=0.0,
        scale=1.3,
        logspace=False,
        max_gradient_norm=1.0,
    )
    # Map the 19-column simplex back to the full 20-token alphabet (zero cysteine).
    return NoCys.sequence(pssm_sharp) if no_cys else pssm_sharp


def score(pred, binder_length):
    """Interface metrics. min_ipSAE is the metric that actually predicts binding."""
    plddt = np.asarray(pred.plddt)
    pae = np.asarray(pred.pae)
    b = binder_length
    inter = np.concatenate([pae[:b, b:].ravel(), pae[b:, :b].ravel()])
    return {
        "iptm": float(np.asarray(pred.iptm)),
        "binder_plddt": float(plddt[:b].mean()),
        "complex_plddt": float(plddt.mean()),
        "interface_pae": float(inter.mean()),
        "min_interface_pae": float(inter.min()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=sorted(GROUPS))
    ap.add_argument("--target-pdb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="protenix_v2")
    ap.add_argument("--n-designs", type=int, default=30)
    ap.add_argument("--binder-length", type=int, default=80)
    ap.add_argument("--recycling-steps", type=int, default=1)
    ap.add_argument("--sampling-steps", type=int, default=20)
    ap.add_argument("--seed0", type=int, default=0)
    ap.add_argument("--allow-cys", action="store_true",
                    help="permit cysteine (default: cysteine-free designs)")
    args = ap.parse_args()
    no_cys = not args.allow_cys

    out = Path(args.out)
    (out / "designs").mkdir(parents=True, exist_ok=True)
    (out / "pdb").mkdir(parents=True, exist_ok=True)

    epitope_pdb = GROUPS[args.group]
    epitope_idx = [r - PDB_OFFSET for r in epitope_pdb]

    seq, template_chain = load_target(Path(args.target_pdb))
    log(f"target: {len(seq)} residues")
    if len(seq) != 157:
        log(f"FATAL: expected 157 residues, got {len(seq)} - target PDB is wrong")
        return 1

    # Prove the index mapping before spending any GPU time on it.
    observed = "".join(seq[i] for i in epitope_idx)
    log(f"group {args.group}: PDB {epitope_pdb} -> idx {epitope_idx} -> '{observed}'")
    expected = {"A_ridge": "QPVN", "B_triad": "HD"}[args.group]
    if observed != expected:
        log(f"FATAL: epitope maps to '{observed}', expected '{expected}'")
        return 1

    # Resume: count what already exists rather than tracking state in a file.
    done = {p.stem for p in (out / "designs").glob("design_*.json")}
    log(f"resuming with {len(done)} designs already on disk")

    atomic_write(
        out / "config.json",
        json.dumps(
            {
                "group": args.group,
                "epitope_pdb": epitope_pdb,
                "epitope_idx": epitope_idx,
                "epitope_residues": observed,
                "model": args.model,
                "binder_length": args.binder_length,
                "n_designs": args.n_designs,
                "recycling_steps": args.recycling_steps,
                "sampling_steps": args.sampling_steps,
                "cysteine_free": no_cys,
                "target_sequence": seq,
            },
            indent=2,
        ),
    )

    log(f"loading model {args.model} (first JIT can take ~4 minutes)")
    model, mode = build_model(args.model)
    mpnn = load_mpnn_sol(0.0)

    design_features, design_writer = model.binder_features(
        binder_length=args.binder_length,
        chains=[TargetChain(seq, use_msa=False, template_chain=template_chain)],
    )
    loss = build_loss(
        model, mode, design_features, epitope_idx, mpnn,
        args.recycling_steps, args.sampling_steps, no_cys,
    )

    n_ok = 0
    for i in range(args.n_designs):
        name = f"design_{i:03d}"
        if name in done:
            continue
        t0 = time.time()
        try:
            pssm = optimize(loss, args.binder_length, args.seed0 + i, no_cys)
            ids = np.asarray(pssm).argmax(-1)
            sequence = "".join(TOKENS[int(j)] for j in ids)
            if no_cys and "C" in sequence:
                log(f"{name} WARNING: cysteine present despite NoCys")

            pred = model.predict(
                PSSM=jax.nn.one_hot(ids, 20),
                features=design_features,
                writer=design_writer,
                recycling_steps=4,
                key=jax.random.key(args.seed0 + i),
            )
            metrics = score(pred, args.binder_length)

            atomic_write(out / "pdb" / f"{name}.pdb", pred.st.make_minimal_pdb())
            atomic_write(
                out / "designs" / f"{name}.json",
                json.dumps(
                    {
                        "name": name,
                        "group": args.group,
                        "sequence": sequence,
                        "length": len(sequence),
                        "seed": args.seed0 + i,
                        "seconds": round(time.time() - t0, 1),
                        **metrics,
                    },
                    indent=2,
                ),
            )
            n_ok += 1
            log(
                f"{name}  iptm={metrics['iptm']:.3f}  "
                f"binder_plddt={metrics['binder_plddt']:.3f}  "
                f"i_pae={metrics['interface_pae']:.2f}  "
                f"({time.time() - t0:.0f}s)  {sequence}"
            )
        except Exception:
            log(f"{name} FAILED:\n{traceback.format_exc()}")

        # Refresh the summary after every design so progress is visible live.
        rows = []
        for p in sorted((out / "designs").glob("design_*.json")):
            rows.append(json.loads(p.read_text()))
        if rows:
            cols = ["name", "sequence", "length", "iptm", "binder_plddt",
                    "complex_plddt", "interface_pae", "min_interface_pae", "seed", "seconds"]
            lines = [",".join(cols)]
            for r in sorted(rows, key=lambda r: -r.get("iptm", 0)):
                lines.append(",".join(str(r.get(c, "")) for c in cols))
            atomic_write(out / "summary.csv", "\n".join(lines) + "\n")

    log(f"FINISHED group={args.group} new={n_ok} total={len(list((out / 'designs').glob('*.json')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
