"""build_bio_features.py — Augment the labeled feature table with bio__ columns.

Reads data/processed/labeled_features.csv, computes the design-side (binder)
biology descriptors (scorer.biology_features) from each row's ``sequence``,
appends them as ``bio__*`` columns, and writes
data/processed/labeled_features_bio.csv (all original columns + the new ones).

Prints mean/min/max summary stats for each new column and confirms the row
count.

Run: python3 scripts/build_bio_features.py
"""

from __future__ import annotations

import csv
import os

from scorer.biology_features import BIO_FEATURE_FUNCS, compute_bio_features

ROOT = os.path.join(os.path.dirname(__file__), "..")
IN = os.path.join(ROOT, "data", "processed", "labeled_features.csv")
OUT = os.path.join(ROOT, "data", "processed", "labeled_features_bio.csv")

EXPECTED_ROWS = 5721

_NEW_COLS = [name for name, _ in BIO_FEATURE_FUNCS]


def _fmt(v: float) -> str:
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        return f"{v:.6g}"
    return str(v)


def main() -> None:
    with open(IN, newline="") as fh:
        reader = csv.DictReader(fh)
        in_fields = list(reader.fieldnames or [])
        rows = list(reader)

    if "sequence" not in in_fields:
        raise SystemExit("input is missing a 'sequence' column")

    out_fields = in_fields + _NEW_COLS
    sums = {c: 0.0 for c in _NEW_COLS}
    mins = {c: float("inf") for c in _NEW_COLS}
    maxs = {c: float("-inf") for c in _NEW_COLS}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields)
        w.writeheader()
        for row in rows:
            feats = compute_bio_features(row.get("sequence", "") or "")
            for c in _NEW_COLS:
                v = float(feats[c])
                sums[c] += v
                mins[c] = min(mins[c], v)
                maxs[c] = max(maxs[c], v)
                row[c] = _fmt(v)
            w.writerow(row)

    n = len(rows)
    print(f"Wrote {OUT}  ({n} rows, {len(out_fields)} columns)\n")

    name_w = max(len(c) for c in _NEW_COLS)
    print(f"{'column':<{name_w}}  {'mean':>12}  {'min':>12}  {'max':>12}")
    print("-" * (name_w + 2 + 12 * 3 + 4))
    for c in _NEW_COLS:
        mean = sums[c] / n if n else 0.0
        print(f"{c:<{name_w}}  {mean:>12.4f}  {mins[c]:>12.4f}  {maxs[c]:>12.4f}")

    print()
    if n == EXPECTED_ROWS:
        print(f"Row count OK: {n} == {EXPECTED_ROWS}")
    else:
        print(f"WARNING: row count {n} != expected {EXPECTED_ROWS}")


if __name__ == "__main__":
    main()
