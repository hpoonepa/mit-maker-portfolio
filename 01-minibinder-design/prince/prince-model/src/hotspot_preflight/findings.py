# SPDX-License-Identifier: MIT
"""The shared vocabulary of check results.

Every check returns :class:`Finding` objects — never printed strings — so the
CLI, the JSON run record, the HTML report and the tests all read the same
values. A check that formats its own output cannot be asserted on cleanly and
cannot be re-rendered for a different consumer.

Each finding carries a machine-readable ``code`` and a human-readable
``message`` that names the cause. "Buried by chain B" is actionable; "score
0.03" is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .residue import ResidueKey

__all__ = [
    "Severity",
    "Verdict",
    "Finding",
    "SiteReport",
    "finding_sort_key",
    "sort_findings",
    "summarise",
]


class Severity(str, Enum):
    """How strongly a finding argues against using a site.

    ``str`` subclass so that it serialises to JSON as its own name without a
    custom encoder.
    """

    PASS = "PASS"
    WARN = "WARN"
    KILL = "KILL"

    @property
    def rank(self) -> int:
        return {"PASS": 0, "WARN": 1, "KILL": 2}[self.value]


class Verdict(str, Enum):
    """The overall recommendation for a site."""

    GO = "GO"
    GO_WITH_WARNINGS = "GO_WITH_WARNINGS"
    STOP = "STOP"


@dataclass(frozen=True)
class Finding:
    """One observation about one residue, or about the site as a whole.

    Args:
        check: which check produced this, e.g. ``"resolved"``, ``"burial"``.
        severity: PASS, WARN or KILL.
        code: stable machine-readable reason, e.g. ``"UNMODELLED"``. Stable
            because downstream tooling and the benchmark group on it; changing
            a code is a breaking change.
        message: one sentence a human can act on, naming the cause.
        key: the residue this concerns, or ``None`` for a site-level finding
            such as patch geometry.
        evidence: the numbers behind the verdict, so a reader can disagree with
            our thresholds without re-running anything.
    """

    check: str
    severity: Severity
    code: str
    message: str
    key: ResidueKey | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "residue": str(self.key) if self.key is not None else None,
            "chain": self.key.auth_asym_id if self.key is not None else None,
            "auth_seq_id": self.key.auth_seq_id if self.key is not None else None,
            "evidence": dict(self.evidence),
        }


@dataclass
class SiteReport:
    """All findings for one site, plus the aggregate verdict."""

    findings: list[Finding] = field(default_factory=list)

    def extend(self, more: Iterable[Finding]) -> None:
        self.findings.extend(more)

    @property
    def verdict(self) -> Verdict:
        """Worst-wins. Any KILL stops the site; any WARN qualifies it.

        Deliberately not a weighted score. A site with one fatal problem and
        nine clean checks is still unusable, and averaging would hide that.
        """
        worst = max((f.severity.rank for f in self.findings), default=0)
        return {0: Verdict.GO, 1: Verdict.GO_WITH_WARNINGS, 2: Verdict.STOP}[worst]

    def of_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]

    @property
    def kills(self) -> list[Finding]:
        return self.of_severity(Severity.KILL)

    @property
    def warnings(self) -> list[Finding]:
        return self.of_severity(Severity.WARN)

    def kill_codes(self) -> list[str]:
        """Distinct KILL codes, in first-seen order.

        This is the unit the benchmark scores: whether we produced the right
        *reason*, not merely the right yes/no.
        """
        seen: list[str] = []
        for f in self.kills:
            if f.code not in seen:
                seen.append(f.code)
        return seen

    def residues_killed(self) -> list[ResidueKey]:
        seen: list[ResidueKey] = []
        for f in self.kills:
            if f.key is not None and f.key not in seen:
                seen.append(f.key)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "n_kill": len(self.kills),
            "n_warn": len(self.warnings),
            "kill_codes": self.kill_codes(),
            "findings": [f.to_dict() for f in self.findings],
        }


def finding_sort_key(finding: Finding) -> tuple[int, str, int, str, str, str]:
    """Total order over findings: by residue, then check, then code.

    Site-level findings (``key is None``) sort last.

    The leading int is a group flag rather than the more obvious
    ``(finding.key is None, finding.key, ...)``, because that form compares
    ``None < None`` whenever two site-level findings meet. Today it survives
    only because tuple comparison short-circuits on equality — the moment a
    check emits two site-level codes it raises TypeError. Spelling the residue
    out as primitives keeps the order total.
    """
    if finding.key is None:
        return (1, "", 0, "", finding.check, finding.code)
    k = finding.key
    return (0, k.auth_asym_id, k.auth_seq_id, k.icode, finding.check, finding.code)


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Deterministic ordering, so run records and test assertions are stable."""
    return sorted(findings, key=finding_sort_key)


def summarise(reports: Sequence[SiteReport]) -> dict[str, int]:
    """Count verdicts across several sites, for batch output."""
    counts = {v.value: 0 for v in Verdict}
    for r in reports:
        counts[r.verdict.value] += 1
    return counts
