"""Tests for dynamics/pockets.py.

Split into two layers:
  1. Parser unit tests (no fpocket binary needed) — use recorded fixtures.
  2. Integration test (skipped unless fpocket is on PATH) — runs the real binary.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dynamics.pockets import (
    FpocketOutputError,
    Pocket,
    detect_pockets,
    _parse_pockets_from_out_dir,
)
from dynamics.tests.conftest import FIXTURES_DIR


# ---------------------------------------------------------------------------
# Pure unit tests — no fpocket binary required
# ---------------------------------------------------------------------------


def test_detect_pockets_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        detect_pockets(tmp_path / "does_not_exist.pdb")


def test_parser_extracts_pockets_from_fixture_info_text(tmp_path: Path) -> None:
    """Stage a fake fpocket out-dir from the recorded fixtures and parse it.

    Layout the parser expects:
        <out_dir>/
            <stem>_info.txt
            pockets/
                pocket0_atm.pdb   (corresponds to "Pocket 1")
                pocket1_atm.pdb   (corresponds to "Pocket 2")
    """
    stem = "tiny_protein"
    out_dir = tmp_path / f"{stem}_out"
    (out_dir / "pockets").mkdir(parents=True)

    # info.txt copied verbatim from the recorded fixture
    info_src = FIXTURES_DIR / "sample_fpocket_info.txt"
    (out_dir / f"{stem}_info.txt").write_text(info_src.read_text())

    # Use the recorded pocket1 PDB for BOTH pockets so we have a deterministic centroid.
    pocket_pdb_src = FIXTURES_DIR / "sample_pocket1_atm.pdb"
    pocket_text = pocket_pdb_src.read_text()
    (out_dir / "pockets" / "pocket0_atm.pdb").write_text(pocket_text)
    (out_dir / "pockets" / "pocket1_atm.pdb").write_text(pocket_text)

    pockets = _parse_pockets_from_out_dir(out_dir, stem)

    assert isinstance(pockets, list)
    assert len(pockets) == 2

    # Pocket 1
    p1 = pockets[0]
    assert isinstance(p1, Pocket)
    assert p1.druggability == pytest.approx(0.823)
    assert p1.volume == pytest.approx(850.123)
    assert p1.n_residues == 78
    assert p1.center == pytest.approx((5.0, 5.0, 5.0), abs=1e-6)

    # Pocket 2
    p2 = pockets[1]
    assert p2.druggability == pytest.approx(0.412)
    assert p2.volume == pytest.approx(432.100)
    assert p2.n_residues == 42
    assert p2.center == pytest.approx((5.0, 5.0, 5.0), abs=1e-6)


# ---------------------------------------------------------------------------
# Integration test — only runs when fpocket binary is installed (e.g. in Docker)
# ---------------------------------------------------------------------------


def test_parser_raises_when_info_file_missing(tmp_path: Path) -> None:
    """fpocket version/naming drift must NOT silently look like 'no pockets found'."""
    out_dir = tmp_path / "stem_out"
    out_dir.mkdir()
    # Note: NO info.txt written - simulates fpocket success with missing output file.
    with pytest.raises(FpocketOutputError):
        _parse_pockets_from_out_dir(out_dir, "stem")


@pytest.mark.skipif(
    shutil.which("fpocket") is None,
    reason="fpocket binary not installed locally; will run in Docker",
)
def test_detect_pockets_returns_nonempty_list_for_known_pocket_protein(
    tmp_path: Path,
) -> None:
    """Run the real fpocket on a known-pocket protein (1STP, streptavidin)."""
    import urllib.request

    pdb = tmp_path / "1stp.pdb"
    # Use the bundled fixture if present, else download.
    bundled = FIXTURES_DIR / "tiny_protein.pdb"
    if bundled.exists():
        shutil.copy(bundled, pdb)
    else:
        urllib.request.urlretrieve("https://files.rcsb.org/download/1STP.pdb", pdb)

    pockets = detect_pockets(pdb)
    assert isinstance(pockets, list)
    assert len(pockets) >= 1
    for p in pockets:
        assert isinstance(p, Pocket)
        assert len(p.center) == 3
        assert p.volume > 0
        assert 0.0 <= p.druggability <= 1.0
