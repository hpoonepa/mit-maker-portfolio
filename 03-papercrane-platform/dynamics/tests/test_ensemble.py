# Check ensemble contracts using local fixtures.
from pathlib import Path
import pytest
from legacy_poc.ensemble import split_ensemble_pdb

FIXTURE = Path(__file__).parent / "fixtures" / "ensemble_3frames.pdb"


def test_split_ensemble_pdb_yields_one_path_per_model(tmp_path):
    out = split_ensemble_pdb(FIXTURE, tmp_path)
    assert len(out) == 3
    for p in out:
        assert p.exists()
        text = p.read_text()
        assert text.count("ATOM") == 2
        assert "MODEL" not in text  # split files don't keep MODEL records


def test_split_ensemble_handles_single_model(tmp_path):
    single = tmp_path / "single.pdb"
    single.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\nEND\n")
    out = split_ensemble_pdb(single, tmp_path)
    assert len(out) == 1
