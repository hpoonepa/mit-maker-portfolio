# Paper Crane Meta-Scorer — Engineering Blueprint v1

> Synthesis note: where the 20 analyses disagreed, the conservative, data-grounded position won. The dominant correction across all 20: **Proteinbase is a public Adaptyv download, the headline `0.806` is a pooled Nipah-dominated number with no per-target counterpart, the trainable label∩feature set is ~1,052 designs / ~107 positives over ~12 weakly-powered targets, and the naive "combine all metrics" ensemble has ALREADY been run in-repo and LOST (0.541 pooled).** The blueprint below is built so the company ships something true on day one and earns the big claim later.

---

## 1. Thesis & the single success metric

**Decision.** The provable v1 thesis is narrow and honest: *a learned, leakage-controlled combiner of all tools' per-design metrics produces a calibrated P(bind) that beats the best single metric (min_ipSAE) on the SAME held-out designs, under Leave-One-Target-Out evaluation, measured by Precision@20 and PR-AUC.* Target-conditioning ("metric importance is a function of the target") is the **roadmap thesis**, explicitly gated on acquiring more labeled targets — not a v1 claim.

**Single success metric:** `ΔPrecision@20` (and secondarily `ΔPR-AUC`) of the meta-scorer over per-target-recomputed min_ipSAE, on Leave-One-Target-Out folds, with a paired bootstrap 95% CI whose lower bound > 0.

**Reasoning.** Every analysis converged on three facts: (a) ROC-AUC `0.806` is pooled and Simpson-inflated — it has no within-target value to beat, so "beat 0.806 target-by-target" is internally contradictory; (b) the product surfaces ~20 designs to wet-lab, so top-of-list precision under ~10% prevalence is the metric that matters, not ROC-AUC; (c) the comparison must be paired on identical held-out designs, never against the published pooled number from a different slice. Precision@20 is also what a customer feels.

---

## 2. Training data & labels (the founder's biggest worry — brutally honest)

**Decision.** Train on **Proteinbase** (public Adaptyv set) as the only dataset that has both real labels AND the model's input features. Use the **explicit experimental `binding` boolean** as the label, conditioned on expression. Treat everything else (benchmark v1.0, internal 5G51/RBX1/god-mode campaigns) as **unlabeled** until wet-lab results return. Accept that v1 is a small-N prototype.

**What real labels actually exist:**
- **Proteinbase** = `https://storage.proteinbase.com/proteinbase_all_data_28_01_2026.csv`. Raw schema is **6 columns**; all metrics + labels are nested in a JSON `evaluations` list (the flat `computational__*`/`experimental__*` schema is notebook *output*, not the file). First engineering task is a JSON-explode ETL — and that ETL is itself a leakage surface.
- **Real wet-lab signal:** an experimental `binding` boolean (~2,517 labeled: ~359 True / ~2,158 False), `binding_strength` (Strong/Medium/Weak/None), and `kd` (present on only 427 designs). These give genuine, uncensored **tested negatives** — the negative class is NOT scarce.
- This is a **third-party download.** Competitors can get it. It is not a moat (see §11). The published numbers were computed on data anyone can re-derive.

**The label landmines (be honest in any YC/benchmark material):**
1. **`is_binder = kd.notna()` is the WRONG label** — it undercounts (106 kd-present rows are actually `binding=False`; 38 binding=True rows have no kd) and conflates "tested, no measurable KD" with "never tested." Use the explicit `binding` boolean instead.
2. **Selection / MNAR bias:** designs got assayed partly *because* they scored well computationally. So min_ipSAE's apparent power is inflated by "was this good enough to send to the lab." Quantify it: compute AUC of `boltz2_min_ipsae` for predicting `was_tested` (assayed-or-not) — publish that number; it is a credibility multiplier.
3. **Expression confound:** `experimental__expressed` predicts the kd-label at AUC ~1.0; sequence-length/composition features rank as top "binding" predictors. Without conditioning on `expressed==True`, the scorer silently becomes an expressibility predictor. Label = **P(binds | expressed)**.
4. **Leakage columns to hard-exclude from features:** every `experimental__*` column (binding 0.96, expressed 1.00, expression-yield 0.92, kd/koff/kon). A unit test must FAIL if any `experimental__*` enters X.
5. **Circular labels — banned:** the benchmark v1.0 hit rule `ipSAE≥0.70 AND DockQ≥0.23 AND pTMEnergy≤-1.2` is a deterministic function of model inputs. Never train or evaluate the headline scorer against it. It is a tool-comparison artifact only.

