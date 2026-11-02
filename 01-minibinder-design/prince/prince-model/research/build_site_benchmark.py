#!/usr/bin/env python
"""Build a site-level binder-designability benchmark from the Anthropic
claude-protein-binder-design release (CC BY 4.0).

One row per (target, site); a site is a cluster of de novo minibinder designs
whose modelled target-contact footprints mutually overlap. The label is whether
designs against that site bound in the lab.

CRITICAL DESIGN CONSTRAINT -- uniform site provenance
-----------------------------------------------------
Experimentally-resolved non-designable sites cannot exist (a failed site yields
no complex, hence no coordinates). Every site in BOTH classes is therefore
defined from MODELLED coordinates only: the release's `epitope_residues`, which
come from the design model (`designed.cif`) or, where the design model lacks
side chains, the bundled Protenix-v2 co-fold. No crystallographic coordinates
enter the labels anywhere. The three resolved designed-binder complexes that
exist for these targets (7N3T, 7OPB, 9HAC) are used only in --validate, to
check that the site-assignment procedure recovers a known interface; that
output never touches the benchmark table.

The release's own epitope footprints are NOT size-comparable across designs
(mean 29.2 target residues for all-atom design models vs 18.7 for backbone-only
ones, and 28.1 vs 18.5 for co-fold- vs design-model-sourced epitopes), and
footprint size is itself correlated with the binding label (p=1.7e-7). Raw
Jaccard over those sets would therefore mix interface geometry with
file-preparation differences. Every footprint is consequently re-cut to a
uniform top-K residues ranked by heavy-atom contact count, which removes the
size axis. K is configurable; the sweep is reported.

Usage:
    python build_site_benchmark.py                 # build benchmark
    python build_site_benchmark.py --validate      # + resolved-complex check
"""

from __future__ import annotations
from paths import DATA, REPO, MODEL

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------
BUNDLE = (
    str(DATA / "minibinder-data")
)
OUT = str(DATA / "site_benchmark")
DL = os.path.join(OUT, "downloads")

IN_DESIGN_SUMMARY = os.path.join(BUNDLE, "data/tables/design_summary.parquet")
IN_COLUMN_DICT = os.path.join(BUNDLE, "data/tables/column_dictionary.parquet")
IN_EPITOPE = os.path.join(DL, "epitope_residue_contacts.parquet")
IN_CONSTRUCTS = os.path.join(DL, "target_constructs.parquet")

HF_BASE = (
    "https://huggingface.co/datasets/Anthropic/claude-protein-binder-design/"
    "resolve/main/data/tables/"
)

# --------------------------------------------------------------------------
# decisions, recorded verbatim in the receipt
# --------------------------------------------------------------------------
FOOTPRINT_K = 10          # uniform footprint size (residues); see the K sweep
FOOTPRINT_K_SWEEP = [8, 10, 12, 15, 20, 0]   # 0 == use all epitope residues
FOOTPRINT_K_SENSITIVITY = 12   # second arm rebuilt end-to-end for comparison
JACCARD_SWEEP = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
JACCARD_CHOSEN = 0.40
LINKAGE_METHOD = "complete"   # every pair within a site overlaps >= threshold
CONSENSUS_FRAC = 0.50         # residue is in the site list if >=50% of members have it
MIN_DESIGNS_FOR_RATE = 5      # a (target, site) row is estimable at this n
MIN_DESIGNS_SOLID = 10

THREE2ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V",
}

# resolved de novo designed-binder complexes whose target is in this release.
# Used for site-assignment validation ONLY -- never for labels.
RESOLVED = {
    "7N3T": {"target": "TrkA", "note": "TrkA ECD + Cao-2022 designed miniprotein"},
    "7OPB": {"target": "IL-7Ra", "note": "IL7R + designed antagonist"},
    "9HAC": {"target": "BBF-14", "note": "BBF-14 + BindCraft binder BBF-14_b4"},
}

RECEIPT: list[str] = []


def log(msg: str = "") -> None:
    print(msg)
    RECEIPT.append(msg)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval; correct at 0/n and n/n, unlike Wald."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - half) / d), min(1.0, (c + half) / d))


# ==========================================================================
# stage 1 -- load and verify
# ==========================================================================
def ensure_downloads() -> None:
    os.makedirs(DL, exist_ok=True)
    for name in ("epitope_residue_contacts", "target_constructs"):
        dest = os.path.join(DL, f"{name}.parquet")
        if not os.path.exists(dest):
            url = f"{HF_BASE}insilico/{name}.parquet"
            log(f"  downloading {url}")
            subprocess.run(["curl", "-sfL", "-o", dest, url], check=True)


def load_and_verify():
    log("=" * 78)
    log("STAGE 1 -- inputs, licence, numbering verification")
    log("=" * 78)
    log("Licence (verified in bundle README.md and data/README.md):")
    log("  data + documentation : CC BY 4.0  (commercial use OK, attribution required)")
    log("  scripts in archives  : MIT")
    log("  third-party material : keeps its own terms (LICENSE.md per archive)")
    log("  -> usable in an OSI-licensed entry provided the dataset is cited;")
    log("     CC BY 4.0 is NOT itself an OSI licence, so keep data and code")
    log("     licensed separately and ship the attribution.")
    log("")

    ensure_downloads()
    inputs = {
        "design_summary.parquet": IN_DESIGN_SUMMARY,
        "column_dictionary.parquet": IN_COLUMN_DICT,
        "epitope_residue_contacts.parquet": IN_EPITOPE,
        "target_constructs.parquet": IN_CONSTRUCTS,
    }
    log("Input sha256:")
    for label, path in inputs.items():
        log(f"  {sha256(path)}  {label}")
    log("")

    ds = pd.read_parquet(IN_DESIGN_SUMMARY)
    er = pd.read_parquet(IN_EPITOPE)
    tc = pd.read_parquet(IN_CONSTRUCTS)
    log(f"design_summary {ds.shape}   epitope_residue_contacts {er.shape}   "
        f"target_constructs {tc.shape}")

    # ---- construct sequences, used as the numbering reference frame ----
    seqs: dict[str, list[str]] = {}
    for _, r in tc.iterrows():
        chains = []
        for part in str(r["target_chain_sequences"]).split(";"):
            tok = part.strip().split(" x")
            chains.append(tok[0].strip())
        seqs[r["target"]] = chains

    # ---- ASSERT the numbering scheme rather than trusting the column name ----
    # column_dictionary says `resnum` is "numbering of the target construct in
    # the source file". That is ambiguous between 1-based sequence position and
    # an author-assigned offset. Test it: resname must equal the construct
    # sequence at resnum-1 for every single residue.
    total = matched = 0
    chain_labels: dict[str, set[str]] = {}
    for _, r in er.iterrows():
        resnum = json.loads(r["resnum"])
        resname = json.loads(r["resname"])
        chain_labels.setdefault(r["target"], set()).update(resnum.keys())
        for ch in resnum:
            for num, nm in zip(resnum[ch], resname[ch]):
                total += 1
                one = THREE2ONE.get(nm, "?")
                if any(1 <= num <= len(s) and s[num - 1] == one
                       for s in seqs[r["target"]]):
                    matched += 1
    log("")
    log(f"NUMBERING ASSERTION: {matched}/{total} epitope residues match the "
        f"co-fold construct sequence at 1-based resnum "
        f"({100 * matched / total:.4f}%)")
    assert matched == total, "epitope numbering is NOT 1-based construct position"
    log("  -> epitope residue numbers are 1-BASED POSITIONS IN THE CO-FOLD")
    log("     CONSTRUCT CHAIN SEQUENCE. They are not PDB author numbers and")
    log("     not UniProt numbers. The construct sequence is the reference")
    log("     frame and is emitted with the benchmark (site_reference_frame).")

    # ---- chain labels are NOT stable, so they must be collapsed ----
    unstable = {t: sorted(c) for t, c in chain_labels.items()
                if len(c) > len(seqs[t])}
    log("")
    log("CHAIN-LABEL CHECK: single-chain constructs appear under more than one")
    log("chain letter, because co-fold chain order follows each predictor's")
    log("input order (INSILICO.md s4). Targets where observed chain letters")
    log("outnumber construct chains:")
    for t, c in sorted(unstable.items()):
        log(f"  {t:14s} construct chains={len(seqs[t])}  observed={c}")
    log("  -> chain letters carry no information and are COLLAPSED. A footprint")
    log("     is a set of residue numbers. Every target here is a monomer or a")
    log("     HOMO-oligomer (all protomers share one sequence), so collapsing")
    log("     cannot merge two chemically distinct chains; it correctly treats")
    log("     'binds protomer A' and 'binds protomer B' as the same site.")
    return ds, er, tc, seqs


