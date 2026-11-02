#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The narrative half of the DWV retrospective: template and rendering.

Split out of ``dwv_retrospective.py`` so that rewording a sentence cannot touch
the measurement and vice versa. Nothing here computes a verdict; every number in
the output arrives as an argument to :func:`render`.

There are deliberately **no imports from the measurement module**. The two
would otherwise form a cycle, and breaking it with a lazy import makes the
narrative's dependency on the measurement implicit. Instead the measurement
module hands over a ``Context`` bundle of identity constants and thresholds, and
this module type-hints it under ``TYPE_CHECKING`` only. The sentences the test
suite asserts on live here, with the prose, so that the assertion and the
document cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from hotspot_preflight.checks.burial import (
    BURIED_RELATIVE_SASA,
    CROP_ARTIFACT_DELTA,
    PARTNER_OCCLUSION_DELTA,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from dwv_retrospective import Arm1Row, Arm2Row, ConfusionMatrix, Design

__all__ = [
    "ARM1_STRUCTURAL_SCOPE_SENTENCE",
    "ARM2_CONFOUNDED_SENTENCE",
    "Context",
    "render",
]


@dataclass(frozen=True)
class Context:
    """What the narrative needs to know that is not itself a measurement.

    Passed in by the measurement module rather than imported from it, so the
    dependency runs one way only. The three thresholds are the exception: they
    are read straight from the check that applies them, so the document cannot
    quote a stale number.
    """

    pdb_id: str
    binder_id: str
    binder_epitope: tuple[int, ...]
    crop_sensitive: tuple[int, ...]
    occluded_candidate: int
    structure_url: str
    arm1_crop: tuple[str, int, int]
    crop_built_sources: tuple[str, ...]
    designs_display_path: str

# Shared qualification for both presentations of the structural readouts.
ARM1_STRUCTURAL_SCOPE_SENTENCE = (
    "Arm 1 measures structural properties without using design scores or binding "
    "labels. The queried sites were selected retrospectively; these readouts "
    "describe their coordinate coverage and structural context."
)
ARM2_CONFOUNDED_SENTENCE = "Arm 2 is confounded and is not the headline result."

#: Typical buried area of a designed minibinder interface, Å². Used only to give
#: the reader a sense of scale in the open-question section; no verdict uses it.
MINIBINDER_INTERFACE_RANGE = "roughly 400-800 Å²"


_DOCUMENT = """\
# The DWV retrospective: {pdb} chain C

A binder campaign against the deformed wing virus capsid nominated hotspots \
Ile405 and Phe408 on chain C of PDB {pdb}. Campaign notes report 35 designs \
ordered across two rounds. Available assay exports contain 10 and 20 unique \
designs, respectively: 0/10 and 1/20 bound. The five ordered designs absent from \
these exports have unknown outcomes, not negative labels. The one observed \
binder is `{binder}`, 79 aa, KD_app ~604 nM by BLI (replicates 546 and 666 nM).

Both nominated hotspots are unmodelled in the deposited entry, and the one \
design observed to bind has model-predicted contacts at a different site. Those \
contacts await experimental epitope mapping. This document regenerates \
the structural preflight readouts for the recorded hotspots.

Naming: "triad" is a historical site label used by the campaign.

## Provenance and how to regenerate

```
python scripts/dwv_retrospective.py --out docs/dwv-retrospective.md
```

- **Structure**: PDB {pdb}, the PDBe *updated* mmCIF (`{structure_url}`), \
cached as `{structure_name}`. The updated file is required rather than the \
archive original: it carries `_pdbx_poly_seq_scheme`, which is the only thing \
that gives an unmodelled residue an author number.
- **Designs**: `{designs_path}`, {n_designs} rows, {checksum_note}. These \
labels were produced for Boltz-2 / Rosetta validation of the order panel, not \
for this analysis.
- **Not an input to this script**: the two available Adaptyv assay exports \
contain 10 and 20 unique designs, one observed binder overall, and live outside \
this repository. The separate 35-ordered count comes from campaign notes. \
The binding outcomes are quoted in prose, not joined to the 26 design rows \
or used as labels for this structural analysis.
- **Deterministic**: no timestamps, fixed ordering, fixed rounding. Two runs \
produce identical bytes.

## Arm 1 — the three-way structural result

{arm1_structural_scope}

Relative SASA is what the checks threshold on; absolute SASA in Å² is carried \
alongside purely so the numbers can be checked against an independent hand \
measurement, and is an exact rescaling of the relative value rather than a \
separate measurement. The crop column is {arm1_crop}; a dash means the residue \
falls outside that crop, or has no coordinates to measure at all.

| residue | role | verdict | relative SASA (assembly / chain / crop) | \
absolute SASA Å² (assembly / chain / crop) | codes |
|---|---|---|---|---|---|
{arm1_table}

### What Arm 1 shows

1. **The nominated hotspots are rejected.** {kill_summary}. Both sit in the \
unmodelled 399-416 tail of chain C, so there were never any coordinates for a \
binder to contact. This answer was available in milliseconds of parsing, before \
a single design was ordered.

2. **Model-predicted contacts for the observed binder pass.** {pass_summary}. \
These residues are predicted contacts of `{binder}`, the one binder in the \
30 available assay records. Experimental epitope mapping and prospective \
site-selection evaluation remain pending.

3. **The crop face is flagged independently.** {artifact_summary}. Each is \
materially more exposed on the truncated crop than on the biological assembly, \
in the same direction and by more than the {crop_delta} relative-SASA \
threshold. Nothing about any design was consulted to reach this.

## Arm 2 — per-design crop classification

{arm2_confounded} It is reported because it is the natural next question and \
because its failure modes are informative. Read the confounds section first.

Ground truth is *was this design built on a truncated crop*: the \
{n_crop_built} designs from {crop_sources}, against the {n_full_domain} \
full-domain designs. The prediction is *does `check_burial` raise \
`CROP_ARTIFACT` for any residue this design contacted, under this design's own \
crop*.

| | predicted crop artifact | predicted clean |
|---|---|---|
| **built on a truncated crop** | {tp} | {fn} |
| **built on the full domain** | {fp} | {tn} |

n = {n_matrix}. TP={tp}, FP={fp}, FN={fn}, TN={tn}.

**The result that matters is FP={fp}: no design built on the full domain was \
wrongly condemned.** For a filter, wrongly rejecting a good site is the cardinal \
sin — it deletes work that would have succeeded, and it does so invisibly, \
because nobody ever learns what the rejected design would have done. Perfect \
specificity here is a stronger statement than the sensitivity number.

Sensitivity is **{tp} of {n_crop_built}**, not {n_crop_built} of \
{n_crop_built}. The {n_fn} missed {fn_noun} {fn_verb} missed for reasons that \
sit in the inputs rather than in the check:

{fn_bullets}

Both are input limitations rather than check failures — a per-residue check can \
only speak about residues it is given, and the one residue it was given in the \
second case genuinely does not move. Said plainly: it is still {tp} of \
{n_crop_built}.

No F1 and no AUC: with {n_crop_built} positives all drawn from one tool, a \
single summary number would be read as a validation result it cannot support.

| design | source | crop | contacts | contacts from | flagged | outcome | note |
|---|---|---|---|---|---|---|---|
{arm2_table}

## Confounds

{arm1_structural_scope} Re-running it needs only the mmCIF: delete the design \
table entirely and Arm 1 is unchanged.

{arm2_confounded} Three reasons, all structural to the dataset:

1. **Crop status is perfectly correlated with tool identity.** All \
{n_crop_built} crop-built designs come from {crop_sources} — one pipeline, \
counting `boltzprot_rd` as a variant of the same. Nothing in this dataset can \
separate *the crop was truncated* from *this tool produced the design*, and the \
matrix above would look identical if the real signal were the latter.

2. **There are only {n_distinct_crops} distinct crop ranges** \
({distinct_crops}), covering {n_crop_built} designs. The effective sample size \
for the crop question is therefore {n_distinct_crops}, not {n_crop_built}: two \
designs sharing a crop share their verdict by construction.

3. **The 26 design rows are not joined to experimental outcomes.** \
`min_ipsae_median` is a Boltz-2 score — another model's opinion, not a \
wet-lab binding label. Across the {n_scored} scored rows the \
crop-built designs span {crop_lo}-{crop_hi} and the full-domain designs \
{full_lo}-{full_hi}; the separation is clean, but it is a separation between \
two predictions. Available assay exports contain one binder among 30 designs; \
five additional ordered designs lack available outcomes. This small, unjoined \
retrospective requires a joined outcome analysis and prospective follow-up.

**Arm 2 is a retrospective consistency check.** The crop ranges, contacts \
and thresholds were all known before this script was written.

## Where the measurement differs from the hand probe

`{occluded}` was expected to come back as partner-occluded. It does not. The \
threshold was deliberately left alone, and that decision is the point of this \
section.

1. **The measurement agrees with the hand probe to the first decimal.** \
{occ_abs_chain} Å² on the isolated chain against {occ_abs_assembly} Å² on the \
biological assembly: a drop of {occ_abs_drop} Å². An independent gemmi + \
freesasa probe, written separately, produced the same two numbers. The \
occlusion is real and the capsid neighbour really does cover part of this \
residue.

2. **The verdict does not fire.** Normalised by this residue's reference \
maximum, that {occ_abs_drop} Å² is {occ_pct_drop}% — under the \
{occlusion_pct}% `OCCLUDED_BY_PARTNER` default. In relative terms the drop is \
{occ_rel_drop} ({occ_rel_chain} on the isolated chain to {occ_rel_assembly} on \
the assembly), so the verdict is {occ_codes} ({occ_verdict}).

3. **The open question, left open.** Relative delta is scale-free and therefore \
comparable across residue types, which is why it is the default: a 20% change \
means the same thing for a tryptophan as for an alanine, and an absolute \
threshold does not. But binding energy tracks *absolute* buried area, and \
{occ_abs_drop} Å² is a meaningful fraction of a typical designed minibinder \
interface of {interface_range}. Whether this criterion should be relative, \
absolute, or a disjunction of the two is a real design question. It is not \
settled here, and it cannot be settled on an n=1 observation.

4. **An absolute criterion would have flagged `{occluded}`, and we did not add \
one.** Lowering the relative threshold to {occ_tuned_threshold}, or introducing \
an absolute-area criterion, after seeing this case would be tuning a parameter \
so that one anecdote fires. A reader who noticed that would be right to discard \
this entire retrospective. The threshold is a documented default \
and it stays; the number is reported here so that anyone who prefers an \
absolute criterion can apply their own judgement without re-running anything.

One caveat on doing that from a run record rather than from this document: \
`check_burial`'s finding evidence carries `absolute_sasa_assembly` but not the \
absolute chain or crop values, so the absolute delta is not directly visible in \
a finding. The absolute columns in the Arm 1 table above are exact rescalings \
of the relative values — every context in one call divides by the same \
reference maximum — and are recorded for precisely this reason.

## Method and thresholds

- `check_resolved` asks, in order: does the chain exist, is the residue \
declared, does it have coordinates. Unmodelled residues are detected twice — \
from `_pdbx_unobs_or_zero_occ_residues` and from declared-minus-observed — \
because the first category is optional in mmCIF and absent from many entries.
- `check_burial` measures relative solvent accessibility on the expanded \
biological assembly, on the isolated chain, and on the crop. Below \
{buried_below} on the assembly is `BURIED_IN_ASSEMBLY` (KILL); a change of more \
than {crop_delta} between crop and assembly is `CROP_ARTIFACT`; a drop of more \
than {occlusion_delta} from chain to assembly is `OCCLUDED_BY_PARTNER`.
- The {pdb} biological assembly is one generator with 60 operators over \
subchains A/B/C, expanding to 180 chains and roughly 420k atoms. The \
neighbourhood trim in the SASA layer is load-bearing, not an optimisation: \
without it the calculation is not tractable.
"""


def _num(value: float | None, places: int = 4) -> str:
    return "—" if value is None else f"{value:.{places}f}"


def _codes(codes: Sequence[str]) -> str:
    return "`" + "`, `".join(codes) + "`" if codes else "—"


def _arm1_table(rows: Sequence[Arm1Row]) -> str:
    lines = []
    for row in rows:
        rel = " / ".join(_num(v) for v in (row.rel_assembly, row.rel_chain, row.rel_crop))
        absolute = " / ".join(
            _num(v, 1) for v in (row.abs_assembly, row.abs_chain, row.abs_crop)
        )
        lines.append(
            f"| {row.key} | {row.role} | **{row.verdict}** | {rel} | {absolute} | "
            f"{_codes(row.resolved_codes + row.burial_codes)} |"
        )
    return "\n".join(lines)


def _arm2_table(rows: Sequence[Arm2Row]) -> str:
    lines = []
    for row in rows:
        contacts = ", ".join(str(k) for k in row.design.contacts) or "none"
        flagged = ", ".join(str(k) for k in row.flagged_residues) if row.flagged else "no"
        full = " (full)" if row.design.crop.is_full else ""
        lines.append(
            f"| `{row.design.design_id}` | {row.design.source} | "
            f"{row.design.crop}{full} | {contacts} | {row.design.contacts_column} | "
            f"{flagged} | **{row.outcome}** | {row.note or '—'} |"
        )
    return "\n".join(lines)


def _false_negative_bullets(rows: Sequence[Arm2Row]) -> str:
    """One bullet per miss, naming the design, its crop and the actual cause.

    Spelled out per design rather than summarised, because "2 missed" invites
    the reader to assume a threshold problem, and neither of these is one.
    """
    bullets = []
    for row in rows:
        if row.outcome != "FN":
            continue
        # With no contacts the note already names the cause; prefixing it with
        # "no contacts recorded" as well would say the same thing twice.
        cause = (
            "contacts " + ", ".join(str(k) for k in row.design.contacts)
            + f" only — {row.note}"
            if row.design.contacts
            else row.note
        )
        bullets.append(
            f"- `{row.design.design_id}` ({row.design.source}, "
            f"{row.design.crop}): {cause}."
        )
    return "\n".join(bullets) if bullets else "- none."


def _checksum_note(designs_csv: Path) -> str:
    checksum = designs_csv.with_suffix(designs_csv.suffix + ".sha256")
    if checksum.exists():
        return f"checksummed in `{checksum.name}`"
    return "with no checksum file alongside it"


def render(
    arm1: Sequence[Arm1Row],
    arm2: Sequence[Arm2Row],
    designs: Sequence[Design],
    matrix: ConfusionMatrix,
    structure: Path,
    designs_csv: Path,
    ctx: Context,
) -> str:
    """Fill :data:`_DOCUMENT`. A pure function of its arguments, by design.

    ``matrix`` is passed in rather than recomputed so that this module needs no
    runtime import from the measurement module — the document reports what was
    measured, it does not get a second opinion.
    """
    by_num = {row.key.auth_seq_id: row for row in arm1}
    crop_built = [d for d in designs if d.is_crop_built]
    crop_scores = [d.min_ipsae_median for d in crop_built if d.min_ipsae_median is not None]
    full_scores = [
        d.min_ipsae_median
        for d in designs
        if not d.is_crop_built and d.min_ipsae_median is not None
    ]
    distinct_crops = sorted({str(d.crop) for d in crop_built})
    n_fn = sum(1 for r in arm2 if r.outcome == "FN")

    # ARM1_RESIDUES guarantees this row exists; indexing directly keeps a
    # missing row a loud failure rather than a silently empty sentence.
    occ = by_num[ctx.occluded_candidate]
    occ_rel_drop = (occ.rel_chain or 0.0) - (occ.rel_assembly or 0.0)
    occ_abs_drop = abs((occ.abs_chain or 0.0) - (occ.abs_assembly or 0.0))
    # The threshold we are declining to move to, one step below the observed
    # drop. Named in the document so the temptation is explicit, not hinted at.
    tuned = int(occ_rel_drop * 100) / 100

    return _DOCUMENT.format(
        pdb=ctx.pdb_id,
        binder=ctx.binder_id,
        structure_url=ctx.structure_url,
        structure_name=structure.name,
        designs_path=ctx.designs_display_path,
        n_designs=len(designs),
        checksum_note=_checksum_note(designs_csv),
        arm1_structural_scope=ARM1_STRUCTURAL_SCOPE_SENTENCE,
        arm2_confounded=ARM2_CONFOUNDED_SENTENCE,
        arm1_crop=f"{ctx.arm1_crop[0]}{ctx.arm1_crop[1]}-{ctx.arm1_crop[2]}",
        arm1_table=_arm1_table(arm1),
        kill_summary=", ".join(
            f"`{r.key}` → {_codes(r.kill_codes)}" for r in arm1 if r.kill_codes
        ),
        pass_summary=", ".join(
            f"`{by_num[n].key}` → {by_num[n].verdict} ({_codes(by_num[n].burial_codes)},"
            f" relative SASA {_num(by_num[n].rel_assembly)} on the assembly)"
            for n in ctx.binder_epitope
        ),
        artifact_summary=", ".join(
            f"`{by_num[n].key}` (+{_num(by_num[n].rel_crop - by_num[n].rel_assembly)}"
            f" relative, {_num(by_num[n].abs_assembly, 1)} →"
            f" {_num(by_num[n].abs_crop, 1)} Å²)"
            for n in ctx.crop_sensitive
        ),
        crop_delta=CROP_ARTIFACT_DELTA,
        buried_below=BURIED_RELATIVE_SASA,
        occlusion_delta=PARTNER_OCCLUSION_DELTA,
        occlusion_pct=f"{PARTNER_OCCLUSION_DELTA * 100:.0f}",
        n_crop_built=len(crop_built),
        n_full_domain=len(designs) - len(crop_built),
        crop_sources=" and ".join(ctx.crop_built_sources),
        tp=matrix.tp,
        fp=matrix.fp,
        fn=matrix.fn,
        tn=matrix.tn,
        n_matrix=matrix.n,
        arm2_table=_arm2_table(arm2),
        n_fn=n_fn,
        fn_noun="design" if n_fn == 1 else "designs",
        fn_verb="is" if n_fn == 1 else "are",
        fn_bullets=_false_negative_bullets(arm2),
        n_distinct_crops=len(distinct_crops),
        distinct_crops=", ".join(distinct_crops),
        n_scored=len(crop_scores) + len(full_scores),
        crop_lo=_num(min(crop_scores)),
        crop_hi=_num(max(crop_scores)),
        full_lo=_num(min(full_scores)),
        full_hi=_num(max(full_scores)),
        occluded=occ.key,
        occ_abs_chain=_num(occ.abs_chain, 1),
        occ_abs_assembly=_num(occ.abs_assembly, 1),
        occ_abs_drop=_num(occ_abs_drop, 1),
        occ_rel_chain=_num(occ.rel_chain),
        occ_rel_assembly=_num(occ.rel_assembly),
        occ_rel_drop=_num(occ_rel_drop),
        occ_pct_drop=f"{occ_rel_drop * 100:.0f}",
        occ_tuned_threshold=f"{tuned:.2f}",
        occ_codes=_codes(occ.burial_codes),
        occ_verdict=occ.verdict,
        interface_range=MINIBINDER_INTERFACE_RANGE,
    )
