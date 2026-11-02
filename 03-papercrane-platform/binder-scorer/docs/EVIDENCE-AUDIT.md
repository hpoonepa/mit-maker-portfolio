# Evidence Atlas: supplied-ranking audit

The first working component of the research selector workbench. It compares
candidate rankings supplied by researchers, audits attribution and missingness,
and exports reproducible evidence. It does not train a new binder model or
generate a composite score.

## Run the demonstration

From the `binder-scorer` directory, with Python 3.10 or newer:

```sh
python -m scorer.evidence_audit_cli examples/evidence-audit.demo.json --top-k 2 --output-dir artifacts/my-first-audit
```

No additional packages, network, API key, LLM, GPU, or external service are
required. Output directories must be new; the CLI refuses to overwrite any
existing directory. Use a different output path on subsequent runs.

The bundled example is entirely synthetic and is labelled as such in the input,
JSON output, and HTML report. Its seven candidates demonstrate agreement,
method disagreement, exact ties, incomplete evidence, and unknown provenance.
Five candidates enter its common comparison cohort.

Outputs:

| File | Purpose |
|---|---|
| `report.html` | Portable report, readable locally without a server or external assets |
| `report.json` | Complete machine-readable audit, including raw supplied scores and method settings |
| `candidates.csv` | Candidate-level assessment and descriptive rank envelopes |
| `manifest.json` | Input/configuration identity and SHA-256 hashes of the three output artifacts |

Reports omit wall-clock timestamps so identical normalized inputs and settings
produce byte-identical bundles. The input hash is over canonical JSON with
methods and candidates sorted by ID, rather than over the original file bytes.

## Python API

```python
from pathlib import Path
from scorer.evidence_audit import build_audit
from scorer.evidence_audit_cli import load_input, export_bundle

evidence = load_input(Path("examples/evidence-audit.demo.json"))
report = build_audit(evidence, top_k=2)
export_bundle(report, Path("artifacts/my-python-audit"))
```

`build_audit` is a pure function. It does not access the existing prior cache,
datasets, labels, model clients, structure files, or application database.

## Evidence contract

Use `examples/evidence-audit.demo.json` as a complete template. The required
top-level fields are `schema_version`, `campaign_id`, `data_kind`, `methods`,
and `candidates`. Unknown fields and duplicate IDs are rejected. The CLI also
rejects duplicate JSON keys and nonfinite JSON numbers.

Use `schema_version: "evidence-audit-input.v1"`. `data_kind` is `research` or
`synthetic_demo`.

Each method declares:

- `id`: unique score identifier.
- `producer` and `version`: the tool/model that supplied the score.
- `evidence_family`: a grouping for methods likely to share evidence or errors.
- `higher_is_better`: explicit boolean score direction.
- `units`: recorded scale; use `unitless` when appropriate.
- `settings`: a JSON object recording relevant run settings.

Family assignments come from the researcher. Different family names do not
prove independence. Repeated runs or related scores from one producer should
not masquerade as independent families.

Each candidate declares `id`, `origin`, `provenance`, and `scores`.
`provenance` is required and is one of:

- `recorded`: the supplier attests that this is attributed research evidence.
- `unknown`: attribution is insufficient; always excluded from comparison.
- `synthetic`: excluded in research mode; allowed only in explicitly labelled demonstrations.

Recorded provenance is an assertion, not an independent verification. The audit
never silently upgrades missing provenance to recorded.

Every candidate must include an observation object for every declared method:

```json
{"status": "observed", "value": 0.8}
```

or, for an unobserved score:

```json
{"status": "failed", "reason": "Provider timeout"}
```

Other unobserved states are `missing` and `not_applicable`. All require a
nonempty reason and forbid a value. Zero is a valid observed value. Missing
keys are errors, rather than implicit zeros or implicit missing observations.

## Comparison semantics

1. Form the common cohort: candidates with permitted provenance and observed
   scores for every declared method.
2. Rank that same cohort separately with each supplied method and its declared
   score direction. Never combine incompatible raw score scales.
3. Preserve the whole occupied rank interval for exact ties. An ID does not
   decide whether a tied candidate crosses the top-k boundary.
4. Report each candidate's best–worst occupied rank over methods. This is a
   descriptive envelope, not a confidence interval or probability.
5. Classify agreement only when at least two evidence families are declared.
   No majority vote is used; duplicating a method cannot outvote another family.

| Assessment | Meaning within the common cohort |
|---|---|
| `consistently_in_top_k` | Every supplied method places the full tie interval inside top-k |
| `consistently_outside_top_k` | Every supplied method places the full tie interval outside top-k |
| `boundary_ambiguous` | Methods disagree across the cutoff, or an exact tie crosses it |
| `insufficient_comparison` | Complete evidence, but fewer than two declared families |
| `not_comparable` | Incomplete evidence and/or unverified provenance |

Excluded candidates are not assigned low ranks. All displayed ranks refer only
to the common cohort, whose membership is explicit. Re-run comparisons if the
cohort changes. If top-k is at least the cohort size, the report warns that the
cutoff cannot distinguish a smaller shortlist.

Pairwise method agreement uses Jaccard overlap of top-k sets. It is unavailable
when an exact tie crosses the cutoff or the cohort is empty. The report also
shows observation counts and cohort retention by source, to expose systematic
exclusion from missing evidence. Complete-case comparisons can still be biased;
this tool does not estimate or correct that bias.

## Verification

```sh
python -m pytest scorer/tests/test_evidence_audit.py -q
```

Tests cover score direction, cutoff ties, all unobserved states, provenance,
shared families, duplicated methods, monotonic score transformations, record
permutations, empty cohorts, invalid observations, export hashes, overwrite
protection, HTML escaping, and spreadsheet formula neutralization.

## Remaining research milestones

The [fixed-budget benchmark runner](EVIDENCE-BENCHMARK.md) now evaluates supplied
scores against existing outcome labels. See the [development gates](plans/2026-09-08-selector-development.md)
for the sequence from these diagnostics to an evaluated model.

This release implements evidence contracts, descriptive ranking diagnostics,
source coverage, local export, and a reproducible demonstration. It does not
establish improved binder recovery, calibrated uncertainty, novelty, or compute
savings. Existing scorer implementations and their historical results are
unchanged and are not automatically imported into this report.

The next milestones remain separate, measurable research tasks:

1. Export frozen, attributed predictions from the existing benchmark and align
   the research/application scoring artifacts. Preserve all model and prompt
   training exclusions and make missingness visible.
2. Correct inferential reporting: separate significance, equivalence, and power
   planning; use fixed shortlist sizes and audits of target/source overlap.
3. Evaluate whether descriptive disagreement predicts actual ranking errors on
   untouched campaigns. Use held-out outcomes; agreement alone is insufficient.
4. Add calibrated uncertainty only after specifying and testing its assumptions.
5. Evaluate computational assessment allocation through offline replay with
   hidden metrics, recorded costs, strong scheduling controls, and frozen splits.

No performance or statistical guarantee is implied by completing this software
foundation. Published claims require the corresponding held-out evaluations.
