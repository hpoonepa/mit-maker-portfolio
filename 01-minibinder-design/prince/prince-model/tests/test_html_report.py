# SPDX-License-Identifier: MIT
"""Tests for the single-file HTML report.

These build :class:`SiteReport` and ``PreflightRun`` objects by hand rather
than running the checks against a structure. The checks have their own suites;
duplicating them here would make this file slow, and would couple a rendering
regression to a structural-biology regression so that neither failure points at
its own cause.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from hotspot_preflight.findings import Finding, Severity, SiteReport, Verdict
from hotspot_preflight.html_report import TOOL_NAME, TOOL_VERSION, render_html
from hotspot_preflight.html_report import write_html
from hotspot_preflight.report import PreflightRun
from hotspot_preflight.residue import (
    ResidueKey,
    to_bindcraft,
    to_boltzgen,
    to_rfdiffusion,
)

# Void elements never close, so a balance check must not expect an end tag.
_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input",
     "link", "meta", "source", "track", "wbr"}
)


class _Structure(HTMLParser):
    """Collects the element tree shape and flags unbalanced tags.

    Asserting on tag balance catches the failure mode that a substring check
    cannot: an unescaped ``<`` in a message closing a cell early still leaves
    the expected substrings in the output.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.tags: list[str] = []
        self.ids: set[str] = set()
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        for name, value in attrs:
            if name == "id" and value:
                self.ids.add(value)
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if not self.stack:
            self.errors.append(f"</{tag}> with nothing open")
        elif self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closed while <{self.stack[-1]}> was open")
        else:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def parse(markup: str) -> _Structure:
    parser = _Structure()
    parser.feed(markup)
    parser.close()
    assert parser.errors == [], parser.errors
    assert parser.stack == [], f"never closed: {parser.stack}"
    return parser


def kill(key: ResidueKey, code: str = "UNMODELLED", **evidence: Any) -> Finding:
    return Finding(
        check="resolved",
        severity=Severity.KILL,
        code=code,
        message=f"residue {key} was never observed in the deposited coordinates",
        key=key,
        evidence=evidence,
    )


def ok(key: ResidueKey) -> Finding:
    return Finding("resolved", Severity.PASS, "RESOLVED",
                   f"residue {key} is resolved", key)


def make_run(
    findings: list[Finding] | None = None,
    **overrides: Any,
) -> PreflightRun:
    fields: dict[str, Any] = {
        "report": SiteReport(findings=list(findings or [])),
        "target_id": "6F5J",
        "assembly_id": "1",
        "hotspot_spec": "C405,C408",
        "keys": [ResidueKey("C", 405), ResidueKey("C", 408)],
        "crop_range": None,
        "tool_formats": {"rfdiffusion": "[C405,C408]",
                         "bindcraft": "C405,C408", "boltzgen": "C312,C315"},
        "parameters": {"probe_radius": 1.4, "algorithm": "LeeRichards",
                       "n_slices": 20, "freesasa_version": "2.2.1"},
        "input_digest": "sha256:0f1e2d3c4b5a69788796a5b4c3d2e1f0",
    }
    fields.update(overrides)
    return PreflightRun(**fields)


# --- Structure -------------------------------------------------------------


def test_renders_well_formed_markup_with_the_required_sections() -> None:
    html = render_html(make_run([kill(ResidueKey("C", 405)), ok(ResidueKey("C", 408))]))
    tree = parse(html)

    assert html.startswith("<!DOCTYPE html>")
    assert "html" in tree.tags and "head" in tree.tags and "body" in tree.tags
    assert "style" in tree.tags
    assert {"verdict", "reasons", "residues", "formats", "reproducibility"} <= tree.ids


def test_title_is_a_short_name_not_a_sentence() -> None:
    html = render_html(make_run())
    title = html.split("<title>", 1)[1].split("</title>", 1)[0]
    assert "." not in title
    assert 1 <= len(title.split()) <= 4


