#!/usr/bin/env python3
"""PDL1 on CLEAN uniform Boltz metrics: top single features vs LLM-from-literature.

1. Build the uniform metric table (all 177 PDL1 designs, fresh Boltz-2.1 folds).
2. Re-prompt the LLM with PDL1 literature + the uniform metric menu (NO data AUCs
   -> purely literature/knowledge-driven, leakage-free) -> signed weights + what
   it thinks matters.
3. Benchmark P@20 + within-PDL1 AUC: B0 (old data), each top single feature,
   and the LLM-weighted combination.
"""
from __future__ import annotations
import csv, glob, json, os, sys
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scorer.data_loader import load_designs            # noqa: E402
from scorer.metric_power import _auc                   # noqa: E402
from scorer.llm_prior import AnthropicClient           # noqa: E402

UNIFORM_CSV = os.path.join(REPO, "data/processed/pdl1_uniform_boltz.csv")
K = 20
# menu: key -> (direction higher_is_better, plain description for the LLM)
MENU = {
    "iptm":                 (1, "interface predicted TM-score (0-1): model's confidence the binder-target INTERFACE is correctly predicted"),
    "ptm":                  (1, "predicted TM-score (0-1): overall complex fold confidence"),
    "complex_iplddt":       (1, "interface pLDDT (0-1): per-atom confidence at the interface"),
    "complex_ipde":         (-1, "interface predicted distance error (LOWER is better): expected error in interface contact distances"),
    "structure_confidence": (1, "overall predicted-structure confidence (0-1)"),
    "n_contact":            (1, "number of target residues the binder contacts (interface size)"),
    "epitope_contact":      (1, "fraction of the binder's target-contact footprint that lands on the literature PD-1 epitope"),
    "epitope_coverage":     (1, "fraction of the literature epitope residues the binder touches"),
}


def build_uniform_table():
    designs = {d["design_id"]: d for d in load_designs("data/processed/labeled_features_bio.csv")
               if d["target"].upper() == "PDL1"}
    ec = {r["design_id"]: r for r in csv.DictReader(open("data/processed/pdl1_epitope_contact.csv"))}
    rows = []
    for d in glob.glob("/tmp/pdl1_folds/PDL1_*"):
        mj = os.path.join(d, "outputs/files/prediction/metrics.json")
        if not os.path.exists(mj):
            continue
        did = "PDL1:" + os.path.basename(d).split("_", 1)[1]
        if did not in designs:
            continue
        m = json.load(open(mj))["best_sample"]["metrics"]
        r = {"design_id": did, "binds": designs[did]["binds"],
             "iptm": m["iptm"], "ptm": m["ptm"], "complex_iplddt": m["complex_iplddt"],
             "complex_ipde": m["complex_ipde"], "structure_confidence": m["structure_confidence"]}
        if did in ec:
            r["n_contact"] = int(ec[did]["n_contact"])
            r["epitope_contact"] = float(ec[did]["epitope_contact"])
            r["epitope_coverage"] = float(ec[did]["epitope_coverage"])
        rows.append(r)
    with open(UNIFORM_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["design_id", "binds"] + list(MENU))
        w.writeheader(); w.writerows(rows)
    return rows


def _call(prompt, tries=4):
    import urllib.request, pathlib
    key = os.environ.get("ANTHROPIC_API_KEY") or [l.split("=", 1)[1].strip()
          for l in pathlib.Path(os.path.join(REPO, ".env")).read_text().splitlines()
          if l.startswith("ANTHROPIC_API_KEY=")][0]
    body = json.dumps({"model": "claude-opus-4-6", "max_tokens": 1500,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    last = ""
    for _ in range(tries):
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
              headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=120).read())
        if d.get("content"):
            return d["content"][0]["text"]
        last = d.get("stop_reason", "?")
    raise RuntimeError(f"model returned no content after {tries} tries (stop_reason={last})")


