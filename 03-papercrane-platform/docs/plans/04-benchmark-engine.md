# Paper Crane Benchmark Engine + Public Leaderboard Plan

**Status**: Moat-critical. This document specifies the engineering plan to convert the static 540-run benchmark on `papercrane-h2im.vercel.app` into a continuously updated, externally reproducible, public leaderboard that becomes the industry reference for protein-binder tool evaluation.

---

## 1. Benchmark Definition Spec

A benchmark cell is fully defined by the 6-tuple:

```
(target_id, tool_id, tool_version, config_hash, seed_range, compute_env_hash)
```

**Current targets (v1.0)**:
| ID | PDB | Chain | Hotspot residues | Class | Tier |
|---|---|---|---|---|---|
| PD-L1 | 5O45 | A | 54,56,66,115,123 | Cytokine receptor | Easy |
| SARS-CoV-2 RBD | 6M0J | E | 417,453,486,493,501 | Viral antigen | Medium |
| IL-7Rα | 3UP1 | A | 80,132,178,182 | Cytokine receptor | Hard |

**Hit definition (pre-registered v1.0)**:
```
hit = (ipSAE >= 0.70) AND (DockQ >= 0.23) AND (pTMEnergy <= -1.2)
```
Values anchor to the thresholds memo at `reference_metric_thresholds.md` (ipSAE AUC 0.806). pTMEnergy threshold derived from the 20-agent novel-metric sweep (see `docs/novel_binding_metrics_2025.md`).

**Input fingerprint** (SHA-256):
```
fingerprint = sha256(pdb_bytes || chain_id || sorted(hotspot_residues) || target_version)
```
Any change to the target regenerates the fingerprint and forks a new benchmark version.

---

## 2. Reproducibility Guarantees

Every run stores a **run manifest** (pinned to IPFS + S3):

```json
{
  "run_id": "pc-run-7f3a9e2c",
  "benchmark_version": "1.0",
  "target_fingerprint": "sha256:a1b2...",
  "tool": {"id": "protenix", "version": "2025.03.14", "git_sha": "4f9d2e1"},
  "config_hash": "sha256:c4d8...",
  "config": {...raw params...},
  "seed_range": [1, 60],
  "compute": {
    "gpu": "A100-80GB",
    "driver": "550.54.15",
    "cuda": "12.4",
    "container_digest": "sha256:e7f1...",
    "provider": "vast.ai"
  },
  "results_digest": "sha256:9a2b...",
  "cost_usd": 4.28,
  "wallclock_sec": 1843
}
```

The "**Re-run this cell**" button on the leaderboard POSTs the manifest to `/api/rerun`, which spins up the identical container on Vast.ai and verifies the `results_digest` matches within tolerance (hit rate delta < 5%). Mismatch opens a public reproducibility incident.

---

## 3. Automated Continuous Benchmarking

**Cron schedule** (GitHub Actions → Vast.ai dispatcher):
- **Nightly (02:00 UTC)**: smoke-test tier — 10 seeds per (tool, target) on spot A100s. ~$8/night.
- **Weekly (Sunday)**: full tier — 60 seeds per (tool, target). ~$260/week.
- **On-demand**: triggered by
  1. New tool version published (polls `pypi`, `github releases`, `huggingface`).
  2. New target added via PR merge to `targets/`.
  3. External submission accepted.

**Drift detection**: if weekly hit rate moves >2σ from trailing 4-week mean, auto-page on Slack + post a `benchmark-incident` GitHub issue.

---

## 4. Public Leaderboard UX

ASCII sketch of `/leaderboard`:

```
+------------------------------------------------------------------------------+
| Paper Crane Benchmark v1.0  |  540 runs  |  3 targets  |  Updated 4h ago     |
+------------------------------------------------------------------------------+
| Filters: [Class v] [Tier v] [Tool v] [Config v]    Sort: [Hit rate v]        |
+----------------+---------+-----------+------------+-----------+--------------+
| Tool / Config  | PD-L1   | RBD       | IL-7Rα     | Mean      | Cost / hit   |
+----------------+---------+-----------+------------+-----------+--------------+
| PaperCrane-V4  | 62% [1] | 48% [1]   | 31% [1]    | 47% +-4%  | $0.89        |
| Protenix-2025  | 55%     | 41%       | 23%        | 40% +-5%  | $1.12        |
| RFdiffusion    | 48%     | 33%       | 18%        | 33% +-6%  | $0.74        |
| BindCraft      | 42%     | 29%       | 12%        | 28% +-6%  | $2.10        |
| Chai-1         | 39%     | 31%       | 15%        | 28% +-5%  | $1.45        |
+----------------+---------+-----------+------------+-----------+--------------+
| Click any cell -> drill to 60 designs, structures, run manifest, rerun btn   |
+------------------------------------------------------------------------------+
```

