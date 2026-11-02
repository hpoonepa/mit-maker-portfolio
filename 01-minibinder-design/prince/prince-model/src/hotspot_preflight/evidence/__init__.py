# SPDX-License-Identifier: MIT
"""The literature-evidence layer: a curated table, and a gate in front of it.

Off by default, and independently ablatable, because we intend to report
whether it helped. Nothing here runs unless a caller passes rows in.

The one rule that defines the package: **an unreviewed row can be loaded,
reported and counted, but can never contribute to a verdict.** See
:mod:`hotspot_preflight.evidence.table` for why, and for the two layers that
enforce it.

Importing this package makes no network call and requires no API key. The
drafting model in :mod:`hotspot_preflight.evidence.grader` is constructed on
first use, so the rest of the tool stays usable offline.
"""

from __future__ import annotations

from .table import (
    BUNDLED_TABLE_DIR,
    CHECK_NAME,
    Direction,
    EvidenceClass,
    EvidenceRow,
    EvidenceTableError,
    UnreviewedRowError,
    check_evidence,
    load_table,
    row_from_mapping,
    rows_for,
    strongest,
    verdict_findings,
)

__all__ = [
    "BUNDLED_TABLE_DIR",
    "CHECK_NAME",
    "Direction",
    "EvidenceClass",
    "EvidenceRow",
    "EvidenceTableError",
    "UnreviewedRowError",
    "check_evidence",
    "load_table",
    "row_from_mapping",
    "rows_for",
    "strongest",
    "verdict_findings",
]
