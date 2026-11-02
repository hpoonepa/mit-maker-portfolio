# SPDX-License-Identifier: MIT
"""Running the checks, and rendering them for a human.

Turns one site's findings into the two things a person reads — a text report and
a CSV — and builds the :class:`~hotspot_preflight.record.PreflightRun` that
:mod:`hotspot_preflight.record` serialises. Nothing here prints: the CLI prints,
the tests assert on returned strings, and a function that did both could serve
only one of them.

The run record itself, its schema and its provenance machinery live in
:mod:`hotspot_preflight.record`, because what a run *was* is a deliverable in its
own right rather than a detail of running one. The names are re-exported below so
that ``from hotspot_preflight.report import to_run_record`` keeps working.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .checks.burial import check_burial
from .checks.numbering import check_numbering, translate_for_tools
from .checks.patch import check_patch_geometry
from .checks.resolved import check_resolved
from .evidence import check_evidence
from .findings import Finding, Severity, SiteReport, sort_findings
from .record import (
    DISTRIBUTION_NAME,
    RUN_RECORD_VERSION,
    RUN_SPECIFIC_PARAMETER_KEYS,
    PreflightRun,
    _reference_id,
    _thresholds,
    file_digest,
    load_schema,
    sasa_parameters,
    to_run_record,
)
from .residue import ResidueKey
from .structure import Target

__all__ = [
    # Owned here.
    "CHECK_ORDER", "CSV_COLUMNS", "run_preflight", "render_text", "write_csv",
    "select_assembly",
    # Re-exported from .record so existing imports keep working. The record is
    # that module's deliverable; this list is a convenience, not a second home.
    "RUN_RECORD_VERSION", "DISTRIBUTION_NAME", "RUN_SPECIFIC_PARAMETER_KEYS",
    "PreflightRun", "to_run_record", "sasa_parameters", "file_digest",
    "load_schema",
]

CHECK_ORDER = ("resolved", "numbering", "burial", "patch")
"""Default run order, and the order the record names them in.

``resolved`` first because a residue with no coordinates makes every later
measurement meaningless; ``patch`` last because it judges the set as a shape.
``evidence`` is deliberately absent — it reads literature, not coordinates, and
is meant to be ablatable, so it runs only when a table is supplied.
"""

CSV_COLUMNS = (
    "target_id", "residue", "chain", "auth_seq_id", "icode",
    "check", "severity", "code", "message", "evidence_json",
)

def select_assembly(target: Target, assembly_id: str | None) -> str | None:
    """Make ``assembly_id`` the assembly the burial check will expand.

