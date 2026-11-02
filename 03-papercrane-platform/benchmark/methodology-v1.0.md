# Paper Crane Binder Design Benchmark — Methodology v1.0

- **Version:** v1.0
- **Date:** 2026-04-23
- **Status:** pre-registered
- **Maintainer:** Paper Crane Core Team
- **Governance:** See [`GOVERNANCE.md`](GOVERNANCE.md)

> This document is the authoritative, pre-registered specification for the
> Paper Crane binder design benchmark. It is versioned, git-signed, and
> immutable after publication. Any change to the thresholds, target set,
> statistics, or reproducibility contract forks a new methodology version
> (see §7, §8). The goal is to provide a scientifically defensible,
> reproducible, head-to-head comparison of *in silico* protein binder design
> tools against standardized targets under matched compute environments.

---

## §1 Benchmark Cell

The fundamental unit of the benchmark is the **benchmark cell**, uniquely
identified by a 6-tuple:

```
cell = (target_id, tool_id, tool_version, config_hash, seed_range, compute_env_hash)
```

| Field              | Definition                                                                                                 |
|--------------------|------------------------------------------------------------------------------------------------------------|
| `target_id`        | Slug from `targets/*.yaml` (e.g. `pd-l1`, `sars-cov2-rbd`, `il-7ra`).                                      |
| `tool_id`          | Canonical tool slug (e.g. `bindcraft`, `rfdiffusion-proteinmpnn`, `boltzgen`).                             |
| `tool_version`     | Upstream release tag or pinned commit SHA of the tool at execution time.                                    |
| `config_hash`      | `sha256` of the canonical JSON config passed to the tool (sorted keys, stripped of runtime-only fields).   |
| `seed_range`       | Inclusive integer range, e.g. `0..59` for full tier (see §5).                                              |
| `compute_env_hash` | See §6.                                                                                                    |

Every published result must cite the full 6-tuple. Two results with identical
6-tuples must be bitwise-identical run manifests (see §11); divergence
indicates a bug and triggers invalidation under §7.

---

## §2 Target Set

The v1.0 target set is defined in [`targets/*.yaml`](targets/). Each target
file is the authoritative record of the target's structural input, hotspot
residues, hotspot rationale, class, difficulty tier, and baseline hit rate.

v1.0 launches with three targets:

- [`targets/pd-l1.yaml`](targets/pd-l1.yaml) — immune checkpoint, easy tier
- [`targets/sars-cov2-rbd.yaml`](targets/sars-cov2-rbd.yaml) — viral antigen, medium tier
- [`targets/il-7ra.yaml`](targets/il-7ra.yaml) — cytokine receptor, hard tier

New targets are added under the governance process in
[`targets/README.md`](targets/README.md) and bump the methodology minor
version (e.g. v1.0 → v1.1) only if the hit-definition or statistical contract
is unchanged; otherwise a new major version is forked (see §7).

---

## §3 Hit Definition

A design is a **hit** iff it simultaneously satisfies all three criteria
computed on its top-ranked predicted complex:

```
hit = (ipSAE >= 0.70) AND (DockQ >= 0.23) AND (pTMEnergy <= -1.2)
```

**Rationale:**

- **ipSAE ≥ 0.70** — ipSAE (interprotein Score from Aligned Errors) is the
  strongest single predictor of experimental binding success in published
  binder-design benchmarks (AUC ≈ 0.806, internal derivation — see
  `[CITATION: ipSAE-auc-derivation]`). 0.70 is the conservative bound of the
  positive-predictive regime.
- **DockQ ≥ 0.23** — standard cutoff for an "acceptable"-quality complex
  prediction (Basu & Wallner 2016), ensuring the interface geometry is
  physically meaningful rather than a random docking artifact.
- **pTMEnergy ≤ −1.2** — pTMEnergy (novel metric, see
  `[CITATION: pTMEnergy-paper]`) captures energy-like interface signal
  orthogonal to ipSAE; the −1.2 threshold was chosen to maintain ≥95%
  specificity on a held-out validation set.

These thresholds are **pre-registered and immutable** under the current
methodology version (see §7). Retrospective threshold tuning is explicitly
disallowed.

Ranking, ties, and design selection rules:

- Each design's score is computed from its **top-1** predicted complex by
  confidence (not mean across samples).
- If multiple seeds produce the same sequence (hash-collision), only the
  first-seen instance counts toward hit count.
- Designs that fail structure prediction (NaN metrics, pipeline error) count
  as non-hits, **not** excluded — this prevents pipeline fragility from
  inflating rates.

---

## §4 Input Fingerprint

To guarantee every tool sees the same target, the per-cell **input
fingerprint** is:

```
fingerprint = sha256(pdb_bytes || chain_id || sorted(hotspot_residues) || target_version)
```

where:

- `pdb_bytes` — raw bytes of the canonical PDB file (stripped of `REMARK`
  lines and re-numbered to author numbering).
- `chain_id` — single ASCII letter, the target chain.
- `sorted(hotspot_residues)` — ascending list of integer residue numbers,
  serialized as `"[1,2,3]"` with no whitespace.
- `target_version` — the `version` field in the target YAML.

The fingerprint is recorded in every run manifest (§11). A mismatch between
a submission's fingerprint and the canonical target fingerprint invalidates
the submission.

---

## §5 Seed Range

Every cell runs a deterministic seed range:

- **Full tier:** 60 seeds (`seed_range = 0..59`). This is the number
  required to produce published leaderboard results and to pass the
  bootstrap confidence-interval width target (§9).
- **Smoke tier:** 10 seeds (`seed_range = 0..9`). Used for cheap CI gates
  and PR previews; **never** promoted to the public leaderboard.