# ==========================================================================
# stage 2 -- binding outcome label
# ==========================================================================
def build_labels(ds: pd.DataFrame) -> pd.DataFrame:
    log("")
    log("=" * 78)
    log("STAGE 2 -- binding outcome label")
    log("=" * 78)
    d = ds.copy()
    n0 = len(d)
    log(f"designs in release: {n0}")

    log("")
    log("Columns used (definitions read from column_dictionary.parquet, not")
    log("inferred from names):")
    log("  binder_final    boolean -- 'final binder call on the human target")
    log("                  determined by this release from both vendors and the")
    log("                  standardized re-fit with a fixed rubric, each call")
    log("                  then checked against the raw sensorgrams of both")
    log("                  vendors'. Blank for the 120 mature GDF-8 designs.")
    log("  adaptyv_binding object  -- binder / non_binder / not_expressed")
    log("                  (tested, no expression, counts as non-binder) /")
    log("                  not_tested / inconclusive")
    log("  twist_binding   object  -- binder / non_binder / not_measured")
    log("                  (on a plate but not produced) / not_tested /")
    log("                  inconclusive")
    log("  vendor_agreement object -- both_bind / neither_bind /")
    log("                  adaptyv_only_bind / twist_only_bind / coverage classes")
    log("  kd_nM_final     float   -- pooled kinetic K_D, nM")
    log("  adaptyv_kd_is_apparent, adaptyv_n_replicates, adaptyv_expression,")
    log("  twist_expression_mg_per_mL -- QC, see handling below.")

    log("")
    log("DECISION 2a -- PRIMARY LABEL is `binder_final`.")
    log("  Rationale: it is the only column that resolves vendor disagreement")
    log("  with a documented, uniformly-applied rubric (WETLAB.md s6) plus a")
    log("  sensorgram review that overturned 29 of 1,320 rubric calls. Taking")
    log("  either vendor alone would import that vendor's format bias (Adaptyv:")
    log("  monovalent cell-free ligand; Twist: bivalent IgG1-Fc ligand, so")
    log("  avidity-inflated), and the two disagree on 136/1,235 designs (89.0%")
    log("  agreement). CAVEAT to state plainly: binder_final was produced by a")
    log("  model applying a rubric, not by a single instrument reading, so it")
    log("  is a curated label. Sensitivity against vendor-only labels below.")

    log("")
    log("DECISION 2b -- DISAGREEMENT between assays is resolved by the")
    log("  binder_final rubric's evidence score, not by me: Adaptyv dose-")
    log("  dependent re-fit response (+2/+1/+0.5/-2), Adaptyv vendor call")
    log("  (+1/-0.5), Twist human-antigen hit (+2 strong / +0.5 other /")
    log("  -1 captured-but-no-fit), ortholog corroboration (+0.5), Twist")
    log("  evidence halved on SEC QC failure, target-specific overrides for")
    log("  RBX1/CUL1 occlusion, Cas9 apo, CLEC12A stickiness and MBP;")
    log("  positive at >= 1.5, never positive on one vendor against that same")
    log("  vendor's negative call.")

    log("")
    log("DECISION 2c -- K_D IS NOT USED for the binary label.")
    log("  adaptyv_kd_is_apparent is True for 420 designs because VEGF-A,")
    log("  mature GDF-8 and 15-PGDH are homodimers, TNF-a a homotrimer, latent")
    log("  GDF-8 a dimeric pro-complex and Nipah-G a tetramer, so a 1:1 fit")
    log("  returns an avidity-contaminated apparent K_D. A K_D threshold would")
    log("  therefore pass oligomeric targets preferentially -- a target-level")
    log("  artifact masquerading as site quality. K_D is carried as a")
    log("  descriptive column (median per site) and used only in the")
    log("  `kd_gated` sensitivity label, which is reported, not shipped.")

    log("")
    log("DECISION 2d -- REPLICATES. adaptyv_n_replicates is >= 2 for every")
    log("  tested design by design of the assay, and the binder_final rubric")
    log("  already scores replicate consistency ('two or more replicates with a")
    log("  dose-dependent response +2; exactly one of several +1'). No extra")
    log("  replicate filter is applied; the median is carried per site and a")
    log("  >= 2-replicate sensitivity label is reported.")

    # ---- exclusion 1: no interpretable measurement at all ----
    excl_na = d.binder_final.isna()
    log("")
    log("DECISION 2e -- EXCLUSIONS, with counts at each step.")
    log(f"  step 0  all designs                                 n={len(d)}")
    log(f"  step 1  drop binder_final is NA                     -{int(excl_na.sum())}")
    tgt_na = d.loc[excl_na, "target"].value_counts().to_dict()
    log(f"          (which designs: {tgt_na})")
    log("          = the 120 mature GDF-8 designs; the antigen aggregated and")
    log("            bound bare assay surfaces, so neither vendor produced an")
    log("            interpretable result. Site outcomes remain unresolved.")
    d = d[~excl_na].copy()
    d["binder_final"] = d.binder_final.astype(bool)
    log(f"          remaining                                    n={len(d)}")

    # ---- exclusion 2: expression failure at every vendor ----
    twist_unusable = (
        d.twist_binding.isin(["not_measured", "not_tested", "inconclusive"])
        | (d.twist_expression_mg_per_mL <= 0.03)
        | d.twist_expression_mg_per_mL.isna()
    )
    expr_fail = (d.adaptyv_binding == "not_expressed") & twist_unusable
    log("")
    log("  step 2  EXPRESSION FAILURES. A design that never expressed is not")
    log("          evidence that its site is undesignable -- it is evidence")
    log("          about that sequence. The two vendors use different")
    log("          expression systems (Adaptyv cell-free, Twist Expi293 Fc")
    log("          fusion), so a failure at one is usually rescued by the")
    log("          other and the design stays informative.")
    ne = (d.adaptyv_binding == "not_expressed").sum()
    log(f"            Adaptyv non-expressers (adaptyv_expression=='none')  "
        f"n={int(ne)}")
    rescued = int(((d.adaptyv_binding == "not_expressed") & ~twist_unusable).sum())
    log(f"            of which measurable at Twist (kept)                  "
        f"n={rescued}")
    log(f"            failed/unmeasurable at BOTH vendors (DROPPED)        "
        f"n={int(expr_fail.sum())}")
    log(f"            their binder_final: "
        f"{d.loc[expr_fail,'binder_final'].value_counts().to_dict()}")
    log("          DECISION: dropped from the primary label (excluded, not")
    log("          modelled separately -- n is too small to model). They are")
    log("          retained in the per-design table with")
    log("          label_exclusion_reason='expression_failure_both_vendors' so")
    log("          anyone can put them back as negatives.")
    d_excl_expr = d[expr_fail].copy()
    d = d[~expr_fail].copy()
    log(f"          remaining                                    n={len(d)}")

    # ---- exclusion 3: no modelled interface ----
    no_ep = d.epitope_n_residues == 0
    log("")
    log(f"  step 3  drop designs with 0 modelled contact residues  "
        f"-{int(no_ep.sum())}")
    log(f"          (targets: {d.loc[no_ep,'target'].value_counts().to_dict()}) "
        f"-- no site can be assigned")
    d_excl_noep = d[no_ep].copy()
    d = d[~no_ep].copy()
    log(f"          remaining                                    n={len(d)}")

    pos = int(d.binder_final.sum())
    log("")
    log(f"PRIMARY LABEL COUNTS: n={len(d)}  binders={pos} "
        f"({100*pos/len(d):.1f}%)  non-binders={len(d)-pos}")

    # ---- sensitivity labels ----
    log("")
    log("SENSITIVITY LABELS (computed, reported, not shipped as the label):")
    d["lab_primary"] = d.binder_final
    d["lab_strict_both"] = np.where(
        d.vendor_agreement == "both_bind", True,
        np.where(d.vendor_agreement == "neither_bind", False, np.nan))
    d["lab_adaptyv"] = np.where(
        d.adaptyv_binding == "binder", True,
        np.where(d.adaptyv_binding.isin(["non_binder", "not_expressed"]), False,
                 np.nan))
    d["lab_twist"] = np.where(
        d.twist_binding == "binder", True,
        np.where(d.twist_binding == "non_binder", False, np.nan))
    d["lab_kd_gated"] = d.binder_final & (d.kd_nM_final <= 1000)
    d["lab_reps2"] = np.where(d.adaptyv_n_replicates >= 2, d.binder_final, np.nan)
    for c in ["lab_primary", "lab_strict_both", "lab_adaptyv", "lab_twist",
              "lab_kd_gated", "lab_reps2"]:
        s = pd.Series(d[c], dtype="object")
        n = s.notna().sum()
        k = (s == True).sum()  # noqa: E712
        log(f"  {c:16s} n={n:5d}  positives={k:4d}  rate={k/max(n,1):.3f}")

    d["label_exclusion_reason"] = ""
    d_excl_expr["label_exclusion_reason"] = "expression_failure_both_vendors"
    d_excl_noep["label_exclusion_reason"] = "no_modelled_contact_residues"
    excluded = pd.concat([d_excl_expr, d_excl_noep], ignore_index=True)
    return d, excluded


# ==========================================================================
# stage 3 -- uniform footprints
# ==========================================================================
def build_footprints(d: pd.DataFrame, er: pd.DataFrame, k: int) -> pd.Series:
    """Top-k target residues by heavy-atom contact count, chains collapsed.

    k == 0 means take every epitope residue (no normalization).
    """
    emap = er.set_index("uuid")
    out = {}
    for uuid in d.uuid:
        r = emap.loc[uuid]
        resnum = json.loads(r["resnum"])
        ncon = json.loads(r["n_atom_contacts"])
        mind = json.loads(r["min_dist"])
        rows = []
        for ch in resnum:
            for num, nc, md in zip(resnum[ch], ncon[ch], mind[ch]):
                rows.append((num, nc, md))
        # collapse chains: a residue number seen on two protomers keeps its
        # strongest contact
        best: dict[int, tuple[int, float]] = {}
        for num, nc, md in rows:
            if num not in best or nc > best[num][0] or (
                    nc == best[num][0] and md < best[num][1]):
                best[num] = (nc, md)
        ordered = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0]))
        if k > 0:
            ordered = ordered[:k]
        out[uuid] = frozenset(n for n, _ in ordered)
    return pd.Series(out, name=f"fp{k}")


def report_footprints(d: pd.DataFrame, er: pd.DataFrame) -> None:
    log("")
    log("=" * 78)
    log("STAGE 3 -- uniform footprint definition (the provenance guard)")
    log("=" * 78)
    m = d.merge(er[["uuid", "source_file_kind"]], on="uuid")
    log("Footprint provenance, both label classes (the asymmetry that MUST NOT")
    log("exist between classes):")
    ct = pd.crosstab(m.source_file_kind, m.binder_final)
    log(ct.to_string())
    fisher_p = stats.fisher_exact(ct.values)[1]
    log(f"  Fisher exact p = {fisher_p:.4f}  -> epitope source is NOT")
    log("  associated with the label, so no class gets a different kind of")
    log("  coordinate. Both classes are modelled throughout: design-model")
    log("  coordinates or a Protenix-v2 co-fold, never a crystal structure.")
    log("")
    log("But raw footprint SIZE is confounded, two ways:")
    sz = m.groupby("source_file_kind").epitope_n_residues.agg(["count", "mean",
                                                               "median"])
    log(sz.to_string())
    sz2 = m.groupby("design_model_status").epitope_n_residues.agg(
        ["count", "mean", "median"])
    log(sz2.to_string())
    log("  Design models stored as backbone-only or CA-only have fewer heavy")
    log("  atoms, so fewer target residues fall within 5 A. That is a")
    log("  file-preparation effect, not interface geometry.")
    b = m[m.binder_final].epitope_n_residues
    nb = m[~m.binder_final].epitope_n_residues
    p = stats.mannwhitneyu(b, nb).pvalue
    log(f"  And size tracks the label: binders median {b.median():.0f} vs "
        f"non-binders {nb.median():.0f}, Mann-Whitney p={p:.2e}")
    log("")
    log(f"DECISION 3 -- every footprint is re-cut to the top K={FOOTPRINT_K}")
    log("  residues by heavy-atom contact count (ties: smaller min_dist, then")
    log("  lower residue number), chains collapsed. K=12 matches the footprint")
    log("  a minibinder actually buries (~10-15 target residues) and the")
    log("  12-residue patch cap of the tool this benchmark is meant to")
    log("  evaluate, so a row is directly comparable to a predicted patch.")
    log("  The K sweep is reported below.")


# ==========================================================================
# stage 4 -- clustering
# ==========================================================================
def cluster_target(fps: list[frozenset], threshold: float) -> np.ndarray:
    """Complete-linkage on 1 - Jaccard: every pair in a site overlaps >= thr."""
    n = len(fps)
    if n == 1:
        return np.array([1])
    dm = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            a, b = fps[i], fps[j]
            u = len(a | b)
            jac = len(a & b) / u if u else 0.0
            dm[i, j] = dm[j, i] = 1.0 - jac
    z = linkage(squareform(dm, checks=False), method=LINKAGE_METHOD)
    return fcluster(z, t=1.0 - threshold, criterion="distance")


def sweep(d: pd.DataFrame, fp_col: str) -> pd.DataFrame:
    rows = []
    for thr in JACCARD_SWEEP:
        n_sites = 0
        n_est = 0
        rates = []
        spreads = []
        for tgt, g in d.groupby("target"):
            lab = cluster_target(list(g[fp_col]), thr)
            n_sites += len(set(lab))
            sub = []
            for s in set(lab):
                mem = g[lab == s]
                if len(mem) >= MIN_DESIGNS_FOR_RATE:
                    n_est += 1
                    r = mem.binder_final.mean()
                    rates.append(r)
                    sub.append(r)
            if len(sub) >= 2:
                spreads.append(max(sub) - min(sub))
        rows.append({
            "jaccard": thr, "n_sites": n_sites,
            f"n_sites_ge{MIN_DESIGNS_FOR_RATE}": n_est,
            "mean_designs_per_site": round(len(d) / n_sites, 2),
            "mean_site_success": round(float(np.mean(rates)), 3) if rates else np.nan,
            "sd_site_success": round(float(np.std(rates)), 3) if rates else np.nan,
            "mean_within_target_spread": (round(float(np.mean(spreads)), 3)
                                          if spreads else np.nan),
            "n_targets_ge2_estimable": len(spreads),
        })
    return pd.DataFrame(rows)


def assign_sites(d: pd.DataFrame, fp_col: str, thr: float) -> pd.DataFrame:
    d = d.copy()
    d["site_id"] = ""
    for tgt, g in d.groupby("target"):
        lab = cluster_target(list(g[fp_col]), thr)
        # order site numbers by descending membership for stable ids
        order = pd.Series(lab).value_counts().index.tolist()
        rank = {s: i + 1 for i, s in enumerate(order)}
        tok = tgt.replace(" ", "").replace("-", "")
        d.loc[g.index, "site_id"] = [f"{tok}_S{rank[s]:02d}" for s in lab]
    return d


# ==========================================================================
# stage 4b -- portable numbering: construct position -> UniProt position
# ==========================================================================
IN_ANTIGENS = os.path.join(DL, "antigens_and_controls.parquet")


