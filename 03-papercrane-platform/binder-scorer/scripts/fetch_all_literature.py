"""fetch_all_literature.py — Cache per-target literature for the 11 targets.

Calls scorer.literature.gather_literature for each well-powered target, using
the canonical feature-table target names as cache keys (so the cached JSON at
data/processed/literature/{TARGET}.json lines up with the feature/labeled
tables). Prints a summary table and FLAGS targets with thin literature
(<3 abstracts retrieved).

Run: python3 scripts/fetch_all_literature.py
"""

from __future__ import annotations

from scorer.literature import gather_literature

# (canonical_name, uniprot, [synonyms]) — names match the feature table keys.
TARGETS = [
    ("EGFR", "P00533", ["EGFR", "ERBB1", "HER1"]),
    ("FGFR2", "P21802", ["FGFR2", "KGFR", "BEK"]),
    ("IL7R", "P16871", ["IL7R", "IL7RA", "CD127"]),
    ("INSULINR", "P06213", ["INSR", "CD220", "insulin receptor"]),
    ("MDM2", "Q00987", ["MDM2", "HDM2"]),
    ("PDL1", "Q9NZQ7", ["PD-L1", "CD274", "B7-H1"]),
    ("PD1", "Q15116", ["PD-1", "PDCD1", "CD279"]),
    ("MZB1", "Q8WU39", ["MZB1", "pERp1"]),
    ("PDGFRB", "P09619", ["PDGFRB", "PDGFR beta", "CD140b"]),
    ("PMVK", "Q15126", ["phosphomevalonate kinase"]),
    ("NIPAH", "Q9IH62",
     ["Nipah virus glycoprotein G", "Nipah attachment glycoprotein", "NiV-G"]),
]


def main() -> None:
    rows = []
    for name, uniprot, synonyms in TARGETS:
        lit = gather_literature(name, synonyms, uniprot)
        n_abs = len(lit.get("abstracts", []))
        ot = lit.get("open_targets", {}) or {}
        n_ot = len(ot)
        rows.append((name, n_abs, n_ot))

    hdr = f"{'target':<10}{'#abstracts':>12}{'#open_targets':>15}  flag"
    print(hdr)
    print("-" * len(hdr))
    thin = []
    for name, n_abs, n_ot in rows:
        flag = "THIN (<3)" if n_abs < 3 else ""
        if n_abs < 3:
            thin.append(name)
        print(f"{name:<10}{n_abs:>12}{n_ot:>15}  {flag}")

    print()
    if thin:
        print(f"FLAGGED thin literature ({len(thin)}): {', '.join(thin)}")
    else:
        print("No thin-literature targets — all >= 3 abstracts.")


if __name__ == "__main__":
    main()
