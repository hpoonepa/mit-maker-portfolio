# SPDX-License-Identifier: MIT
"""The SAbDab2 summary table: fetching, pinning, parsing, chain resolution.

SAbDab is the only source that states **chain roles** — which auth chain is
heavy, light, antigen. No RCSB query route provides that, and without it an
epitope cannot be derived: you do not know which atoms are the antibody.

**The snapshot is the source of truth, not the network.** The endpoint that
works is undocumented, and the *documented* legacy URL returns a 1,456-byte
React shell **with HTTP 200** (verified 2026-10-05), so a naive fetch
"succeeds" and the CSV reader parses HTML into 1-column rows. We pin a snapshot
in the repo, prefer it always, and refuse any payload that looks like a page.

**Chain names in this table are not always chain names.** 8.8% of Hchain and
Lchain values (3,540 of 40,303, measured) carry a domain index — an scFv
written ``Hchain='H1'``/``Lchain='H2'`` on a single chain ``H``. Looking up
``'H1'`` finds nothing and yields an **empty antibody atom set**, i.e. an empty
epitope rather than an error. But blind suffix stripping is also wrong: this
table holds genuine multi-character auth chain ids such as ``AA``, ``AF``,
``LLL``. So :func:`resolve_chain` matches against the chain ids the structure
actually has, and tries strip-rules only as a fallback.

**Rows, instances and entries are three different numbers.** 22,548 rows for
11,667 PDB entries — counting rows as structures inflates N by 1.93x. For the
protein-antigen subset: 16,800 instances across 8,548 entries. The headline
benchmark size is neither; it is the distinct-antigen count after clustering
(see :mod:`benchmark.cluster`).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "SUMMARY_URL",
    "LEGACY_SUMMARY_URL",
    "SNAPSHOT_DIR",
    "SabdabError",
    "Snapshot",
    "fetch_summary",
    "save_snapshot",
    "load_snapshot",
    "load_summary",
    "AntibodyInstance",
    "parse_instances",
    "protein_antigen_instances",
    "InstanceCounts",
    "count_instances",
    "short_pdb_id",
    "split_tokens",
]

SUMMARY_URL = "https://sabdab.opig.stats.ox.ac.uk/api/download/all-summary"
"""The working endpoint. Undocumented, hence the pinned snapshot."""

LEGACY_SUMMARY_URL = "https://opig.stats.ox.ac.uk/webapps/newsabdab/sabdab/summary/all/"
"""The *documented* endpoint. Returns an HTML shell with HTTP 200. Do not use."""

_SITE_URL = "https://sabdab.opig.stats.ox.ac.uk/"

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshot"
SNAPSHOT_CSV = "sabdab_summary_all.csv.gz"
SNAPSHOT_META = "sabdab_snapshot.json"

MIN_PLAUSIBLE_BYTES = 1_000_000
"""The real payload is ~17 MB. Anything this small is an error page."""

_HTML_MARKERS = (b"<!doctype html", b"<html", b"<head", b"<script", b"<!DOCTYPE HTML")

PROTEIN_ANTIGEN_TOKEN = "PROTEIN"
"""``antigen_type`` is upper-case in SAbDab2 (``PROTEIN``, not ``protein``)."""

# The other antigen_type tokens are ION, SUGAR, HAPTEN, PEPTIDE, RNA, DNA,
# NUCLEOTIDE and OTHER. They are not used to type chains: antigen_chain and
# antigen_type are NOT positionally aligned (1BJ1 has three chains 'A|V|W'
# against two types 'ION|PROTEIN'), so chain typing is done from coordinates
# in benchmark.epitope.protein_chain_ids instead.

_EXTENDED_PDB_RE = re.compile(r"^pdb_0000(?P<code>[0-9a-zA-Z]{4})$")
_NA = {"", "na", "none", "null", "?", "."}


class SabdabError(RuntimeError):
    """A SAbDab payload could not be obtained or trusted.

    Raised instead of letting urllib's traceback escape, because the actionable
    information (which URL, what came back, what to do) is what the operator
    needs and a traceback buries it.
    """


@dataclass(frozen=True)
class Snapshot:
    """A pinned copy of the table plus everything needed to cite it.

    ``sha256``/``n_bytes`` are of the *uncompressed* bytes as served, so the pin
    can be checked against a fresh fetch byte for byte.
    """

    csv_text: str
    sha256: str
    n_bytes: int
    n_rows: int
    source_url: str
    fetched_at: str
    http_date: str = ""
    ui_version: str = ""

    def as_metadata(self) -> dict[str, object]:
        """The JSON sidecar: everything needed to cite and re-verify the pin."""
        return {
            "source_url": self.source_url,
            "sha256": self.sha256,
            "n_bytes": self.n_bytes,
            "n_rows": self.n_rows,
            "fetched_at": self.fetched_at,
            "http_date": self.http_date,
            "ui_version": self.ui_version,
        }

    def as_log(self) -> dict[str, object]:
        """A one-line form for the build log, so runs are traceable to a pin."""
        return {
            "sha256": self.sha256[:16],
            "n_bytes": self.n_bytes,
            "n_rows": self.n_rows,
            "fetched_at": self.fetched_at,
            "ui_version": self.ui_version or "unknown",
        }


def _reject_non_csv(payload: bytes, url: str) -> None:
    """Refuse an HTML error page rather than parsing it as CSV.

    The guard for the HTTP-200-HTML trap. Three independent checks — size, HTML
    markers, expected header columns — because any one alone is defeatable.
    """
    if len(payload) < MIN_PLAUSIBLE_BYTES:
        raise SabdabError(
            f"{url} returned only {len(payload)} bytes; the real summary table "
            f"is ~17 MB. This is almost certainly an error page served with "
            f"HTTP 200. Use the pinned snapshot in {SNAPSHOT_DIR} instead."
        )
    head = payload[:4096].lower()
    for marker in _HTML_MARKERS:
        if marker.lower() in head:
            raise SabdabError(
                f"{url} returned HTML, not CSV (found {marker.decode()!r}). "
                f"The documented legacy SAbDab URL serves a web-app shell with "
                f"HTTP 200; do not parse it. Use the pinned snapshot in "
                f"{SNAPSHOT_DIR}."
            )
    first_line = payload.split(b"\n", 1)[0].decode("utf-8", "replace")
    required = ("INSTANCE", "PDB", "Hchain", "Lchain", "antigen_chain")
    missing = [c for c in required if c not in first_line]
    if missing:
        raise SabdabError(
            f"{url} returned a CSV whose header lacks {missing}. The table "
            f"format has changed; update benchmark/sabdab.py rather than "
            f"guessing at column positions."
        )


def fetch_summary(timeout: float = 180.0, url: str = SUMMARY_URL) -> Snapshot:
    """Download the table once, validating that it is really a table.

    Raises:
        SabdabError: on a network failure or a payload that fails
            :func:`_reject_non_csv`. The message names the URL and the fix.
    """
    request = urllib.request.Request(
        url, headers={"Accept": "text/csv", "User-Agent": "hotspot-preflight/0.1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            http_date = response.headers.get("Date", "")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SabdabError(
            f"could not reach {url}: {exc}. This endpoint is undocumented and "
            f"may have moved. Fall back to the pinned snapshot in "
            f"{SNAPSHOT_DIR}, or to AsEP's Zenodo archive "
            f"(doi:10.5281/zenodo.11495514)."
        ) from exc

    _reject_non_csv(payload, url)
    text = payload.decode("utf-8")
    return Snapshot(
        csv_text=text,
        sha256=hashlib.sha256(payload).hexdigest(),
        n_bytes=len(payload),
        n_rows=max(text.count("\n") - 1, 0),
        source_url=url,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        http_date=http_date,
        ui_version=_probe_ui_version(timeout=15.0),
    )


def _probe_ui_version(timeout: float) -> str:
    """Best-effort read of the SAbDab2 UI version from the site's index page.

    The API exposes no ``/version`` route (checked: 404) and sends no
    ``api-version`` header, so this embedded string is the only version marker
    available. Absence is not an error — the payload sha256 is the real pin.
    """
    try:
        with urllib.request.urlopen(_SITE_URL, timeout=timeout) as response:
            html = response.read(8192).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return ""
    match = re.search(r'"uiVersion"\s*:\s*"([^"]+)"', html)
    return match.group(1) if match else ""


def save_snapshot(snapshot: Snapshot, directory: Path | str = SNAPSHOT_DIR) -> Path:
    """Write the snapshot to the repo, gzipped, with a JSON provenance sidecar."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / SNAPSHOT_CSV
    # mtime=0 so the gzip bytes are reproducible across rebuilds.
    with gzip.GzipFile(csv_path, "wb", compresslevel=9, mtime=0) as handle:
        handle.write(snapshot.csv_text.encode("utf-8"))
    (directory / SNAPSHOT_META).write_text(
        json.dumps(snapshot.as_metadata(), indent=2, sort_keys=True) + "\n"
    )
    return csv_path