**The true bottleneck is target count, not design count.** After joining labels to the boltz2 feature panel, the usable set is **~1,052 designs / ~107 positives / ~12 weakly-powered targets**, dominated by Nipah (~67%). Target-conditioning is statistically **unobservable** here (you need ≥2 well-powered targets with *different* metric importances to even demonstrate that importance varies). The single highest-leverage data action is not modeling — it is **re-running the tool stack on labeled-positive designs that currently lack the metric panel** (to lift ~107 positives toward several hundred) and **acquiring new diverse labeled targets**.

---

## 3. Target feature-vector (minimal v1 set)

**Decision.** Ship a **small, interpretable, structure-only** target vector. NO ESM2 embedding, NO LLM-extracted text features in v1 — at ~12 targets a high-dimensional target encoder memorizes target identity. Compute it once per distinct target (only ~24 structures — minutes of CPU).

**v1 target features (all computable from target PDB + chain + optional hotspots):**
- `log10(target_length)`, `disorder_fraction` (mean pLDDT<50 or IUPred3)
- DSSP secondary-structure fractions: `frac_helix`, `frac_strand`, `frac_loop` (global + epitope-local if hotspots given)
- Interface/epitope geometry: `epitope_planarity_rmsd` (SVD plane-fit CA RMSD over hotspot+10Å sphere), `epitope_pocket_volume` + `druggability` (`dynamics/pockets.py::detect_pockets`)
- `epitope_hydrophobicity`, `epitope_net_charge_pH7`, `frac_polar`, `n_hotspots`, `hotspot_mean_SASA`
- `fold_class` / Foldseek cluster id (categorical) — **NOTE: red-team flags this as target-ID leakage at ~12–24 structures; drop it for v1, keep continuous geometry only.**

**Reasoning.** These reproduce the difficulty rationale already encoded in the target YAMLs (shallow+polar ⇒ hard like IL-7Rα 0.18; hydrophobic core ⇒ easy like PD-L1 0.42) and let a tree's interaction terms deliver conditioning. Defer `ESM2-1280 PCA` and APBS/cryptic-pocket features behind a config flag `use_target_embedding=False`, enabled only when `n_distinct_labeled_targets ≥ ~30`. **Mandatory guard:** train a target-features-ONLY model under LOTO; if it scores >~0.6 AUC, the features encode target identity / base-rate, not transferable signal — shrink them.

**Fix the data bug:** `pd-l1.yaml class='cytokine_receptor'` is wrong (PD-L1 is an Ig-superfamily checkpoint ligand). Build a curated `competition → target PDB/UniProt` mapping table by hand; do NOT regex-derive the target key — a single mis-merge is silent LOTO leakage.

---

## 4. Design feature-vector & missing-tool handling

**Decision.** Use ONLY metrics verified present in Proteinbase, plus missing-indicators handled carefully. Missingness is structured as **~4 co-missing BLOCKS, not 12 independent tools.**

**Verified-present features (exact column names):**
`boltz2_min_ipsae, boltz2_ipsae, boltz2_iptm, boltz2_ptm, boltz2_plddt, boltz2_complex_plddt, boltz2_complex_iplddt, boltz2_complex_pde, boltz2_pdockq, boltz2_pdockq2, boltz2_lis, shape_complimentarity_boltz2_binder_ss` (note the misspelling — it IS the column), `proteinmpnn_score, redesigned_proteinmpnn_score, proteinmpnn_seq_recovery, esmfold_plddt, ted_confidence, isoelectric_point, molecular_weight`, foldseek tm-score/aligned-length/evalue vs afdb50/cath50/pdb100, plus sequence-derived `seq_length, cys_count, AA-fractions, seq_entropy`, and helix/sheet/loop parsed from the `foldstring` field.

