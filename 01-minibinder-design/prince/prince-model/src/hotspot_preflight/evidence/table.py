# SPDX-License-Identifier: MIT
"""The curated evidence table, and the review gate that guards it.

LLM literature work fails in two ways. A fabricated citation is the obvious one,
and at least detectable. The quieter and more expensive one is faithfully
repeating a claim the literature never established.

This project has already paid for the second. The DWV protruding-domain
"catalytic triad" (Asp294-His277-Ser278) is described in Skubnik et al., PNAS
2017 — which hedges it as *putative* and concedes "the distances between the
side chains of the residues are larger than ideal for catalyzing a hydrolytic
reaction". Our own measurement on 5G51 found no donor-acceptor pair anywhere in
the hydrogen-bond window, and the only functional assay ever attempted on the
homologous site (Kalynych et al., PNAS 2017) was negative. We targeted it
anyway. Designs reached 0.854 ``min_ipSAE`` and none of them bound.

A retrieval system asked "is Asp294 functionally important?" returns the PNAS
sentence and says yes. So retrieval is not what this does: it reads a
version-controlled table where every row carries a DOI or PMID, an
``evidence_class``, a direction and a ``reviewed`` flag — and only reviewed rows
can influence a verdict.

The gate has two layers. The filter in :func:`check_evidence` is the policy;
:func:`verdict_findings` raises :class:`UnreviewedRowError` on an unreviewed row,
so a refactor routing around it fails loudly. Curation: ``data/evidence/README.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..findings import Finding, Severity, sort_findings
from ..residue import HotspotParseError, ResidueKey, parse_hotspot_spec

__all__ = [
    "CHECK_NAME",
    "BUNDLED_TABLE_DIR",
    "EvidenceClass",
    "Direction",
    "EvidenceRow",
    "EvidenceTableError",
    "UnreviewedRowError",
    "load_table",
    "row_from_mapping",
    "rows_for",
    "strongest",
    "verdict_findings",
    "check_evidence",
]

CHECK_NAME = "evidence"
"""The ``check`` field on every Finding this module returns."""

#: Curated tables shipped with the repo. Four parents up from this file.
BUNDLED_TABLE_DIR = Path(__file__).resolve().parents[3] / "data" / "evidence"


class EvidenceClass(str, Enum):
    """What kind of claim a row is, ordered strongest first.

    The ordering is the point: "a paper says these residues look like a triad"
    and "an assay found no activity" are not the same kind of statement, and a
    table treating them as interchangeable reproduces the exact error this
    module exists to prevent.
    """

    FUNCTIONAL_ASSAY = "FUNCTIONAL_ASSAY"
    MUTAGENESIS = "MUTAGENESIS"
    STRUCTURAL_OBSERVATION = "STRUCTURAL_OBSERVATION"
    CONSERVATION = "CONSERVATION"
    ASSERTION = "ASSERTION"

    @property
    def strength(self) -> int:
        """Higher wins. Derived from declaration order, so it cannot desync."""
        members = list(type(self))
        return len(members) - members.index(self)

    @property
    def is_assayed(self) -> bool:
        """True when a wet experiment stands behind the claim — the dividing
        line for ``EVIDENCE_SUPPORTED``. Conservation and a structural
        observation are real findings, but neither tested anything.
        """
        return self in (EvidenceClass.FUNCTIONAL_ASSAY, EvidenceClass.MUTAGENESIS)


class Direction(str, Enum):
    """Whether the row argues for or against functional relevance."""

    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"


class EvidenceTableError(ValueError):
    """A table could not be loaded. Always names the offending row."""


class UnreviewedRowError(RuntimeError):
    """An unreviewed row reached the verdict path.

    A broken invariant, not a user-facing error: if this is raised in production
    the review gate has been refactored around and the module is no longer doing
    the one job it was built for.
    """


# A DOI is "10." then a 4-9 digit registrant, a slash, and a non-empty suffix.
# Optional doi:/URL prefixes are accepted because that is what people paste.
_DOI_RE = re.compile(
    r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?10\.\d{4,9}/\S+$", re.IGNORECASE
)
_PMID_RE = re.compile(r"^pmid:?\s*\d{1,9}$", re.IGNORECASE)
_BARE_NUMBER_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class EvidenceRow:
    """One literature claim about one or more residues.

    Args:
        residues: in author numbering. A triad is one row naming three
            residues, not three rows: the claim is about the constellation, and
            splitting it lets the three drift apart under editing.
        claim: what the source says, in the source's own hedging. "may
            constitute a putative triad" must not be flattened to "is a triad".
        source: DOI or PMID, required and shape-validated at load, because a
            claim nobody can chase is indistinguishable from one we made up.
        evidence_class: what kind of claim this is. See :class:`EvidenceClass`.
        direction: does it support or refute functional relevance.
        reviewed: has a human accepted it. Only ``True`` rows affect a verdict.
        notes: caveats that must travel with the row — numbering regime,
            homologue-versus-target, measured geometry that disagrees.
        reviewer: who accepted it; required when ``reviewed``, so acceptance is
            an attributable act and not an anonymous flag flip.
    """

    residues: tuple[ResidueKey, ...]
    claim: str
    source: str
    evidence_class: EvidenceClass
    direction: Direction
    reviewed: bool
    notes: str = ""
    reviewer: str = ""

    def covers(self, key: ResidueKey) -> bool:
        return key in self.residues

    @property
    def residue_spec(self) -> str:
        """The residues as a human writes them, e.g. ``C277,C278,C294``."""
        return ",".join(str(k) for k in self.residues)


def _describe(raw: Any) -> str:
    """Identify a row in an error message by its claim.

    A curator fixing a load error has to find the row, and a row index is
    useless the moment rows are reordered.
    """
    if isinstance(raw, dict):
        claim = raw.get("claim")
        if isinstance(claim, str) and claim.strip():
            return f"row {claim.strip()!r}"
    return f"row {raw!r}"


def _validate_source(source: Any, where: str) -> str:
    """Reject anything not DOI- or PMID-shaped, naming what was given.

    A bare integer is refused rather than read as a PMID, the same policy as
    ``parse_hotspot_spec`` refusing a chainless number: guessing is how
    unverifiable provenance gets in.
    """
    if source is None or not str(source).strip():
        raise EvidenceTableError(
            f"{where} has no source. Every row needs a DOI (10.xxxx/yyyy) or a "
            f"PMID (PMID:12345678): a claim nobody can look up cannot be "
            f"distinguished from one that was invented."
        )
    text = str(source).strip()
    if _DOI_RE.match(text) or _PMID_RE.match(text):
        return text
    if _BARE_NUMBER_RE.match(text):
        raise EvidenceTableError(
            f"{where} has source {text!r}, a bare number. Write "
            f"'PMID:{text}' if that is what you mean — we will not guess "
            f"which identifier namespace a number belongs to."
        )
    raise EvidenceTableError(
        f"{where} has source {text!r}, which is neither DOI-shaped "
        f"(10.xxxx/yyyy) nor PMID-shaped (PMID:12345678). A free-text "
        f"citation cannot be verified, so it is not accepted."
    )


def _validate_enum(raw: Any, enum: type, field: str, where: str) -> Any:
    text = str(raw).strip().upper() if raw is not None else ""
    try:
        return enum(text)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in enum)
        raise EvidenceTableError(
            f"{where} has {field} {raw!r}; allowed values are {allowed}"
        ) from exc


def _parse_residues(raw: Any, where: str) -> tuple[ResidueKey, ...]:
    if raw is None or (isinstance(raw, (list, tuple)) and not raw):
        raise EvidenceTableError(
            f"{where} names no residues. A claim about nothing cannot be "
            f"matched to a hotspot."
        )
    tokens = raw if isinstance(raw, (list, tuple)) else [raw]
    spec = ",".join(str(t).strip() for t in tokens)
    try:
        keys = parse_hotspot_spec(spec)
    except HotspotParseError as exc:
        raise EvidenceTableError(f"{where} has unparseable residues: {exc}") from exc
    return tuple(keys)


def row_from_mapping(raw: Any) -> EvidenceRow:
    where = _describe(raw)
    if not isinstance(raw, dict):
        raise EvidenceTableError(f"{where} is not a mapping")

    claim = str(raw.get("claim", "")).strip()
    if not claim:
        raise EvidenceTableError(
            f"{where} has no claim. State what the source says, in the "
            f"source's own hedging."
        )

    reviewed = raw.get("reviewed", False)
    if not isinstance(reviewed, bool):
        raise EvidenceTableError(f"{where} reviewed must be a YAML boolean, not text or a number")
    reviewer = str(raw.get("reviewer", "") or "").strip()
    if reviewed and not reviewer:
        raise EvidenceTableError(
            f"{where} is marked reviewed: true but names no reviewer. "
            f"Accepting a row into the verdict path is an attributable act."
        )

    return EvidenceRow(
        residues=_parse_residues(raw.get("residues"), where),
        claim=claim,
        source=_validate_source(raw.get("source"), where),
        evidence_class=_validate_enum(
            raw.get("evidence_class"), EvidenceClass, "evidence_class", where
        ),
        direction=_validate_enum(raw.get("direction"), Direction, "direction", where),
        reviewed=reviewed,
        notes=str(raw.get("notes", "") or "").strip(),
        # Dropped rather than kept on an unreviewed row: a reviewer name with
        # reviewed: false is a half-finished edit, and carrying it forward
        # makes the row look vetted in a report.
        reviewer=reviewer if reviewed else "",
    )


def load_table(path: str | Path) -> list[EvidenceRow]:
    """Load and fully validate one YAML evidence table.

    Strict and total: the first bad row aborts the load, because a half-loaded
    table leaves rows silently absent from the verdict.

    Raises:
        EvidenceTableError: on a missing file, malformed YAML, or any row with
            missing or unverifiable provenance. The message names the row.
    """
    import yaml  # imported here so a YAML-less install can still import this

    p = Path(path)
    if not p.is_file():
        raise EvidenceTableError(f"no evidence table at {p}")

    try:
        doc = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:
        raise EvidenceTableError(f"{p} is not valid YAML: {exc}") from exc

    if not isinstance(doc, dict):
        raise EvidenceTableError(
            f"{p} must be a mapping with a 'rows' key, got {type(doc).__name__}"
        )

    raw_rows = doc.get("rows")
    if raw_rows is None:
        raise EvidenceTableError(f"{p} has no 'rows' key")
    if not isinstance(raw_rows, list):
        raise EvidenceTableError(f"{p} 'rows' must be a list")

    rows: list[EvidenceRow] = []
    for raw in raw_rows:
        try:
            rows.append(row_from_mapping(raw))
        except EvidenceTableError as exc:
            raise EvidenceTableError(f"{p}: {exc}") from exc
    return rows


def rows_for(rows: Iterable[EvidenceRow], key: ResidueKey) -> list[EvidenceRow]:
    """Every row whose residue list contains ``key``, in table order."""
    return [r for r in rows if r.covers(key)]


def strongest(rows: Sequence[EvidenceRow]) -> list[EvidenceRow]:
    """The rows tied at the highest ``evidence_class`` strength.

    Every row at that strength, not one arbitrary winner, so a REFUTES tied
    with a SUPPORTS is visible rather than decided by table order.
    """
    if not rows:
        return []
    top = max(r.evidence_class.strength for r in rows)
    return [r for r in rows if r.evidence_class.strength == top]


def _site_finding(code: str, message: str, evidence: dict[str, Any]) -> Finding:
    """A WARN about the table's coverage of the site, not about one residue.

    ``key=None`` so these sort last, and so no residue appears to own a
    statement that is really about what the table contains.
    """
    return Finding(
        check=CHECK_NAME,
        severity=Severity.WARN,
        code=code,
        message=message,
        key=None,
        evidence=evidence,
    )


def _grade(key: ResidueKey, covering: Sequence[EvidenceRow]) -> Finding:
    """Grade one residue from the reviewed rows that cover it.

    A refutation tied at the top strength beats a support, deliberately:
    claiming function where an assay found none costs a design campaign, while
    the reverse costs only a missed opportunity.

    ASSERTION, CONSERVATION and STRUCTURAL_OBSERVATION all grade to
    ``EVIDENCE_WEAK``: they share the one property that matters here, that
    nobody tested anything.
    """
    top = strongest(covering)
    refutes = [r for r in top if r.direction is Direction.REFUTES]
    row = refutes[0] if refutes else top[0]

    if refutes:
        code, severity = "EVIDENCE_REFUTED", Severity.WARN
        message = (
            f"{key}: the strongest reviewed evidence refutes its functional "
            f"relevance — {row.evidence_class.value} in {row.source} "
            f'("{row.claim}"). Do not use function-blocking as a design '
            f"rationale for this site."
        )
    elif row.evidence_class.is_assayed:
        code, severity = "EVIDENCE_SUPPORTED", Severity.PASS
        message = (
            f"{key}: reviewed {row.evidence_class.value} support in "
            f'{row.source} ("{row.claim}").'
        )
    else:
        code, severity = "EVIDENCE_WEAK", Severity.WARN
        message = (
            f"{key}: the only reviewed support is {row.evidence_class.value} "
            f"({row.source}) — an assertion in a paper is not an assayed "
            f"result, and neither is conservation or a structural observation. "
            f"Nothing here has been tested."
        )

    # The full provenance rides along as evidence, so a reader can disagree with
    # our grading, and trace a refutation to the paper that refuted it.
    return Finding(
        check=CHECK_NAME,
        severity=severity,
        code=code,
        message=message,
        key=key,
        evidence={
            "source": row.source,
            "evidence_class": row.evidence_class.value,
            "direction": row.direction.value,
            "claim": row.claim,
            "notes": row.notes,
            "reviewer": row.reviewer,
            "residues": row.residue_spec,
            "n_reviewed_rows": len(covering),
        },
    )


def verdict_findings(
    keys: Sequence[ResidueKey],
    reviewed_rows: Sequence[EvidenceRow],
) -> list[Finding]:
    """Per-residue findings from rows that have **already** been filtered.

    Split out from :func:`check_evidence` so the gate exists twice: a filter
    there, an enforced precondition here.

    Raises:
        UnreviewedRowError: if any row is unreviewed. Refusing is the design —
            an unreviewed claim must not reach a verdict even by mistake.
    """
    offenders = [r for r in reviewed_rows if not r.reviewed]
    if offenders:
        raise UnreviewedRowError(
            f"{len(offenders)} unreviewed row(s) reached the verdict path "
            f"(first: {offenders[0].claim!r}). Unreviewed evidence must be "
            f"filtered out before grading; see check_evidence()."
        )

    findings: list[Finding] = []
    for key in keys:
        covering = rows_for(reviewed_rows, key)
        if not covering:
            # Deliberately silent per residue. Coverage is reported once, at
            # site level, so an empty table cannot flood a report with N
            # copies of the same warning.
            continue
        findings.append(_grade(key, covering))
    return findings


def check_evidence(
    target: Any,
    keys: Sequence[ResidueKey],
    rows: Sequence[EvidenceRow],
) -> list[Finding]:
    """Grade the requested residues against the curated table.

    Args:
        target: the loaded structure, accepted only to keep every check's
            signature uniform, and **deliberately unused**: this check reads
            literature, never coordinates, and must never emit a structural
            verdict that the resolved/burial/numbering checks own. ``None`` is
            valid, and is what the tests pass.
        keys: the hotspot residues under consideration.
        rows: every row in the table, reviewed and unreviewed alike. The filter
            happens here, once.

    Returns:
        Findings in ``sort_findings`` order; site-level findings sort last.
    """
    del target  # see the docstring: uniform signature, no structural input

    if not keys:
        return []

    # The review gate. Everything below this line sees reviewed rows only.
    reviewed = [r for r in rows if r.reviewed]
    unreviewed = [r for r in rows if not r.reviewed]

    findings = verdict_findings(keys, reviewed)

    if not any(rows_for(reviewed, k) for k in keys):
        findings.append(
            _site_finding(
                "NO_EVIDENCE",
                f"No reviewed literature evidence covers any of the "
                f"{len(keys)} requested residue(s). Functional evidence for "
                f"this site remains unknown; review the literature and add "
                f"attributed rows when available.",
                {
                    "n_requested": len(keys),
                    "n_reviewed_rows": len(reviewed),
                    "residues": ",".join(str(k) for k in keys),
                },
            )
        )

    # Only unreviewed rows relevant to *these* residues. Rows about other
    # residues were not excluded from this verdict in any meaningful sense, so
    # counting them would overstate how much is pending for this site.
    pending = [r for r in unreviewed if any(r.covers(k) for k in keys)]
    if pending:
        findings.append(
            _site_finding(
                "UNREVIEWED_EVIDENCE_PRESENT",
                f"{len(pending)} unreviewed evidence row(s) cover these "
                f"residues and were excluded from the verdict — they did not "
                f"affect it. A human must accept a row (reviewed: true with a "
                f"reviewer) before it can count.",
                {
                    "n_unreviewed": len(pending),
                    "n_unreviewed_in_table": len(unreviewed),
                    "claims": [r.claim for r in pending],
                    "sources": [r.source for r in pending],
                },
            )
        )

    return sort_findings(findings)