def llm_weights(rows):
    """Re-prompt the LLM with PDL1 literature + the uniform menu. No data AUCs."""
    lit = json.load(open("data/processed/literature/PDL1.json"))
    abstracts = "\n".join(f"- [{a.get('pmid','')}] {a.get('title','')}" for a in lit.get("abstracts", [])[:15])
    menu_txt = "\n".join(f"  - {k}: {desc} ({'higher=better' if d > 0 else 'lower=better'})"
                         for k, (d, desc) in MENU.items())
    prompt = f"""You are a computational protein engineer prioritizing de novo protein binder designs
against PD-L1 (a validated, widely-studied cancer-immunotherapy target) for wet-lab validation. This is
standard structure-based therapeutic design. Each candidate was folded in complex with PD-L1 using
Boltz-2.1; the confidence/interface metrics below are available uniformly for every candidate. Your job
is to set a SIGNED importance weighting over these metrics to rank candidates by how likely each is a
genuine binder, informed by the literature and your knowledge of protein-protein interaction prediction.

PD-L1 binder / interface design literature:
{abstracts}

AVAILABLE METRICS:
{menu_txt}

Output JSON ONLY (no prose):
{{"weights": {{<metric>: <signed float; + = higher value -> more likely a real binder, - = less likely>}},
  "most_important": "<the single metric you trust most and why, one sentence>",
  "rationale": "<2-3 sentences on what you weighted and why>"}}
Concentrate weight on what actually predicts binding (a diffuse weighting is weak). Never reference experimental binding labels."""
    raw = _call(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        raw = raw[4:].strip() if raw.lstrip().startswith("json") else raw.strip()
    i, j = raw.find("{"), raw.rfind("}")
    return json.loads(raw[i:j + 1])


def main():
    rows = build_uniform_table()
    npos = sum(1 for r in rows if r["binds"])
    print(f"uniform PDL1 table: {len(rows)} designs, {npos} binders ({npos/len(rows):.1%}), k={K}\n")

    def signed(r, k):
        return r[k] * MENU[k][0] if k in r and r[k] is not None else None

    def auc(score_of):
        p = [(score_of(r), r["binds"]) for r in rows]
        p = [(s, l) for s, l in p if s is not None and s == s]
        return _auc(p)

    def patk(score_of, kk=K):
        s = [(score_of(r), r) for r in rows if score_of(r) is not None]
        s.sort(key=lambda x: -x[0]); top = s[:kk]
        return sum(1 for _, r in top if r["binds"]) / len(top)

    print("=== ask the LLM (literature only, no data AUCs) ===")
    w = llm_weights(rows)
    print("MOST IMPORTANT (LLM):", w.get("most_important"))
    print("RATIONALE:", w.get("rationale"))
    print("WEIGHTS:", {k: round(v, 3) for k, v in w["weights"].items()})

    # z-scores of the RAW metric (LLM's signed weight encodes direction, so do
    # NOT direction-correct here, or complex_ipde double-flips).
    def zmap(k):
        v = np.array([(r[k] if k in r and r[k] is not None else np.nan) for r in rows], float)
        mu, sd = np.nanmean(v), np.nanstd(v)
        return {id(r): (0.0 if not np.isfinite(x) else (x - mu) / sd) for r, x in zip(rows, v)} if sd else None
    zs = {k: zmap(k) for k in MENU}

    def llm_score(r):
        s = 0.0
        for k, wt in w["weights"].items():
            if k in zs and zs[k] is not None:
                s += wt * zs[k][id(r)]  # weight sign (from LLM) encodes direction
        return s

    print(f"\n=== PDL1 ranking quality (base rate {npos/len(rows):.3f}) ===")
    print(f"{'ranking':32}{'AUC':>7}{'P@20':>7}")
    print(f"{'B0 (OLD best_ipsae, fragmented)':32}{'-':>7}{'0.300':>7}   <- the old benchmark")
    for k in ["iptm", "complex_ipde", "ptm", "structure_confidence", "epitope_contact"]:
        print(f"{('single: '+k):32}{auc(lambda r,k=k: signed(r,k)):>7.3f}{patk(lambda r,k=k: signed(r,k)):>7.3f}")
    print(f"{'LLM-weighted (from literature)':32}{auc(llm_score):>7.3f}{patk(llm_score):>7.3f}")


if __name__ == "__main__":
    main()
