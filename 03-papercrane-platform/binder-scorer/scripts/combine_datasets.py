"""Combine the labeled de-novo binder datasets into one table and count
targets / sequences usable for testing.

Sources (raw files under data/raw/, gitignored):
  - overath.csv       (Overath 2025 "Binder Design Dataset"): label col `binder` True/False, binder seq `A_seq`
  - proteinbase.csv   (Proteinbase 28 Jan 2026): label in nested `evaluations` JSON (experimental/binding), seq `sequence`
  - bindcraft.csv     (BindCraft SI Table 1): label col `Binding` 1/0, seq `Sequence`
  - ppb_affinity.xlsx (PPB-Affinity): natural-PPI affinity (Kd) — TRANSFER/auxiliary, NOT a binary binding test set

Run: python3 scripts/combine_datasets.py
"""
import csv
import json
import re
import collections
import os

csv.field_size_limit(10 ** 7)
RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "combined_labeled.csv")

# --- target name normalisation across sources -----------------------------
_ALIASES = {
    "egfr": "EGFR", "egfrecd": "EGFR",
    "il7r": "IL7R", "il7ra": "IL7R",
    "pdl1": "PDL1",
    "mdm2": "MDM2",
    "insulinr": "INSULINR", "insulinreceptor": "INSULINR", "insulinreceptorinsr": "INSULINR",
    "ifnar2": "IFNAR2",
    "spcas9": "SPCAS9",
    "her2": "HER2", "her2erbb2": "HER2",
    "pd1": "PD1", "pdcd1": "PD1",
    "fgfr2": "FGFR2",
    "fgfr1": "FGFR1", "fgfrbeta1": "FGFR1",
    "nipah": "NIPAH", "nipahglycoproteing": "NIPAH",
    "trka": "TRKA", "trkantrk1": "TRKA",
    "virb8": "VIRB8",
    "sarscov2rbd": "SARS_RBD", "sarscov2spikerbd": "SARS_RBD",
    "il2ra": "IL2RA",
    "sntx": "SNTX",
    "ltk": "LTK",
    "il10ra": "IL10RA",
    "pdgfrbeta": "PDGFRB",
    "tnfa": "TNFA",
    "serumalbumin": "HSA", "humanserumalbumin": "HSA",
    "fcrn": "FCRN",
    "gm2a": "GM2A", "orm2": "ORM2", "mzb1": "MZB1", "mzb1perp1": "MZB1",
    "idi2": "IDI2", "hnmt": "HNMT", "pmvk": "PMVK", "rfk": "RFK",
    "ambp": "AMBP", "phyh": "PHYH",
    "der7": "DER7", "derf7": "DER7", "der21": "DER21", "derf21": "DER21",
    "cldn1": "CLDN1", "cbago": "CBAGO", "sas6": "SAS6", "bbf14": "BBF14", "betv1": "BETV1",
    "pmhcsilsy1": "PMHC_SILSY", "pmhcny1": "PMHC_NY",
}


def norm_target(name):
    s = (name or "").strip().lower()
    s = s.replace("human-", "").replace("human_", "")
    s = re.sub(r"[^a-z0-9]", "", s)
    if not s:
        return None
    return _ALIASES.get(s, s.upper())


def to_bool(v):
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "binder", "pos", "positive"):
        return True
    if s in ("false", "0", "no", "n", "nonbinder", "neg", "negative"):
        return False
    return None


