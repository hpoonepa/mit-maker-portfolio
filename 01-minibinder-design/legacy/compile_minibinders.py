#!/usr/bin/env python3
"""Collect VP3 designs into a combined FASTA and a campaign report."""
import csv, os

ROOT = os.path.dirname(os.path.abspath(__file__))

def rd(path):
    with open(os.path.join(ROOT, path)) as f:
        return list(csv.DictReader(f))

def f(v, nd=3):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "—"

# ── Runs: (label, region/cluster, path, campaign) ──────────────────────────
C1 = [
    ("BoltzGen · C-term hotspot", "cterm",
     "campaign_5MV5/results/boltzgen_cterm/cterm/final_ranked_designs/all_designs_metrics.csv"),
    ("BoltzGen · N-term hotspot", "nterm",
     "campaign_5MV5/results/boltzgen_nterm/nterm/final_ranked_designs/all_designs_metrics.csv"),
    ("BoltzGen · N-term (extended 200)", "nterm-200",
     "campaign_5MV5/results/boltzgen_nterm_200/2603050101/final_ranked_designs/all_designs_metrics.csv"),
]
C2 = [
    ("RFdiff+BoltzGen · cluster1 (c62/c103/c124)", "cluster1",
     "campaign_5MV5_rfdiff/boltzgen_output/cluster1/final_ranked_designs/all_designs_metrics.csv"),
    ("RFdiff+BoltzGen · cluster2 (c114/c186/c237)", "cluster2",
     "campaign_5MV5_rfdiff/boltzgen_output/cluster2/final_ranked_designs/all_designs_metrics.csv"),
    ("RFdiff+BoltzGen · cluster3 (c250/c254)", "cluster3",
     "campaign_5MV5_rfdiff/boltzgen_output/cluster3/final_ranked_designs/all_designs_metrics.csv"),
    ("RFdiff+BoltzGen · top_bude_mixed", "top_bude_mixed",
     "campaign_5MV5_rfdiff/boltzgen_output/top_bude_mixed/final_ranked_designs/all_designs_metrics.csv"),
]

def load_designs(runs):
    out = []
    for label, tag, path in runs:
        rows = rd(path)
        recs = []
        for r in rows:
            seq = (r.get("designed_sequence") or r.get("designed_chain_sequence") or "").strip()
            if not seq:
                continue
            recs.append({
                "id": r.get("id", "").strip(),
                "seq": seq,
                "len": len(seq),
                "iptm": r.get("design_to_target_iptm", ""),
                "ptm": r.get("design_ptm", ""),
                "pae": r.get("min_design_to_target_pae", ""),
                "rmsd": r.get("filter_rmsd", ""),
                "dsasa": r.get("delta_sasa_refolded", ""),
            })
        recs.sort(key=lambda d: -(float(d["iptm"]) if d["iptm"] else 0))
        out.append((label, tag, path, recs))
    return out

c1_runs = load_designs(C1)
c2_runs = load_designs(C2)

# ── Validated / final candidate sets ───────────────────────────────────────
# Campaign 1: 9 QC-passing, Chai-1 cross-validated (has seq + chai1 metrics)
c1_val = rd("campaign_5MV5/results/chai1_validation_results.csv")
c1_val_by_seq = {r["sequence"].strip(): r for r in c1_val}

# Campaign 2: 20 selected for validation (id+seq+boltzgen metrics) joined with chai1
c2_cand = rd("campaign_5MV5_rfdiff/validation/candidates_for_validation.csv")
c2_chai = {r["design"].strip(): r for r in rd("campaign_5MV5_rfdiff/validation/chai1_validation_results.csv")}
c2_val_by_seq = {}
c2_final = []
for r in c2_cand:
    ch = c2_chai.get(r["id"].strip(), {})
    rec = {**r, "chai1_best_iptm": ch.get("chai1_best_iptm", ""),
           "chai1_avg_iptm": ch.get("chai1_avg_iptm", ""),
           "iptm_delta": ch.get("iptm_delta", "")}
    c2_final.append(rec)
    c2_val_by_seq[r["sequence"].strip()] = rec

val_seqs = set(c1_val_by_seq) | set(c2_val_by_seq)

def flag(seq):
    return "★" if seq in val_seqs else ""

# ── Ordered / sent set — mainsub1.csv (the actual submission) ───────────────
def rd_abs(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))