@pytest.mark.parametrize(
    ("findings", "phrase"),
    [
        ([], "GO"),
        (
            [
                Finding(
                    check="resolved",
                    severity=Severity.WARN,
                    code="LOW_OCCUPANCY",
                    message="atoms present but at zero occupancy",
                    key=ResidueKey("C", 405),
                )
            ],
            "GO WITH WARNINGS",
        ),
        ([kill(ResidueKey("C", 405))], "STOP"),
    ],
)
def test_verdict_appears_in_words(findings: list[Finding], phrase: str) -> None:
    html = render_html(make_run(findings))
    assert phrase in html
    # Words, not a bare enum repr: GO_WITH_WARNINGS must never reach the page.
    assert Verdict.GO_WITH_WARNINGS.value not in html


def test_verdict_shows_the_kill_count() -> None:
    html = render_html(
        make_run([kill(ResidueKey("C", 405)), kill(ResidueKey("C", 408))])
    )
    assert "2" in html.split('id="verdict"', 1)[1].split("</section>", 1)[0]


def test_empty_run_renders_a_clean_go_page() -> None:
    html = render_html(make_run([]))
    parse(html)
    assert "GO" in html
    assert "STOP" not in html
    # No findings must not mean an empty, confusing page.
    assert "reproducibility" in html


# --- Kill reasons in plain language ----------------------------------------


def test_kill_reasons_name_the_cause_in_plain_language() -> None:
    html = render_html(
        make_run(
            [
                kill(ResidueKey("C", 405), "UNMODELLED"),
                kill(ResidueKey("C", 408), "BURIED_IN_ASSEMBLY"),
                kill(ResidueKey("C", 410), "WRONG_NUMBERING_SCHEME"),
            ]
        )
    )
    reasons = html.split('id="reasons"', 1)[1].split("</section>", 1)[0]
    # Case-insensitive: only the leading letter of a cause is presentational.
    assert "never observed in the deposited coordinates" in reasons.lower()
    assert "buried on the biological assembly" in reasons.lower()
    assert "label_seq" in reasons
    # Brand names must survive the sentence-casing, not be flattened.
    assert "BoltzGen" in reasons
    # And a reader who does not know the tool is told what to do.
    assert "What to do" in reasons


def test_an_unknown_kill_code_still_renders_its_message() -> None:
    """A new check must not produce a blank reason before this file is updated."""
    html = render_html(make_run([kill(ResidueKey("C", 405), "SOME_FUTURE_CODE")]))
    assert "SOME_FUTURE_CODE" in html
    assert "never observed in the deposited coordinates" in html


def test_reduced_confidence_is_visible_not_smoothed_away() -> None:
    html = render_html(
        make_run(
            [
                Finding(
                    check="resolved",
                    severity=Severity.WARN,
                    code="NO_UNOBS_CATEGORY",
                    message=(
                        "6F5J omits the optional "
                        "_pdbx_unobs_or_zero_occ_residues category"
                    ),
                )
            ]
        )
    )
    assert "Confidence" in html
    assert "_pdbx_unobs_or_zero_occ_residues" in html


# --- Residue table ---------------------------------------------------------


def test_failing_residues_get_a_row_each() -> None:
    html = render_html(
        make_run([kill(ResidueKey("C", 405)), kill(ResidueKey("C", 408))])
    )
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert body.count("<tr") == 2
    assert "C405" in body and "C408" in body
    assert "KILL" in body and "resolved" in body


def test_fifty_passing_residues_are_a_count_not_fifty_rows() -> None:
    passing = [ok(ResidueKey("C", 300 + i)) for i in range(50)]
    html = render_html(make_run(passing + [kill(ResidueKey("C", 405))]))
    parse(html)

    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert body.count("<tr") == 1, "passing residues must not be expanded inline"
    assert "50" in html
    assert "<details" in html
    # The names are still available, just disclosed rather than expanded.
    assert "C349" in html


