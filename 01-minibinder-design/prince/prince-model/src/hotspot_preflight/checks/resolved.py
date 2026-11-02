# SPDX-License-Identifier: MIT
"""Is the hotspot residue actually in the structure?

This cheap check reports hotspots that lack deposited coordinates before
downstream modelling. A campaign against PDB 6F5J chain C specified Ile405 and
Phe408. Chain C declares 416 residues, 393 of them are modelled, and residues
399-416 have no coordinates. Both hotspots sat in that gap. This observation concerns coordinate coverage at the nominated hotspots.

The check asks three separate questions, in order, because a wrong answer to an
earlier one makes the later ones meaningless:

1. Does the chain exist? A typo'd chain id makes the residue number noise.
2. Is the residue declared at all? If not, the number is wrong, not the model.
3. Does it have coordinates? This is the question people think they are asking.

**The None-versus-empty-set distinction.** Unmodelled residues are detected two
ways: by reading ``_pdbx_unobs_or_zero_occ_residues``, and by deriving
declared-minus-observed. The first is optional in mmCIF and absent from many
real entries, so :func:`unobserved_from_cif_category` returns ``None`` when it is
missing — *the entry does not say* — which is not ``set()`` — *the entry says
nothing is missing*. Treating ``None`` as "all clear" is the bug that makes a
checker silently useless on much of the archive. Here ``None`` suppresses the
cross-check, downgrades confidence via a site-level ``NO_UNOBS_CATEGORY``
warning, and never contributes to a clean verdict. The derived route decides the
verdict in every case, because coordinates are ground truth and annotation is
not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..findings import Finding, Severity
from ..residue import ResidueKey
from ..structure import (
    LOW_OCCUPANCY_THRESHOLD,
    Target,
    _icode,
    declared_residues,
    low_occupancy_residues,
    observed_residues,
    unobserved_from_alignment,
    unobserved_from_cif_category,
)

__all__ = ["CHECK_NAME", "check_resolved"]

CHECK_NAME = "resolved"
"""The ``check`` field on every Finding this module returns."""

#: Existence verdicts. Exactly one is emitted per residue — they are mutually
#: exclusive answers to "is this residue there?", and emitting two would leave
#: the caller to decide which to believe.
EXISTENCE_CODES = ("NO_SUCH_CHAIN", "NOT_DECLARED", "UNMODELLED", "RESOLVED")


@dataclass(frozen=True)
class _Evidence:
    """Everything about the entry that the per-residue verdicts need.

    Computed once per call rather than per residue: each accessor walks the
    whole structure or a whole cif category, and a 20-hotspot site would
    otherwise re-read the file twenty times for the same answer.
    """

    target: Target
    chain_ids: tuple[str, ...]
    declared: frozenset[ResidueKey]
    observed: frozenset[ResidueKey]
    low_occupancy: frozenset[ResidueKey]
    occupancies: dict[ResidueKey, float]
    # None means the entry omits the category. Not an empty set.
    from_category: frozenset[ResidueKey] | None
    from_alignment: frozenset[ResidueKey]

    @property
    def entry_id(self) -> str:
        return self.target.entry_id

    def declared_range(self, chain_id: str) -> tuple[int, int] | None:
        """Author-numbering span the chain declares, or None if it declares none."""
        nums = [
            k.auth_seq_id for k in self.declared if k.auth_asym_id == chain_id
        ]
        return (min(nums), max(nums)) if nums else None

    def n_declared(self, chain_id: str) -> int:
        return sum(1 for k in self.declared if k.auth_asym_id == chain_id)

    def case_insensitive_matches(self, chain_id: str) -> list[str]:
        return [c for c in self.chain_ids if c.lower() == chain_id.lower()]


def _max_occupancies(target: Target) -> dict[ResidueKey, float]:
    """Highest occupancy among each residue's atoms.

    :func:`low_occupancy_residues` already owns the threshold decision; this
    exists only to put the actual number in the evidence, so a reader can
    disagree with the threshold without re-running anything. ``_icode`` is
    borrowed from :mod:`..structure` rather than reimplemented so that the
    mmCIF single-space convention has one definition in the package.
    """
    out: dict[ResidueKey, float] = {}
    for chain in target.st[0]:
        for res in chain.get_polymer():
            if not len(res):
                continue
            key = ResidueKey(chain.name, res.seqid.num, _icode(res.seqid.icode))
            out[key] = max(atom.occ for atom in res)
    return out


def _gather(target: Target) -> _Evidence:
    from_category = unobserved_from_cif_category(target)
    return _Evidence(
        target=target,
        chain_ids=tuple(target.chain_ids),
        declared=frozenset(declared_residues(target)),
        observed=frozenset(observed_residues(target)),
        low_occupancy=frozenset(low_occupancy_residues(target)),
        occupancies=_max_occupancies(target),
        from_category=(
            None if from_category is None else frozenset(from_category)
        ),
        from_alignment=frozenset(unobserved_from_alignment(target)),
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


def _no_such_chain(key: ResidueKey, ev: _Evidence) -> Finding:
    present = list(ev.chain_ids)
    matches = ev.case_insensitive_matches(key.auth_asym_id)
    listed = ", ".join(present) if present else "none"
    message = (
        f"chain {key.auth_asym_id!r} does not exist in {ev.entry_id}; "
        f"the polymer chains present are: {listed}"
    )
    if matches:
        # Worth calling out by name: it is a one-character fix, and the user is
        # otherwise likely to go looking for a missing chain that is right there.
        message += (
            f". This looks like a letter-case mismatch — "
            f"chain {matches[0]!r} exists and differs only in case"
        )
    return _finding(
        Severity.KILL,
        "NO_SUCH_CHAIN",
        message,
        key,
        chains_present=present,
        case_insensitive_matches=matches,
        entry_id=ev.entry_id,
    )


def _not_declared(key: ResidueKey, ev: _Evidence) -> Finding:
    span = ev.declared_range(key.auth_asym_id)
    if span is not None:
        message = (
            f"residue {key} is not in the declared sequence of {ev.entry_id} at "
            f"all (chain {key.auth_asym_id} declares residues {span[0]}-"
            f"{span[1]}). This is usually a wrong chain id or a typo'd residue "
            f"number, not a gap in the model"
        )
    else:
        # Reached when the chain exists in the coordinates but no declared
        # residue could be named in author numbering — which happens when
        # `_declared_by_offset` finds the label-to-author offset is not a single
        # constant (mid-chain renumbering or insertion codes) and omits the
        # chain rather than guessing. Blaming a typo here would be wrong and
        # would send the user looking for a mistake they did not make: the
        # residue may well be declared, we simply cannot say which author
        # number it has.
        message = (
            f"residue {key}: chain {key.auth_asym_id} exists in {ev.entry_id} "
            f"but its declared numbering could not be reconciled with the "
            f"coordinates, so no residue on it can be confirmed. This is a "
            f"property of the entry, not necessarily a mistake in your hotspot "
            f"— check the chain's numbering by hand before trusting it"
        )
    return _finding(
        Severity.KILL,
        "NOT_DECLARED",
        message,
        key,
        declared_min=span[0] if span else None,
        declared_max=span[1] if span else None,
        n_declared=ev.n_declared(key.auth_asym_id),
        entry_id=ev.entry_id,
    )


def _route_opinions(key: ResidueKey, ev: _Evidence) -> dict[str, Any]:
    """Both detection routes' opinions, for the evidence block.

    ``in_unobs_category`` is ``None``, not ``False``, when the category is
    absent: the entry made no statement, and recording a bare ``False`` would
    let a later reader infer the entry had vouched for the residue.
    """
    return {
        "in_unobs_category": (
            None if ev.from_category is None else key in ev.from_category
        ),
        "in_derived_gap": key in ev.from_alignment,
        "unobs_category_present": ev.from_category is not None,
    }


def _unmodelled(key: ResidueKey, ev: _Evidence) -> Finding:
    message = (
        f"residue {key} is declared in {ev.entry_id} but was never observed — "
        f"it has no atoms in the coordinates, so there is nothing for a binder "
        f"to contact"
    )
    return _finding(
        Severity.KILL,
        "UNMODELLED",
        message,
        key,
        entry_id=ev.entry_id,
        **_route_opinions(key, ev),
    )


def _resolved(key: ResidueKey, ev: _Evidence) -> Finding:
    return _finding(
        Severity.PASS,
        "RESOLVED",
        f"residue {key} is declared and present in the coordinates of "
        f"{ev.entry_id}",
        key,
        entry_id=ev.entry_id,
        # Indexed, not .get(): RESOLVED is only emitted for an observed
        # residue, and every observed residue is in the map by
        # construction. A KeyError here would mean that invariant broke,
        # which should be loud rather than a null in the evidence.
        occupancy=ev.occupancies[key],
    )


def _low_occupancy(key: ResidueKey, ev: _Evidence) -> Finding:
    # Indexed for the same reason as in `_resolved`; a None here would
    # also crash the format below, just less informatively.
    occ = ev.occupancies[key]
    return _finding(
        Severity.WARN,
        "LOW_OCCUPANCY",
        f"residue {key} has atoms but all at occupancy {occ:.2f}, at or below "
        f"the {LOW_OCCUPANCY_THRESHOLD} threshold — it is in the file but was "
        f"not really resolved",
        key,
        occupancy=occ,
        threshold=LOW_OCCUPANCY_THRESHOLD,
        entry_id=ev.entry_id,
    )


def _routes_disagree(key: ResidueKey, ev: _Evidence) -> Finding:
    # `_check_one` only calls this when the category exists, so re-checking for
    # None here would be a branch no test could ever falsify. Asserting the
    # precondition instead keeps the dead branch out of the file.
    assert ev.from_category is not None, "caller must check the category exists"
    in_category = key in ev.from_category
    in_derived = key in ev.from_alignment
    return _finding(
        Severity.WARN,
        "DETECTION_ROUTES_DISAGREE",
        f"residue {key}: the entry's _pdbx_unobs_or_zero_occ_residues category "
        f"says {'unobserved' if in_category else 'observed'} but "
        f"declared-minus-observed says "
        f"{'unobserved' if in_derived else 'observed'}. The deposition is "
        f"internally inconsistent; the coordinates were believed",
        key,
        entry_id=ev.entry_id,
        **_route_opinions(key, ev),
    )


def _no_unobs_category(ev: _Evidence) -> Finding:
    return _finding(
        Severity.WARN,
        "NO_UNOBS_CATEGORY",
        f"{ev.entry_id} omits the optional "
        f"_pdbx_unobs_or_zero_occ_residues category, so the entry does not "
        f"declare which residues are unmodelled. Only the derived route "
        f"(declared sequence minus observed coordinates) was available and the "
        f"two routes could not be cross-checked — confidence is reduced",
        None,
        unobs_category_present=False,
        route_used="alignment",
        n_derived_unobserved=len(ev.from_alignment),
        entry_id=ev.entry_id,
    )


def _check_one(key: ResidueKey, ev: _Evidence) -> list[Finding]:
    """All findings for one residue: one existence verdict, plus qualifiers."""
    if key.auth_asym_id not in ev.chain_ids:
        return [_no_such_chain(key, ev)]
    if key not in ev.declared:
        return [_not_declared(key, ev)]

    out: list[Finding] = []
    # The coordinates decide. The annotation only gets to raise a disagreement.
    if key in ev.observed:
        out.append(_resolved(key, ev))
        if key in ev.low_occupancy:
            out.append(_low_occupancy(key, ev))
    else:
        out.append(_unmodelled(key, ev))

    if ev.from_category is not None:
        if (key in ev.from_category) != (key in ev.from_alignment):
            out.append(_routes_disagree(key, ev))
    return out


def check_resolved(target: Target, keys: Sequence[ResidueKey]) -> list[Finding]:
    """Check that each hotspot residue exists and has coordinates.

    Args:
        target: loaded structure, from
            :func:`hotspot_preflight.structure.load_target`.
        keys: hotspot residues in canonical author numbering.

    Returns:
        Findings in **caller order**: the residues' findings in the order
        ``keys`` gave them, followed by any site-level findings. The order a
        user writes hotspots in sometimes reflects priority — the same reason
        :func:`hotspot_preflight.residue.parse_hotspot_spec` preserves
        first-seen order — so sorting here would silently discard it. A caller
        wanting the canonical presentation order pipes the result through
        :func:`hotspot_preflight.findings.sort_findings`, which is what the
        report builder does when it writes the run record.

        Each residue yields exactly one of ``NO_SUCH_CHAIN``, ``NOT_DECLARED``,
        ``UNMODELLED`` or ``RESOLVED``, optionally joined by ``LOW_OCCUPANCY``
        or ``DETECTION_ROUTES_DISAGREE``. ``RESOLVED`` plus ``LOW_OCCUPANCY`` is
        deliberate: a zero-occupancy residue does exist in the file, so killing
        it would overstate the case, but it was not really resolved either, so
        passing it silently would understate it.

        A single ``NO_UNOBS_CATEGORY`` warning is appended when the entry omits
        ``_pdbx_unobs_or_zero_occ_residues``, including when ``keys`` is empty —
        reduced confidence is a property of the entry, not of the hotspot list.

    Burial and exposure are deliberately not judged here; the ``burial`` check
    owns that, and a residue can be perfectly resolved and still useless.
    """
    ev = _gather(target)
    findings: list[Finding] = []
    for key in keys:
        findings.extend(_check_one(key, ev))
    if ev.from_category is None:
        findings.append(_no_unobs_category(ev))
    return findings
