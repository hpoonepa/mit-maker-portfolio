# LLM Meta-Scorer Platform Contract

Status: experimental platform feature, implemented 2026-07-11.

## Source material reviewed

The feature is based on the separate `binder-scorer` research repository:

- `docs/specs/2026-06-19-meta-scorer-blueprint-design.md`
- `docs/plans/2026-06-27-llm-prior-benchmark.md`
- `docs/research/2026-06-28-llm-benchmark-result.md`
- `data/processed/llm_priors.json`
- `data/processed/5g51_prior.json`
- `scorer/llm_prior.py` and `scorer/baselines.py`

The corrected benchmark result is the governing evidence. At 11 held-out
targets, achieved MDE is about 0.150, not 0.035. The reported v1 and v2 deltas
are therefore statistically unresolved. The platform must not describe this
score as validated, `P(bind)`, or a replacement for wet-lab evidence.

## Product behavior

Design API responses now include a versioned `metaScore`:

```ts
{
  version: "llm-prior-v2-platform.1";
  evidenceType: "computational";    // never wet-lab evidence
  status: "scored" | "insufficient_metrics";
  score: number | null;             // 0..1 relative evidence, not P(bind)
  coverage: number;                 // observed absolute prior weight / total
  priorSource: "target_prior" | "observed_metric_fallback";
  targetKey: string | null;
  availableMetrics: number;
  experimental: true;
}
```

`designs.get` also returns rationale, liabilities, citations, metric
contributions, and caveats. List endpoints return the compact summary.

The dashboard shows the full disclosure on design detail. The designs table
can sort by the experimental score, but canonical job rank is unchanged.

Each job also exposes a candidate decision report through
`designs.decisionReport`. It ranks persisted candidates by meta-score and
coverage, assigns conservative `advance`, `review`, `hold`, or
`insufficient_data` triage labels, and exports JSON/CSV with the scorer
version and provenance. `advance` is only a shortlist for manual review and
orthogonal validation.

This feature is computation-only. It consumes stored in-silico design metrics;
it does not schedule, control, or record wet-lab experiments.

## Deterministic scoring

The LLM does not run in the request path. It generated signed per-target priors
offline; the API consumes a checked-in, versioned subset of those priors.

For each available metric:

1. Resolve a documented alias (`ipsae`, `ipSAE`, `min_ipsae`, etc.).
2. Map the metric to `[0,1]` using a declared bounded transform.
3. For positive weights, aligned evidence is the normalized value.
4. For negative weights, aligned evidence is `1 - normalized value`.
5. Return the absolute-weighted mean over available metrics.

Missing metrics do not become zeros. They reduce `coverage`. If no supported
metric exists, the API returns `insufficient_metrics` and `score: null`.

This platform transform uses bounded metric scaling. The Python LOTO `B_LLM`
benchmark instead uses training-fold z-score normalization. The
research artifact does not currently ship deployable population means and
standard deviations for production inference.

## Target identity and fallback

New submissions persist owned `targetId` and `projectId` on the job. Design
reads resolve the linked target name/PDB first, then the submitted four-letter
PDB ID for legacy jobs.

Cached priors are available for EGFR, FGFR2, IL7R, INSULINR, MDM2, MZB1, PD1,
PDGFRB, PDL1, PMVK, and the scorer's explicit 5G51 target.

Unknown targets use an `observed_metric_fallback` dominated by ipSAE, with
ipTM and pDockQ as secondary evidence. The UI labels this fallback explicitly.

### 5G51 identity warning

The scorer artifact identifies 5G51 as a DWV VP3 capsid target. Some older
Papercrane benchmark copy labels 5G51 as PD-L1. The scoring resolver treats the
exact PDB identity as DWV VP3 and never aliases 5G51 to PDL1. This discrepancy
must be resolved before publishing any 5G51 benchmark claim.

## Operational rules

- Never call a frontier LLM during design reads or ranking.
- Never change a prior without changing `LLM_META_SCORER_VERSION`.
- Never silently map an unknown target to the nearest named prior.
- Never use the experimental score as canonical rank or allocation reward.
- Keep citations and biological liabilities visible with target priors.
- Synthetic/stub designs keep their existing provenance banner; a meta-score
  over fabricated input remains fabricated evidence.

## Next validation steps

1. Export deployable normalization statistics and a signed model manifest from
   `binder-scorer` if exact `B_LLM` parity is required.
2. Add the structure-derived epitope-contact features proposed by the LLM.
3. Resolve target/PDB identity conflicts across benchmark fixtures and copy.
4. Expand metric-blind wet-lab labels to roughly 200 targets if the observed
   variance persists and a 0.035 lift remains the target effect.
5. Only consider canonical ranking after a preregistered held-out evaluation
   has a confidence interval whose lower bound clears zero.
