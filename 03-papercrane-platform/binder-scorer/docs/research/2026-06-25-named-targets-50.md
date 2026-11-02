All the research is already provided in the prompt. I just need to deduplicate, merge, tier, and produce the markdown. No tools needed — this is synthesis work.

# Paper Crane — 50 Named Targets (where to get them)

## Reality check up top

This is the honest accounting. **Tier A is brutally small.** After deduplicating across all four research dumps, the de-novo binder world gives only a handful of targets with both ≥10 tested positives *and* real tested negatives. Everything else is either thin (train-only), natural PPI (transfer), or antibody/nanobody (separate world).

### Tier counts (after dedup)

| Tier | Definition | Count |
|------|-----------|-------|
| **A** | On-distribution de-novo target, ≥10 tested pos + real tested neg → usable as LOTO test | **7** (only 5 are clean; 2 are license-blocked or thin) |
| **B** | De-novo target, labels but thin (<10 pos) or partial neg → pooled training only | **24** |
| **C** | Natural PPI / affinity (SKEMPI, Affinity Benchmark, PPB-Affinity, small-mol/peptide-vs-peptide) → transfer-pretrain only | **16** |
| **D** | Antibody/nanobody antigen as target → transfer/validation only | **3** |
| | **TOTAL DISTINCT** | **50** |

We hit exactly 50 distinct named targets — but read the Tier A shortlist before getting excited. The padding to 50 comes from Tier C (natural affinity) and Tier B novel probes, which is exactly what the brief warned would happen.

### The blunt truth about Tier A

The single best on-distribution resource is **Overath et al. 2025** (Zenodo 15722219, CC-BY-4.0, `final_dataset.csv`) which pools per-target positives AND tested negatives. From it, only **FGFR2, EGFR, IL-7Ra, Mdm2, InsulinR, PD-L1** clear ≥10 pos with real negatives. **Nipah** (Adaptyv, 111 pos) is the biggest pos count of all but its license is unclear for commercial use. That's it. Six clean + one license-blocked = your entire test universe.

---

## Master table — 50 distinct named targets

Sorted Tier A → B → C → D. "pos/neg/designs" are best-available counts; "unknown" = no per-target count found. Download column gives the fastest path to the data.

