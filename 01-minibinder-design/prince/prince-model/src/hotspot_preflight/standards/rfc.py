# SPDX-License-Identifier: MIT
"""iGEM assembly standards: reverse-translate a binder CDS that is legal to clone.

This is not a sequence-screening module. The real task, and the only direct
path from a protein-design tool to a genetic-design standard, is: **take the
binder's amino acid sequence, choose codons for it, and avoid the restriction
sites the assembly standard forbids — including the ones created at the
prefix/suffix seams, which exist in neither the part nor the flank alone.**

Two published standards are covered.

**RFC 10** (BioBrick assembly; MIT DSpace handle ``1721.1/45138``) forbids
EcoRI, XbaI, SpeI and PstI sites inside a part. All four recognition sites are
palindromic — each is its own reverse complement — so a single forward-strand
scan cannot miss a reverse-strand occurrence. :func:`find_sites` is still given
an explicit ``both_strands`` argument rather than deciding for itself, and the
test suite *proves* the palindromicity rather than asserting the conclusion.

**RFC 1000** (Type IIS assembly) forbids BsaI and SapI sites. These are
**not** palindromic: BsaI reads ``GGTCTC`` forward and ``GAGACC`` on the
reverse strand, SapI ``GCTCTTC`` and ``GAAGAGC``. A forward-only scan silently
passes a CDS that an enzyme will happily cut. That is the obvious bug in any
implementation of this, and ``both_strands=True`` is mandatory for RFC 1000.

**Scope.** This module implements the published RFC 10 and RFC 1000
sequence constraints. Current iGEM submission requirements should be checked
against the competition's own guidance.

**The seam, and the trap inside it.** The RFC 10 prefix and suffix themselves
contain EcoRI, NotI and XbaI, and SpeI, NotI and PstI respectively — by
construction, since those are the assembly's own cut sites. So a junction-aware
scan must flag only the sites whose span *overlaps the insert*; treating the
standard's own flanking sites as violations would make
:func:`reverse_translate` try to repair a sequence it does not own, and never
terminate. Flank sequences are supplied by the caller, because the exact flanks
depend on the assembly plan.
"""

from __future__ import annotations

import random
from typing import Mapping

__all__ = [
    "RFC10_FORBIDDEN",
    "RFC10_DISCOURAGED",
    "RFC1000_FORBIDDEN",
    "STANDARDS",
    "CODON_USAGE",
    "GENETIC_CODE",
    "RARE_CODON_MIN_USAGE",
    "ReverseTranslationError",
    "reverse_complement",
    "translate",
    "find_sites",
    "reverse_translate",
    "check_rfc_compliance",
]

RFC10_FORBIDDEN: dict[str, str] = {
    "EcoRI": "GAATTC",
    "XbaI": "TCTAGA",
    "SpeI": "ACTAGT",
    "PstI": "CTGCAG",
}
"""RFC 10 illegal sites. All palindromic, so one strand suffices."""

RFC10_DISCOURAGED: dict[str, str] = {"NotI": "GCGGCCGC"}
"""RFC 10 advises avoiding NotI. Avoid, not illegal — reported separately."""

RFC1000_FORBIDDEN: dict[str, str] = {"BsaI": "GGTCTC", "SapI": "GCTCTTC"}
"""RFC 1000 illegal sites. Type IIS and **not** palindromic: scan both strands."""

STANDARDS: dict[str, dict[str, object]] = {
    "RFC10": {
        "forbidden": RFC10_FORBIDDEN,
        "discouraged": RFC10_DISCOURAGED,
        # Every RFC 10 site is its own reverse complement, so the reverse
        # strand carries no information the forward scan has not already seen.
        "both_strands": False,
    },
    "RFC1000": {
        "forbidden": RFC1000_FORBIDDEN,
        "discouraged": {},
        # Type IIS sites are asymmetric. Omitting this is the bug.
        "both_strands": True,
    },
}

_COMPLEMENT = str.maketrans("ACGT", "TGCA")