def test_severity_is_legible_without_colour() -> None:
    """Greyscale and colourblind readers get a text label, not a hue."""
    html = render_html(make_run([kill(ResidueKey("C", 405))]))
    assert ">KILL<" in html
    for char in html:
        assert ord(char) < 0x2190, f"non-ASCII glyph {char!r} in a greyscale report"


# --- Tool formats ----------------------------------------------------------


def test_tool_formats_are_in_copyable_code_blocks() -> None:
    html = render_html(make_run())
    formats = html.split('id="formats"', 1)[1].split("</section>", 1)[0]
    assert formats.count("<code") >= 3
    assert "[C405,C408]" in formats
    assert "C312,C315" in formats


def test_an_unproducible_format_shows_the_explanation_instead() -> None:
    """``translate_for_tools`` stores the reason under the tool's own key.

    So a value is either a hotspot string or a sentence, and prose must never be
    rendered as a copyable format - someone would paste it into a design config.
    """
    reason = "C52A carries insertion code 'A', which RFdiffusion cannot express"
    html = render_html(
        make_run(
            tool_formats={
                "rfdiffusion": reason,
                "bindcraft": "C405,C408",
                "boltzgen": "C312,C315",
            }
        )
    )
    formats = html.split('id="formats"', 1)[1].split("</section>", 1)[0]
    assert "could not be produced" in formats
    assert "insertion code" in formats
    # The two that worked are still offered, and the reason is not one of them.
    assert formats.count("<code") == 2
    assert "C405,C408" in formats and "C312,C315" in formats
    for block in formats.split("<code")[1:]:
        assert "insertion code" not in block.split("</code>", 1)[0]


def test_a_missing_format_key_is_reported_not_skipped() -> None:
    html = render_html(make_run(tool_formats={"bindcraft": "C405,C408"}))
    formats = html.split('id="formats"', 1)[1].split("</section>", 1)[0]
    for tool in ("rfdiffusion", "bindcraft", "boltzgen"):
        assert tool in formats
    assert formats.count("could not be produced") == 2
    assert "No reason recorded" in formats


def test_provenance_filename_is_shown_when_present() -> None:
    html = render_html(make_run(input_filename="6f5j_updated.cif"))
    assert "6f5j_updated.cif" in html


# --- Reproducibility -------------------------------------------------------


def test_real_tool_formats_classify_as_formats_not_prose() -> None:
    """Pins the classifier against the real emitters, in both directions.

    The format/reason union is inferred from punctuation, so this is the test
    that fails loudly the day a real format gains a space or numbering.py
    adopts a sentinel instead - rather than the report quietly mislabelling one.
    """
    keys = [ResidueKey("C", 325), ResidueKey("C", 326)]
    label_map = {keys[0]: 312, keys[1]: 313}
    formats = {
        "rfdiffusion": to_rfdiffusion(keys),
        "bindcraft": to_bindcraft(keys),
        "boltzgen": to_boltzgen(keys, label_map),
    }
    html = render_html(make_run(tool_formats=formats))
    section = html.split('id="formats"', 1)[1].split("</section>", 1)[0]
    assert "could not be produced" not in section
    assert section.count("<code") == 3
    for value in formats.values():
        assert f"<code>{value}</code>" in section


def test_a_real_boltzgen_failure_reason_is_rendered_as_prose() -> None:
    """The reason is generated by the real emitter, not pasted in, so this test
    cannot drift from the message numbering.py actually produces."""
    keys = [ResidueKey("C", 405), ResidueKey("C", 408)]
    try:
        to_boltzgen(keys, {})  # empty map: no label_seq_id for either residue
    except KeyError as exc:
        reason = str(exc.args[0])
    else:  # pragma: no cover - a silent pass here would void the whole test
        pytest.fail("to_boltzgen accepted residues absent from the label map")

    html = render_html(
        make_run(
            tool_formats={
                "rfdiffusion": "[C405,C408]",
                "bindcraft": "C405,C408",
                "boltzgen": reason,
            }
        )
    )
    section = html.split('id="formats"', 1)[1].split("</section>", 1)[0]
    assert "could not be produced" in section
    # The reason itself, whatever numbering.py currently words it as. Asserting
    # on fixed wording would make this test a copy of the message rather than a
    # check that the message is classified and shown.
    assert escape(reason) in section
    # The two usable formats are still offered, and the reason is not one.
    assert section.count("<code") == 2
    for block in section.split("<code")[1:]:
        assert reason not in block.split("</code>", 1)[0]


