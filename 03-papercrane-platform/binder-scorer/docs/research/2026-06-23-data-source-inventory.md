# Paper Crane — Data Source Inventory & Totals

> Historical acquisition notes, 23 June 2026. The permission labels below are unverified planning assessments, not a grant or publication clearance. In particular, code licenses do not determine dataset rights; ODbL/ODC-BY attribution and share-alike terms must be checked for the exact data version; and “validation-only” does not itself authorize redistribution. The current [file-level source and terms map](../../../THIRD_PARTY/DATA-PROVENANCE.md) supersedes these broad permission summaries.

## 1. Headline totals (bottom line up front)

Counts are the realistic *usable* sequence-label pairs (tested designs with a recoverable sequence + target + outcome), not raw repository sizes. Ranges reflect genuine uncertainty in the survey.

### (a) GOLD — on-distribution de-novo binders, real tested negatives, commercial-OK
| Metric | Range |
|---|---|
| Usable sequences | **~15,500 – 16,500** |
| Distinct targets | **~5 – 8** (after dedup) |

Composition: Bits-to-Binders CD20 (~12,000), Nipah NiV-G (~1,196), EGFR R1+R2 combined (~601), Cao 2022 yeast-display subsample (hundreds–low-thousands of *clean* per-design labels, target-subsampled), Bennett/Coventry 2023 retrospective (hundreds), plus the Proteinbase-hosted competition targets. The big caveat: **of these, only Cao 2022 + Bennett 2023 carry MULTIPLE distinct targets** — every Adaptyv/BioML set is single-target. So GOLD sequence count is dominated by 3 single-target deep wells (CD20, Nipah, EGFR) plus the two multi-target IPD screens.

### (b) USEFUL / AUXILIARY — real labels, but off-distribution or license-caveated
| Metric | Range |
|---|---|
| Usable sequences/entries | **~20,000 – 30,000+** (PPB-Affinity ~12k, SKEMPI ~7k, RBX1 ~321, BindCraft ~212, BoltzGen hundreds, Cao 2020 RBD, ProtDBench/Cao-labeled set, affinity benchmarks ~180–207) |
| Distinct targets/complexes | **hundreds** (mostly 1 measurement each — NOT well-powered) |

These are continuous-affinity natural-PPI or single-value complexes. They transfer-pretrain a binding-strength head; they do **not** supply per-target hit/miss power.

### (c) ANTIBODY — separate population world
| Metric | Range |
|---|---|
| Usable sequences/entries | **~400,000 – 500,000+** (AlphaSeq ~71k–105k, AbAgym ~335k incl. ~37k interface, CoV-AbDab ~13k, FLAb binding slice, AB-Bind ~1.1k) |
| Distinct antigens | **dozens – low hundreds** |

Large but mostly **license-blocked or off-distribution**: AlphaSeq is CC-BY-NC (no commercial), AbAgym + AB-Bind are academic-only/no-license, SAbDab/Thera-SAbDab have no negatives. Validation-only or transfer signal — not training rows for a shippable model.

### THE GATING NUMBER — well-powered targets (≥10 pos AND ≥10 neg)
- **Commercial-clean, on-distribution: ~4 confirmed + ~5–10 conditional = realistic ~8–14.**
  - **Confirmed single-target (4):** CD20, Nipah NiV-G, EGFR (combined), and ~1 from Cao 2020 RBD scope.
  - **Conditional, multi-target (the swing factor):** Cao 2022 (~8–11 sites *if* per-design clean labels parse out of pooled NGS) + Bennett 2023 (~5–8 after dedup vs Cao). These two are the ONLY path to real target diversity, and their well-powered counts are **estimated, not verified** (positive counts vary by site; some sites are positive-thin).
- **Honest verdict:** the thesis needs ~15–30 diverse well-powered targets. We can confidently stand up **~4–6 today**; reaching **~12–18** depends entirely on whether Cao 2022 + Bennett 2023 yield clean per-target hit/miss tables after supplementary parsing. **That parse is the load-bearing risk for the entire program.**

---

## 2. Ranked acquisition table (GOLD first)

