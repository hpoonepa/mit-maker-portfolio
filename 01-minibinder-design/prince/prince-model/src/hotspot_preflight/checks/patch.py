# SPDX-License-Identifier: MIT
"""C5: is the hotspot set one patch a binder could actually cover?

The other checks ask whether each residue is real and reachable. This one asks
whether the residues, taken together, describe a *site*. They are different
failures and only this one is invisible to every tool downstream:

* RFdiffusion accepts any hotspot list. Given residues on opposite faces of a
  domain it does not complain — it hallucinates a backbone satisfying whichever
  subset it can reach and reports ordinary confidence for the result.
* ProteinMPNN then designs a sequence for that backbone, and AF2 or Boltz
  predicts the complex that was designed. Every score is computed against the
  site the pipeline settled on, not the site that was asked for.

So a scattered hotspot list does not fail loudly. It silently becomes a
campaign against a smaller, different epitope, and the numbers look fine.

Thresholds here are stated as module constants and justified individually.
``RFDIFFUSION_MIN_HOTSPOTS``/``MAX`` come from RFdiffusion's own README, which
says "we normally recommend between 3-6 hotspots"; the diameter limit comes
from the size of the face a minibinder presents. The geometry itself is
measured in :mod:`hotspot_preflight.surface`, which holds no thresholds.

This check deliberately stays inside geometry. It emits no verdict on whether a
residue exists (the resolved check), whether it is buried (the burial check) or
whether its number means what the user thinks (the numbering check) — a second
opinion on those would double-count the same problem in the aggregate verdict.
"""

from __future__ import annotations

from typing import Any, Sequence

import gemmi

from ..findings import Finding, Severity, sort_findings
from ..residue import ResidueKey
from ..structure import Target
from ..surface import (
    NEIGHBOUR_CUTOFF_A,
    Patch,
    connected_components,
    neighbour_graph,
    patch_diameter,
    residue_centroid,
)

__all__ = [
    "CHECK_NAME",
    "RFDIFFUSION_MIN_HOTSPOTS",
    "RFDIFFUSION_MAX_HOTSPOTS",
    "MAX_PATCH_DIAMETER_A",
    "check_patch_geometry",
]

CHECK_NAME = "patch"

RFDIFFUSION_MIN_HOTSPOTS = 3
RFDIFFUSION_MAX_HOTSPOTS = 6
"""RFdiffusion's README: "we normally recommend between 3-6 hotspots".

Both ends are failure modes, not style. Below three, the diffusion model has
too little to aim at and drifts to whatever surface it likes — the hotspots stop
constraining the design. Above six, the set describes more surface than one
small binder can bury, so the model satisfies a subset and the rest is
decoration the campaign never tests.
"""

MAX_PATCH_DIAMETER_A = 25.0
"""Widest hotspot separation a minibinder interface can plausibly span.

A 60-100 residue binder presents one face; a three-helix bundle is ~20-25 A
across, and a typical designed interface buries 700-1000 A^2 of that. Hotspots
further apart than the binder is wide cannot all be contacted, whatever the
design tool reports.
"""


def _finding(
    severity: Severity,
    code: str,
    message: str,
    **evidence: Any,
) -> Finding:
    """Every finding here is site-level: patch geometry is a property of the
    set, not of any one residue, so pinning it to a member would misattribute
    it."""
    return Finding(
        check=CHECK_NAME,
        severity=severity,
        code=code,
        message=message,
        key=None,
        evidence=evidence,
    )


def _with_coordinates(
    target: Target | gemmi.Structure, keys: Sequence[ResidueKey]
) -> list[ResidueKey]:
    """The subset that has heavy atoms, in the caller's order.

    Unmodelled and absent residues are excluded rather than reported: the
    resolved and numbering checks own those verdicts, and emitting a geometry
    code for them would mean two checks killing one site for one reason. They
    are still counted into every finding's evidence, so the exclusion is
    visible rather than silent.
    """
    out: list[ResidueKey] = []
    for key in keys:
        try:
            residue_centroid(target, key)
        except KeyError:
            continue
        out.append(key)
    return out