def test_nested_parameters_are_flattened_not_dumped_as_dict_reprs() -> None:
    """``run.parameters`` nests checks/thresholds/sasa. A Python repr on the page
    buries every pinned threshold and the SASA reference_id inside one blob."""
    html = render_html(
        make_run(
            parameters={
                "checks": ["resolved", "numbering", "burial"],
                "thresholds": {"burial_rel_sasa": 0.2, "low_occupancy": 0.1},
                "sasa": {"probe_radius": 1.4, "reference_id": "sha256:deadbeef"},
            }
        )
    )
    assert "sasa.probe_radius" in html
    assert "sasa.reference_id" in html
    assert "sha256:deadbeef" in html
    assert "thresholds.burial_rel_sasa" in html
    assert "0.2" in html
    assert "resolved, numbering, burial" in html
    # No Python container repr anywhere on the page.
    for repr_marker in ("&#x27;", "{&", "[&"):
        assert repr_marker not in html


def test_every_parameter_appears_in_the_output() -> None:
    parameters = {
        "probe_radius": 1.4,
        "algorithm": "LeeRichards",
        "algorithm_parameter": "n_slices",
        "n_slices": 20,
        "classifier": "ProtOr",
        "include_hydrogens": False,
        "include_hetatm": True,
        "relative_sasa_method": "empirical",
        "neighbour_cutoff_a": 12.0,
        "focus_chain": "C",
        "freesasa_version": "2.2.1",
        "gemmi_version": "0.7.5",
    }
    html = render_html(make_run(parameters=parameters))
    for key, value in parameters.items():
        assert key in html, key
        assert str(value) in html, f"{key}={value}"


def test_reproducibility_is_collapsed_but_present() -> None:
    html = render_html(make_run())
    repro = html.split('id="reproducibility"', 1)[1].split("</section>", 1)[0]
    assert "<details" in repro
    assert "open" not in repro.split(">", 1)[0]
    assert "sha256:0f1e2d3c4b5a69788796a5b4c3d2e1f0" in repro
    assert "6F5J" in repro


def test_crop_range_is_reported_when_present() -> None:
    html = render_html(make_run(crop_range=("C", 280, 420)))
    assert "280" in html and "420" in html


def test_footer_names_the_tool_and_licence() -> None:
    html = render_html(make_run())
    assert TOOL_NAME in html
    assert TOOL_VERSION in html
    assert "MIT" in html


def _pyproject_version() -> str:
    """The version in the ``[project]`` table. ``tomllib`` is 3.11+ and this
    project supports 3.10, so there is a fallback rather than a skip: a drift
    test that silently does not run is the same lie as having no test."""
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    try:
        import tomllib
    except ImportError:
        table = text.split("\n[project]\n", 1)[1].split("\n[", 1)[0]
        found = re.search(r'^version\s*=\s*"([^"]+)"', table, re.M)
        assert found is not None, "no version in the [project] table"
        return found.group(1)
    return str(tomllib.loads(text)["project"]["version"])


def test_tool_version_matches_pyproject() -> None:
    """``TOOL_VERSION`` is hardcoded so a checkout and an installed wheel render
    byte-identical reports; the cost is that it can drift from the package, and
    a report stamped with a version the package lacks is its own small lie."""
    assert TOOL_VERSION == _pyproject_version()


# --- Self-containment ------------------------------------------------------


