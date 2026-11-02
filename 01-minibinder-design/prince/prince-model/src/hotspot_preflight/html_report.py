# SPDX-License-Identifier: MIT
"""A single-file, offline HTML report for one preflight run.

This gets attached to a wiki page, emailed, or opened by a reviewer with no
network, so it embeds everything: the CSS lives in a ``<style>`` block and there
are no scripts, fonts, images or remote links. Nothing here may fetch a resource
at render time or at view time.

There is no templating engine either. One document shape does not justify a
dependency every reviewer must then install to regenerate the report, so the page
is assembled from :class:`string.Template` and :func:`html.escape`.

The output is deterministic: identical inputs give byte-identical HTML, which is
what makes two reports diffable and so shows a reader that a re-run changed
nothing. A wall-clock timestamp would break that, so the generation date is
injected by the caller via ``generated_at`` or left out.

Severity carries a text label as well as a colour, because this report will be
printed in greyscale and read by colourblind reviewers. No emoji.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from .findings import Finding, Severity, SiteReport, Verdict, sort_findings

if TYPE_CHECKING:  # pragma: no cover - the annotation is the only use
    # Annotation-only, so rendering never depends on the orchestration layer:
    # this module reads attributes off the run and nothing more.
    from .report import PreflightRun

__all__ = ["render_html", "write_html", "TOOL_NAME", "TOOL_VERSION"]

TOOL_NAME = "hotspot-preflight"
TOOL_VERSION = "0.1.0"
"""Mirrors ``pyproject.toml``. Hardcoded rather than read from package metadata
so the report renders identically from a checkout and from an installed wheel:
a version that depended on the install method would make two identical runs
produce different bytes."""

#: The three downstream consumers, in the order the report lists them.
TOOL_ORDER = ("rfdiffusion", "bindcraft", "boltzgen")

# numbering.translate_for_tools() stores the *reason* under the tool's own key
# when a format cannot be produced, so a value is either a hotspot string or
# prose. These grammars tell them apart: every real format is a comma-separated
# run of residue tokens and so contains no whitespace, while every reason is a
# sentence. Rendering a sentence inside a copyable <code> block would invite
# someone to paste an error message into their design config.
# FRAGILE and temporary: the discriminator is punctuation, not type, so a tool
# whose hotspot syntax legitimately contains a space would be misread as prose.
# Do not widen these patterns - the union belongs in the type system. A frozen
# ToolFormat with a value-or-reason discriminant is planned across numbering.py,
# report.py, cli.py and this module; when it lands, delete _FORMAT_SHAPES.
_FORMAT_SHAPES = {
    "rfdiffusion": re.compile(r"^\[[A-Za-z0-9_,-]+\]$"),
    "bindcraft": re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_,-]*$"),
    "boltzgen": re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_,]*$"),
}
#: Fallback grammar for a tool this module has not been taught yet.
_ANY_FORMAT = re.compile(r"^\S+$")

#: Word and gist per verdict. Spelled out rather than reusing ``Verdict.value``,
#: so the page never shows ``GO_WITH_WARNINGS``.
_VERDICTS: dict[Verdict, tuple[str, str]] = {
    Verdict.GO: ("GO", "Every hotspot residue passed every check. Proceed."),
    Verdict.GO_WITH_WARNINGS: ("GO WITH WARNINGS", "No hotspot is disqualified, but "
        "at least one check is less certain than it should be. Read the warnings "
        "before spending compute."),
    Verdict.STOP: ("STOP", "At least one hotspot residue cannot be designed against. "
        "Fix the site specification before running any design job against it."),
}

# Plain language for each cause, and the action it implies. A reader who has never
# used this tool must be able to act on the report without reading the source, so a
# bare code or score is never enough.
_CAUSES: dict[str, tuple[str, str]] = {
    "NO_SUCH_CHAIN": (
        "the chain named in the hotspot specification is not present in this structure",
        "Check the chain letter: ids differ between asymmetric unit and assembly.",
    ),
    "NOT_DECLARED": (
        "the residue number is outside the range this entry declares for the chain, so "
        "no such residue exists in this entry at all",
        "You are on a different numbering than the entry uses. Check a viewer.",
    ),
    "UNMODELLED": (
        "never observed in the deposited coordinates - the residue is declared in the "
        "sequence but has no atoms, so there is no surface to design against",
        "Pick a hotspot that was actually resolved - unmodelled residues sit in "
        "flexible tails, and nothing can be designed against absent atoms.",
    ),
    "WRONG_NUMBERING_SCHEME": (
        "the numbering looks like BoltzGen's mmCIF label_seq numbering rather than "
        "author numbering, so these hotspots would aim at other residues",
        "Convert once: RFdiffusion and BindCraft take author numbering, "
        "BoltzGen takes label_seq.",
    ),
    "AMBIGUOUS_NUMBERING": (
        "the numbers are consistent with more than one numbering scheme, so which "
        "residues you mean cannot be decided from the specification",
        "State the scheme explicitly, or pick a residue where they disagree.",
    ),
    "ICODE_NOT_EXPRESSIBLE": (
        "the residue carries an mmCIF insertion code, which the hotspot syntax of the "
        "downstream tool cannot express",
        "Use a tool that accepts insertion codes, or pick a neighbour without "
        "one - dropping the code silently would aim the design elsewhere.",
    ),
    "BURIED_IN_ASSEMBLY": (
        "buried on the biological assembly - the residue looks exposed on the single "
        "chain, but is covered once the symmetry mates are built, so nothing can reach it",
        "Choose a hotspot exposed on the assembly - this is what a "
        "single-chain view hides.",
    ),
    "BURIED_RELATIVE_SASA": (
        "buried in the structure as given - too little of the residue's reference "
        "maximum solvent-accessible surface is actually accessible",
        "Pick a surface residue. Check the measured relative SASA in the "
        "evidence against your own threshold before overriding.",
    ),
    "OCCLUDED_BY_PARTNER": (
        "covered by a binding partner that is already present in the structure",
        "Target a different face, or confirm the partner is absent in vivo.",
    ),
    "CROP_ARTIFACT": (
        "the site only looks exposed because the target was cropped - on the intact "
        "structure it is covered",
        "Re-run against the uncropped target: designs from a crop that exposes "
        "the epitope cannot bind the real protein.",
    ),
}

# Codes that reduce how much the report can claim, as opposed to disqualifying a
# residue. These get their own block: a check that ran with less evidence than usual
# must say so rather than read as a clean pass.
_CONFIDENCE_CODES = frozenset({
    "NO_UNOBS_CATEGORY", "NO_ASSEMBLY_DEFINED", "DETECTION_ROUTES_DISAGREE",
    "FALLBACK_ATOM_RADIUS", "FALLBACK_ELEMENT_RADII", "REFERENCE_SUBSTITUTE_MAX",
    "LOW_OCCUPANCY",
})

_DARK_PALETTE = """--bg: #14171a; --fg: #e8eaed; --muted: #a2a9b3; --border: #343a41; --panel: #1d2126; --code-bg: #22272c; --kill-fg: #ffe8ea; --kill-bg: #7a1222; --kill-edge: #d4707e; --warn-fg: #ffeec9; --warn-bg: #4b3a10; --warn-edge: #d8b668; --pass-fg: #d8ecdd; --pass-bg: #1f3526; --pass-edge: #71a37f;"""
"""The dark values, declared once and emitted under both dark selectors so the
two cannot drift apart."""