Every cell exposes: hit rate, 95% bootstrap CI, mean ipSAE, mean DockQ, compute cost per hit, "Re-run" button, "Download PDBs (.tar.gz)", "View manifest". Drill-down opens a molstar viewer with all 60 designs ranked.

---

## 5. External Submissions — The Genius Move

**Flow**:
1. Researcher opens a PR against `github.com/papercrane-bio/benchmark-submissions` with:
   - Tool name, version, install recipe (Dockerfile or conda env).
   - Config YAML for each target.
   - Author attestation (signed commit).
2. CI runs a **dry-run** on 5 seeds against PD-L1 to validate the tool produces parseable outputs.
3. On PR approval (2 Paper Crane maintainers + 1 external reviewer from the rotating panel), submission is promoted to the leaderboard and run on the weekly full tier.
4. **Incentive**: accepted submissions get **$100 Paper Crane compute credits** + permanent citation badge. For academic labs this is free press.

Positions Paper Crane as **neutral arbiter** — critical because you cannot be both the best tool and the referee unless the refereeing is provably open.

---

## 6. Pre-Registered Hit Thresholds

Methodology lives at `benchmark/methodology-v1.0.md`, Git-tracked, signed by GPG, commit hash surfaced on the leaderboard header:

> "Methodology v1.0 @ 4f9d2e1 (signed 2026-04-23). See Merkle proof."

**Pre-registration rule**: no threshold change is retroactive. Changing the hit definition forks a new methodology version (`v1.1`). Old leaderboard remains frozen at `/leaderboard/v1.0`, new data populates `/leaderboard/v1.1`. This is the anti-cherry-picking guarantee.

A public "**Why these thresholds?**" page documents the derivation from AUC sweeps in `reference_metric_thresholds.md` and the novel-metrics research.

---

## 7. Target Catalog Management

Target schema (`targets/<id>.yaml`):

```yaml
id: il7ra
pdb: 3UP1
chain: A
hotspots: [80, 132, 178, 182]
hotspot_rationale: |
  Derived from IL-7/IL-7Rα interface residues in Walsh 2012;
  cross-validated with MaSIF patch prediction top-5.
class: cytokine_receptor
tier: hard
baseline_hit_rate: 0.18
added: 2026-03-15
added_by: paper-crane-core
version: 1
```

Adding a target requires a PR with: PDB, hotspot rationale (literature or computational source), difficulty tier (from preliminary 60-seed default-tool run), and public comment period (7 days).

---

## 8. Statistics Layer

- **Hit rate CI**: bootstrap with 10,000 resamples on the 60 seeds.
- **Comparison significance**: paired bootstrap on matched seeds between tool A and tool B. Report p-value + effect size.
- **Multi-seed variance**: report coefficient of variation per (tool, target). Tools with CV > 0.35 get a "high variance" flag.
- **Meta-metric**: **Cost-adjusted hit rate** = hit_rate / (cost_usd_per_design). This is the headline number; it rewards tools that are both accurate AND efficient — Paper Crane's strength.

---

## 9. Preprint / Publication Strategy

- **Continuous bioRxiv preprint**: "The Paper Crane Benchmark: A Continuously Updated Leaderboard for Protein Binder Design." Every monthly release produces a new version on bioRxiv + a Zenodo DOI.
- **Citation format**:
  > Poonepalle H. et al. *Paper Crane Benchmark v1.2*. Zenodo (2026). doi:10.5281/zenodo.xxxxxxx
- **Artifact package**: every Zenodo release bundles the full run manifests, PDB outputs, and leaderboard snapshot.
- **Strategic value**: the preprint is (a) the MIT EA defense artifact, (b) YC traction signal, (c) forces competitors to either participate or explain absence.

---

## 10. API Access

```
GET  /api/v1/leaderboard?target=il7ra&tool=*
GET  /api/v1/run/{run_id}
GET  /api/v1/target/{target_id}
POST /api/v1/rerun  (auth required, rate-limited)
GET  /api/v1/methodology/{version}
```

