"""Combine the 3 Nebius V5 picks with the top 4 V3/V4 Modal sequences
(ranked by boltz2_min_ipsae — AUC 0.806, strongest predictor per the
project metrics-thresholds memory) into a single ordered CSV."""
from __future__ import annotations
import csv
from pathlib import Path

ROOT = Path(__file__).parent.parent          # mosaic project root
NEBIUS_PICKS = ROOT / "nebius/outputs/5g51_v5_top_picks.csv"
V4_CANDIDATES = ROOT / "5g51_v4_boltz2_candidates.csv"
V4_BOLTZ2 = ROOT / "boltz2_5g51_v4_results.csv"
V3B = ROOT / "god_v3b_results.csv"
OUT = ROOT / "nebius/outputs/5g51_combined_order.csv"


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def main():
    # ----- V5 (already curated) -----
    v5 = load_csv(NEBIUS_PICKS)

    # ----- V4: join candidates (seq) with boltz2 validation (ipsae) by seed -----
    v4_seq = {int(r["seed"]): r for r in load_csv(V4_CANDIDATES)}
    v4_score = {int(r["seed"]): r for r in load_csv(V4_BOLTZ2)}
    v4_rows = []
    for seed, score in v4_score.items():
        if seed not in v4_seq:
            continue
        seq_row = v4_seq[seed]
        v4_rows.append({
            "campaign": "V4",
            "seed": seed,
            "sequence": seq_row["sequence"],
            "length": int(seq_row["length"]),
            "cys_count": int(seq_row["cys_count"]),
            "boltz2_min_ipsae": float(score["boltz2_min_ipsae"]),
            "boltz2_iptm": float(score["boltz2_iptm"]),
            "boltz2_plddt": float(score["boltz2_plddt"]),
            "protenix_iptm": float(seq_row["protenix_iptm"]),
        })
    v4_rows.sort(key=lambda r: -r["boltz2_min_ipsae"])

    # ----- V3b: scores + seq already in one file -----
    v3b_rows = []
    for r in load_csv(V3B):
        try:
            v3b_rows.append({
                "campaign": "V3b",
                "seed": int(r["seed"]),
                "sequence": r["sequence"],
                "length": int(r["length"]),
                "cys_count": int(r["cys_count"]),
                "boltz2_min_ipsae": float(r["boltz2_min_ipsae"]),
                "boltz2_iptm": float(r["boltz2_iptm"]),
                "boltz2_plddt": float(r["boltz2_plddt"]),
                "protenix_iptm": float(r["protenix_iptm"]),
            })
        except (KeyError, ValueError):
            continue
    v3b_rows.sort(key=lambda r: -r["boltz2_min_ipsae"])

    # ----- Top-4 across V3b+V4 by min_ipsae (any cys) -----
    modal_pool = sorted(v3b_rows + v4_rows, key=lambda r: -r["boltz2_min_ipsae"])
    seen = set()
    modal_top = []
    for r in modal_pool:
        k = (r["campaign"], r["seed"])
        if k in seen:
            continue
        seen.add(k)
        modal_top.append(r)
        if len(modal_top) >= 4:
            break

    # ----- Top-3 ADDITIONAL: cys=0 only, not already picked, by min_ipsae -----
    already = {(r["campaign"], r["seed"]) for r in modal_top}
    cysfree_pool = [r for r in modal_pool
                    if r["cys_count"] == 0 and (r["campaign"], r["seed"]) not in already]
    cysfree_top3 = cysfree_pool[:3]

    # ----- Build unified order CSV -----
    out_rows = []
    for r in v5:
        out_rows.append({
            "name": r["name"],
            "campaign": "V5",
            "seed": int(r["seed"]),
            "sequence": r["sequence"],
            "length": len(r["sequence"]),
            "cys_count": r["sequence"].count("C"),
            "primary_metric": "v5_composite",
            "primary_metric_value": "see nebius/outputs/5g51_v5_best_sequences.csv",
            "notes": "Nebius V5 + hotspot loss (Ile145/Phe148)",
        })
    for r in modal_top:
        name = f"5G51_{r['campaign']}_seed{r['seed']:02d}"
        out_rows.append({
            "name": name,
            "campaign": r["campaign"],
            "seed": r["seed"],
            "sequence": r["sequence"],
            "length": r["length"],
            "cys_count": r["cys_count"],
            "primary_metric": "boltz2_min_ipsae",
            "primary_metric_value": f"{r['boltz2_min_ipsae']:.4f}",
            "notes": f"Modal {r['campaign']} top-4 — boltz2_iptm={r['boltz2_iptm']:.3f} "
                     f"plddt={r['boltz2_plddt']:.3f} protenix_iptm={r['protenix_iptm']:.3f}",
        })
    for r in cysfree_top3:
        name = f"5G51_{r['campaign']}_seed{r['seed']:02d}_cysfree"
        out_rows.append({
            "name": name,
            "campaign": r["campaign"],
            "seed": r["seed"],
            "sequence": r["sequence"],
            "length": r["length"],
            "cys_count": r["cys_count"],
            "primary_metric": "boltz2_min_ipsae",
            "primary_metric_value": f"{r['boltz2_min_ipsae']:.4f}",
            "notes": f"Modal {r['campaign']} cys-free top-3 — boltz2_iptm={r['boltz2_iptm']:.3f} "
                     f"plddt={r['boltz2_plddt']:.3f} protenix_iptm={r['protenix_iptm']:.3f}",
        })

    # ----- 5 external picks from the design-platform screenshots -----
    # "Min iPAE" is lower-is-better (PAE convention). Picks are the 5 lowest
    # iPAE values among the 8 screenshots; all 5 happen to be cys-free.
    external = [
        # seq_id, sequence,                                    pTM,   pLDDT, RMSD, ipae, len, cys
        (60, "TLEEAKAAALAEISAYLDDKAKEFDITVEAALKAKLLADAKAALDQAADVAQVETLKAEAKQLIFEFLKWANNQGKKTLSLADFEAFKASVPKTTETALF",
         0.94, 0.96, 0.44, 0.38, 100, 0),
        (51, "ASKTELISKVKAKITELETQLNSVNAAIATLEDTSVSDADKKAAAIAAKKGTLLDKLLTDAQINNLTPAQLLTLLKAEQQVLQESITGLKEILAKLEAGSLDLNETVTVQTGLPQPMIDALKAIGRDDLVAANPVTKRQEKLVDVLSKIP",
         0.94, 0.96, 0.61, 0.41, 150, 0),
        (4,  "AAAGFHLEIEGDQTKVTDVKNLDQAKAEKLAQSVKRALQYLVANEKPYSSLEEETTLPVNFKVVDVQVDGKTYTLDVKGELTGEKGKLVKADVDVEVTEE",
         0.94, 0.94, 0.57, 0.46, 100, 0),
        (99, "ASVSAQLSALVDEYTAKLDALNADIVAAVDAGDAAKLAALEAQEAALIAAFLAKVAAVLDGIANQTQFSNAYADMQQILEQTTNYYKALLSGLTLLLLQDKAAEKGFAVAQDAQTLIKNTVLAKYGAADGQKVYDKILAEYAAYKAAQAA",
         0.96, 0.95, 0.51, 0.53, 150, 0),
        (93, "GAAVEQAKQEILKEVQKKKAEGAKEVVYLTTNKANAETVESALKELKAEGKIKDFKKEELTAEKVEVTLKDGYTAQQNGVKIAQEVKKLPQVKDVDIAELSGQELTLAVVLKDGEKIENVVEEVKKLPEVKDAKKGSSTTTLYKFTVTLK",
         0.92, 0.93, 0.57, 0.59, 150, 0),
    ]
    for seq_id, seq, ptm, plddt, rmsd, ipae, length, cys in external:
        out_rows.append({
            "name": f"5G51_ext_seq{seq_id:02d}",
            "campaign": "external",
            "seed": seq_id,
            "sequence": seq,
            "length": length,
            "cys_count": cys,
            "primary_metric": "min_iPAE_external",
            "primary_metric_value": f"{ipae:.2f}",
            "notes": f"Design-platform screenshot — pTM={ptm:.2f} pLDDT={plddt:.2f} "
                     f"complex_RMSD={rmsd:.2f} (Min iPAE lower-is-better)",
        })

    cols = ["name", "campaign", "seed", "sequence", "length", "cys_count",
            "primary_metric", "primary_metric_value", "notes"]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)

    print(f"Wrote {OUT}  ({len(out_rows)} sequences)\n")
    print(f"{'#':>2} {'campaign':<8} {'seed':>4} {'cys':>3} {'len':>3} "
          f"{'metric':<18} {'value':<10}  name")
    print("-" * 95)
    for i, r in enumerate(out_rows, 1):
        print(f"{i:>2} {r['campaign']:<8} {r['seed']:>4} {r['cys_count']:>3} "
              f"{r['length']:>3} {r['primary_metric']:<18} "
              f"{str(r['primary_metric_value'])[:10]:<10}  {r['name']}")


if __name__ == "__main__":
    main()
