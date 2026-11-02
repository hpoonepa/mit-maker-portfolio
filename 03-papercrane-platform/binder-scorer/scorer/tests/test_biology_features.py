"""Tests for scorer.biology_features — design-side (binder) biology descriptors.

Expected values are HAND-COMPUTED on the known 15-residue sequence
``SEQ = "ACDEFGHIKLMNNST"`` using the standard Kyte-Doolittle hydropathy and
Chou-Fasman propensity tables (reused from scorer.target_features).

Residue-by-residue Kyte-Doolittle for SEQ:
    A  1.8   C  2.5   D -3.5   E -3.5   F  2.8
    G -0.4   H -3.2   I  4.5   K -3.9   L  3.8
    M  1.9   N -3.5   N -3.5   S -0.8   T -0.7
"""

from __future__ import annotations

import pytest

from scorer.biology_features import (
    aggregation_propensity,
    cys_is_odd,
    disorder_fraction,
    disulfide_potential,
    immunogenicity_proxy,
    n_cys,
    phospho_site_density,
    ptm_site_density,
    topology_helix_frac,
    topology_loop_frac,
    topology_strand_frac,
)

SEQ = "ACDEFGHIKLMNNST"  # 15 residues


def test_seq_length_sanity():
    assert len(SEQ) == 15


def test_aggregation_propensity():
    # Max mean Kyte-Doolittle over sliding windows of size {5,6,7}.
    # Most hydrophobic window is FGHIKLM (positions 5-11, size 7):
    #   2.8 -0.4 -3.2 +4.5 -3.9 +3.8 +1.9 = 5.5 ; mean = 5.5/7.
    assert aggregation_propensity(SEQ) == pytest.approx(5.5 / 7.0)


def test_aggregation_propensity_short_seq_fallback():
    # Sequence shorter than the smallest window (5) -> mean over whole seq.
    # "AIL" KD = 1.8 + 4.5 + 3.8 = 10.1 ; mean = 10.1/3.
    assert aggregation_propensity("AIL") == pytest.approx(10.1 / 3.0)


def test_aggregation_propensity_empty():
    assert aggregation_propensity("") == 0.0


def test_ptm_site_density():
    # N-glyc sequons N[^P][ST]:
    #   N(12) N(13) S(14) -> NNS, third=S  -> sequon
    #   N(13) S(14) T(15) -> NST, third=T  -> sequon   => 2 sequons
    # O-glyc-prone S/T residues: S(14), T(15)           => 2
    # density = (2 + 2) / 15
    assert ptm_site_density(SEQ) == pytest.approx(4.0 / 15.0)


def test_phospho_site_density():
    # S + T + Y = S(14) + T(15) + 0 = 2 ; / 15
    assert phospho_site_density(SEQ) == pytest.approx(2.0 / 15.0)


def test_disulfide_potential():
    # One cysteine -> floor(1/2) = 0 potential pairs.
    assert disulfide_potential(SEQ) == pytest.approx(0.0)


def test_disulfide_potential_multiple_cys():
    # 5 cysteines -> floor(5/2) = 2 potential pairs.
    assert disulfide_potential("CCACCGC") == pytest.approx(2.0)


def test_n_cys_and_odd_flag():
    assert n_cys(SEQ) == 1
    assert cys_is_odd(SEQ) is True
    assert n_cys("CCACCGC") == 5
    assert cys_is_odd("CCACCGC") is True
    assert cys_is_odd("CC") is False


def test_disorder_fraction():
    # Disorder-promoting set {S,P,E,K,Q,G,R,D,A,N}:
    #   A,D,E,G,K,N,N,S = 8 of 15
    assert disorder_fraction(SEQ) == pytest.approx(8.0 / 15.0)


def test_topology_fractions_values():
    # Chou-Fasman per-residue classification of SEQ:
    #   helix : A,D,E,K,M           = 5
    #   strand: C,F,I,L,T           = 5
    #   loop  : G,H,N,N,S           = 5
    assert topology_helix_frac(SEQ) == pytest.approx(5.0 / 15.0)
    assert topology_strand_frac(SEQ) == pytest.approx(5.0 / 15.0)
    assert topology_loop_frac(SEQ) == pytest.approx(5.0 / 15.0)


def test_topology_fractions_sum_to_one():
    s = topology_helix_frac(SEQ) + topology_strand_frac(SEQ) + topology_loop_frac(SEQ)
    assert s == pytest.approx(1.0)


def test_immunogenicity_proxy_none_above_threshold():
    # Crude T-cell-epitope proxy: density of hydrophobic 9-mers (mean KD > 0).
    # For SEQ every 9-mer has mean hydropathy < 0 -> 0 hits -> 0.0 density.
    assert immunogenicity_proxy(SEQ) == pytest.approx(0.0)


def test_immunogenicity_proxy_all_hydrophobic():
    # 12 isoleucines: every 9-mer mean KD = 4.5 > 0.
    # windows = 12 - 9 + 1 = 4 ; density = 4 / 12.
    seq = "I" * 12
    assert immunogenicity_proxy(seq) == pytest.approx(4.0 / 12.0)


def test_immunogenicity_proxy_too_short():
    # No 9-mer fits -> 0.0.
    assert immunogenicity_proxy("AAAA") == pytest.approx(0.0)


def test_empty_sequences_return_zero():
    assert ptm_site_density("") == 0.0
    assert phospho_site_density("") == 0.0
    assert disulfide_potential("") == 0.0
    assert disorder_fraction("") == 0.0
    assert topology_helix_frac("") == 0.0
    assert immunogenicity_proxy("") == 0.0
