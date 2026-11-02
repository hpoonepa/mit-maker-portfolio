#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Measure the deformed-wing-virus retrospective. One command, no human steps.

    python scripts/dwv_retrospective.py --out docs/dwv-retrospective.md

The campaign specified hotspots Ile405 and Phe408 on chain C of PDB 6F5J, ordered
35 designs across two rounds, and got one binder (``l79_s469532_mpnn9``, 79 aa,
KD_app ~604 nM by BLI). Both hotspots sit in the unmodelled 399-416 tail.

**Arm 1** measures eight residues through :func:`check_resolved` and
:func:`check_burial` in three structural contexts; every row is a per-residue
structural fact about the deposited entry, so there is nothing for a confound to
attach to. **Arm 2** asks per design whether the tool would have flagged that
design's own contacts under its own crop — a weaker claim, stated as such.

The narrative lives in ``dwv_retrospective_report.py``, so rewording a sentence
cannot touch the measurement. Output is deterministic and diffable.
"""

from __future__ import annotations

import csv
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import typer

REPO_ROOT = Path(__file__).resolve().parents[1]
# Runnable as `python scripts/dwv_retrospective.py` without an editable install,
# which is the point of "one command regenerates it". This directory goes on the
# path too, so the sibling report module resolves however this file was loaded.
for _entry in (str(REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from hotspot_preflight.checks.burial import (  # noqa: E402
    BURIED_RELATIVE_SASA,
    CROP_ARTIFACT_DELTA,
    PARTNER_OCCLUSION_DELTA,
    check_burial,
)
from hotspot_preflight.checks.resolved import check_resolved  # noqa: E402
from hotspot_preflight.findings import Finding, SiteReport, sort_findings  # noqa: E402
from hotspot_preflight.residue import ResidueKey  # noqa: E402
from hotspot_preflight.structure import Target, load_target  # noqa: E402

__all__ = [
    "CropRangeError", "CropSpec", "Design", "Arm1Row", "Arm2Row", "generate",
    "ConfusionMatrix", "parse_crop_range", "parse_epitope_residues", "confusion",
    "load_designs", "run_burial", "build_arm1", "build_arm2",
]

PDB_ID = "6F5J"
TARGET_CHAIN = "C"
STRUCTURE_URL = "https://www.ebi.ac.uk/pdbe/entry-files/download/6f5j_updated.cif"

DEFAULT_STRUCTURE = REPO_ROOT / ".cache" / "6f5j_updated.cif"
DEFAULT_DESIGNS = REPO_ROOT / "data" / "designs_VALIDATED_full_metrics.csv"
DEFAULT_OUT = REPO_ROOT / "docs" / "dwv-retrospective.md"

#: The crop Arm 1 compares against: the one that actually shipped designs.
ARM1_CROP: tuple[str, int, int] = (TARGET_CHAIN, 310, 398)
#: Arm 2's ground truth. A property of the tool, not of the structure — which
#: is exactly the confound the generated document is required to confess.
CROP_BUILT_SOURCES = frozenset({"boltzprot", "boltzprot_rd"})
#: ``(auth_seq_id, role)`` for Arm 1, ordered by number so the rendered table
#: is stable without a sort at render time.
ARM1_RESIDUES: tuple[tuple[int, str], ...] = (
    (277, 'part of the putative "triad" site'),
    (325, "model-predicted contact of the observed binder"),
    (326, "model-predicted contact of the observed binder"),
    (359, "neighbour on the crop-cut face"),
    (384, "contacted by the crop-built designs"),
    (395, "neighbour on the crop-cut face"),
    (405, "original campaign hotspot (Ile405)"),
    (408, "original campaign hotspot (Phe408)"),
)
#: Expected to open up on the crop, and expected to be covered by a capsid
#: neighbour. Named so the narrative can reference them by role.
CROP_SENSITIVE = (359, 384, 395)
OCCLUDED_CANDIDATE = 277
BINDER_ID = "l79_s469532_mpnn9"
BINDER_EPITOPE = (325, 326)


def _display_path(path: Path) -> str:
    """Repo-relative if possible, bare name otherwise — for display only."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _log(message: str) -> None:
    """Progress to stderr only. Tests must never depend on our stdout."""
    print(message, file=sys.stderr, flush=True)



class CropRangeError(ValueError):
    """A ``design_crop_pdb_range`` cell could not be read unambiguously."""