**Do NOT reference** `pTMEnergy, bt_ipsae, tb_ipsae, DockQ, PyRosetta dG/SC/dSASA` in the Proteinbase-trained model — they are absent. Keep `pdockq/pdockq2` as flagged raw columns the tree can ignore (AUC ~0.500; do NOT inject through ratios). Drop `pDockQ`-derived composites.

**Missing-tool handling:**
- Co-missing BLOCKS: `ran_boltz2` (~72% present), `ran_foldseek` (~38%), `ran_esmfold`/`ran_proteinmpnn` (~100%). Define ~4 block-availability indicators, not dozens of per-column `*_isnan`.
- **Two-model split (load-bearing leakage discipline):** because the legacy label is a missingness indicator, block-availability features leak.
  - **HEADLINE model:** trained/evaluated only on rows where the Boltz-2 block ran, with NO availability indicators and NO `experimental__*`. This is where the "beat min_ipSAE" claim lives, apples-to-apples with min_ipSAE (also only defined on that subset).
  - **DEPLOYMENT model:** full feature set + block-availability indicators, used to score partial-coverage candidates and feed the bandit — its probability is honest for ranking but its AUC is NOT comparable to the headline.
- Use LightGBM native NaN handling (`use_missing=True, zero_as_missing=False`); prefer routing-on-missing over mean-imputation. **Audit `min_ipsae==0` as a failure sentinel** (many 0.0 values); if it encodes "prediction failed," it inflates the baseline.
- **Run a missingness-NMAR gate:** compare positive-rate in metric-present vs metric-absent labeled rows; if they diverge, restrict training to targets where the panel covers both binders and non-binders.

---

## 5. Model class & target-conditioning architecture

**Decision.** Primary = **regularized gradient-boosted trees (LightGBM/CatBoost)**. Run a **monotone-constrained penalized logistic regression** as an honesty baseline and **TabPFN v2** for cold-start/small-per-target. **Reject LLM fine-tuning.** Given ~107 positives, the realistic v1 winner may be a 3–5 feature monotone logistic or normalized rank-fusion — and that is an acceptable, defensible outcome.

**Target-conditioning architecture (overfitting addressed):** do NOT fit a deep conditioner or FiLM gate at this target count. Use **partial pooling**: a hierarchical model with per-target random intercepts (absorbing base-rate differences so the metric coefficients de-confound), plus **≤4–6 hand-picked metric×target-feature interaction terms** (e.g. `min_ipsae × frac_strand`, `shape_comp × epitope_planarity`) chosen on domain priors. Conditioning is reported **descriptively (SHAP)**, labeled "directional, underpowered," until `n_targets_with≥10_binders ≥ ~10` with ≥2 per SS class.

**Config:** LightGBM `num_leaves≤15, max_depth 3–4, min_child_samples 30–60, lr 0.02–0.03, strong L1/L2, scale_pos_weight≈10, feature_fraction 0.7, early stopping on grouped val`. Monotone constraints (written only against existing columns): `+1 boltz2_min_ipsae, +1 boltz2_ipsae, +1 shape_complimentarity, +1 boltz2_iptm`; `plddt` unconstrained.

**Reasoning.** Grinsztajn/McElfresh/Hollmann settle GBDT>NN on small tabular; Overath's external result (a 3-feature linear model beats complex ML across 15 targets) is a direct warning that a 90–110-dim model will overfit. Stage simple→complex (§10 ladder) and ship the smallest rung that wins.

---

## 6. Probability calibration

**Decision.** One **GLOBAL** calibrator, fit on held-out folds via nested GroupKFold-by-target. Use **Platt/sigmoid (or beta) — NOT isotonic** (isotonic needs >~500 positives; we have ~107). Emit a **probability interval** via Inductive Venn-ABERS whose width feeds the bandit.

