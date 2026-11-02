"""loto_split.py — Leave-One-Target-Out (LOTO) splitter (Task A3).

A target is a valid TEST fold only if it is "well-powered": it has at least
10 confirmed binders AND at least 10 confirmed non-binders. Under-powered and
relaxed targets remain valid TRAIN data — they are simply never held out as a
test fold (we cannot trust a Precision@k estimate on a handful of positives).

A design dict must carry at minimum a ``target`` key and a ``binds`` key whose
value is a real bool (``True`` => confirmed binder). Loading/parsing the CSV
(string "True"/"False" -> bool, design_id synthesis) happens upstream in the
data loader; this module is pure splitting logic so it stays trivially testable.
"""

from __future__ import annotations

from typing import Iterator, Mapping, Sequence

MIN_POS = 10
MIN_NEG = 10


def well_powered_targets(designs: Sequence[Mapping[str, object]]) -> set[str]:
    """Return the set of targets with >=10 positives AND >=10 negatives."""
    pos: dict[str, int] = {}
    neg: dict[str, int] = {}
    for d in designs:
        t = d["target"]
        if d.get("binds") is True:
            pos[t] = pos.get(t, 0) + 1
        else:
            neg[t] = neg.get(t, 0) + 1
    return {
        t
        for t in set(pos) | set(neg)
        if pos.get(t, 0) >= MIN_POS and neg.get(t, 0) >= MIN_NEG
    }


def loto_folds(
    designs: Sequence[Mapping[str, object]],
) -> Iterator[tuple[str, list, list]]:
    """Yield ``(target, train_designs, test_designs)`` for each well-powered target.

    test  = all designs whose ``target`` == the held-out target.
    train = ALL other designs (including under-powered/relaxed targets).
    Folds are yielded in sorted target order for determinism.
    """
    wp = well_powered_targets(designs)
    for target in sorted(wp):
        test = [d for d in designs if d["target"] == target]
        train = [d for d in designs if d["target"] != target]
        yield target, train, test
