# SPDX-License-Identifier: MIT
"""Tests for the DWV retrospective scripts.

Both modules are loaded from their paths rather than imported, because
``scripts/`` is deliberately not a package: it holds entry points, not library
code, and making it importable would invite the rest of the codebase to depend
on it.

The structural tests are the point of this file. A preflight filter is only
useful if it is *selective*, so the test that matters most is not that the
failed hotspots are rejected — a filter that rejects everything does that — but
that residues 325 and 326, the epitope of the one design that actually bound,
survive every check.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS / "dwv_retrospective.py"
DESIGNS_CSV = REPO_ROOT / "data" / "designs_VALIDATED_full_metrics.csv"


def _load_script(name: str) -> ModuleType:
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - path is fixed
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before execution, not after: `dataclasses` resolves a class's
    # own module through sys.modules while processing it, and on Python 3.10
    # raises AttributeError if it is not there yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dwv = _load_script("dwv_retrospective")
report = _load_script("dwv_retrospective_report")

from hotspot_preflight.findings import Severity  # noqa: E402
from hotspot_preflight.residue import ResidueKey  # noqa: E402
from hotspot_preflight.structure import load_target  # noqa: E402

CHAIN = dwv.TARGET_CHAIN
ARM1_CROP = dwv.ARM1_CROP
FULL_DOMAIN_CROP = (CHAIN, 260, 416)


# ---------------------------------------------------------------------------
# Pure parsing and loading — no structure needed
# ---------------------------------------------------------------------------


def test_the_report_module_does_not_import_the_measurement_module() -> None:
    """The split's contract: the dependency runs one way only.

    If the narrative could import the measurement, it could recompute a number
    instead of reporting the one that was measured. Checked on the source text
    because a successful import here would not prove the absence of one.
    """
    source = (SCRIPTS / "dwv_retrospective_report.py").read_text(encoding="utf-8")
    runtime = [
        line
        for line in source.splitlines()
        if "dwv_retrospective" in line and line.lstrip().startswith(("import", "from"))
    ]
    # The only mention is the TYPE_CHECKING block, which never runs.
    assert len(runtime) == 1
    assert source.index("TYPE_CHECKING:") < source.index(runtime[0])


def test_parses_the_full_domain_range_and_keeps_the_full_marker() -> None:
    crop = dwv.parse_crop_range("260-416 (full)")
    assert (crop.chain, crop.first, crop.last) == (CHAIN, 260, 416)
    assert crop.is_full is True
    assert crop.as_range == (CHAIN, 260, 416)
    assert str(crop) == "C260-416"


@pytest.mark.parametrize("raw", ["300-398", "310-398", "265-355"])
def test_parses_a_bare_truncated_range(raw: str) -> None:
    crop = dwv.parse_crop_range(raw)
    first, last = (int(part) for part in raw.split("-"))
    assert (crop.first, crop.last) == (first, last)
    assert crop.is_full is False


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "full", "260", "260-", "-416", "a-b", "398-300", "260..416", "260-416)"],
)
def test_rejects_malformed_crop_ranges(raw: str) -> None:
    """A design whose crop cannot be read must not default to full-domain.

    Defaulting would move a row of the confusion matrix on a parse failure.
    """
    with pytest.raises(dwv.CropRangeError):
        dwv.parse_crop_range(raw)


def test_parses_slash_delimited_contacts_sorted_and_deduplicated() -> None:
    assert dwv.parse_epitope_residues("294/277/278/277") == (
        ResidueKey(CHAIN, 277),
        ResidueKey(CHAIN, 278),
        ResidueKey(CHAIN, 294),
    )
    assert dwv.parse_epitope_residues("") == ()
    assert dwv.parse_epitope_residues("325/326/") == (
        ResidueKey(CHAIN, 325),
        ResidueKey(CHAIN, 326),
    )


def test_rejects_a_non_numeric_contact_rather_than_dropping_it() -> None:
    with pytest.raises(ValueError, match="non-numeric"):
        dwv.parse_epitope_residues("325/Tyr326")


def test_loads_26_designs_split_7_crop_built_and_19_full_domain() -> None:
    designs = dwv.load_designs(DESIGNS_CSV)
    assert len(designs) == 26
    crop_built = [d for d in designs if d.is_crop_built]
    full_domain = [d for d in designs if not d.is_crop_built]
    assert len(crop_built) == 7
    assert len(full_domain) == 19
    # 6 boltzprot + 1 boltzprot_rd, which is the perfect tool/crop correlation
    # the generated document is required to confess.
    assert sorted(d.source for d in crop_built) == ["boltzprot"] * 6 + [
        "boltzprot_rd"
    ]
    assert {str(d.crop) for d in crop_built} == {
        "C265-355",
        "C300-398",
        "C310-398",
    }
    assert all(d.crop.is_full for d in full_domain)


def test_the_confirmed_binder_row_carries_its_known_epitope() -> None:
    designs = {d.design_id: d for d in dwv.load_designs(DESIGNS_CSV)}
    binder = designs[dwv.BINDER_ID]
    assert binder.contacts == tuple(
        ResidueKey(CHAIN, n) for n in dwv.BINDER_EPITOPE
    )
    assert not binder.is_crop_built


def test_confusion_matrix_counts_each_outcome_once() -> None:
    matrix = dwv.ConfusionMatrix(tp=5, fp=0, fn=2, tn=19)
    assert (matrix.tp, matrix.fp, matrix.fn, matrix.tn) == (5, 0, 2, 19)
    assert matrix.n == 26


def test_confusion_matrix_exposes_no_derived_summary_number() -> None:
    """Deliberate: with 7 positives from one tool, a ratio would be over-read.

    Asserted rather than merely documented, because the easiest way for this
    retrospective to start overclaiming is for somebody to add a convenient
    ``.f1`` and then quote it.
    """
    matrix = dwv.ConfusionMatrix(tp=5, fp=0, fn=2, tn=19)
    for derived in ("precision", "recall", "f1", "accuracy", "auc"):
        assert not hasattr(matrix, derived), derived


# ---------------------------------------------------------------------------
# The structural result — needs 6F5J
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def arm1_rows(real_6f5j: Path) -> dict[int, Any]:
    """Arm 1 measured once; the assembly expansion is the expensive part."""
    target = load_target(real_6f5j)
    keys = {ResidueKey(CHAIN, num) for num, _ in dwv.ARM1_RESIDUES}
    burial = dwv.run_burial(target, {ARM1_CROP: keys})
    rows = dwv.build_arm1(target, burial, crop=ARM1_CROP)
    return {row.key.auth_seq_id: row for row in rows}


@pytest.mark.network
@pytest.mark.parametrize("num", [405, 408])
def test_original_hotspots_are_killed_as_unmodelled(num: int, real_6f5j: Path) -> None:
    """The campaign's own hotspots. Both sit in the unmodelled 399-416 tail."""
    target = load_target(real_6f5j)
    findings = dwv.check_resolved(target, [ResidueKey(CHAIN, num)])
    kills = [f for f in findings if f.severity is Severity.KILL]
    assert [f.code for f in kills] == ["UNMODELLED"]
    assert kills[0].key == ResidueKey(CHAIN, num)


