"""Co-fold resolution tests for the Boltz-2 Modal app.

Exercises `_resolve_cofold()` — the pure helper `papercrane_dispatch` uses to
turn a merged params dict into (target_seq, binder_seq). RCSB fetches are
mocked by monkeypatching `_sequence_from_pdb`, so no network / GPU is touched.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

pytest.importorskip("modal")

TOOL_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "boltz2_modal_app", TOOL_ROOT / "modal_app.py"
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


def test_partner_pdb_becomes_binder(mod):
    target, binder = mod._resolve_cofold(
        {"targetSeq": "MKTAY", "partnerPdb": "1ABC", "partnerChain": "B"}, {}
    )
    assert target == "MKTAY"
    assert binder == "SEQ_1ABC_B"


def test_explicit_binder_beats_partner_pdb(mod):
    _, binder = mod._resolve_cofold(
        {"targetSeq": "MKTAY", "binderSeq": "GAAG", "partnerPdb": "1ABC"}, {}
    )
    assert binder == "GAAG"


def test_binders_list_beats_partner_pdb(mod):
    _, binder = mod._resolve_cofold(
        {
            "targetSeq": "MKTAY",
            "binders": [{"sequence": "LISTBINDER", "seed": 0}],
            "partnerPdb": "1ABC",
        },
        {},
    )
    assert binder == "LISTBINDER"


def test_no_partner_leaves_binder_none(mod):
    target, binder = mod._resolve_cofold({"targetSeq": "MKTAY"}, {})
    assert target == "MKTAY"
    assert binder is None


def test_target_pdb_honors_chain(mod):
    target, _ = mod._resolve_cofold({"targetPdb": "2XYZ", "targetChain": "A"}, {})
    assert target == "SEQ_2XYZ_A"


def test_target_falls_back_to_smoke(mod):
    target, binder = mod._resolve_cofold({}, {})
    assert target == mod.SMOKE_SEQUENCE
    assert binder is None