# Relative synonymous codon usage in Escherichia coli K-12, rounded to two
# decimals. Ordering and magnitudes follow the Kazusa codon usage database
# (Nakamura et al. 2000); they are used to weight codon choice, not reported as
# measurements. Stop is fixed to TAA, E. coli's dominant terminator.
CODON_USAGE: dict[str, dict[str, float]] = {
    "A": {"GCG": 0.36, "GCC": 0.27, "GCA": 0.21, "GCT": 0.16},
    "R": {"CGC": 0.40, "CGT": 0.38, "CGG": 0.10, "CGA": 0.06, "AGA": 0.04, "AGG": 0.02},
    "N": {"AAC": 0.55, "AAT": 0.45},
    "D": {"GAT": 0.63, "GAC": 0.37},
    "C": {"TGC": 0.56, "TGT": 0.44},
    "Q": {"CAG": 0.65, "CAA": 0.35},
    "E": {"GAA": 0.68, "GAG": 0.32},
    "G": {"GGC": 0.40, "GGT": 0.34, "GGG": 0.15, "GGA": 0.11},
    "H": {"CAT": 0.57, "CAC": 0.43},
    "I": {"ATT": 0.51, "ATC": 0.42, "ATA": 0.07},
    "L": {"CTG": 0.50, "TTA": 0.13, "TTG": 0.13, "CTC": 0.10, "CTT": 0.10, "CTA": 0.04},
    "K": {"AAA": 0.76, "AAG": 0.24},
    "M": {"ATG": 1.00},
    "F": {"TTT": 0.57, "TTC": 0.43},
    "P": {"CCG": 0.52, "CCA": 0.19, "CCT": 0.16, "CCC": 0.13},
    "S": {"AGC": 0.28, "TCT": 0.15, "TCC": 0.15, "AGT": 0.15, "TCG": 0.15, "TCA": 0.12},
    "T": {"ACC": 0.44, "ACG": 0.27, "ACT": 0.17, "ACA": 0.13},
    "W": {"TGG": 1.00},
    "Y": {"TAT": 0.57, "TAC": 0.43},
    "V": {"GTG": 0.37, "GTT": 0.26, "GTC": 0.22, "GTA": 0.15},
    "*": {"TAA": 1.00},
}

GENETIC_CODE: dict[str, str] = {
    codon: aa for aa, codons in CODON_USAGE.items() for codon in codons
}
"""Codon to amino acid, for the subset of codons :func:`reverse_translate` may
emit. Completed below with the synonymous codons omitted above as rare, so
that :func:`translate` can read back any standard CDS."""

# The codons left out of CODON_USAGE above (E. coli uses them, just rarely
# enough that we never choose them). They are needed so that translate() works
# on sequences this module did not write.
GENETIC_CODE.update(
    {
        "CTA": "L",
        "TTA": "L",
        "TTG": "L",
        "TAG": "*",
        "TGA": "*",
    }
)

RARE_CODON_MIN_USAGE = 0.10
"""Codons below this relative usage are not chosen.

A designed binder that cannot be expressed is not a design. Rare codons are
excluded from the initial pass *and* from repairs, and if that makes a site
unavoidable the error says so rather than quietly emitting a rare codon.
"""

_MAX_REPAIR_ROUNDS_PER_CODON = 8
"""Bound on the repair loop, as a multiple of the protein length."""


class ReverseTranslationError(ValueError):
    """No codon assignment avoids a forbidden site."""


def reverse_complement(dna: str) -> str:
    """Reverse complement of an uppercase A/C/G/T string."""
    return dna.translate(_COMPLEMENT)[::-1]


def _validate_dna(dna: str) -> None:
    for position, base in enumerate(dna):
        if base not in "ACGT":
            raise ValueError(
                f"{base!r} at position {position} is not an unambiguous DNA "
                f"base; this module works on uppercase A/C/G/T only"
            )


def translate(dna: str) -> str:
    """Translate a CDS. Used to assert that reverse translation is lossless."""
    _validate_dna(dna)
    if len(dna) % 3:
        raise ValueError(f"CDS length {len(dna)} is not a multiple of 3")
    out: list[str] = []
    for i in range(0, len(dna), 3):
        codon = dna[i : i + 3]
        if codon not in GENETIC_CODE:
            raise ValueError(f"codon {codon!r} at position {i} is not in the table")
        out.append(GENETIC_CODE[codon])
    return "".join(out)