**Reasoning.** Discrimination and calibration are orthogonal (monotone calibrators preserve ranking), so calibration is Stage 2 — only after a model out-discriminates min_ipSAE under LOTO (the in-repo 0.541 ensemble proves this is not free). Per-target/per-tier calibrators are infeasible at ~12 targets. Report reliability diagram + ECE (equal-mass bins) + Brier + **Brier Skill Score vs a calibrated min_ipSAE-alone model**, all with bootstrap CIs — never a bare ECE point estimate at this N. **Product copy must say P(measurable binding | assayed)**, not raw P(binds), and must not imply higher P = tighter affinity (among binders, min_ipSAE correlates *negatively* with KD, r≈-0.39).

---

## 7. Explainability layer

**Decision.** Ship **interventional TreeSHAP** importances, but at **per-bucket** granularity (interface classes: helical / sheet-flat / mixed / ligand-present), NOT per-target — per-target AUC is NaN for the key metrics today, so a per-target UI would only show weak sequence features.

**Implementation:** cluster correlated features (`|ρ|>0.8`: the min_ipsae/ipsae/iptm/lis family is near-collinear) and report **grouped SHAP at cluster level** so credit isn't split arbitrarily. Validate importance rank-stability across CV folds; suppress any importance whose bootstrap CI overlaps a label-shuffled null. **Leakage ablation:** zero the target-feature block; if per-bucket importance variation collapses, the "varies by target" story is real conditioning — if it persists via design-only features, it's target-ID memorization (report which). The LLM verbalizes the SHAP JSON verbatim (§13) and may not invent any number not in it.

---

## 8. Online seed allocation (bandit/portfolio)

**Decision.** A **cost-aware, two-tier Thompson-sampling portfolio** over the 6 generator arms `{bindcraft, rfdiffusion-proteinmpnn, boltzgen} × {2 configs}`, maximizing **hits per GPU-dollar**. **NOTE: red-team flags this as over-engineering for v1 — cut to cost-normalized greedy + Beta prior; defer Thompson/Venn-ABERS/IPS to v2 when arms ≫ budget.** The honest win is cost-normalization + warm start + the data flywheel — NOT bandit regret efficiency (at 6 arms / ~100 pulls, asymptotic bounds are vacuous).

**Mechanism:**
- **Two scorer tiers (economics fix):** a CHEAP early-proxy score (generator self-confidence / one fast metric, no Boltz-2) drives the bandit; the FULL validated scorer runs only on survivors for final ranking. A bandit that needs a full Boltz-2 run per seed to score is uneconomic.
- **Cost index:** `c_a = wallclock_sec × GPU_$/sec`; dispatch to `argmax θ_a/c_a` that fits remaining budget (BindCraft is ~30–100× slower than RFdiffusion+MPNN, so equal-seed allocation wastes budget). This directly optimizes the already-published `cost_adjusted_hit_rate`.
- **Three-tier reward ladder:** `r0=scorer_p` (dense), `r1=in-silico hit` (after Boltz-2), `r2=experimental binding` (wet-lab). `λ_t` blends toward **r2** as real labels accrue — otherwise the loop optimizes a self-referential ipSAE proxy forever.
- **Per-tool reward de-bias:** subtract a rolling per-tool baseline (or rank within tool) so generators that internally optimize the scorer's metrics (BindCraft hallucinates against AF2 ipSAE) aren't structurally over-allocated.
- Warm-start priors `Beta(α,β)` hand-set from each target's `baseline_hit_rate` (strength 2–4); SOFT successive-halving; pending-pull pessimism discount; log **arm sampling propensity** for off-policy (IPS/DR) evaluation.

**Bandits matter for real only when arms expand to seed-level hyperparameters (guidance scale, binder length, hotspot weighting)** so #arms ≫ budget — that's v2, and it's the honest reason bandits earn their keep.

---

## 9. Cold-start strategy

**Decision.** Three layers: (1) **Foldseek k-NN route** the new target to a difficulty class + eligible-tool set (route only — do not inherit per-tool win-rates; the catalog has label density on ~2 targets); (2) **safe default score** = single global ipSAE-dominant heuristic with one global calibration map, labeled "within-target validity unproven"; (3) **self-correcting bandit** with weak priors (`k=5`) + generous uniform pilot. TabPFN v2 handles the small-per-target regime.