@pytest.mark.network
@pytest.mark.parametrize("num", [325, 326])
def test_the_confirmed_binders_epitope_is_not_killed_by_any_check(
    num: int, arm1_rows: dict[int, Any]
) -> None:
    """The most important test in this file.

    A filter that rejects every site is worthless. 325 and 326 are the epitope
    of ``l79_s469532_mpnn9``, the one design of 35 that bound at ~604 nM, so a
    KILL here from any check — in any of the three structural contexts — would
    mean the tool would have thrown away the only real result.
    """
    row = arm1_rows[num]
    assert row.kill_codes == ()
    assert row.verdict == "GO"
    assert "RESOLVED" in row.resolved_codes
    assert "EXPOSED" in row.burial_codes
    assert row.rel_assembly is not None and row.rel_assembly > dwv.BURIED_RELATIVE_SASA


@pytest.mark.network
def test_384_is_a_crop_artifact_under_the_truncated_crop(real_6f5j: Path) -> None:
    """The residue the crop-built designs contacted, in both contexts.

    Under 310-398 the freshly cut face makes it materially more exposed than it
    is on the biological assembly; under the full domain there is no cut and
    nothing to flag. Same residue, same code path, opposite verdicts.
    """
    target = load_target(real_6f5j)
    key = ResidueKey(CHAIN, 384)

    truncated = dwv.check_burial(target, [key], crop_range=ARM1_CROP)
    codes = {f.code for f in truncated}
    assert "CROP_ARTIFACT" in codes

    artifact = next(f for f in truncated if f.code == "CROP_ARTIFACT")
    rel_crop = artifact.evidence["relative_sasa_crop"]
    rel_assembly = artifact.evidence["relative_sasa_assembly"]
    # Direction matters: the crop must be the *more* exposed context.
    assert rel_crop > rel_assembly
    assert rel_crop - rel_assembly > dwv.CROP_ARTIFACT_DELTA

    full = dwv.check_burial(target, [key], crop_range=FULL_DOMAIN_CROP)
    assert "CROP_ARTIFACT" not in {f.code for f in full}


