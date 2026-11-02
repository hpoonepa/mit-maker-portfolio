# LLM Literature-Informed Per-Target Prior — Benchmark Plan

> **For agentic workers:** Execute with superpowers:subagent-driven-development, task-by-task, TDD. Steps use `- [ ]`.

**Goal:** Build a `B_LLM` scorer where an LLM **reads real research (PubMed + Open Targets)** about each target, uses it to identify known epitopes / liabilities / failure-modes, then **decides which features matter and how to weight them** (and proposes new features to compute). Wire it into the existing LOTO harness and benchmark vs B0 / B5 / B6. Produce the number: *does a literature-informed per-target prior beat raw min_ipSAE, the global model, and the target-conditioned tree?*

**Architecture (data flow):**
```
target → [literature.py] PubMed + Open Targets → abstracts/facts (cached)
       → [llm_prior.py] LLM(features + literature) → structured prior:
            { weights over metrics, failure_penalties, epitope_residues,
              liabilities, proposed_features[computable_now | needs_structure] }  (cached JSON)
       → [baselines.b_llm_prior] train-normalized weighted sum + penalties → ranking
       → [loto_eval] benchmark vs B0/B5/B6
```
Priors generated **once per target, offline, cached** (deterministic eval, no API at eval time). The LLM sees target identity + structural features + literature + the metric list — **never the test labels.**

**Tech stack:** Python; existing `scorer/` harness; Anthropic API; PubMed E-utilities (free REST); Open Targets GraphQL; Boltz API (Phase 2 only).

**Prerequisites (confirmed):** `ANTHROPIC_API_KEY` ✓, Boltz API ✓. PubMed E-utilities need no key (optional `NCBI_API_KEY` for higher rate).

**Honest caveats baked in:** (1) Even with literature, the LLM knows these famous targets → still the *identity-revealed* arm; the K5 anonymized/novel-target control is the honest follow-up (separate plan). (2) n=11 → result is **directional, not proof** (below MDE 0.035). (3) Literature retrieval quality varies per target (obscure targets = thin abstracts).

---

# PHASE 1 — Literature-informed weighting (the ~1-day core)

## Task 1 — Literature retrieval (`scorer/literature.py`)
**Files:** Create `scorer/literature.py`, `scorer/tests/test_literature.py`. Cache dir: `data/processed/literature/{target}.json` (gitignored).

- [ ] **Failing test:** `build_pubmed_query(target_name, synonyms)` returns a query string combining the target + binder/epitope/inhibitor/antibody terms. `parse_efetch_xml(xml)` extracts `[{pmid,title,abstract}]` from a small fixture XML.
- [ ] **Implement:**
  - `fetch_pubmed_abstracts(target_name, synonyms, retmax=15) -> list[dict]` — PubMed E-utilities `esearch` (get PMIDs) then `efetch` (abstracts). Cache to JSON; on cache hit, skip network. Rate-limit politely.
  - `fetch_open_targets(uniprot) -> dict` — Open Targets GraphQL: known drugs, tractability, safety liabilities (best-effort; return `{}` on miss). Optional but include.
  - `gather_literature(target, synonyms, uniprot) -> dict` — merges both, caches, returns `{abstracts:[...], open_targets:{...}}`.
- [ ] Test with a recorded HTTP fixture (no live network in tests). Run green, commit.
- [ ] **Build the target→synonyms/UniProt map** for the 11 well-powered targets (reuse `data/raw/targets/` accessions: EGFR P00533, FGFR2 P21802, IL7R P16871, INSULINR P06213, MDM2 Q00987, PDL1 Q9NZQ7, PD1 Q15116, MZB1 Q8WU39, PDGFRB P09619, PMVK Q15126, NIPAH Q9IH62). Run `gather_literature` for all 11, cache, print abstract counts per target (flag thin ones).

## Task 2 — Prior schema + loader (`scorer/llm_prior.py`)
**Files:** Create `scorer/llm_prior.py`, `scorer/tests/test_llm_prior.py`. Cache: `data/processed/llm_priors.json`.

Prior shape:
```json
{ "EGFR": {
    "weights": {"computational__boltz2_min_ipsae":0.4,"shape_complementarity":0.3,"rmsd_binder":0.2,"computational__boltz2_iptm":0.1},
    "failure_penalties": {"cysteine_fraction": {"gt":0.08,"penalty":1.0}},
    "epitope_residues": [310,311,...],
    "liabilities": ["disulfide misfold if Cys-rich","off-target to domain II"],
    "proposed_features": [{"name":"epitope_contact_domainIII","computable":"needs_structure"}],
    "rationale": "...", "citations": ["PMID:..."]
}}
```
- [ ] **Failing test:** frozen `Prior` dataclass; `load_priors(path)` validates weights finite/non-negative, keys ∈ known feature columns, L1-normalizes, raises on unknown metric key.
- [ ] **Implement** `Prior`, `load_priors`, `_validate_and_normalize`. Run green, commit.

