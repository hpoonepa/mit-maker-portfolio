"""Unit tests for the ProteinMPNN adapter.

These tests exercise `prepare()` and `parse()` without invoking the upstream
ProteinMPNN CLI. Anything that would actually spawn
`/opt/proteinmpnn/protein_mpnn_run.py` is tagged `@pytest.mark.integration`
and skipped by default.
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
    ProteinMPNNAdapter,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def design_request(request_payload) -> DesignRequest:
    return DesignRequest.from_json(request_payload)


@pytest.fixture()
def adapter() -> ProteinMPNNAdapter:
    return ProteinMPNNAdapter()


def test_request_parses_from_json(design_request: DesignRequest):
    assert design_request.backbones == [
        "s3://papercrane-test/backbones/backbone_0001.pdb"
    ]
    assert design_request.seeds == [0, 1]
    assert design_request.params.temperature == pytest.approx(0.1)
    assert design_request.params.omit_aas == "CX"
    assert design_request.params.num_seq_per_target == 1
    assert design_request.params.fixed_positions == {"A": [1, 2]}


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


def test_prepare_builds_job_handle(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    assert pathlib.Path(job["pdb_dir"]).exists()
    assert job["num_seq_per_target"] == 1
    assert job["sampling_temp"] == pytest.approx(0.1)
    assert job["omit_aas"] == "CX"
    assert job["seeds"] == [0, 1]
    assert job["out_dir"] == "/outputs/designs"


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

    metrics = design["metrics"]
    assert metrics["score"] == pytest.approx(1.234)
    assert metrics["confidence_mean"] == pytest.approx(0.87)

    assert result.run_metadata["tool"] == "proteinmpnn"
    assert result.run_metadata["adapterVersion"] == ADAPTER_VERSION


@pytest.mark.integration
def test_run_invokes_upstream_proteinmpnn(adapter, design_request, tmp_path):
    """Requires /opt/proteinmpnn/protein_mpnn_run.py — skipped outside the container."""
    job = adapter.prepare(design_request, tmp_path)
    adapter.run(job)