@pytest.mark.network
def test_277_is_less_exposed_on_the_assembly_than_on_the_isolated_chain(
    arm1_rows: dict[int, Any],
) -> None:
    """Partner occlusion, asserted on sign rather than on a verdict.

    The capsid neighbour really does cover part of this residue, and the
    assembly value really is the lower one. Whether the drop clears the
    ``OCCLUDED_BY_PARTNER`` threshold is a separate question the generated
    document discusses; the measurement's direction is what is asserted here.
    """
    row = arm1_rows[277]
    assert row.rel_assembly < row.rel_chain
    assert row.abs_assembly < row.abs_chain


@pytest.mark.network
def test_the_three_crop_sensitive_residues_all_open_up_on_the_crop(
    arm1_rows: dict[int, Any],
) -> None:
    """359, 384 and 395 move in the same direction, by more than the threshold."""
    for num in (359, 384, 395):
        row = arm1_rows[num]
        assert "CROP_ARTIFACT" in row.burial_codes, num
        assert row.rel_crop - row.rel_assembly > dwv.CROP_ARTIFACT_DELTA, num
        assert row.abs_crop > row.abs_assembly, num


@pytest.mark.network
def test_arm2_matrix_separates_crop_built_designs_without_false_positives(
    real_6f5j: Path,
) -> None:
    """Arm 2 end to end: no full-domain design is wrongly flagged.

    A false positive here would be the damaging error — it would mean the check
    condemns intact-domain sites — so it is asserted exactly, while recall is
    asserted only as a floor because the misses are input-driven and documented.
    """
    target = load_target(real_6f5j)
    designs = dwv.load_designs(DESIGNS_CSV)
    requests: dict[tuple[str, int, int], set[ResidueKey]] = {}
    for design in designs:
        if design.contacts:
            requests.setdefault(design.crop.as_range, set()).update(design.contacts)
    burial = dwv.run_burial(target, requests)
    matrix = dwv.confusion(dwv.build_arm2(designs, burial))

    assert matrix.n == 26
    assert matrix.fp == 0
    assert matrix.tn == 19
    assert matrix.tp >= 5
    assert matrix.tp + matrix.fn == 7


# ---------------------------------------------------------------------------
# The generated document
# ---------------------------------------------------------------------------


def _run_script(out: Path, structure: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONHASHSEED"] = "0"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--out",
            str(out),
            "--structure",
            str(structure),
            "--designs",
            str(DESIGNS_CSV),
        ],
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.fixture(scope="session")
def generated_twice(
    tmp_path_factory: pytest.TempPathFactory, real_6f5j: Path
) -> tuple[Path, Path]:
    """Run the real entry point twice, into two separate files."""
    directory = tmp_path_factory.mktemp("dwv")
    first, second = directory / "first.md", directory / "second.md"
    _run_script(first, real_6f5j)
    _run_script(second, real_6f5j)
    return first, second


@pytest.mark.network
def test_running_the_script_twice_produces_identical_bytes(
    generated_twice: tuple[Path, Path],
) -> None:
    """Deterministic output is what makes the document committable and diffable."""
    first, second = generated_twice
    assert first.read_bytes() == second.read_bytes()



@pytest.mark.network
def test_the_threshold_was_not_tuned_to_make_c277_fire(
    arm1_rows: dict[int, Any],
) -> None:
    """A regression guard on the ruling, not on the measurement.

    C277's relative drop sits just below the default. If someone later lowers
    ``PARTNER_OCCLUSION_DELTA`` far enough to catch it, this fails and they have
    to justify moving a documented threshold rather than doing it quietly.
    """
    row = arm1_rows[dwv.OCCLUDED_CANDIDATE]
    drop = row.rel_chain - row.rel_assembly
    assert drop < dwv.PARTNER_OCCLUSION_DELTA
    assert "OCCLUDED_BY_PARTNER" not in row.burial_codes