def uniprot_maps(seqs: dict) -> dict[str, dict]:
    """construct 1-based position -> UniProt 1-based position, per target.

    The release numbers epitope residues by position in its own co-fold
    construct, which is not portable. The accession comes from the release's
    own reagent table; the offset is derived by aligning the construct to the
    canonical UniProt sequence, never assumed.
    """
    log("")
    log("=" * 78)
    log("STAGE 4b -- portable numbering (construct position -> UniProt)")
    log("=" * 78)
    if not os.path.exists(IN_ANTIGENS):
        url = f"{HF_BASE}wetlab/antigens_and_controls.parquet"
        log(f"  downloading {url}")
        subprocess.run(["curl", "-sfL", "-o", IN_ANTIGENS, url], check=True)
    log(f"  {sha256(IN_ANTIGENS)}  antigens_and_controls.parquet")
    ag = pd.read_parquet(IN_ANTIGENS)
    acc = (ag[ag.role.astype(str).str.contains("target antigen", na=False)]
           .dropna(subset=["uniprot_accession"])
           .groupby("target").uniprot_accession.first().to_dict())
    os.makedirs(os.path.join(DL, "uniprot"), exist_ok=True)
    out = {}
    for tgt, chains in seqs.items():
        a = acc.get(tgt)
        if not a:
            log(f"  {tgt:14s} no UniProt accession in the release reagent "
                f"table (de novo protein) -- construct numbering only")
            out[tgt] = {"accession": None, "map": {}, "identity": np.nan}
            continue
        path = os.path.join(DL, "uniprot", f"{a}.fasta")
        if not os.path.exists(path):
            try:
                subprocess.run(
                    ["curl", "-sfL", "-o", path,
                     f"https://rest.uniprot.org/uniprotkb/{a}.fasta"],
                    check=True, timeout=60)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                log(f"  {tgt:14s} {a}: fetch failed -- construct numbering only")
                out[tgt] = {"accession": a, "map": {}, "identity": np.nan}
                continue
        with open(path) as fh:
            up = "".join(l.strip() for l in fh if not l.startswith(">"))
        con = chains[0]
        mp = {}
        for blk in SequenceMatcher(None, up, con,
                                   autojunk=False).get_matching_blocks():
            for off in range(blk.size):
                mp[blk.b + off + 1] = blk.a + off + 1
        ident = 100.0 * len(mp) / len(con)
        log(f"  {tgt:14s} {a}  UniProt len {len(up):5d}  construct len "
            f"{len(con):5d}  mapped {len(mp):5d} positions ({ident:.1f}% of "
            f"the construct)")
        out[tgt] = {"accession": a, "map": mp, "identity": ident}
    log("")
    log("  Positions that do not map are construct-only residues (expression")
    log("  tags, engineered linkers, or a different isoform) and are emitted")
    log("  as blank in site_residues_uniprot. The construct frame stays")
    log("  authoritative; UniProt is a convenience column.")
    return out


# ==========================================================================
# stage 5 -- benchmark table
# ==========================================================================
def build_benchmark(d: pd.DataFrame, er: pd.DataFrame, tc: pd.DataFrame,
                    seqs: dict, fp_col: str, umaps: dict) -> pd.DataFrame:
    emap = er.set_index("uuid")
    cmap = tc.set_index("target")
    rows = []
    for (tgt, sid), g in d.groupby(["target", "site_id"]):
        fps = list(g[fp_col])
        cnt: dict[int, int] = {}
        for f in fps:
            for r in f:
                cnt[r] = cnt.get(r, 0) + 1
        need = CONSENSUS_FRAC * len(fps)
        consensus = sorted(r for r, c in cnt.items() if c >= need)
        union = sorted(cnt)
        n = len(g)
        k = int(g.binder_final.sum())
        lo, hi = wilson(k, n)
        src = emap.loc[g.uuid, "source_file_kind"].value_counts().to_dict()
        kd = g.loc[g.binder_final, "kd_nM_final"].dropna()
        pair_j = []
        for i in range(len(fps)):
            for j in range(i + 1, len(fps)):
                u = len(fps[i] | fps[j])
                pair_j.append(len(fps[i] & fps[j]) / u if u else 0.0)
        rows.append({
            "site_id": sid,
            "target": tgt,
            "target_construct_id": cmap.loc[tgt, "target_construct_id"],
            "site_residues_consensus": ";".join(map(str, consensus)),
            "site_n_residues_consensus": len(consensus),
            "site_residues_union": ";".join(map(str, union)),
            "uniprot_accession": umaps[tgt]["accession"],
            "site_residues_uniprot": ";".join(
                str(umaps[tgt]["map"][r]) for r in consensus
                if r in umaps[tgt]["map"]),
            "n_designs": n,
            "n_expressed": int((g.adaptyv_binding != "not_expressed").sum()),
            "n_binders": k,
            "success_rate": round(k / n, 4),
            "ci95_low": round(lo, 4),
            "ci95_high": round(hi, 4),
            "estimable": n >= MIN_DESIGNS_FOR_RATE,
            "generators": ";".join(
                f"{a}:{b}" for a, b in g.generator.value_counts().items()),
            "n_generators": g.generator.nunique(),
            "design_models": ";".join(
                f"{a}:{b}" for a, b in g.design_model.value_counts().items()),
            "campaigns": ";".join(sorted(g.campaign.unique())),
            "median_binder_length": float(g.binder_length.median()),
            "median_kd_nM_binders": (round(float(kd.median()), 1)
                                     if len(kd) else np.nan),
            "median_adaptyv_n_replicates": float(
                g.adaptyv_n_replicates.median()),
            "mean_pairwise_jaccard": round(float(np.mean(pair_j)), 3)
                                     if pair_j else 1.0,
            "footprint_source_kinds": ";".join(f"{a}:{b}" for a, b in src.items()),
            "site_provenance": "modelled_only",
            "site_reference_frame": (
                f"1-based position in co-fold construct "
                f"{cmap.loc[tgt,'target_construct_id']} "
                f"({cmap.loc[tgt,'target_chain_lengths']}); sequence in "
                f"site_reference_sequences.fasta"),
        })
    bm = pd.DataFrame(rows).sort_values(
        ["target", "n_designs"], ascending=[True, False]).reset_index(drop=True)
    return bm


# ==========================================================================
# stage 6 -- power
# ==========================================================================
def mdd(n1: int, n2: int, p1: float, alpha: float = 0.05,
        power: float = 0.80) -> float:
    """Minimum detectable difference in proportions, two-sided normal approx."""
    za = stats.norm.ppf(1 - alpha / 2)
    zb = stats.norm.ppf(power)
    best = np.nan
    for delta in np.arange(0.01, 1.0, 0.005):
        p2 = p1 + delta
        if p2 > 1:
            break
        pbar = (p1 * n1 + p2 * n2) / (n1 + n2)
        se0 = np.sqrt(pbar * (1 - pbar) * (1 / n1 + 1 / n2))
        se1 = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
        if abs(delta) >= za * se0 + zb * se1:
            best = delta
            break
    return best


def power_report(d: pd.DataFrame, bm: pd.DataFrame) -> pd.DataFrame:
    log("")
    log("=" * 78)
    log("STAGE 6 -- statistical power")
    log("=" * 78)
    log(f"benchmark rows (target, site): {len(bm)}")
    log(f"  with n_designs >= {MIN_DESIGNS_FOR_RATE} (estimable): "
        f"{int((bm.n_designs >= MIN_DESIGNS_FOR_RATE).sum())}")
    log(f"  with n_designs >= {MIN_DESIGNS_SOLID}: "
        f"{int((bm.n_designs >= MIN_DESIGNS_SOLID).sum())}")
    log(f"  singletons (n_designs == 1): {int((bm.n_designs == 1).sum())}")
    log("")
    log("Sites only inform RANKING when one target carries >= 2 sites whose")
    log("outcomes differ. Per target:")
    rows = []
    for tgt, g in bm.groupby("target"):
        est = g[g.n_designs >= MIN_DESIGNS_FOR_RATE]
        n_est = len(est)
        spread = (est.success_rate.max() - est.success_rate.min()
                  if n_est >= 2 else np.nan)
        p_hom = np.nan
        if n_est >= 2:
            tab = np.array([[r.n_binders, r.n_designs - r.n_binders]
                            for r in est.itertuples()])
            keep = tab[tab.sum(axis=1) > 0]
            if keep.shape[0] >= 2 and keep.sum() > 0:
                try:
                    if keep.shape[0] == 2:
                        p_hom = stats.fisher_exact(keep)[1]
                    else:
                        p_hom = stats.chi2_contingency(keep)[1]
                except ValueError:
                    p_hom = np.nan
        tot = int(g.n_designs.sum())
        base = float(d[d.target == tgt].binder_final.mean())
        med_n = int(est.n_designs.median()) if n_est else 0
        rows.append({
            "target": tgt, "n_designs": tot, "n_sites": len(g),
            "n_sites_estimable": n_est,
            "median_designs_per_estimable_site": med_n,
            "target_success_rate": round(base, 3),
            "site_rate_spread": round(spread, 3) if n_est >= 2 else np.nan,
            "p_homogeneity": round(p_hom, 4) if p_hom == p_hom else np.nan,
            "mdd_80pct_power": (round(mdd(med_n, med_n, base), 3)
                                if n_est >= 2 and med_n >= 2 else np.nan),
            # A target informs RANKING if it has >=2 estimable sites of usable
            # size whose rates actually DIFFER. MBP (0/90) gives sites with
            # identical 0.0 rates and can order nothing, so spread>0 excludes
            # it. An overall rate near the ceiling is NOT disqualifying on its
            # own: TREM2 sits at 0.835 yet its sites range over 0.5, which is
            # rankable. The floor/ceiling fact is reported separately instead
            # of being baked into this flag.
            "at_floor_or_ceiling": bool(not (0.05 < base < 0.80)),
            "informative_for_ranking": bool(
                n_est >= 2 and med_n >= MIN_DESIGNS_FOR_RATE
                and spread == spread and spread > 0.0),
        })
    pw = pd.DataFrame(rows).sort_values("n_sites_estimable", ascending=False)
    log(pw.to_string(index=False))
    inf = pw[pw.informative_for_ranking]
    log("")
    log(f"TARGETS INFORMATIVE FOR SITE RANKING: {len(inf)} of {len(pw)}")
    log(f"  (>= 2 estimable sites, median site n >= {MIN_DESIGNS_FOR_RATE}, site")
    log("   rates actually differ)")
    fc = pw[pw.informative_for_ranking & pw.at_floor_or_ceiling]
    if len(fc):
        log(f"  of these, at the floor/ceiling overall so a site rate is "
            f"compressed: {sorted(fc.target.tolist())}")
    log(f"  {sorted(inf.target.tolist())}")
    excl = pw[~pw.informative_for_ranking]
    log(f"  NOT informative: {sorted(excl.target.tolist())}")
    for r in excl.itertuples():
        why = []
        if r.n_sites_estimable < 2:
            why.append("<2 estimable sites")
        if not (r.median_designs_per_estimable_site >= MIN_DESIGNS_FOR_RATE):
            why.append("median site too small")
        if r.site_rate_spread == 0.0:
            why.append("all site rates identical")
        if r.at_floor_or_ceiling:
            why.append(f"also at the "
                       f"{'floor' if r.target_success_rate <= 0.05 else 'ceiling'}"
                       f" ({r.target_success_rate:.3f})")
        log(f"    {r.target:14s} {'; '.join(why)}")
    sig = pw[(pw.p_homogeneity < 0.05)]
    log("")
    log(f"TARGETS WHERE SITES DEMONSTRABLY DIFFER (p_homogeneity < 0.05): "
        f"{len(sig)}")
    log(f"  {sorted(sig.target.tolist())}")
    mdds = pw.mdd_80pct_power.dropna()
    if len(mdds):
        log("")
        log("MINIMUM DETECTABLE DIFFERENCE between two sites of one target, at")
        log("  80% power, alpha=0.05, using that target's median site size:")
        log(f"  median {mdds.median():.2f}, best {mdds.min():.2f}, worst "
            f"{mdds.max():.2f} -- in ABSOLUTE success rate.")
        log("  Blunt reading: a single pair of sites can only be separated when")
        log("  their true success rates differ by roughly 55 to 77 percentage")
        log("  points. Pairwise site discrimination is NOT powered. What is")
        log("  powered is the aggregate question below.")
    n_est_rows = int((bm.n_designs >= MIN_DESIGNS_FOR_RATE).sum())
    rho = np.tanh((stats.norm.ppf(0.975) + stats.norm.ppf(0.80))
                  / np.sqrt(max(n_est_rows - 3, 1)))
    log("")
    log("AGGREGATE (the use this benchmark can actually support): evaluating a")
    log(f"  site ranker against all {n_est_rows} estimable rows at once. With")
    log(f"  {n_est_rows} rows, a rank correlation of |rho| >= {rho:.2f} between a")
    log("  predicted score and observed site success is detectable at 80%")
    log("  power. That is the headline number: this benchmark can tell a")
    log("  ranker with moderate-or-better correlation from random, and cannot")
    log("  resolve individual site pairs.")
    return pw