# `260-416 (full)` and `300-398`. The parenthesised note is free text in the
# source table, so it is captured and inspected rather than matched exactly.
_CROP_RE = re.compile(r"^(?P<first>\d+)\s*-\s*(?P<last>\d+)(?:\s*\((?P<note>[^)]*)\))?$")


@dataclass(frozen=True)
class CropSpec:
    """One design's target truncation, in author numbering.

    ``is_full`` is read from the cell's note, not inferred from the span: "full"
    is the claim under test, and deriving it would make the test circular.
    """

    chain: str
    first: int
    last: int
    is_full: bool

    @property
    def as_range(self) -> tuple[str, int, int]:
        """The ``crop_range`` triple :func:`check_burial` consumes."""
        return (self.chain, self.first, self.last)

    def __str__(self) -> str:
        return f"{self.chain}{self.first}-{self.last}"


def parse_crop_range(raw: str, chain: str = TARGET_CHAIN) -> CropSpec:
    """Parse ``260-416 (full)``, ``300-398`` and friends.

    Raises:
        CropRangeError: on anything else, empty cells and backwards ranges
            included. A design whose crop cannot be read must not default to
            full-domain: that would move a row of the matrix on a parse failure.
    """
    text = (raw or "").strip()
    if not text:
        raise CropRangeError("empty crop range")
    match = _CROP_RE.match(text)
    if match is None:
        raise CropRangeError(f"could not parse crop range {raw!r}")
    first, last = int(match.group("first")), int(match.group("last"))
    if last < first:
        raise CropRangeError(f"crop range {raw!r} runs backwards ({first} to {last})")
    note = (match.group("note") or "").strip().lower()
    return CropSpec(chain, first, last, "full" in note)


def parse_epitope_residues(raw: str, chain: str = TARGET_CHAIN) -> tuple[ResidueKey, ...]:
    """Parse a slash-delimited contact list such as ``277/278/294``.

    Sorted and deduplicated, so the rendered table stays diffable.

    Raises:
        ValueError: on a non-numeric token rather than dropping it — a dropped
            contact makes a design look un-flaggable for an invisible reason.
    """
    nums: list[int] = []
    for token in (raw or "").split("/"):
        token = token.strip()
        if not token:
            continue
        try:
            nums.append(int(token))
        except ValueError as exc:
            raise ValueError(
                f"contact list {raw!r} holds non-numeric residue {token!r}"
            ) from exc
    return tuple(ResidueKey(chain, n) for n in sorted(set(nums)))


@dataclass(frozen=True)
class Design:
    """One ordered design, as the validated metrics table records it."""

    design_id: str
    source: str
    min_ipsae_median: float | None
    crop: CropSpec
    contacts: tuple[ResidueKey, ...]
    contacts_column: str

    @property
    def is_crop_built(self) -> bool:
        """Arm 2's ground truth: was this built against a truncated crop?"""
        return self.source in CROP_BUILT_SOURCES


def _optional_float(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"expected a number, got {raw!r}") from exc


def load_designs(path: Path, chain: str = TARGET_CHAIN) -> list[Design]:
    """Read the validated metrics CSV, preserving file order.

    Contacts come from ``b2_epitope_residues``, falling back to
    ``dt_epitope_residues`` when empty. Which column spoke is recorded on the
    row: the two predictors disagree, and a reader checking a surprising
    classification needs to know which one was used.
    """
    designs: list[Design] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for line_no, row in enumerate(csv.DictReader(handle), start=2):
            design_id = (row.get("design_id") or "").strip()
            if not design_id:
                raise ValueError(f"{path}:{line_no} has no design_id")
            try:
                crop = parse_crop_range(row.get("design_crop_pdb_range", ""), chain)
            except CropRangeError as exc:
                raise CropRangeError(f"{path}:{line_no} ({design_id}): {exc}") from exc

            contacts = parse_epitope_residues(row.get("b2_epitope_residues", ""), chain)
            column = "b2_epitope_residues"
            if not contacts:
                contacts = parse_epitope_residues(row.get("dt_epitope_residues", ""), chain)
                column = "dt_epitope_residues" if contacts else "none"

            designs.append(
                Design(
                    design_id=design_id,
                    source=(row.get("source") or "").strip(),
                    min_ipsae_median=_optional_float(row.get("min_ipsae_median", "")),
                    crop=crop,
                    contacts=contacts,
                    contacts_column=column,
                )
            )
    if not designs:
        raise ValueError(f"{path} holds no design rows")
    return designs