## Task 3 — Literature-informed prior generator (`scorer/llm_prior.py`, append)
- [ ] **Failing test:** `build_prior_prompt(target, features_row, literature, available_metrics)` produces a prompt that includes structural features, the literature abstracts/facts, the metric list, and instructs: *from the literature, identify the known epitope residues, liabilities, and failure modes; then output JSON only — weights over the listed metrics, failure_penalties, epitope_residues, liabilities, proposed_features (each tagged computable_now|needs_structure), citations; never reference experimental labels.*
- [ ] **Implement** `build_prior_prompt`, `generate_prior(target, features_row, literature, available_metrics, client) -> Prior`, `AnthropicClient` (model `claude-opus-4-8`, low temp, JSON output), `RecordedClient` for tests.
- [ ] **Implement** `main()` CLI: for each of 11 targets → load features row + cached literature + metric list → `generate_prior` → write `llm_priors.json`. Print each prior's weights, epitope_residues, liabilities, proposed_features, citations.
- [ ] Test with `RecordedClient`. Run green, commit.
- [ ] **Generate the real cache** (real Anthropic + cached literature). Eyeball: priors VARY across targets; citations are real PMIDs; collect the union of `proposed_features` (feeds Phase 2).

## Task 4 — `b_llm_prior` scorer (`scorer/baselines.py`, append)
- [ ] **Failing test** on a synthetic fold where the prior up-weights the signal metric → ranks binders first AND differs from B6.
- [ ] **Implement** `b_llm_prior(train_labels, train_designs, test_designs, *, priors=None, target=None)`:
  - Default-load priors; missing target → fall back to `b0_within_fold_min_ipsae` + log.
  - Normalization (mean/std, nan-aware) from **train only** (leakage-safe).
  - `score = Σ w·z(metric)`, sign-flipped for `ENSEMBLE_INVERT_SUBSTRINGS`; skip missing; subtract `failure_penalties`. Rank descending.
- [ ] Register `("B_LLM", b_llm_prior)`. Run full suite green, commit.

## Task 5 — Wire + benchmark
- [ ] Thread `priors` + per-fold `target` into `b_llm_prior` from `run_loto_eval`.
- [ ] Integration test: `run_loto_eval(candidate="B_LLM", baseline="B0")` returns standard structure (11 folds, valid verdict, finite delta).
- [ ] Full suite green, commit.
- [ ] **RUN THE BENCHMARK:** `B_LLM` vs **B0** (headline), vs **B6**, vs **B5**. Capture per-target ΔPrecision@k, mean Δ + BCa CI + sign test, three-zone verdict, power statement, Nipah-IN/OUT.

## Task 6 — Report + framing
- [ ] `docs/research/2026-06-27-llm-benchmark-result.md`: prior table (weights/epitope/liabilities/citations per target), the three deltas + verdicts, caveats (memorization arm, n=11 underpowered, literature thinness). Update memory `[[papercrane-metascorer]]`.

---

# PHASE 2 — Feature-discovery menu (biology-informed; mostly TODAY, no dynamics)

> The "LLM discovers features to build" piece. The LLM picks from a MENU of biology features (per target, from literature) + proposes **signed** weights. Most of the menu is sequence-based → computable today. Only `[struct]` features need Boltz.
>
> **Design rationale (Orbion 2026, "Beyond Structure and Affinity"):** three layers of signal —
> **Transferable** (aggregation propensity = most robust cross-benchmark; PTM-site density, length-confounded → length-normalize). **Architecture-dependent** (topology, disorder, disulfide descriptors — significant but **FLIP DIRECTION** by context → a single global weight averages the flip to zero; per-target/LLM weighting can flip the sign). **Context-specific** (phospho associations, low-disorder dominance — assay/format-tied). Stacking biology filters lifted hit-rate 13.8%→38.6% (2.8×) after controlling for sequence-level predictors. **Implication: weights must be SIGNED; benchmark LLM-weighted vs data-weighted to test whether per-target sign-flipping wins.**
> **Dynamics features are OUT of scope for this build.**