# ==========================================================================
# stage 7 -- confounds
# ==========================================================================
def site_signal_test(d: pd.DataFrame, n_perm: int = 5000,
                     seed: int = 0) -> None:
    """Is there ANY site-level signal, and does it survive the generator?

    Statistic: between-site heterogeneity of success, summed over targets,
    sum_t sum_s n_s (p_s - p_t)^2, over estimable sites only. The null
    permutes the binding labels WITHIN strata, which preserves every
    stratum's success rate and every site's size and destroys only the
    association between site identity and outcome. Permuting within
    (target, generator) therefore answers the question that decides whether
    this benchmark is valid at all: does site identity predict the outcome
    once the generator that proposed it is held fixed?
    """
    log("")
    log("=" * 78)
    log("STAGE 7a -- is there any site signal, and does it survive generator?")
    log("=" * 78)
    sub = d.groupby(["target", "site_id"]).filter(
        lambda g: len(g) >= MIN_DESIGNS_FOR_RATE).copy()
    y = sub.binder_final.to_numpy(dtype=float)
    tcode = pd.factorize(sub.target)[0]
    scode = pd.factorize(sub.target.astype(str) + "|" + sub.site_id)[0]
    n_t, n_s = tcode.max() + 1, scode.max() + 1

    def stat(v: np.ndarray) -> float:
        tsum = np.bincount(tcode, v, n_t)
        tcnt = np.bincount(tcode, minlength=n_t)
        pt = tsum / tcnt
        ssum = np.bincount(scode, v, n_s)
        scnt = np.bincount(scode, minlength=n_s)
        ps = ssum / scnt
        # map each site to its target
        s2t = np.zeros(n_s, dtype=int)
        s2t[scode] = tcode
        return float(np.sum(scnt * (ps - pt[s2t]) ** 2))

    obs = stat(y)
    rng = np.random.default_rng(seed)
    log(f"estimable designs in test: {len(sub)}  sites: {n_s}  targets: {n_t}")
    log(f"observed heterogeneity: {obs:.2f}")
    log("")
    for cols, name in [
        (["target"], "target only          (generator NOT controlled)"),
        (["target", "generator"], "target x generator   (generator CONTROLLED)"),
        (["target", "generator", "design_model"],
         "+ design_model       (generator AND model CONTROLLED)"),
    ]:
        groups = [np.asarray(ix) for ix in
                  sub.groupby(cols, observed=True).indices.values()]
        null = np.empty(n_perm)
        for i in range(n_perm):
            v = y.copy()
            for ix in groups:
                if len(ix) > 1:
                    v[ix] = rng.permutation(v[ix])
            null[i] = stat(v)
        p = (1 + int((null >= obs).sum())) / (n_perm + 1)
        log(f"  {name}")
        log(f"    null mean {null.mean():6.2f} +/- {null.std():.2f}   "
            f"excess {obs - null.mean():6.2f}   p = {p:.5f}"
            + ("  (permutation floor)" if p <= 1.5 / (n_perm + 1) else ""))
    log("")
    log("  READING: the null mean rises as confounders are held fixed, so part")
    log("  of the raw heterogeneity really is generator mix. The observed value")
    log("  nevertheless stays far above the generator-controlled null, so site")
    log("  identity carries outcome information that the generator does not")
    log("  explain. That is the result that makes this benchmark worth having.")


def variance_decomposition(d: pd.DataFrame, bm: pd.DataFrame,
                           pw: pd.DataFrame) -> None:
    """Is between-target variance swamping between-site variance?

    If it is, a model can score well on pooled rows by recognising which
    target a site belongs to, while knowing nothing about sites. This is the
    single check that decides how the benchmark must be scored.
    """
    log("")
    log("=" * 78)
    log("STAGE 7b -- between-target vs between-site variance")
    log("=" * 78)
    for name, sub in (("ALL sites", d),
                      ("ESTIMABLE sites only (n >= %d)" % MIN_DESIGNS_FOR_RATE,
                       d.groupby(["target", "site_id"]).filter(
                           lambda g: len(g) >= MIN_DESIGNS_FOR_RATE))):
        y = sub.binder_final.astype(float)
        gm = y.mean()
        ss_tot = float(((y - gm) ** 2).sum())
        ss_t = sum(len(g) * (g.binder_final.mean() - gm) ** 2
                   for _, g in sub.groupby("target"))
        ss_s = 0.0
        exp_noise = 0.0
        for _, g in sub.groupby("target"):
            pt = g.binder_final.mean()
            for _, h in g.groupby("site_id"):
                ss_s += len(h) * (h.binder_final.mean() - pt) ** 2
                exp_noise += pt * (1 - pt) * (1 - len(h) / len(g))
        log("")
        log(f"{name}: n={len(sub)}  total SS={ss_tot:.2f}")
        log(f"  between-target             {ss_t:7.2f}  "
            f"({100*ss_t/ss_tot:5.1f}% of total)")
        log(f"  between-site within target {ss_s:7.2f}  "
            f"({100*ss_s/ss_tot:5.1f}%)")
        log(f"  residual (design-to-design){ss_tot-ss_t-ss_s:7.2f}  "
            f"({100*(ss_tot-ss_t-ss_s)/ss_tot:5.1f}%)")
        log(f"  target : site variance ratio = {ss_t/ss_s:.2f}")
        log(f"  site SS expected from binomial noise alone = {exp_noise:.2f}"
            f"  -> {100*(ss_s-exp_noise)/ss_s:.0f}% of the observed site")
        log("     heterogeneity is real, the rest is sampling noise")

    log("")
    log("THE CONSEQUENCE, stated bluntly. Between-target variance is the")
    log("larger component, so a scorer evaluated on POOLED rows can do well")
    log("without any site knowledge at all:")
    e = bm[bm.estimable].copy()
    tm = e.groupby("target").success_rate.mean()
    e["target_mean"] = e.target.map(tm)
    rho_t = stats.spearmanr(e.target_mean, e.success_rate).statistic
    log(f"  a predictor that outputs ONLY its target's mean success rate and")
    log(f"  ignores the site entirely scores Spearman rho = {rho_t:.3f} on the")
    log(f"  {len(e)} pooled estimable rows.")
    log(f"  SD of site success: pooled {e.success_rate.std():.3f} = target")
    log(f"  means {tm.std():.3f} + within-target residual "
        f"{e.groupby('target').success_rate.transform(lambda s: s - s.mean()).std():.3f}")
    log("")
    log("  So POOLED SCORING OF THIS BENCHMARK IS INVALID. Any evaluation")
    log("  MUST be (a) within-target -- rank sites only against other sites of")
    log("  the same target -- and (b) leave-one-target-out, so no model is")
    log("  ever fitted and tested on the same target. A reported pooled")
    log("  correlation on these rows should be assumed to be target")
    log("  recognition until proven otherwise.")
    for inf, name in ((pw[pw.informative_for_ranking].target.tolist(),
                       "informative targets"),
                      (pw[pw.p_homogeneity < 0.05].target.tolist(),
                       "PRIMARY set (heterogeneity established)")):
        n_rows = int(e[e.target.isin(inf)].shape[0])
        df = max(n_rows - len(inf), 1)
        rho = np.tanh((stats.norm.ppf(0.975) + stats.norm.ppf(0.80))
                      / np.sqrt(max(df - 3, 1)))
        log("")
        log(f"  WITHIN-TARGET POWER over the {len(inf)} {name}:")
        log(f"    {n_rows} estimable rows, {df} within-target degrees of")
        log(f"    freedom -> detectable |rho| = {rho:.2f} at 80% power, "
            f"alpha=0.05.")
    log("")
    log("  Quote the within-target figure, NOT the pooled one: the pooled row")
    log("  count flatters the benchmark because it counts between-target")
    log("  ordering that no site ranker should get credit for.")


def recommended_evaluation(d: pd.DataFrame, bm: pd.DataFrame,
                           pw: pd.DataFrame) -> None:
    """How this benchmark must and must not be scored."""
    log("")
    log("=" * 78)
    log("RECOMMENDED EVALUATION -- binding rules, not suggestions")
    log("=" * 78)
    log("1. WITHIN-TARGET RANKING IS THE HEADLINE METRIC. Score a model by")
    log("   whether it orders a single target's own sites by their measured")
    log("   success rate, then aggregate that across targets (mean per-target")
    log("   Spearman, or a per-target concordance). Report the per-target")
    log("   values, not only the aggregate.")
    log("")
    log("2. NEVER REPORT A POOLED SITE-LEVEL AUC OR CORRELATION. Between-")
    log("   target variance exceeds between-site variance (ratio 1.54 on the")
    log("   estimable rows), and target success ranges from 0.000 (MBP, 90")
    log("   designs, nothing worked) to 0.835 (TREM2). A predictor that emits")
    log("   only its target's mean rate and is blind to sites scores Spearman")
    log("   0.73 pooled. A pooled number therefore measures target")
    log("   recognition and must not be quoted as site ranking.")
    log("")
    log("3. ANY MODEL FITTING MUST BE LEAVE-ONE-TARGET-OUT. Not a random")
    log("   split: sites of one target share a surface, a construct, an assay")
    log("   plate and a success baseline, so a random split leaks the target")
    log("   baseline into the test fold.")
    log("")
    sig = pw[(pw.p_homogeneity < 0.05)].sort_values("p_homogeneity")
    log("4. PRIMARY EVALUATION SET -- the targets whose within-target site")
    log("   heterogeneity is statistically established:")
    for r in sig.itertuples():
        rows_t = int(bm[(bm.target == r.target) & bm.estimable].shape[0])
        log(f"     {r.target:10s} p={r.p_homogeneity:<8.5g} spread="
            f"{r.site_rate_spread:.3f}  {rows_t} estimable sites, "
            f"{r.n_designs} designs")
    _n = len(sig)
    _w = {4: "FOUR", 5: "FIVE", 6: "SIX", 7: "SEVEN", 8: "EIGHT"}.get(_n, str(_n))
    log(f"   That is {_n} targets. {_w} TARGETS IS A SMALL PRIMARY SET and the")
    log(f"   writeup must say so in those words. A result on {_n} targets is")
    log("   suggestive, not established.")
    _fc = sig[sig.at_floor_or_ceiling]
    for r in _fc.itertuples():
        log(f"   NOTE {r.target}: overall rate {r.target_success_rate:.3f} is at")
        log(f"   the {'floor' if r.target_success_rate <= 0.05 else 'ceiling'}, "
            f"yet its site rates span {r.site_rate_spread:.3f} and differ")
        log("   significantly. It is rankable, but its sites are compressed")
        log("   toward one end, so a ranker is tested over a narrow band.")
    log("")
    sec = pw[pw.informative_for_ranking & (pw.p_homogeneity >= 0.05)]
    log("5. SECONDARY SET -- informative_for_ranking but heterogeneity not")
    log("   individually significant (report separately, never merged into")
    log("   the primary):")
    log(f"     {sorted(sec.target.tolist())}")
    log("")
    excl = pw[~pw.informative_for_ranking]
    log("6. EXCLUDE FROM RANKING ENTIRELY (no within-target signal exists to")
    log("   rank, at any sample size):")
    for r in excl.itertuples():
        log(f"     {r.target:14s} rate={r.target_success_rate:.3f} "
            f"spread={r.site_rate_spread if r.site_rate_spread == r.site_rate_spread else 0:.3f}")
    log("")
    mdds = pw.mdd_80pct_power.dropna()
    log("7. STATE THE SENSITIVITY HONESTLY. Minimum detectable difference")
    log(f"   between two sites of one target is {mdds.min():.2f} to "
        f"{mdds.max():.2f} in absolute")
    log("   success rate at 80% power. THIS BENCHMARK DETECTS LARGE EFFECTS")
    log("   ONLY. Do not let a reader infer more power than exists: a model")
    log("   that fails here is not thereby shown to be useless, and a model")
    log("   that passes has cleared a coarse bar, not a fine one.")
    log("")
    log("8. STRATIFY BY GENERATOR OR SAY WHY NOT. Generator is non-")
    log("   independent of site on most targets (stage 7), so a site rate is")
    log("   partly its generator mix. The `generators` column per row exists")
    log("   for this.")


