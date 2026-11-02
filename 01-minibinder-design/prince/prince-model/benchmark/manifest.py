# SPDX-License-Identifier: MIT
"""The shippable manifest: the only benchmark artefact that goes into git.

No coordinates, no bulk archives. The manifest names what to download and what
the label is; ``scripts/build_benchmark.py --coords-only`` fetches the rest.
That keeps the repo small and, more importantly, keeps us clear of every
licence question about redistributing somebody else's data.

**Residue keys are stored as ``chain:seq`` or ``chain:seq:icode``.** The compact
form ``W88`` that the design tools use is ambiguous to read back: an auth chain
id may itself end in a digit (mmCIF allows it), so ``A1405`` could be chain A
residue 1405 or chain A1 residue 405. The colon form is lossless, and
:func:`format_residues` / :func:`parse_residues` round-trip it. 6AL0 chain A has
a 13-residue insertion at 263A-263L, so the insertion-code field is not
theoretical.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterable, Sequence

from hotspot_preflight.residue import NO_ICODE, ResidueKey

__all__ = [
    "MANIFEST_COLUMNS",
    "ManifestRow",
    "format_residue_key",
    "parse_residue_key",
    "format_residues",
    "parse_residues",
    "format_chain_resolution",
    "write_manifest",
    "read_manifest",
    "DroppedRow",
    "write_dropped",
]

_RESIDUE_SEP = ";"
_CHAIN_SEP = "|"


def format_residue_key(key: ResidueKey) -> str:
    """``chain:seq`` normally, ``chain:seq:icode`` when an insertion code exists."""
    if key.has_icode:
        return f"{key.auth_asym_id}:{key.auth_seq_id}:{key.icode}"
    return f"{key.auth_asym_id}:{key.auth_seq_id}"


def parse_residue_key(text: str) -> ResidueKey:
    """Inverse of :func:`format_residue_key`.

    Raises:
        ValueError: on anything it cannot read exactly. A manifest that parses
            loosely is a manifest that silently changes the labels.
    """
    parts = text.strip().split(":")
    if len(parts) == 2:
        chain, number = parts
        icode = NO_ICODE
    elif len(parts) == 3:
        chain, number, icode = parts
        icode = icode or NO_ICODE
    else:
        raise ValueError(
            f"cannot read {text!r} as a residue key; expected 'chain:seq' or "
            f"'chain:seq:icode'"
        )
    try:
        return ResidueKey(chain, int(number), icode)
    except ValueError as exc:
        raise ValueError(f"cannot read {text!r} as a residue key: {exc}") from exc


def format_residues(keys: Iterable[ResidueKey]) -> str:
    return _RESIDUE_SEP.join(format_residue_key(k) for k in keys)


def parse_residues(text: str) -> tuple[ResidueKey, ...]:
    if not text.strip():
        return ()
    return tuple(
        parse_residue_key(part)
        for part in text.split(_RESIDUE_SEP)
        if part.strip()
    )


def format_chain_resolution(resolutions: Iterable[object]) -> str:
    """``A->L=label|V=auth|W=auth``, one entry per annotated antigen chain.

    Takes anything whose ``str()`` is a ``ChainResolution`` rendering, so the
    manifest module does not import the epitope module.
    """
    return _CHAIN_SEP.join(str(r) for r in resolutions)


@dataclass(frozen=True)
class ManifestRow:
    """One antibody instance and its epitope label.

    ``epitope_residues`` is the union over all protein antigen chains (guard 2).
    ``dominant_chain`` and ``n_epitope_dominant`` are carried alongside because
    a published epitope refers to one antigen chain, so comparing a paper's
    residue count against the union is an apples-to-oranges error waiting to
    happen. Keeping both in the file makes the distinction impossible to miss.

    ``chain_resolution`` records, for **every** chain SAbDab annotated, which
    identifier namespace answered for it — ``A->L=label``, ``C=non_polymer``,
    and so on (guard 5). It is in the shipped file rather than only in the
    build log because the namespace is part of the label's provenance: an
    epitope whose antigen chain came from ``label`` was derived against a chain
    the summary table named in a different namespace than the coordinates use,
    and a reader comparing against SAbDab's own numbering needs to know that.
    It also makes the one failure mode that cannot be detected downstream —
    a wrong chain that yields a complete, plausible epitope — auditable by
    grepping one column.
    """

    instance_id: str
    pdb_id: str
    heavy_chain: str
    light_chain: str
    antigen_chains: str
    epitope_residues: str
    n_epitope: int
    dominant_chain: str
    n_epitope_dominant: int
    cluster_id: str
    split: str
    cutoff_angstrom: float
    method: str
    resolution: str
    chain_resolution: str = ""

    @classmethod
    def from_epitope(
        cls,
        result,
        heavy_chain: str | None,
        light_chain: str | None,
        cluster_id: str,
        split: str,
        method: str,
        resolution: float | None,
        chain_resolution: Iterable[object] = (),
    ) -> "ManifestRow":
        return cls(
            instance_id=result.instance_id,
            pdb_id=result.pdb_id.lower(),
            heavy_chain=heavy_chain or "",
            light_chain=light_chain or "",
            antigen_chains=_CHAIN_SEP.join(result.antigen_chains),
            epitope_residues=format_residues(result.residues),
            n_epitope=result.size,
            dominant_chain=result.dominant_chain or "",
            n_epitope_dominant=len(result.dominant_residues),
            cluster_id=cluster_id,
            split=split,
            cutoff_angstrom=result.cutoff,
            method=method,
            resolution="" if resolution is None else f"{resolution:.2f}",
            chain_resolution=format_chain_resolution(chain_resolution),
        )

    @property
    def residues(self) -> tuple[ResidueKey, ...]:
        return parse_residues(self.epitope_residues)

    @property
    def antigen_chain_list(self) -> tuple[str, ...]:
        if not self.antigen_chains:
            return ()
        return tuple(self.antigen_chains.split(_CHAIN_SEP))

    @property
    def resolution_namespaces(self) -> tuple[str, ...]:
        """The namespace token of each annotated chain, in annotation order."""
        return tuple(
            part.rsplit("=", 1)[-1]
            for part in self.chain_resolution.split(_CHAIN_SEP)
            if part.strip()
        )


MANIFEST_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(ManifestRow))


def write_manifest(rows: Sequence[ManifestRow], path: Path | str) -> Path:
    """Write the manifest CSV, sorted, so two builds produce identical bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MANIFEST_COLUMNS))
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (r.pdb_id, r.instance_id)):
            writer.writerow({name: getattr(row, name) for name in MANIFEST_COLUMNS})
    return path


