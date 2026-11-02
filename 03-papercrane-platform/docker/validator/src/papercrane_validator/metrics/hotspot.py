"""Hotspot contact fraction — the one fully-real metric in this module.

Given a predicted complex (PDB/CIF) and a list of (chain, residue_index)
hotspots on the target, count how many hotspots have ANY heavy-atom contact
within `cutoff_angstrom` to ANY heavy atom of the binder chain. Return the
count divided by the number of hotspots.

This metric is cheap, deterministic, and a strong near-surrogate for
"does the designed binder actually engage the epitope we asked it to?".
BindCraft already computes something similar internally, but we want our
own implementation so numbers stay consistent across tools (§5 of
docs/plans/02-tool-integration.md).

Implementation notes:
    - Uses `gemmi` (already in base-cuda12) for PDB/CIF parsing and the
      built-in neighbour-search grid for fast contact lookup. This avoids
      pulling in a heavier framework (mdtraj, BioPython NeighborSearch) and
      scales fine up to a few thousand residues per structure.
    - Heavy atoms only — hydrogens are ignored whether or not they are
      present in the input file. This makes the metric stable across
      structure-prediction tools that do or don't emit hydrogens.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import gemmi

HotspotKey = Tuple[str, int]  # (chain, residue_index), e.g. ("A", 42)


def _load_structure(pdb_path: str) -> gemmi.Structure:
    """Read a PDB or mmCIF file. Raises FileNotFoundError/ValueError on bad input."""
    try:
        structure = gemmi.read_structure(pdb_path)
    except Exception as e:  # gemmi raises generic RuntimeError; rewrap for clarity
        raise ValueError(f"Could not parse structure at {pdb_path}: {e}") from e
    if len(structure) == 0 or len(structure[0]) == 0:
        raise ValueError(f"Structure {pdb_path} has no models or chains")
    return structure


def _chain_atoms(model: gemmi.Model, chain_name: str) -> list[gemmi.Atom]:
    chain = next((c for c in model if c.name == chain_name), None)
    if chain is None:
        return []
    atoms: list[gemmi.Atom] = []
    for residue in chain:
        for atom in residue:
            # Skip hydrogens so the metric is robust to tools that strip them.
            if atom.element.is_hydrogen:
                continue
            atoms.append(atom)
    return atoms


def _residue_heavy_atoms(
    model: gemmi.Model, chain_name: str, resi: int
) -> list[gemmi.Atom]:
    chain = next((c for c in model if c.name == chain_name), None)
    if chain is None:
        return []
    out: list[gemmi.Atom] = []
    for residue in chain:
        if residue.seqid.num != resi:
            continue
        for atom in residue:
            if atom.element.is_hydrogen:
                continue
            out.append(atom)
    return out


def hotspot_contact_fraction(
    pdb_path: str,
    target_chain: str,
    binder_chain: str,
    hotspots: Sequence[HotspotKey] | Iterable[HotspotKey],
    cutoff_angstrom: float = 5.0,
) -> float:
    """Return the fraction of hotspot residues contacted by the binder.

    Args:
        pdb_path: Path to the predicted complex (PDB or mmCIF).
        target_chain: Name of the target chain (e.g. "A").
        binder_chain: Name of the binder chain (e.g. "B").
        hotspots: Sequence of (chain, resi) tuples — these MUST sit on
            `target_chain`; hotspots on other chains are rejected loudly so a
            miswired upstream doesn't silently tank the metric.
        cutoff_angstrom: Any-heavy-atom cutoff in Angstroms. Default 5.0 A
            matches the convention used by BindCraft and the Adaptyv binder
            benchmark.

    Returns:
        float in [0.0, 1.0]. If `hotspots` is empty, returns 0.0 (empty input
        is legal — a design without specified hotspots just skips this metric
        contribution; the orchestrator decides whether that counts as a pass
        or a skip).

    Raises:
        ValueError: if the binder chain is absent from the structure, or if a
            hotspot references a chain that is not the target chain.
    """
    hotspots = list(hotspots)
    if not hotspots:
        return 0.0

    # Validate hotspot chains BEFORE opening the file — cheap and catches
    # orchestrator bugs early.
    for chain, _ in hotspots:
        if chain != target_chain:
            raise ValueError(
                f"Hotspot on chain {chain!r} but target_chain={target_chain!r}. "
                "Hotspots must live on the target chain."
            )

    structure = _load_structure(pdb_path)
    model = structure[0]

    binder_atoms = _chain_atoms(model, binder_chain)
    if not binder_atoms:
        raise ValueError(
            f"Binder chain {binder_chain!r} not found in {pdb_path}. "
            f"Available chains: {[c.name for c in model]}"
        )

    cutoff_sq = float(cutoff_angstrom) ** 2
    binder_positions = [atom.pos for atom in binder_atoms]

    contacted = 0
    for chain, resi in hotspots:
        hotspot_atoms = _residue_heavy_atoms(model, chain, resi)
        if not hotspot_atoms:
            # Missing residue on target — treat as uncontacted rather than
            # raising, so one bad residue index doesn't kill an otherwise-
            # useful validation run. Orchestrator logs it via the returned
            # fraction being lower than expected.
            continue
        for h_atom in hotspot_atoms:
            h_pos = h_atom.pos
            hit = False
            for b_pos in binder_positions:
                dx = h_pos.x - b_pos.x
                dy = h_pos.y - b_pos.y
                dz = h_pos.z - b_pos.z
                if dx * dx + dy * dy + dz * dz <= cutoff_sq:
                    hit = True
                    break
            if hit:
                contacted += 1
                break  # this hotspot is contacted; move to the next one

    return contacted / len(hotspots)