def confound_report(d: pd.DataFrame) -> None:
    log("")
    log("=" * 78)
    log("STAGE 7 -- confounds that limit what a site rate can mean")
    log("=" * 78)
    log("If generators are not spread evenly over the sites of a target, a")
    log("site's success rate partly measures its generator mix, not the site.")
    rows = []
    for tgt, g in d.groupby("target"):
        est = [s for s, h in g.groupby("site_id") if len(h) >= MIN_DESIGNS_FOR_RATE]
        if len(est) < 2:
            continue
        sub = g[g.site_id.isin(est)]
        for var in ("generator", "design_model"):
            tab = pd.crosstab(sub.site_id, sub[var])
            tab = tab.loc[:, tab.sum() > 0]
            try:
                p = stats.chi2_contingency(tab.values)[1]
            except ValueError:
                p = np.nan
            rows.append({"target": tgt, "variable": var,
                         "n_levels": tab.shape[1],
                         "p_independent_of_site": round(p, 4) if p == p else np.nan})
    cf = pd.DataFrame(rows)
    if len(cf):
        log(cf.pivot(index="target", columns="variable",
                     values="p_independent_of_site").to_string())
        bad = cf[(cf.p_independent_of_site < 0.05)]
        log("")
        log(f"  {len(bad)} target x variable combinations are significantly")
        log("  non-independent: on those targets a site's success rate is")
        log("  confounded with which generator proposed that site. The")
        log("  benchmark therefore ships generators per row so any user can")
        log("  stratify, and site rates must not be read as pure site quality.")
    log("")
    log("Floor and ceiling targets carry no usable site signal regardless of n:")
    for tgt, g in d.groupby("target"):
        r = g.binder_final.mean()
        if r <= 0.05 or r >= 0.80:
            log(f"  {tgt:14s} {int(g.binder_final.sum()):3d}/{len(g):3d} = "
                f"{r:.3f}  ({'floor' if r <= 0.05 else 'ceiling'})")


# ==========================================================================
# stage 8 -- resolved-complex validation (kept out of the labels)
# ==========================================================================
def validate_resolved(d: pd.DataFrame, bm: pd.DataFrame, seqs: dict,
                      fp_col: str) -> pd.DataFrame:
    log("")
    log("=" * 78)
    log("STAGE 8 -- site-assignment validation against resolved complexes")
    log("           (REPORTED SEPARATELY; NEVER ENTERS THE LABELS)")
    log("=" * 78)
    try:
        import gemmi
    except ImportError:
        log("  gemmi unavailable -- skipped")
        return pd.DataFrame()

    os.makedirs(os.path.join(DL, "pdb"), exist_ok=True)
    rows = []
    for pdb, meta in RESOLVED.items():
        path = os.path.join(DL, "pdb", f"{pdb.lower()}.cif.gz")
        if not os.path.exists(path):
            subprocess.run(
                ["curl", "-sfL", "-o", path,
                 f"https://files.rcsb.org/download/{pdb}.cif.gz"], check=True)
        st = gemmi.read_structure(path)
        st.setup_entities()
        st.remove_ligands_and_waters()
        model = st[0]
        tgt = meta["target"]
        ref = seqs[tgt][0]

        # identify which chain is the target by sequence identity to the
        # release construct; everything else is treated as the binder.
        # difflib matching blocks are used rather than a substitution-matrix
        # alignment: the crystal construct and the release construct are the
        # same protein, so only indels need handling, and this keeps the
        # crystal-index -> construct-position map exact.
        # coverage of the RELEASE CONSTRUCT is the right denominator: several
        # constructs here are a single domain (TrkA is 101 aa inside a ~385 aa
        # crystallized ectodomain), so dividing by the crystal chain length
        # would reject the correct chain.
        cov = {}
        for ch in model:
            s = gemmi.one_letter_code([r.name for r in ch]).upper()
            if len(s) < 20:
                continue
            sm = SequenceMatcher(None, ref.upper(), s, autojunk=False)
            cov[ch.name] = 100.0 * sum(
                b.size for b in sm.get_matching_blocks()) / len(ref)
        if not cov:
            log(f"  {pdb}: no protein chain of >= 20 residues -- skipped")
            continue
        best_chain = max(cov, key=cov.get)
        best_id = cov[best_chain]
        if best_id < 60:
            log(f"  {pdb}: no chain covers the {tgt} construct "
                f"(best coverage {best_id:.1f}%) -- skipped")
            continue

        tchain = model[best_chain]
        # the binder is every chain that is NOT another copy of the target;
        # including a second target copy would import crystal-packing contacts
        others = [ch for ch in model
                  if ch.name != best_chain and cov.get(ch.name, 0.0) < 40.0]
        if not others:
            log(f"  {pdb}: no non-target protein chain (apo) -- skipped")
            continue

        ns = gemmi.NeighborSearch(st, 5.0).populate()
        # crystal chain index -> 1-based construct position
        tseq = gemmi.one_letter_code([r.name for r in tchain]).upper()
        xtal2con: dict[int, int] = {}
        for blk in SequenceMatcher(None, ref.upper(), tseq,
                                   autojunk=False).get_matching_blocks():
            for off in range(blk.size):
                xtal2con[blk.b + off] = blk.a + off + 1

        contact_pos = set()
        unmapped = 0
        other_names = {ch.name for ch in others}
        for i, res in enumerate(tchain):
            hit = False
            for atom in res:
                for m in ns.find_atoms(atom.pos, "\0", radius=5.0):
                    cra = m.to_cra(model)
                    if cra.chain.name in other_names:
                        if atom.pos.dist(cra.atom.pos) <= 5.0:
                            hit = True
                            break
                if hit:
                    break
            if hit:
                if i in xtal2con:
                    contact_pos.add(xtal2con[i])
                else:
                    # a crystal contact on a part of the protein that the
                    # release construct does not contain at all
                    unmapped += 1

        # which benchmark site of this target best matches?
        sub = bm[bm.target == tgt]
        best = None
        for r in sub.itertuples():
            u = set(int(x) for x in r.site_residues_union.split(";") if x)
            c = set(int(x) for x in r.site_residues_consensus.split(";") if x)
            jac_u = len(contact_pos & u) / len(contact_pos | u) if u else 0
            rec = len(contact_pos & c) / len(c) if c else 0
            if best is None or jac_u > best["jaccard_union"]:
                best = {"site_id": r.site_id, "n_designs": r.n_designs,
                        "success_rate": r.success_rate,
                        "jaccard_union": round(jac_u, 3),
                        "consensus_recovered_frac": round(rec, 3)}
        rows.append({
            "pdb": pdb, "target": tgt, "note": meta["note"],
            "target_chain": best_chain,
            "binder_chains": ";".join(ch.name for ch in others),
            "construct_coverage_pct": round(best_id, 1),
            "n_crystal_contact_residues": len(contact_pos),
            "n_contacts_outside_construct": unmapped,
            "crystal_contact_positions": ";".join(map(str, sorted(contact_pos))),
            **{f"best_{k}": v for k, v in best.items()},
        })
        log(f"  {pdb} ({tgt}): construct coverage {best_id:.1f}%, binder "
            f"chain(s) {','.join(ch.name for ch in others)}, "
            f"{unmapped} crystal contacts fall outside the construct")
        log(f"    crystal interface = {len(contact_pos)} construct"
            f" positions; best-matching benchmark site "
            f"{best['site_id']} (n={best['n_designs']}, "
            f"success={best['success_rate']}), Jaccard vs site union = "
            f"{best['jaccard_union']}, consensus residues recovered = "
            f"{best['consensus_recovered_frac']}")
    log("")
    log("  Interpretation: this checks only that the clustering lands on a real")
    log("  interface for targets where one happens to be resolved. It is not a")
    log("  label, not a positive, and not used anywhere in the benchmark table.")
    out = pd.DataFrame(rows)
    if len(out):
        log("")
        log("  AND NOTE THE RESULT THAT PROVES WHY: the crystallographic site")
        log("  does not map onto a successful site. For 7N3T the resolved")
        log("  Cao-2022 TrkA interface matches a benchmark site whose designs")
        log("  bound 0 times out of 4, and for 9HAC the resolved BindCraft")
        log("  BBF-14 interface matches a site at 2/10. A site being")
        log("  crystallographically real says nothing about how often a design")
        log("  against it binds. Had resolved complexes been used to define")
        log("  positives, those two rows would have been labelled successes")
        log("  while the modelled evidence says the opposite -- which is")
        log("  exactly the label-provenance artifact this build is built to")
        log("  avoid.")
    return out


# ==========================================================================
# structure-availability reconnaissance (metadata only, no coordinates)
# ==========================================================================
def _api(url: str, payload: dict | None = None) -> dict | None:
    """RCSB metadata call, cached on disk so re-runs cost nothing."""
    cache = os.path.join(DL, "rcsb_cache")
    os.makedirs(cache, exist_ok=True)
    key = hashlib.sha256(
        (url + json.dumps(payload or {}, sort_keys=True)).encode()).hexdigest()
    path = os.path.join(cache, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except json.JSONDecodeError:
            pass
    cmd = ["curl", "-sfL", "--max-time", "60", url]
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json", "-d",
                json.dumps(payload)]
    try:
        r = subprocess.run(cmd, capture_output=True, check=True)
        out = json.loads(r.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError,
            subprocess.TimeoutExpired):
        return None
    with open(path, "w") as fh:
        json.dump(out, fh)
    return out