| Dataset | ~Sequences | ~Targets | Negatives? | Distribution | Commercial OK | Backfill | Verdict |
|---|---|---|---|---|---|---|---|
| Bits-to-Binders CD20 (BioML) | ~12,000 (707 pos) | 1 | yes (huge, ~11,277) | de-novo | **yes** (CC-BY+MIT)¹ | optional | **GOLD** |
| Adaptyv EGFR R2 | 402 (55 pos/325 neg) | 1 | yes | de-novo (+ab framework) | yes (ODbL share-alike) | minimal | **GOLD** |
| Adaptyv Nipah NiV-G | 1,196 (111 pos) | 1 | yes (~1,085) | de-novo | unclear (verify) | low | **GOLD** |
| Cao et al. 2022 (yeast-display) | ~810k tested* | 13 sites / 12 prot | yes (rich) | de-novo | yes (CC-BY) | **yes (heavy)** | **GOLD** |
| Bennett/Coventry 2023 | ~80k prosp + ~1M retro* | 4 + ~10 retro | yes | de-novo | yes (CC-BY) | partial | **GOLD** |
| Proteinbase aggregate hub | 2,500+ (⚠ overlaps below) | ~7–8 | yes (per-collection) | mixed | yes (ODC-BY) | low–mod | **GOLD** |
| Adaptyv EGFR (R1+R2 combined entry) | 601 char. | 1 | yes | mixed | yes (ODbL) | minimal | **GOLD** |
| Adaptyv EGFR R1 | 202 (8 pos) | 1 | partial | de-novo | yes (ODbL) | minimal | USEFUL |
| Adaptyv RBX1 / GEM-X | ~321 (9 pos ⚠<10) | 1 | yes (~312) | de-novo | unclear (verify) | low | USEFUL |
| BindCraft supp (Nature 2025) | 212 (65 pos) | 12–13 | partial | de-novo | unclear | moderate | USEFUL |
| BoltzGen (8 campaigns) | hundreds (~15/target) | 26 (excl. sm-mol) | partial | de-novo | yes (MIT code) | moderate | USEFUL |
| ProtDBench / Cao-labeled | thousands | 10 | yes (aggregate) | de-novo | unclear | low–mod | USEFUL |
| Cao et al. 2020 (SARS RBD) | thousands (105 hits) | 1 | yes | de-novo | yes (CC-BY) | yes | USEFUL |
| PPB-Affinity | 12,062 | 3,032 PDB | no (synth thr.) | mixed | yes* (drop PDBbind rows) | yes | USEFUL |
| SKEMPI 2.0 | 7,085 (440 abolish) | ~237 interactions | partial | natural-PPI | yes (CC-BY) | yes | AUXILIARY |
| CoV-AbDab | ~12,916 | multi CoV variants | partial/sparse | antibody | yes (CC-BY) | yes | USEFUL |
| AbAgym | ~335k (37k iface) | dozens | yes | antibody | **unclear (academic)** | mod–high | USEFUL |
| AlphaSeq | ~71k–105k | 1 | yes | antibody | **NO (CC-BY-NC-SA)** | yes | USEFUL |
| FLAb (binding slice) | 132 datasets | many | partial | antibody | yes* (per-study) | high | AUXILIARY |
| AB-Bind | 1,101 | 32 cmplx | partial | antibody | **unclear (no license)** | yes | AUXILIARY |
| Affinity Benchmark v2 / v5.5 | ~179 / ~176–207 | ~179 / ~207 | no | natural-PPI | yes (Apache-2.0) | yes | AUXILIARY |
| SAbDab | ~18,744 Fv | hundreds | no | antibody | yes (CC-BY) | yes | AUXILIARY |
| "Beyond Structure & Affinity" | re-analysis only | 2 (CD20,EGFR) | inherits | de-novo | unclear | n/a | AUXILIARY |
| PDBbind PP subset v2020 | ~2,071 | unknown | no | natural-PPI | **unclear/restrictive** | yes | SKIP |
| Thera-SAbDab | ~461–1k | many | no | antibody | yes | yes | SKIP |
| BindingDB PPI slice | tiny | tiny | no | natural-PPI | yes (CC-BY 3.0) | high | SKIP |
| BioLiP2 / IntAct / STRING | M-scale | many | no | natural-PPI | yes | n/a | SKIP |
| AbDev (Ginkgo) | 326 | n/a | n/a (developability) | antibody | unclear | n/a | SKIP |
| Protein Design Archive | 1,500+ | n/a | no | de-novo | unclear | n/a | SKIP |
| Paper Crane internal campaigns | hundreds | several | **no wet-lab label** | de-novo | yes (owned) | n/a | SKIP |

*\*Tested-sequence count, not clean per-design label count. ¹CD20 label = CAR-T functional enrichment, not pure SPR/BLI.*

---

## 3. Recommended acquisition order (fastest path to leave-one-target-out)

**Tier 1 — quick wins, pull this week (all direct download, minimal backfill):**
1. **Adaptyv EGFR R2 + R1** — `github.com/adaptyvbio/egfr_competition_2` & `_1`. 1 clean well-powered target, ships metrics, trivial compute.
2. **Bits-to-Binders CD20** — GitHub `kosonocky/bits-to-binders` CSVs (Zenodo 18840101 for full). 1 massive-power target, CC-BY clean.
3. **Adaptyv Nipah NiV-G** — Proteinbase / gitter-lab mirror. 1 well-powered target (verify license).
4. **Proteinbase bulk CSV** — one download yields RBX1, TREM2, IL-7Ra, MDM2, IFNAR2 etc. **But dedupe vs the Adaptyv repos (see §5).**

These 4 pulls give **~3–4 well-powered targets** in days — enough for a first within-target calibration, **not** enough for leave-one-target-out.

**Tier 2 — the diversity unlock, slow but essential (start in parallel):**
5. **Cao et al. 2022** — IPD repo + supplementary. **This is the single highest-leverage acquisition for the thesis** because it is the only source of ~8–11 well-powered *distinct* targets. Budget real effort to parse pooled NGS/SSM into clean per-design (seq→bind/not) tables; sub-sample to well-powered sites first.
6. **Bennett/Coventry 2023** — `files.ipd.uw.edu/pub/improving_dl_binders_2023/`. Adds ~5–8 targets AND a baseline AF2 interface score for calibration. **Dedupe against Cao 2022 before counting targets.**

