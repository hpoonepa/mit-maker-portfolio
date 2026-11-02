"""BioEmu wrapper + multi-model PDB splitter.

The BioEmu subprocess calls in `generate_ensemble` are tested only in the
cloud smoke test (Task 12) — local Macs don't have BioEmu's CUDA env.
The PURE parser `split_ensemble_pdb` is unit-tested locally with fixtures.

Real BioEmu CLI (verified in dynamics/README.md, BioEmu commit 13503161):
  python -m bioemu.sample --sequence <AA> --num_samples N --output_dir DIR
    → writes <DIR>/topology.pdb + <DIR>/samples.xtc (backbone-only XTC trajectory)
  python -m bioemu.sidechain_relax --pdb-path <DIR>/topology.pdb --xtc-path <DIR>/samples.xtc
    → writes <DIR>/samples_sidechain_rec.pdb (all-atom multi-model PDB)

  Verify exact flag spellings against dynamics/README.md before final wiring;
  this docstring captures what was current at the time of writing.
"""
from __future__ import annotations
from pathlib import Path
import subprocess


def _extract_sequence_from_pdb(pdb_path: Path) -> str:
    """Read a PDB file and return its single-chain one-letter amino-acid sequence.

    Uses Biopython. If the PDB has multiple chains, this returns the longest one.
    """
    from Bio.PDB import PDBParser
    from Bio.PDB.Polypeptide import PPBuilder

    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", str(pdb_path))
    ppb = PPBuilder()
    sequences: list[str] = []
    for pp in ppb.build_peptides(structure):
        sequences.append(str(pp.get_sequence()))
    if not sequences:
        raise ValueError(f"No polypeptide chains found in {pdb_path}")
    return max(sequences, key=len)


def generate_ensemble(
    input_pdb: Path,
    output_dir: Path,
    num_samples: int = 100,
) -> Path:
    """Run BioEmu on the input PDB. Returns path to the all-atom multi-model PDB
    suitable for downstream per-frame fpocket detection.

    Pipeline (real BioEmu CLI — see module docstring):
      1. Extract amino-acid sequence from input_pdb.
      2. python -m bioemu.sample --sequence ... --num_samples N --output_dir output_dir
         (backbone-only XTC + topology.pdb)
      3. python -m bioemu.sidechain_relax --pdb-path topology.pdb --xtc-path samples.xtc
         (all-atom multi-model PDB at output_dir/samples_sidechain_rec.pdb)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sequence = _extract_sequence_from_pdb(Path(input_pdb))

    # Step 1: sample backbone ensemble
    subprocess.run(
        [
            "python", "-m", "bioemu.sample",
            "--sequence", sequence,
            "--num_samples", str(num_samples),
            "--output_dir", str(output_dir),
        ],
        check=True,
    )

    topology = output_dir / "topology.pdb"
    samples_xtc = output_dir / "samples.xtc"
    if not topology.exists() or not samples_xtc.exists():
        raise RuntimeError(
            f"BioEmu sample produced unexpected output in {output_dir}; "
            f"expected topology.pdb + samples.xtc"
        )

    # Step 2: sidechain reconstruction → all-atom multi-model PDB
    subprocess.run(
        [
            "python", "-m", "bioemu.sidechain_relax",
            "--pdb-path", str(topology),
            "--xtc-path", str(samples_xtc),
        ],
        check=True,
    )

    all_atom_pdb = output_dir / "samples_sidechain_rec.pdb"
    if not all_atom_pdb.exists():
        raise RuntimeError(
            f"BioEmu sidechain_relax did not produce {all_atom_pdb}; "
            f"check dynamics/README.md for the current expected output filename"
        )
    return all_atom_pdb


def split_ensemble_pdb(multi_model_pdb: Path, out_dir: Path) -> list[Path]:
    """Split a multi-model PDB into one file per model. Returns ordered list.

    PURE: deterministic for the same input file. Used in tests with the
    ensemble_3frames.pdb fixture (no BioEmu required).
    """
    multi_model_pdb = Path(multi_model_pdb)
    text = multi_model_pdb.read_text()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if "MODEL" not in text:
        target = out_dir / f"{multi_model_pdb.stem}_frame_001.pdb"
        target.write_text(text)
        return [target]

    frames: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("MODEL"):
            current = []
        elif line.startswith("ENDMDL"):
            if current is not None:
                frames.append(current)
                current = None
        elif current is not None and line.startswith(("ATOM", "HETATM", "TER")):
            current.append(line)

    out_paths: list[Path] = []
    for i, frame_lines in enumerate(frames, 1):
        p = out_dir / f"{multi_model_pdb.stem}_frame_{i:03d}.pdb"
        p.write_text("\n".join(frame_lines) + "\nEND\n")
        out_paths.append(p)
    return out_paths
