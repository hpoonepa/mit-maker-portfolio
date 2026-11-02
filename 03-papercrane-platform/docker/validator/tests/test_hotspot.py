"""Tests for the hotspot contact metric.

The metric definition we validate here:

    For each hotspot residue on the target chain, count it as contacted if ANY
    heavy atom of ANY residue on the binder chain sits within 5.0 A of ANY
    heavy atom of the hotspot residue. Return the fraction of hotspots that
    are contacted.

Fixture layout (see tests/fixtures/design_0001.pdb):

    - Target chain A, residues 1..5. Hotspots = resi 2, 4.
    - Binder chain B, residues 1..3.
    - Binder residue 1 sits near target residue 2  (contact).
    - Binder residue 2 sits near target residue 4  (contact).
    - Binder residue 3 is placed at (50,50,50) -- far away.

    Both hotspots (A/2 and A/4) are contacted -> contact_fraction = 1.0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from papercrane_validator.metrics.hotspot import hotspot_contact_fraction


FIXTURES = Path(__file__).parent / "fixtures"
DESIGN_PDB = FIXTURES / "design_0001.pdb"


def test_both_hotspots_contacted_returns_one():
    frac = hotspot_contact_fraction(
        pdb_path=str(DESIGN_PDB),
        target_chain="A",
        binder_chain="B",
        hotspots=[("A", 2), ("A", 4)],
        cutoff_angstrom=5.0,
    )
    assert frac == pytest.approx(1.0)


def test_single_unreachable_hotspot_returns_zero():
    # Residue 1 of the target sits at (~1.5, 0, 0). The nearest binder atom is
    # residue 1 of chain B at (~4.5, 5.5, 0) -> distance ~6.3 A, outside 5 A.
    frac = hotspot_contact_fraction(
        pdb_path=str(DESIGN_PDB),
        target_chain="A",
        binder_chain="B",
        hotspots=[("A", 1)],
        cutoff_angstrom=5.0,
    )
    assert frac == pytest.approx(0.0)


def test_partial_contact_returns_half():
    frac = hotspot_contact_fraction(
        pdb_path=str(DESIGN_PDB),
        target_chain="A",
        binder_chain="B",
        # A/2 is contacted, A/5 is not.
        hotspots=[("A", 2), ("A", 5)],
        cutoff_angstrom=5.0,
    )
    assert frac == pytest.approx(0.5)


def test_empty_hotspots_returns_zero_without_raising():
    frac = hotspot_contact_fraction(
        pdb_path=str(DESIGN_PDB),
        target_chain="A",
        binder_chain="B",
        hotspots=[],
        cutoff_angstrom=5.0,
    )
    assert frac == 0.0


def test_wrong_binder_chain_raises():
    with pytest.raises(ValueError):
        hotspot_contact_fraction(
            pdb_path=str(DESIGN_PDB),
            target_chain="A",
            binder_chain="Z",  # not present
            hotspots=[("A", 2)],
            cutoff_angstrom=5.0,
        )
