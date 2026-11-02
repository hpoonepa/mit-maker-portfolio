# SPDX-License-Identifier: MIT
"""Reconcile a hotspot list against the structure's two numbering schemes.

Design tools disagree about how a residue is named:

* RFdiffusion takes author numbering — ``ppi.hotspot_res=[A30,A33,A34]``
* BindCraft takes author numbering — ``target_hotspot_residues="A30-33,B12"``
* BoltzGen indexes binding-site residues by mmCIF ``label_seq_id``, a 1-indexed
  count along the entity that generally does **not** equal the author number

So a list that is right for one tool is silently wrong for another. Nothing
raises; the design job simply aims at different residues, and you find out weeks
later from a flat assay. This check detects that mistake and
:func:`translate_for_tools` emits the correctly converted list for each tool.

The detection hinges on one number: the per-chain **offset**, author number
minus ``label_seq_id``.

* offset 0 — the two schemes coincide, so a mistake is undetectable *and
  harmless*. Neither ``WRONG_NUMBERING_SCHEME`` nor ``AMBIGUOUS_NUMBERING`` can
  fire, and some real entries (6F5J chain C among them) can never exhibit this
  bug at all.
* offset larger than the chain's length — the two readings cannot both be
  valid, so a wrong-scheme list resolves in exactly one scheme and we name it
  with certainty.
* small non-zero offset — both readings land on real, *different* residues.
  We cannot tell which was meant, which is what ``AMBIGUOUS_NUMBERING`` is for.

This check says nothing about whether a residue is modelled or solvent-exposed;
the ``resolved`` and ``burial`` checks own those verdicts. It does have to *ask*
whether a residue is modelled, though, because the author-to-label_seq map is
built from coordinates: without consulting the declared sequence an unmodelled
residue is indistinguishable from a nonexistent one, and the check would report
a numbering error for numbering that is correct. That case gets
``RESIDUE_DECLARED_NOT_OBSERVED`` as a WARN — never a second KILL for a fact
``resolved`` already owns, matching ``burial.py``'s ``RESIDUE_NOT_OBSERVED``.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..findings import Finding, Severity
from ..residue import (
    ResidueKey,
    to_bindcraft,
    to_boltzgen,
    to_rfdiffusion,
)
from ..structure import (
    Target,
    build_label_seq_map,
    declared_residues,
    observed_residues,
)

__all__ = [
    "CHECK_NAME",
    "ICODE_UNSUPPORTED_TOOLS",
    "build_reverse_label_seq_map",
    "check_numbering",
    "translate_for_tools",
]

CHECK_NAME = "numbering"

ICODE_UNSUPPORTED_TOOLS = ["rfdiffusion"]
"""Tools whose hotspot syntax has no slot for an mmCIF insertion code."""

_TOOL_EMITTERS = ("rfdiffusion", "bindcraft", "boltzgen")


def build_reverse_label_seq_map(target: Target) -> dict[tuple[str, int], ResidueKey]:
    """Map ``(auth_asym_id, label_seq_id)`` back to the author residue key.

    This is the lookup that answers "if the user meant BoltzGen numbering,
    which residue did they actually name?" — the second interpretation every
    finding below is built from.

    Built by inverting :func:`structure.build_label_seq_map`, so it covers only
    residues with coordinates. That is deliberate: a declared-but-unmodelled
    residue has no usable label_seq for BoltzGen anyway, and claiming the
    translation works for it would hand the user a config that targets a gap.
    """
    reverse: dict[tuple[str, int], ResidueKey] = {}
    for key, label_seq in build_label_seq_map(target).items():
        # Insertion-code residues share an author number with their parent but
        # have distinct label_seq ids, so the reverse direction stays 1:1.
        reverse[(key.auth_asym_id, label_seq)] = key
    return reverse


def _chain_offset(
    label_map: dict[ResidueKey, int], chain_id: str
) -> int | None:
    """Author minus label_seq for a chain, or None when it is not constant.

    A non-constant offset means the chain was renumbered mid-sequence (or
    carries insertion codes). The offset is then not a single fact and we report
    None rather than an average, which would be a fiction.
    """
    offsets = {
        key.auth_seq_id - label_seq
        for key, label_seq in label_map.items()
        if key.auth_asym_id == chain_id
    }
    return offsets.pop() if len(offsets) == 1 else None


def _range(values: list[int]) -> list[int] | None:
    return [min(values), max(values)] if values else None


def _chain_ranges(
    label_map: dict[ResidueKey, int], chain_id: str
) -> tuple[list[int] | None, list[int] | None]:
    """The chain's observed author range and label_seq range."""
    auth = [k.auth_seq_id for k in label_map if k.auth_asym_id == chain_id]
    label = [v for k, v in label_map.items() if k.auth_asym_id == chain_id]
    return _range(auth), _range(label)


