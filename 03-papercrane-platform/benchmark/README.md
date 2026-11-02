# Paper Crane Binder Design Benchmark

A pre-registered, reproducible, head-to-head benchmark of *in silico*
protein binder design tools.

## What This Is

The Paper Crane benchmark evaluates binder-design tools (BindCraft,
RFdiffusion+ProteinMPNN, BoltzGen, etc.) on a standardized set of
therapeutically-relevant targets under matched compute environments,
using pre-registered hit criteria and statistical procedures. Results
are cost-adjusted, bootstrap-stabilized, and reproducible from signed
run manifests.

## Versioning

- **Methodology** is versioned as `methodology-vX.Y.md`. The current
  authoritative spec is [`methodology-v1.0.md`](methodology-v1.0.md).
- **Targets** are defined in [`targets/`](targets/). Adding or
  modifying a target bumps the methodology version (see
  [`targets/README.md`](targets/README.md)).
- Every methodology file is git-signed with a maintainer GPG key.
  Commit hashes are published on every leaderboard page so any
  historical result can be traced to the exact methodology text under
  which it was scored.
- Old methodology versions and old leaderboards remain immutable and
  published — they are never edited or removed.

## Structure

```
benchmark/
  methodology-v1.0.md        # authoritative pre-registered spec
  targets/                   # target YAML files (one per target)
    pd-l1.yaml
    sars-cov2-rbd.yaml
    il-7ra.yaml
    README.md                # target schema + PR workflow
  GOVERNANCE.md              # advisory panel, CoI, disputes
  CITATION.cff               # citation metadata
  README.md                  # this file
  migrate/                   # (owned by another agent)
  manifests/                 # signed per-cell run manifests (populated at run time)
```

## Quick Start

1. Read the methodology: [`methodology-v1.0.md`](methodology-v1.0.md).
2. Pick a target from [`targets/`](targets/).
3. Run your tool under the specified seed range (§5) and produce a
   signed run manifest (§11).
4. Submit via pull request following [`GOVERNANCE.md`](GOVERNANCE.md).

## Key Design Principles

- **Pre-registration.** Thresholds and procedures are fixed before any
  tool is scored. Retrospective threshold tuning is explicitly
  disallowed; see methodology §3, §7.
- **Reproducibility.** Every cell is identified by a 6-tuple
  (target, tool, version, config, seeds, compute-env) and produces a
  signed manifest sufficient to re-run independently.
- **Cost-adjusted.** Primary headline metric is
  `hit_rate / mean_cost_usd_per_design` (methodology §10), so tools
  cannot "win" by throwing compute at the problem.
- **External governance.** A rotating 3-person external advisory
  panel reviews submissions and methodology changes
  ([`GOVERNANCE.md`](GOVERNANCE.md)).

## Citation

If you use this benchmark in published work, cite it using the metadata
in [`CITATION.cff`](CITATION.cff). BibTeX and other formats can be
generated from the `.cff` file via
[cffconvert](https://github.com/citation-file-format/cffconvert) or
GitHub's "Cite this repository" button.

## License

The benchmark specification, target YAMLs, and scoring code are
released under terms to be confirmed at v1.0 publication. Tool outputs
and submissions remain under their authors' licenses.

## See Also

- [`methodology-v1.0.md`](methodology-v1.0.md) — authoritative spec
- [`targets/README.md`](targets/README.md) — target schema + workflow
- [`GOVERNANCE.md`](GOVERNANCE.md) — review and dispute process
- [`CITATION.cff`](CITATION.cff) — citation metadata