def check_patch_geometry(
    target: Target | gemmi.Structure, keys: Sequence[ResidueKey]
) -> list[Finding]:
    """Judge a hotspot set as a shape.

    Args:
        target: the loaded structure, or a structure such as an expanded
            assembly. Geometry should be judged in the context the campaign will
            design against; on an assembly a site that straddles two copies of a
            chain is contiguous, and on the asymmetric unit it is not.
        keys: candidate hotspot residues in author numbering, in the user's own
            order.

    Returns:
        Findings in canonical order, via
        :func:`hotspot_preflight.findings.sort_findings`. Unlike the burial
        check, there is no per-residue order to preserve — every finding here
        describes the whole set.

    Raises:
        ValueError: on an empty hotspot list. There is no geometry to judge, and
            returning a PASS for it would report an empty site as a good one.
    """
    if not keys:
        raise ValueError("no hotspot residues to check")

    unique = list(dict.fromkeys(keys))
    placed = _with_coordinates(target, unique)
    chains = sorted({k.auth_asym_id for k in unique})

    # Shared by every finding, so a reader can see what was and was not judged.
    common: dict[str, Any] = {
        "n_hotspots": len(unique),
        "n_without_coordinates": len(unique) - len(placed),
        "chains": chains,
        "neighbour_cutoff_a": NEIGHBOUR_CUTOFF_A,
    }

    findings: list[Finding] = []
    findings.extend(_count_findings(unique, common))
    findings.extend(_chain_findings(chains, common))
    findings.extend(_shape_findings(target, placed, common))

    # A PASS requires that every hotspot was actually measured. With a residue
    # excluded for want of coordinates the remainder can look perfect while the
    # real set is scattered, and "geometry OK" would be read as having cleared
    # the whole site.
    #
    # Tested against findings *above* PASS rather than against any finding at
    # all: HOTSPOT_COUNT_UNUSUAL is itself a PASS-severity note, and a note must
    # not suppress the geometry verdict it sits beside.
    flagged = any(f.severity is not Severity.PASS for f in findings)
    if not flagged and len(placed) == len(unique):
        findings.append(
            _finding(
                Severity.PASS,
                "PATCH_GEOMETRY_OK",
                f"The {len(placed)} hotspot residues form one contiguous patch "
                f"{patch_diameter(target, _as_patch(placed)):.1f} A across on "
                f"chain {chains[0]}, which a single minibinder face can cover.",
                **common,
            )
        )
    return sort_findings(findings)


def _as_patch(keys: Sequence[ResidueKey]) -> Patch:
    """A :class:`Patch` carrying only its members.

    The geometry helpers take a Patch, and the numeric fields are properties of
    a measured profile that this check neither has nor needs — it compares
    shapes, not exposure. Zeroes here are never read.
    """
    return Patch(
        residues=tuple(sorted(keys)),
        centroid=(0.0, 0.0, 0.0),
        area=0.0,
        mean_relative_sasa=0.0,
    )


def _count_findings(
    keys: Sequence[ResidueKey], common: dict[str, Any]
) -> list[Finding]:
    """``HOTSPOT_COUNT_UNUSUAL``, at PASS severity: a note, never a verdict.

    **Do not raise this to WARN.** Every other code in this package reports
    something *measured about the target* — a residue has no coordinates, a site
    is buried on the assembly, a number resolves in the wrong scheme. This one
    reports the shape of the *user's request*, and its source is a sentence in
    another tool's README. A finding that can demote a verdict should be about
    the site, not about how many residues somebody typed.

    The decisive evidence is experimental: ``l79_s469532_mpnn9`` binds 6F5J at
    604 nM by BLI — one binder in 35 ordered — against a **two-residue**
    specification, C325/C326. Widening that site is not available either, since
    C327 is buried on the assembly. A tool that flagged an assay-confirmed site
    as questionable because of a style guideline would simply be wrong.

    This is a reclassification, not a tuned threshold, and the difference
    matters. ``RFDIFFUSION_MIN_HOTSPOTS``/``MAX`` are unchanged, the finding
    still fires on exactly the same inputs, and it still appears in the text
    report, the CSV and the run record. Only its severity changed, because it
    measures nothing about the structure. Moving a *measurement* — the burial
    cut-off, say — to make a desired finding appear would be the opposite thing,
    and is not what happened here.
    """
    n = len(keys)
    if RFDIFFUSION_MIN_HOTSPOTS <= n <= RFDIFFUSION_MAX_HOTSPOTS:
        return []
    direction = (
        "too few to constrain where the binder lands"
        if n < RFDIFFUSION_MIN_HOTSPOTS
        else "more surface than one small binder can bury, so the model will "
        "satisfy a subset and ignore the rest"
    )
    return [
        _finding(
            Severity.PASS,
            "HOTSPOT_COUNT_UNUSUAL",
            f"{n} hotspot residues is outside the 3-6 that RFdiffusion's "
            f"own README recommends (\"we normally recommend between 3-6 "
            f"hotspots\"): {direction}. This is advice about a design tool, not "
            f"a measurement of your target, so it does not qualify the verdict.",
            recommended=[RFDIFFUSION_MIN_HOTSPOTS, RFDIFFUSION_MAX_HOTSPOTS],
            **common,
        )
    ]


