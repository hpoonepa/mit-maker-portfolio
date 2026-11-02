# SPDX-License-Identifier: MIT
"""Reading a per-residue score file another tool produced, and normalising it.

Split from :mod:`.external` so that *parsing* and *predicting* are separate
concerns, and because the column rules here are the fiddly, dangerous part.

**Why columns are resolved by name and never by position.** DiscoTope-3.0's
README column list is stale — ``main.py`` inserts ``calibrated_score`` — so any
fixed index is correct for some versions of the tool and silently wrong for
others. "Silently wrong" is the whole problem: an index read of the neighbouring
column yields plausible per-residue numbers that are not the prediction, and
nothing downstream can tell. So a header is matched by name, the score column is
chosen by declared preference (:data:`SCORE_COLUMN_PREFERENCE`), the column
actually used is recorded on :class:`ExternalScoreFile`, and positional reading
survives only as a fallback for a headerless two- or three-column file.

**Licensing, and why nothing here downloads.** This repository is MIT.
DiscoTope-3.0's code is CC BY-NC-4.0 and its data carries no grant at all; SEMA
ships a file labelled MIT whose text actually reads "Copyright (c) 2016 AYLIEN",
which is boilerplate from an unrelated project and is not a licence grant for
SEMA. Vendoring, copying or redistributing any of their code, weights or data
would violate those terms and contaminate this package's licence. So nothing
here fetches, bundles or mirrors anything: it parses a file **you** generated,
under whatever terms apply to you, on your own machine. A path that looks like a
URL is rejected for that reason.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..residue import NO_ICODE, HotspotParseError, ResidueKey, parse_hotspot_spec
from .normalise import UNSCORED, midrank_percentiles

__all__ = [
    "MIN_MATCH_FRACTION",
    "UNSCORED",
    "CHAIN_COLUMNS",
    "PDB_CHAIN_COLUMNS",
    "RESNUM_COLUMNS",
    "RESIDUE_COLUMNS",
    "SCORE_COLUMN_PREFERENCE",
    "ICODE_COLUMNS",
    "REJECTED_COLUMNS",
    "ExternalScoreError",
    "ExternalScoreFile",
    "midrank_percentiles",
    "load_external_scores",
    "load_external_score_file",
]

MIN_MATCH_FRACTION = 0.5
"""Below this fraction of file residues found in the structure, warn loudly."""

CHAIN_COLUMNS = ("chain", "chain_id", "auth_asym_id", "asym_id", "pdb_strand_id")

PDB_CHAIN_COLUMNS = ("pdb", "pdb_id", "pdb_chain", "structure", "entry")
"""Columns holding ``<entry>_<chain>``, e.g. DiscoTope-3.0's ``pdb`` = ``7lj8_A``.

DiscoTope emits no chain column at all; the chain is the suffix of this one.
Reading it as an opaque identifier and leaving the chain unknown would make
every residue key wrong, so the suffix is split out explicitly.
"""

RESNUM_COLUMNS = (
    "resnum", "res_num", "resi", "resseq", "res_id", "auth_seq_id",
    "position", "pos",
)
RESIDUE_COLUMNS = ("residue_key", "key")
"""Columns holding a combined ``A325`` token rather than a bare number.

Deliberately NOT ``residue``: DiscoTope-3.0 has a ``residue`` column holding the
three-letter *type* (``TYR``), and treating that as a combined key would parse
garbage. A combined key must be named unambiguously.
"""

SCORE_COLUMN_PREFERENCE = (
    "calibrated_score",
    "discotope_score",
    "score",
    "probability",
    "prediction",
    "value",
    "prob",
    "pred",
)
"""Score columns, **most specific first**; the first one present wins.

Order is load-bearing, not cosmetic. DiscoTope-3.0's own README column list is
stale — ``main.py`` inserts ``calibrated_score`` — and a file can carry both a
raw ``score`` and a ``calibrated_score``. Those are different quantities, so
picking by first-match-in-the-row rather than by declared preference would read
a plausible number that is silently the wrong one. The column actually used is
recorded on :class:`ExternalScoreFile` so a run record can prove which it was.
"""

ICODE_COLUMNS = ("icode", "ins_code", "insertion_code", "pdb_ins_code")

REJECTED_COLUMNS = ("label_seq_id", "label_seq", "seq_id", "index", "idx")
"""Columns we refuse rather than interpret.