_STYLE = """
:root { --bg: #ffffff; --fg: #15181c; --muted: #5a626c; --border: #d5d9df; --panel: #f6f7f9; --code-bg: #f0f2f5; --kill-fg: #ffffff; --kill-bg: #8a1020; --kill-edge: #8a1020; --warn-fg: #3d2a00; --warn-bg: #f2d9a0; --warn-edge: #9a7414; --pass-fg: #1d3b24; --pass-bg: #e2ece4; --pass-edge: #4a6b52; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { $dark }
}
:root[data-theme="dark"] { $dark }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); margin: 0;
  font: 16px/1.55 ui-sans-serif, system-ui, -apple-system, Helvetica, sans-serif; }
main { max-width: 62rem; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
h1 { font-size: 1.35rem; margin: 0 0 .25rem; letter-spacing: -.01em; }
h2 { font-size: 1.05rem; margin: 2rem 0 .6rem; } p { margin: .5rem 0; }
h3 { font-size: .95rem; margin: 1.2rem 0 .35rem; }
.sub { color: var(--muted); font-size: .9rem; margin: 0 0 1.25rem; }
.verdict { border: 2px solid var(--border); border-radius: .5rem;
  padding: .9rem 1rem; background: var(--panel); }
.verdict-word { font-size: 1.5rem; font-weight: 700; letter-spacing: .04em;
  display: inline-block; padding: .1rem .5rem; border-radius: .3rem;
  border: 2px solid currentColor; }
.v-go { color: var(--pass-edge); } .v-warn { color: var(--warn-edge); }
.v-halt { color: var(--kill-edge); }
.count { color: var(--muted); font-size: .9rem; margin-left: .5rem; } .fmt h3 { margin-bottom: .2rem; }
.reason { border-left: .3rem solid var(--kill-edge); background: var(--panel);
  padding: .6rem .8rem; margin: .7rem 0; border-radius: 0 .3rem .3rem 0; }
.reason.warn { border-left-color: var(--warn-edge); } .reason h3 { margin-top: 0; }
.next { color: var(--muted); font-size: .92rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .45rem .5rem; vertical-align: top;
  border-bottom: 1px solid var(--border); }
th { font-size: .78rem; text-transform: uppercase; letter-spacing: .05em;
  color: var(--muted); }
.sev { font-size: .72rem; font-weight: 700; letter-spacing: .06em;
  padding: .1rem .4rem; border-radius: .2rem; border: 1px solid;
  white-space: nowrap; }
.sev-KILL { color: var(--kill-fg); background: var(--kill-bg); border-color: var(--kill-edge); }
.sev-WARN { color: var(--warn-fg); background: var(--warn-bg); border-color: var(--warn-edge); }
.sev-PASS { color: var(--pass-fg); background: var(--pass-bg); border-color: var(--pass-edge); }
code, pre, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
code { background: var(--code-bg); padding: .1rem .3rem; border-radius: .2rem;
  font-size: .88rem; }
.fmt code { display: block; padding: .6rem .7rem; overflow-x: auto;
  white-space: pre; border: 1px solid var(--border); user-select: all; }
details { margin: .6rem 0; } summary { cursor: pointer; font-size: .9rem; }
dl { display: grid; grid-template-columns: minmax(10rem, max-content) 1fr;
  gap: .2rem .9rem; margin: .5rem 0; font-size: .88rem; }
dt { color: var(--muted); } dd { margin: 0; overflow-wrap: anywhere; }
ul.keys { list-style: none; padding: 0; margin: .4rem 0; display: flex;
  flex-wrap: wrap; gap: .3rem; }
ul.keys li { background: var(--code-bg); padding: .1rem .35rem;
  border-radius: .2rem; font-size: .82rem; }
footer { margin-top: 2.5rem; padding-top: .8rem; color: var(--muted);
  border-top: 1px solid var(--border); font-size: .82rem; }
@media (max-width: 34rem) {
  main { padding: 1rem .75rem 2rem; }
  dl { grid-template-columns: 1fr; }
  table { font-size: .84rem; }
  th, td { padding: .4rem .3rem; }
}
""".replace("$dark", _DARK_PALETTE)