def find_sites(
    dna: str, patterns: Mapping[str, str], *, both_strands: bool
) -> list[tuple[str, int]]:
    """Locate recognition sites in ``dna``.

    Args:
        dna: uppercase A/C/G/T.
        patterns: ``{enzyme name: recognition site}``.
        both_strands: when true, also searches each site's reverse complement.
            Mandatory for asymmetric Type IIS sites such as BsaI and SapI, and
            redundant (but harmless) for palindromic ones. There is no default:
            getting this wrong is the headline bug in this area, so the caller
            states the intent.

    Returns:
        ``[(enzyme name, position)]`` sorted by position then name, with
        overlapping occurrences all reported. Positions are 0-based indices
        **into the supplied strand**; a reverse-strand occurrence is reported
        at the position where the site's reverse complement begins, so that one
        coordinate system suffices to locate the codon that must change.
    """
    _validate_dna(dna)
    hits: set[tuple[str, int]] = set()
    for name, site in patterns.items():
        _validate_dna(site)
        needles = {site}
        if both_strands:
            needles.add(reverse_complement(site))
        for needle in needles:
            start = dna.find(needle)
            while start != -1:
                hits.add((name, start))
                start = dna.find(needle, start + 1)
    return sorted(hits, key=lambda hit: (hit[1], hit[0]))


def _choose_codons(
    protein: str, table: Mapping[str, Mapping[str, float]], rng: random.Random
) -> list[str]:
    """One weighted draw per residue, restricted to non-rare codons."""
    codons: list[str] = []
    for position, aa in enumerate(protein, start=1):
        options = _options(aa, table, position)
        weights = [options[c] for c in options]
        codons.append(rng.choices(list(options), weights=weights, k=1)[0])
    return codons


def _options(
    aa: str, table: Mapping[str, Mapping[str, float]], position: int
) -> dict[str, float]:
    if aa not in table:
        raise ValueError(
            f"{aa!r} at residue {position} is not an amino acid this codon "
            f"table can encode; expected one of {''.join(sorted(table))}"
        )
    usable = {
        codon: usage
        for codon, usage in table[aa].items()
        if usage >= RARE_CODON_MIN_USAGE
    }
    # Met, Trp and the stop have a single codon whose usage is 1.0, so the
    # floor never empties a set in the standard table; a caller-supplied table
    # might, and silently falling back to rare codons would hide that.
    if not usable:
        raise ValueError(
            f"every codon for {aa!r} at residue {position} is below the rare "
            f"codon floor of {RARE_CODON_MIN_USAGE}"
        )
    return usable


def _violations(
    codons: list[str],
    patterns: Mapping[str, str],
    both_strands: bool,
    prefix: str,
    suffix: str,
) -> list[tuple[str, int, int]]:
    """Sites that overlap the insert, as ``(name, site start, site end)``.

    Coordinates are in the full ``prefix + cds + suffix`` string. Sites lying
    wholly inside a flank are excluded: the RFC 10 prefix and suffix contain
    the standard's own cut sites, and trying to repair them would never finish.
    """
    cds = "".join(codons)
    full = prefix + cds + suffix
    insert_start = len(prefix)
    insert_end = insert_start + len(cds)

    out: list[tuple[str, int, int]] = []
    for name, start in find_sites(full, patterns, both_strands=both_strands):
        end = start + len(patterns[name])
        if start < insert_end and end > insert_start:
            out.append((name, start, end))
    return out


