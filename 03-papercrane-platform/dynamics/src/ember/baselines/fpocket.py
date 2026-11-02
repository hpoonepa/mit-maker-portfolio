"""Strict adapter for the pinned fpocket reference-output format.

Verified against upstream 4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066:
Pocket 1 -> pocket1_atm.pdb + pocket1_vert.pqr. Centers are alpha-sphere
centroids; residue membership comes from actual protein atom records.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from ..schema import Observation, ResidueID


class PocketOutputError(ValueError):
    pass


def parse_info(path: str | Path) -> dict[int, dict[str, float]]:
    text = Path(path).read_text()
    blocks = re.split(r"(?m)^Pocket\s+(\d+)\s*:\s*$", text)
    if len(blocks) == 1:
        raise PocketOutputError("No pocket records: use an explicit successful zero-pocket receipt")
    if blocks[0].strip():
        raise PocketOutputError("Unexpected preamble in fpocket info file")
    pockets = {}
    for index in range(1, len(blocks), 2):
        number = int(blocks[index])
        if number < 1 or number in pockets:
            raise PocketOutputError("Duplicate/invalid pocket number")
        values = {}
        for line in blocks[index + 1].splitlines():
            if not line.strip():
                continue
            if ":" not in line:
                raise PocketOutputError(f"Malformed descriptor line: {line!r}")
            key, raw = line.split(":", 1)
            key = key.strip().lower()
            try:
                value = float(raw.strip())
            except ValueError as error:
                raise PocketOutputError(f"Nonnumeric descriptor {key}") from error
            if key in values or not math.isfinite(value):
                raise PocketOutputError(f"Duplicate or non-finite descriptor {key}")
            values[key] = value
        for key in ("score", "druggability score", "number of alpha spheres", "volume"):
            if key not in values:
                raise PocketOutputError(f"Pocket {number} missing {key}")
        count = values["number of alpha spheres"]
        if count < 1 or not count.is_integer() or values["volume"] < 0:
            raise PocketOutputError("Invalid alpha-sphere count or volume")
        pockets[number] = values
    return pockets


def _coordinates(path: Path) -> list[tuple[float, float, float]]:
    if not path.is_file():
        raise PocketOutputError(f"Missing pocket coordinates: {path}")
    coords = []
    for line in path.read_text().splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            try:
                point = tuple(float(line[start : start + 8]) for start in (30, 38, 46))
            except ValueError as error:
                raise PocketOutputError(f"Malformed atom coordinates in {path}") from error
            if not all(math.isfinite(x) for x in point):
                raise PocketOutputError(f"Non-finite atom coordinates in {path}")
            coords.append(point)
    if not coords:
        raise PocketOutputError(f"Empty atom file: {path}")
    return coords


def parse_pocket(
    out_dir: str | Path,
    number: int,
    descriptors: dict[str, float],
    *,
    frame_id: str,
    source: str,
    residue_mapping: dict[ResidueID, int],
    structure_path: str | None = None,
) -> Observation:
    out_dir = Path(out_dir)
    atom_file = out_dir / "pockets" / f"pocket{number}_atm.pdb"
    # Reading coordinates also validates malformed/truncated atom records.
    _coordinates(atom_file)
    residues = set()
    for line in atom_file.read_text().splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        try:
            author = ResidueID(line[21].strip(), int(line[22:26]), line[26].strip())
        except (ValueError, IndexError) as error:
            raise PocketOutputError(f"Invalid residue ID in {atom_file}") from error
        if author not in residue_mapping:
            raise PocketOutputError(f"Pocket atom outside declared residue mapping: {author}")
        residues.add(residue_mapping[author])
    vertices = _coordinates(out_dir / "pockets" / f"pocket{number}_vert.pqr")
    if len(vertices) != int(descriptors["number of alpha spheres"]):
        raise PocketOutputError("Alpha-sphere count differs from vertex file")
    center = tuple(sum(point[i] for point in vertices) / len(vertices) for i in range(3))
    return Observation(
        f"{frame_id}:fpocket:{number}",
        frame_id,
        source,
        tuple(sorted(residues)),
        center,
        descriptors["score"],
        descriptors["volume"],
        descriptors["druggability score"],
        sasa=descriptors.get("total sasa"),
        structure_path=structure_path,
    )


def parse_output(
    out_dir: str | Path,
    stem: str,
    *,
    frame_id: str,
    source: str,
    residue_mapping: dict[ResidueID, int],
    structure_path: str | None = None,
    zero_pockets_confirmed: bool = False,
) -> list[Observation]:
    out_dir = Path(out_dir)
    info = out_dir / f"{stem}_info.txt"
    if zero_pockets_confirmed:
        # The future subprocess adapter must supply this only with a successful
        # version-specific no-pocket receipt. Missing output alone is not success.
        if (info.exists() and info.read_text().strip()) or list(
            (out_dir / "pockets").glob("pocket*_atm.pdb")
        ):
            raise PocketOutputError("Zero-pocket receipt contradicts output files")
        return []
    if not info.is_file():
        raise PocketOutputError(f"Missing fpocket info file: {info}")
    records = parse_info(info)
    return [
        parse_pocket(
            out_dir,
            number,
            values,
            frame_id=frame_id,
            source=source,
            residue_mapping=residue_mapping,
            structure_path=structure_path,
        )
        for number, values in sorted(records.items())
    ]