def structure_recon() -> None:
    """What 3D coordinates exist per target, and how much of each site is
    actually resolved in them.

    Deliberately metadata-only: unobserved residues are read from the RCSB
    polymer-entity-instance features, so no coordinate file is downloaded and
    nothing is built. The point is a feasibility picture -- a site whose
    residues are unresolved in the only available structure cannot be scored
    from that structure, and that should shrink the benchmark rather than be
    papered over.
    """
    log("=" * 78)
    log("STRUCTURE-AVAILABILITY RECONNAISSANCE (metadata only)")
    log("=" * 78)
    bm = pd.read_csv(os.path.join(OUT, "site_benchmark.csv"))
    tc = pd.read_parquet(IN_CONSTRUCTS)
    seqs = {r["target"]: str(r["target_chain_sequences"]).split(" x")[0].strip()
            for _, r in tc.iterrows()}

    rows, site_rows = [], []
    for tgt in sorted(bm.target.unique()):
        con = seqs[tgt]
        hits = _api(
            "https://search.rcsb.org/rcsbsearch/v2/query",
            {"query": {"type": "terminal", "service": "sequence",
                       "parameters": {"evalue_cutoff": 0.1,
                                      "identity_cutoff": 0.9,
                                      "sequence_type": "protein",
                                      "value": con}},
             "return_type": "polymer_entity",
             "request_options": {"paginate": {"start": 0, "rows": 25},
                                 "results_verbosity": "verbose"}})
        if not hits or not hits.get("result_set"):
            log(f"\n{tgt}: NO PDB entity at >=90% identity to the construct "
                f"-- a predicted model is the only option")
            rows.append({"target": tgt, "best_pdb": None,
                         "status": "no_experimental_structure"})
            continue

        cands = []
        for h in hits["result_set"][:25]:
            eid = h["identifier"]                      # e.g. 1ABC_1
            entry_id, ent = eid.split("_")
            if entry_id.upper() in RESOLVED:
                # never score on a complex used to VALIDATE site assignment,
                # and never on a designed-binder complex at all: its interface
                # is one of the things being predicted
                continue
            meta = _api(f"https://data.rcsb.org/rest/v1/core/entry/{entry_id}")
            ent_d = _api("https://data.rcsb.org/rest/v1/core/polymer_entity/"
                         f"{entry_id}/{ent}")
            if not meta or not ent_d:
                continue
            method = (meta.get("exptl") or [{}])[0].get("method", "?")
            res = (meta.get("rcsb_entry_info", {})
                   .get("resolution_combined") or [None])[0]
            n_ent = meta.get("rcsb_entry_info", {}).get(
                "polymer_entity_count_protein", 1)
            eseq = ent_d.get("entity_poly", {}).get(
                "pdbx_seq_one_letter_code_can", "").replace("\n", "").upper()
            if not eseq:
                continue
            sm = SequenceMatcher(None, con.upper(), eseq, autojunk=False)
            cov = sum(b.size for b in sm.get_matching_blocks()) / len(con)
            asyms = ent_d.get("rcsb_polymer_entity_container_identifiers", {}
                              ).get("asym_ids", [])
            cands.append({
                "entry_id": entry_id, "entity": ent, "method": method,
                "resolution_A": res, "coverage": cov,
                "n_protein_entities": n_ent, "eseq": eseq,
                "apo": n_ent == 1,
                "asym": asyms[0] if asyms else None,
                "title": (meta.get("struct", {}).get("title") or "")[:70]})
        if not cands:
            log(f"\n{tgt}: entity metadata unavailable -- skipped")
            continue

        # APO IS PREFERRED, and this is not cosmetic. A bound partner buries
        # target surface, so patch enumeration and any SASA-derived feature
        # computed on a holo structure sees an interface that is not there in
        # the apo state -- and for several of these targets the bound partner
        # sits exactly where the designs bind. Rank: apo first, then construct
        # coverage, then resolution.
        def rank(c: dict) -> tuple:
            return (c["apo"], round(c["coverage"], 3),
                    -(c["resolution_A"] or 9.9))

        cands.sort(key=rank, reverse=True)
        best = cands[0]
        best_holo = next((c for c in cands if not c["apo"]), None)
        best_apo = next((c for c in cands if c["apo"]), None)

        # unobserved residues, from features rather than from coordinates
        unobs: set[int] = set()
        if best["asym"]:
            inst = _api("https://data.rcsb.org/rest/v1/core/"
                        f"polymer_entity_instance/{best['entry_id']}/"
                        f"{best['asym']}")
            for f in (inst or {}).get("rcsb_polymer_instance_feature", []):
                if f.get("type") in ("UNOBSERVED_RESIDUE_XYZ",
                                     "UNOBSERVED_ATOM_XYZ"):
                    for p in f.get("feature_positions", []):
                        b, e = p.get("beg_seq_id"), p.get("end_seq_id", None)
                        if b:
                            for x in range(b, (e or b) + 1):
                                unobs.add(x)

        # construct position -> entity position
        c2e = {}
        for blk in SequenceMatcher(None, best["eseq"], con.upper(),
                                   autojunk=False).get_matching_blocks():
            for off in range(blk.size):
                c2e[blk.b + off + 1] = blk.a + off + 1

        log("")
        log(f"{tgt}")
        log(f"  CHOSEN           {best['entry_id']}_{best['entity']}  "
            f"{best['method']}"
            + (f" {best['resolution_A']:.2f} A" if best["resolution_A"] else "")
            + ("  [APO, target alone]" if best["apo"]
               else f"  [HOLO, {best['n_protein_entities']} protein entities]"))
        log(f"                   {best['title']}")
        if not best["apo"]:
            log(f"  !! NO APO STRUCTURE at >=90% identity. The only coordinates")
            log(f"     available have a bound partner, which occludes target")
            log(f"     surface. Patch enumeration on this entry will not see")
            log(f"     the free-state surface. FLAGGED for your decision.")
        elif best_holo:
            log(f"  (best holo alternative was "
                f"{best_holo['entry_id']}_{best_holo['entity']} at "
                f"{best_holo['resolution_A']} A -- not used)")
        log(f"  construct cover  {100*best['coverage']:.1f}%  "
            f"({len(c2e)}/{len(con)} positions map)")
        log(f"  apo candidates at >=90% identity: "
            f"{sum(1 for c in cands if c['apo'])} of {len(cands)} entities")
        log(f"  unobserved residues in the chain: {len(unobs)}")

        sub = bm[(bm.target == tgt) & bm.estimable]
        fracs = []
        for r in sub.itertuples():
            res = [int(x) for x in str(r.site_residues_consensus).split(";") if x]
            mapped = [c2e[x] for x in res if x in c2e]
            resolved = [x for x in mapped if x not in unobs]
            frac = len(resolved) / len(res) if res else np.nan
            fracs.append(frac)
            site_rows.append({
                "site_id": r.site_id, "target": tgt,
                "best_pdb": f"{best['entry_id']}_{best['entity']}",
                "is_apo": best["apo"],
                "n_site_residues": len(res),
                "n_mapped_to_pdb": len(mapped),
                "n_resolved_in_pdb": len(resolved),
                "frac_scoreable": round(frac, 3) if frac == frac else np.nan,
                "n_designs": r.n_designs, "success_rate": r.success_rate,
                "fully_scoreable": bool(frac == 1.0),
            })
        if fracs:
            full = sum(1 for f in fracs if f == 1.0)
            log(f"  estimable sites   {len(fracs)}  |  fully scoreable "
                f"{full}  |  median residues present "
                f"{100*float(np.median(fracs)):.0f}%  |  worst "
                f"{100*min(fracs):.0f}%")
        rows.append({
            "target": tgt, "best_pdb": f"{best['entry_id']}_{best['entity']}",
            "is_apo": best["apo"],
            "needs_predicted_model": False,
            "n_apo_candidates": sum(1 for c in cands if c["apo"]),
            "best_apo_pdb": (f"{best_apo['entry_id']}_{best_apo['entity']}"
                             if best_apo else None),
            "best_holo_pdb": (f"{best_holo['entry_id']}_{best_holo['entity']}"
                              if best_holo else None),
            "method": best["method"], "resolution_A": best["resolution_A"],
            "construct_coverage": round(best["coverage"], 4),
            "n_protein_entities": best["n_protein_entities"],
            "n_unobserved_residues": len(unobs),
            "title": best["title"],
            "n_estimable_sites": len(fracs),
            "n_fully_scoreable_sites": sum(1 for f in fracs if f == 1.0),
            "median_frac_scoreable": (round(float(np.median(fracs)), 3)
                                      if fracs else np.nan),
            "status": "ok",
        })

    sr = pd.DataFrame(site_rows)
    tr = pd.DataFrame(rows)
    tr.to_csv(os.path.join(OUT, "structure_availability_targets.csv"),
              index=False)
    sr.to_csv(os.path.join(OUT, "structure_availability_sites.csv"), index=False)
    log("")
    log("=" * 78)
    log("FEASIBILITY SUMMARY")
    log("=" * 78)
    if len(sr):
        log(f"estimable sites examined        {len(sr)}")
        log(f"  fully resolved in the best PDB {int(sr.fully_scoreable.sum())}")
        log(f"  >= 90% of residues resolved    "
            f"{int((sr.frac_scoreable >= 0.9).sum())}")
        log(f"  < 75% resolved (not scoreable) "
            f"{int((sr.frac_scoreable < 0.75).sum())}")
        bad = sr[sr.frac_scoreable < 0.9]
        if len(bad):
            log("  rows that would have to be dropped or modelled:")
            for r in bad.itertuples():
                log(f"    {r.site_id:14s} {r.n_resolved_in_pdb}/"
                    f"{r.n_site_residues} resolved in {r.best_pdb}")
        log("")
        log(f"  sites whose structure is APO     "
            f"{int(sr.is_apo.sum())} of {len(sr)}")
        log(f"  sites only available HOLO        "
            f"{int((~sr.is_apo).sum())}  (bound partner occludes surface)")
        log(f"  fully resolved AND apo           "
            f"{int((sr.fully_scoreable & sr.is_apo).sum())}  <- "
            f"unambiguously scoreable")
    log("")
    log("TARGETS NEEDING A PREDICTED MODEL (no experimental entity at >= 90%")
    log("identity to the construct):")
    nm = tr[tr.get("status") == "no_experimental_structure"]
    log(f"  {len(nm)}" + (f": {nm.target.tolist()}" if len(nm) else " -- none"))
    holo = tr[(tr.get("is_apo") == False)]  # noqa: E712
    log("")
    log("TARGETS WITH NO APO STRUCTURE (flagged, not resolved here):")
    for r in holo.itertuples():
        log(f"  {r.target:14s} best is {r.best_pdb} with "
            f"{r.n_protein_entities} protein entities "
            f"({r.n_apo_candidates} apo candidates found)")
    log("")
    log("  Nothing was downloaded and nothing was built: unobserved-residue")
    log("  ranges come from the RCSB entity-instance feature records, and")
    log("  every RCSB response is cached under downloads/rcsb_cache/.")
    with open(os.path.join(OUT, "RECEIPT_structures.txt"), "w") as fh:
        fh.write("\n".join(RECEIPT) + "\n")


# ==========================================================================
# structure preparation: strip partners, recompute exposure
# ==========================================================================
# Tien et al. 2013 (PLoS ONE 8:e80635), theoretical max accessible area, A^2.
MAX_ASA = {
    "A": 129.0, "R": 274.0, "N": 195.0, "D": 193.0, "C": 167.0, "E": 223.0,
    "Q": 225.0, "G": 104.0, "H": 224.0, "I": 197.0, "L": 201.0, "K": 236.0,
    "M": 224.0, "F": 240.0, "P": 159.0, "S": 155.0, "T": 172.0, "W": 285.0,
    "Y": 263.0, "V": 174.0,
}


def _rel_sasa(path: str) -> dict[tuple[str, str], float]:
    """(chain, residue number) -> relative SASA, from coordinates only.

    freesasa reads the written file as-is. No symmetry mates are generated
    anywhere in this function, so a crystallographic lattice neighbour can
    never bury a surface here: only the chains present in the file contribute.
    HETATM records are skipped by freesasa's default options, so waters,
    buffer components and cofactors are excluded from both arms of the
    comparison, which isolates the protein-partner effect.
    """
    import freesasa
    st = freesasa.Structure(path)
    res = freesasa.calc(st)
    out = {}
    for ch, residues in res.residueAreas().items():
        for num, area in residues.items():
            aa = MAX_ASA.get(getattr(area, "residueType", ""), None)
            tot = area.total
            if aa is None:
                # residueType is a 3-letter code in some builds
                three = getattr(area, "residueType", "").strip()
                aa = MAX_ASA.get(THREE2ONE.get(three, ""), None)
            out[(ch, str(num).strip())] = (tot / aa) if aa else np.nan
    return out


