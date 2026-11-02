"""BioEmu command plans and explicit trajectory extraction, never implicit launch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .io import atomic_write_json, file_hash
from .schema import AMINO_ACIDS


@dataclass(frozen=True)
class SamplingPlan:
    sample_argv: tuple[str, ...]
    reconstruct_argv: tuple[str, ...]
    requested_frames: int
    backbone_topology: str
    backbone_trajectory: str
    reconstructed_topology: str
    reconstructed_trajectory: str
    warnings: tuple[str, ...]


def plan_bioemu(
    sequence: str,
    output_dir: str | Path,
    *,
    requested_frames: int = 16,
    seed: int = 1729,
    python: str = "python",
    model_name: str = "bioemu-v1.1",
    batch_size_100: int = 10,
) -> SamplingPlan:
    if not sequence or set(sequence) - AMINO_ACIDS:
        raise ValueError("BioEmu input must be a standard amino-acid sequence")
    if type(requested_frames) is not int or requested_frames < 1:
        raise ValueError("Requested frame count must be positive")
    if type(seed) is not int or seed < 0 or type(batch_size_100) is not int or batch_size_100 < 1:
        raise ValueError("Seed/batch size invalid")
    if model_name not in {"bioemu-v1.0", "bioemu-v1.1", "bioemu-v1.2"}:
        raise ValueError("Pin a reviewed checkpoint name")
    output = Path(output_dir).resolve()
    # Emit argument arrays while leaving filesystem, model and MSA state untouched.
    sample = (
        python,
        "-m",
        "bioemu.sample",
        "--sequence",
        sequence,
        "--num_samples",
        str(requested_frames),
        "--output_dir",
        str(output),
        "--model_name",
        model_name,
        "--base_seed",
        str(seed),
        "--batch_size_100",
        str(batch_size_100),
        "--filter_samples",
        "True",
    )
    reconstruct = (
        python,
        "-m",
        "bioemu.sidechain_relax",
        "--pdb-path",
        str(output / "topology.pdb"),
        "--xtc-path",
        str(output / "samples.xtc"),
        "--outpath",
        str(output),
        "--prefix",
        "samples",
        "--no-md-equil",
    )
    return SamplingPlan(
        sample,
        reconstruct,
        requested_frames,
        str(output / "topology.pdb"),
        str(output / "samples.xtc"),
        str(output / "samples_sidechain_rec.pdb"),
        str(output / "samples_sidechain_rec.xtc"),
        (
            "Commands are unexecuted; exact environment/checkpoint hashes still required.",
            "Sampling can contact the MSA service and download AF2/BioEmu weights.",
            "HPacker first use may install its own environment; include setup time and disk.",
            "Reconstruction has no minimization in this plan; all-atom validity remains a separate gate.",
            "The topology PDB contains one frame; the paired XTC contains the ensemble.",
        ),
    )


def extract_trajectory_frames(
    topology_path: str | Path,
    trajectory_path: str | Path,
    output_dir: str | Path,
    *,
    sequence: str,
    requested_frames: int,
    expected_frames: int,
) -> dict:
    """Read every reconstructed frame; no sampler/model is called.

    Future compute-stage IO adapter. MDtraj stores coordinates in nm and writes
    PDB coordinates in angstroms. Use save_pdb rather than copying xyz directly.
    expected_frames must come from the preceding reconstruction receipt.
    """
    import mdtraj as md
    import numpy as np

    if not 0 <= expected_frames <= requested_frames or requested_frames < 1:
        raise ValueError("Invalid requested/expected frame accounting")
    top, xtc = Path(topology_path), Path(trajectory_path)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Frame extraction requires an empty output directory")
    trajectory = md.load_xtc(str(xtc), top=str(top))
    if trajectory.n_frames != expected_frames:
        raise ValueError("Reconstruction receipt and actual trajectory frame counts disagree")
    if not np.isfinite(trajectory.xyz).all():
        raise ValueError("Non-finite reconstructed coordinates")
    if trajectory.topology.n_chains != 1:
        raise ValueError("Expected exactly one protein chain in reconstructed topology")
    sequences = trajectory.topology.to_fasta()
    if sequences != [sequence]:
        raise ValueError("Reconstructed topology sequence differs from canonical input")
    # Backbone-only output must never pass as reconstructed all-atom output.
    from .mapping import THREE_TO_ONE

    expected_heavy = {
        "A": 5,
        "C": 6,
        "D": 8,
        "E": 9,
        "F": 11,
        "G": 4,
        "H": 10,
        "I": 8,
        "K": 9,
        "L": 8,
        "M": 8,
        "N": 8,
        "P": 7,
        "Q": 9,
        "R": 11,
        "S": 6,
        "T": 7,
        "V": 7,
        "W": 14,
        "Y": 12,
    }
    for residue in trajectory.topology.residues:
        heavy = [a for a in residue.atoms if a.element is not None and a.element.symbol not in {"H", "D"}]
        amino = THREE_TO_ONE.get(residue.name)
        if amino is None or len(heavy) < expected_heavy[amino]:
            raise ValueError("Incomplete heavy-atom reconstruction")
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for index in range(trajectory.n_frames):
        path = output / f"frame_{index:05d}.pdb"
        trajectory[index].save_pdb(str(path))
        files.append({"frame_id": f"frame_{index:05d}", "path": str(path), "sha256": file_hash(path)})
    receipt = {
        "topology_sha256": file_hash(top),
        "trajectory_sha256": file_hash(xtc),
        "requested_frames": requested_frames,
        "reconstructed_frames": trajectory.n_frames,
        "units_in_pdb": "angstrom",
        "unordered_samples": True,
        "all_atom_physical_quality_checked": False,
        "frames": files,
    }
    atomic_write_json(output / "frames.json", receipt)
    return receipt