def ensure_structure(path: Path) -> Path:
    """Fetch the *updated* mmCIF once if it is not cached.

    The updated file, not the archive original: it carries
    ``_pdbx_poly_seq_scheme``, the only thing that gives an unmodelled residue
    an author number at all.
    """
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"downloading {PDB_ID} to {path}")
    try:
        urllib.request.urlretrieve(STRUCTURE_URL, path)
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"cannot download {PDB_ID} from {STRUCTURE_URL}: {exc}. "
            f"Place the file at {path} by hand and re-run."
        ) from exc
    return path


BurialIndex = dict[tuple[str, int, int], dict[ResidueKey, list[Finding]]]


def run_burial(
    target: Target, requests: Mapping[tuple[str, int, int], Iterable[ResidueKey]]
) -> BurialIndex:
    """Run :func:`check_burial` once per distinct crop, indexed by residue.

    Per crop, not per design: each call expands the 6F5J assembly (60 operators
    over subchains A/B/C, 180 chains, ~420k atoms), so 26 calls would redo that
    expansion 26 times for four distinct answers.
    """
    index: BurialIndex = {}
    for crop in sorted(requests):
        keys = sorted(set(requests[crop]))
        if not keys:
            continue
        _log(f"burial: crop {crop[0]}{crop[1]}-{crop[2]} over {len(keys)} residues")
        per_key: dict[ResidueKey, list[Finding]] = {}
        for finding in check_burial(target, keys, crop_range=crop):
            if finding.key is not None:
                per_key.setdefault(finding.key, []).append(finding)
        index[crop] = per_key
    return index


def _absolute_from_relative(
    relative: float | None, rel_assembly: float | None, abs_assembly: float | None
) -> float | None:
    """Recover an absolute SASA from a relative one.

    Exact, not approximate: every context in one ``check_burial`` call divides
    by the same reference maximum, so the ratio of two relative values is the
    ratio of the absolutes. For traceability only; no verdict uses them.
    """
    if relative is None or rel_assembly in (None, 0) or abs_assembly is None:
        return None
    return relative / rel_assembly * abs_assembly


@dataclass(frozen=True)
class Arm1Row:
    """One residue, measured in all three contexts, with its verdict."""

    key: ResidueKey
    role: str
    verdict: str
    resolved_codes: tuple[str, ...]
    burial_codes: tuple[str, ...]
    kill_codes: tuple[str, ...]
    rel_assembly: float | None
    rel_chain: float | None
    rel_crop: float | None
    abs_assembly: float | None
    abs_chain: float | None
    abs_crop: float | None


def build_arm1(
    target: Target,
    burial: BurialIndex,
    crop: tuple[str, int, int] = ARM1_CROP,
    residues: Sequence[tuple[int, str]] = ARM1_RESIDUES,
) -> list[Arm1Row]:
    """The three-way per-residue result.

    ``check_resolved`` runs once for the whole set — it walks the structure and
    two cif categories per call — and its site-level findings (such as
    ``NO_UNOBS_CATEGORY``) are excluded from the per-residue rows, since they
    describe the entry rather than the residue.
    """
    keys = [ResidueKey(crop[0], num) for num, _ in residues]
    _log(f"resolved: {len(keys)} residues on chain {crop[0]}")
    per_key: dict[ResidueKey, list[Finding]] = {}
    for finding in check_resolved(target, keys):
        if finding.key is not None:
            per_key.setdefault(finding.key, []).append(finding)

    rows: list[Arm1Row] = []
    for (_, role), key in zip(residues, keys):
        found = sort_findings(per_key.get(key, []) + burial[crop].get(key, []))
        report = SiteReport(findings=list(found))
        ev: Mapping[str, Any] = next(
            (f.evidence for f in found if "relative_sasa_assembly" in f.evidence), {}
        )
        rel_a = ev.get("relative_sasa_assembly")
        abs_a = ev.get("absolute_sasa_assembly")
        rel_c = ev.get("relative_sasa_chain")
        rel_x = ev.get("relative_sasa_crop")
        rows.append(
            Arm1Row(
                key, role, report.verdict.value,
                tuple(f.code for f in found if f.check == "resolved"),
                tuple(f.code for f in found if f.check == "burial"),
                tuple(report.kill_codes()),
                rel_a, rel_c, rel_x, abs_a,
                _absolute_from_relative(rel_c, rel_a, abs_a),
                _absolute_from_relative(rel_x, rel_a, abs_a),
            )
        )
    return rows