Tier 2 is what moves you from ~4 to ~12–18 well-powered targets and makes LOTO actually meaningful.

**Tier 3 — transfer/pretrain head + eval (anytime):** PPB-Affinity (drop PDBbind rows) and SKEMPI for a binding-strength pretraining head; Affinity Benchmark v5.5 (Apache-2.0) as a clean held-out affinity eval.

**Slowest / lowest yield:** AbAgym/AlphaSeq parsing, BoltzGen supplement extraction, ProtDBench per-target verification.

---

## 4. License watch-outs (cannot train a shippable commercial model on these)

| Dataset | Status | Action |
|---|---|---|
| **AlphaSeq** | **FORBIDDEN** — CC-BY-NC-SA 4.0, explicit NonCommercial | Validation only, or license from MIT-LL/A-Alpha Bio |
| **AbAgym** | **Unclear → treat as no** — "academic use" + 67 per-study licenses | Don't train until cleared |
| **AB-Bind** | **Unclear → treat as no** — repo has NO license = all-rights-reserved | Author permission needed |
| **PDBbind PP v2020** | **Restrictive** — no redistribution, post-2020 paywalled | SKIP; segregate any PPB-Affinity rows sourced from it |
| **Nipah / RBX1 / ProtDBench / BindCraft** | **Unclear license string** | Verify exact CC/ODbL before commercial training; treat as validation-only until confirmed |
| **Adaptyv EGFR (all rounds)** | **OK but copyleft** — ODbL share-alike on derived *databases* | Model weights likely fine; legal review on any redistributed derived data |
| **FLAb** | OK aggregate (CC-BY) **but per-study upstream licenses vary** | Filter component studies before commercial use |
| **PPB-Affinity** | CC-BY wrapper **but ingests PDBbind rows** | Drop/segregate PDBbind-derived rows |

Clean-for-commercial-training: CD20 (CC-BY+MIT), Cao 2022, Bennett 2023, Cao 2020 (all CC-BY), SKEMPI (CC-BY), Affinity Benchmark v2/v5.5 (Apache-2.0), Proteinbase aggregate (ODC-BY), SAbDab/CoV-AbDab (CC-BY).

---

## 5. Honest gaps, double-counting, and the ceiling

**Double-counting — explicit warnings:**
- **Proteinbase aggregates the Adaptyv competitions.** EGFR (R1+R2), Nipah, RBX1, TREM2 appear BOTH as standalone entries AND inside Proteinbase's "2,500+". **Count each target once.** Pull from one source per target and dedupe by sequence.
- **EGFR R1+R2 = 601 combined characterized, NOT additive.** R2's 400 + R1's 202 overlap; "601" is the combined count. Don't sum to 802.
- **Bennett 2023 retrospective REUSES Cao 2022 targets** (IL-7Ra, TrkA, FGFR2, InsulinR, PDGFR). Dedupe before counting distinct well-powered targets — otherwise the ~12–18 estimate inflates toward double.
- **PPB-Affinity subsumes SKEMPI, SAbDab, PDBbind, Affinity Benchmark, ATLAS.** Using PPB-Affinity AND its components double-counts. Pick one.
- **"Beyond Structure & Affinity" re-analyzes CD20 + EGFR** — it's a feature recipe, zero new labels.

**Thin spots:**
- **Tested negatives on-distribution exist for only ~5–8 distinct commercial-clean targets.** This is the real scarcity — not sequence count.
- **Multi-target diversity hinges on two academic IPD screens** whose clean per-design label extraction is unverified. If that parse fails, we're stuck at ~4–6 single-target wells and cannot do a credible leave-one-target-out.
- **Most "well-powered" claims are positive-limited.** Negatives are abundant everywhere; ≥10 *positives* per target is the binding constraint (RBX1=9, EGFR-R1=8, BindCraft per-target mostly <10, BoltzGen ~15/target total).
- **Label heterogeneity:** CD20 = CAR-T functional enrichment; Adaptyv = BLI Kd; Cao = FACS/SC50. Mixing these without a per-assay correction will inject noise into a unified scorer.

**Realistic ceiling:**
- **Commercial-clean, on-distribution sequences:** ~15k–16k (CD20 dominates; remove it and it's only ~3k–4k).
- **Commercial-clean, on-distribution well-powered targets:** **~8–14 best case, ~4–6 confirmed-today.** This is below the ~15–30 the LOTO thesis wants.
- **Bridging the gap** requires either (a) successfully parsing Cao 2022 + Bennett 2023 into clean per-target tables, or (b) **generating our own wet-lab labels** — Paper Crane's internal campaigns become the highest-value future dataset the moment they're tested, since they'd be on-distribution, our-own-metrics, and hit/miss. Until then, antibody/affinity data can pretrain and validate but cannot substitute for de-novo per-target power.