def load_snapshot(directory: Path | str = SNAPSHOT_DIR) -> Snapshot:
    """Read the pinned snapshot, verifying its sha256 against the sidecar.

    Raises:
        SabdabError: if it is missing or its digest does not match. A
            silently-corrupt snapshot would poison every label downstream.
    """
    directory = Path(directory)
    csv_path = directory / SNAPSHOT_CSV
    meta_path = directory / SNAPSHOT_META
    if not csv_path.exists() or not meta_path.exists():
        raise SabdabError(
            f"no pinned snapshot in {directory}. Create one with "
            f"`python scripts/build_benchmark.py --refresh-snapshot`, which "
            f"fetches {SUMMARY_URL} once and writes it here."
        )
    meta = json.loads(meta_path.read_text())
    with gzip.open(csv_path, "rb") as handle:
        payload = handle.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != meta.get("sha256"):
        raise SabdabError(
            f"{csv_path} has sha256 {digest} but {meta_path} records "
            f"{meta.get('sha256')}. The snapshot is corrupt or was edited; "
            f"refetch it rather than building labels from it."
        )
    text = payload.decode("utf-8")
    _reject_non_csv(payload, str(csv_path))
    return Snapshot(
        csv_text=text,
        sha256=digest,
        n_bytes=len(payload),
        n_rows=int(meta.get("n_rows", max(text.count("\n") - 1, 0))),
        source_url=str(meta.get("source_url", SUMMARY_URL)),
        fetched_at=str(meta.get("fetched_at", "")),
        http_date=str(meta.get("http_date", "")),
        ui_version=str(meta.get("ui_version", "")),
    )


