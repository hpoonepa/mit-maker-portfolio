# SPDX-License-Identifier: MIT
"""The command line. The only module in this package that prints.

Its real contract is the **exit code**, because the point of a preflight check
is that a pipeline can refuse to spend GPU hours on a site that was never going
to work: ``0`` GO, ``1`` GO_WITH_WARNINGS, ``2`` STOP, ``3`` usage error.

A CI job gates on ``2``; a cautious one gates on ``1``. Code ``3`` is kept
distinct from ``2`` on purpose: "your hotspot string is malformed" and "your
hotspot is buried" demand completely different responses, and a pipeline that
cannot tell them apart will retry the one it should fix.

Expected failures print one actionable sentence and never a traceback. A
traceback is a bug report filed against us; a user who mistyped a residue needs
a correction they can act on.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

import typer

from .findings import Verdict
from .report import (
    PreflightRun,
    render_text,
    run_preflight,
    select_assembly,
    to_run_record,
    write_csv,
)
from .residue import HotspotParseError, ResidueKey, parse_hotspot_spec
from .structure import Target, load_target

__all__ = ["app", "EXIT_CODES", "PDBE_UPDATED_CIF_URL", "parse_crop"]

EXIT_CODES = {
    Verdict.GO: 0,
    Verdict.GO_WITH_WARNINGS: 1,
    Verdict.STOP: 2,
}
EXIT_USAGE = 3

PDBE_UPDATED_CIF_URL = (
    "https://www.ebi.ac.uk/pdbe/entry-files/download/{entry}_updated.cif"
)
"""PDBe's *updated* mmCIF, not an RCSB download.

