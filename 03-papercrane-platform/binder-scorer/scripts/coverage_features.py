#!/usr/bin/env python3
"""Two literature-flagged features our static fold misses (LLM discovery -> compute):

(1) glycan_shield   — does the binder's interface overlap N-glycosylation sequons
    (N-X-[S/T])? The fold is BARE protein, so a binder can 'win' in silico on a face
    that real glycan blocks. Flag = #glyc sequons in the construct whose Asn is
    shadowed by the binder (binder atom within GLYCAN_R). Higher = worse.
(2) ligand_occlusion — does the binder cover the NATURAL LIGAND's footprint (the
    functional site, from literature via the LLM)? Covers it -> functionally blocks.
    = fraction of ligand-site residues the binder contacts.

Honest caveat: both predict FUNCTION/IN-VIVO success; our labels are IN-VITRO binding
(often on non-glycosylated target). So they may not lift P@20 here even if correct —
that gap is itself the point (our benchmark measures binding, not function).
"""
from __future__ import annotations
import glob, json, os, re, sys
import numpy as np
import gemmi
from scipy.spatial import cKDTree

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import load_designs           # noqa: E402
from scorer.metric_power import _auc                  # noqa: E402
from scripts.pdl1_uniform_experiment import _call      # noqa: E402

TARGETS = ["PDL1", "MDM2", "INSULINR", "EGFR", "IL7R"]
GLYCAN_R = 12.0      # glycans extend ~10-15 A from the Asn
CONTACT = 5.0
K = 20


def construct(t):
    txt = open(os.path.join(REPO, "data/raw/target_references.fasta")).read()
    for b in re.split(r"^>", txt, flags=re.M):
        if b.upper().startswith(t):
            seq = "".join(b.split("\n")[1:]).strip()
            m = re.search(r"(\d+)-(\d+)", b.split("\n")[0]); off = int(m.group(1)) - 1 if m else 0
            return seq, off
    return None, 0


def nglyc_asn(seq, off):
    """0-based construct index -> full residue number of each N-X-[S/T] (X!=P) Asn."""
    return {i: i + 1 + off for i in range(len(seq) - 2)
            if seq[i] == "N" and seq[i + 1] != "P" and seq[i + 2] in "ST"}


def ligand_sites_llm():
    """One batched LLM call: per target, the residues that contact the NATURAL ligand."""
    prompt = """For each human target below, give the residues that DIRECTLY CONTACT its natural
binding partner / ligand in the published co-complex structure (the functional site a therapeutic
binder must occlude to block signaling). Use standard UniProt residue numbering. Targets and their
natural ligand:
- PDL1 (CD274): contacts PD-1
- MDM2: contacts p53 transactivation-domain peptide
- INSULINR: contacts insulin (site 1, L1 + alphaCT)
- EGFR: contacts EGF (domain III/ I face)
- IL7R (IL-7Ralpha): contacts IL-7
Output JSON ONLY: {"PDL1":{"ligand":"PD-1","residues":[..ints..],"pdb":"4ZQK"}, "MDM2":{...}, ...}
Give the well-characterized contact residues; integers only."""
    raw = _call(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1]; raw = raw[4:] if raw.lstrip().startswith("json") else raw
    i, j = raw.find("{"), raw.rfind("}")
    return json.loads(raw[i:j + 1])


def design_features(cif, glyc_full, ligand_full, off):
    m = gemmi.read_structure(cif)[0]
    ch = {c.name: c for c in m}
    A, B = ch.get("A"), ch.get("B")
    if not A or not B:
        return None
    bpos = np.array([[a.pos.x, a.pos.y, a.pos.z] for r in B for a in r if not a.element.is_hydrogen])
    btree = cKDTree(bpos)
    # map full residue numbers -> construct CA positions
    ca = {}
    contacted = set()
    for ti, res in enumerate(A, start=1):
        full = ti + off
        cat = res.find_atom("CA", "*")
        if cat is not None:
            ca[full] = [cat.pos.x, cat.pos.y, cat.pos.z]
        if any(btree.query([a.pos.x, a.pos.y, a.pos.z])[0] <= CONTACT for a in res if not a.element.is_hydrogen):
            contacted.add(full)
    # glycan_shield: # glyc Asn shadowed by binder
    shield = sum(1 for full in glyc_full.values()
                 if full in ca and btree.query(ca[full])[0] <= GLYCAN_R)
    # ligand_occlusion: fraction of ligand-site residues (in construct) the binder contacts
    lig_in = [r for r in ligand_full if r in ca]
    occl = (sum(1 for r in lig_in if r in contacted) / len(lig_in)) if lig_in else 0.0
    return shield, occl, len(lig_in)


def main():
    print("Fetching natural-ligand sites from the LLM (literature)...")
    try:
        lig = ligand_sites_llm()
        print("  ligand sites:", {t: f"{v.get('ligand')}({len(v.get('residues',[]))}res,{v.get('pdb')})" for t, v in lig.items()})
    except Exception as e:
        print("  LLM failed:", str(e)[:60], "-> ligand_occlusion will be 0"); lig = {}

    print(f"\n{'target':9}{'n':>5}{'#glyc_seq':>10}{'#lig_in':>9}   "
          f"{'glyc_AUC':>9}{'occl_AUC':>9}{'rho_ipsae':>11}")
    for t in TARGETS:
        seq, off = construct(t)
        glyc = nglyc_asn(seq, off)
        ligand_full = set(int(r) for r in lig.get(t, {}).get("residues", []))
        designs = {d["design_id"]: d for d in load_designs("data/processed/labeled_features_bio.csv")
                   if d["target"].upper() == t}
        rows = []
        from scripts.compute_ipsae import ipsae, chain_lengths
        for d in glob.glob(f"/tmp/{t.lower()}_folds/{t}_*"):
            cif = os.path.join(d, "outputs/files/prediction/sample_0_predicted_structure.cif")
            paef = os.path.join(d, "outputs/files/prediction/sample_0_pae.npz")
            did = f"{t}:" + os.path.basename(d).split("_", 1)[1]
            if not (os.path.exists(cif) and os.path.exists(paef)) or did not in designs:
                continue
            f = design_features(cif, glyc, ligand_full, off)
            if f is None:
                continue
            cl = chain_lengths(cif)
            isae = ipsae(np.load(paef)["pae"], cl[0], cl[1]) if cl else 0.0
            rows.append({"binds": designs[did]["binds"], "glyc": f[0], "occl": f[1], "ipsae": isae, "lig_in": f[2]})
        if not rows:
            print(f"{t:9} no data"); continue
        n = len(rows)
        # glycan is a PENALTY (higher=worse) -> AUC of -glyc; occlusion is positive
        ga = _auc([(-r["glyc"], r["binds"]) for r in rows])
        oa = _auc([(r["occl"], r["binds"]) for r in rows]) if ligand_full else None
        # orthogonality: spearman-ish corr of occl vs ipsae
        oc = np.array([r["occl"] for r in rows]); ip = np.array([r["ipsae"] for r in rows])
        rho = float(np.corrcoef(oc, ip)[0, 1]) if oc.std() and ip.std() else 0.0
        print(f"{t:9}{n:>5}{len(glyc):>10}{rows[0]['lig_in']:>9}   "
              f"{ga:>9.3f}{(f'{oa:.3f}' if oa else 'n/a'):>9}{rho:>11.2f}")
    print("\nNote: AUC vs IN-VITRO binding labels. glyc>0.5 / occl>0.5 = the feature tracks binding;")
    print("near 0.5 likely means the assay used non-glycosylated target / scored binding-not-function.")


if __name__ == "__main__":
    main()