MAINSUB = "/Users/harsha/Downloads/mainsub1.csv"
NEB = "/Users/harsha/Desktop/claudeprojects/mosaic/nebius/outputs"
sent = rd_abs(MAINSUB)  # name, sequence (order = submission order)
tagp = {r["name"]: r for r in rd_abs(os.path.join(NEB, "mainsub1_tag_placement.csv"))}
epi = {}
_epi_path = os.path.join(NEB, "5g51_ranked_by_epitope.csv")
if os.path.exists(_epi_path):
    epi = {r["name"]: r for r in rd_abs(_epi_path)}

# ── Emit markdown ───────────────────────────────────────────────────────────
L = []
w = L.append
tot1 = sum(len(r[3]) for r in c1_runs)
tot2 = sum(len(r[3]) for r in c2_runs)

w("# VP3 (5MV5) Minibinder Campaign — Master Compilation\n")
w("Every minibinder designed against **VP3 (PDB 5MV5, chain C; 383 aa)** across both design campaigns, with metrics and full sequences. ★ marks a design carried forward to Chai-1 cross-validation (the closest thing to a \"final\" set — see note).\n")
w("## Overview\n")
w("| | Campaign 1 | Campaign 2 |")
w("|---|---|---|")
w("| Approach | BoltzGen all-atom diffusion, hotspot-guided | RFdiffusion backbones → BoltzGen inverse folding |")
w("| Hotspot targeting | N-term & C-term epitopes | 4 hotspot clusters (c62/c103/c124, c114/c186/c237, c250/c254, top_bude_mixed) |")
w(f"| Total designs | {tot1} | {tot2} |")
w("| Carried to Chai-1 validation | 9 (QC-passing) | 20 (top by composite) |")
w(f"\n**Grand total designed: {tot1 + tot2} minibinders** ({tot1} + {tot2}). Validated candidate set: {len(c1_val)} + {len(c2_final)} = {len(c1_val)+len(c2_final)}.\n")
w("**QC thresholds (campaign 1):** ipTM ≥ 0.50 · PAE_interface ≤ 10.0 Å · pTM ≥ 0.80 · scRMSD ≤ 2.0 Å.\n")
w("> **The set actually sent** is in Section 0 below (`mainsub1.csv`, 15 binders). Sections 1–2 are the broader design campaign these were selected from. Chai-1 cross-validation scored the campaign candidates **weak-to-moderate** (ipTM dropped vs BoltzGen's self-estimate), shown per-design.\n")

# ── Section 0: the actual ordered / sent set (mainsub1) ─────────────────────
w("---\n\n## 0. ⭐ Ordered / sent — the actual submission (`mainsub1.csv`)\n")
w(f"The **{len(sent)} binders actually sent**, in submission order. Source: `/Users/harsha/Downloads/mainsub1.csv` (target 5G51). Tag placement from `mainsub1_tag_placement.csv`; Boltz2 epitope scores from `5g51_ranked_by_epitope.csv` where available (the V4 seeds — the condF/orig/latent designs weren't in that scoring run).\n")
w("| # | Name | Len | Tag end | Buried-end Å | Boltz2 ipSAE | ipTM | Hotspots/3 | Validated |")
w("|---|------|-----|---------|--------------|--------------|------|-----------|-----------|")
for i, r in enumerate(sent, 1):
    name = r["name"].strip(); seq = (r.get("sequence") or "").strip()
    t = tagp.get(name, {}); e = epi.get(name, {})
    w(f"| {i} | {name} | {len(seq)} | {t.get('tag_terminus','—')} | {f(t.get('buried_end_dist'),1)} | "
      f"{f(e.get('boltz2_min_ipsae')) if e.get('boltz2_min_ipsae') else '—'} | "
      f"{f(e.get('boltz2_iptm')) if e.get('boltz2_iptm') else '—'} | "
      f"{e.get('hotspots_hit_of_3','—')} | {e.get('boltz2_validated','—')} |")
w("\n```")
for r in sent:
    name = r["name"].strip(); seq = (r.get("sequence") or "").strip()
    w(f">{name} ({len(seq)}aa)")
    w(seq)
w("```\n")

# ── Section 1: finals ───────────────────────────────────────────────────────
w("---\n\n## 1. VP3 campaign — final / validated candidates\n")

