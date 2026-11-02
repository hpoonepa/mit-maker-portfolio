# SPDX-License-Identifier: MIT
"""What a preflight run *was*: the reproducibility artifact and its schema.

Separate from :mod:`hotspot_preflight.report`, which runs the checks and renders
them, because this is a deliverable in its own right rather than a detail of
running one. Somebody asking how this project handles reproducibility should find
a module named for it, carrying the input digest, the tool and dependency
versions, the pinned SASA parameters, the JSON Schema and the serialiser —
instead of reading a module named for running checks and hoping.

Two decisions here are load-bearing.

**The record carries no time field.** It is committed next to the designs it
justified and diffed against the next run. A timestamp makes every diff
non-empty, which trains readers to ignore diffs, so the one real change hides in
the noise. A caller needing wall-clock time must store it itself. Nothing in this
module reads a clock, and ``test_record_is_byte_identical_across_runs_of_the_same_input``
holds it that way.

**Every threshold is imported, never restated.** Each number under
``parameters`` comes from the constant the check actually compared against, or
from a real ``BurialProfile``. A copy here would let a threshold change in a
check module leave the record describing a run that never happened — and a record
that misdescribes its own run is worse than no record at all.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable

import gemmi

from .checks.burial import (
    BURIAL_CONTACT_A, BURIED_RELATIVE_SASA, CROP_ARTIFACT_DELTA,
    PARTNER_OCCLUSION_DELTA, SASA_PROBE_RADIUS, compute_burial,
)
from .findings import Finding, Severity, SiteReport
from .residue import NO_ICODE, ResidueKey
from .schema import load_schema, schema_text
from .structure import LOW_OCCUPANCY_THRESHOLD

__all__ = [
    "RUN_RECORD_VERSION", "DISTRIBUTION_NAME", "RUN_SPECIFIC_PARAMETER_KEYS",
    "PreflightRun", "to_run_record", "sasa_parameters", "file_digest",
    "load_schema", "schema_text",
]

RUN_RECORD_VERSION = "1"
"""Generation of the run-record format. Bumped only on a breaking change."""

DISTRIBUTION_NAME = "hotspot-preflight"

RUN_SPECIFIC_PARAMETER_KEYS = frozenset({
    "n_reference_empirical", "n_reference_published", "n_reference_substituted",
    "n_fallback_radius_atoms", "focus_chain", "freesasa_version",
    "gemmi_version", "reference_id",
})
"""Keys of ``BurialProfile.parameters`` that are *not* pinned settings.

The counters describe one measurement rather than the configuration, and the
library versions are reported once under ``versions``. Excluding them keeps the
``sasa`` block a pure statement of *how* SASA was computed, which is what must
match between two runs for their numbers to be comparable. ``reference_id`` is
excluded for a different reason — it is a digest of the structure-derived table,
so it belongs to the run — but is still recorded, via :func:`_reference_id`.
"""


def file_digest(path: str | Path) -> str:
    """SHA-256 of a file, chunked so a 180-chain entry is not loaded whole
    just to be hashed."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - installed in all envs
        return "unknown"


def _version_from_pyproject() -> str:
    """Read ``project.version`` from the source checkout.

    Needed because the dev and test environments run from ``src/`` via pytest's
    ``pythonpath`` without installing the distribution, and a record whose tool
    version reads "unknown" cannot be traced back to a revision.
    """
    path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    loader = None
    for module in ("tomllib", "tomli"):  # stdlib on 3.11+, a dev dep before it
        try:
            loader = __import__(module)
            break
        except ModuleNotFoundError:
            continue
    if loader is not None:
        try:
            return str(loader.loads(text)["project"]["version"])
        except (KeyError, TypeError, ValueError):
            return "unknown"
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "unknown"


def _tool_version() -> str:
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return _version_from_pyproject()


def _probe_structure() -> gemmi.Structure:
    """Three contiguous glycines: the cheapest input ``compute_burial`` accepts.

    Its only purpose is to produce a real ``BurialProfile`` so the pinned
    parameters can be read off one rather than copied into this file. Every
    number it yields is discarded; only ``parameters`` is kept.
    """
    structure = gemmi.Structure()
    structure.name = "PROBE"
    structure.spacegroup_hm = "P 1"
    model, chain = gemmi.Model("1"), gemmi.Chain("A")
    for index in range(3):
        residue = gemmi.Residue()
        residue.name, residue.het_flag = "GLY", "A"
        residue.seqid = gemmi.SeqId(index + 1, " ")
        for name, elem, dx in (("N", "N", 0.0), ("CA", "C", 1.5), ("C", "C", 3.0)):
            atom = gemmi.Atom()
            atom.name, atom.element = name, gemmi.Element(elem)
            atom.pos = gemmi.Position(index * 4.0 + dx, 0.0, 0.0)
            atom.occ, atom.b_iso = 1.0, 20.0
            residue.add_atom(atom)
        chain.add_residue(residue)
    model.add_chain(chain)
    structure.add_model(model)
    return structure


