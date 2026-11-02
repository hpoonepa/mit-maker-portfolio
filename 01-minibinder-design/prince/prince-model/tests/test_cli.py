# SPDX-License-Identifier: MIT
"""The CLI's contract is its exit code.

A preflight check is only worth building if CI can gate on it, so 0/1/2/3 are
asserted individually and every expected failure is checked to produce prose
rather than a traceback. A traceback is a bug report; a user who typed a hotspot
wrongly needs a correction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hotspot_preflight.cli import app

runner = CliRunner()

# A minimal identity-operation biological assembly, appended to the synthetic
# fixture so that a GO verdict is reachable offline. Without it the burial check
# correctly warns NO_ASSEMBLY_DEFINED and the best attainable verdict is
# GO_WITH_WARNINGS, which would leave exit code 0 testable only over the
# network. `asym_id_list` is the *label* asym id, which gemmi writes as "Axp"
# for this fixture - the author chain id "A" raises "no subchain A".
#
# `method_details` is not optional here either: gemmi reads _pdbx_struct_assembly
# as a fixed column set and silently reports zero assemblies when it is absent,
# which cost an afternoon to find.
_ASSEMBLY_CATEGORIES = """#
loop_
_pdbx_struct_assembly.id
_pdbx_struct_assembly.details
_pdbx_struct_assembly.method_details
_pdbx_struct_assembly.oligomeric_details
_pdbx_struct_assembly.oligomeric_count
1 'author_defined_assembly' ? monomeric 1
#
loop_
_pdbx_struct_assembly_gen.assembly_id
_pdbx_struct_assembly_gen.oper_expression
_pdbx_struct_assembly_gen.asym_id_list
1 1 Axp
#
loop_
_pdbx_struct_oper_list.id
_pdbx_struct_oper_list.type
_pdbx_struct_oper_list.name
_pdbx_struct_oper_list.matrix[1][1]
_pdbx_struct_oper_list.matrix[1][2]
_pdbx_struct_oper_list.matrix[1][3]
_pdbx_struct_oper_list.vector[1]
_pdbx_struct_oper_list.matrix[2][1]
_pdbx_struct_oper_list.matrix[2][2]
_pdbx_struct_oper_list.matrix[2][3]
_pdbx_struct_oper_list.vector[2]
_pdbx_struct_oper_list.matrix[3][1]
_pdbx_struct_oper_list.matrix[3][2]
_pdbx_struct_oper_list.matrix[3][3]
_pdbx_struct_oper_list.vector[3]
1 'identity operation' 1_555 1.0 0.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 0.0 1.0 0.0
#
"""


@pytest.fixture
def cif_with_assembly(cif_with_unobs_category: Path, tmp_path: Path) -> Path:
    """The synthetic entry plus a declared monomeric assembly."""
    out = tmp_path / "with_assembly.cif"
    out.write_text(cif_with_unobs_category.read_text() + _ASSEMBLY_CATEGORIES)
    return out


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_exit_0_when_every_check_passes(cif_with_assembly: Path) -> None:
    """Three contiguous residues: the patch check warns below three, so a
    two-residue site can no longer reach GO."""
    result = runner.invoke(
        app, ["check", str(cif_with_assembly), "--hotspots", "A101,A102,A103"]
    )
    assert result.exit_code == 0, result.output
    assert "VERDICT: GO" in result.output


def test_exit_1_on_warnings_only(cif_with_unobs_category: Path) -> None:
    """The fixture declares no biological assembly, which is a WARN, not a KILL."""
    result = runner.invoke(
        app, ["check", str(cif_with_unobs_category), "--hotspots", "A101,A102,A103"]
    )
    assert result.exit_code == 1, result.output
    assert "VERDICT: GO_WITH_WARNINGS" in result.output
    assert "NO_ASSEMBLY_DEFINED" in result.output


def test_exit_2_when_a_residue_is_killed(cif_with_unobs_category: Path) -> None:
    result = runner.invoke(
        app, ["check", str(cif_with_unobs_category), "--hotspots", "A104"]
    )
    assert result.exit_code == 2, result.output
    assert "VERDICT: STOP" in result.output
    assert "never observed" in result.output


def test_exit_3_on_an_unparseable_hotspot_spec(
    cif_with_unobs_category: Path,
) -> None:
    """Names the offending token and the fix, and shows no traceback."""
    result = runner.invoke(
        app, ["check", str(cif_with_unobs_category), "--hotspots", "405"]
    )
    assert result.exit_code == 3, result.output
    assert "405" in result.output
    assert "A405" in result.output
    assert "Traceback" not in result.output


def test_exit_3_on_a_missing_structure_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.cif"
    result = runner.invoke(app, ["check", str(missing), "--hotspots", "A101"])
    assert result.exit_code == 3, result.output
    assert "nope.cif" in result.output
    assert "Traceback" not in result.output


def test_exit_3_on_an_unreadable_structure_file(tmp_path: Path) -> None:
    junk = tmp_path / "junk.cif"
    junk.write_text("this is not a structure\n")
    result = runner.invoke(app, ["check", str(junk), "--hotspots", "A101"])
    assert result.exit_code == 3, result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# --crop
# ---------------------------------------------------------------------------


def test_crop_accepts_chain_first_last(cif_with_unobs_category: Path) -> None:
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_unobs_category),
            "--hotspots",
            "A101",
            "--crop",
            "A:101-103",
        ],
    )
    assert result.exit_code in (0, 1), result.output
    assert "A101-103" in result.output


@pytest.mark.parametrize("bad", ["A101-103", "A:101:103", "A:abc-def", "101-103"])
def test_exit_3_on_a_malformed_crop(
    cif_with_unobs_category: Path, bad: str
) -> None:
    result = runner.invoke(
        app,
        ["check", str(cif_with_unobs_category), "--hotspots", "A101", "--crop", bad],
    )
    assert result.exit_code == 3, result.output
    assert "CHAIN:FIRST-LAST" in result.output
    assert "Traceback" not in result.output


def test_exit_3_when_the_crop_holds_no_observed_residues(
    cif_with_unobs_category: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_unobs_category),
            "--hotspots",
            "A101",
            "--crop",
            "A:900-999",
        ],
    )
    assert result.exit_code == 3, result.output
    assert "no observed residues" in result.output
    assert "Traceback" not in result.output


def test_exit_3_when_the_crop_chain_does_not_exist(
    cif_with_unobs_category: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_unobs_category),
            "--hotspots",
            "A101",
            "--crop",
            "Z:101-103",
        ],
    )
    assert result.exit_code == 3, result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# --assembly
# ---------------------------------------------------------------------------


def test_assembly_can_be_named(cif_with_assembly: Path) -> None:
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_assembly),
            "--hotspots",
            "A101,A102,A103",
            "--assembly",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output


def test_exit_3_on_an_unknown_assembly(cif_with_assembly: Path) -> None:
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_assembly),
            "--hotspots",
            "A101",
            "--assembly",
            "99",
        ],
    )
    assert result.exit_code == 3, result.output
    assert "99" in result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# Output artifacts
# ---------------------------------------------------------------------------


def test_json_output_is_a_valid_run_record(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    out = tmp_path / "run.json"
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_unobs_category),
            "--hotspots",
            "A101,A104",
            "--json",
            str(out),
        ],
    )
    assert result.exit_code == 2, result.output
    record = json.loads(out.read_text())
    assert record["verdict"] == "STOP"
    assert record["site"]["hotspot_spec"] == "A101,A104"
    assert record["input"]["filename"] == "with_unobs.cif"


def test_csv_output_has_a_header_and_rows(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    out = tmp_path / "run.csv"
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_unobs_category),
            "--hotspots",
            "A101",
            "--csv",
            str(out),
        ],
    )
    assert result.exit_code == 1, result.output
    lines = out.read_text().splitlines()
    assert lines[0].startswith("target_id,")
    assert len(lines) > 1


def test_quiet_suppresses_the_report_but_keeps_the_exit_code(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    out = tmp_path / "run.json"
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_unobs_category),
            "--hotspots",
            "A104",
            "--quiet",
            "--json",
            str(out),
        ],
    )
    assert result.exit_code == 2
    assert result.output.strip() == ""
    assert json.loads(out.read_text())["verdict"] == "STOP"


def test_quiet_still_reports_usage_errors(cif_with_unobs_category: Path) -> None:
    """Silencing the report must not silence the reason a run never happened."""
    result = runner.invoke(
        app, ["check", str(cif_with_unobs_category), "--hotspots", "405", "--quiet"]
    )
    assert result.exit_code == 3
    assert "A405" in result.output


def test_exit_3_when_an_output_path_is_not_writable(
    cif_with_unobs_category: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "check",
            str(cif_with_unobs_category),
            "--hotspots",
            "A101",
            "--json",
            str(tmp_path / "no" / "such" / "dir" / "run.json"),
        ],
    )
    assert result.exit_code == 3, result.output
    assert "Traceback" not in result.output


def test_help_documents_the_exit_codes() -> None:
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    for code in ("0", "1", "2", "3"):
        assert code in result.output


# ---------------------------------------------------------------------------
# The real entry, by PDB id
# ---------------------------------------------------------------------------


@pytest.fixture
def cache_at_repo(real_6f5j: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI's cache at the already-downloaded 6F5J so the id path is
    exercised without a second download."""
    monkeypatch.setenv("HOTSPOT_PREFLIGHT_CACHE", str(real_6f5j.parent))
    return real_6f5j