The updated file carries per-residue SIFTS annotation and the curated
``_pdbx_unobs_or_zero_occ_residues`` category that the resolved check
cross-checks against. A plain RCSB coordinate file does not, which silently
reduces every verdict to the single derived route.
"""

CACHE_ENV_VAR = "HOTSPOT_PREFLIGHT_CACHE"
DEFAULT_CACHE_DIR = ".cache"

_PDB_ID_RE = re.compile(r"^[0-9][A-Za-z0-9]{3}$")
_CROP_RE = re.compile(
    r"^(?P<chain>[A-Za-z][A-Za-z0-9_]*):(?P<first>-?\d+)-(?P<last>-?\d+)$"
)
_CROP_FORM = "CHAIN:FIRST-LAST, e.g. --crop C:310-398"

app = typer.Typer(
    add_completion=False,
    help="Preflight checks for binder design: is the site you chose real?",
)


@app.callback()
def main() -> None:
    """Preflight checks for protein binder design hotspots.

    Present so that ``preflight check ...`` keeps its subcommand name; a Typer
    app with a single command and no callback collapses into a bare command.
    """


def _fail(message: str) -> typer.Exit:
    """Report a usage error as prose on stderr and exit 3.

    stderr, not stdout, so that ``--json`` consumers piping stdout do not have
    to parse an error out of the stream they expect JSON on.
    """
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=EXIT_USAGE)


def parse_crop(value: str) -> tuple[str, int, int]:
    """Parse ``CHAIN:FIRST-LAST`` into the burial check's crop tuple.

    Strict by design. A crop is the single most dangerous input in this tool —
    designing against a truncation is what produced the 7/7 failure this package
    exists to prevent — so a form we are not certain of is rejected rather than
    guessed at.

    Raises:
        ValueError: on anything else, naming the expected form.
    """
    match = _CROP_RE.match(value.strip())
    if match is None:
        raise ValueError(f"could not parse crop {value!r}. Expected {_CROP_FORM}")
    first, last = int(match.group("first")), int(match.group("last"))
    if last < first:
        raise ValueError(
            f"crop {value!r} runs backwards ({first} to {last}). "
            f"Expected {_CROP_FORM}"
        )
    return match.group("chain"), first, last


def _cache_dir() -> Path:
    """Where fetched entries live.

    Overridable by environment so CI and tests can place the cache deliberately
    instead of depending on the working directory.
    """
    return Path(os.environ.get(CACHE_ENV_VAR) or DEFAULT_CACHE_DIR)


def _fetch_entry(entry_id: str) -> Path:
    """Download a PDB entry's updated mmCIF, reusing the cache when present.

    Raises:
        ValueError: on any network or filesystem failure, phrased as something
            the user can act on. A urllib traceback tells them nothing.
    """
    entry = entry_id.lower()
    cache = _cache_dir()
    path = cache / f"{entry}_updated.cif"
    if path.exists():
        return path
    url = PDBE_UPDATED_CIF_URL.format(entry=entry)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        # Download beside the target and move into place, so an interrupted
        # fetch cannot leave a truncated file that every later run trusts.
        partial = path.with_suffix(".cif.partial")
        urllib.request.urlretrieve(url, partial)
        partial.replace(path)
    except urllib.error.HTTPError as exc:
        raise ValueError(
            f"PDBe returned HTTP {exc.code} for entry {entry_id!r} ({url}). "
            f"Check the id, or pass a local file path instead."
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(
            f"could not download entry {entry_id!r} from {url}: {exc}. "
            f"Pass a local file path instead."
        ) from exc
    return path


def _resolve_structure(value: str) -> Path:
    """Interpret the positional argument as a path or a 4-character PDB id.

    An existing path always wins, so a local file literally named ``6f5j`` is
    never shadowed by a download.

    Raises:
        ValueError: when it is neither a readable file nor a plausible entry id.
    """
    path = Path(value)
    if path.exists():
        if path.is_dir():
            raise ValueError(f"{value!r} is a directory, not a structure file")
        return path
    if _PDB_ID_RE.match(value):
        return _fetch_entry(value)
    raise ValueError(
        f"no such file {value!r}. Pass a path to an mmCIF or PDB file, or a "
        f"4-character PDB id such as 6f5j to fetch it from PDBe."
    )


def _site_chain(keys: Sequence[ResidueKey], flag: str) -> str:
    """The single chain a hotspot list lives on.

    ``--sbol-out`` and ``--construct`` are per-chain by construction: an SBOL
    ``Component`` is one sequence. Guessing which chain a multi-chain site meant
    would pick a numbering scheme on the user's behalf, so it is refused.
    """
    chains = sorted({k.auth_asym_id for k in keys})
    if len(chains) != 1:
        raise ValueError(
            f"{flag} needs a hotspot list on one chain; yours spans "
            f"{', '.join(chains)}. Run one chain at a time."
        )
    return chains[0]


def _write_outputs(
    run: PreflightRun,
    target: Target,
    json_path: Path | None,
    csv_path: Path | None,
    html_path: Path | None = None,
    sbol_path: Path | None = None,
) -> None:
    """Raises ValueError so the caller can turn it into exit 3."""
    try:
        if json_path is not None:
            json_path.write_text(
                json.dumps(to_run_record(run), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if csv_path is not None:
            write_csv(run, csv_path)
        if html_path is not None:
            # Imported here, not at module scope: html_report imports report,
            # and a CLI that cannot start because a reporting template failed to
            # parse would take the structural checks down with it.
            from .html_report import write_html

            write_html(run, html_path)
        if sbol_path is not None:
            _write_sbol_site(run, target, sbol_path)
    except OSError as exc:
        raise ValueError(f"could not write output: {exc}") from exc


def _write_sbol_site(run: PreflightRun, target: Target, path: Path) -> None:
    """Write the site as SBOL 3, raising ValueError with the installation hint
    when ``sbol3`` is absent — one actionable line, not an ImportError."""
    from .standards.sbol import (
        NumberingMapError,
        SbolUnavailableError,
        write_sbol,
    )

    chain = _site_chain(run.keys, "--sbol-out")
    try:
        write_sbol(target, chain, run.keys, path)
    except SbolUnavailableError as exc:
        raise ValueError(str(exc)) from None
    except NumberingMapError as exc:
        raise ValueError(f"--sbol-out: {exc}") from None


def _crop_from_construct(target: Target, keys: Sequence[ResidueKey], path: Path):
    """Read a crop range out of an SBOL construct, in author numbering.

    Uses ``construct_crop_range``, never ``read_construct``: the latter returns
    1-based sequence indices, the two tuples have the same shape, and ``--crop``
    takes author numbers — so passing one where the other belongs is exactly the
    silent misaim this tool exists to catch, and it would not raise.
    """
    from .standards.sbol import (
        ConstructReadError,
        SbolUnavailableError,
        construct_crop_range,
    )

    chain = _site_chain(keys, "--construct")
    try:
        return construct_crop_range(target, chain, path)
    except SbolUnavailableError as exc:
        raise ValueError(str(exc)) from None
    except ConstructReadError as exc:
        raise ValueError(f"--construct: {exc}") from None


def _load_evidence(path: Path) -> list[Any]:
    from .evidence import EvidenceTableError, load_table

    try:
        return load_table(path)
    except EvidenceTableError as exc:
        raise ValueError(f"--evidence: {exc}") from None


@app.command()
def check(
    structure: str = typer.Argument(
        ...,
        metavar="STRUCTURE",
        help="Path to an mmCIF or PDB file, or a 4-character PDB id to fetch.",
    ),
    hotspots: str = typer.Option(
        ...,
        "--hotspots",
        "-h",
        help='Hotspot residues in author numbering, e.g. "C405,C408" or "C405-408".',
    ),
    crop: str | None = typer.Option(
        None,
        "--crop",
        metavar="CHAIN:FIRST-LAST",
        help="The truncation you intend to design against, e.g. C:310-398.",
    ),
    json_out: Path | None = typer.Option(
        None, "--json", metavar="OUT.json", help="Write the run record here."
    ),
    csv_out: Path | None = typer.Option(
        None, "--csv", metavar="OUT.csv", help="Write one row per finding here."
    ),
    html_out: Path | None = typer.Option(
        None, "--html", metavar="OUT.html", help="Write a standalone HTML report here."
    ),
    sbol_out: Path | None = typer.Option(
        None,
        "--sbol-out",
        metavar="OUT.nt",
        help="Write the site as SBOL 3. Needs the 'sbol' extra.",
    ),
    construct: Path | None = typer.Option(
        None,
        "--construct",
        metavar="IN.nt",
        help="Read the crop range from an SBOL construct instead of --crop.",
    ),
    evidence: Path | None = typer.Option(
        None,
        "--evidence",
        metavar="TABLE.yaml",
        help="Grade the site against a curated literature table. Off by default.",
    ),
    patch: bool = typer.Option(
        True,
        "--patch/--no-patch",
        help="Judge the hotspot set as a shape. --no-patch gives the pre-patch output.",
    ),
    assembly: str | None = typer.Option(
        None,
        "--assembly",
        metavar="NAME",
        help="Biological assembly to measure burial on. Defaults to the first declared.",
    ),
    quiet: bool = typer.Option(
        False, "--quiet", help="Suppress the report; exit code and files still happen."
    ),
) -> None:
    """Check whether a hotspot site is worth designing against.

    Exit codes: 0 GO, 1 GO_WITH_WARNINGS, 2 STOP, 3 usage error.
    """
    if crop is not None and construct is not None:
        # Both set a crop range. Preferring one silently would mean the run used
        # a truncation the user did not think they had asked for.
        raise _fail(
            "--crop and --construct both set the crop range; pass only one"
        )
    keys: list[ResidueKey]
    try:
        keys = parse_hotspot_spec(hotspots)
    except HotspotParseError as exc:
        # The parse error already names the offending token and the fix; it is
        # repeated verbatim rather than re-worded so the two cannot diverge.
        raise _fail(f"bad --hotspots {hotspots!r}: {exc}") from None

    try:
        crop_range = parse_crop(crop) if crop is not None else None
    except ValueError as exc:
        raise _fail(str(exc)) from None

    try:
        path = _resolve_structure(structure)
    except ValueError as exc:
        raise _fail(str(exc)) from None

    try:
        target = load_target(path)
    except (RuntimeError, ValueError, OSError) as exc:
        # gemmi raises RuntimeError for an unparseable file, which is a usage
        # error from here: the input was not a structure.
        raise _fail(f"could not read {path.name}: {exc}") from None

    try:
        select_assembly(target, assembly)
        if construct is not None:
            crop_range = _crop_from_construct(target, keys, construct)
        rows = _load_evidence(evidence) if evidence is not None else None
        run = run_preflight(
            target,
            keys,
            crop_range=crop_range,
            hotspot_spec=hotspots,
            patch=patch,
            evidence_rows=rows,
        )
    except ValueError as exc:
        raise _fail(str(exc)) from None

    try:
        _write_outputs(run, target, json_out, csv_out, html_out, sbol_out)
    except ValueError as exc:
        raise _fail(str(exc)) from None

    if not quiet:
        typer.echo(render_text(run), nl=False)
    raise typer.Exit(code=EXIT_CODES[run.report.verdict])


@app.command()
def propose(
    structure: str = typer.Argument(
        ...,
        metavar="STRUCTURE",
        help="Path to an mmCIF or PDB file, or a 4-character PDB id to fetch.",
    ),
    chain: str | None = typer.Option(
        None, "--chain", metavar="C", help="Author chain id. Defaults to the first."
    ),
    top: int = typer.Option(10, "--top", metavar="N", help="How many to report."),
    predictor: str = typer.Option(
        "geometric", "--predictor", help="Scoring backend to rank with."
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        metavar="NAME",
        help=(
            "Weight profile for the geometric backend: designability (default, "
            "hand-set), antibody_epitope (fitted), exposure_only."
        ),
    ),
    json_out: Path | None = typer.Option(
        None, "--json", metavar="OUT.json", help="Write the ranked candidates here."
    ),
    assembly: str | None = typer.Option(
        None, "--assembly", metavar="NAME", help="Biological assembly to measure on."
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress the table."),
) -> None:
    """Propose candidate binder sites, ranked, instead of checking one you have.

    Exit codes: 0 success, 3 usage error. Deliberately never 1 or 2 — this
    command reports candidates and passes no verdict, so a pipeline must not be
    able to gate on it as though it had.
    """
    from .predict import UnknownPredictorError, available, get
    from .predict.profiles import get_profile
    from .propose import propose_sites, render_propose_text, to_propose_record

    if top < 1:
        raise _fail(f"--top must be at least 1, got {top}")

    kwargs: dict[str, object] = {}
    if profile is not None:
        # Rejected here rather than passed through, because a factory that does
        # not take `profile` would raise a TypeError about its own signature and
        # the user would have to guess that the flag was the problem. Weights
        # are a property of the geometric baseline; an external score file is
        # read, not reweighted.
        if predictor != "geometric":
            raise _fail(
                f"--profile applies to the geometric predictor, not "
                f"{predictor!r}; weight profiles reweight our own features and "
                f"an external score file is read as given"
            )
        try:
            kwargs["profile"] = get_profile(profile)
        except ValueError as exc:
            raise _fail(str(exc)) from None

    try:
        target = load_target(_resolve_structure(structure))
    except ValueError as exc:
        raise _fail(str(exc)) from None
    except (RuntimeError, OSError) as exc:
        raise _fail(f"could not read {structure}: {exc}") from None

    try:
        pred = get(predictor, **kwargs)
    except UnknownPredictorError as exc:
        known = ", ".join(available())
        raise _fail(f"{exc} Available: {known}.") from None

    try:
        select_assembly(target, assembly)
        sites = propose_sites(target, pred, chain=chain)
    except ValueError as exc:
        raise _fail(str(exc)) from None

    if json_out is not None:
        try:
            json_out.write_text(
                json.dumps(to_propose_record(sites, top), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise _fail(f"could not write output: {exc}") from None

    if not quiet:
        typer.echo(render_propose_text(sites, top), nl=False)
    raise typer.Exit(code=0)

from .service_cli import analyze_command, serve_command
app.command("serve")(serve_command)
app.command("analyze")(analyze_command)
