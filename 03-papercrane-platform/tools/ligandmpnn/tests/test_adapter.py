"""Unit tests for the LigandMPNN adapter.

These tests exercise `prepare()` and `parse()` without invoking the upstream
LigandMPNN CLI. Anything that would actually spawn `/opt/ligandmpnn/run.py`
is tagged `@pytest.mark.integration` and skipped by default.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

TOOL_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = TOOL_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(TOOL_ROOT))

from adapter import (  # noqa: E402
    ADAPTER_VERSION,
    DesignRequest,
    LigandMPNNAdapter,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def design_request(request_payload) -> DesignRequest:
    return DesignRequest.from_json(request_payload)


@pytest.fixture()
def adapter() -> LigandMPNNAdapter:
    return LigandMPNNAdapter()


def test_request_parses_from_json(design_request: DesignRequest):
    assert design_request.backbones == [
        "s3://papercrane-test/backbones/backbone_0001.pdb"
    ]
    assert design_request.seeds == [0, 1]
    assert design_request.params.temperature == pytest.approx(0.1)
    assert design_request.params.omit_aas == "CX"
    assert design_request.params.num_seq_per_target == 1
    assert design_request.params.ligand_context_radius == pytest.approx(8.0)
    assert design_request.params.fixed_positions == {"A": [1, 2]}
    assert design_request.ligand_atoms is not None
    assert len(design_request.ligand_atoms) == 2
    assert design_request.ligand_atoms[0].element == "C"


def test_validate_accepts_valid_request(adapter, design_request):
    assert adapter.validate(design_request) == []


def test_validate_rejects_empty_seeds(adapter, design_request):
    design_request.seeds = []
    errors = adapter.validate(design_request)
    assert any(e["field"] == "seeds" for e in errors)


def test_validate_rejects_empty_backbones(adapter, design_request):
    design_request.backbones = []
    errors = adapter.validate(design_request)
    assert any(e["field"] == "backbones" for e in errors)


def test_validate_rejects_bad_temperature(adapter, design_request):
    design_request.params.temperature = 0.0
    errors = adapter.validate(design_request)
    assert any(e["field"].endswith("temperature") for e in errors)


def test_validate_rejects_bad_num_seq_per_target(adapter, design_request):
    design_request.params.num_seq_per_target = 0
    errors = adapter.validate(design_request)
    assert any(e["field"].endswith("num_seq_per_target") for e in errors)


def test_validate_rejects_bad_ligand_context_radius(adapter, design_request):
    design_request.params.ligand_context_radius = 0.5
    errors = adapter.validate(design_request)
    assert any(e["field"].endswith("ligand_context_radius") for e in errors)


def test_validate_rejects_mutually_exclusive_ligand_inputs(adapter, design_request):
    design_request.ligand_sdf = "s3://papercrane-test/ligands/ligand.sdf"
    errors = adapter.validate(design_request)
    assert any(e["field"] == "ligand" for e in errors)


def test_prepare_builds_job_handle(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    assert pathlib.Path(job["pdb_dir"]).exists()
    assert job["num_seq_per_target"] == 1
    assert job["sampling_temp"] == pytest.approx(0.1)
    assert job["omit_aas"] == "CX"
    assert job["ligand_context_radius"] == pytest.approx(8.0)
    assert job["seeds"] == [0, 1]
    assert job["out_dir"] == "/outputs/designs"


def test_prepare_materialises_ligand_atoms_as_pdb(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    ligand_pdb = pathlib.Path(job["ligand_pdb"])
    assert ligand_pdb.exists()
    text = ligand_pdb.read_text()
    assert "HETATM" in text
    assert " C " in text or "C1" in text
    assert "END" in text


def test_prepare_uses_staged_sdf_path_when_requested(adapter, design_request, tmp_path):
    design_request.ligand_atoms = None
    design_request.ligand_sdf = "s3://papercrane-test/ligands/ligand.sdf"
    job = adapter.prepare(design_request, tmp_path)
    assert job["ligand_pdb"] == "/inputs/ligands/ligand.sdf"


def test_prepare_writes_fixed_positions_jsonl(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    fp_path = pathlib.Path(job["fixed_positions_jsonl"])
    assert fp_path.exists()
    assert json.loads(fp_path.read_text()) == {"A": [1, 2]}


def test_prepare_omits_fixed_positions_when_missing(adapter, design_request, tmp_path):
    design_request.params.fixed_positions = None
    job = adapter.prepare(design_request, tmp_path)
    assert "fixed_positions_jsonl" not in job


def test_parse_reads_fixture_designs(adapter, tmp_path):
    # Copy the sample outputs into a tmp dir simulating /outputs/designs.
    out_dir = tmp_path / "designs"
    shutil.copytree(FIXTURES / "sample_output", out_dir)

    result = adapter.parse({"out_dir": str(out_dir)})
    assert len(result.designs) == 1

    design = result.designs[0]
    assert design["sequence"].startswith("MKTAY")
    assert design["sequence"] == "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"
    assert design["seed"] == 0
    assert design["structurePath"].endswith("backbone_0001.pdb")
    assert design["ligandPath"].endswith("ligand.sdf")

    metrics = design["metrics"]
    assert metrics["score"] == pytest.approx(1.102)
    assert metrics["confidence_mean"] == pytest.approx(0.89)
    assert metrics["ligand_context_residues"] == pytest.approx(12)

    assert result.run_metadata["tool"] == "ligandmpnn"
    assert result.run_metadata["adapterVersion"] == ADAPTER_VERSION


@pytest.mark.integration
def test_run_invokes_upstream_ligandmpnn(adapter, design_request, tmp_path):
    """Requires /opt/ligandmpnn/run.py — skipped outside the container."""
    job = adapter.prepare(design_request, tmp_path)
    adapter.run(job)
