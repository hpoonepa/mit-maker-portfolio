# Research Evaluation — Is the LLM-Per-Target Prior Good Research / Nature-Publishable? (2026-06-29)

> Source: 13-agent dynamic workflow (`wf_8a3f2b0a-1a8`) — 6 assessment dimensions
> (rigor, novelty/prior-art, publishability, improvements, framing, data-needs), each
> with its load-bearing claim adversarially verified against live literature + the repo,
> then synthesized. Evaluates the v1/v2 benchmark in `2026-06-28-llm-benchmark-result.md`.

## TL;DR

The leakage discipline is **real and above field median**, but the headline statistics are
**broken** and the central thesis is **not yet identified**. Neither v1's "powered loss" nor
v2's "genuine tie" is statistically supported at n=11. It is **not Nature**; the realistic
ceiling (with powered results + a small prospective wet-lab A/B) is **Nature Communications /
Nature Methods**, with **MLSB / Bioinformatics** the honest near-term home. The one thing
publishable today is the **Simpson's-paradox ipSAE-deflation finding** — after the selection
mechanism is modeled.

---

## 1. Is it good research? — Mixed: rigorous engineering, not yet a finding

**What's genuinely strong (keep):**
- True GroupKFold-by-target LOTO (`scorer/loto_split.py:39-52`) — all of target T in test, rest in train.
- Leave-this-target-out empirical power table (`llm_prior.main:469`) — T's labels never enter its own prompt.
- Train-only z-scoring in the scorer (`scorer/baselines.py:360-371`); explicit `experimental__*`
  leakage assertion (`pc_contracts/leakage.assert_no_leakage`) with a passing exclusion test.
- Honesty is **mostly real, not performative**: git history shows the power/MDE module (d66ed08,
  2026-06-26) was committed **before** the results docs (2026-06-28) — "pre-registered" is literally
  true. Docs admit the v1 loss, the dilution root-cause, n=11 weakness, un-run controls, Nipah refusal.

### THE CRITICAL BUG — the MDE is mis-derived (verified, not refuted)

`scorer/power_analysis.py:16` hardcodes `sigma_assumed=0.0414`, with a docstring admitting it was
"calibrated so that at n=11 the MDE equals the pre-registered value of 0.035" — **circular**. Worse,
it plugs an **SE-scale** quantity into the slot where the formula `MDE = (z_α+z_β)·σ/√n` requires the
**per-fold delta SD**. The real per-fold ΔP@k SD is **~0.14–0.175** (recoverable from the study's own
BCa CIs as `SD = SE·√11`). Correctly computed:

> **True MDE ≈ 0.11–0.15, not 0.035.**

**Consequence:** every delta in the study falls in the *underpowered / UNTESTED* zone.
- v1's −0.058 is **not** a "powered loss" — it's untested.
- v2's −0.014 / +0.005 / +0.006 are **not** a "genuine tie" — also untested.
- At n=11 **nothing is statistically resolved.** Until this is fixed, no downstream verdict is interpretable.

### Two more rigor problems

- **The literature's contribution is unidentified.** The v2 LLM is *fed* the leakage-safe within-target
  AUC table, so its winning behavior (ordering actifptm/interface_residues correctly) is plausibly
  downstream of **that table, not the literature**. The ablation separating them was never run.
- **The "beats tools with NO literature access" framing is rigged** on three counts: (a) B5 already
  ingests literature/structure-derived target features (`epitope_hydrophobicity`, `interface_class`,
  `druggability`); (b) B0 — the metric most worth beating — is **never actually beaten** (v2 = −0.014
  vs B0); (c) the comparison is underpowered to detect anything below ~0.12.

### Secondary concerns
- **MNAR / range-restriction collider:** the "negatives" are designs that passed an upstream
  computational filter (typically ipSAE/iptm) before being ordered + tested. Conditioning on high
  ipSAE collapses its within-target variance, mechanically depressing its AUC (0.605–0.72). So the
  "actifptm beats ipSAE within-target" finding is **partly a selection artifact**, not pure biology —
  the repo reframes the pooled 0.806 as Simpson-inflated but never models the selection mechanism.