### The discovery menu (LLM selects per target from these)
| Feature | Tag | What literature reveals → why it matters |
|---|---|---|
| `aggregation_propensity` | `[seq]` | binder aggregation; Orbion's most robust transferable signal (hydrophobic-patch score) |
| `ptm_site_density` | `[seq]` | N-glyc (N[^P][ST]) + O-glyc motif counts / length (length-normalized) |
| `phospho_site_density` | `[seq]` | S/T/Y phospho-acceptor density |
| `disulfide_potential` | `[seq]` | Cys count, pair potential, even/odd (beyond cysteine_fraction) |
| `disorder_fraction` | `[seq]` | disorder-promoting residue content (architecture-dependent, sign flips) |
| `topology_proxy` | `[seq]` | design SS architecture (Chou-Fasman helix/strand/loop on the binder) |
| `immunogenicity_proxy` | `[seq]` | predicted T-cell-epitope density (therapeutic targets) |
| `interface_conservation` | `[seq/ext]` | contacts conserved vs variable residues |
| `epitope_contact` | `[struct]` | contacts on literature hotspot residues (Boltz) |
| `off_target_face_contact` | `[struct]` | contacts on a known-bad face → penalty (Boltz) |
| `competitive_epitope_overlap` | `[struct]` | overlap with natural-ligand/antibody footprint (Boltz) |

## Task 7 — Biology feature block (`scorer/biology_features.py`) — `[seq]`, TODAY
- [ ] **Failing tests** (hand-computed on a known sequence) for: `aggregation_propensity` (max sliding-window mean hydrophobicity / aggregation-prone tripeptide count), `ptm_site_density` (N-glyc motif count + S/T/Y density per length), `phospho_site_density`, `disulfide_potential` (n_cys, floor(n_cys/2) pairs, even/odd), `disorder_fraction` (reuse target-feature disorder set), `topology_proxy` (Chou-Fasman frac_helix/strand/loop on the design), `immunogenicity_proxy` (hydrophobic 9-mer density as a crude T-cell-epitope proxy).
- [ ] **Implement**, pure-Python, zero-dep. Run green, commit.
- [ ] **Compute for ALL designs** in `labeled_features.csv` → write `data/processed/labeled_features_bio.csv` (original cols + the new `[seq]` biology columns). Add these to the available-metrics list used by the harness + the LLM prompt.

## Task 8 — LLM selects from the full menu + SIGNED weights
- [ ] Extend the prior generator (Task 3) prompt to present the **menu** and instruct: *from the literature, select which menu features matter for THIS target and assign a **signed** weight (positive = higher is better, negative = higher is worse — features can flip direction by target); flag any `[struct]` features you'd want computed; cite sources.* Allow negative weights in the `Prior` schema/validation (drop the non-negative constraint; keep finite + L1-normalize on absolute value).
- [ ] Regenerate the cached priors over the menu. Print per-target: which biology features each target up/down-weighted, and the SIGN (look for the Orbion flip — same feature, opposite sign across targets).

## Task 9 — DUAL benchmark (LLM-weighted vs data-weighted)
- [ ] Run on `labeled_features_bio.csv`:
  - **LLM-weighted:** `B_LLM` (uses the signed menu prior) vs **B0 / B5 / B6**.
  - **Data-weighted:** B6 and B5 retrained **with the new biology columns included** vs B6/B5 without them — does adding the biology features help when DATA sets the weights?
- [ ] Report both. Key question: do the Orbion biology features lift Precision@k, and does the **LLM (signed, per-target) weighting beat the data-learned global weighting** specifically on the sign-flipping features? Capture per-target deltas + CIs + three-zone verdicts.

## Task 10 — `[struct]` features via Boltz (sampled today, full later)
- [ ] `boltz-api estimate-cost` for one target's designs; log cost. Fold a SAMPLE (e.g., one well-powered target's designs) → compute `epitope_contact` (fraction of binder–target contacts on the LLM's literature epitope residues) → add column → re-benchmark on that target as proof-of-concept. Full-dataset folding is a follow-up (cost/time gated).

---

## Definition of Done (Phase 1)
1. `literature.py` retrieves + caches PubMed/Open Targets per target.
2. Priors are **literature-informed** (carry epitope_residues, liabilities, citations) and **vary across targets**.
3. `B_LLM` runs through the harness, leakage-safe.
4. Three benchmark numbers (vs B0/B5/B6) with CIs + three-zone verdicts captured.
5. Honest caveats documented. Full suite green.

## Out of scope
- K5 anonymized / novel-target memorization control (honest follow-up, separate plan).
- `resolve_prior` blend with a data corrector.
- Dynamics features (separate track).