def read_manifest(path: Path | str) -> list[ManifestRow]:
    """Read a manifest back, validating its columns.

    Raises:
        ValueError: if the header does not match :data:`MANIFEST_COLUMNS`.
            Reading a manifest from a different version of this code and
            silently filling defaults would produce a benchmark that is neither
            version.
    """
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        if header != MANIFEST_COLUMNS:
            raise ValueError(
                f"{path} has columns {header}, expected {MANIFEST_COLUMNS}"
            )
        out: list[ManifestRow] = []
        for record in reader:
            out.append(
                ManifestRow(
                    instance_id=record["instance_id"],
                    pdb_id=record["pdb_id"],
                    heavy_chain=record["heavy_chain"],
                    light_chain=record["light_chain"],
                    antigen_chains=record["antigen_chains"],
                    epitope_residues=record["epitope_residues"],
                    n_epitope=int(record["n_epitope"]),
                    dominant_chain=record["dominant_chain"],
                    n_epitope_dominant=int(record["n_epitope_dominant"]),
                    cluster_id=record["cluster_id"],
                    split=record["split"],
                    cutoff_angstrom=float(record["cutoff_angstrom"]),
                    method=record["method"],
                    resolution=record["resolution"],
                    chain_resolution=record["chain_resolution"],
                )
            )
    return out


@dataclass(frozen=True)
class DroppedRow:
    """An instance that did not make the benchmark, and why.

    This file ships next to the manifest. An unexamined drop log is how a
    systematic bug — one wrong chain-resolution rule, say — hides as "a few
    small interfaces". The reason strings are machine-groupable on purpose.
    """

    instance_id: str
    pdb_id: str
    reason: str
    detail: str = ""


def write_dropped(rows: Sequence[DroppedRow], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["instance_id", "pdb_id", "reason", "detail"])
        for row in sorted(rows, key=lambda r: (r.reason, r.pdb_id, r.instance_id)):
            writer.writerow([row.instance_id, row.pdb_id, row.reason, row.detail])
    return path