def _chain_finding(key: ResidueKey, chain_ids: list[str]) -> Finding:
    """NO_SUCH_CHAIN. Takes precedence: a number on a phantom chain is noise."""
    case_match = next(
        (c for c in chain_ids if c.lower() == key.auth_asym_id.lower()), None
    )
    message = (
        f"chain {key.auth_asym_id!r} does not exist in this entry; "
        f"its chains are {', '.join(chain_ids) or '(none)'}"
    )
    if case_match is not None:
        message += (
            f". Chain ids are case-sensitive in mmCIF — this differs from "
            f"{case_match!r} only by case, so {key.auth_asym_id}"
            f"{key.auth_seq_id} is probably meant to be "
            f"{case_match}{key.auth_seq_id}"
        )
    return Finding(
        check=CHECK_NAME,
        severity=Severity.KILL,
        code="NO_SUCH_CHAIN",
        message=message,
        key=key,
        evidence={"chains": list(chain_ids), "case_insensitive_match": case_match},
    )


def _resolution_finding(
    key: ResidueKey,
    *,
    author_hit: bool,
    declared: bool,
    label_hit: ResidueKey | None,
    label_seq: int | None,
    offset: int | None,
    auth_range: list[int] | None,
    label_range: list[int] | None,
) -> Finding:
    """Decide between the five resolution outcomes for one residue.

    ``author_hit`` is observation, not existence: a residue declared in the
    entry but never modelled is *not* a numbering error, which is why
    ``declared`` is a separate input rather than folded into ``author_hit``.
    """
    base: dict[str, Any] = {"chain_offset": offset}

    if author_hit and label_hit is not None and label_hit != key:
        # Both readings name a real residue, and not the same one.
        return Finding(
            check=CHECK_NAME,
            severity=Severity.WARN,
            code="AMBIGUOUS_NUMBERING",
            message=(
                f"{key} is valid in both schemes and they disagree: as an "
                f"author number it is {key}, but read as label_seq_id "
                f"{key.auth_seq_id} it is author residue {label_hit}. This "
                f"chain's author numbering is offset by {offset}, so every "
                f"number in range is valid twice — confirm which tool the list "
                f"was written for before using it."
            ),
            key=key,
            evidence={
                **base,
                "author_interpretation": str(key),
                "label_seq_interpretation": str(label_hit),
                "label_seq": label_seq,
            },
        )

    if author_hit:
        return Finding(
            check=CHECK_NAME,
            severity=Severity.PASS,
            code="NUMBERING_CONSISTENT",
            message=(
                f"{key} resolves unambiguously in author numbering"
                + (f" (label_seq_id {label_seq})" if label_seq is not None else "")
            ),
            key=key,
            evidence={**base, "label_seq": label_seq},
        )

    if declared:
        # The entry's own declared sequence confirms this author number, so the
        # numbering is fine and the residue is merely unmodelled. Emitting
        # NO_SUCH_RESIDUE here would be a confident statement of the wrong
        # cause, sending the user off to re-derive a scheme that was correct —
        # and it would be the second KILL for one underlying fact. WARN, and
        # the resolved check owns the verdict, as burial.py does with
        # RESIDUE_NOT_OBSERVED.
        hint = (
            f" If this list was written in label_seq numbering, "
            f"{key.auth_seq_id} is author residue {label_hit}."
            if label_hit is not None
            else ""
        )
        return Finding(
            check=CHECK_NAME,
            severity=Severity.WARN,
            code="RESIDUE_DECLARED_NOT_OBSERVED",
            message=(
                f"{key} is declared in this entry but has no atoms in the "
                f"coordinates, so it has no label_seq_id and BoltzGen output "
                f"will be incomplete. Its numbering is not the problem; the "
                f"resolved check owns the verdict on unmodelled residues." + hint
            ),
            key=key,
            evidence={
                **base,
                "declared": True,
                "observed": False,
                "label_seq": None,
                "label_seq_interpretation": (
                    None if label_hit is None else str(label_hit)
                ),
            },
        )

    if label_hit is not None:
        return Finding(
            check=CHECK_NAME,
            severity=Severity.KILL,
            code="WRONG_NUMBERING_SCHEME",
            message=(
                f"{key} does not exist in author numbering, but label_seq_id "
                f"{key.auth_seq_id} is author residue {label_hit} — this list "
                f"looks like BoltzGen/label_seq numbering. Use {label_hit} for "
                f"RFdiffusion and BindCraft."
            ),
            key=key,
            evidence={
                **base,
                "author_interpretation": None,
                "label_seq_interpretation": str(label_hit),
                "label_seq": key.auth_seq_id,
            },
        )

    return Finding(
        check=CHECK_NAME,
        severity=Severity.KILL,
        code="NO_SUCH_RESIDUE",
        message=(
            f"{key} resolves in neither scheme on chain {key.auth_asym_id}: "
            f"observed author numbers run {_fmt_range(auth_range)} and "
            f"label_seq_id runs {_fmt_range(label_range)}"
        ),
        key=key,
        evidence={
            **base,
            "author_range": auth_range,
            "label_seq_range": label_range,
        },
    )