_PAGE = Template(
    """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hotspot Preflight</title>
<style>$style</style>
</head>
<body>
<main>
<h1>Hotspot preflight: $target</h1>
<p class="sub">Hotspot specification <code>$spec</code>$stamp</p>
$verdict
$reasons
$confidence
$residues
$formats
$repro
<footer>$footer</footer>
</main>
</body>
</html>
"""
)


def render_html(run: PreflightRun, *, generated_at: str | None = None) -> str:
    """Render one preflight run as a self-contained HTML document.

    Args:
        run: the completed run. Only attributes are read; nothing is executed.
        generated_at: an optional, already-formatted date or timestamp to show.
            The caller supplies it rather than this function reading the clock,
            because an embedded wall-clock time would make two reports of the
            same run differ and so stop them being diffable.

    Returns:
        A complete HTML document. Deterministic for a given input, with no
        reference to any remote resource.
    """
    report = run.report
    verdict = report.verdict
    stamp = (
        f" &middot; generated {escape(str(generated_at))}"
        if generated_at is not None
        else ""
    )
    return _PAGE.substitute(
        style=_STYLE,
        target=escape(str(run.target_id)),
        spec=escape(str(run.hotspot_spec)),
        stamp=stamp,
        verdict=_verdict_section(verdict, report),
        reasons=_reasons_section(report),
        confidence=_confidence_section(report),
        residues=_residues_section(report),
        formats=_formats_section(run.tool_formats),
        repro=_repro_section(run),
        footer=(
            f"{escape(TOOL_NAME)} {escape(TOOL_VERSION)} &middot; MIT licence "
            "&middot; self-contained report, no external resources"
        ),
    )


