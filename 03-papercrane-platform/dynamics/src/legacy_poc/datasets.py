"""PocketMiner benchmark prep: XLSX->CSV conversion, target loading, ligand centroid."""
from __future__ import annotations

import csv
import urllib.request
from dataclasses import dataclass
from pathlib import Path


PDB_URL = "https://files.rcsb.org/download/{pdb_id}.pdb"


@dataclass(frozen=True)
class BenchmarkTarget:
    apo_pdb_id: str
    holo_pdb_id: str
    ligand_resname: str


def load_pocketminer_benchmark(csv_path: Path) -> list[BenchmarkTarget]:
    """Load a normalized PocketMiner CSV (columns: apo_pdb,holo_pdb,ligand_resname)
    into a list of BenchmarkTarget."""
    targets: list[BenchmarkTarget] = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            targets.append(
                BenchmarkTarget(
                    apo_pdb_id=row["apo_pdb"].strip().lower(),
                    holo_pdb_id=row["holo_pdb"].strip().lower(),
                    ligand_resname=row["ligand_resname"].strip().upper(),
                )
            )
    return targets


def fetch_pdb(pdb_id: str, dest_dir: Path) -> Path:
    """Download a PDB file from RCSB into dest_dir; return the local path.
    Skips download if the file already exists."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{pdb_id.lower()}.pdb"
    if out.exists():
        return out
    urllib.request.urlretrieve(PDB_URL.format(pdb_id=pdb_id.upper()), out)
    return out


def holo_ligand_centroid(
    holo_pdb: Path, ligand_resname: str
) -> tuple[float, float, float]:
    """Compute the (x, y, z) centroid of all HETATM records matching ligand_resname."""
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    target = ligand_resname.strip().upper()
    for line in Path(holo_pdb).read_text().splitlines():
        if not line.startswith("HETATM"):
            continue
        resname = line[17:20].strip().upper()
        if resname != target:
            continue
        xs.append(float(line[30:38]))
        ys.append(float(line[38:46]))
        zs.append(float(line[46:54]))
    if not xs:
        raise ValueError(f"Ligand {target} not found in {holo_pdb}")
    return (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))


def convert_pocketminer_xlsx_to_csv(
    xlsx_path: Path,
    csv_path: Path,
    sheet_name: str = "validation_and_test_sets",
    header_rows: int = 3,
    apo_col: int = 2,
    holo_col: int = 6,
    ligand_col: int = 8,
) -> Path:
    """Convert the PocketMiner supplementary XLSX into a normalized CSV with
    columns: apo_pdb,holo_pdb,ligand_resname.

    Defaults are the canonical PocketMiner indices documented in
    dynamics/README.md (## PocketMiner benchmark):
      - apo PDB ID = column index 2
      - holo PDB ID = column index 6
      - holo ligand code = column index 8
    All indices are 0-indexed against the values_only=True tuple returned by
    openpyxl's iter_rows (i.e. column A == index 0).

    Rows whose apo/holo/ligand cell is None or whose holo cell equals 'n/a'
    (case-insensitive) are skipped. Real PocketMiner XLSX has 49 valid data
    rows once these filters are applied.
    """
    from openpyxl import load_workbook  # lazy import; XLSX-path-only dependency

    wb = load_workbook(filename=str(xlsx_path), read_only=True, data_only=True)
    sheet = wb[sheet_name]
    rows_iter = sheet.iter_rows(values_only=True)
    for _ in range(header_rows):
        next(rows_iter, None)

    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["apo_pdb", "holo_pdb", "ligand_resname"])
        for row in rows_iter:
            if not row or all(cell is None for cell in row):
                continue
            # Defensive index guard: rows may be shorter than expected
            if max(apo_col, holo_col, ligand_col) >= len(row):
                continue
            apo = row[apo_col]
            holo = row[holo_col]
            lig = row[ligand_col]
            if apo is None or holo is None or lig is None:
                continue
            if str(holo).strip().lower() == "n/a":
                continue
            if str(lig).strip().lower() == "n/a":
                continue
            writer.writerow(
                [
                    str(apo).strip().lower(),
                    str(holo).strip().lower(),
                    str(lig).strip().upper(),
                ]
            )
    return Path(csv_path)