``label_seq_id`` is mmCIF entity numbering — a 1-based count along the declared
polymer — and it generally does not equal the author number this package uses
everywhere. A bare ``index`` is worse still. Reading either as an author number
would load cleanly and point at the wrong residues, which is the exact silent
failure :mod:`hotspot_preflight.residue` exists to prevent, so the file is
rejected with instructions instead.
"""

_EXPECTED = (
    "expected either three columns 'chain,resnum,score' or two columns "
    "'residue,score' where residue is a combined token such as 'A325'; "
    "residue numbers must be author (PDB-deposited) numbering"
)
_EXPECTED_JSON = (
    'expected a top-level JSON array of objects, each with "chain", "resnum" '
    'and "score" (optionally "icode"), e.g. '
    '[{"chain": "C", "resnum": 325, "score": 0.81}]'
)


class ExternalScoreError(ValueError):
    """An external score file could not be read as per-residue scores."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _normalise(name: str) -> str:
    return name.strip().strip("#").strip().lower().replace(" ", "_").replace("-", "_")


def _delimiter(path: Path, first_line: str) -> str:
    """Pick the delimiter from the extension, falling back to the content.

    Extension first because it is the author's own declaration; content only
    when the extension does not say, so a ``.csv`` holding tabs is reported as
    malformed rather than silently reinterpreted.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return ","
    if suffix in (".tsv", ".tab"):
        return "\t"
    if "\t" in first_line:
        return "\t"
    if "," in first_line:
        return ","
    raise ExternalScoreError(
        f"{path}: cannot tell whether this file is comma- or tab-separated "
        f"(first line: {first_line.strip()!r}). Give it a .csv or .tsv "
        f"extension. {_EXPECTED}."
    )


def _data_rows(path: Path, delimiter: str) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            [cell.strip() for cell in row]
            for row in csv.reader(handle, delimiter=delimiter)
            if row
            and not row[0].lstrip().startswith("#")
            and any(c.strip() for c in row)
        ]
    if not rows:
        raise ExternalScoreError(f"{path} holds no data rows. {_EXPECTED}.")
    return rows


def _header_index(
    path: Path, header: Sequence[str]
) -> tuple[dict[str, int], str] | None:
    """Map a recognised header to ``(column indices, score column name)``.

    ``None`` when the row is not a recognised header. The score column's *name*
    comes back so the caller can record which quantity it actually read.
    """
    normalised = [_normalise(cell) for cell in header]
    for cell in normalised:
        if cell in REJECTED_COLUMNS:
            raise ExternalScoreError(
                f"{path}: column {cell!r} is not author numbering. "
                f"label_seq_id / seq_id are mmCIF entity numbering (a 1-based "
                f"count along the declared polymer) and an index is neither; "
                f"both differ from the author numbers this package uses, so "
                f"reading them would silently target the wrong residues. "
                f"Convert to author numbering first. {_EXPECTED}."
            )

    found: dict[str, int] = {}
    for i, cell in enumerate(normalised):
        for role, names in (
            ("chain", CHAIN_COLUMNS),
            ("pdb_chain", PDB_CHAIN_COLUMNS),
            ("resnum", RESNUM_COLUMNS),
            ("residue", RESIDUE_COLUMNS),
            ("icode", ICODE_COLUMNS),
        ):
            if cell in names and role not in found:
                found[role] = i

    # The score column is chosen by DECLARED PREFERENCE, never by position and
    # never by whichever candidate appears first in the row. See
    # SCORE_COLUMN_PREFERENCE: a file carrying both `score` and
    # `calibrated_score` holds two different quantities, and taking the wrong
    # one yields plausible numbers that are silently not the prediction.
    score_column = ""
    for preferred in SCORE_COLUMN_PREFERENCE:
        if preferred in normalised:
            found["score"] = normalised.index(preferred)
            score_column = preferred
            break

    if "score" not in found:
        return None
    if not ({"resnum", "residue"} & set(found)):
        return None
    if not ({"chain", "pdb_chain"} & set(found)) and "residue" not in found:
        raise ExternalScoreError(
            f"{path}: found a score column but no chain. Add a 'chain' column, "
            f"or a 'pdb' column of the form '<entry>_<chain>'. A residue "
            f"number with no chain is ambiguous and we will not guess. "
            f"{_EXPECTED}."
        )
    return found, score_column


def _float(path: Path, raw: str, row_no: int) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ExternalScoreError(
            f"{path} line {row_no}: {raw!r} is not a number, so it cannot be a "
            f"score. {_EXPECTED}."
        ) from exc


def _chain_from_pdb_column(path: Path, raw: str, row_no: int) -> str:
    """Recover the chain from ``<entry>_<chain>``, e.g. ``7lj8_A`` -> ``A``.

    Raises rather than falling back to the whole token: a chain id of
    ``"7lj8_A"`` matches no residue in any structure, so every lookup would
    miss and the low-match warning would fire with a confusing cause.
    """
    _, sep, suffix = raw.strip().rpartition("_")
    if not sep or not suffix:
        raise ExternalScoreError(
            f"{path} line {row_no}: cannot get a chain from {raw!r}. A 'pdb' "
            f"column must look like '<entry>_<chain>', e.g. '7lj8_A'. "
            f"{_EXPECTED}."
        )
    return suffix


def _key(path: Path, chain: str, resnum: str, icode: str, row_no: int) -> ResidueKey:
    try:
        return ResidueKey(chain, int(resnum), icode or NO_ICODE)
    except ValueError as exc:
        raise ExternalScoreError(
            f"{path} line {row_no}: cannot read chain {chain!r} residue "
            f"{resnum!r} as a residue ({exc}). {_EXPECTED}."
        ) from exc


def _combined_key(path: Path, token: str, row_no: int) -> ResidueKey:
    try:
        keys = parse_hotspot_spec(token)
    except HotspotParseError as exc:
        raise ExternalScoreError(
            f"{path} line {row_no}: cannot read {token!r} as a residue ({exc}). "
            f"{_EXPECTED}."
        ) from exc
    if len(keys) != 1:
        raise ExternalScoreError(
            f"{path} line {row_no}: {token!r} names {len(keys)} residues; one "
            f"row must describe exactly one residue. {_EXPECTED}."
        )
    return keys[0]


def _add(
    path: Path, out: dict[ResidueKey, float], key: ResidueKey, score: float, row_no: int
) -> None:
    if key in out and out[key] != score:
        raise ExternalScoreError(
            f"{path} line {row_no}: {key} already has score {out[key]} and is "
            f"now given {score}. A duplicated residue with two scores is "
            f"ambiguous; deduplicate the file."
        )
    out[key] = score


def _load_tabular(path: Path) -> tuple[dict[ResidueKey, float], str]:
    with path.open(encoding="utf-8") as handle:
        first_line = handle.readline()
    if not first_line.strip():
        raise ExternalScoreError(f"{path} is empty. {_EXPECTED}.")

    delimiter = _delimiter(path, first_line)
    rows = _data_rows(path, delimiter)
    header = _header_index(path, rows[0])
    has_header = header is not None
    columns, score_column = header if header is not None else (None, "")
    body = rows[1:] if has_header else rows
    if columns is None:
        width = len(rows[0])
        if width == 3:
            columns = {"chain": 0, "resnum": 1, "score": 2}
            score_column = "column 3 (positional, no header)"
        elif width == 2:
            columns = {"residue": 0, "score": 1}
            score_column = "column 2 (positional, no header)"
        else:
            raise ExternalScoreError(
                f"{path} has {width} column(s) and no recognised header, so "
                f"the columns cannot be identified. Add a header row naming "
                f"them, or {_EXPECTED}."
            )
    if not body:
        raise ExternalScoreError(
            f"{path} has a header but no data rows. {_EXPECTED}."
        )

    # Row numbers reported to the user count data rows, so they are off by one
    # from file lines whenever comments or blank lines were skipped. Still far
    # more useful than no position at all.
    offset = 2 if has_header else 1
    out: dict[ResidueKey, float] = {}
    for i, row in enumerate(body):
        row_no = i + offset
        needed = max(columns.values())
        if len(row) <= needed:
            raise ExternalScoreError(
                f"{path} line {row_no}: {len(row)} column(s), but column "
                f"{needed + 1} is needed. {_EXPECTED}."
            )
        score = _float(path, row[columns["score"]], row_no)
        if "residue" in columns:
            key = _combined_key(path, row[columns["residue"]], row_no)
        else:
            icode = row[columns["icode"]] if "icode" in columns else ""
            icode = "" if icode in ("?", ".", "") else icode
            if "chain" in columns:
                chain = row[columns["chain"]]
            else:
                chain = _chain_from_pdb_column(
                    path, row[columns["pdb_chain"]], row_no
                )
            key = _key(path, chain, row[columns["resnum"]], icode, row_no)
        _add(path, out, key, score, row_no)
    return out, score_column


def _load_json(path: Path) -> dict[ResidueKey, float]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalScoreError(
            f"{path} is not valid JSON ({exc}). {_EXPECTED_JSON}."
        ) from exc
    if not isinstance(payload, list):
        raise ExternalScoreError(
            f"{path}: top level is {type(payload).__name__}, not a list. "
            f"{_EXPECTED_JSON}."
        )
    if not payload:
        raise ExternalScoreError(f"{path} holds an empty list. {_EXPECTED_JSON}.")

    out: dict[ResidueKey, float] = {}
    for i, record in enumerate(payload, start=1):
        if not isinstance(record, dict):
            raise ExternalScoreError(
                f"{path} item {i} is {type(record).__name__}, not an object. "
                f"{_EXPECTED_JSON}."
            )
        fields = {_normalise(k): v for k, v in record.items()}
        for name in fields:
            if name in REJECTED_COLUMNS:
                raise ExternalScoreError(
                    f"{path} item {i}: field {name!r} is mmCIF entity "
                    f"numbering or a bare index, not author numbering; "
                    f"reading it would silently target the wrong residues. "
                    f"{_EXPECTED_JSON}."
                )
        chain = _first(fields, CHAIN_COLUMNS)
        if chain is None and (pdb := _first(fields, PDB_CHAIN_COLUMNS)) is not None:
            chain = _chain_from_pdb_column(path, str(pdb), i)
        resnum = _first(fields, RESNUM_COLUMNS)
        # Preference-ordered, exactly as for a header row: a record carrying
        # both `score` and `calibrated_score` holds two different quantities.
        score = _first(fields, SCORE_COLUMN_PREFERENCE)
        if chain is None or resnum is None or score is None:
            raise ExternalScoreError(
                f"{path} item {i} has fields {sorted(fields)}; needs a chain, "
                f"a residue number and a score. {_EXPECTED_JSON}."
            )
        icode = _first(fields, ICODE_COLUMNS)
        out_key = _key(
            path,
            str(chain),
            str(resnum),
            "" if icode in (None, "?", ".", "") else str(icode),
            i,
        )
        _add(path, out, out_key, _float(path, str(score), i), i)
    return out


def _first(fields: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in fields:
            return fields[name]
    return None


@dataclass(frozen=True)
class ExternalScoreFile:
    """What a score file contained, plus how it was read.

    ``score_column`` and ``raw`` exist for auditability. Given DiscoTope-3.0's
    stale README and the possibility of a file carrying both ``score`` and
    ``calibrated_score``, "which number did we actually use" has to be
    answerable from a run record rather than by re-reading this module.
    """

    path: Path
    raw: dict[ResidueKey, float]
    score_column: str

    @property
    def percentiles(self) -> dict[ResidueKey, float]:
        """:func:`midrank_percentiles` of :attr:`raw`."""
        return midrank_percentiles(self.raw)




def load_external_score_file(path: str | Path) -> ExternalScoreFile:
    """Read a local CSV, TSV or JSON score file, recording how it was read.

    The format is chosen by extension — ``.json`` is JSON, anything else is
    tabular — and the tabular columns **by header name**, never by position when
    a header is present. Positional reading is the fallback for a headerless
    two- or three-column file only, and is refused for anything wider.

    Raises:
        ExternalScoreError: on anything unreadable, naming the columns it
            expected. A traceback from :mod:`csv` or :mod:`json` tells a user
            nothing about what their file should have looked like.
    """
    text = str(path)
    if "://" in text:
        raise ExternalScoreError(
            f"{text!r} looks like a URL. This adapter reads only local files "
            f"you generated yourself and never downloads anything — the "
            f"predictors it is meant to host have licences that forbid us "
            f"redistributing their code, weights or output."
        )
    resolved = Path(text).expanduser()
    if not resolved.is_file():
        raise ExternalScoreError(f"no such score file: {resolved}")
    if resolved.suffix.lower() == ".json":
        scores, column = _load_json(resolved), "json field"
    else:
        scores, column = _load_tabular(resolved)
    return ExternalScoreFile(path=resolved, raw=scores, score_column=column)


def load_external_scores(path: str | Path) -> dict[ResidueKey, float]:
    """Raw per-residue scores from a file. See :func:`load_external_score_file`.

    Returns the values **as written in the file**. Callers that will compare,
    blend or threshold them want :attr:`ExternalScoreFile.percentiles` instead;
    see :func:`midrank_percentiles` for why raw values are not comparable.
    """
    return load_external_score_file(path).raw