def sasa_parameters() -> dict[str, Any]:
    """The pinned SASA settings, read off a real ``BurialProfile``.

    Harvested rather than restated. ``checks.sasa`` owns the probe radius,
    algorithm, slice count and classifier and does not re-export them through
    ``checks.burial``; reading them off a profile means the record follows that
    module automatically, including through a rename.
    """
    profile = compute_burial(_probe_structure(), context="chain")
    return {
        key: value
        for key, value in sorted(profile.parameters.items())
        if key not in RUN_SPECIFIC_PARAMETER_KEYS
    }


def _reference_id(findings: Iterable[Finding]) -> str | None:
    """The reference-scale digest the burial check actually measured against.

    Taken from the findings, not recomputed: a recomputed one could disagree
    with what the check used, which is what this field exists to rule out.
    ``None`` when burial never ran.
    """
    for finding in findings:
        value = finding.evidence.get("reference_id")
        if isinstance(value, str) and value:
            return value
    return None


def _thresholds() -> dict[str, float]:
    """Every number a verdict was compared against, imported from its owner."""
    return {
        "low_occupancy_at_or_below": LOW_OCCUPANCY_THRESHOLD,
        "buried_relative_sasa_below": BURIED_RELATIVE_SASA,
        "crop_artifact_delta_above": CROP_ARTIFACT_DELTA,
        "partner_occlusion_delta_above": PARTNER_OCCLUSION_DELTA,
        "burial_contact_a": BURIAL_CONTACT_A,
        "sasa_probe_radius": SASA_PROBE_RADIUS,
    }

@dataclass
class PreflightRun:
    """Everything one preflight produced, with no formatting applied.

    Holds the inputs beside the findings because a verdict is only
    interpretable next to the file, site and thresholds that produced it —
    which is also exactly what :func:`to_run_record` serialises.
    """

    report: SiteReport
    target_id: str
    assembly_id: str | None
    hotspot_spec: str
    keys: list[ResidueKey]
    crop_range: tuple[str, int, int] | None
    tool_formats: dict[str, str]
    parameters: dict[str, Any]
    input_digest: str
    input_filename: str = ""

    @property
    def verdict_value(self) -> str:
        return self.report.verdict.value

    def flagged_keys(self) -> list[ResidueKey]:
        """Residues carrying at least one finding above PASS, in order."""
        out: list[ResidueKey] = []
        for finding in self.report.findings:
            if finding.severity is Severity.PASS or finding.key is None:
                continue
            if finding.key not in out:
                out.append(finding.key)
        return out

def _residue_dict(key: ResidueKey) -> dict[str, Any]:
    # icode is None rather than the mmCIF single space: a consumer reading JSON
    # has no reason to know that convention, and " " reads as a bug.
    return {
        "chain": key.auth_asym_id,
        "auth_seq_id": key.auth_seq_id,
        "icode": key.icode if key.icode != NO_ICODE else None,
    }


def to_run_record(run: PreflightRun) -> dict[str, Any]:
    """Serialise a run into the committable JSON record.

    JSON-safe under ``json.dumps(..., sort_keys=True)``, and carries no
    absolute path: only the input's base name plus its SHA-256, which is what
    identifies the coordinates. Shape documented by
    ``schema/run_record.schema.json`` and tested against it.

    **No timestamp, by design.** A record is committed next to the designs it
    justified and diffed against the next run. A time field makes every diff
    non-empty, which trains readers to ignore diffs, so the one real change hides
    in the noise. A caller needing wall-clock time must store it itself.
    """
    crop = run.crop_range
    record: dict[str, Any] = {
        "record_version": RUN_RECORD_VERSION,
        "tool": {"name": DISTRIBUTION_NAME, "version": _tool_version()},
        "versions": {
            "gemmi": gemmi.__version__,
            "freesasa": _package_version("freesasa"),
        },
        "input": {
            "filename": run.input_filename,
            "sha256": run.input_digest,
            "target_id": run.target_id,
            "assembly_id": run.assembly_id,
        },
        "site": {
            "hotspot_spec": run.hotspot_spec,
            "keys": [str(k) for k in run.keys],
            "residues": [_residue_dict(k) for k in run.keys],
            "crop_range": (
                None
                if crop is None
                else {"chain": crop[0], "first": crop[1], "last": crop[2]}
            ),
        },
        "parameters": run.parameters,
        "tool_formats": dict(run.tool_formats),
    }
    # SiteReport already owns the verdict/counts/findings contract; reusing it
    # means the record cannot drift from what the checks reported.
    record.update(run.report.to_dict())
    return record