@pytest.mark.network
def test_6f5j_unmodelled_hotspots_exit_2(cache_at_repo: Path) -> None:
    result = runner.invoke(app, ["check", "6f5j", "--hotspots", "C405,C408"])
    assert result.exit_code == 2, result.output
    assert "never observed" in result.output
    assert "C405" in result.output and "C408" in result.output


@pytest.mark.network
def test_6f5j_real_binder_epitope_exits_0(cache_at_repo: Path) -> None:
    """C325/C326 is the epitope of a binder that measured KD 604 nM.

    Asserted with --no-patch, which is the three-check contract the README
    documents. The default now exits 1 on this same site; see
    test_6f5j_epitope_is_demoted_to_exit_1_by_the_patch_check.
    """
    result = runner.invoke(
        app, ["check", "6f5j", "--hotspots", "C325,C326", "--no-patch"]
    )
    assert result.exit_code == 0, result.output
    assert "VERDICT: GO" in result.output
    assert "[C325,C326]" in result.output


@pytest.mark.network
def test_6f5j_epitope_keeps_exit_0_with_the_count_note_present(
    cache_at_repo: Path,
) -> None:
    """The patch check reports the unusual count without demoting it.

    Two residues is below the 3-6 RFdiffusion recommends, so the note fires —
    but it is advice about a design tool rather than a measurement of the target,
    and this exact site binds at 604 nM, so it must not qualify the verdict.
    Pinned at exit 0 *with* the note so neither half can regress: dropping the
    note would lose the advice, raising it to WARN would fail an assay-confirmed
    site.
    """
    result = runner.invoke(app, ["check", "6f5j", "--hotspots", "C325,C326"])
    assert result.exit_code == 0, result.output
    assert "VERDICT: GO" in result.output
    # Labelled NOTE, not WARN: visible to the reader, invisible to the verdict.
    assert "NOTE (whole entry):" in result.output
    assert "HOTSPOT_COUNT_UNUSUAL" in result.output
    assert "WARN" not in result.output
    assert "2 of 2 hotspot residues passed every check" in result.output


@pytest.mark.network
def test_pdb_id_is_cached_and_reused(cache_at_repo: Path) -> None:
    """The second run must not need the network at all."""
    before = cache_at_repo.stat().st_mtime_ns
    result = runner.invoke(
        app, ["check", "6F5J", "--hotspots", "C325", "--no-patch"]
    )
    assert result.exit_code == 0, result.output
    assert cache_at_repo.stat().st_mtime_ns == before