- **Forced zero-delta folds bias toward "tie":** `b_llm_prior` falls back to B0 when no prior exists
  (NIPAH safety-refusal), contributing Δ=0 by construction and shrinking |mean Δ| and the CI toward 0.
- **Arbitrary three-zone thresholds:** `real_product` requires wins ≥ n−1 (10/11), `fall_back` uses
  wins ≤ n//2−1 — no power justification.

---

## 2. Could it be published in Nature? — No.

A per-target metric-reweighting reranker bolted on top of existing AF/Boltz confidence scores is
**incremental method tooling** by Nature's own framing — not a design paradigm or validated biology.
The field's flagship ranking-metric work (ipSAE, the Adaptyv competition, the Overath ~3,766-binder
meta-analysis) lives on **bioRxiv or in specialist venues**, not Nature.

### Realistic venue ladder

| Venue | What it requires |
|---|---|
| **MLSB / MLCB workshop** | Honest home *today* — tolerates n=11 + leakage-safe LOTO design + fresh framing |
| **Bioinformatics / NAR note** | The **Simpson's-paradox ipSAE-deflation finding alone** — no wet-lab. **First model the selection mechanism** or a reviewer dismisses it as a range-restriction collider |
| **Bioinformatics / PLOS Comp Bio** | A *powered* retrospective win + memorization + literature ablations across ~20–35 targets |
| **Nature Comms / Nature Methods / NMI** | All of the above **+ a small prospective wet-lab A/B** (LLM-rank top-20 vs ipSAE-rank top-20, disjoint, SPR/BLI hit rate). ~$60–120K, one wet-lab quarter, 2–3 targets |

To even approach the **Nature family**, you'd need ALL of: (1) the power calc fixed and re-stated;
(2) ~25–50 diverse, balanced targets (not 11, not 67% Nipah); (3) a **powered win** over B0 (correct
MDE, paired BCa CI excluding 0) — not just the LightGBMs, which collapse to global on novel targets;
(4) a literature-ablation isolating literature from the AUC table; (5) the un-run memorization /
name-anonymization control; (6) ideally a prospective wet-lab A/B. Even clearing all six tops out at
**Nature Methods / NMI / NAR**, not Nature/Cell/Science.

---

## 3. Novelty

The signed, per-target, literature-informed prior framing is **novel-ish** but adjacent to a crowded
prior-art neighborhood: LLM-as-judge/reranker in science; structural model-quality-assessment models
(EnQA, DProQA, GATE); learned ensembles of AF/Boltz confidence metrics; target-conditioned metric
weighting. It is closer to a **fresh wrapper on known ideas** than a new primitive — defensible at a
workshop, not as a standalone Nature-level conceptual advance.

---

## 4. The honest version of the claim

> "At ~11 targets, a literature-anchored per-target LLM prior performs **on par with — does not beat —**
> strong baselines (including B5, a LightGBM itself given literature-derived target features) on LOTO
> Precision@k. The study is **underpowered**: true MDE ≈ 0.11–0.15, not the registered 0.035, so neither
> v1's 'loss' nor v2's 'tie' is statistically resolved. Genuine per-target weight deviation is
> **expressible** (MDM2 aromatic/strand sign-flip; PD1 promoting interface_residues), but the
> literature's marginal value **over the empirical AUC table the LLM is fed is not yet identified**, and
> apparent per-target wins concentrate on EGFR/MDM2 — exactly the memorizable targets — with the
> memorization control never run."

---

## 5. Top improvements (ranked by ΔPrecision@k per unit effort)

1. **[low] Fix the MDE** — recompute from the real per-fold delta SD (~0.175 from the BCa CIs), not the
   reverse-engineered 0.0414. Re-issue every verdict. Reframes the project from "we tied" to "we can't
   yet tell" — honest, and makes the case for scale. *Gate on everything else.*
2. **[low] Literature-ablation** — LLM + AUC-table **without** literature vs **with**, same targets/folds.
   The load-bearing experiment. If the no-literature arm ties too, a plain empirical reweighter suffices
   and the literature thesis is dead; if literature adds powered lift, you finally have an identified claim.