w("### 1a. Campaign 1 — BoltzGen direct · 9 QC-passing (ranked by BoltzGen ipTM)\n")
w("| # | ID | Region | Len | BoltzGen ipTM | pTM | PAE | RMSD | Chai-1 ipTM | Chai-1 assess |")
w("|---|----|--------|-----|---------------|-----|-----|------|-------------|---------------|")
# order by campaign summary ipTM (BoltzGen). pull boltzgen metrics from run recs by id
c1_metrics = {d["id"]: d for _,_,_,recs in c1_runs for d in recs}
c1_order = ["boltzgen_cterm_28","boltzgen_cterm_36","boltzgen_cterm_49","boltzgen_nterm_44",
            "boltzgen_cterm_30","boltzgen_nterm_43","boltzgen_nterm_42","boltzgen_nterm_49","boltzgen_nterm_39"]
for i, cid in enumerate(c1_order, 1):
    m = c1_metrics.get(cid, {})
    v = c1_val_by_seq.get(m.get("seq",""), {})
    region = "C-term" if "cterm" in cid else "N-term"
    w(f"| {i} | {cid} | {region} | {m.get('len','—')} | {f(m.get('iptm'))} | {f(m.get('ptm'))} | {f(m.get('pae'),2)} | {f(m.get('rmsd'),2)} | {f(v.get('chai1_best_iptm'))} | {v.get('assessment','—')} |")
w("\n```")
for cid in c1_order:
    m = c1_metrics.get(cid, {})
    w(f">{cid} ({m.get('len','?')}aa)")
    w(m.get("seq",""))
w("```\n")

w("### 1b. Campaign 2 — RFdiffusion+BoltzGen · 20 selected (ranked by composite score)\n")
w("| # | ID | Cluster | Len | BoltzGen ipTM | Composite | Chai-1 ipTM | ipTM Δ |")
w("|---|----|---------|-----|---------------|-----------|-------------|--------|")
for i, r in enumerate(c2_final, 1):
    w(f"| {i} | {r['id']} | {r['cluster']} | {r['length']} | {f(r.get('iptm'))} | {f(r.get('composite_score'))} | {f(r.get('chai1_best_iptm'))} | {f(r.get('iptm_delta'),3)} |")
w("\n```")
for r in c2_final:
    w(f">{r['id']} ({r['length']}aa)")
    w(r["sequence"].strip())
w("```\n")

# ── Section 2: all designs ──────────────────────────────────────────────────
w("---\n\n## 2. All designs (complete)\n")
w("Every generated minibinder with sequence + metrics, grouped by run and ranked by ipTM (BoltzGen self-estimate). ★ = in a validated set above.\n")

def emit_run(label, tag, path, recs):
    w(f"\n### {label} — {len(recs)} designs\n")
    w(f"<sub>`{path}`</sub>\n")
    w("| ★ | ID | Len | ipTM | pTM | PAE | RMSD | dSASA | Sequence |")
    w("|---|----|-----|------|-----|-----|------|-------|----------|")
    for d in recs:
        w(f"| {flag(d['seq'])} | {d['id']} | {d['len']} | {f(d['iptm'])} | {f(d['ptm'])} | {f(d['pae'],2)} | {f(d['rmsd'],2)} | {f(d['dsasa'],0)} | `{d['seq']}` |")

w("\n## Campaign 1 — BoltzGen direct\n")
for run in c1_runs:
    emit_run(*run)
w("\n## Campaign 2 — RFdiffusion + BoltzGen\n")
for run in c2_runs:
    emit_run(*run)

doc = "\n".join(L) + "\n"
out_md = os.path.join(ROOT, "VP3_5MV5_all_minibinders.md")
with open(out_md, "w") as fh:
    fh.write(doc)

# ── Companion: combined FASTA of every design ───────────────────────────────
fa = []
for r in sent:
    name = r["name"].strip(); seq = (r.get("sequence") or "").strip()
    fa.append(f">{name} len={len(seq)} ORDERED_SENT")
    fa.append(seq)
for _, tag, _, recs in c1_runs + c2_runs:
    for d in recs:
        star = " validated" if d["seq"] in val_seqs else ""
        fa.append(f">{d['id']} len={d['len']} iptm={f(d['iptm'])}{star}")
        fa.append(d["seq"])
out_fa = os.path.join(ROOT, "VP3_5MV5_all_minibinders.fasta")
with open(out_fa, "w") as fh:
    fh.write("\n".join(fa) + "\n")

print(f"Campaign 1: {tot1} designs across {len(c1_runs)} runs")
print(f"Campaign 2: {tot2} designs across {len(c2_runs)} runs")
print(f"Grand total: {tot1+tot2} designs; validated set: {len(c1_val)+len(c2_final)}")
print(f"Wrote {out_md}")
print(f"Wrote {out_fa}")
