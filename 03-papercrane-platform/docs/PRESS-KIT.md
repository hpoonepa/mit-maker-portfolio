# Paper Crane — Press Kit

## At a glance

| Field | Value |
|---|---|
| **Company** | Paper Crane |
| **Founded** | 2026 |
| **HQ** | Remote — operating out of Georgia, USA |
| **Domain** | papercrane.bio |
| **Stage** | Pre-seed, closed beta |
| **Funding** | TBD |
| **Team size** | TBD |
| **Contact** | hello@papercrane.bio |

---

## One-liner

Paper Crane is a managed protein-binder design platform that runs the best open-source models — BoltzGen, BindCraft, RFdiffusion, ProteinMPNN, Boltz-2, Chai-1 — behind a single workflow, ranks the outputs with validated metrics, and delivers wet-lab-ready sequences.

## Two-sentence description

Paper Crane gives biology labs a one-click pipeline from PDB target to ranked, exportable binder candidates without writing GPU code or stitching together a dozen GitHub repos. We bring-your-own-key for compute, so labs keep their data, their credits, and their results.

---

## Why "Paper Crane"

The name comes from **Senbazuru** — the Japanese tradition of folding 1,000 origami cranes (千羽鶴) as a wish for healing. In binder design, you fold 1,000 sequences and hope a few of them bind. One crane is a wish; a thousand is a campaign. That's the work.

---

## Founder

**Harsha Poonepalle** — Founder & CEO
- High school junior, Lambert High School (Georgia, USA), Class of 2027
- Background: synthetic biology, AI for protein design, computational biology research
- Built the first version of the Paper Crane pipeline as part of an iGEM 2026 software-track project
- Contact: hello@papercrane.bio

---

## Product

A web app + API at **papercrane.bio** that takes a target structure (PDB ID or upload), surfaces hotspot residues, runs binder-design jobs against managed or BYOK GPU compute, and returns ranked designs with full metrics, side-by-side comparison, and FASTA export.

### The 12-tool stack

Paper Crane orchestrates the following open-source models and validators:

1. **BoltzGen** — all-atom diffusion design (side-chain aware from the start).
2. **BindCraft** — hallucination-based binder design with built-in AF2 validation.
3. **RFdiffusion** — backbone generation for de novo binders.
4. **ProteinMPNN** — inverse folding for sequence design on a backbone.
5. **LigandMPNN** — ligand-aware sequence design for cofactor / small-molecule pockets.
6. **SolubleMPNN** — solubility-optimized sequences for E. coli expression.
7. **Boltz-1 / Boltz-2** — open structure prediction for complex validation.
8. **Chai-1** — foundation-model structure prediction for protein-protein and protein-ligand complexes.
9. **AlphaFold2 / AF-Multimer** — gold-standard validation and confidence metrics.
10. **ESM2** — pseudo-log-likelihood scoring and embeddings for sequence plausibility.
11. **ipSAE ranker** — interprotein Score from Aligned Errors, exposed with target-specific performance caveats rather than a universal accuracy claim.
12. **Foldseek** — structural homology search across PDB and AFDB.

---

## Beta program

- **Status:** invite-only closed beta as of 2026-04.
- **Who we're letting in:** academic labs running real binder-design campaigns, plus a small number of biotech R&D teams.
- **What beta members get:** free credits during the beta window, direct Slack channel with the founder, priority on new model integrations, locked-in launch pricing.
- **Waitlist:** **https://papercrane.bio/waitlist**
- **Beta duration:** TBD (rolling, capped on slots not date).

---

## Key facts (no fabrication)

- 12 open-source tools integrated under one workflow.
- Bring-your-own-key support for Modal GPU compute (more providers TBD).
- Validated ranking using ipSAE > ipTM > pDockQ hierarchy (research-backed thresholds).
- Customer count: **TBD — closed beta**.
- Designs run to date: **TBD**.
- Revenue: **TBD — pre-revenue**.
- Press coverage: **TBD**.

> Note to journalists: we will not provide fabricated metrics. If a number is not in this document it is not yet ready to share. Email hello@papercrane.bio for the latest figures under embargo.

---

## Visual assets

- **Logo:** TBD (origami crane mark — assets in `/public/brand/` once finalized).
- **Product screenshots:** TBD — pending Wave-D screenshot capture pass.
  - `/benchmark` Pareto frontier
  - `/dashboard` project list
  - `/target` Mol* viewer with hotspots
  - `/app/designs` ranked design grid
  - Side-by-side compare view
- **Founder photo:** TBD.
- **Demo video:** TBD — see `DEMO-SCRIPT.md` for the 5-minute flow.

---

## Boilerplate (use freely)

> Paper Crane is a managed protein-binder design platform that turns any PDB target into ranked, wet-lab-ready binder candidates. By orchestrating the best open-source design and validation models — BoltzGen, BindCraft, RFdiffusion, ProteinMPNN, Boltz-2, Chai-1 and more — behind a single workflow, Paper Crane lets biology labs run state-of-the-art campaigns without writing GPU code. Founded in 2026 and headquartered in Georgia, USA, the company operates a closed beta for academic and biotech labs. Learn more at papercrane.bio.

---

## Contact

- **General / press:** hello@papercrane.bio
- **Beta access:** https://papercrane.bio/waitlist
- **Founder (direct):** hello@papercrane.bio