def load_summary(
    directory: Path | str = SNAPSHOT_DIR, allow_network: bool = False
) -> Snapshot:
    """Prefer the pinned snapshot; touch the network only if told to.

    Defaulting ``allow_network`` to False is the point: evaluation runs must be
    reproducible, and a live fetch against an undocumented endpoint is not.
    """
    try:
        return load_snapshot(directory)
    except SabdabError:
        if not allow_network:
            raise
        snapshot = fetch_summary()
        save_snapshot(snapshot, directory)
        return snapshot


def short_pdb_id(value: str) -> str:
    """Convert SAbDab2's extended id to the 4-character code RCSB uses.

    SAbDab2 writes ``pdb_00001bj1``; ``files.rcsb.org`` wants ``1BJ1`` (its
    path is case-sensitive). Returned lowercase; callers upper-case for URLs.
    """
    value = value.strip()
    match = _EXTENDED_PDB_RE.match(value)
    if match:
        return match.group("code").lower()
    if len(value) == 4:
        return value.lower()
    raise SabdabError(
        f"cannot read {value!r} as a PDB id; expected either 'pdb_0000xxxx' or "
        f"a 4-character code"
    )


def split_tokens(value: str | None) -> tuple[str, ...]:
    """Split a pipe-delimited SAbDab field, dropping NA placeholders."""
    if not value:
        return ()
    out: list[str] = []
    for raw in value.split("|"):
        token = raw.strip()
        if token and token.lower() not in _NA and token not in out:
            out.append(token)
    return tuple(out)


