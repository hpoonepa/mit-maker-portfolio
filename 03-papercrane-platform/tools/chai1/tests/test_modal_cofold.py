"""Co-fold resolution tests for the Chai-1 Modal app.

Exercises `_resolve_chains()` — the pure helper `papercrane_dispatch` uses to
build the `chains` list from a merged params dict. RCSB fetches are mocked by
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
        "chai1_modal_app", TOOL_ROOT / "modal_app.py"
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
    chains = mod._resolve_chains(
        {
            "targetPdb": "1ABC",
            "targetChain": "A",
            "partnerPdb": "2XYZ",
            "partnerChain": "B",
        },
        {},
    )
    assert chains == [
        {"id": "A", "sequence": "SEQ_1ABC_A"},
        {"id": "B", "sequence": "SEQ_2XYZ_B"},
    ]


def test_target_seq_plus_partner_pdb_cofold(mod):
    chains = mod._resolve_chains(
        {"targetSeq": "MKTAY", "partnerPdb": "2XYZ"}, {}
    )
    assert chains == [
        {"id": "A", "sequence": "MKTAY"},
        {"id": "B", "sequence": "SEQ_2XYZ_ANY"},
    ]


def test_explicit_chains_passthrough(mod):
    supplied = [{"id": "A", "sequence": "AAAA"}, {"id": "L", "sequence": "CC"}]
    chains = mod._resolve_chains({"chains": supplied}, {})
    assert chains is supplied


def test_single_target_fallback(mod):
    chains = mod._resolve_chains({"targetSeq": "MKTAY"}, {})
    assert chains == [{"id": "A", "sequence": "MKTAY"}]


def test_no_inputs_falls_back_to_smoke(mod):
    chains = mod._resolve_chains({}, {})
    assert chains == [{"id": "A", "sequence": mod.SMOKE_SEQUENCE}]
