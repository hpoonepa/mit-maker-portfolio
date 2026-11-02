# SPDX-License-Identifier: MIT
"""Tests for the numbering contract.

The whole codebase keys residues on ResidueKey. These tests pin the conversions
to and from every numbering scheme we touch, because the schemes genuinely
disagree: BoltzGen indexes binding-site residues by mmCIF label_seq_id while
BindCraft and RFdiffusion use author numbering.
"""

import pytest

from hotspot_preflight.residue import (
    ResidueKey,
    parse_hotspot_spec,
    to_rfdiffusion,
    to_bindcraft,
    to_boltzgen,
    HotspotParseError,
)


class TestResidueKey:
    def test_is_frozen(self):
        k = ResidueKey("A", 405)
        with pytest.raises(Exception):
            k.auth_seq_id = 406

    def test_is_hashable_and_usable_as_dict_key(self):
        d = {ResidueKey("A", 405): "ile"}
        assert d[ResidueKey("A", 405)] == "ile"

    def test_equality_ignores_nothing(self):
        assert ResidueKey("A", 405) == ResidueKey("A", 405)
        assert ResidueKey("A", 405) != ResidueKey("B", 405)
        assert ResidueKey("A", 405) != ResidueKey("A", 408)

    def test_default_icode_is_blank_space(self):
        """mmCIF uses a single space, not empty string, for no insertion code."""
        assert ResidueKey("A", 405).icode == " "

    def test_icode_distinguishes_residues(self):
        assert ResidueKey("A", 52) != ResidueKey("A", 52, "A")

    def test_sorts_by_chain_then_number(self):
        keys = [ResidueKey("B", 10), ResidueKey("A", 20), ResidueKey("A", 10)]
        assert sorted(keys) == [
            ResidueKey("A", 10),
            ResidueKey("A", 20),
            ResidueKey("B", 10),
        ]

    def test_str_omits_blank_icode(self):
        assert str(ResidueKey("A", 405)) == "A405"

    def test_str_includes_real_icode(self):
        assert str(ResidueKey("A", 52, "A")) == "A52A"


class TestParseHotspotSpec:
    def test_single_residue(self):
        assert parse_hotspot_spec("A405") == [ResidueKey("A", 405)]

    def test_comma_separated(self):
        assert parse_hotspot_spec("A405,A408") == [
            ResidueKey("A", 405),
            ResidueKey("A", 408),
        ]

    def test_range_expands_inclusive(self):
        assert parse_hotspot_spec("A405-407") == [
            ResidueKey("A", 405),
            ResidueKey("A", 406),
            ResidueKey("A", 407),
        ]

    def test_mixed_ranges_and_singles_across_chains(self):
        assert parse_hotspot_spec("A405-406,B12") == [
            ResidueKey("A", 405),
            ResidueKey("A", 406),
            ResidueKey("B", 12),
        ]

    def test_bracketed_rfdiffusion_style(self):
        assert parse_hotspot_spec("[A30,A33]") == [
            ResidueKey("A", 30),
            ResidueKey("A", 33),
        ]

    def test_whitespace_tolerated(self):
        assert parse_hotspot_spec(" A405 , A408 ") == [
            ResidueKey("A", 405),
            ResidueKey("A", 408),
        ]

    def test_insertion_code_parsed(self):
        assert parse_hotspot_spec("A52A") == [ResidueKey("A", 52, "A")]

    def test_deduplicates_preserving_order(self):
        assert parse_hotspot_spec("A405,A405") == [ResidueKey("A", 405)]

    def test_multicharacter_chain_id(self):
        """mmCIF auth_asym_id can exceed one character; PDB format cannot."""
        assert parse_hotspot_spec("AA405") == [ResidueKey("AA", 405)]

    def test_negative_residue_number(self):
        """Author numbering legitimately goes negative, e.g. expression tags."""
        assert parse_hotspot_spec("A-3") == [ResidueKey("A", -3)]

    def test_bare_integer_is_rejected(self):
        """A number with no chain is the bug class this contract exists to stop."""
        with pytest.raises(HotspotParseError, match="chain"):
            parse_hotspot_spec("405")

    def test_empty_spec_is_rejected(self):
        with pytest.raises(HotspotParseError):
            parse_hotspot_spec("")

    def test_garbage_is_rejected(self):
        with pytest.raises(HotspotParseError):
            parse_hotspot_spec("not-a-residue")

    def test_backwards_range_is_rejected(self):
        with pytest.raises(HotspotParseError, match="range"):
            parse_hotspot_spec("A408-405")

    def test_range_across_chains_is_rejected(self):
        with pytest.raises(HotspotParseError):
            parse_hotspot_spec("A405-B408")


class TestEmitters:
    KEYS = [ResidueKey("A", 30), ResidueKey("A", 33), ResidueKey("B", 12)]

    def test_rfdiffusion_format(self):
        assert to_rfdiffusion(self.KEYS) == "[A30,A33,B12]"

    def test_bindcraft_format_collapses_runs(self):
        keys = [ResidueKey("A", 30), ResidueKey("A", 31), ResidueKey("A", 32)]
        assert to_bindcraft(keys) == "A30-32"

    def test_bindcraft_format_mixed(self):
        assert to_bindcraft(self.KEYS) == "A30,A33,B12"

    def test_boltzgen_requires_label_seq_mapping(self):
        """BoltzGen uses label_seq_id, so emitting it without a map is an error,
        not a silent pass-through of author numbers."""
        with pytest.raises(ValueError, match="label_seq"):
            to_boltzgen(self.KEYS, label_seq_map=None)

    def test_boltzgen_uses_mapped_label_seq(self):
        mapping = {
            ResidueKey("A", 30): 15,
            ResidueKey("A", 33): 18,
            ResidueKey("B", 12): 4,
        }
        assert to_boltzgen(self.KEYS, label_seq_map=mapping) == "A15,A18,B4"

    def test_boltzgen_missing_key_raises(self):
        with pytest.raises(KeyError):
            to_boltzgen(self.KEYS, label_seq_map={ResidueKey("A", 30): 15})

    def test_emitters_reject_empty(self):
        for fn in (to_rfdiffusion, to_bindcraft):
            with pytest.raises(ValueError):
                fn([])

    def test_rfdiffusion_rejects_insertion_codes(self):
        """RFdiffusion's hotspot syntax has no place for an insertion code, so we
        refuse rather than silently dropping it and aiming at the wrong residue."""
        with pytest.raises(ValueError, match="insertion code"):
            to_rfdiffusion([ResidueKey("A", 52, "A")])


class TestRoundTrip:
    @pytest.mark.parametrize(
        "spec", ["A405", "A405,A408", "A30-33", "A1,B2,C3", "A-3", "AA405"]
    )
    def test_parse_then_rfdiffusion_then_parse_is_stable(self, spec):
        once = parse_hotspot_spec(spec)
        twice = parse_hotspot_spec(to_rfdiffusion(once))
        assert once == twice