``check_burial`` always expands ``target.st.assemblies[0]`` and takes
    no assembly argument, so choosing another means reordering the list in
    place. Doing it here keeps that coupling in one documented place.

    Returns the name now in use, or ``None`` when the entry declares none.

    Raises:
        ValueError: if the entry declares no assembly but one was named, or not
            the one requested. Falling back to the deposited first assembly
            would answer a question the user did not ask.
    """
    names = [a.name for a in target.st.assemblies]
    if assembly_id is None:
        return names[0] if names else None
    if assembly_id not in names:
        raise ValueError(
            f"{target.entry_id} has no biological assembly named "
            f"{assembly_id!r}; it declares: {', '.join(names) or 'none'}"
        )
    items = list(target.st.assemblies)
    target.st.assemblies = [a for a in items if a.name == assembly_id] + [
        a for a in items if a.name != assembly_id
    ]
    return assembly_id




def run_preflight(
    target: Target,
    keys: Sequence[ResidueKey],
    *,
    crop_range: tuple[str, int, int] | None = None,
    hotspot_spec: str = "",
    patch: bool = True,
    evidence_rows: Sequence[Any] | None = None,
) -> PreflightRun:
    """Run every enabled check against one site and collect the result.

    Args:
        target: loaded structure, from ``structure.load_target``. To measure
            burial on a specific assembly, pass it through
            :func:`select_assembly` first.
        keys: hotspot residues in canonical author numbering.
        crop_range: ``(chain, first, last)``, inclusive, or ``None``.
        hotspot_spec: the specification as typed, recorded verbatim.
        patch: run the patch-geometry check. On by default; off reproduces the
            three-check output that predates it.
        evidence_rows: curated literature rows from
            ``evidence.load_table``, or ``None`` to skip the check. Opt-in
            because the component is meant to be ablatable — it must never
            influence a default run, so that a verdict can always be attributed
            to coordinates alone.

    Raises:
        ValueError: on an empty key list, or a crop range that is backwards, on
            an unknown chain, or holding no observed residues. These are the
            caller's mistakes, so they are raised rather than reported — a
            finding would imply the check had run.
    """
    if not keys:
        raise ValueError("no hotspot residues to check")
    keys = list(keys)

    findings: list[Finding] = []
    findings.extend(check_resolved(target, keys))
    findings.extend(check_numbering(target, keys))
    ran = ["resolved", "numbering"]

    # check_burial raises on a hotspot whose chain does not exist, while
    # check_resolved explains it properly — listing the chains present and
    # flagging a letter-case mismatch. Skipping those keys keeps the better
    # message instead of collapsing the whole run into one usage error.
    present = set(target.chain_ids)
    burial_keys = [k for k in keys if k.auth_asym_id in present]
    if burial_keys:
        findings.extend(check_burial(target, burial_keys, crop_range=crop_range))
        ran.append("burial")

    if patch:
        # Judged on the asymmetric unit, the same context check_burial reports
        # as "chain". An expanded assembly would call a site contiguous because
        # it straddles two copies of one chain, which is true of the crystal and
        # not of the single-chain crop a campaign actually designs against.
        findings.extend(check_patch_geometry(target, keys))
        ran.append("patch")

    if evidence_rows is not None:
        findings.extend(check_evidence(target, keys, evidence_rows))
        ran.append("evidence")

    findings = sort_findings(findings)
    sasa = sasa_parameters()
    sasa["reference_id"] = _reference_id(findings)

    return PreflightRun(
        report=SiteReport(findings),
        target_id=target.entry_id,
        assembly_id=(
            target.st.assemblies[0].name if len(target.st.assemblies) else None
        ),
        hotspot_spec=hotspot_spec,
        keys=keys,
        crop_range=crop_range,
        tool_formats=translate_for_tools(target, keys),
        parameters={
            "checks": ran,
            "thresholds": _thresholds(),
            "sasa": sasa,
        },
        input_digest=file_digest(target.path),
        input_filename=Path(target.path).name,
    )




def _noun(count: int) -> str:
    return "hotspot residue" if count == 1 else "hotspot residues"


def _headline(run: PreflightRun) -> list[str]:
    count = len(run.keys)
    spec = run.hotspot_spec or ",".join(str(k) for k in run.keys)
    line = f"{run.target_id}: {count} {_noun(count)} from {spec!r}"
    if run.assembly_id is not None:
        line += f", biological assembly {run.assembly_id}"
    if run.crop_range is not None:
        line += ", crop {}{}-{}".format(*run.crop_range)
    return [f"VERDICT: {run.verdict_value}", line, ""]


def _display_sort_key(finding: Finding) -> tuple[Any, ...]:
    """Residue order, then worst severity first within a residue.

    Deliberately not :func:`sort_findings`, which orders by check name and so
    would print a residue's WARN above its KILL. The canonical order still
    governs the run record; the report leads with the deciding line.
    """
    key = finding.key
    return (
        key is None,
        "" if key is None else key.auth_asym_id,
        0 if key is None else key.auth_seq_id,
        "" if key is None else key.icode,
        -finding.severity.rank,
        finding.check,
        finding.code,
    )


def _reportable(finding: Finding) -> bool:
    """Whether a finding gets its own line rather than being counted.

    Anything above PASS does. So does a **site-level** PASS, labelled NOTE: the
    count summary is per residue, so a finding about the whole entry has no count
    to be folded into, and dropping it would silently lose the advice it carries.
    ``HOTSPOT_COUNT_UNUSUAL`` is the case that matters — it is PASS precisely
    because it must not move a verdict, but a user still needs to read it.
    """
    return finding.severity is not Severity.PASS or finding.key is None


def _flagged_lines(findings: Iterable[Finding]) -> list[str]:
    """One line per reportable finding, grouped by residue, worst first.

    Messages are used verbatim rather than re-worded from the code: the checks
    already phrase the cause in plain words, and a copy here would go stale.
    """
    lines = []
    for finding in sorted(filter(_reportable, findings), key=_display_sort_key):
        if finding.key is not None:
            label, where = finding.severity.value, str(finding.key)
        else:
            # PASS at site level reads as a note, not as a verdict on the site.
            passed = finding.severity is Severity.PASS
            label = "NOTE" if passed else finding.severity.value
            where = "(whole entry)"
        lines.append(
            f"{label} {where}: {finding.message} [{finding.check}/{finding.code}]"
        )
    return lines


def render_text(run: PreflightRun) -> str:
    """The human-facing report, returned as a string.

    Leads with the verdict, because that is the decision. Then one line per
    reportable finding (see :func:`_reportable`); passing residues are counted,
    not listed, since a wall of PASS lines buries the one KILL that matters. Ends
    with the per-tool hotspot strings. No colour or emoji: this is read in CI
    logs and pasted into notebooks.
    """
    lines = _headline(run)
    flagged = _flagged_lines(run.report.findings)
    if flagged:
        lines.extend(flagged)
        lines.append("")

    total = len(run.keys)
    clean = total - len(run.flagged_keys())
    lines.append(f"{clean} of {total} {_noun(total)} passed every check.")

    lines.extend(["", "Hotspot strings for your design tool:"])
    width = max((len(name) for name in run.tool_formats), default=0)
    for name, value in run.tool_formats.items():
        lines.append(f"  {name.ljust(width)}  {value}")
    return "\n".join(lines) + "\n"


def write_csv(run: PreflightRun, path: str | Path) -> None:
    """Write one row per finding, PASS rows included.

    PASS rows are kept because the CSV feeds the benchmark, which scores
    reasons rather than verdicts and needs to see what was cleared, not only
    what failed. ``evidence`` is one JSON column: the keys differ per check, and
    a union of them all would be a sparse table nobody can read.
    """
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for finding in run.report.findings:
            data = finding.to_dict()
            key = finding.key
            writer.writerow([
                run.target_id,
                data["residue"] or "",
                data["chain"] or "",
                "" if data["auth_seq_id"] is None else data["auth_seq_id"],
                key.icode if key is not None and key.has_icode else "",
                data["check"],
                data["severity"],
                data["code"],
                data["message"],
                json.dumps(data["evidence"], sort_keys=True),
            ])