def _chain_findings(chains: Sequence[str], common: dict[str, Any]) -> list[Finding]:
    """``MULTI_CHAIN_SITE``, a WARN, and correctly so.

    Unlike ``HOTSPOT_COUNT_UNUSUAL`` this *is* a measurement of the target: these
    residues demonstrably sit on more than one chain of this structure. The
    failure it catches — a chain letter copied from another entry, or numbering
    read off one chain and applied to another — is the silent misaim the whole
    package exists to prevent, so demoting it would be perverse.

    The message therefore leads with what was measured and puts the action
    second, so that nothing about it reads as advice.
    """
    if len(chains) < 2:
        return []
    named = ", ".join(chains)
    return [
        _finding(
            Severity.WARN,
            "MULTI_CHAIN_SITE",
            f"The hotspots sit on {len(chains)} different chains of this "
            f"structure ({named}), so they are not all on one polypeptide. That "
            f"is legitimate for a site deliberately straddling a real interface, "
            f"but it is more often a chain letter copied from a different entry, "
            f"or numbering taken from one chain and applied to another — the "
            f"mistake this tool exists to catch. Confirm you meant to design "
            f"across the interface.",
            n_chains=len(chains),
            **common,
        )
    ]


def _shape_findings(
    target: Target | gemmi.Structure,
    placed: Sequence[ResidueKey],
    common: dict[str, Any],
) -> list[Finding]:
    """Contiguity and span, measured only over residues that have coordinates."""
    if not placed:
        return []

    graph = neighbour_graph(target, placed)
    components = connected_components(graph)
    out: list[Finding] = []

    if len(components) > 1:
        groups = [[str(k) for k in component] for component in components]
        described = "; ".join("+".join(g) for g in groups)
        out.append(
            _finding(
                Severity.KILL,
                "NOT_CONTIGUOUS",
                f"The hotspots fall into {len(components)} separate groups "
                f"({described}), not one bindable site: no two groups have "
                f"heavy atoms within {NEIGHBOUR_CUTOFF_A:.0f} A of each other. "
                f"A binder presents one face, so it would contact at most one "
                f"group — and the design tool will report confident scores for "
                f"that partial site without flagging the rest.",
                n_components=len(components),
                components=groups,
                **common,
            )
        )

    diameter = patch_diameter(target, _as_patch(placed))
    if diameter > MAX_PATCH_DIAMETER_A:
        out.append(
            _finding(
                Severity.WARN,
                "PATCH_TOO_LARGE",
                f"The hotspots span {diameter:.1f} A, wider than the "
                f"{MAX_PATCH_DIAMETER_A:.0f} A face a 60-100 residue minibinder "
                f"presents. Expect the design to engage one end of the site and "
                f"leave the other untouched; either split it into two campaigns "
                f"or use a larger scaffold.",
                diameter_a=round(diameter, 2),
                max_diameter_a=MAX_PATCH_DIAMETER_A,
                **common,
            )
        )
    return out