def write_html(run: PreflightRun, path: str | Path, **kwargs: Any) -> None:
    """Write :func:`render_html` to ``path`` as UTF-8.

    ``kwargs`` reach :func:`render_html`, so a caller that wants a timestamp
    need not render and write in two steps.
    """
    Path(path).write_text(render_html(run, **kwargs), encoding="utf-8")


# --- Sections --------------------------------------------------------------


def _verdict_section(verdict: Verdict, report: SiteReport) -> str:
    css = {
        Verdict.GO: "v-go",
        Verdict.GO_WITH_WARNINGS: "v-warn",
        Verdict.STOP: "v-halt",
    }[verdict]
    word, gist = _VERDICTS[verdict]
    n_kill, n_warn = len(report.kills), len(report.warnings)
    killed = len(report.residues_killed())
    counts = (
        f"{n_kill} blocking finding(s) across {killed} residue(s), "
        f"{n_warn} warning(s)"
    )
    return (
        f'<section id="verdict"><div class="verdict">'
        f'<span class="verdict-word {css}">{word}</span>'
        f'<span class="count">{escape(counts)}</span>'
        f"<p>{escape(gist)}</p>"
        f"</div></section>"
    )


def _reasons_section(report: SiteReport) -> str:
    """One block per blocking cause, named in plain language. Grouped by code
    rather than per residue, because the action is the same for every residue
    that failed for the same reason."""
    parts = ['<section id="reasons">']
    if not report.kills:
        parts.append("<h2>Blocking problems</h2><p>None.</p>")
    else:
        parts.append("<h2>Why this site is blocked</h2>")
        for code in report.kill_codes():
            group = [f for f in report.kills if f.code == code]
            parts.append(_reason_block(code, group, "reason"))
    parts.append("</section>")
    return "".join(parts)


def _reason_block(code: str, group: Sequence[Finding], css: str) -> str:
    cause, action = _CAUSES.get(code, ("", ""))
    where = ", ".join(str(f.key) for f in group if f.key is not None)
    heading = escape(where) if where else "Whole site"
    body = [f'<div class="{css}"><h3>{heading}</h3>']
    if cause:
        # Only the first character is raised. str.capitalize() would lowercase
        # the rest and turn "BoltzGen", "mmCIF" and "SASA" into nonsense.
        body.append(f"<p>{escape(cause[0].upper() + cause[1:])}.</p>")
    # The finding's own message always appears, so a code this module has not
    # been taught yet still produces a readable, actionable block.
    for finding in group:
        body.append(f"<p>{escape(finding.message)}</p>")
        body.append(_evidence(finding))
    body.append(f'<p class="next">Code <code>{escape(code)}</code>.')
    if action:
        body.append(f" What to do: {escape(action)}")
    body.append("</p></div>")
    return "".join(body)


def _confidence_section(report: SiteReport) -> str:
    """Surface checks that ran on less evidence than usual. Smoothing these away
    would let the report read as a clean pass when a check could not see what it
    needed to."""
    reduced = [
        f for f in sort_findings(report.findings)
        if f.code in _CONFIDENCE_CODES and f.severity is not Severity.PASS
    ]
    if not reduced:
        return ""
    blocks = "".join(_reason_block(f.code, [f], "reason warn") for f in reduced)
    return (
        '<section id="confidence"><h2>Confidence caveats</h2><p>These do not '
        "disqualify a residue, but they do limit what this report can claim. "
        f"Read them before treating a pass as settled.</p>{blocks}</section>"
    )


