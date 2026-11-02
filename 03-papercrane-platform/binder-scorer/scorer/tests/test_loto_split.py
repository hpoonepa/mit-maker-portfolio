from __future__ import annotations

import pytest

from scorer.loto_split import loto_folds, well_powered_targets


def _mk(target, binds, i):
    return {"design_id": f"{target}:{binds}:{i}", "target": target, "binds": binds}


def _synth():
    designs = []
    # T_A: well-powered (10 pos, 10 neg)
    for i in range(10):
        designs.append(_mk("A", True, i))
        designs.append(_mk("A", False, i))
    # T_B: well-powered (12 pos, 11 neg)
    for i in range(12):
        designs.append(_mk("B", True, i))
    for i in range(11):
        designs.append(_mk("B", False, i))
    # T_C: under-powered (3 pos, 30 neg) -> valid train, never test
    for i in range(3):
        designs.append(_mk("C", True, i))
    for i in range(30):
        designs.append(_mk("C", False, i))
    return designs


def test_well_powered_requires_10_pos_and_10_neg():
    wp = well_powered_targets(_synth())
    assert wp == {"A", "B"}


def test_loto_yields_one_fold_per_well_powered_target():
    folds = list(loto_folds(_synth()))
    targets = sorted(t for t, _, _ in folds)
    assert targets == ["A", "B"]


def test_test_fold_is_only_that_target_train_is_everything_else():
    folds = {t: (tr, te) for t, tr, te in loto_folds(_synth())}
    tr_a, te_a = folds["A"]
    assert all(d["target"] == "A" for d in te_a)
    assert all(d["target"] != "A" for d in tr_a)
    # train includes under-powered C
    assert any(d["target"] == "C" for d in tr_a)
    # partition is complete: train + test == all designs
    assert len(tr_a) + len(te_a) == len(_synth())


def test_underpowered_target_never_becomes_a_test_fold():
    folds = list(loto_folds(_synth()))
    assert "C" not in {t for t, _, _ in folds}


def test_empty_input_yields_no_folds():
    assert list(loto_folds([])) == []
