# SPDX-License-Identifier: MIT
"""Is the surface you are designing against actually a surface?

A binder campaign starts by cutting the target down to something a design tool
can hold — a crop. The cut exposes whatever it slices through, so the crop has
faces the real protein does not have. Designs bind those faces and then fail.

Measured on our own 5G51 campaign, 26 designs against one target: the 7 built
against truncated crops scored 0.567-0.940 against their own crop and
0.0000-0.0369 against the intact 260-416 domain; the 19 built against the full
domain scored 0.183-0.854 and none collapsed. Perfect separation, 7/7 and
19/19, and no design score saw it coming — every score was computed in the same
truncated context that created the artifact.

So this check measures relative solvent accessibility three ways and compares
them: on the expanded **biological assembly** (the real multi-chain form), on
the **isolated chain**, and on a user-supplied **crop**. Open on the crop but
shut on the assembly is a crop artifact; open on the chain but shut on the
assembly is partner occlusion; shut on the assembly is not a binding site.

The measurement lives in :mod:`.sasa` and the assembly expansion in
:mod:`.assembly`; neither holds a threshold. Every threshold is here, and all
deltas go through :func:`compare_contexts`, which refuses to subtract profiles
built on different reference scales.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

import gemmi

from ..findings import Finding, Severity
from ..residue import ResidueKey
from ..structure import Target, _icode, observed_residues
from .assembly import expand_assembly
from .sasa import (
    NEIGHBOUR_CUTOFF_A,
    PUBLISHED_MAX_SASA,
    REQUIRED_PARAMETER_KEYS,
    SASA_PROBE_RADIUS,
    VALID_CONTEXTS,
    BurialProfile,
    _chain_names,
    _heavy_atoms,
    _neighbour_search,
    _subset_structure,
    compute_burial,
    reference_digest,
    reference_max_sasa,
    trim_to_neighbourhood,
)

__all__ = [
    # Thresholds, identity and judgement, owned here.
    "BURIED_RELATIVE_SASA", "CROP_ARTIFACT_DELTA", "PARTNER_OCCLUSION_DELTA",
    "BURIAL_CONTACT_A", "CHECK_NAME",
    "compare_contexts", "check_burial",
    # Re-exported from .assembly and .sasa so `from ...checks.burial import X`
    # keeps working for callers that do not care where the pieces moved to.
    "expand_assembly",
    "SASA_PROBE_RADIUS", "NEIGHBOUR_CUTOFF_A", "PUBLISHED_MAX_SASA",
    "REQUIRED_PARAMETER_KEYS", "VALID_CONTEXTS", "BurialProfile",
    "compute_burial", "reference_digest", "reference_max_sasa",
    "trim_to_neighbourhood",
]

CHECK_NAME = "burial"

BURIED_RELATIVE_SASA = 0.05
"""Below this on the assembly the residue is not solvent-facing at all: KILL."""

CROP_ARTIFACT_DELTA = 0.20
"""Change in relative SASA between two contexts that we call material."""

PARTNER_OCCLUSION_DELTA = CROP_ARTIFACT_DELTA
"""The same number, named separately so the two rules read independently."""

BURIAL_CONTACT_A = 5.0
"""Range at which another chain counts as packing against a residue. Used only
to *name* the occluder: 'buried by chain B' is actionable, '0.002' is not."""



# ---------------------------------------------------------------------------
# Comparing contexts
# ---------------------------------------------------------------------------


def _scale(p: BurialProfile) -> str:
    return (
        f"{p.context!r} (scale {p.reference_id}, "
        f"{p.parameters.get('n_reference_empirical')} empirical / "
        f"{p.parameters.get('n_reference_published')} published)"
    )


def compare_contexts(a: BurialProfile, b: BurialProfile) -> dict[ResidueKey, float]:
    """Per-residue ``a - b`` relative SASA, for residues present in both.

    The only place a delta is computed, and it refuses to compute one across
    mismatched denominator scales. Relative SASA is an area over a
    per-residue-type reference maximum, so profiles built on different
    reference tables are in different units; subtracting them gives a number
    that looks entirely plausible and means nothing.

    Not hypothetical: recomputing the reference per context passed this
    module's whole suite — every threshold assertion, both real structures —
    because the rescaled values stayed in range and kept their ordering. A
    future change here should fail
    ``test_mismatched_reference_scales_refuse_to_compare`` rather than quietly
    produce comparable-looking output.

    Raises:
        ValueError: if the two profiles carry different ``reference_id``s.
    """
    if a.reference_id != b.reference_id:
        raise ValueError(
            f"cannot compare {_scale(a)} with {_scale(b)}: different reference "
            f"scales, so their deltas would be meaningless. Build one table "
            f"with reference_max_sasa() and pass it to every context."
        )
    return {
        key: value - b.relative_sasa[key]
        for key, value in a.relative_sasa.items()
        if key in b.relative_sasa
    }


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def _find_residue(model: gemmi.Model, key: ResidueKey) -> gemmi.Residue | None:
    if key.auth_asym_id not in [c.name for c in model]:
        return None
    for res in model[key.auth_asym_id]:
        if res.seqid.num == key.auth_seq_id and _icode(res.seqid.icode) == key.icode:
            return res
    return None


def _occluding_chains(structure: gemmi.Structure, key: ResidueKey) -> list[str]:
    """Other chains packing against this residue, most contacts first."""
    model = structure[0]
    res = _find_residue(model, key)
    if res is None:
        return []
    search = _neighbour_search(model, BURIAL_CONTACT_A)
    counts: Counter[str] = Counter()
    for atom in _heavy_atoms(res):
        for mark in search.find_atoms(atom.pos, "\0", radius=BURIAL_CONTACT_A):
            name = model[mark.chain_idx].name
            if name != key.auth_asym_id:
                counts[name] += 1
    return [name for name, _ in counts.most_common()]


def _validate_crop(
    target: Target, crop_range: tuple[str, int, int], observed: set[ResidueKey]
) -> None:
    chain, first, last = crop_range
    if chain not in _chain_names(target.st):
        raise ValueError(
            f"crop chain {chain!r} is not in {target.entry_id}; "
            f"chains are {_chain_names(target.st)}"
        )
    if last < first:
        raise ValueError(f"crop range {chain}{first}-{last} runs backwards")
    if not any(
        k.auth_asym_id == chain and first <= k.auth_seq_id <= last for k in observed
    ):
        raise ValueError(
            f"crop range {chain}{first}-{last} contains no observed residues; "
            f"check the numbering scheme you took it from"
        )


def _finding(
    severity: Severity,
    code: str,
    message: str,
    key: ResidueKey | None = None,
    **evidence: Any,
) -> Finding:
    return Finding(
        check=CHECK_NAME,
        severity=severity,
        code=code,
        message=message,
        key=key,
        evidence=evidence,
    )


def check_burial(
    target: Target,
    keys: Sequence[ResidueKey],
    crop_range: tuple[str, int, int] | None = None,
) -> list[Finding]:
    """Decide, per residue, whether the site is really solvent-facing.

    Findings come back in the caller's hotspot order, site-level first, and are
    deliberately *not* sorted: ``parse_hotspot_spec`` preserves first-seen
    order because it sometimes reflects priority. Pipe through
    ``findings.sort_findings`` when you want a canonical order.

    Args:
        target: the loaded structure.
        keys: candidate hotspot residues, in author numbering.
        crop_range: ``(auth_asym_id, first, last)``, inclusive — the truncation
            you intend to design against. Residues on other chains are still
            checked, they just get no crop comparison.

    Raises:
        ValueError: on an empty key list, a hotspot on an unknown chain, or a
            crop range that is backwards, on an unknown chain, or holds no
            observed residues.
    """
    if not keys:
        raise ValueError("no hotspot residues to check")

    present = _chain_names(target.st)
    for key in keys:
        if key.auth_asym_id not in present:
            raise ValueError(
                f"chain {key.auth_asym_id!r} (from hotspot {key}) is not in "
                f"{target.entry_id}; chains are {present}"
            )

    observed = observed_residues(target)
    if crop_range is not None:
        _validate_crop(target, crop_range, observed)

    findings: list[Finding] = []
    # One reference table, from the asymmetric unit, shared by all three
    # contexts. See compute_burial's `reference` argument for why.
    reference = reference_max_sasa(target.st)
    focus_chains = sorted({k.auth_asym_id for k in keys})

    chain_profiles: dict[str, BurialProfile] = {}
    assembly_profiles: dict[str, BurialProfile] = {}
    assembly_structures: dict[str, gemmi.Structure] = {}

    expanded = expand_assembly(target) if target.st.assemblies else None
    if expanded is None:
        findings.append(
            _finding(
                Severity.WARN,
                "NO_ASSEMBLY_DEFINED",
                f"{target.entry_id} declares no biological assembly, so burial "
                f"was measured on the isolated chain instead. An asymmetric "
                f"unit is not necessarily the biological form, so occlusion by "
                f"a partner chain cannot be ruled out here.",
                n_chains_in_file=len(present),
            )
        )

    for chain in focus_chains:
        single = _subset_structure(target.st, [chain])
        chain_profiles[chain] = compute_burial(
            single, context="chain", focus_chain=chain, reference=reference
        )
        if expanded is None:
            assembly_structures[chain] = single
            assembly_profiles[chain] = chain_profiles[chain]
        else:
            trimmed = trim_to_neighbourhood(expanded, chain)
            assembly_structures[chain] = trimmed
            assembly_profiles[chain] = compute_burial(
                trimmed, context="assembly", focus_chain=chain, reference=reference
            )

    crop_profile: BurialProfile | None = None
    if crop_range is not None:
        crop_chain, first, last = crop_range
        cropped = _subset_structure(
            target.st, [crop_chain], keep=lambda r: first <= r.seqid.num <= last
        )
        crop_profile = compute_burial(
            cropped, context="crop", focus_chain=crop_chain, reference=reference
        )

    # All delta arithmetic goes through compare_contexts, which refuses to
    # subtract profiles measured on different reference scales.
    chain_deltas = {
        chain: compare_contexts(chain_profiles[chain], assembly_profiles[chain])
        for chain in focus_chains
    }
    crop_deltas: dict[ResidueKey, float] = {}
    if crop_profile is not None and crop_range is not None:
        # The crop chain need not carry any hotspot — crop A, hotspots on B is
        # legal — in which case there is no assembly profile to compare against
        # and no key can want a crop delta anyway.
        crop_chain_profile = assembly_profiles.get(crop_range[0])
        if crop_chain_profile is not None:
            crop_deltas = compare_contexts(crop_profile, crop_chain_profile)

    for key in keys:
        findings.extend(
            _findings_for(
                key,
                observed,
                chain_profiles[key.auth_asym_id],
                assembly_profiles[key.auth_asym_id],
                assembly_structures[key.auth_asym_id],
                crop_profile,
                crop_range,
                chain_deltas[key.auth_asym_id].get(key),
                crop_deltas.get(key),
            )
        )
    return findings


def _findings_for(
    key: ResidueKey,
    observed: set[ResidueKey],
    chain_profile: BurialProfile,
    assembly_profile: BurialProfile,
    assembly_structure: gemmi.Structure,
    crop_profile: BurialProfile | None,
    crop_range: tuple[str, int, int] | None,
    delta_chain: float | None,
    delta_crop: float | None,
) -> list[Finding]:
    if key not in observed or key not in assembly_profile.relative_sasa:
        return [
            _finding(
                Severity.WARN,
                "RESIDUE_NOT_OBSERVED",
                f"{key} has no atoms in the coordinates, so its solvent "
                f"accessibility is undefined and burial cannot be judged. The "
                f"resolved check owns the verdict on unmodelled residues.",
                key,
                observed=False,
            )
        ]

    rel_assembly = assembly_profile.relative_sasa[key]
    rel_chain = chain_profile.relative_sasa.get(key, rel_assembly)
    in_crop = (
        crop_profile is not None
        and crop_range is not None
        and key.auth_asym_id == crop_range[0]
        and key in crop_profile.relative_sasa
    )
    rel_crop = crop_profile.relative_sasa[key] if in_crop else None

    evidence: dict[str, Any] = {
        "relative_sasa_assembly": round(rel_assembly, 4),
        "relative_sasa_chain": round(rel_chain, 4),
        "relative_sasa_crop": None if rel_crop is None else round(rel_crop, 4),
        "absolute_sasa_assembly": round(assembly_profile.absolute_sasa[key], 2),
        "n_chains_in_assembly_context": assembly_profile.n_chains,
        "buried_below": BURIED_RELATIVE_SASA,
        "delta_threshold": CROP_ARTIFACT_DELTA,
        "reference_id": assembly_profile.reference_id,
        # How the denominators were priced, carried through so a run record
        # states it without re-measuring. n_reference_published > 0 means some
        # residue types could not be calibrated from this structure, so those
        # relative values rest on the Tien fallback table rather than on
        # anything measured in-structure — a reviewer reproducing the run has
        # to be able to see that.
        #
        # Taken from the assembly profile, which is the context every verdict
        # here rests on, and the same source as reference_id above. The two
        # reference-table counts are properties of the shared table and so are
        # identical across contexts; the substitution and radius-fallback
        # counts are per-context, and the crop's own are not reported because
        # no finding is decided on them.
        **{
            name: assembly_profile.parameters[name]
            for name in (
                "n_reference_empirical",
                "n_reference_published",
                "n_reference_substituted",
                "n_fallback_radius_atoms",
                "focus_chain",
            )
        },
    }
    out: list[Finding] = []

    # Computed at most once per residue: an interface residue trips both the
    # buried and the occluded branch, and each call builds a NeighborSearch.
    buried = rel_assembly < BURIED_RELATIVE_SASA
    occluded = delta_chain is not None and delta_chain > PARTNER_OCCLUSION_DELTA
    occluders = (
        _occluding_chains(assembly_structure, key) if buried or occluded else []
    )

    if buried:
        cause = (
            f"chain {occluders[0]} packs against it"
            if occluders
            else "it faces its own chain's core, not solvent"
        )
        out.append(
            _finding(
                Severity.KILL,
                "BURIED_IN_ASSEMBLY",
                f"{key} is not solvent-accessible on the biological assembly "
                f"(relative SASA {rel_assembly:.3f}): {cause}. A binder cannot "
                f"reach it.",
                key,
                occluding_chains=occluders,
                **evidence,
            )
        )

    if (
        rel_crop is not None
        and delta_crop is not None
        and abs(delta_crop) > CROP_ARTIFACT_DELTA
    ):
        chain, first, last = crop_range  # type: ignore[misc]
        opened, shut = ("exposed", "buried") if delta_crop > 0 else ("buried", "exposed")
        direction = (
            f"{opened} on your crop ({rel_crop:.2f}) but {shut} on the "
            f"assembly ({rel_assembly:.2f})"
        )
        consequence = (
            "designs will bind a face the intact protein does not have"
            if delta_crop > 0
            else "the crop hides a site that is real"
        )
        out.append(
            _finding(
                Severity.WARN,
                "CROP_ARTIFACT",
                f"{key} is {direction}; the crop {chain}{first}-{last} changes "
                f"its accessibility, so {consequence}.",
                key,
                crop=f"{chain}{first}-{last}",
                **evidence,
            )
        )

    if occluded:
        named = f"chain {occluders[0]}" if occluders else "another chain"
        out.append(
            _finding(
                Severity.WARN,
                "OCCLUDED_BY_PARTNER",
                f"{key} is {rel_chain:.2f} exposed on the isolated chain but "
                f"only {rel_assembly:.2f} on the biological assembly — {named} "
                f"covers it. Designing against the single chain aims at a "
                f"surface the assembled protein buries.",
                key,
                occluding_chains=occluders,
                **evidence,
            )
        )

    if not out:
        out.append(
            _finding(
                Severity.PASS,
                "EXPOSED",
                f"{key} is solvent-exposed on the biological assembly "
                f"(relative SASA {rel_assembly:.2f}) and no change of "
                f"structural context moves it materially.",
                key,
                **evidence,
            )
        )
    return out
