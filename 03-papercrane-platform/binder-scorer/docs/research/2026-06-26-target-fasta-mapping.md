# Target FASTA reference — well-powered targets (2026-06-26)

Trimmed to the binder-relevant domain using UniProt annotations + literature. Full-length UniProt FASTAs cached under `data/raw/targets/`. Construct sequences in `data/raw/target_references.fasta`.

| Target | UniProt | Construct range | Len | Confidence | Domain |
|--------|---------|-----------------|-----|------------|--------|
| EGFR | P00533 | 310-510 | 201 | APPROX | Ectodomain domain III (L2, EGF/cetuximab-binding face) |
| FGFR2 | P21802 | 154-358 | 205 | GOOD | Ig-like D2-D3 (FGF/ligand-binding) |
| IL7R | P16871 | 21-239 | 219 | GOOD | Extracellular cytokine-binding ectodomain |
| INSULINR | P06213 | 28-310 | 283 | APPROX | alpha-subunit L1+CR (provisional site-1 region) |
| MDM2 | Q00987 | 17-125 | 109 | GOOD | p53-binding SWIB domain (1YCR construct) |
| PDL1 | Q9NZQ7 | 19-127 | 109 | GOOD | Ig-like V-type domain (PD-1-binding face) |
| PD1 | Q15116 | 25-170 | 146 | GOOD | Extracellular IgV ectodomain |

## Confidence notes
- **GOOD** (5): FGFR2, IL7R, MDM2, PDL1, PD1 — construct matches annotated domain boundaries / standard binding-study constructs.
- **APPROX** (2): 
  - **EGFR** — domain III boundary varies across sources; used padded 310-510. Confirm against the actual design PDB (3NJP) before trusting ipSAE.
  - **INSULINR** — exact Cao/Baker construct unconfirmed (insulin receptor has multiple binder-accessible sites: L1/site-1 vs FnIII/site-2). Provisional L1+CR (28-310). MUST confirm PDB before backfill.

## Still needed (relaxed + other targets, not yet pulled)
TRKA, VIRB8, SARS_RBD, IL2RA, SNTX, BBF14, DER7, IFNAR2, LTK, IL10RA, CD45, BETV1, CLDN1, etc.
Proteinbase targets (NIPAH, PMVK, MZB1, PDGFRB, metabolic enzymes) already have boltz2_min_ipsae — no FASTA needed for backfill.
