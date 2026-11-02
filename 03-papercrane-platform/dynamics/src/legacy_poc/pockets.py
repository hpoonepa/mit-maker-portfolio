"""fpocket wrapper. One structure in, list of Pocket records out.

Layered so the parser is testable WITHOUT the fpocket binary:
  - ``_run_fpocket``               - subprocess only; not unit-tested locally.
  - ``_parse_pockets_from_out_dir``- pure file I/O over an fpocket-style out dir.
  - ``_pocket_center``             - centroid of one pocket's ATOM/HETATM coords.
  - ``detect_pockets``             - public API; orchestrates the two layers.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass(frozen=True)
class Pocket:
    """A single fpocket-detected cavity."""

    center: Tuple[float, float, float]
    volume: float
    druggability: float
    n_residues: int


# NOTE on regex casing: real fpocket emits "Number of Alpha Spheres" with a
# capital "A" and "S". The plan-spec regex used lowercase. We make the whole
# regex case-insensitive (re.IGNORECASE) so it tolerates either casing across
# fpocket versions.
_POCKET_RE = re.compile(
    r"Pocket\s+(?P<idx>\d+)\s*:.*?"
    r"Druggability\s+Score\s*:\s*(?P<drug>[0-9.]+).*?"
    r"Number\s+of\s+Alpha\s+Spheres\s*:\s*(?P<spheres>\d+).*?"
    r"Real\s+volume\s*\(approximation\)\s*:\s*(?P<vol>[0-9.]+)",
    re.DOTALL | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pure layer: parse an fpocket out-dir into Pocket records (no subprocess).
# ---------------------------------------------------------------------------


class FpocketOutputError(RuntimeError):
    """fpocket subprocess exited successfully but produced no info.txt - likely a version or naming mismatch."""


def _parse_pockets_from_out_dir(out_dir: Path, stem: str) -> List[Pocket]:
    """Parse pocket records from a directory that looks like fpocket output.

    Expected layout::

        <out_dir>/
            <stem>_info.txt
            pockets/
                pocket0_atm.pdb     (Pocket 1)
                pocket1_atm.pdb     (Pocket 2)
                ...
    """
    out_dir = Path(out_dir)
    info_file = out_dir / f"{stem}_info.txt"
    if not info_file.exists():
        raise FpocketOutputError(
            f"fpocket succeeded but expected info file is missing: {info_file}. "
            "Likely an fpocket version or output-naming mismatch."
        )

    info_text = info_file.read_text()
    pockets: List[Pocket] = []
    for m in _POCKET_RE.finditer(info_text):
        idx = int(m.group("idx"))
        center = _pocket_center(out_dir, idx)
        pockets.append(
            Pocket(
                center=center,
                volume=float(m.group("vol")),
                druggability=float(m.group("drug")),
                n_residues=int(m.group("spheres")),
            )
        )
    return pockets


def _pocket_center(out_dir: Path, idx: int) -> Tuple[float, float, float]:
    """Centroid of ATOM/HETATM coordinates in pockets/pocket{idx-1}_atm.pdb.

    fpocket numbers Pocket "1" in the info file but writes its atoms to
    pocket0_atm.pdb (zero-indexed filename). We honour that here.
    """
    pdb = out_dir / "pockets" / f"pocket{idx - 1}_atm.pdb"
    if not pdb.exists():
        return (0.0, 0.0, 0.0)

    xs: List[float] = []
    ys: List[float] = []
    zs: List[float] = []
    for line in pdb.read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            try:
                xs.append(float(line[30:38]))
                ys.append(float(line[38:46]))
                zs.append(float(line[46:54]))
            except ValueError:
                continue
    if not xs:
        return (0.0, 0.0, 0.0)
    return (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))


# ---------------------------------------------------------------------------
# Subprocess layer: invoke fpocket. Not unit-tested locally.
# ---------------------------------------------------------------------------


def _run_fpocket(staged_pdb: Path, work_dir: Path) -> Path:
    """Run fpocket on ``staged_pdb`` inside ``work_dir`` and return the out dir.

    The caller owns ``work_dir`` and is responsible for keeping it alive long
    enough to read the returned out dir's contents (and for cleaning it up).

    Raises:
        subprocess.CalledProcessError: if the fpocket binary fails.
    """
    subprocess.run(
        ["fpocket", "-f", str(staged_pdb)],
        check=True,
        capture_output=True,
    )
    return Path(work_dir) / f"{staged_pdb.stem}_out"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_pockets(pdb_path: Path) -> List[Pocket]:
    """Run fpocket on ``pdb_path`` and return the parsed Pocket list.

    Raises:
        FileNotFoundError: if ``pdb_path`` does not exist.
        subprocess.CalledProcessError: if the fpocket binary fails.
        FpocketOutputError: if fpocket exits 0 but produces no info.txt.
    """
    pdb_path = Path(pdb_path)
    if not pdb_path.exists():
        raise FileNotFoundError(pdb_path)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        staged = td_path / pdb_path.name
        shutil.copy(pdb_path, staged)
        out_dir = _run_fpocket(staged, td_path)
        return _parse_pockets_from_out_dir(out_dir, pdb_path.stem)
