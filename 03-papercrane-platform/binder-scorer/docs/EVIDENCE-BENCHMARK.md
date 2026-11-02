# Fixed-budget evidence benchmark

This runner evaluates supplied, frozen computational scores against existing
outcome labels. It does not train, select, or calibrate models. It uses the
evidence-audit contract and has no additional dependencies.

## Run

From `binder-scorer`:

```sh
python -m scorer.evidence_benchmark examples/evidence-benchmark.demo.json --top-k 1 --output benchmark-demo.json
```

The example contains invented scores and outcomes for three independent demo
groups. It establishes software behavior only. The JSON report is explicitly
labelled `synthetic_demo` and is not evidence of model performance.

The destination parent directory must exist. An existing output file is never
overwritten. `--seed` defaults to 0 and `--bootstrap-samples` to 5000. Repeating
the same input and configuration produces byte-identical results.

Python API:

```python
from pathlib import Path
from scorer.evidence_audit_cli import load_input
from scorer.evidence_benchmark import evaluate_benchmark

report = evaluate_benchmark(
    load_input(Path("examples/evidence-benchmark.demo.json")), top_k=1
)
```

## Input

Use the complete demo JSON as a template. Required fields:

- `schema_version`: `evidence-benchmark-input.v1`.
- `benchmark_id`: a stable descriptive identifier.
- `baseline_method_id`: the declared comparator, present in every campaign.
- `development_groups`: group identifiers used for development or model selection.
- `campaigns`: entries containing `evaluation_group`, `evidence`, and `outcomes`.

`evidence` is a complete [evidence audit input](EVIDENCE-AUDIT.md).
`outcomes` explicitly maps every supplied candidate ID to `true`, `false`, or
`null`. Unknown outcomes must be null. Strings, integer encodings, omitted IDs,
and extra IDs are rejected.

An evaluation group should capture dependency, such as repeated campaigns for
the same target or related targets. Assigning each campaign its own group when
they are dependent overstates independent evidence. Evaluation groups cannot
overlap declared development groups. Campaign IDs must be unique; method
definitions, including settings, must agree across campaigns. Use the method
settings field for policy/model artifact hashes where available. Synthetic and
research campaigns cannot be mixed.

The runner checks declarations, not their historical truth. It cannot discover
upstream training leakage, hidden prompt tuning, sequence homology, or falsely
declared groups. Those require dataset and artifact audits before a final study.

## Endpoints and exclusions

Ranks and the common evidence cohort are computed before outcomes are read.
Every method uses the same cohort. The primary endpoint is Precision@k with a
fixed requested k. Campaigns whose common cohort is smaller than k remain in
the report but do not enter primary comparisons. There is no outcome-dependent
choice of k.

A campaign with any unknown outcome in the common cohort is excluded from the
primary comparison. The runner does not discard unknown-labelled candidates
and rerank the remaining pool. Unknown outcomes outside the evidence cohort
do not enter the metric computation. The resulting estimand is conditional on
the common cohort; it is not an estimate for all generated candidates.

Zero-positive campaigns remain eligible for precision. Recall and NDCG are null
when no positives exist. No minimum positive count is used to remove difficult
campaigns. Recall and NDCG are reported per campaign; the headline aggregation
is group-macro Precision@k.

Exact ties crossing the cutoff are averaged over uniform tie orderings. The
report also supplies the minimum and maximum possible Precision@k under those
ties. These are ordering bounds, not sampling confidence intervals. NDCG uses
the expected binary gain over each tied block.

## Aggregation and inference

The runner averages campaign precision within each declared group, then weights
groups equally. It bootstraps paired group-level precision differences against
the declared baseline using a seeded percentile bootstrap. It does not resample
individual candidates as if they were independent targets.

With fewer than two eligible groups, no sampling interval is reported. A
constant empirical difference distribution is labelled degenerate, even when
its empirical interval has zero width. Neither that interval nor a small-group
bootstrap establishes certainty about new campaigns. Group independence and
representativeness remain assumptions.

No automatic winner, equivalence verdict, power estimate, or multiple-comparison
claim is emitted. Freeze a primary comparison and analysis protocol before
examining final evaluation outcomes.

The agreement diagnostic separately measures observed outcomes among candidates
that all methods place inside top-k. It exposes the possibility that methods
agree and are wrong together. This selected-subset fraction is not calibrated
confidence and is not a replacement for comparisons at the same shortlist size.

## Verification

```sh
python -m pytest scorer/tests/test_evidence_benchmark.py -q
```

Tests include cutoff ties, fixed-budget exclusions, zero positives, unknown
labels, correlated campaign groups, a single-group interval, shared incorrect
rankings, method drift, development overlap, reproducibility, and CLI output
protection.
