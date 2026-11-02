"""Running the checks, and rendering them for a human.

The run record and its schema are a separate deliverable and have their own file;
see tests/test_record.py. What is left here is the aggregation contract -- which
checks run, in what order, and what survives a hotspot on a chain that does not
exist -- plus the two things a person actually reads.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from hotspot_preflight.findings import Severity, Verdict, sort_findings
from hotspot_preflight.report import (
    CHECK_ORDER,
    PreflightRun,
    render_text,
    run_preflight,
    to_run_record,
    write_csv,
)
from hotspot_preflight.residue import ResidueKey, parse_hotspot_spec
from hotspot_preflight.structure import load_target

@pytest.fixture
def clean_run(cif_with_unobs_category: Path) -> PreflightRun:
    """A101/A102 are modelled and exposed; the entry declares no assembly, so
    NO_ASSEMBLY_DEFINED is the only finding above PASS."""
    target = load_target(cif_with_unobs_category)
    return run_preflight(
        target, parse_hotspot_spec("A101,A102"), hotspot_spec="A101,A102"
    )


@pytest.fixture
def killed_run(cif_with_unobs_category: Path) -> PreflightRun:
    """A104 is declared but unmodelled - the 6F5J chain C failure, in miniature."""
    target = load_target(cif_with_unobs_category)
    return run_preflight(
        target, parse_hotspot_spec("A101,A104"), hotspot_spec="A101,A104"
    )


def test_run_preflight_runs_all_three_checks(clean_run: PreflightRun) -> None:
    assert {f.check for f in clean_run.report.findings} == set(CHECK_ORDER)
    assert to_run_record(clean_run)["parameters"]["checks"] == list(CHECK_ORDER)


def test_run_preflight_findings_are_in_canonical_order(
    killed_run: PreflightRun,
) -> None:
    """The checks return findings in caller order; the aggregator sorts."""
    assert killed_run.report.findings == sort_findings(killed_run.report.findings)


def test_verdicts_follow_the_worst_finding(
    killed_run: PreflightRun, clean_run: PreflightRun
) -> None:
    assert killed_run.report.verdict is Verdict.STOP
    assert "UNMODELLED" in killed_run.report.kill_codes()
    assert clean_run.report.verdict is Verdict.GO_WITH_WARNINGS
    # HOTSPOT_COUNT_UNUSUAL also fires on this 2-residue fixture, but at PASS,
    # so the only thing qualifying the verdict is a fact about the entry.
    assert [f.code for f in clean_run.report.warnings] == ["NO_ASSEMBLY_DEFINED"]


def test_run_preflight_rejects_an_empty_hotspot_list(
    cif_with_unobs_category: Path,
) -> None:
    with pytest.raises(ValueError, match="no hotspot residues"):
        run_preflight(load_target(cif_with_unobs_category), [])


def test_phantom_chain_is_reported_not_raised(
    cif_with_unobs_category: Path,
) -> None:
    """check_burial raises on an unknown chain; check_resolved explains it, so
    burial is skipped for those keys to keep the better message."""
    target = load_target(cif_with_unobs_category)
    run = run_preflight(target, [ResidueKey("Z", 101)], hotspot_spec="Z101")
    assert run.report.verdict is Verdict.STOP
    assert "NO_SUCH_CHAIN" in run.report.kill_codes()


def test_crop_range_reaches_the_burial_check(cif_with_unobs_category: Path) -> None:
    target = load_target(cif_with_unobs_category)
    run = run_preflight(
        target,
        parse_hotspot_spec("A101"),
        crop_range=("A", 101, 102),
        hotspot_spec="A101",
    )
    assert run.crop_range == ("A", 101, 102)
    evidence = [
        f.evidence for f in run.report.findings if f.check == "burial" and f.key
    ]
    assert any(e.get("relative_sasa_crop") is not None for e in evidence)


def test_bad_crop_range_raises_for_the_boundary_to_catch(
    cif_with_unobs_category: Path,
) -> None:
    target = load_target(cif_with_unobs_category)
    with pytest.raises(ValueError, match="no observed residues"):
        run_preflight(
            target, parse_hotspot_spec("A101"), crop_range=("A", 900, 999)
        )




def test_render_text_leads_with_the_verdict(killed_run: PreflightRun) -> None:
    assert render_text(killed_run).splitlines()[0] == "VERDICT: STOP"


def test_render_text_names_each_killed_residue_worst_finding_first(
    killed_run: PreflightRun,
) -> None:
    """The canonical order sorts by check name, which would print A104's WARN
    above its KILL. The human report must not bury the line that decided it."""
    text = render_text(killed_run)
    assert "never observed" in text
    lines = [line for line in text.splitlines() if " A104: " in line]
    assert lines and lines[0].startswith("KILL")


def test_render_text_summarises_passing_residues_as_a_count(
    killed_run: PreflightRun,
) -> None:
    text = render_text(killed_run)
    assert "1 of 2 hotspot residues passed every check" in text
    # The passing residue is counted, not listed with its PASS findings.
    assert "is declared and present in the coordinates" not in text


def test_render_text_ends_with_the_tool_format_strings(
    clean_run: PreflightRun,
) -> None:
    text = render_text(clean_run)
    assert "rfdiffusion" in text and "[A101,A102]" in text
    assert "bindcraft" in text and "A101-102" in text
    assert "boltzgen" in text
    assert text.index("rfdiffusion") > text.index("VERDICT")


def test_render_text_returns_plain_text_and_does_not_print(
    killed_run: PreflightRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """report.py is consumed by the CLI, the tests and the JSON writer; a
    module that prints could serve only one of the three."""
    text = render_text(killed_run)
    assert "\x1b[" not in text
    assert all(ord(ch) < 128 or ch in "—" for ch in text)
    assert capsys.readouterr() == ("", "")


def test_render_text_mentions_the_crop_when_one_was_used(
    cif_with_unobs_category: Path,
) -> None:
    target = load_target(cif_with_unobs_category)
    keys = parse_hotspot_spec("A101")
    run = run_preflight(target, keys, crop_range=("A", 101, 103))
    assert "A101-103" in render_text(run)


def test_write_csv_emits_one_row_per_finding(
    killed_run: PreflightRun, tmp_path: Path
) -> None:
    out = tmp_path / "findings.csv"
    write_csv(killed_run, out)
    rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert len(rows) == len(killed_run.report.findings)
    assert rows[0]["code"] == killed_run.report.findings[0].code
    assert rows[0]["severity"] in {"PASS", "WARN", "KILL"}


def test_write_csv_keeps_evidence_as_json_and_takes_a_string_path(
    killed_run: PreflightRun, tmp_path: Path
) -> None:
    out = tmp_path / "as_str.csv"
    write_csv(killed_run, str(out))
    rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
    for row in rows:
        assert isinstance(json.loads(row["evidence_json"]), dict)


@pytest.mark.network
def test_6f5j_unmodelled_hotspots_stop_the_campaign(real_6f5j: Path) -> None:
    """C405 and C408 are the hotspots 35 designs were ordered against."""
    target = load_target(real_6f5j)
    run = run_preflight(
        target, parse_hotspot_spec("C405,C408"), hotspot_spec="C405,C408"
    )
    assert run.report.verdict is Verdict.STOP
    assert "UNMODELLED" in run.report.kill_codes()
    assert "never observed" in render_text(run)


@pytest.mark.network
def test_6f5j_real_binder_epitope_passes(real_6f5j: Path) -> None:
    """C325/C326 is the epitope of l79_s469532_mpnn9, KD 604 nM by BLI.

    A filter that rejects everything is worthless, so this is the more important
    of the two real-entry tests. The record built from it is validated in
    tests/test_record.py, which owns that contract.
    """
    target = load_target(real_6f5j)
    keys = parse_hotspot_spec("C325,C326")
    run = run_preflight(target, keys, hotspot_spec="C325,C326", patch=False)
    assert run.report.verdict is Verdict.GO
    assert all(f.severity is Severity.PASS for f in run.report.findings)
    assert run.assembly_id is not None


@pytest.mark.network
def test_count_note_is_reported_without_demoting_the_binder_epitope(
    real_6f5j: Path,
) -> None:
    """The note fires on an assay-confirmed site and does not qualify it.

    C325/C326 is a two-residue specification — below the 3-6 RFdiffusion's README
    recommends — and it is the epitope of the one binder in 35 that worked, at
    604 nM by BLI. Widening it is not an option either: C327 is buried on the
    assembly, so C325-C327 is a KILL. So the count note must fire *and* leave the
    verdict at GO. Both halves are asserted, because losing the note would drop
    real advice and raising it to WARN would fail a site we know binds.
    """
    target = load_target(real_6f5j)
    keys = parse_hotspot_spec("C325,C326")
    run = run_preflight(target, keys, hotspot_spec="C325,C326")
    assert run.report.verdict is Verdict.GO
    assert not run.report.kills and not run.report.warnings
    note = next(f for f in run.report.findings if f.code == "HOTSPOT_COUNT_UNUSUAL")
    assert note.severity is Severity.PASS
    # Site-level findings have no residue count to be folded into, so the text
    # report must still show it.
    assert "HOTSPOT_COUNT_UNUSUAL" in render_text(run)
    assert "NOTE (whole entry):" in render_text(run)
