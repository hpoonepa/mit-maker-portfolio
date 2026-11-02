# Check datasets contracts using local fixtures.
from pathlib import Path

import pytest

from legacy_poc.datasets import (
    BenchmarkTarget,
    convert_pocketminer_xlsx_to_csv,
    holo_ligand_centroid,
    load_pocketminer_benchmark,
)
from tests.conftest import FIXTURES_DIR


def test_load_pocketminer_benchmark_returns_list_of_targets(tmp_path):
    csv = tmp_path / "pm.csv"
    csv.write_text("apo_pdb,holo_pdb,ligand_resname\n1jwp,1pzo,SIA\n1ade,1cib,AMP\n")
    targets = load_pocketminer_benchmark(csv)
    assert len(targets) == 2
    assert all(isinstance(t, BenchmarkTarget) for t in targets)
    assert targets[0].apo_pdb_id == "1jwp"
    assert targets[0].holo_pdb_id == "1pzo"
    assert targets[0].ligand_resname == "SIA"


def test_holo_ligand_centroid_extracts_from_hetatm_records(tmp_path):
    pdb = tmp_path / "holo.pdb"
    pdb.write_text(
        "HETATM    1  C1  LIG A 999       1.000   2.000   3.000  1.00  0.00           C\n"
        "HETATM    2  C2  LIG A 999       3.000   4.000   5.000  1.00  0.00           C\n"
        "END\n"
    )
    cx, cy, cz = holo_ligand_centroid(pdb, ligand_resname="LIG")
    assert cx == pytest.approx(2.0)
    assert cy == pytest.approx(3.0)
    assert cz == pytest.approx(4.0)


def test_holo_ligand_centroid_raises_if_ligand_not_found(tmp_path):
    pdb = tmp_path / "holo.pdb"
    pdb.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\nEND\n")
    with pytest.raises(ValueError):
        holo_ligand_centroid(pdb, ligand_resname="LIG")


def test_convert_pocketminer_xlsx_to_csv_emits_normalized_csv(tmp_path):
    # Synthetic XLSX fixture mirrors the real PocketMiner format:
    #   sheet_name = "validation_and_test_sets"
    #   3 header rows
    #   col index 2 = apo PDB ID
    #   col index 6 = holo PDB ID
    #   col index 8 = holo ligand code
    # These match the canonical indices documented in dynamics/README.md
    # under "## PocketMiner benchmark" (0-indexed against openpyxl's
    # values_only tuple), so we rely on the function's defaults.
    csv_out = tmp_path / "out.csv"
    convert_pocketminer_xlsx_to_csv(
        FIXTURES_DIR / "sample_pocketminer.xlsx",
        csv_out,
    )
    rows = csv_out.read_text().splitlines()
    assert rows[0] == "apo_pdb,holo_pdb,ligand_resname"
    assert len(rows) >= 2  # header + at least one data row
    # Spot-check first data row matches the fixture: apo=1jwp, holo=1pzo, lig=SIA
    fields = rows[1].split(",")
    assert len(fields) == 3
    assert all(f.strip() for f in fields)
    assert fields[0] == "1jwp"
    assert fields[1] == "1pzo"
    assert fields[2] == "SIA"
