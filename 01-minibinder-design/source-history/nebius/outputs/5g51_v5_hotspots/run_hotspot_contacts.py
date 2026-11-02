#!/usr/bin/env python3
"""Drive ~/Downloads/analyze_hotspot_contacts.py over the local V5 complexes.

Reuses that script's exact contact math (analyze / HOTSPOTS / EPITOPE_POS) and
just repoints its data sources at this directory's seed_*/seed_*_complex.pdb.
Run: uv run --no-project --with gemmi --with numpy python run_hotspot_contacts.py
"""
import csv, glob, importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/Downloads/analyze_hotspot_contacts.py")

spec = importlib.util.spec_from_file_location("ahc", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

pdbs = sorted(glob.glob(os.path.join(HERE, "seed_*/seed_*_complex.pdb")))
rows = [r for r in (m.analyze(p, {}) for p in pdbs) if r]
rows.sort(key=lambda d: int(d["seed"]))

cols = ["seed", "rank", "iptm", "contact_mode", "hotspots_hit",
        "d_I405", "d_F408", "d_I411", "frac_epitope", "n_contacts",
        "contacted_PDBnums"]
out = os.path.join(HERE, "5g51_v5_hotspot_contacts.csv")
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)

print(f"analyzed {len(rows)} complexes -> {out}\n")
hdr = f"{'seed':>4}{'iptm':>7}{'mode':>9}{'hit/3':>6}{'I405':>7}{'F408':>7}{'I411':>7}{'%epi':>6}{'nC':>4}"
print(hdr)
for d in rows:
    print(f"{d['seed']:>4}{str(d['iptm'])[:5]:>7}{d['contact_mode']:>9}{d['hotspots_hit']:>6}"
          f"{str(d['d_I405']):>7}{str(d['d_F408']):>7}{str(d['d_I411']):>7}"
          f"{str(d['frac_epitope']):>6}{d['n_contacts']:>4}")
