# Benchmark Targets

This directory contains the authoritative target YAML files for the Paper
Crane binder design benchmark. Each target is one file (`<slug>.yaml`), and
the file is the canonical record of that target's structural input,
hotspots, classification, and baseline difficulty.

## Schema

Every target YAML conforms to the following schema:

```yaml
id: <slug>                       # kebab-case, matches filename
pdb: <PDB ID>                    # 4-char RCSB PDB identifier
chain: <letter>                  # single-letter target chain
hotspots: [list of residue nums] # integer residue numbers, author numbering
hotspot_rationale: |
  <literature or computational justification>
class: <cytokine_receptor|viral_antigen|...>
tier: <easy|medium|hard|very_hard>
baseline_hit_rate: <float 0-1>   # measured baseline for reference tool
added: <ISO date>
added_by: <submitter>
version: 1                       # target schema version, bumps on edits
```

The `id` MUST equal the filename stem. The `version` integer bumps whenever
any structural field changes (PDB, chain, hotspots), which invalidates
cached fingerprints (see methodology §4).

## Adding a New Target

New targets are added by pull request under the following workflow:

1. **Open a PR** that adds exactly one new `<slug>.yaml` file in this
   directory. Do not bundle multiple targets into a single PR.
2. **Literature-sourced rationale is required.** The `hotspot_rationale`
   field must cite at least one peer-reviewed publication or preprint that
   justifies the hotspot selection (e.g. co-crystal structure, alanine
   scan, deep mutational scan, or published interface analysis).
   Hand-waved or purely computational rationales (e.g. "top-5 by SASA")
   are rejected; a published analysis linking the residues to function or
   binding energy is required.
3. **Tier claim requires baseline evidence.** The `tier` and
   `baseline_hit_rate` fields must be supported by either a prior
   internal benchmark run or a citation; unsupported claims are rejected.
4. **7-day public comment window.** Once the PR is opened and passes CI,
   it enters a mandatory 7-calendar-day public comment period. The PR
   cannot be merged during this window even with maintainer approval.
   This is to allow community feedback on target selection, which is a
   scientifically consequential decision (see `../GOVERNANCE.md`).
5. **Review requirements.** At least two Paper Crane maintainers AND at
   least one external advisory panel member must approve the PR after
   the comment window closes.
6. **Methodology version bump.** Adding a target bumps the methodology
   minor version (e.g. v1.0 → v1.1). The PR must include the
   corresponding `methodology-vX.Y.md` file created from the previous
   version with the target added to §2. The old methodology file is
   **never** deleted or modified.

## Removing or Modifying a Target

Targets are effectively immutable once published. If a target is found to
be erroneous (e.g. wrong chain, misnumbered hotspots, superseded PDB):

- **Do not edit the existing YAML file.** Existing leaderboard results
  are tied to its fingerprint.
- Open a PR that (a) marks the old target `deprecated: true` and (b)
  adds a new target (e.g. `pd-l1-v2.yaml`) with the corrected
  information. Follow the full new-target workflow above.
- The new target gets its own slug, its own baseline, and its own
  leaderboard column.

## Current Targets

| ID              | PDB  | Chain | Tier   | Baseline | Class                |
|-----------------|------|-------|--------|----------|----------------------|
| pd-l1           | 5O45 | A     | easy   | 0.42     | cytokine_receptor    |
| sars-cov2-rbd   | 6M0J | E     | medium | 0.29     | viral_antigen        |
| il-7ra          | 3UP1 | A     | hard   | 0.18     | cytokine_receptor    |

## See Also

- [`../methodology-v1.0.md`](../methodology-v1.0.md) — authoritative
  methodology spec (§2, §4).
- [`../GOVERNANCE.md`](../GOVERNANCE.md) — advisory panel, review
  workflow, dispute resolution.
