#!/usr/bin/env python
"""Sample Senba (adapted MarS-FM) transition endpoints for one protein structure.

Senba is a MarS-FM checkpoint, so it loads with the pinned MarS-FM source
(https://github.com/valence-labs/mars-fm at 4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946).
Put that repository on PYTHONPATH, then run:

    python inference_example.py --pdb 1ubq.pdb --chain A \
        --checkpoint senba.ckpt \
        --expect-sha256 f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c \
        --samples 8 --ode-steps 10 --seed 20260904 --out senba-1ubq.pdb

What you get: a multi-model PDB whose MODEL 1 is the input heavy-atom structure
and whose MODELS 2..K+1 are K independent samples of where the model places the
chain after the trained lag (50 mdCATH frames at 450 K). The samples are not a
trajectory, carry no physical clock, and were validated only on single-chain
mdCATH domains of at most 256 residues. Every claim about Senba is bounded to
that validation evidence; see README.md.

Input requirements: one protein chain, standard amino acids only, every heavy
atom present (crystal structures with truncated side chains are rejected rather
than silently zero-filled). HETATM records, hydrogens, alternate locations other
than A, and other chains are dropped before parsing.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import torch

torch.serialization.add_safe_globals([argparse.Namespace])

from mars.data.geometry import atom14_to_atom37, atom14_to_frames, atom37_to_torsions  # noqa: E402
from mars.model.module import MarSModule  # noqa: E402
from mars.utils import atom14_to_pdb  # noqa: E402
from mars.vendored.openfold import protein  # noqa: E402
from mars.vendored.openfold import residue_constants as rc  # noqa: E402

VALIDATED_MAX_RESIDUES = 256
TRAINED_LAG_FRAMES = 50
TRAINED_TEMPERATURE_K = 450


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def clean_pdb_text(pdb_text: str, chain_id: str | None) -> str:
    """Keep ATOM records of one chain with primary alternate locations only."""
    kept: list[str] = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM  "):
            continue
        if len(line) < 54:
            raise ValueError("truncated ATOM record in input PDB")
        if line[16] not in (" ", "A"):
            continue
        if chain_id is not None and line[21].strip() != chain_id:
            continue
        kept.append(line[:16] + " " + line[17:])
    if not kept:
        raise ValueError("no ATOM records matched the requested chain")
    return "\n".join(kept) + "\nEND\n"


def pdb_to_atom14(pdb_text: str, chain_id: str | None) -> tuple[np.ndarray, str]:
    prot = protein.from_pdb_string(clean_pdb_text(pdb_text, chain_id))
    if prot.chain_index is not None and len(np.unique(prot.chain_index)) != 1:
        raise ValueError("the structure has several chains; pass --chain")
    if prot.aatype.size == 0:
        raise ValueError("no residues were parsed")
    if np.any(prot.aatype >= rc.restype_num):
        raise ValueError("non-standard residues are not supported by MarS-FM")
    n_res = int(prot.aatype.shape[0])
    atom14 = np.zeros((n_res, 14, 3), dtype=np.float32)
    for index, aatype in enumerate(prot.aatype.tolist()):
        names = rc.restype_name_to_atom14_names[rc.restype_1to3[rc.restypes[aatype]]]
        for slot, name in enumerate(names):
            if not name:
                continue
            atom_index = rc.atom_order[name]
            if prot.atom_mask[index, atom_index] <= 0:
                raise ValueError(
                    f"residue {index + 1} ({rc.restypes[aatype]}) is missing heavy atom {name}; "
                    "supply a structure with complete side chains"
                )
            atom14[index, slot] = prot.atom_positions[index, atom_index]
    sequence = "".join(rc.restypes[aatype] for aatype in prot.aatype.tolist())
    return atom14, sequence


def build_batch(atom14: np.ndarray, sequence: str, samples: int, device: torch.device) -> dict:
    """Mirror the batch layout used by the frozen Senba validation runs."""
    seqres = torch.tensor([rc.restype_order[residue] for residue in sequence])
    seqres = seqres.unsqueeze(0).repeat(samples, 1)
    repeated = np.repeat(atom14[None], samples, axis=0).astype(np.float32, copy=False)
    frames = atom14_to_frames(torch.from_numpy(repeated))
    atom37 = torch.from_numpy(atom14_to_atom37(repeated, seqres)).float()
    torsions, torsion_mask = atom37_to_torsions(atom37, seqres)
    batch = {
        "torsions": torsions.unsqueeze(1),
        "torsion_mask": torsion_mask,
        "trans": frames._trans.unsqueeze(1),
        "rots": frames._rots._rot_mats.unsqueeze(1),
        "seqres": seqres,
        "mask": torch.ones_like(seqres, dtype=torch.float32),
    }
    return {key: value.to(device) for key, value in batch.items()}


def kabsch_rmsd(reference: np.ndarray, mobile: np.ndarray) -> float:
    """C-alpha RMSD after optimal superposition (no reflection)."""
    ref = reference - reference.mean(axis=0)
    mob = mobile - mobile.mean(axis=0)
    covariance = mob.T @ ref
    u, _, vt = np.linalg.svd(covariance)
    sign = np.sign(np.linalg.det(u @ vt))
    correction = np.diag([1.0, 1.0, sign])
    rotation = u @ correction @ vt
    aligned = mob @ rotation
    return float(np.sqrt(np.mean(np.sum((aligned - ref) ** 2, axis=1))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdb", required=True, type=Path, help="input PDB file (heavy atoms, one chain)")
    parser.add_argument("--chain", default=None, help="chain identifier to use when the file has several")
    parser.add_argument("--checkpoint", required=True, type=Path, help="path to senba.ckpt")
    parser.add_argument("--expect-sha256", default=None, help="refuse to run unless the checkpoint hash matches")
    parser.add_argument("--samples", type=int, default=8, help="independent endpoint draws")
    parser.add_argument("--ode-steps", type=int, default=10, help="flow ODE steps (validation used 10)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True, type=Path, help="multi-model PDB to write")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    if args.samples < 1 or args.ode_steps < 1:
        parser.error("--samples and --ode-steps must be positive")
    digest = sha256_file(args.checkpoint)
    if args.expect_sha256 is not None and digest != args.expect_sha256.lower().removeprefix("sha256:"):
        print(f"checkpoint hash {digest} does not match --expect-sha256", file=sys.stderr)
        return 2

    atom14, sequence = pdb_to_atom14(args.pdb.read_text(), args.chain)
    if len(sequence) > VALIDATED_MAX_RESIDUES:
        print(
            f"warning: {len(sequence)} residues exceeds the validated scope of "
            f"{VALIDATED_MAX_RESIDUES}; outputs are outside the published evidence",
            file=sys.stderr,
        )

    device = torch.device(args.device)
    torch.manual_seed(args.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)
    model = MarSModule.load_from_checkpoint(str(args.checkpoint), map_location="cpu")
    model.eval().to(device)
    batch = build_batch(atom14, sequence, args.samples, device)
    with torch.no_grad():
        generated_atom14, _ = model.inference(batch, num_steps=args.ode_steps)
    samples = generated_atom14[:, 0].float().cpu().numpy()  # [K, L, 14, 3]

    aatype = np.array([rc.restype_order[residue] for residue in sequence])
    atom14_to_pdb(np.concatenate([atom14[None], samples], axis=0), aatype, str(args.out))

    reference_ca = atom14[:, 1]
    rmsds = [kabsch_rmsd(reference_ca, sample[:, 1]) for sample in samples]
    print(f"checkpoint sha256 {digest}")
    print(f"sequence length {len(sequence)}; lag {TRAINED_LAG_FRAMES} frames at {TRAINED_TEMPERATURE_K} K")
    print(f"wrote {args.out} with MODEL 1 = input and MODELS 2..{args.samples + 1} = independent draws")
    print("aligned C-alpha RMSD of each draw from the input (A): " + ", ".join(f"{value:.3f}" for value in rmsds))
    print("these draws are independent samples at one lag, not a trajectory or a physical-time prediction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
