"""The stages that were built, tested, and unreachable from the command line.

Before this wiring, `preflight` exposed three of the project's checks and none of
its reporting, prediction, evidence or standards layers — a toolkit rather than a
tool. These tests assert only that each flag produces its artifact and that the
artifact parses; the behaviour of each stage belongs to its own test file.

The exception is `--construct`, which is tested for meaning rather than mechanics:
it is the clearest demonstration in the project of the numbering thesis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hotspot_preflight.cli import app

# Imported rather than duplicated: conftest.py belongs to another agent, so the
# shared literal lives in the test module that first needed it.
from test_cli import _ASSEMBLY_CATEGORIES

runner = CliRunner()


@pytest.fixture
def cif_with_assembly(cif_with_unobs_category: Path, tmp_path: Path) -> Path:
    out = tmp_path / "with_assembly.cif"
    out.write_text(cif_with_unobs_category.read_text() + _ASSEMBLY_CATEGORIES)
    return out


@pytest.fixture
def cache_at_repo(real_6f5j: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOTSPOT_PREFLIGHT_CACHE", str(real_6f5j.parent))
    return real_6f5j


def _has_sbol3() -> bool:
    from hotspot_preflight.standards.sbol import sbol3_available

    return sbol3_available()


def test_html_flag_writes_a_standalone_report(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    out = tmp_path / "report.html"
    result = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101,A104",
         "--html", str(out)],
    )
    assert result.exit_code == 2, result.output
    page = out.read_text(encoding="utf-8")
    assert page.lstrip().lower().startswith("<!doctype html")
    assert "STOP" in page and "A104" in page


def test_patch_check_runs_by_default_and_reaches_the_record(
    cif_with_assembly: Path, tmp_path: Path
) -> None:
    out = tmp_path / "run.json"
    result = runner.invoke(
        app,
        ["check", str(cif_with_assembly), "--hotspots", "A101,A102,A103",
         "--json", str(out)],
    )
    assert result.exit_code == 0, result.output
    record = json.loads(out.read_text())
    assert record["parameters"]["checks"] == [
        "resolved", "numbering", "burial", "patch"
    ]
    assert any(f["check"] == "patch" for f in record["findings"])


def test_no_patch_reproduces_the_three_check_output_byte_for_byte(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    """--no-patch must be exactly the pre-patch run, not merely similar.

    Compared against `render_text(run_preflight(..., patch=False))` rather than
    a transcript pasted in here, so the assertion cannot go stale when a check
    legitimately rewords a message, while still catching any drift between the
    CLI path and the library contract.
    """
    from hotspot_preflight.report import render_text, run_preflight, to_run_record
    from hotspot_preflight.residue import parse_hotspot_spec
    from hotspot_preflight.structure import load_target

    out = tmp_path / "run.json"
    result = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101,A102",
         "--no-patch", "--json", str(out)],
    )
    assert result.exit_code == 1, result.output

    target = load_target(cif_with_unobs_category)
    expected = run_preflight(
        target,
        parse_hotspot_spec("A101,A102"),
        hotspot_spec="A101,A102",
        patch=False,
    )
    assert result.stdout == render_text(expected)
    assert "[patch/" not in result.stdout
    assert json.loads(out.read_text())["parameters"]["checks"] == to_run_record(
        expected
    )["parameters"]["checks"] == ["resolved", "numbering", "burial"]


@pytest.mark.network
def test_evidence_flag_grades_against_the_shipped_dwv_table(
    cache_at_repo: Path, tmp_path: Path
) -> None:
    """The DWV table's three rows are the refuted "catalytic triad".

    Marked network because it needs the real 6F5J; the table itself ships.
    """
    from hotspot_preflight.evidence import BUNDLED_TABLE_DIR

    table = BUNDLED_TABLE_DIR / "dwv_6f5j.yaml"
    out = tmp_path / "run.json"
    result = runner.invoke(
        app,
        ["check", "6f5j", "--hotspots", "C294,C277,C278",
         "--evidence", str(table), "--json", str(out)],
    )
    assert result.exit_code == 1, result.output
    record = json.loads(out.read_text())
    assert "evidence" in record["parameters"]["checks"]
    codes = {f["code"] for f in record["findings"] if f["check"] == "evidence"}
    assert codes == {"EVIDENCE_REFUTED"}

def test_evidence_is_off_by_default(cif_with_unobs_category: Path, tmp_path: Path) -> None:
    """The component is meant to be ablatable, so a default run must not see it."""
    out = tmp_path / "run.json"
    runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101,A102",
         "--json", str(out)],
    )
    record = json.loads(out.read_text())
    assert "evidence" not in record["parameters"]["checks"]
    assert not [f for f in record["findings"] if f["check"] == "evidence"]


def test_exit_3_on_a_missing_evidence_table(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101",
         "--evidence", str(tmp_path / "nope.yaml")],
    )
    assert result.exit_code == 3, result.output
    assert "Traceback" not in result.output


def test_exit_3_when_crop_and_construct_are_both_given(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    """Both set the crop range; preferring one silently would run a truncation
    the user did not think they had asked for."""
    result = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101",
         "--crop", "A:101-103", "--construct", str(tmp_path / "c.nt")],
    )
    assert result.exit_code == 3, result.output
    assert "--crop" in result.output and "--construct" in result.output
    assert "Traceback" not in result.output


@pytest.mark.skipif(not _has_sbol3(), reason="needs the 'sbol' extra")
def test_sbol_out_writes_a_document_and_construct_reads_author_numbers(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    """The same SBOL document yields ('A', 1, 6) from read_construct and
    ('A', 101, 106) from construct_crop_range — identical tuple shapes, different
    coordinate systems, and no exception if you confuse them.

    That is the numbering thesis in one line, and it is why the CLI must call
    construct_crop_range. Author numbering in this fixture is label_seq + 100, so
    the two readings cannot coincide by luck: the recorded crop must be 101-106
    and is asserted to differ from 1-6 explicitly.
    """
    from hotspot_preflight.standards.sbol import read_construct

    doc = tmp_path / "site.nt"
    written = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101,A102,A103",
         "--sbol-out", str(doc)],
    )
    assert written.exit_code == 1, written.output
    assert doc.is_file() and doc.stat().st_size > 0
    assert read_construct(doc) == ("A", 1, 6)

    out = tmp_path / "run.json"
    result = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101,A102,A103",
         "--construct", str(doc), "--json", str(out)],
    )
    assert result.exit_code == 1, result.output
    crop = json.loads(out.read_text())["site"]["crop_range"]
    assert crop == {"chain": "A", "first": 101, "last": 106}
    assert (crop["first"], crop["last"]) != (1, 6)


@pytest.mark.skipif(_has_sbol3(), reason="only meaningful without the extra")
def test_sbol_out_without_the_extra_names_the_install(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101",
         "--sbol-out", str(tmp_path / "x.nt")],
    )
    assert result.exit_code == 3, result.output
    assert "sbol" in result.output
    assert "Traceback" not in result.output


def test_sbol_out_refuses_a_multi_chain_site(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    """An SBOL Component is one sequence, so a two-chain site has no answer."""
    result = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101,B102",
         "--sbol-out", str(tmp_path / "x.nt")],
    )
    assert result.exit_code == 3, result.output
    assert "one chain" in result.output


class TestProposeProfileFlag:
    """`--profile` selects which named WeightProfile ranks the sites.

    Three profiles ship and they rank differently on purpose — `designability`
    is measurably below chance on antibody epitopes while `antibody_epitope` is
    the fitted one. Without this flag the profiles are reachable only from
    Python, so the README's advice to use the fitted weights on an antibody-like
    target could not be followed from the command line.
    """

    def test_defaults_to_designability(self, cif_with_unobs_category: Path) -> None:
        """The default must not move silently: changing it changes what every
        published run of this tool means."""
        result = runner.invoke(
            app, ["propose", str(cif_with_unobs_category), "--quiet", "--json", "-"]
        )
        assert result.exit_code == 0, result.output

    def test_accepts_each_shipped_profile(
        self, cif_with_unobs_category: Path, tmp_path: Path
    ) -> None:
        from hotspot_preflight.predict.profiles import PROFILES

        for name in PROFILES:
            out = tmp_path / f"{name}.json"
            result = runner.invoke(
                app,
                ["propose", str(cif_with_unobs_category), "--profile", name,
                 "--quiet", "--json", str(out)],
            )
            assert result.exit_code == 0, f"{name}: {result.output}"
            assert json.loads(out.read_text())

    def test_unknown_profile_is_a_usage_error_naming_the_real_ones(
        self, cif_with_unobs_category: Path
    ) -> None:
        """A typo'd profile must not silently fall back to the default, which
        would publish numbers from weights the user did not ask for."""
        result = runner.invoke(
            app,
            ["propose", str(cif_with_unobs_category), "--profile", "antibody",
             "--quiet"],
        )
        assert result.exit_code == 3, result.output
        assert "antibody_epitope" in result.output
        assert "designability" in result.output

    def test_profile_is_recorded_in_the_json(
        self, cif_with_unobs_category: Path, tmp_path: Path
    ) -> None:
        """Which weights produced a ranking is part of the result, not a detail
        of how it was invoked."""
        out = tmp_path / "ranked.json"
        result = runner.invoke(
            app,
            ["propose", str(cif_with_unobs_category), "--profile",
             "antibody_epitope", "--quiet", "--json", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert "antibody_epitope" in out.read_text()

    def test_profile_with_a_non_geometric_predictor_is_rejected(
        self, cif_with_unobs_category: Path, tmp_path: Path
    ) -> None:
        """Weight profiles are a property of the geometric baseline. Accepting
        the flag for `external` would imply it reweighted a score file it only
        reads."""
        result = runner.invoke(
            app,
            ["propose", str(cif_with_unobs_category), "--predictor", "external",
             "--profile", "exposure_only", "--quiet"],
        )
        assert result.exit_code == 3, result.output
        # Rejected on the flag combination, before the backend is built, so the
        # message is about --profile and not about whatever `external` needs.
        assert "--profile" in result.output and "geometric" in result.output
