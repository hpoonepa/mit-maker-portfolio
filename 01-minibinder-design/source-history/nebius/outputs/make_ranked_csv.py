#!/usr/bin/env python3
"""Merge epitope-contact analysis with Boltz2 metrics and rank:
designs hitting all 3 hotspots first, ordered by min_ipSAE (validated best
binding predictor), then the remainder by hit-count then min_ipSAE.
"""
import csv, os
HERE = os.path.dirname(os.path.abspath(__file__))

# Boltz2 validation metrics (from each fold's CSV: line). V5 designs were NOT
# re-folded (local structure reused) -> no comparable Boltz2 numbers.
B2 = {  # name: (plddt, iptm, bt_ipsae, tb_ipsae, min_ipsae)
 "5G51_ext_seq04": (0.9402,0.7635,0.5766,0.3327,0.3327),
 "5G51_ext_seq51": (0.9519,0.7715,0.5473,0.3128,0.3128),
 "5G51_ext_seq60": (0.9040,0.8895,0.7873,0.8311,0.7873),
 "5G51_ext_seq93": (0.9511,0.6836,0.4601,0.2881,0.2881),
 "5G51_ext_seq99": (0.8999,0.4915,0.2208,0.2009,0.2009),
 "5G51_V3b_seed24": (0.8126,0.4902,0.2175,0.1918,0.1918),
 "5G51_V3b_seed29_cysfree": (0.8644,0.7229,0.2930,0.4754,0.2930),
 "5G51_V4_seed01": (0.9719,0.9568,0.8670,0.9282,0.8670),
 "5G51_V4_seed05_cysfree": (0.9809,0.9619,0.8012,0.9395,0.8012),
 "5G51_V4_seed06": (0.9712,0.9567,0.8533,0.9293,0.8533),
 "5G51_V4_seed17": (0.9563,0.9492,0.8190,0.9211,0.8190),
 "5G51_V4_seed37_cysfree": (0.9368,0.9126,0.8105,0.7983,0.7983),
}

contacts = {r["name"]: r for r in csv.DictReader(open(os.path.join(HERE, "5g51_all15_hotspot_contacts.csv")))}
order = {r["name"]: r for r in csv.DictReader(open(os.path.join(HERE, "5g51_combined_order.csv")))}

rows = []
for name, c in contacts.items():
    b = B2.get(name)
    hit = int(c["hotspots_hit"])
    minip = b[4] if b else None
    rows.append({
        "name": name,
        "campaign": order[name]["campaign"],
        "hotspots_hit_of_3": hit,
        "d_I405": c["d_I405"], "d_F408": c["d_F408"], "d_I411": c["d_I411"],
        "frac_epitope": c["frac_epitope"], "n_contacts": c["n_contacts"],
        "boltz2_iptm": b[1] if b else "", "boltz2_bt_ipsae": b[2] if b else "",
        "boltz2_tb_ipsae": b[3] if b else "", "boltz2_min_ipsae": minip if minip is not None else "",
        "boltz2_plddt": b[0] if b else "",
        "boltz2_validated": "yes" if b else "no (design-pipeline only)",
        "_sortmin": minip if minip is not None else -1.0,
    })

# rank: all-3 first, then by min_ipSAE desc, then hit-count desc as tiebreak
rows.sort(key=lambda r: (-(r["hotspots_hit_of_3"] == 3), -r["hotspots_hit_of_3"], -r["_sortmin"]))
for i, r in enumerate(rows, 1):
    r["rank"] = i
    del r["_sortmin"]

cols = ["rank", "name", "campaign", "hotspots_hit_of_3", "boltz2_min_ipsae",
        "boltz2_iptm", "boltz2_bt_ipsae", "boltz2_tb_ipsae", "boltz2_plddt",
        "frac_epitope", "n_contacts", "d_I405", "d_F408", "d_I411", "boltz2_validated"]
out = os.path.join(HERE, "5g51_ranked_by_epitope.csv")
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print("wrote", out, "\n")
print(f"{'#':>2} {'design':>26}{'hit':>4}{'min_ipSAE':>10}{'ipTM':>7}{'%epi':>6}  val")
for r in rows:
    print(f"{r['rank']:>2} {r['name']:>26}{r['hotspots_hit_of_3']:>4}"
          f"{str(r['boltz2_min_ipsae']):>10}{str(r['boltz2_iptm']):>7}{str(r['frac_epitope']):>6}  {r['boltz2_validated']}")