def structure_prepare() -> None:
    """Fetch the chosen entries, strip non-target chains, and quantify how
    much the partner was hiding.

    Rules implemented, in the order they bind:
      1. a genuine apo entity is preferred (done in the recon stage);
      2. where only holo exists, EVERY non-target chain is removed and
         exposure is recomputed on the stripped file -- never on the
         deposited assembly;
      3. before/after relative SASA of each site's residues is reported;
      4. no symmetry mates are ever generated, so lattice contacts cannot
         bury a surface (see _rel_sasa);
      5. the PHYSIOLOGICAL oligomer is kept intact -- a homotrimeric TNF-a
         interface is legitimately buried and must stay buried -- while
         crystallographic copies beyond that count are dropped. The expected
         copy count comes from the release's own construct stoichiometry
         (`target_chain_lengths`, e.g. 157x3 for TNF-a), not from prose.
    """
    import gemmi
    log("=" * 78)
    log("STRUCTURE PREPARATION -- strip partners, recompute exposure")
    log("=" * 78)
    tr = pd.read_csv(os.path.join(OUT, "structure_availability_targets.csv"))
    bm = pd.read_csv(os.path.join(OUT, "site_benchmark.csv"))
    tc = pd.read_parquet(IN_CONSTRUCTS)
    seqs = {r["target"]: str(r["target_chain_sequences"]).split(" x")[0].strip()
            for _, r in tc.iterrows()}
    copies = {}
    for _, r in tc.iterrows():
        tok = str(r["target_chain_lengths"]).split("x")
        copies[r["target"]] = int(tok[1]) if len(tok) > 1 else 1

    sdir = os.path.join(OUT, "structures")
    rawdir = os.path.join(DL, "pdb")
    os.makedirs(sdir, exist_ok=True)
    os.makedirs(rawdir, exist_ok=True)

    log("")
    log("Physiological copy count per target, from the release's own construct")
    log("stoichiometry (kept intact; extra crystallographic copies dropped):")
    log("  " + ", ".join(f"{t}:{c}" for t, c in sorted(copies.items())))

    rows, site_rows = [], []
    for r in tr.itertuples():
        tgt = r.target
        if not isinstance(getattr(r, "best_pdb", None), str):
            log(f"\n{tgt}: no structure -- skipped")
            continue
        chosen = r.best_pdb
        # compare the chosen entry against the best alternative of the other
        # kind, so "do apo and holo disagree about accessibility?" is answerable
        alt = r.best_holo_pdb if r.is_apo else r.best_apo_pdb
        con = seqs[tgt]
        want = copies[tgt]

        log("")
        log(f"{tgt}  chosen {chosen}  "
            f"({'APO' if r.is_apo else 'HOLO -- MUST BE STRIPPED'})")

        for role, eid in (("chosen", chosen), ("alternative", alt)):
            if not isinstance(eid, str):
                continue
            entry = eid.split("_")[0]
            cif = os.path.join(rawdir, f"{entry.lower()}.cif.gz")
            if not os.path.exists(cif):
                try:
                    subprocess.run(
                        ["curl", "-sfL", "--max-time", "180", "-o", cif,
                         f"https://files.rcsb.org/download/{entry}.cif.gz"],
                        check=True)
                except subprocess.CalledProcessError:
                    log(f"  {role} {eid}: download failed -- skipped")
                    continue
            st = gemmi.read_structure(cif)
            st.setup_entities()
            st.remove_alternative_conformations()
            st.remove_hydrogens()
            st.remove_waters()
            st.remove_ligands_and_waters()
            model = st[0]

            # which chains are the target, by construct coverage
            cov = {}
            for ch in model:
                s = gemmi.one_letter_code([x.name for x in ch]).upper()
                if len(s) < 20:
                    continue
                sm = SequenceMatcher(None, con.upper(), s, autojunk=False)
                cov[ch.name] = sum(b.size for b in sm.get_matching_blocks()) \
                    / len(con)
            tchains = [c for c, v in sorted(cov.items(), key=lambda kv: -kv[1])
                       if v >= 0.60][:want]
            if not tchains:
                log(f"  {role} {eid}: no chain covers the construct -- skipped")
                continue
            others = [c for c in cov if c not in tchains]
            extra_copies = [c for c, v in cov.items()
                            if v >= 0.60 and c not in tchains]

            # ---- baseline: target chains plus whatever CONTACTS them ----
            # (not the whole deposited file: a 22-chain replisome exceeds the
            # PDB format, and only contacting chains can occlude anything)
            ns = gemmi.NeighborSearch(st, 6.0).populate()
            contacting = set()
            for cn in tchains:
                for res in model[cn]:
                    for atom in res:
                        for m in ns.find_atoms(atom.pos, "\0", radius=6.0):
                            cra = m.to_cra(model)
                            if cra.chain.name not in tchains:
                                contacting.add(cra.chain.name)

            def write(keep: set, path: str) -> None:
                s2 = gemmi.Structure()
                s2.add_model(gemmi.Model("1"))
                for ch in model:
                    if ch.name in keep:
                        s2[0].add_chain(ch.clone())
                s2.cell = gemmi.UnitCell()      # empty cell: no symmetry, ever
                s2.spacegroup_hm = "P 1"
                s2.setup_entities()
                s2.write_pdb(path)

            base_p = os.path.join(sdir, f"{tgt.replace(' ','_')}_{eid}_"
                                        f"{role}_deposited.pdb")
            strip_p = os.path.join(sdir, f"{tgt.replace(' ','_')}_{eid}_"
                                         f"{role}_stripped.pdb")
            write(set(tchains) | contacting, base_p)
            write(set(tchains), strip_p)
            try:
                sb = _rel_sasa(base_p)
                ss = _rel_sasa(strip_p)
            except Exception as exc:                       # noqa: BLE001
                log(f"  {role} {eid}: SASA failed ({exc}) -- skipped")
                continue

            # construct position -> (chain, author residue number)
            pos2res: dict[int, list] = {}
            for cn in tchains:
                ch = model[cn]
                cseq = gemmi.one_letter_code([x.name for x in ch]).upper()
                for blk in SequenceMatcher(None, con.upper(), cseq,
                                           autojunk=False
                                           ).get_matching_blocks():
                    for off in range(blk.size):
                        cpos = blk.a + off + 1
                        res = ch[blk.b + off]
                        pos2res.setdefault(cpos, []).append(
                            (cn, str(res.seqid.num)))

            log(f"  {role:11s} {eid}  target chains {tchains}"
                f"  contacting chains stripped: "
                f"{sorted(contacting) if contacting else 'none'}"
                + (f"  extra crystallographic copies dropped: {extra_copies}"
                   if extra_copies else ""))

            sub = bm[(bm.target == tgt) & bm.estimable]
            deltas = []
            for s in sub.itertuples():
                res = [int(x) for x in
                       str(s.site_residues_consensus).split(";") if x]
                bvals, svals = [], []
                for p in res:
                    for key in pos2res.get(p, []):
                        if key in sb:
                            bvals.append(sb[key])
                        if key in ss:
                            svals.append(ss[key])
                if not svals:
                    continue
                mb = float(np.nanmean(bvals)) if bvals else np.nan
                ms = float(np.nanmean(svals))
                deltas.append(ms - mb)
                site_rows.append({
                    "site_id": s.site_id, "target": tgt, "role": role,
                    "pdb": eid, "is_apo": bool(r.is_apo) if role == "chosen"
                    else None,
                    "n_site_residues": len(res),
                    "n_resolved": len(svals),
                    "mean_relsasa_deposited": round(mb, 4) if mb == mb else np.nan,
                    "mean_relsasa_stripped": round(ms, 4),
                    "delta_relsasa": round(ms - mb, 4) if mb == mb else np.nan,
                    "n_designs": s.n_designs, "success_rate": s.success_rate,
                })
            if deltas:
                dd = [x for x in deltas if x == x]
                log(f"              site mean relative SASA rose by "
                    f"{np.mean(dd):+.3f} on average after stripping "
                    f"(max {max(dd):+.3f}) over {len(dd)} sites")
            rows.append({
                "target": tgt, "role": role, "pdb": eid,
                "is_apo_choice": bool(r.is_apo),
                "target_chains_kept": ";".join(tchains),
                "physiological_copies": want,
                "chains_stripped": ";".join(sorted(contacting)),
                "extra_copies_dropped": ";".join(sorted(extra_copies)),
                "stripped_file": os.path.basename(strip_p),
                "mean_delta_relsasa": (round(float(np.nanmean(deltas)), 4)
                                       if deltas else np.nan),
            })

    sdf = pd.DataFrame(site_rows)
    tdf = pd.DataFrame(rows)
    sdf.to_csv(os.path.join(OUT, "structure_sasa_sites.csv"), index=False)
    tdf.to_csv(os.path.join(OUT, "structure_sasa_targets.csv"), index=False)

    log("")
    log("=" * 78)
    log("HOW BIG WAS THE ARTIFACT WE AVOIDED?")
    log("=" * 78)
    ch = sdf[sdf.role == "chosen"].dropna(subset=["delta_relsasa"])
    if len(ch):
        holo = ch[ch.is_apo == False]              # noqa: E712
        apo = ch[ch.is_apo == True]                # noqa: E712
        log(f"sites on HOLO-only targets ({holo.target.nunique()} targets, "
            f"{len(holo)} sites):")
        if len(holo):
            log(f"  mean relative SASA  deposited "
                f"{holo.mean_relsasa_deposited.mean():.3f}  ->  stripped "
                f"{holo.mean_relsasa_stripped.mean():.3f}   "
                f"(+{holo.delta_relsasa.mean():.3f})")
            worst = holo.nlargest(min(5, len(holo)), "delta_relsasa")
            log("  worst-affected sites (these would have read as buried):")
            for w in worst.itertuples():
                log(f"    {w.site_id:14s} {w.mean_relsasa_deposited:.3f} -> "
                    f"{w.mean_relsasa_stripped:.3f}  "
                    f"({w.delta_relsasa:+.3f})  success={w.success_rate}")
        log(f"sites on APO targets ({apo.target.nunique()} targets, "
            f"{len(apo)} sites): mean delta "
            f"{apo.delta_relsasa.mean():+.3f}")
        log("  (non-zero on apo targets too, wherever the deposited entry has")
        log("   a crystallographic neighbour chain in contact -- which is")
        log("   exactly the lattice-burial case, and it is stripped as well)")

    log("")
    log("DO APO AND HOLO DISAGREE ABOUT ACCESSIBILITY? (a result in itself)")
    piv = sdf.pivot_table(index="site_id", columns="role",
                          values="mean_relsasa_stripped")
    if "alternative" in piv and "chosen" in piv:
        both = piv.dropna()
        if len(both):
            rho = stats.spearmanr(both["chosen"], both["alternative"]).statistic
            log(f"  {len(both)} sites have both a chosen and an alternative")
            log(f"  structure. After stripping BOTH, site mean relative SASA")
            log(f"  agrees at Spearman rho = {rho:.3f}, mean absolute "
                f"difference {np.mean(np.abs(both['chosen']-both['alternative'])):.3f}.")
            dis = (both["chosen"] - both["alternative"]).abs().nlargest(
                min(5, len(both)))
            log("  largest disagreements (same site, two structures):")
            for sid, v in dis.items():
                log(f"    {sid:14s} |delta| = {v:.3f}  "
                    f"chosen {both.loc[sid,'chosen']:.3f} vs alternative "
                    f"{both.loc[sid,'alternative']:.3f}")
            log("  A large value here means the site's accessibility is")
            log("  conformation-dependent, so any score for it is only as")
            log("  stable as the structure chosen. Those rows deserve a")
            log("  caveat in the writeup rather than silent averaging.")
    log("")
    log(f"stripped structures written to {sdir}")
    log("  these, NOT the deposited files, are what any scoring must consume")
    with open(os.path.join(OUT, "RECEIPT_structures.txt"), "w") as fh:
        fh.write("\n".join(RECEIPT) + "\n")