3. **[low] Fold the ~3,800 already-labeled Overath/Proteinbase designs** (~$190 free Boltz credits, data
   on disk) → LOTO from 11 to ~25–35 targets, Nipah 67% → ~15%. Necessary (not sufficient) for power.
   Expect CIs to tighten around ~0 vs B0, **not** to flip the sign on its own.
4. **[low] Run the un-run memorization control (K5)** — name-anonymized targets (sequence/structure only,
   gene name stripped) + obscure-target holdout (MZB1/PMVK/VirB8). Wins cluster on EGFR/MDM2, which
   saturate Claude's corpus and public Adaptyv leaderboards. First objection any reviewer/YC partner raises.
5. **[medium] The real win — LLM-prior + out-of-fold data stack** (empirical-Bayes / shrink LightGBM
   coefficients toward the LLM's signed weights), evaluated **specifically against B0**. LLM-alone and
   data-alone both tie B0 and neither dominates — the textbook signature that a fit stack beats both. On
   novel targets the LightGBMs collapse to global while the LLM prior still differentiates. Fit out-of-fold
   it cannot do worse than `max(LLM, B6)`.
6. **[medium] Database-grounded epitope-contact features** (SAbDab / IEDB / PDBe-KB co-crystal contacts,
   **not** LLM-guessed residues — those invite a hallucination objection). Where the binder lands on the
   functional epitope is the one signal class B0/B5/B6 structurally cannot capture from global metrics —
   and the only place a genuine *literature* edge can come from.
7. **[medium] Model the MNAR / range-restriction selection mechanism** before publishing the ipSAE-deflation
   note — protects the single most publishable asset from a fatal collider objection.

---

## 6. Roadmap — from "untested tie" to a publishable win

1. **Fix the power calculation first.** Recompute MDE from the real per-fold delta SD; re-state every
   verdict — both v1 and v2 are currently "untested," not "loss"/"tie." Nothing downstream is
   interpretable until this is done.
2. **Expand the scoreboard** by folding the on-disk Overath/Proteinbase designs to ~25–35 targets,
   dropping Nipah dominance. Expect tighter CIs around a near-zero point estimate vs B0, not a sign flip.
3. **Run the two identifying controls** before claiming anything: (a) literature-ablation;
   (b) memorization / name-anonymization + obscure-target holdout.
4. **Beat the right baseline the right way:** LLM-prior + out-of-fold data stack aimed at B0, plus
   database-backed epitope-contact features.
5. **Protect and sharpen the one publishable finding:** model the selection mechanism behind the
   ipSAE-deflation result; turn the MDM2 sign-flip into a designed B6-global-null vs B6-with-LLM-signs
   contrast — that contrast *is* the mechanistic claim.
6. **Only if the retrospective win becomes powered** (correct MDE, BCa CI excluding 0, ~25+ balanced
   targets, controls passed): add a 2–3 target prospective wet-lab A/B to clear the Nature Comms / Methods bar.

---

## 7. Bottom line

The discipline is real and above field median, but the headline is broken: with a mis-derived MDE
(~0.11–0.15 actual vs the registered 0.035) at n=11, neither v1's "loss" nor v2's "tie" is resolved —
and the literature's contribution is unidentified because the LLM is handed an empirical AUC table that
may be doing the work, while the "baselines have no literature access" framing is rigged (B5 already
ingests literature-derived features; B0 is never beaten). It is **not Nature** — a metric-reweighting
reranker is incremental tooling. The realistic ceiling with powered results + a small prospective
wet-lab A/B is **Nature Communications / Methods**; **MLSB / Bioinformatics** is the honest near-term
home; the one finding publishable today is the **Simpson's-paradox ipSAE-deflation result** (guard the
selection-bias objection first). To convert the tie into a win, in order: **fix the power calc → fold
the already-labeled designs → run the literature + memorization ablations → stack the LLM prior with an
out-of-fold data corrector aimed at B0.**
