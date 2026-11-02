#!/usr/bin/env python3
"""Run ~/Downloads/analyze_hotspot_contacts.py's contact math over ALL 15
ordered 5G51 binders (3 local V5 + 12 Boltz2-folded order complexes).

Reuses that script's analyze()/HOTSPOTS/EPITOPE_POS verbatim; just supplies the
paired <pdb>.csv each design needs (sequence from 5g51_combined_order.csv) and
maps each PDB back to its order-CSV design name.
Run: uv run --no-project --with gemmi --with numpy python run_hotspot_contacts_all.py
"""
import csv, importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/Downloads/analyze_hotspot_contacts.py")
ORDER = os.path.join(HERE, "5g51_combined_order.csv")

spec = importlib.util.spec_from_file_location("ahc", SRC)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

# design name -> (seq, seed)
order = {r["name"]: (r["sequence"].strip(), r["seed"]) for r in csv.DictReader(open(ORDER))}

# name -> complex pdb path
V5 = {"5G51_V5_seed00_rank2": "5g51_v5_hotspots/seed_000/seed_000_complex.pdb",
      "5G51_V5_seed07_rank3": "5g51_v5_hotspots/seed_007/seed_007_complex.pdb",
      "5G51_V5_seed10_rank4": "5g51_v5_hotspots/seed_010/seed_010_complex.pdb"}
paths = {}
for name in order:
    if name in V5:
        paths[name] = os.path.join(HERE, V5[name])
    else:
        p = os.path.join(HERE, "5g51_order_complexes", name, "complex.pdb")
        if os.path.exists(p):
            paths[name] = p

rows = []
for name, (seq, seed) in order.items():
    p = paths.get(name)
    if not p:
        rows.append({"name": name, "missing": True}); continue
    # write the paired <pdb>.csv analyze() reads for the binder sequence
    with open(os.path.splitext(p)[0] + ".csv", "w", newline="") as f:
        f.write("seed,sequence,iptm\n%s,%s,\n" % (seed, seq))
    rec = m.analyze(p, {})
    if rec is None:
        rows.append({"name": name, "missing": "analyze-failed"}); continue
    rec["name"] = name
    rows.append(rec)

# write combined csv
cols = ["name", "hotspots_hit", "d_I405", "d_F408", "d_I411", "frac_epitope",
        "n_contacts", "contact_mode", "contacted_PDBnums"]
out = os.path.join(HERE, "5g51_all15_hotspot_contacts.csv")
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
    for r in rows:
        if not r.get("missing"):
            w.writerow(r)

print(f"analyzed {sum(1 for r in rows if not r.get('missing'))}/15 -> {out}\n")
print(f"{'design':>26}{'hit/3':>6}{'I405':>7}{'F408':>7}{'I411':>7}{'%epi':>6}{'nC':>4}")
for r in rows:
    if r.get("missing"):
        print(f"{r['name']:>26}   --- {r['missing']} ---"); continue
    print(f"{r['name']:>26}{r['hotspots_hit']:>6}{str(r['d_I405']):>7}{str(r['d_F408']):>7}"
          f"{str(r['d_I411']):>7}{str(r['frac_epitope']):>6}{r['n_contacts']:>4}")