**Reasoning.** Retire the "guaranteed 0.806 floor" language — `0.806` is pooled, Nipah-dominated, and effectively a viral-glycoprotein model; transferring it confidently to a flat polar cytokine receptor may be actively wrong. The bandit self-corrects, so weak priors cost little. Surface a **wide uncertainty band** (Venn-ABERS) and flag every prediction `validated` vs `extrapolated`; for a brand-new customer target the honest product is a calibrated prior + an allocator that provably self-corrects, not a guarantee.

---

## 10. Evaluation protocol & baselines to beat

**Decision.** **Leave-One-Target-Out** (GroupKFold by curated target id) is the ONLY admissible headline protocol. Plain/random CV leaks target identity and is forbidden in any reported number. Nest an inner GroupKFold for HPO + calibration. Add a **design-method-family holdout** (several Proteinbase methods explicitly optimize ipSAE). Run Nipah-in vs Nipah-out side by side; if a "win" exists only with Nipah pooled in, label it leakage publicly.

> **RED-TEAM CRITICAL:** the protocol is not yet pinned down. Under LOTO each fold is ONE target, so "recompute within-target" is a no-op; you must choose per-fold-averaged Precision@k (undefined on targets with <k designs) OR pooled (reintroduces Simpson leakage). Resolve to **Precision@k(target) / Recall@budget** and PRE-REGISTER before generating any number.

**Baseline ladder (ship the smallest rung whose paired held-out Δ is significant):**
- **B0:** `boltz2_min_ipsae` alone, recomputed on the identical held-out rows (NOT the pooled 0.806). Expect ~0.55–0.70.
- **B1:** L2-logistic on `{min_ipsae, shape_complimentarity, iptm, lis}` — the real bar; a 50-line model clears single-metric trivially.
- **B2:** the in-repo naive percentile-rank ensemble (**0.541 pooled** — you must beat your own documented failure).
- **B3:** Overath 3-feature linear model (`ipSAE_min + shape_comp + RMSD_binder`) — the external parsimonious baseline.
- **B4:** GBDT, metrics only. **B5:** + target features. **B6:** + interactions/conditioning.