def _residues_section(report: SiteReport) -> str:
    """Findings table, with passes disclosed rather than expanded: fifty green
    rows would push the three that matter off the screen."""
    findings = sort_findings(report.findings)
    notable = [f for f in findings if f.severity is not Severity.PASS]
    passed = [f for f in findings if f.severity is Severity.PASS]

    parts = ['<section id="residues"><h2>Per-residue findings</h2>']
    if notable:
        parts.append(
            "<table><thead><tr><th>Residue</th><th>Check</th><th>Severity</th>"
            "<th>Code</th><th>Finding</th></tr></thead><tbody>"
        )
        for finding in notable:
            where = str(finding.key) if finding.key is not None else "whole site"
            sev = finding.severity.value
            parts.append(
                f'<tr><td class="mono">{escape(where)}</td>'
                f"<td>{escape(finding.check)}</td>"
                f'<td><span class="sev sev-{sev}">{sev}</span></td>'
                f'<td class="mono">{escape(finding.code)}</td>'
                f"<td>{escape(finding.message)}{_evidence(finding)}</td></tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append("<p>No residue raised a warning or a blocking finding.</p>")

    if passed:
        keys = _distinct_keys(passed)
        label = f"{len(passed)} passing check(s) on {len(keys)} residue(s)"
        items = "".join(f"<li>{escape(k)}</li>" for k in keys)
        parts.append(
            f"<details><summary>{escape(label)}</summary>"
            f'<ul class="keys">{items}</ul></details>'
        )
    parts.append("</section>")
    return "".join(parts)


def _formats_section(tool_formats: Mapping[str, str]) -> str:
    """The downstream hotspot strings, each in its own copyable block."""
    parts = [
        '<section id="formats"><h2>Downstream tool formats</h2>',
        "<p>These are the same residues written in each tool's own hotspot "
        "syntax. They are not interchangeable: the numbering differs.</p>",
    ]
    extra = sorted(k for k in tool_formats if k not in TOOL_ORDER)
    for tool in (*TOOL_ORDER, *extra):
        value = (tool_formats.get(tool) or "").strip()
        shape = _FORMAT_SHAPES.get(tool, _ANY_FORMAT)
        parts.append(f'<div class="fmt"><h3>{escape(tool)}</h3>')
        if value and shape.match(value):
            parts.append(f"<code>{escape(value)}</code>")
        else:
            why = escape(value) if value else "No reason recorded."
            parts.append(f"<p>This format could not be produced. {why}</p>")
        parts.append("</div>")
    parts.append("</section>")
    return "".join(parts)


def _repro_section(run: PreflightRun) -> str:
    """Everything needed to reproduce the run: collapsed because most readers
    want the verdict, present because a reviewer who doubts it needs the digest
    and every pinned threshold without having to ask."""
    rows: list[tuple[str, str]] = [
        ("input digest", str(run.input_digest)),
        # The base name only, never a path: the record must not embed the
        # machine it was produced on. The digest above is what identifies the
        # coordinates.
        ("input file", run.input_filename or "not recorded"),
        ("target", str(run.target_id)),
        ("biological assembly", str(run.assembly_id or "none declared by the entry")),
        ("hotspot specification", str(run.hotspot_spec)),
        ("hotspot residues", ", ".join(str(k) for k in run.keys) or "none"),
    ]
    if run.crop_range is not None:
        chain, start, end = run.crop_range
        rows.append(("target crop", f"chain {chain}, residues {start} to {end}"))
    else:
        rows.append(("target crop", "none - the full structure was used"))
    rows.extend(_flatten(run.parameters))

    items = "".join(
        f'<dt>{escape(name)}</dt><dd class="mono">{escape(value)}</dd>'
        for name, value in rows
    )
    return (
        '<section id="reproducibility"><h2>Reproducibility</h2><details><summary>'
        f"Input digest, numbering and every pinned parameter</summary>"
        f"<dl>{items}</dl></details></section>"
    )


# --- Helpers ---------------------------------------------------------------


def _evidence(finding: Finding) -> str:
    """The numbers behind a finding, so a reader can disagree with a threshold.

    Keys are sorted because each check builds ``evidence`` in whatever order its
    code runs, and an unsorted render would not be byte-identical.
    """
    if not finding.evidence:
        return ""
    items = "".join(
        f"<dt>{escape(str(k))}</dt><dd>{escape(str(v))}</dd>"
        for k, v in sorted(finding.evidence.items(), key=lambda kv: str(kv[0]))
    )
    return f"<details><summary>Evidence</summary><dl>{items}</dl></details>"


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Nested parameter blocks as sorted dotted leaf paths. ``run.parameters``
    nests checks/thresholds/sasa, and a plain ``str()`` per top-level key would
    print a Python dict repr, burying every threshold and the SASA
    ``reference_id`` in one blob instead of one readable row per setting."""
    if isinstance(value, Mapping):
        rows: list[tuple[str, str]] = []
        for key, sub in sorted(value.items(), key=lambda kv: str(kv[0])):
            rows.extend(_flatten(sub, f"{prefix}.{key}" if prefix else str(key)))
        return rows
    if isinstance(value, (list, tuple)):
        return [(prefix, ", ".join(str(v) for v in value) or "none")]
    return [(prefix, str(value))]


def _distinct_keys(findings: Iterable[Finding]) -> list[str]:
    """Residue names in first-seen order. ``dict.fromkeys`` rather than a set,
    because a set would reorder them and break byte-identical output."""
    return list(dict.fromkeys(
        str(f.key) if f.key is not None else "whole site" for f in findings
    ))
