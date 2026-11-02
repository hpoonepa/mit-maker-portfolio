"""Co-fold resolution tests for the AlphaFold3/Protenix Modal app.

Exercises `_resolve_input_str()` — the pure helper `papercrane_dispatch` uses
to build the input FASTA from a merged params dict. RCSB fetches are mocked by
monkeypatching `_sequence_from_pdb`, so no network / GPU is touched.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

pytest.importorskip("modal")

TOOL_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "alphafold3_modal_app", TOOL_ROOT / "modal_app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mod(monkeypatch):
    module = _load_module()

    def fake_seq_from_pdb(pdb_id, chain_id=None):
        if not pdb_id:
            return None
        return f"SEQ_{pdb_id}_{chain_id or 'ANY'}"

    monkeypatch.setattr(module, "_sequence_from_pdb", fake_seq_from_pdb)
    return module


def test_two_structure_cofold_builds_two_chains(mod):
    fasta = mod._resolve_input_str(
        {
            "targetPdb": "1ABC",
            "targetChain": "A",
            "partnerPdb": "2XYZ",
            "partnerChain": "B",
        },
        {},
    )
    assert ">protein|A" in fasta
    assert "SEQ_1ABC_A" in fasta
    assert ">protein|B" in fasta
    assert "SEQ_2XYZ_B" in fasta


def test_explicit_chains_passthrough(mod):
    fasta = mod._resolve_input_str(
        {"chains": [{"id": "A", "sequence": "AAAA"}, {"id": "B", "sequence": "CCCC"}]},
        {},
    )
    assert ">protein|A" in fasta and "AAAA" in fasta
    assert ">protein|B" in fasta and "CCCC" in fasta


def test_single_target_fasta(mod):
    fasta = mod._resolve_input_str({"targetSeq": "MKTAY"}, {})
    assert fasta == ">protein|A\nMKTAY\n"


def test_no_inputs_falls_back_to_smoke(mod):
    fasta = mod._resolve_input_str({}, {})
    assert fasta == mod.SMOKE_FASTA