**Report per held-out target:** `N_pos`, `N_neg`, ROC-AUC, **PR-AUC**, **Precision@k**, Brier/ECE; aggregate = unweighted mean across targets (so Nipah doesn't dominate). Significance = **paired bootstrap (10,000 BCa, seed=0) of ΔPrecision@k and ΔAUC vs B0 and B3 on identical designs**, plus a **power-honesty statement**: with ~12 targets the conditioning test (B6−B5) AND the headline test (B4/B5 vs B0) may be inconclusive — say so. Strip all `experimental__*`. **Pre-register and version** splits-v1.json + label-provenance manifest before generating data.

---

## 11. Prior art & where the REAL moat is

**Decision.** The moat is **NOT Proteinbase** (public Adaptyv download) and NOT the meta-scorer math (Overath shows 3 linear features rival complex ML; structural-QA models like EnQA/DProQA/GATE are prior art on a different label). The defensible assets are the three things Proteinbase does **not** have:

1. **A leakage-controlled, pre-registered, real-wet-lab binder-scoring benchmark** with LOTO + paired baselines — the credibility artifact no competitor has published.
2. **A true 12-tool orthogonal feature matrix** — but only if you *prove* the extra tools add marginal Precision@k beyond Boltz-2's own metrics (run the Boltz-2-only vs +each-tool ablation; Overath suggests 2–3 metrics may carry most of the signal). If they don't, the multi-tool "moat" collapses to orchestration, which Tamarind/Neurosnap already own — know this before pitching it.
3. **The data flywheel:** new diverse labeled targets + seed-allocation exploration logs with logged propensities and counterfactuals — the one corpus competitors structurally cannot download.

**Honest YC headline:** "Single metrics are weak *within* a target; we built the first leakage-controlled real-label benchmark and extract measurable additional top-k ranking signal over the best metric under Leave-One-Target-Out — and our allocator + flywheel compound on data nobody else has." Do NOT cite "82.1% hit rate, p<10⁻¹⁵, 3,500 targets" — these conflate hit-rate with AUC, treat correlated non-iid designs as independent, and the target counts are irreconcilable across docs. A technical YC partner will reproduce the notebook in an afternoon.

---

## 12. Data flywheel / logging schema

**Decision.** Extend the existing Postgres schema (`benchmark_runs` + `designs` JSONB). Log EVERY design with full tool metrics + decision-time bandit state + nullable experimental outcome.

**Tables:**
- `targets(target_id PK, pdb, chain, hotspots, features JSONB, esm2_embedding VECTOR(1280) [unused until ≥30 labeled targets])`
- `designs(design_id PK, target_id FK, tool_id, tool_version, config_hash, seed, sequence, metrics JSONB, cost_usd, wallclock_sec, metric_present_blocks JSONB)`
- `predictions(design_id FK, model_version, scorer_p, venn_abers_lo, venn_abers_hi, eval_split ∈ {train,loto_holdout,shadow}, label_used ∈ {weak,strong}, boundary_distance)`
- `experimental_outcomes(design_id FK, binds BOOL, binding_strength, kd_nm, assay, expressed BOOL, reported_by, design_input_features_hash, UNIQUE(design_id,reported_by,assay,replicate), CHECK(kd_nm IS NULL OR binds))`
- `allocation_events(run_id, target_id, arm, posterior_alpha, posterior_beta, sampled_theta, index_theta_over_cost, sampling_propensity, proxy_reward_raw, proxy_reward_adj, true_reward NULLABLE, pending_pulls, budget_remaining, policy_version)`

**Backfill jobs (named, not assumed free):** (1) JSON-explode ETL → frozen sha256-versioned label table; (2) `historical_relabel` — recompute DockQ + pTMEnergy on legacy CSVs (5G51/v5 lack them, so they cannot be in-silico-labeled today); (3) `backfill_external` — re-run the 12-tool stack on Cao-2022 / Adaptyv designs to materialize features for their real labels (labels-without-features are unusable raw). 10–15% exploration slots always reserved; tested-negatives are first-class; promotion gate = paired bootstrap on identical LOTO held designs + ≥10 pos & ≥10 neg per held target.

---

## 13. Role of the LLM

**Decision.** LLM lives **only at the two edges**, never in the scoring path:
- **Ingest orchestration:** free-text → UniProt/PDB id + chain, categorical class/intent, tool-calling for fpocket/DSSP/Foldseek, config-fill. LLM proposes → deterministic validators verify → human confirms wet-lab constraints (hotspots/epitopes to a wet-lab without a human gate is a liability).
- **Egress rendering:** verbalize the TreeSHAP JSON verbatim, assemble the top-20 report.

**It does NOT** emit P(bind), compute allocation, or contribute any learned feature to the scorer in v1 (LLM-text features overfit at ~12 targets). Keep the LLM out of `config_hash` (pin a frozen local extraction model id for ingest so reproducibility holds; never let a drifting frontier API id into the hash).

> **RED-TEAM:** §3 epitope-local target features depend on hotspots, and the LLM proposes hotspots at ingest → train/serve skew (historical = hand-set hotspots, new = LLM-set). Freeze a deterministic hotspot rule and hash hotspot provenance into the feature vector.

---

## 14. V1 scope, build order, and explicit KILL criteria

**Build order (each step gates the next):**
0. **Resolve Proteinbase commercial-training/redistribution license** (it aggregates ~191 third-party teams' submissions). HARD GATE before touching the CSV.
1. **JSON-explode ETL + frozen label table** (explicit `binding` boolean, conditioned on `expressed`, sha256-versioned). Hard-exclude `experimental__*`. *Done = leakage unit test passes.*
2. **LOTO eval harness + curated target-mapping table + B0 baseline recomputed on the identical ~1,052-row intersection.** *Done = honest within-target min_ipSAE number + pinned Precision@k(target) definition exists.*
3. **Selection-leak + missingness-NMAR + range-restriction diagnostics** (`was_tested` AUC; metric-present vs -absent positive-rate; min_ipSAE distribution tested vs untested). *Publish these.*
4. **Baseline ladder B1→B6** under LOTO with paired bootstrap + power analysis; **ship the smallest winning rung.** Platt calibration.
5. **Per-bucket SHAP** + target-ID leakage ablation.
6. **Cost-normalized greedy allocator** (Beta prior from baseline_hit_rate) + logging schema. (Defer the full bandit.)
7. **Highest-leverage data action — NOT parallel, this is the #1 milestone:** acquire ≥2 well-powered non-Nipah targets with metric-blind-tested labels; re-score labeled-positive designs lacking the metric panel.

**KILL criteria (pre-registered — if hit, stop and pivot the narrative):**
- **K1:** The learned model does NOT beat B0 (within-target min_ipSAE) AND B2 (the 0.541 ensemble) on LOTO Precision@k with a CI lower bound > 0 → the scorer thesis is not yet real; pivot YC story to orchestration + benchmark + flywheel, frame the scorer as an improving by-product.
- **K2:** The Boltz-2-only vs +each-tool ablation shows the extra 9 tools add no significant marginal Precision@k → the "12-tool moat" is dead; ship a 2–3 metric scorer and compete on UX/flywheel.
- **K3:** Selection-leak diagnostic shows min_ipSAE's `was_tested` AUC ≈ its `is_binder` AUC (or range-restriction shows the baseline is artificially weakened) → the labeled signal is assay-selection, not binding; halt headline claims until metric-blind-tested labels are acquired.
- **K4:** After conditioning, target-features-only LOTO AUC > ~0.6 OR the SHAP leakage ablation shows conditioning is target-ID memorization → no honest target-conditioning claim; ship the global scorer only.

---

## 15. Open questions for the founder

1. **Where did `0.806` actually come from?** It is an unfilled `[CITATION: ipSAE-auc-derivation]` placeholder in methodology-v1.0.md and is not reproduced on Proteinbase's trainable slice. Adopt it with full provenance or retire it.
2. **How fast can you generate balanced, metric-blind-tested labels on NEW (non-Nipah) targets?** This throughput — not model tuning — gates the entire target-conditioning thesis. Fork: densify one more target for a 2nd LOTO fold (cheap proof), or test a wide thin panel across many targets (what the thesis needs)?
3. **Is there GPU budget to re-score Cao-2022 / Adaptyv designs and the labeled-positive Proteinbase rows that lack the metric panel?** Fastest path to a defensible strong-label set.
4. **Do the internal 5G51/RBX1/god-mode campaigns have ANY returned wet-lab binding results, or are they purely in-silico-scored?** If real results exist they are the most valuable labels in the company.
5. **Proteinbase commercial-use / redistribution license** — confirm before training a shippable model on it. (P0, not optional.)
6. **What is the real wet-lab batch size k** (assumed ~20) and does it scale with target list length? Precision@k must match the actual screen — and several powered targets have <20 tested designs, leaving per-target Precision@20 undefined.

---

# Red-Team Findings & Punch-List

This blueprint is unusually disciplined — leakage controls, pre-registered KILL criteria, refusal of the pooled 0.806, honest baselines. Below are the places it is **still wrong or still optimistic despite its self-awareness**, ordered by how badly a technical YC partner can hurt you with them.

## THE SINGLE BIGGEST RISK

**The dataset cannot adjudicate the claim the company is built to prove, and the blueprint half-hides this by applying its honesty selectively.**

The blueprint says target-conditioning (the *entire* differentiated pitch) is **statistically unobservable** at ~12 targets and demotes it to roadmap — good. But it then asserts the *headline* claim ("beat min_ipSAE within-target under LOTO, ΔPrecision@20 CI lower bound > 0") as provable v1, and that claim is **just as underpowered**:

1. **Power.** ~107 positives over ~12 targets, 67% Nipah. Non-Nipah folds have a handful of positives each. A paired bootstrap over ~11 tiny clusters to get a Precision@20 CI lower bound > 0 has near-zero power. The blueprint grants this honesty to the conditioning test but withholds it from the headline test — the central internal inconsistency.
2. **The metric is undefined on its own dataset.** Several powered targets have <20 tested designs, so Precision@20 is degenerate on most LOTO folds.
3. **Selection makes even a measured win non-transferable.** The labeled population is assay-selected; the product scores fresh, unselected generator output at deployment, where the manifold doesn't hold.

**Consequence:** evidence for the thesis is gated entirely on **new prospective, metric-blind-tested labels on diverse non-Nipah targets** — a slow, costly wet-lab program that is the real critical path.

## CONCRETE FLAWS

1. **Evaluation protocol not actually pinned — both readings broken.** Per-fold averaging is undefined on small targets; pooling reintroduces Simpson leakage. Pin to Precision@k(target)/Recall@budget before any number.
2. **Range-restriction attenuation** (the subtle selection bug K3 misses): selection truncates min_ipSAE's range, deflating its measured AUC, so a meta-scorer can "beat" an artificially weakened baseline. Add the tested-vs-untested distribution diagnostic.
3. **"Tested negatives not scarce" is misleading post-join** — market the ~1,052-row / ~107-pos headline-subset counts, not 359/2,158.
4. **Two-model split = "the number isn't from the shipped model" landmine** — pre-script how you present headline≠deployment, or it reads as cherry-picking.
5. **Foldseek fold-id as target feature = the target-ID leakage you banned.** Drop categorical fold id; keep continuous geometry.
6. **LLM-set hotspots enter the feature pipeline → train/serve skew.** Freeze a deterministic hotspot rule; hash provenance.
7. **The bandit is the over-engineering the rest of the doc forbids.** V1 = cost-normalized greedy + Beta prior. Defer Thompson/Venn-ABERS/IPS to v2.
8. **Calibration oversold at this N** — don't market calibrated probabilities in v1; say uncertainty is too wide to be product-grade.
9. **Precision@20 doesn't match the operation** — use Precision@k(target)/Recall@budget.
10. **License is a P0 gate, not open-question #5** — resolve before ETL.

## THE STRATEGIC OVERCLAIM (decides the YC outcome)

The provable v1 is likely **undifferentiated** (a 4-feature logistic wins, B4–B6 add nothing), and the differentiated v2 (target-conditioning) is **unprovable until a new-target wet-lab program succeeds** — which likely exceeds the YC evidence window. The thesis can be *true* and still have *no demonstrable evidence* at decision time. **That timeline gap, not leakage, is what to fix.** And in the kill-triggered world the blueprint pivots to "orchestration + benchmark + flywheel" — but admits orchestration is owned by Tamarind/Neurosnap and Proteinbase is a public download, so it never closes the loop on what the company actually is. Close that loop.

## PRIORITIZED PUNCH-LIST

1. **Resolve Proteinbase commercial-training license FIRST** (hard gate before ETL).
2. **Pin the evaluation protocol** — Precision@k(target)/Recall@budget; pre-register; define behavior when target size < k.
3. **Apply the conditioning test's honesty to the headline test** — run a power analysis; state up front the headline Δ may be inconclusive at ~12 targets / ~107 selected positives.
4. **Add the range-restriction diagnostic + selection-transfer caveat**; make K3 catch attenuation, not just gross equality.
5. **Report post-join counts**; retire pre-join "359/2,158."
6. **Reframe the YC headline** around what's provable + the data program; pre-write the K1/K2 fallback identity.
7. **Cut the bandit to cost-normalized greedy + Beta prior for v1.**
8. **Drop categorical Foldseek fold id** from target features.
9. **Freeze a deterministic hotspot rule**; hash hotspot provenance.
10. **Pre-script the "headline model ≠ deployed model" explanation.**
11. **Make "acquire ≥2 well-powered non-Nipah targets with differing metric importances" the company's #1 milestone**, not a parallel step.

**What the blueprint gets right (keep):** banning circular benchmark-v1.0 labels, the `experimental__*` leakage unit test, LOTO-only + Nipah-in/out side-by-side, refusing the pooled 0.806, B2 (the 0.541 ensemble) as a baseline you must beat, and the K1–K4 kill gates. The skeleton is sound; the optimism is concentrated in pretending the headline test escapes the same power/selection limits the doc correctly applies to conditioning.

---

*Source: 42-agent dynamic workflow (`wf_af5db1e7-36f`), 20 hardened dimensions + synthesis + red-team, 2026-06-19.*