@dataclass(frozen=True)
class Arm2Row:
    """One design's predicted crop-artifact flag against its ground truth."""

    design: Design
    flagged: bool
    flagged_residues: tuple[ResidueKey, ...]
    note: str

    @property
    def outcome(self) -> str:
        if self.design.is_crop_built:
            return "TP" if self.flagged else "FN"
        return "FP" if self.flagged else "TN"


@dataclass(frozen=True)
class ConfusionMatrix:
    """Raw counts, and deliberately nothing derived.

    No precision, recall, F1 or AUC. With 7 positives all drawn from one tool,
    any single summary number would be read as a validation result it cannot
    support, so the document is given the four counts and nothing to round.
    """

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn


NO_CONTACTS_NOTE = (
    "no contacted residues recorded by either predictor, so a per-residue check "
    "has nothing to judge"
)
NO_CHANGE_NOTE = "no contacted residue changed materially under this crop"


def build_arm2(designs: Sequence[Design], burial: BurialIndex) -> list[Arm2Row]:
    """Per design: would the tool have flagged this design's own contacts?

    A design with no recorded contacts cannot be flagged by a per-residue check
    and is counted as a negative, with the reason written into the row. Dropping
    such rows would quietly improve the matrix by deleting its hardest cases.
    """
    rows: list[Arm2Row] = []
    for design in designs:
        if not design.contacts:
            rows.append(Arm2Row(design, False, (), NO_CONTACTS_NOTE))
            continue
        per_key = burial[design.crop.as_range]
        hits = tuple(
            key
            for key in design.contacts
            if any(f.code == "CROP_ARTIFACT" for f in per_key.get(key, []))
        )
        rows.append(Arm2Row(design, bool(hits), hits, "" if hits else NO_CHANGE_NOTE))
    return rows


def confusion(rows: Sequence[Arm2Row]) -> ConfusionMatrix:
    counts = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}
    for row in rows:
        counts[row.outcome] += 1
    return ConfusionMatrix(counts["TP"], counts["FP"], counts["FN"], counts["TN"])



def generate(
    structure_path: Path = DEFAULT_STRUCTURE,
    designs_csv: Path = DEFAULT_DESIGNS,
    crop: tuple[str, int, int] = ARM1_CROP,
) -> str:
    """Run both arms and return the rendered document."""
    # Imported here, not at module scope: the report module is the consumer of
    # everything defined above it, so a top-level import would be a cycle.
    from dwv_retrospective_report import Context, render

    structure_path = ensure_structure(Path(structure_path))
    designs_csv = Path(designs_csv)
    _log(f"loading {structure_path}")
    target = load_target(structure_path)
    designs = load_designs(designs_csv, chain=crop[0])
    n_crop = sum(d.is_crop_built for d in designs)
    _log(f"{len(designs)} designs: {n_crop} crop-built, {len(designs) - n_crop} full")

    requests: dict[tuple[str, int, int], set[ResidueKey]] = {
        crop: {ResidueKey(crop[0], num) for num, _ in ARM1_RESIDUES}
    }
    for design in (d for d in designs if d.contacts):
        requests.setdefault(design.crop.as_range, set()).update(design.contacts)

    burial = run_burial(target, requests)
    arm1 = build_arm1(target, burial, crop=crop)
    arm2 = build_arm2(designs, burial)
    matrix = confusion(arm2)
    _log(f"arm 2: TP={matrix.tp} FP={matrix.fp} FN={matrix.fn} TN={matrix.tn}")
    return render(
        arm1, arm2, designs, matrix, structure_path, designs_csv,
        Context(
            PDB_ID, BINDER_ID, BINDER_EPITOPE, CROP_SENSITIVE,
            OCCLUDED_CANDIDATE, STRUCTURE_URL, crop,
            tuple(sorted(CROP_BUILT_SOURCES)), _display_path(designs_csv),
        ),
    )


app = typer.Typer(add_completion=False)


@app.command()
def main(
    out: Path = typer.Option(DEFAULT_OUT, help="Markdown file to write."),
    structure: Path = typer.Option(DEFAULT_STRUCTURE, help="mmCIF; fetched if absent."),
    designs: Path = typer.Option(DEFAULT_DESIGNS, help="Validated metrics CSV."),
) -> None:
    """Regenerate the DWV retrospective write-up."""
    document = generate(structure_path=structure, designs_csv=designs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
    _log(f"wrote {out} ({len(document)} bytes)")


if __name__ == "__main__":
    app()