def _fmt_range(rng: list[int] | None) -> str:
    return f"{rng[0]}-{rng[1]}" if rng else "(nothing observed)"


def _icode_finding(key: ResidueKey) -> Finding:
    """ICODE_NOT_EXPRESSIBLE, reported independently of resolution.

    This is a property of the tool syntax, not of the structure, so it holds
    whether or not the residue itself resolves.
    """
    return Finding(
        check=CHECK_NAME,
        severity=Severity.WARN,
        code="ICODE_NOT_EXPRESSIBLE",
        message=(
            f"{key} carries insertion code {key.icode!r}, which "
            f"{', '.join(ICODE_UNSUPPORTED_TOOLS)} hotspot syntax cannot "
            f"express; BindCraft and BoltzGen can still target it"
        ),
        key=key,
        evidence={
            "icode": key.icode,
            "affected_tools": list(ICODE_UNSUPPORTED_TOOLS),
        },
    )


def check_numbering(
    target: Target, keys: Sequence[ResidueKey]
) -> list[Finding]:
    """Check a hotspot list against both numbering schemes of ``target``.

    Args:
        target: loaded structure.
        keys: hotspot residues as the user wrote them, assumed to be author
            numbering — the assumption this check exists to test.

    Returns:
        Findings in **caller order** — per-key findings follow the order of
        ``keys``, with any site-level findings appended last. The order a user
        writes hotspots in sometimes reflects priority (see
        :func:`residue.parse_hotspot_spec`, which preserves it), so sorting here
        would silently discard information this check does not own. Callers
        wanting a canonical order pipe the result through
        :func:`findings.sort_findings`, which is what ``report.py`` does when it
        builds the run record and the rendered output.

        Codes are a stable contract: ``WRONG_NUMBERING_SCHEME``,
        ``AMBIGUOUS_NUMBERING``, ``NO_SUCH_RESIDUE``,
        ``RESIDUE_DECLARED_NOT_OBSERVED``, ``NO_SUCH_CHAIN``,
        ``ICODE_NOT_EXPRESSIBLE``, ``NUMBERING_CONSISTENT``.
    """
    chain_ids = target.chain_ids
    observed = observed_residues(target)
    # Declared is consulted because the reverse map is built from coordinates:
    # without it an unmodelled residue is indistinguishable from a nonexistent
    # one, and we would report a numbering error for correct numbering.
    declared = declared_residues(target)
    label_map = build_label_seq_map(target)
    reverse = build_reverse_label_seq_map(target)

    findings: list[Finding] = []
    for key in keys:
        if key.auth_asym_id not in chain_ids:
            findings.append(_chain_finding(key, chain_ids))
            continue

        if key.has_icode:
            findings.append(_icode_finding(key))

        # A key carrying an insertion code is author numbering by construction:
        # label_seq_id has no insertion codes, so there is no second reading.
        label_hit = (
            None if key.has_icode else reverse.get((key.auth_asym_id, key.auth_seq_id))
        )
        auth_range, label_range = _chain_ranges(label_map, key.auth_asym_id)
        findings.append(
            _resolution_finding(
                key,
                author_hit=key in observed,
                declared=key in declared,
                label_hit=label_hit,
                label_seq=label_map.get(key),
                offset=_chain_offset(label_map, key.auth_asym_id),
                auth_range=auth_range,
                label_range=label_range,
            )
        )

    return findings


def translate_for_tools(
    target: Target, keys: Sequence[ResidueKey]
) -> dict[str, str]:
    """Emit the hotspot list in each tool's own numbering.

    Returns ``{"rfdiffusion": ..., "bindcraft": ..., "boltzgen": ...}``. A
    format that cannot be produced maps to the reason verbatim instead of
    raising, because the caller wants the formats that *do* work — being handed
    two usable strings and one explanation beats an exception that yields none.
    """
    label_map = build_label_seq_map(target)
    out: dict[str, str] = {}
    for tool in _TOOL_EMITTERS:
        try:
            if tool == "rfdiffusion":
                out[tool] = to_rfdiffusion(keys)
            elif tool == "bindcraft":
                out[tool] = to_bindcraft(keys)
            else:
                out[tool] = to_boltzgen(keys, label_map)
        except (ValueError, KeyError) as exc:
            # KeyError stringifies with quotes around the message; unwrap it so
            # the reason reads as prose in a report.
            out[tool] = (
                str(exc.args[0]) if isinstance(exc, KeyError) else str(exc)
            )
    return out
