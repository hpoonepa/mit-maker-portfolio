# SPDX-License-Identifier: MIT
"""Tests for structure loading, numbering maps, and unmodelled-residue detection."""

import pytest

from hotspot_preflight.residue import ResidueKey
from hotspot_preflight.structure import (
    load_target,
    build_label_seq_map,
    declared_residues,
    observed_residues,
    unobserved_from_cif_category,
    unobserved_from_alignment,
    low_occupancy_residues,
)


class TestLoad:
    def test_loads_and_reports_chains(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        assert t.chain_ids == ["A"]

    def test_author_numbering_is_not_label_numbering(self, cif_with_unobs_category):
        """The fixture offsets author numbering by +100 on purpose. If these were
        equal the other tests could pass by coincidence."""
        t = load_target(cif_with_unobs_category)
        observed = observed_residues(t)
        assert ResidueKey("A", 101) in observed
        assert ResidueKey("A", 1) not in observed


class TestLabelSeqMap:
    def test_maps_author_to_label_seq(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        m = build_label_seq_map(t)
        assert m[ResidueKey("A", 101)] == 1
        assert m[ResidueKey("A", 102)] == 2
        assert m[ResidueKey("A", 106)] == 6

    def test_unmodelled_residues_absent_from_map(self, cif_with_unobs_category):
        """The map is built from observed coordinates, so it cannot contain a
        residue with no atoms. to_boltzgen() relies on this to raise."""
        t = load_target(cif_with_unobs_category)
        m = build_label_seq_map(t)
        assert ResidueKey("A", 104) not in m


class TestDeclaredVsObserved:
    def test_declared_includes_unmodelled(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        declared = declared_residues(t)
        assert len(declared) == 6
        assert ResidueKey("A", 104) in declared

    def test_observed_excludes_unmodelled(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        observed = observed_residues(t)
        assert len(observed) == 4
        assert ResidueKey("A", 104) not in observed


class TestUnobservedFromCifCategory:
    def test_reads_the_category_when_present(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        got = unobserved_from_cif_category(t)
        assert got == {ResidueKey("A", 104), ResidueKey("A", 105)}

    def test_returns_none_when_category_absent(self, cif_without_unobs_category):
        """Critical distinction: None means 'the entry does not say', which is
        NOT the same as the empty set meaning 'nothing is missing'. This
        category is optional and absent from many real entries."""
        t = load_target(cif_without_unobs_category)
        assert unobserved_from_cif_category(t) is None


class TestUnobservedFromAlignment:
    def test_finds_the_gap_without_the_category(self, cif_without_unobs_category):
        """The derived route must find the same gap the category would have
        declared, because we cannot rely on the category existing."""
        t = load_target(cif_without_unobs_category)
        got = unobserved_from_alignment(t)
        assert got == {ResidueKey("A", 104), ResidueKey("A", 105)}

    def test_agrees_with_the_category_when_both_available(
        self, cif_with_unobs_category
    ):
        t = load_target(cif_with_unobs_category)
        assert unobserved_from_alignment(t) == unobserved_from_cif_category(t)


class TestLowOccupancy:
    def test_flags_zero_occupancy_residue(self, cif_with_zero_occupancy):
        t = load_target(cif_with_zero_occupancy)
        assert ResidueKey("A", 103) in low_occupancy_residues(t)

    def test_full_occupancy_not_flagged(self, cif_with_unobs_category):
        t = load_target(cif_with_unobs_category)
        assert low_occupancy_residues(t) == set()


@pytest.mark.network
class TestRealEntry6F5J:
    """Integration test on the entry that motivated this project.

    6F5J is the deformed wing virus capsid. A 5G51 binder campaign specified
    hotspots Ile405 and Phe408 on the VP-like chain; both lie in a tail region
    that is unmodelled in the deposited coordinates. 35 designs were ordered
    against residues that were never observed.
    """

    def test_399_to_416_are_unmodelled_on_chain_c(self, real_6f5j):
        t = load_target(real_6f5j)
        unobs = unobserved_from_cif_category(t)
        assert unobs is not None
        tail = {ResidueKey("C", n) for n in range(399, 417)}
        assert tail <= unobs

    def test_the_two_campaign_hotspots_are_unmodelled(self, real_6f5j):
        t = load_target(real_6f5j)
        unobs = unobserved_from_cif_category(t)
        assert ResidueKey("C", 405) in unobs
        assert ResidueKey("C", 408) in unobs

    def test_both_detection_routes_agree_on_the_tail(self, real_6f5j):
        t = load_target(real_6f5j)
        from_cat = unobserved_from_cif_category(t)
        from_aln = unobserved_from_alignment(t)
        tail = {ResidueKey("C", n) for n in range(399, 417)}
        assert tail <= from_cat
        assert tail <= from_aln