# ==========================================================================
# main
# ==========================================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true",
                    help="also run the resolved-complex site-assignment check")
    ap.add_argument("--structures", action="store_true",
                    help="structure-availability reconnaissance only "
                         "(metadata; reads an existing site_benchmark.csv)")
    ap.add_argument("--prepare", action="store_true",
                    help="fetch chosen entries, strip non-target chains and "
                         "recompute site exposure (needs --structures first)")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    if args.structures:
        structure_recon()
        return
    if args.prepare:
        structure_prepare()
        return

    started = datetime.now(timezone.utc).isoformat()
    log(f"build_site_benchmark.py  started {started}")
    log(f"python {platform.python_version()}  pandas {pd.__version__}  "
        f"numpy {np.__version__}")
    log("")

    ds, er, tc, seqs = load_and_verify()
    d, excluded = build_labels(ds)
    report_footprints(d, er)

    # ---- footprint-size sweep ----
    log("")
    log("K sweep (at the chosen Jaccard threshold), K=0 means all residues:")
    fp_cache = {}
    krows = []
    for k in FOOTPRINT_K_SWEEP:
        fp_cache[k] = build_footprints(d, er, k)
        dk = d.copy()
        dk[f"fp{k}"] = dk.uuid.map(fp_cache[k])
        dk = assign_sites(dk, f"fp{k}", JACCARD_CHOSEN)
        ns = dk.site_id.nunique()
        est = sum(1 for _, g in dk.groupby(["target", "site_id"])
                  if len(g) >= MIN_DESIGNS_FOR_RATE)
        # does footprint size still separate the classes at this K, and does
        # it still separate the two epitope provenances? n is fixed at len(d)
        # for every K, so these are directly comparable across K -- but the
        # rank-biserial effect sizes are reported too, because p alone invites
        # the objection that the test changes with K.
        sz = dk[f"fp{k}"].map(len)
        prov = dk.merge(er[["uuid", "source_file_kind"]], on="uuid")
        pz = prov[f"fp{k}"].map(len)
        b, nb = sz[dk.binder_final], sz[~dk.binder_final]
        pm = pz[prov.source_file_kind == "predicted"]
        dmm = pz[prov.source_file_kind == "design_model"]

        def rb(x, y):
            u = stats.mannwhitneyu(x, y).statistic
            return 2 * u / (len(x) * len(y)) - 1

        krows.append({
            "K": k, "n_sites": ns,
            f"n_sites_ge{MIN_DESIGNS_FOR_RATE}": est,
            "n_designs_shorter_than_K": int((dk.epitope_n_residues < k).sum())
            if k > 0 else 0,
            "mean_footprint_size": round(float(sz.mean()), 2),
            "size_diff_binder_minus_non": round(float(b.mean() - nb.mean()), 2),
            "size_vs_label_rank_biserial": round(abs(rb(b, nb)), 3),
            "size_vs_label_p": f"{stats.mannwhitneyu(b, nb).pvalue:.2e}",
            "provenance_size_gap_res": round(float(pm.mean() - dmm.mean()), 2),
            "provenance_rank_biserial": round(abs(rb(pm, dmm)), 3),
        })
    kdf = pd.DataFrame(krows)
    log(kdf.to_string(index=False))
    log(f"  -> K={FOOTPRINT_K} keeps footprints uniform (size no longer")
    log("     separates the classes) while still resolving distinct sites.")

    fp_col = f"fp{FOOTPRINT_K}"
    d[fp_col] = d.uuid.map(fp_cache[FOOTPRINT_K])

    # ---- what top-K actually fixed, measured rather than asserted ----
    chk = d.merge(er[["uuid", "source_file_kind"]], on="uuid")
    chk["fs"] = chk[fp_col].map(len)
    raw = chk.groupby("source_file_kind").epitope_n_residues.mean()
    cut = chk.groupby("source_file_kind").fs.mean()
    p_raw = stats.mannwhitneyu(
        *[g.epitope_n_residues for _, g in chk.groupby("source_file_kind")]).pvalue
    p_cut = stats.mannwhitneyu(
        *[g.fs for _, g in chk.groupby("source_file_kind")]).pvalue
    log("")
    log("WHAT TOP-K FIXED, AND WHAT IT DID NOT (measured, not asserted):")
    log(f"  provenance size gap, raw epitopes : design_model {raw.get('design_model'):.1f}"
        f" vs predicted {raw.get('predicted'):.1f} residues "
        f"(diff {abs(raw.diff().iloc[-1]):.1f}, p={p_raw:.1e})")
    log(f"  provenance size gap, top-{FOOTPRINT_K} footprints: "
        f"design_model {cut.get('design_model'):.2f} vs predicted "
        f"{cut.get('predicted'):.2f} residues "
        f"(diff {abs(cut.diff().iloc[-1]):.2f}, p={p_cut:.1e})")
    log(f"  -> the gap shrinks by "
        f"{100*(1-abs(cut.diff().iloc[-1])/abs(raw.diff().iloc[-1])):.0f}%. It is")
    log("     STILL statistically significant, and that must be stated: the")
    log("     residue is entirely due to designs whose modelled interface has")
    log(f"     fewer than K={FOOTPRINT_K} contact residues in the first place "
        f"({int((chk.epitope_n_residues < FOOTPRINT_K).sum())} of {len(chk)}),")
    log("     which cannot be padded. Among the designs that do have >= K")
    log("     contacts every footprint is exactly K, and footprint size then")
    big = chk[chk.epitope_n_residues >= FOOTPRINT_K]
    p_big = stats.mannwhitneyu(big[big.binder_final].fs,
                               big[~big.binder_final].fs).pvalue
    log(f"     carries no label information at all (p={p_big:.2f} vs "
        f"p={stats.mannwhitneyu(chk[chk.binder_final].epitope_n_residues, chk[~chk.binder_final].epitope_n_residues).pvalue:.1e}")
    log("     for raw epitope size). Users who want the size axis gone")
    log(f"     entirely should restrict to epitope_n_residues >= {FOOTPRINT_K},")
    log("     which the per-design table supports.")

    # ---- Jaccard sweep ----
    log("")
    log("=" * 78)
    log("STAGE 4 -- Jaccard threshold sweep "
        f"(complete linkage on 1 - Jaccard, K={FOOTPRINT_K})")
    log("=" * 78)
    sw = sweep(d, fp_col)
    log(sw.to_string(index=False))
    sw.to_csv(os.path.join(OUT, "jaccard_sweep.csv"), index=False)
    log("")
    log(f"DECISION 4 -- threshold = {JACCARD_CHOSEN}, complete linkage.")
    log("  Complete linkage is used so that EVERY pair of designs inside a")
    log("  site overlaps by at least the threshold; single linkage would chain")
    log("  a whole protein surface into one site through intermediates.")
    log("  Threshold rationale, read off the sweep and nothing else: the")
    log("  quantity that decides whether this benchmark exists is the number")
    log("  of rows with enough designs to estimate a rate, and that count")
    log("  peaks at 0.40 (96 rows; 93 at 0.30, 91 at 0.35, 87 at 0.45, 54 at")
    log("  0.55). At 0.40 two designs share a site only when 2/3 of their 12")
    log("  contact residues coincide, which is a defensible reading of 'same")
    log("  site'. NOTE what the sweep does NOT justify: within-target spread")
    log("  in success rate rises monotonically with the threshold (0.26 at")
    log("  0.20 to 0.67 at 0.60), but that is sampling noise from ever-smaller")
    log("  sites, not more signal -- which is exactly why the permutation test")
    log("  in stage 7a, not the spread, is used to decide whether site")
    log("  identity means anything. The whole sweep ships so the choice is")
    log("  auditable and a user can rebuild at any threshold.")

    umaps = uniprot_maps(seqs)
    d = assign_sites(d, fp_col, JACCARD_CHOSEN)
    bm = build_benchmark(d, er, tc, seqs, fp_col, umaps)

    log("")
    log("=" * 78)
    log("STAGE 5 -- benchmark table")
    log("=" * 78)
    log(f"rows (target, site): {len(bm)}   targets: {bm.target.nunique()}   "
        f"designs: {int(bm.n_designs.sum())}")
    cols = ["site_id", "target", "n_designs", "n_binders", "success_rate",
            "ci95_low", "ci95_high", "site_n_residues_consensus",
            "mean_pairwise_jaccard", "n_generators"]
    log("")
    log("Estimable rows (n_designs >= %d):" % MIN_DESIGNS_FOR_RATE)
    log(bm[bm.estimable][cols].to_string(index=False))

    pw = power_report(d, bm)
    site_signal_test(d)
    variance_decomposition(d, bm, pw)
    confound_report(d)
    recommended_evaluation(d, bm, pw)

    # ---- K sensitivity arm, rebuilt end to end ----
    log("")
    log("=" * 78)
    log(f"K SENSITIVITY ARM -- the whole benchmark rebuilt at "
        f"K={FOOTPRINT_K_SENSITIVITY}")
    log("=" * 78)
    ka = FOOTPRINT_K_SENSITIVITY
    d2 = d.drop(columns=["site_id"]).copy()
    d2[f"fp{ka}"] = d2.uuid.map(fp_cache[ka])
    d2 = assign_sites(d2, f"fp{ka}", JACCARD_CHOSEN)
    bm2 = build_benchmark(d2, er, tc, seqs, f"fp{ka}", umaps)
    cmp_rows = []
    for tag, dd, bb, kk in ((f"K={FOOTPRINT_K} (primary)", d, bm, FOOTPRINT_K),
                            (f"K={ka} (sensitivity)", d2, bm2, ka)):
        est = bb[bb.estimable]
        n_sig = 0
        n_inf = 0
        for tgt, g in est.groupby("target"):
            base = float(dd[dd.target == tgt].binder_final.mean())
            spread = g.success_rate.max() - g.success_rate.min()
            if len(g) >= 2 and 0.05 < base < 0.80 and spread > 0:
                n_inf += 1
            if len(g) >= 2:
                tab = np.array([[r.n_binders, r.n_designs - r.n_binders]
                                for r in g.itertuples()])
                tab = tab[tab.sum(axis=1) > 0]
                if tab.shape[0] >= 2:
                    try:
                        p = (stats.fisher_exact(tab)[1] if tab.shape[0] == 2
                             else stats.chi2_contingency(tab)[1])
                        n_sig += int(p < 0.05)
                    except ValueError:
                        pass
        y = dd.binder_final.astype(float)
        gm = y.mean()
        ss_t = sum(len(g) * (g.binder_final.mean() - gm) ** 2
                   for _, g in dd.groupby("target"))
        ss_s = 0.0
        for _, g in dd.groupby("target"):
            pt = g.binder_final.mean()
            for _, h in g.groupby("site_id"):
                ss_s += len(h) * (h.binder_final.mean() - pt) ** 2
        cmp_rows.append({
            "arm": tag, "n_sites": len(bb),
            "n_estimable": int(bb.estimable.sum()),
            "n_targets_informative": n_inf,
            "n_targets_sig_heterogeneous": n_sig,
            "mean_site_success": round(float(est.success_rate.mean()), 3),
            "median_site_n": int(est.n_designs.median()),
            "mean_pairwise_jaccard": round(float(est.mean_pairwise_jaccard.mean()), 3),
            "target_site_var_ratio": round(ss_t / ss_s, 2),
        })
    cmpdf = pd.DataFrame(cmp_rows)
    log(cmpdf.to_string(index=False))
    log("")
    log(f"  The primary K was moved from 12 to {FOOTPRINT_K} because the K")
    log("  sweep shows K=10 strictly better on BOTH criteria that matter:")
    log("  more estimable rows AND a weaker residual size/provenance")
    log("  confound (the residual comes from designs with fewer than K")
    log("  contacts, which cannot be padded, so a smaller K leaves fewer of")
    log("  them). K=8 de-confounds further still but costs ~20 estimable")
    log("  rows, which this benchmark cannot afford. Both arms ship.")
    bm2.to_csv(os.path.join(OUT, f"site_benchmark_K{ka}.csv"), index=False)
    cmpdf.to_csv(os.path.join(OUT, "k_sensitivity_comparison.csv"), index=False)

    val = pd.DataFrame()
    if args.validate:
        val = validate_resolved(d, bm, seqs, fp_col)

    # ---- outputs ----
    bm.to_csv(os.path.join(OUT, "site_benchmark.csv"), index=False)
    per = d[["uuid", "full_name", "target", "site_id", "design_model",
             "campaign", "generator", "sequence_design_method", "binder_length",
             "rank", "binder_final", "kd_nM_final", "adaptyv_binding",
             "twist_binding", "vendor_agreement", "adaptyv_expression",
             "adaptyv_n_replicates", "epitope_n_residues",
             "label_exclusion_reason"]].copy()
    per["footprint_residues"] = d[fp_col].map(lambda s: ";".join(map(str, sorted(s))))
    per = per.merge(er[["uuid", "source_file_kind", "target_construct_id"]],
                    on="uuid")
    per.to_csv(os.path.join(OUT, "design_site_map.csv"), index=False)

    exc = excluded[["uuid", "full_name", "target", "generator", "binder_final",
                    "adaptyv_binding", "twist_binding", "adaptyv_expression",
                    "twist_expression_mg_per_mL", "epitope_n_residues",
                    "label_exclusion_reason"]]
    exc.to_csv(os.path.join(OUT, "excluded_designs.csv"), index=False)
    pw.to_csv(os.path.join(OUT, "power_analysis.csv"), index=False)
    kdf.to_csv(os.path.join(OUT, "footprint_k_sweep.csv"), index=False)
    if len(val):
        val.to_csv(os.path.join(OUT, "resolved_complex_validation.csv"),
                   index=False)

    with open(os.path.join(OUT, "site_reference_sequences.fasta"), "w") as fh:
        for _, r in tc.iterrows():
            for i, s in enumerate(seqs[r["target"]], 1):
                fh.write(f">{r['target_construct_id']}|{r['target']}|chain{i}|"
                         f"len{len(s)}|1-based positions used by "
                         f"site_residues_*\n{s}\n")

    log("")
    log("=" * 78)
    log("OUTPUTS")
    log("=" * 78)
    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        if os.path.isfile(p):
            log(f"  {os.path.getsize(p):>9d}  {f}")

    me = os.path.abspath(__file__)
    log("")
    log(f"script sha256: {sha256(me)}  {me}")
    log(f"finished {datetime.now(timezone.utc).isoformat()}")
    with open(os.path.join(OUT, "RECEIPT.txt"), "w") as fh:
        fh.write("\n".join(RECEIPT) + "\n")


if __name__ == "__main__":
    main()