The 60-seed count was chosen to yield ≤5% absolute 95%-CI half-width on
hit rate for a tool whose true rate is ~30%, given the 10,000-resample
bootstrap described in §9.

---

## §6 Compute Environment Fingerprint

```
compute_env_hash = sha256(container_digest || cuda_version || driver_version)
```

- `container_digest` — full OCI digest (e.g. `sha256:abc…`) of the pinned
  Docker image in which the tool was executed. Mutable tags (`latest`,
  floating version tags) are rejected.
- `cuda_version` — full CUDA toolkit version string as reported by
  `nvcc --version` inside the container.
- `driver_version` — host NVIDIA driver version (`nvidia-smi
  --query-gpu=driver_version`).

The compute environment fingerprint is logged in every run manifest.
Submissions that cannot produce a valid `compute_env_hash` — or whose
container digest is not reproducible from a publicly-available Dockerfile —
are ineligible for the public leaderboard but may be listed in a
"community" category.

---

## §7 Pre-registration Rule

All thresholds, target sets, seed ranges, statistical procedures, and
reproducibility requirements specified in this document are **pre-registered
and immutable** within a methodology version.

**No retroactive changes.** If any of the following change, a new
methodology version (v1.1, v2.0, …) **must** be forked and the old version
frozen:

- Hit criteria (§3) or any threshold value.
- Input fingerprint formula (§4).
- Seed count or selection procedure (§5).
- Compute-env fingerprint formula (§6).
- Statistical procedure (§9).
- Cost-adjusted metric formula (§10).

Forking a methodology version requires (see §8):

1. A PR that creates `methodology-vX.Y.md` (this file is never overwritten).
2. GPG-signed commit from a maintainer.
3. At least 2 advisory panel approvals (§8, `GOVERNANCE.md`).
4. A 7-day public comment window (`targets/README.md` process).

Tools are evaluated under the methodology version that was current at
submission time; old leaderboards remain published and immutable.

---

## §8 Versioning Policy

- Every methodology version is committed as a file named
  `methodology-vX.Y.md` (this file is `methodology-v1.0.md`). The file is
  append-only; typos or clarifications require a new patch version.
- Every release commit is **signed with a maintainer's GPG key**. Unsigned
  commits touching `methodology-*.md` or `targets/**` are rejected by CI
  (see `.github/workflows/benchmark-methodology-gate.yml`).
- The commit hash of the methodology file is **published on every
  leaderboard page** and on every run-manifest header, so any result can
  be traced to the exact methodology text it was scored under.
- Tool-version–to–methodology-version compatibility is listed in the
  leaderboard metadata.

---

## §9 Statistics

- **Hit-rate confidence intervals:** 10,000-resample nonparametric
  bootstrap over the 60 designs in a cell, 95% CIs reported by the
  bias-corrected and accelerated (BCa) method.
- **Tool comparisons:** paired bootstrap (designs held constant across
  tools where the target is identical) with 10,000 resamples. Reported
  as a paired difference in hit-rate, 95% CI, and a two-sided bootstrap
  p-value. Multiple-comparison correction uses
  Benjamini–Hochberg (FDR = 5%) when comparing N > 2 tools per target.
- **Per-target vs aggregate:** aggregate hit-rates are reported as
  the unweighted mean of per-target hit-rates, not pooled across
  targets, so a single easy target cannot dominate the score.
- **Reproducibility of CIs:** the bootstrap RNG seed is fixed
  (`seed = 0`) and published with each leaderboard release.

---

## §10 Cost-Adjusted Hit Rate

The primary headline metric is **cost-adjusted hit rate**:

```
cost_adjusted_hit_rate = hit_rate / mean_cost_usd_per_design
```

where `mean_cost_usd_per_design` is the mean USD cost to produce one
design (GPU-time × list price of the cheapest eligible instance,
averaged across the 60 seeds). List prices are snapshotted weekly from
public cloud pricing (AWS on-demand, Vast.ai median, Modal published
rates).

This metric penalizes tools that achieve high hit rates only via
expensive sampling, and is the default leaderboard sort. Raw hit rate,
mean cost, and the ratio are all displayed.

---

## §11 Reproducibility — Signed Run Manifests

Every cell produces a **run manifest** that is signed (maintainer GPG or
submitter's verified key) and stored under
`benchmark/manifests/<target_id>/<tool_id>/<cell_hash>.json.sig`.

A run manifest contains, at minimum:

- Full 6-tuple (§1).
- Input fingerprint (§4) and the raw inputs (or a URL + sha256 of their
  stored copy).
- Compute environment fingerprint (§6).
- Per-seed raw outputs (sequence, top-1 predicted complex, and the
  ipSAE / DockQ / pTMEnergy values).
- Hit count and derived hit rate.
- Bootstrap CI with the fixed RNG seed.
- Wall-clock, GPU-seconds, and measured cost.
- Methodology commit hash.

Submissions without a verifiable signed manifest are ineligible for the
public leaderboard.

---

## §12 External Submission Policy

External submissions are welcomed under the following summary rules;
the authoritative process is [`GOVERNANCE.md`](GOVERNANCE.md):

- Submitters must open a PR with their signed run manifest(s).
- Submitter must disclose any conflicts of interest (employment,
  funding, equity).
- Submissions are reviewed by the 3-person external advisory panel
  (rotating, see `GOVERNANCE.md`) plus ≥2 Paper Crane maintainers.
- Disputes over results or methodology are resolved by a public RFC
  process (30-day window) documented in `GOVERNANCE.md`.
- Submissions that fail the reproducibility contract (§11) are
  returned with specific remediation instructions, not silently
  rejected.

---

**signed-by:** `<maintainer-gpg-key-fingerprint-placeholder>`

**methodology commit:** `<populated-by-CI-on-publish>`

**citation:** see [`CITATION.cff`](CITATION.cff)