| # | Target | PDB / UniProt | Tier | ~designs | ~pos | ~neg | Source (best single) | Download | comm_ok |
|---|--------|---------------|------|----------|------|------|----------------------|----------|---------|
| 1 | **FGFR2** | 1DJS / P21802 | A | 2123 | 193 | 1930 | Overath 2025 (Cao design) | zenodo.org/records/15722219 | yes |
| 2 | **EGFR (ECD)** | 1MOX / P00533 | A | 434 + 400 | 28 + 53 | 406 + ~347 | Overath 2025 + Adaptyv R2 | zenodo 15722219; github.com/adaptyvbio/egfr_competition_2 | yes |
| 3 | **IL-7Rα** | 3DI3 / P16871 | A | 171 | 38 | 133 | Overath 2025 (Cao+Watson) | zenodo.org/records/15722219 | yes |
| 4 | **Mdm2** | 1YCR / Q00987 | A | 96 | 55 | 41 | Overath 2025 (Watson RFdiff) | zenodo.org/records/15722219 | yes |
| 5 | **Insulin receptor (InsR)** | 4OGA / P06213 | A | 117 | 20 | 97 | Overath 2025 (Cao) | zenodo.org/records/15722219 | yes |
| 6 | **PD-L1 (CD274)** | 5O45 / Q9NZQ7 | A | 95 | 12 | 83 | Overath 2025 (Watson) | zenodo.org/records/15722219 | yes |
| 7 | **Nipah virus glycoprotein G** | 2VSM / Q9IH62 | A | 1196 | 111 | ~1085 | Adaptyv (Jan 2026) | proteinbase.com/competitions/adaptyv-nipah-competition; github.com/gitter-lab/adaptyvbio-nipah | **unclear** |
| 8 | **TrkA (NTRK1)** | 2IFG / P04629 | B | 128 | 9 | 119 | Overath 2025 (Cao) | zenodo.org/records/15722219 | yes |
| 9 | **SARS-CoV-2 spike RBD** | 6M0J / P0DTC2 | B | 99 | 9 | 90 | Overath 2025 (Cao) | zenodo.org/records/15722219 | yes |
| 10 | **VirB8 (Brucella T4SS)** | 4O3V / Q2YIR8 | B | 99 | 9 | 90 | Overath 2025 (Cao) | zenodo.org/records/15722219 | yes |
| 11 | **IL-2Rα (CD25)** | — / P01589 | B | 66 | 6 | 60 | Overath 2025 (Bennett) | zenodo.org/records/15722219 | yes |
| 12 | **sntx (snake α-neurotoxin)** | 3FTx family / P60615-class | B | 49 | 7 | 42 | Overath 2025 (Vazquez-Torres) | zenodo.org/records/15722219 | yes |
| 13 | **LTK** | — / P29376 | B | 33 | 3 | 30 | Overath 2025 (Bennett) | zenodo.org/records/15722219 | yes |
| 14 | **IL-10Rα** | — / Q13651 | B | 22 | 2 | 20 | Overath 2025 (Bennett) | zenodo.org/records/15722219 | yes |
| 15 | **pMHC SILSY** | HLA 3-chain | B | 96 | 2 | 94 | Overath 2025 | zenodo.org/records/15722219 | yes |
| 16 | **pMHC NY-ESO-1** | HLA-A*02:01 / SLLMWITQC | B | 41 | 1 | 40 | Overath 2025 | zenodo.org/records/15722219 | yes |
| 17 | **PDGFR (PDGFRB)** | 3MJG / P09619 | B | unknown | ≥1 | unknown | Cao 2022 / BoltzGen | files.ipd.uw.edu/pub/2021-minibinders/ | yes |
| 18 | **Influenza H3 HA** | 3ZTJ / HA-H3 | B | unknown | unknown | unknown | Cao 2022 | files.ipd.uw.edu/pub/2021-minibinders/ | unclear |
| 19 | **Influenza H1 HA** | 5VLI / HA-H1 | B | ~95 | unknown | yes | Watson 2023 (RFdiff) / Bennett | RFdiffusion Zenodo; nature.com s41467-023-38328-5 SI | yes |
| 20 | **TGF-β1** | 3KFD / P01137 | B | unknown | unknown | unknown | Cao 2022 | files.ipd.uw.edu/pub/2021-minibinders/ | unclear |
| 21 | **IGF1R** | 5U8R / P08069 | B | unknown | unknown | yes (Cao neg) | Cao 2022 | files.ipd.uw.edu/pub/2021-minibinders/ | unclear |
| 22 | **CD3δ** | 1XIW / P04234 | B | unknown | unknown | yes (Cao neg) | Cao 2022 | files.ipd.uw.edu/pub/2021-minibinders/ | unclear |
| 23 | **Tie2 (TEK)** | 2GY7 / Q02763 | B | unknown | unknown | yes (Cao neg) | Cao 2022 | files.ipd.uw.edu/pub/2021-minibinders/ | unclear |
| 24 | **IDI2** (novel) | — / Q9BXS1 | B | ~15 | ≥1 (9.8nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 25 | **PHYH** (novel) | — / O14832 | B | ~15 | ≥1 (7.8nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 26 | **HNMT** (novel) | — / P50135 | B | ~15 | ≥1 (99nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 27 | **ORM2** (novel) | — / P19652 | B | ~15 | ≥1 (22nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 28 | **GM2A** (novel) | — / P17900 | B | ~15 | ≥1 (270nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 29 | **PMVK** (novel) | — / Q15126 | B | ~15 | ≥1 (23nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 30 | **RFK** (novel) | — / Q969G6 | B | ~15 | ≥1 (8.8nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 31 | **MZB1** (novel) | — / Q8WU39 | B | ~15 | ≥1 (12nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 32 | **AMBP** (novel) | — / P02760 | B | ~15 | ≥1 (26nM) | unknown | BoltzGen 2025 | github.com/HannesStark/boltzgen | yes |
| 33 | **RagA:RagC dimer** | Q7L523:Q9HB90 | B | 24 | 14 | 10 | BoltzGen (cyclic peptide) | github.com/HannesStark/boltzgen | yes |
| 34 | **RagC GTPase** | — / Q9HB90 | B | 29 | 7 | 22 | BoltzGen (linear peptide) | github.com/HannesStark/boltzgen | yes |
| 35 | **GyrA (DNA gyrase A)** | — / P0AES4 | B | 1808 | 352 (func) | ~1456 | BoltzGen (AMP screen) | github.com/HannesStark/boltzgen | yes |
| 36 | **TNFα** | 1TNF / P01375 | B | unknown | ≥1 | some | BoltzGen benchmark | github.com/HannesStark/boltzgen | yes |
| 37 | **NPM1-c (disordered)** | — / P06748 | B | 5 | 1 | 4 | BoltzGen (IDR) | github.com/HannesStark/boltzgen | yes |
| 38 | **Penguinpox cGAMP PDE** | novel viral | B | 7 | 1 | 6 | BoltzGen (nanobody) | github.com/HannesStark/boltzgen | yes |
| 39 | **CD45 (PTPRC)** | — / P08575 | B | ~11–16 | 4 | unknown | BindCraft 2025 | nature.com s41586-025-09429-6 SI; github.com/martinpacesa/BindCraft | yes |
| 40 | **SpCas9** | 4OO8 / Q99ZW2 | B | 6 | 6 | 0 | BindCraft 2025 | nature.com s41586-025-09429-6 SI | yes |
| 41 | **PD-1 (PDCD1)** | 4ZQK / Q15116 | B | 53 | unknown | unknown | BindCraft 2025 | nature.com s41586-025-09429-6 SI | yes |
| 42 | **IFNAR2** | — / P48551 | B | 20 | 3 | 17 | BindCraft 2025 | nature.com s41586-025-09429-6 SI | yes |
| 43 | **HER2 (ERBB2)** | — / P04626 | B | 10 | 1 | 9 | BindCraft 2025 | nature.com s41586-025-09429-6 SI | yes |
| 44 | **Barnase / Barstar** | 1BRS | C | N/A | unknown | unknown (some abolish-binding) | SKEMPI 2.0 | life.bsc.es/pid/skempi2 | yes |
| 45 | **TEM-1 β-lactamase / BLIP** | 1JTG | C | N/A | unknown | unknown | SKEMPI 2.0 | life.bsc.es/pid/skempi2 | yes |
| 46 | **hGH / GH receptor** | 1A22 / 3HHR | C | N/A | unknown (Ala-scan) | unknown | SKEMPI 2.0 | life.bsc.es/pid/skempi2 | yes |
| 47 | **TCR / peptide-MHC** | 1AO7, 3QIB | C | N/A | unknown | unknown | PPB-Affinity 2024 | zenodo.org/records/13054646; huggingface proteinea/ppb_affinity | unclear |
| 48 | **Hen lysozyme / Ab (D1.3, HyHEL)** | 1VFB / 3HFM / 2I25 | D | N/A | unknown (>20 ddG) | unknown | SKEMPI 2.0 | life.bsc.es/pid/skempi2 | yes |
| 49 | **VEGF-A / anti-VEGF Fab** | 1BJ1 | D | N/A | unknown | unknown | Affinity Benchmark v2 | github.com/haddocking/binding-affinity-benchmark | yes |
| 50 | **PPB-Affinity bulk pool** | ~thousands of PDBs | C | N/A | ~12,052 labeled | unknown | PPB-Affinity 2024 | zenodo.org/records/13054646 | unclear |

> Tier-C single-system slots (44–47, 49) each stand in for a *family* in SKEMPI/Affinity-Benchmark; #50 is the bulk pool covering the rest (RNase A/RI, AChE/fasciculin, Ran/importin, ACE2/RBD-natural, colicin/Im, trypsin/inhibitor, OMTKY3, Ras/RasGAP, Cdc42, EphB4/ephrin, CD2/CD58, cyclophilin/capsid, C3d/CR2, TTR/RBP, actin family, α-amylase/tendamistat, etc.). These are not enumerated as separate rows to avoid padding the count with ~25 near-identical transfer entries — they all arrive in one download.

---

## Dedup / merge log (every merge made)

The four sources massively overlap. Here is exactly what got collapsed:

1. **Cao 2022 ↔ Bennett 2023 ↔ Overath 2025 ↔ ProtDBench** — these reuse the SAME 12 Cao target structures. Bennett "new ordered campaigns" (IL-7Ra, InsR, PD-L1, TrkA, HA) are re-runs against Cao targets, NOT new targets. **Merged to one row each**, attributed to **Overath 2025** wherever Overath has clean per-target pos/neg counts (it pools everything and is CC-BY). Affected: FGFR2, EGFR, IL-7Ra, InsR, PD-L1, TrkA, SARS-CoV-2 RBD, VirB8, PDGFR, TGF-β, IGF1R, CD3δ, Tie2, H3 HA.
2. **SARS-CoV-2 RBD** — Cao2020 Science (clean IPD download) + Cao2022 + Overath + ProtDBench all describe the same antigen. **One row**, attributed to Overath (has tested neg); Cao2020 download noted as the clean positive anchor but the RBD positive set is thin (9 in Overath), so demoted A→B.
3. **PD-L1 / IL-7Ra / InsR / PDGFR / TNFα** appeared as both "BoltzGen 5-target benchmark" and Cao/BindCraft/Overath targets. **One row each.** The fabricated "BoltzGen 11-target @4µM fill-to-1000" benchmark was DROPPED entirely (confirmed hallucinated in the 2nd source's adversarial pass). TNFα kept only as its real BoltzGen-benchmark B-tier row.
4. **Influenza HA** — three distinct subtypes/sources existed: Cao H3 (3ZTJ, #18), Watson/Bennett H1 (5VLI, #19). **Kept as 2 rows** (genuinely different subtypes + design sets). The "H3 BoltzGen benchmark" framing was dropped as fabricated.
5. **BindCraft duplicates** — PD-L1 (BindCraft 11/13) merged into the Overath PD-L1 row. CbAgo, Sas6, allergens (Der f 21, Bet v 1, Der f 7, BBF-14), CLDN1, NPM1, melittin/indolicidin/protegrin — these are thin/unverified BindCraft or BoltzGen peptide rows. **To avoid 50-padding with 1-positive allergen stubs, only the BindCraft rows with verified tested negatives were kept** (CD45, SpCas9, PD-1, IFNAR2, HER2). The allergen quartet + CbAgo + Sas6 + CLDN1 were dropped as redundant thin train-only stubs already represented by stronger B-tier negatives.
6. **BoltzGen 9 novel targets** — the 2nd source named only 4; the 4th source correctly enumerated all 9 (PHYH, HNMT, IDI2, MZB1, PMVK, RFK, AMBP, ORM2, GM2A). **All 9 listed** (#24–32) since they're real, named, MIT-licensed, and add genuine low-PDB-similarity diversity.
7. **Peptide/small-mol targets** (melittin, indolicidin, protegrin, rucaparib) — off-distribution (peptide-vs-peptide, small molecule). **Folded into the Tier-C narrative / dropped** rather than given rows; rucaparib is not even a protein. Not counted toward the 50 except via the bulk pool.
8. **SKEMPI 2.0 ⊂ PPB-Affinity; Affinity Benchmark v2 ⊂ PPB-Affinity** — PPB-Affinity subsumes both. **Kept a few flagship SKEMPI single-systems as named rows** (Barnase/Barstar, TEM-1/BLIP, hGH/GHR — the canonical mutational-scan systems) plus one Affinity-Benchmark Fab (VEGF), plus the TCR-pMHC subgroup, plus the bulk pool row. The ~25 other natural complexes (RNase/RI, AChE/fasciculin, Ran/importin, colicins, OMTKY3, Ras/RasGAP, etc.) were **collapsed into the #50 bulk-pool row** to avoid padding.
9. **RBX1 (2LGV)** — GEM×Adaptyv ICLR 2026 competition, NO public labels yet. **Dropped from the 50** (placeholder Tier-D future). Watch proteinbase / gembio.ai.
10. **BHRF1, VEGF-A, IL-17A (ProtDBench in-silico)** and **BenchBB targets (BHRF1, SpCas9, MBP, BBF-14)** — ProtDBench rows are in-silico-only (no experimental pos/neg); BenchBB raw labels are behind a paid assay service (not downloadable). **Dropped or merged** (SpCas9 kept via BindCraft which has real labels; BHRF1 dropped as in-silico/paywalled).

---

## If you want to TEST (LOTO) — the Tier A shortlist

These are your **only** held-out-target candidates. The honest count is **6 clean + 1 license-blocked = 7**.

| Target | pos | neg | Why it qualifies | Caveat |
|--------|-----|-----|------------------|--------|
| **FGFR2** | 193 | 1930 | Biggest clean pool, perfect for LOTO | none — best target |
| **Mdm2** | 55 | 41 | Best class balance | smallest design count |
| **IL-7Rα** | 38 | 133 | Abundant pos + neg | none |
| **EGFR** | 28+53 | 406+~347 | Pooled Overath + Adaptyv R2 | two sources to merge |
| **InsR** | 20 | 97 | Clears ≥10 | thinner positives |
| **PD-L1** | 12 | 83 | Just clears ≥10 | thinnest A-tier pos set |
| **Nipah G** | 111 | ~1085 | Largest pos count of ALL | **license unclear — do NOT use commercially until cleared** |

**Brutal honesty:** with only 6 commercially-clean Tier A targets, a leave-one-target-out evaluation has just **6 folds**. That is statistically thin — one weird target swings your whole AUC. Treat LOTO results as directional, not definitive, and report per-fold scores, never just the mean. If you can clear Nipah's license, 7 folds + its huge n materially strengthens the test.

---

## Pull order — most distinct targets per download

Do these in order. Three downloads get you 90% of everything.

1. **Overath 2025** — `zenodo.org/records/15722219` (`final_dataset.csv`, 82 MB, CC-BY-4.0). **→ 16 distinct targets in one file**, including 6 of 7 Tier A, with per-binder TRUE/FALSE labels already pooled. This is the single highest-value pull. Do it first.
2. **BoltzGen** — `github.com/HannesStark/boltzgen` (MIT; verify exact org path, may be `jclinic-mit/boltzgen`). **→ ~15 distinct targets** (9 novel proteins + Rag peptides + GyrA + TNFα + NPM1 + penguinpox). All MIT, fully open.
3. **PPB-Affinity** — `zenodo.org/records/13054646` + HuggingFace `proteinea/ppb_affinity`. **→ entire Tier C transfer pool in one shot** (subsumes SKEMPI + Affinity Benchmark). Check license before commercial use.
4. **BindCraft SI** — `nature.com/articles/s41586-025-09429-6` SI CSV + `github.com/martinpacesa/BindCraft` (MIT). **→ CD45, SpCas9, PD-1, IFNAR2, HER2** (5 targets with tested negatives).
5. **Adaptyv EGFR R1/R2** — `github.com/adaptyvbio/egfr_competition_2` (ODbL, attribution, commercial OK). **→ boosts EGFR** to 53 extra pos.
6. **Adaptyv Nipah** — `proteinbase.com/competitions/adaptyv-nipah-competition` + mirror `github.com/gitter-lab/adaptyvbio-nipah`. **→ Nipah G** (111 pos) — but clear the license first.
7. **Cao 2022 / IPD minibinders** — `files.ipd.uw.edu/pub/2021-minibinders/` — only needed for the FACS/SSM raw data on PDGFR/TGF-β/IGF1R/CD3δ/Tie2 if Overath's pooled counts aren't enough. Lowest priority (counts un-tabulated).

After pulls 1–4 you have **~38 distinct named targets** on disk with labels. Pulls 5–7 add the remaining Tier A boost and the un-tabulated Cao tail.

---

## Did we reach 50? — yes, but read the fine print

**Real distinct total = 50.** But the composition is the honest story:

- **Only 7 are Tier A**, and **only 6 are commercially clean** (Nipah is license-blocked).
- **24 are Tier B** — thin de-novo, train-pool only. Many BoltzGen novel-target rows (#24–32) have just ≥1 positive and *unknown* negatives, so they're weak even for training.
- **16 Tier C + 3 Tier D** = 19 of the 50 are off-distribution natural-affinity / antibody padding. We hit 50 *because* of them. Strip the transfer/antibody padding and the genuine de-novo binder universe is **31 targets, 7 of them test-grade.**

**To get more REAL Tier A** (the only number that matters for a clean test), padding won't help — you'd need to **generate your own labeled data**: run a binder campaign (BindCraft/BoltzGen) against 3–5 fresh targets, order ~50–100 designs each on Adaptyv/BenchBB, and get binary BLI/SPR readouts. That's the only path from 6 clean test targets to ~12, which is what a credible LOTO benchmark actually needs.