**Tiers**:
- **Free**: 1,000 requests/day, read-only. Drives academic adoption.
- **Team ($49/mo)**: 50,000/day + webhook alerts on new results.
- **Enterprise**: programmatic `rerun` and custom-target submission.

---

## 11. Build Sequence (6 Milestones)

| M | Scope | ETA | Dep |
|---|---|---|---|
| **M1** | Port existing 540-run V3B/V4/5G51/RBX1 data into Postgres, build `/leaderboard` page reading from DB (replacing static JSON on Vercel). | Day 1-3 | — |
| **M2** | Add full run-manifest schema, backfill manifests for existing runs (recompute digests, pin to IPFS). "Re-run this cell" button (manual trigger only). | Day 4-6 | M1 |
| **M3** | Nightly cron on GitHub Actions → Vast.ai dispatcher. Drift detection + Slack alerts. | Day 7-9 | M2 |
| **M4** | Public submission repo, dry-run CI, reviewer workflow. First external tool onboarded. | Day 10-13 | M3 |
| **M5** | Preprint automation: monthly Zenodo release script + bioRxiv template generator. | Day 14-16 | M4 |
| **M6** | Community target nomination portal; expand to 10 targets per roadmap §12. | Day 17-25 | M5 |

M1–M3 ship within the 14-day MVP sprint. M4–M6 post-YC-application.

---

## 12. Target Expansion Roadmap (3 → 10)

| # | Target | PDB | Class | Tier | Rationale |
|---|---|---|---|---|---|
| 1 | PD-L1 | 5O45 | Cytokine rec | Easy | Already in v1.0; immuno-oncology reference |
| 2 | SARS-CoV-2 RBD | 6M0J | Viral antigen | Med | Already in v1.0; pandemic relevance |
| 3 | IL-7Rα | 3UP1 | Cytokine rec | Hard | Already in v1.0; sparse literature binders |
| 4 | TrkA (NGF recep) | 1WWW | RTK | Hard | First kinase-adjacent ECD; expands class |
| 5 | CXCR4 | 3OE0 | **GPCR** | V.Hard | First GPCR — everyone claims to handle them, few do |
| 6 | Influenza HA stem | 6CNV | Viral antigen | Med | Tests conserved-epitope generalization |
| 7 | TNF-α | 2AZ5 | Cytokine | Easy | Validated drug target; calibration anchor |
| 8 | IL-2 | 1M47 | Cytokine | Med | Classic design benchmark (Baker lab precedent) |
| 9 | Acetylcholinesterase | 1EVE | **Enzyme** | Hard | First enzyme — orthosteric-site binding class |
| 10 | HIV gp120 CD4bs | 3JWD | Viral antigen | V.Hard | Notoriously difficult — separates strong from weak |

Adds GPCR and enzyme classes, raises top-tier difficulty (10 is notoriously unsolved), keeps an easy calibration anchor (7).

---

## 13. Risks + Mitigations

| Risk | Mitigation |
|---|---|
| **Target curation bias** (we pick targets our tool wins on) | Rotating 3-person external advisory panel approves new targets; 7-day public comment; hotspot rationale from literature not us |
| **Gaming by tool authors** (train-on-test) | Seed range is public but outputs are verified against container digest; tool versions pinned by `git_sha`; reproducibility incidents are public |
| **Methodology disputes** | Methodology versioning — forks create new leaderboard, old stays frozen; signed commits; public RFC process for changes |
| **Compute cost of continuous benchmarking** (~$1,400/mo at 10 targets × 5 tools weekly) | Spot Vast.ai A100s; smoke tier nightly, full tier weekly; sponsorship model — "Benchmark sponsored by X" after traction |
| **Paper Crane appearing non-neutral** | Public governance doc; external submissions outnumber our own configs; all our configs rerun by external reviewers before publication |
| **Tool authors refuse to participate** | We run their tool ourselves from public code; clearly label "author-submitted" vs "Paper-Crane-run" on leaderboard |

---

## Closing

The benchmark is the wedge. Every academic who cites our preprint, every tool author who submits a config, every journalist who writes "according to the Paper Crane Benchmark..." — they all reinforce the position. Ship M1-M3 inside the 14-day sprint so the YC application points to a live, continuously updated leaderboard, not a screenshot.