def reverse_translate(
    protein: str,
    *,
    forbidden: Mapping[str, str],
    codon_table: str = "e_coli",
    seed: int = 0,
    prefix: str = "",
    suffix: str = "",
) -> str:
    """Choose a CDS for ``protein`` that carries no ``forbidden`` site.

    Args:
        protein: one-letter amino acids, ``*`` for a stop. Preserved exactly —
            the result is translated back and compared before it is returned.
        forbidden: ``{enzyme name: site}``, e.g. :data:`RFC10_FORBIDDEN`. Both
            strands are always scanned here, because a site the caller cares
            about on one strand is a site on the other for any asymmetric
            enzyme and the cost of the extra scan is nil.
        codon_table: only ``"e_coli"`` is available.
        seed: makes the result deterministic. Codons are drawn with weights
            from :data:`CODON_USAGE`, so a different seed gives a different but
            equally valid synonymous variant — useful when one seed hits an
            unavoidable site.
        prefix: sequence immediately 5' of the insert, if the CDS will be
            cloned into a scar. Scanned for sites that *span the seam*.
        suffix: sequence immediately 3' of the insert, likewise.

    Returns:
        The CDS alone, without ``prefix`` or ``suffix``.

    Raises:
        ValueError: on an unknown amino acid or codon table.
        ReverseTranslationError: when no synonymous substitution removes a
            site. The message names the codon position, the enzyme and the
            alternatives tried, rather than looping until something times out.
    """
    if codon_table != "e_coli":
        raise ValueError(
            f"unknown codon table {codon_table!r}; only 'e_coli' is available"
        )
    _validate_dna(prefix)
    _validate_dna(suffix)

    rng = random.Random(seed)
    table = CODON_USAGE
    codons = _choose_codons(protein, table, rng)

    budget = _MAX_REPAIR_ROUNDS_PER_CODON * len(codons) + 16
    for _ in range(budget):
        violations = _violations(codons, forbidden, True, prefix, suffix)
        if not violations:
            break
        name, start, end = violations[0]
        if not _repair(codons, name, start, end, table, forbidden, prefix, suffix):
            first_codon = max(0, (start - len(prefix)) // 3)
            raise ReverseTranslationError(
                f"{name} site ({forbidden[name]}) at position {start} of "
                f"prefix+CDS+suffix cannot be removed: no non-rare synonymous "
                f"codon for any of the residues it spans "
                f"(codon {first_codon + 1} onwards, residues "
                f"{protein[first_codon : min(len(protein), first_codon + 3)]!r}) "
                f"breaks it. Try a different seed, or change the protein."
            )
    else:  # pragma: no cover - the repair step either succeeds or raises
        raise ReverseTranslationError(
            f"gave up after {budget} repair rounds; the forbidden set may be "
            f"mutually unsatisfiable for this protein"
        )

    cds = "".join(codons)
    if translate(cds) != protein:
        raise RuntimeError(
            "reverse translation changed the protein; this is a bug in "
            "hotspot_preflight.standards.rfc"
        )
    return cds


def _repair(
    codons: list[str],
    name: str,
    start: int,
    end: int,
    table: Mapping[str, Mapping[str, float]],
    forbidden: Mapping[str, str],
    prefix: str,
    suffix: str,
) -> bool:
    """Try to break one site by swapping a synonymous codon.

    Walks the codons the site overlaps left to right and, within each, the
    alternatives in descending usage order, taking the first swap that reduces
    the number of overlapping violations. Deterministic, and it cannot cycle,
    because a swap is only kept when the count strictly drops.
    """
    insert_start = len(prefix)
    first = max(0, (start - insert_start) // 3)
    last = min(len(codons) - 1, (end - 1 - insert_start) // 3)
    before = len(_violations(codons, forbidden, True, prefix, suffix))

    for index in range(first, last + 1):
        current = codons[index]
        aa = GENETIC_CODE[current]
        alternatives = sorted(
            (c for c in _options(aa, table, index + 1) if c != current),
            key=lambda c: (-table[aa][c], c),
        )
        for candidate in alternatives:
            codons[index] = candidate
            after = len(_violations(codons, forbidden, True, prefix, suffix))
            if after < before:
                return True
            codons[index] = current
    return False


def check_rfc_compliance(dna: str, standard: str = "RFC10") -> list[str]:
    """Report a CDS's compliance with an assembly standard.

    Args:
        dna: the part sequence, without assembly flanks. Flank seams are
            :func:`reverse_translate`'s concern, because fixing one means
            changing a codon.
        standard: ``"RFC10"`` or ``"RFC1000"``.

    Returns:
        Human-readable messages, empty when compliant. Forbidden sites and
        discouraged sites are worded differently and never conflated: RFC 10
        advises against NotI, it does not outlaw it.

    Raises:
        ValueError: on an unknown standard or non-ACGT input.
    """
    if standard not in STANDARDS:
        raise ValueError(
            f"unknown standard {standard!r}; available: "
            f"{', '.join(sorted(STANDARDS))}"
        )
    _validate_dna(dna)
    spec = STANDARDS[standard]
    both: bool = spec["both_strands"]  # type: ignore[assignment]
    forbidden: Mapping[str, str] = spec["forbidden"]  # type: ignore[assignment]
    discouraged: Mapping[str, str] = spec["discouraged"]  # type: ignore[assignment]

    strands = "both strands" if both else "the forward strand (site is palindromic)"
    messages = [
        f"{standard}: forbidden {name} site {forbidden[name]} at position "
        f"{position} (scanned {strands})"
        for name, position in find_sites(dna, forbidden, both_strands=both)
    ]
    messages += [
        f"{standard}: discouraged {name} site {discouraged[name]} at position "
        f"{position} — RFC 10 advises avoiding it; it is not illegal"
        for name, position in find_sites(dna, discouraged, both_strands=both)
    ]
    return messages