def test_no_remote_resources() -> None:
    html = render_html(make_run([kill(ResidueKey("C", 405))]))
    assert "http://" not in html
    assert "https://" not in html
    assert "//" not in html.replace("<!DOCTYPE html>", "")
    tree = parse(html)
    for tag in ("script", "link", "img", "iframe", "object", "embed", "svg", "video"):
        assert tag not in tree.tags, f"<{tag}> can reach the network"
    assert "src=" not in html
    assert "@import" not in html
    assert "url(" not in html


def test_hostile_input_is_inert_and_the_document_survives() -> None:
    payload = '<script>alert("pwned")</script>'
    hostile = Finding(
        check='resolved" onmouseover="alert(1)',
        severity=Severity.KILL,
        code="UNMODELLED",
        message=f"residue {payload} & <b>bold</b> 'quoted'",
        key=ResidueKey("C", 405),
        evidence={"<claim>": '"><img onerror=alert(1)>'},
    )
    html = render_html(
        make_run([hostile], hotspot_spec=payload, target_id=f"6F5J{payload}")
    )

    tree = parse(html)
    assert "script" not in tree.tags
    assert "img" not in tree.tags
    assert 'alert("pwned")' not in html
    assert "&lt;script&gt;" in html
    # The payload survives as readable text, so the reader sees what was passed.
    assert any('<script>alert("pwned")</script>' in chunk for chunk in tree.text)
    # And the document is intact, not truncated at the injection point.
    assert "reproducibility" in tree.ids
    assert html.rstrip().endswith("</html>")


# --- Determinism -----------------------------------------------------------


def test_two_renders_are_byte_identical() -> None:
    run = make_run([kill(ResidueKey("C", 405)), ok(ResidueKey("C", 408))])
    first = render_html(run)
    second = render_html(run)
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


def test_no_timestamp_unless_injected() -> None:
    plain = render_html(make_run())
    stamped = render_html(make_run(), generated_at="2026-10-05")
    assert "2026-10-05" in stamped
    assert "2026-10-05" not in plain
    assert len(stamped) > len(plain)


def test_parameter_order_does_not_change_the_output() -> None:
    """Sorted rendering, so a dict built in a different order still diffs clean."""
    forward = render_html(make_run(parameters={"a": 1, "b": 2, "c": 3}))
    reverse = render_html(make_run(parameters={"c": 3, "b": 2, "a": 1}))
    assert forward == reverse


# --- Theming ---------------------------------------------------------------


def test_dark_mode_properties_under_all_three_selectors() -> None:
    html = render_html(make_run())
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert ":root {" in style
    assert "@media (prefers-color-scheme: dark)" in style
    media = style.split("@media (prefers-color-scheme: dark)", 1)[1]
    assert ':root:not([data-theme="light"])' in media
    assert ':root[data-theme="dark"]' in style

    # Each selector must actually redefine the palette, not merely exist.
    for block in (
        style.split(":root {", 1)[1],
        media.split(':root:not([data-theme="light"])', 1)[1],
        style.split(':root[data-theme="dark"]', 1)[1],
    ):
        assert "--bg:" in block.split("}", 1)[0]
        assert "--fg:" in block.split("}", 1)[0]

    assert "body {" in style and "background: var(--bg)" in style


def test_readable_at_phone_width() -> None:
    html = render_html(make_run())
    assert 'name="viewport"' in html
    assert "width=device-width" in html


# --- write_html ------------------------------------------------------------


def test_write_html_round_trips(tmp_path: Any) -> None:
    run = make_run([kill(ResidueKey("C", 405))])
    path = tmp_path / "report.html"
    assert write_html(run, path) is None
    assert path.read_text(encoding="utf-8") == render_html(run)


def test_write_html_accepts_a_string_path(tmp_path: Any) -> None:
    path = tmp_path / "nested" / "report.html"
    path.parent.mkdir()
    write_html(make_run(), str(path))
    assert path.exists()
    parse(path.read_text(encoding="utf-8"))