def _opt_str(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return None if value.lower() in _NA else value


def _opt_float(value: str | None) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AntibodyInstance:
    """One antibody copy bound to one antigen, as the table reports it.

    The chain fields are the **raw** values: they may carry a domain index and
    may name chains the structure does not have. Resolution happens in
    :func:`resolve_chain`, once the coordinates are in hand.
    """

    instance_id: str
    pdb_id: str
    heavy_chain: str | None
    light_chain: str | None
    antigen_chains: tuple[str, ...]
    antigen_types: frozenset[str]
    method: str
    resolution: float | None

    @property
    def antibody_chains(self) -> tuple[str, ...]:
        return tuple(c for c in (self.heavy_chain, self.light_chain) if c)

    @property
    def has_protein_antigen(self) -> bool:
        return PROTEIN_ANTIGEN_TOKEN in self.antigen_types

    @property
    def is_single_domain(self) -> bool:
        """A VHH/nanobody: heavy chain, no light chain (e.g. 1ZVH)."""
        return self.heavy_chain is not None and self.light_chain is None


def parse_instances(csv_text: str) -> list[AntibodyInstance]:
    """Parse the table into one record per antibody instance.

    Guard 4. SAbDab2's ``INSTANCE`` column is already one-per-antibody-copy,
    but we still group by ``(pdb, heavy, light)`` and **union** the antigen
    chains, so a future table emitting one row per antigen chain cannot inflate
    the count. :func:`count_instances` keeps rows/instances/entries visible.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    grouped: dict[tuple[str, str | None, str | None], dict[str, object]] = {}
    order: list[tuple[str, str | None, str | None]] = []

    for row in reader:
        pdb_id = short_pdb_id(row["PDB"])
        heavy = _opt_str(row.get("Hchain"))
        light = _opt_str(row.get("Lchain"))
        key = (pdb_id, heavy, light)
        if key not in grouped:
            order.append(key)
            grouped[key] = {
                "instance_id": _opt_str(row.get("INSTANCE")) or "-".join(
                    str(p) for p in key if p
                ),
                "antigen_chains": [],
                "antigen_types": set(),
                "method": _opt_str(row.get("method")) or "UNKNOWN",
                "resolution": _opt_float(row.get("resolution")),
            }
        record = grouped[key]
        chains: list[str] = record["antigen_chains"]  # type: ignore[assignment]
        chains.extend(
            c for c in split_tokens(row.get("antigen_chain")) if c not in chains
        )
        types: set[str] = record["antigen_types"]  # type: ignore[assignment]
        types.update(t.upper() for t in split_tokens(row.get("antigen_type")))

    out: list[AntibodyInstance] = []
    for key in order:
        pdb_id, heavy, light = key
        record = grouped[key]
        out.append(
            AntibodyInstance(
                instance_id=str(record["instance_id"]),
                pdb_id=pdb_id,
                heavy_chain=heavy,
                light_chain=light,
                antigen_chains=tuple(record["antigen_chains"]),  # type: ignore[arg-type]
                antigen_types=frozenset(record["antigen_types"]),  # type: ignore[arg-type]
                method=str(record["method"]),
                resolution=record["resolution"],  # type: ignore[arg-type]
            )
        )
    return out


def protein_antigen_instances(
    instances: Iterable[AntibodyInstance],
    max_resolution: float | None = 3.5,
    methods: Sequence[str] = ("XRAY", "ELECTRON_MICROSCOPY"),
) -> list[AntibodyInstance]:
    """Instances with at least one protein antigen, at usable resolution.

    ``max_resolution=None`` disables the filter. NMR and scattering entries are
    excluded by default: no resolution to filter on, and contact geometry that
    is not comparable to a diffraction or EM structure.
    """
    allowed = {m.upper() for m in methods}
    out = []
    for inst in instances:
        if not inst.has_protein_antigen or not inst.antigen_chains:
            continue
        if inst.method.upper() not in allowed:
            continue
        if max_resolution is not None:
            if inst.resolution is None or inst.resolution > max_resolution:
                continue
        out.append(inst)
    return out


@dataclass(frozen=True)
class InstanceCounts:
    """Rows, instances and entries, kept apart on purpose.

    22,548 rows and 11,667 entries are both wrong answers to "how big is the
    benchmark". The right one is the distinct-antigen count after clustering.
    """

    n_rows: int
    n_instances: int
    n_entries: int

    @property
    def row_inflation(self) -> float:
        return self.n_rows / self.n_entries if self.n_entries else 0.0


def count_instances(
    instances: Sequence[AntibodyInstance], n_rows: int | None = None
) -> InstanceCounts:
    return InstanceCounts(
        n_rows=len(instances) if n_rows is None else n_rows,
        n_instances=len(instances),
        n_entries=len({i.pdb_id for i in instances}),
    )
