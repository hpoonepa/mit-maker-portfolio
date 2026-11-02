# SPDX-License-Identifier: MIT
"""The numbering contract.

Every residue in this codebase is identified by a :class:`ResidueKey`, and
nothing outside this module may build a residue identifier from a bare integer.

The reason is concrete. Design tools disagree about residue numbering:

* RFdiffusion takes author numbering, e.g. ``ppi.hotspot_res=[A30,A33]``
* BindCraft takes author numbering, e.g. ``A30-33,B12``
* BoltzGen indexes binding-site residues by mmCIF ``label_seq_id``, which is a
  1-indexed count along the entity and generally does *not* equal the author
  number

A hotspot list that is correct for one tool is therefore silently wrong for
another: no error is raised, the design job simply aims somewhere else. Keeping
one canonical representation and converting only through named, tested
functions is how we stop that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

__all__ = [
    "ResidueKey",
    "HotspotParseError",
    "parse_hotspot_spec",
    "to_rfdiffusion",
    "to_bindcraft",
    "to_boltzgen",
]

NO_ICODE = " "
"""mmCIF represents 'no insertion code' as a single space, not an empty string."""


class HotspotParseError(ValueError):
    """A hotspot specification could not be parsed unambiguously."""


@dataclass(frozen=True, order=True)
class ResidueKey:
    """A single residue, in author (PDB-deposited) numbering.

    Author numbering is the canonical internal scheme because it is what
    structure viewers display, what papers cite, and what two of the three
    major design tools consume. ``label_seq_id`` and 0-based indices are
    derived on demand, never stored.

    Args:
        auth_asym_id: Author chain identifier. gemmi exposes this as
            ``Chain.name``. May be more than one character in mmCIF.
        auth_seq_id: Author residue number. gemmi exposes this as
            ``Residue.seqid.num``. Legitimately negative for expression tags.
        icode: Insertion code, gemmi's ``Residue.seqid.icode``. A single space
            means none.
    """

    auth_asym_id: str
    auth_seq_id: int
    icode: str = field(default=NO_ICODE)

    def __post_init__(self) -> None:
        if not self.auth_asym_id:
            raise ValueError("auth_asym_id must not be empty")
        if len(self.icode) != 1:
            raise ValueError(
                f"icode must be exactly one character (a space means none), "
                f"got {self.icode!r}"
            )

    @property
    def has_icode(self) -> bool:
        return self.icode != NO_ICODE

    def __str__(self) -> str:
        suffix = self.icode if self.has_icode else ""
        return f"{self.auth_asym_id}{self.auth_seq_id}{suffix}"


# Chain ids start with a letter; the number may be negative; an optional
# trailing single letter is an insertion code. The chain group is lazy so that
# "AA405" resolves to chain "AA" rather than failing on chain "A".
_SINGLE_RE = re.compile(
    r"^(?P<chain>[A-Za-z][A-Za-z0-9_]*?)(?P<num>-?\d+)(?P<icode>[A-Za-z])?$"
)

# Ranges use non-negative numbers only, so that "A-3" is unambiguously the
# single residue -3 rather than a malformed range.
_RANGE_RE = re.compile(
    r"^(?P<c1>[A-Za-z][A-Za-z0-9_]*?)(?P<n1>\d+)"
    r"-(?P<c2>[A-Za-z][A-Za-z0-9_]*)?(?P<n2>\d+)$"
)

_BARE_NUMBER_RE = re.compile(r"^-?\d+$")


def parse_hotspot_spec(spec: str) -> list[ResidueKey]:
    """Parse a human-written hotspot specification into canonical keys.

    Accepts the union of the syntaxes the design tools use, so that a user can
    paste what they already have:

    * ``"A405"`` — one residue
    * ``"A405,A408"`` — a list
    * ``"A405-407"`` — an inclusive range
    * ``"[A30,A33]"`` — RFdiffusion's bracketed form
    * ``"A52A"`` — with an insertion code

    Duplicates are removed and first-seen order is preserved, because the order
    a user writes hotspots in sometimes reflects priority.

    Raises:
        HotspotParseError: on anything ambiguous. In particular a bare number
            with no chain is rejected rather than guessed at, since assuming a
            chain is exactly the silent-misaim bug this module exists to stop.
    """
    cleaned = spec.strip().strip("[]").strip()
    if not cleaned:
        raise HotspotParseError("empty hotspot specification")

    keys: list[ResidueKey] = []
    seen: set[ResidueKey] = set()

    for raw in cleaned.split(","):
        token = raw.strip()
        if not token:
            continue
        for key in _parse_token(token):
            if key not in seen:
                seen.add(key)
                keys.append(key)

    if not keys:
        raise HotspotParseError(f"no residues found in {spec!r}")
    return keys


def _parse_token(token: str) -> list[ResidueKey]:
    if m := _RANGE_RE.match(token):
        c1, c2 = m.group("c1"), m.group("c2")
        if c2 is not None and c2 != c1:
            raise HotspotParseError(
                f"range {token!r} spans two chains ({c1} and {c2}); "
                f"write one range per chain"
            )
        start, end = int(m.group("n1")), int(m.group("n2"))
        if end < start:
            raise HotspotParseError(
                f"range {token!r} runs backwards ({start} to {end})"
            )
        return [ResidueKey(c1, n) for n in range(start, end + 1)]

    if m := _SINGLE_RE.match(token):
        return [
            ResidueKey(
                m.group("chain"),
                int(m.group("num")),
                m.group("icode") or NO_ICODE,
            )
        ]

    if _BARE_NUMBER_RE.match(token):
        raise HotspotParseError(
            f"{token!r} has no chain identifier. Write e.g. 'A{token}' — "
            f"a residue number alone is ambiguous and we will not guess."
        )

    raise HotspotParseError(f"could not parse {token!r} as a residue")


def _require_nonempty(keys: Sequence[ResidueKey]) -> None:
    if not keys:
        raise ValueError("no hotspot residues to emit")


def to_rfdiffusion(keys: Sequence[ResidueKey]) -> str:
    """Emit RFdiffusion's ``ppi.hotspot_res`` form, e.g. ``[A30,A33,B12]``.

    RFdiffusion's documentation recommends 3-6 hotspots; that guidance is
    checked in the patch-geometry check, not here.

    Raises:
        ValueError: if any key carries an insertion code, since RFdiffusion's
            syntax cannot express one. Dropping it silently would aim the design
            at a different residue.
    """
    _require_nonempty(keys)
    for k in keys:
        if k.has_icode:
            raise ValueError(
                f"{k} carries insertion code {k.icode!r}, which RFdiffusion's "
                f"hotspot syntax cannot express"
            )
    return "[" + ",".join(str(k) for k in keys) + "]"


def to_bindcraft(keys: Sequence[ResidueKey]) -> str:
    """Emit BindCraft's ``target_hotspot_residues`` form.

    Consecutive runs on one chain collapse to ``A30-32``, which is the form
    BindCraft's own documentation uses.
    """
    _require_nonempty(keys)
    parts: list[str] = []
    for chain, run in _consecutive_runs(keys):
        if len(run) == 1:
            parts.append(str(run[0]))
        else:
            parts.append(f"{chain}{run[0].auth_seq_id}-{run[-1].auth_seq_id}")
    return ",".join(parts)


def _consecutive_runs(
    keys: Iterable[ResidueKey],
) -> list[tuple[str, list[ResidueKey]]]:
    """Group keys into runs of consecutive numbers on the same chain.

    Input order is preserved. A residue with an insertion code never joins a
    run, because 52 and 52A are not consecutive in any meaningful sense.
    """
    runs: list[tuple[str, list[ResidueKey]]] = []
    for key in keys:
        if runs:
            chain, current = runs[-1]
            last = current[-1]
            joinable = (
                chain == key.auth_asym_id
                and not key.has_icode
                and not last.has_icode
                and key.auth_seq_id == last.auth_seq_id + 1
            )
            if joinable:
                current.append(key)
                continue
        runs.append((key.auth_asym_id, [key]))
    return runs


def to_boltzgen(
    keys: Sequence[ResidueKey],
    label_seq_map: Mapping[ResidueKey, int] | None,
) -> str:
    """Emit BoltzGen-style indices, which are mmCIF ``label_seq_id``.

    This is the conversion that silently breaks campaigns. BoltzGen does not
    use author numbering, so emitting author numbers here would produce a file
    that loads cleanly and targets the wrong residues.

    Args:
        keys: residues in canonical author numbering.
        label_seq_map: mapping built from the structure by
            :func:`hotspot_preflight.structure.build_label_seq_map`. Required —
            there is no safe default.

    Raises:
        ValueError: if ``label_seq_map`` is None.
        KeyError: if any key is absent from the map, which means the residue is
            not in the structure and must be investigated rather than skipped.
    """
    _require_nonempty(keys)
    if label_seq_map is None:
        raise ValueError(
            "to_boltzgen requires a label_seq map: BoltzGen uses mmCIF "
            "label_seq_id, not author numbering, so author numbers cannot be "
            "passed through. Build one with structure.build_label_seq_map()."
        )
    missing = [k for k in keys if k not in label_seq_map]
    if missing:
        # "not observed in the coordinates", not "not present in the structure":
        # the usual cause is a residue the entry declares in its polymer sequence
        # but never modelled, which is present in the entry and absent from the
        # atoms. Saying "not present" sends the user looking for a typo in a
        # hotspot list that is correct.
        raise KeyError(
            f"no label_seq_id for {', '.join(str(k) for k in missing)} — "
            f"these residues are not observed in the coordinates, so they may "
            f"be declared in the entry but unmodelled"
        )
    return ",".join(f"{k.auth_asym_id}{label_seq_map[k]}" for k in keys)