# --- loaders: each yields dicts {source, target, sequence, binds} ----------
def load_overath():
    rows = []
    with open(os.path.join(RAW, "overath.csv"), newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            seq = (r.get("A_seq") or "").strip().upper()
            b = to_bool(r.get("binder"))
            t = norm_target(r.get("target_id"))
            if seq and t and b is not None:
                rows.append({"source": "overath", "target": t, "sequence": seq, "binds": b})
    return rows


def load_bindcraft():
    rows = []
    with open(os.path.join(RAW, "bindcraft.csv"), newline="", encoding="utf-8-sig", errors="replace") as fh:
        for r in csv.DictReader(fh):
            seq = (r.get("Sequence") or "").strip().upper()
            b = to_bool(r.get("Binding"))
            t = norm_target(r.get("Target"))
            if seq and t and b is not None:
                rows.append({"source": "bindcraft", "target": t, "sequence": seq, "binds": b})
    return rows


def _majority(bools, tie_true=True):
    """Resolve replicate boolean measurements. Majority wins; tie -> tie_true."""
    if not bools:
        return None
    t = sum(1 for b in bools if b)
    f = len(bools) - t
    if t > f:
        return True
    if f > t:
        return False
    return tie_true  # tie: a measured bind is meaningful signal


def load_proteinbase():
    """Proteinbase designs carry MULTIPLE experimental binding evals (replicates).
    Label = majority of binding booleans, conditioned on expression
    (P(binds | expressed)): drop designs that did not express, since an
    expression failure is not a tested non-binder."""
    rows = []
    with open(os.path.join(RAW, "proteinbase.csv"), newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            seq = (r.get("sequence") or "").strip().upper()
            ev = r.get("evaluations", "")
            if not seq or not ev or ev in ("[]", "null"):
                continue
            try:
                evals = json.loads(ev)
            except Exception:
                continue
            binding_bools, expressed_bools, target = [], [], None
            for e in evals:
                if not isinstance(e, dict) or e.get("type") != "experimental":
                    continue
                m = e.get("metric")
                if m == "binding":
                    b = to_bool(e.get("value"))
                    if b is not None:
                        binding_bools.append(b)
                        if target is None and e.get("target"):
                            target = norm_target(e.get("target"))
                elif m == "expressed":
                    eb = to_bool(e.get("value"))
                    if eb is not None:
                        expressed_bools.append(eb)
            if target is None:
                for e in evals:
                    if isinstance(e, dict) and e.get("target"):
                        target = norm_target(e.get("target"))
                        break
            # condition on expression: if expression was measured and failed, exclude
            expressed = _majority(expressed_bools, tie_true=True) if expressed_bools else True
            if not expressed:
                continue
            binds = _majority(binding_bools, tie_true=True)
            if seq and target and binds is not None:
                rows.append({"source": "proteinbase", "target": target, "sequence": seq, "binds": binds})
    return rows


def per_source_summary(name, rows):
    tg = collections.Counter(r["target"] for r in rows)
    pos = sum(1 for r in rows if r["binds"])
    neg = sum(1 for r in rows if not r["binds"])
    print(f"\n[{name}] labeled designs={len(rows)}  pos={pos}  neg={neg}  targets={len(tg)}")
    return tg


def main():
    over, bind, prot = load_overath(), load_bindcraft(), load_proteinbase()
    for n, rs in [("Overath", over), ("BindCraft", bind), ("Proteinbase", prot)]:
        per_source_summary(n, rs)

    # combine + dedup by sequence. A sequence may appear in multiple sources;
    # group all its labels and resolve: unanimous -> keep; conflicting -> DROP
    # (genuinely ambiguous across assays) and log it. Target taken from the
    # highest-priority source (overath > proteinbase > bindcraft).
    grouped = collections.defaultdict(list)
    for r in over + prot + bind:  # priority order preserved
        grouped[r["sequence"]].append(r)
    combined, conflicts = [], 0
    for seq, recs in grouped.items():
        labels = {rec["binds"] for rec in recs}
        if len(labels) > 1:
            conflicts += 1  # conflicting label across sources -> drop
            continue
        keep = recs[0]  # priority source provides source+target
        combined.append({"source": keep["source"], "target": keep["target"],
                         "sequence": seq, "binds": recs[0]["binds"]})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["source", "target", "sequence", "binds"])
        w.writeheader()
        w.writerows(combined)

    # combined counts
    tg = collections.defaultdict(lambda: [0, 0])  # target -> [pos, neg]
    for r in combined:
        tg[r["target"]][0 if r["binds"] else 1] += 1
    pos = sum(1 for r in combined if r["binds"])
    neg = sum(1 for r in combined if not r["binds"])
    well = {t: pn for t, pn in tg.items() if pn[0] >= 10 and pn[1] >= 10}
    relaxed = {t: pn for t, pn in tg.items() if pn[0] >= 5 and pn[1] >= 5}

    print("\n" + "=" * 60)
    print("COMBINED LABELED DE-NOVO DATASET")
    print("=" * 60)
    print(f"unique sequences (deduped) : {len(combined)}")
    print(f"  positives (binders)      : {pos}")
    print(f"  negatives (non-binders)  : {neg}")
    print(f"distinct targets (union)   : {len(tg)}")
    print(f"label conflicts on dup seqs: {conflicts}")
    print(f"\nWELL-POWERED targets (>=10 pos & >=10 neg) = TESTABLE (LOTO folds): {len(well)}")
    for t, (p, n) in sorted(well.items(), key=lambda x: -x[1][0]):
        print(f"   {t:12s} pos={p:5d} neg={n:5d}")
    print(f"\nRELAXED testable (>=5 pos & >=5 neg): {len(relaxed)}")
    print("   " + ", ".join(sorted(relaxed)))
    print("\nALL targets (pos/neg):")
    for t, (p, n) in sorted(tg.items(), key=lambda x: -(x[1][0] + x[1][1])):
        flag = " <-- testable" if t in well else ""
        print(f"   {t:12s} pos={p:5d} neg={n:5d}{flag}")
    print(f"\nwrote {OUT}")
    print("\nNOTE: PPB-Affinity (~12,063 rows) is natural-PPI affinity (Kd), OFF-distribution —")
    print("      transfer/pretrain only, NOT counted in the de-novo binary test set above.")


if __name__ == "__main__":
    main()
