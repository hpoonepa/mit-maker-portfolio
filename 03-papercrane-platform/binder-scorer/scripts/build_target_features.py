"""build_target_features.py — Build data/processed/target_features.csv.

Loads the 7 binding-domain constructs from data/raw/target_references.fasta and
4 domain-trimmed sequences sliced from full UniProt FASTAs under
data/raw/targets/, computes the sequence-based target-side features
(scorer.target_features), and writes the per-target feature table.

The target column uses normalized names matching the feature/labeled table
exactly: EGFR, FGFR2, IL7R, INSULINR, MDM2, MZB1, NIPAH, PD1, PDGFRB, PDL1, PMVK.

CAVEAT: these are SEQUENCE-BASED proxies (Chou-Fasman SS, no real structure).
pocket_volume/druggability are NaN (need structure+fpocket — a later upgrade).

Run: python3 scripts/build_target_features.py
"""

from __future__ import annotations

import csv
import os

from scorer.target_features import compute_target_features

ROOT = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "processed", "target_features.csv")

# Domain-trimmed full-length targets: (normalized_name, fasta_file, slice).
# Slices are 1-based inclusive residue ranges; None means use the whole chain.
#   MZB1   : 189aa, whole sequence is the soluble protein.
#   PDGFRB : 1106aa multidomain receptor — use the extracellular Ig-like region
#            (~residues 33-530), NOT the kinase domain.
#   PMVK   : 192aa, whole sequence.
#   NIPAH  : 602aa glycoprotein G — use the C-terminal globular head (~180-602),
#            the binder target.
_TRIMMED = [
    ("MZB1", "MZB1_Q8WU39_full.fasta", None),
    ("PDGFRB", "PDGFRB_P09619_full.fasta", (33, 530)),
    ("PMVK", "PMVK_Q15126_full.fasta", None),
    ("NIPAH", "NIPAH_Q9IH62_full.fasta", (180, 602)),
]

_FIELDS = [
    "target",
    "log_length",
    "disorder_fraction",
    "frac_helix",
    "frac_strand",
    "frac_loop",
    "pocket_volume",
    "druggability",
    "epitope_hydrophobicity",
    "epitope_net_charge",
    "frac_polar",
    "interface_class",
]


def _read_fasta_seq(path: str) -> str:
    return "".join(
        line.strip() for line in open(path) if not line.startswith(">")
    )


def _load_reference_constructs(path: str) -> dict[str, str]:
    """Parse target_references.fasta -> {normalized_target: sequence}."""
    out: dict[str, str] = {}
    name = None
    buf: list[str] = []
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if name is not None:
                    out[name] = "".join(buf)
                # header form: >EGFR|P00533|310-510|description
                name = line[1:].split("|", 1)[0].strip().upper()
                buf = []
            else:
                buf.append(line.strip())
        if name is not None:
            out[name] = "".join(buf)
    return out


def _slice(seq: str, rng) -> str:
    if rng is None:
        return seq
    start, end = rng  # 1-based inclusive
    return seq[start - 1: end]


def build_rows() -> list[dict]:
    sequences: dict[str, str] = {}
    sequences.update(_load_reference_constructs(
        os.path.join(RAW, "target_references.fasta")))
    for name, fname, rng in _TRIMMED:
        full = _read_fasta_seq(os.path.join(RAW, "targets", fname))
        sequences[name] = _slice(full, rng)

    rows = []
    for target in sorted(sequences):
        feats = compute_target_features(sequences[target])
        row = {"target": target}
        for f in _FIELDS[1:]:
            row[f] = feats[f]
        rows.append(row)
    return rows


def _fmt(v) -> str:
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        return f"{v:.6g}"
    return str(v)


def main() -> None:
    rows = build_rows()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r[k]) for k in _FIELDS})

    # Eyeball the table — interface_class distribution especially.
    print(f"Wrote {OUT}  ({len(rows)} targets)\n")
    hdr = f"{'target':<10}{'logL':>6}{'helix':>7}{'strand':>7}{'loop':>7}" \
          f"{'disord':>8}{'hydroph':>9}{'netchg':>8}{'polar':>7}  interface_class"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['target']:<10}"
              f"{r['log_length']:>6.2f}"
              f"{r['frac_helix']:>7.2f}"
              f"{r['frac_strand']:>7.2f}"
              f"{r['frac_loop']:>7.2f}"
              f"{r['disorder_fraction']:>8.2f}"
              f"{r['epitope_hydrophobicity']:>9.2f}"
              f"{r['epitope_net_charge']:>8.3f}"
              f"{r['frac_polar']:>7.2f}"
              f"  {r['interface_class']}")
    from collections import Counter
    dist = Counter(r["interface_class"] for r in rows)
    print("\ninterface_class distribution:", dict(dist))


if __name__ == "__main__":
    main()
