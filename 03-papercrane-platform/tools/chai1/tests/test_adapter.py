"""Unit tests for the Chai-1 adapter.

These tests exercise `prepare()` and `parse()` without invoking the upstream
`chai_lab` package. Anything that would actually spawn `python -m chai_lab.main`
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
    Chai1Adapter,
    Chai1Params,
    StructureRequest,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def structure_request(request_payload) -> StructureRequest:
    return StructureRequest.from_json(request_payload)


@pytest.fixture()
def adapter() -> Chai1Adapter:
    return Chai1Adapter()


def test_request_parses_from_json(structure_request: StructureRequest):
    assert len(structure_request.chains) == 2
    assert structure_request.chains[0].id == "A"
    assert structure_request.chains[0].sequence.startswith("MKTAY")
    assert structure_request.chains[1].id == "B"
    assert structure_request.seeds == [42]
    assert structure_request.binder_chain_id == "B"
    assert structure_request.params is not None
    assert structure_request.params.num_trunk_recycles == 3
    assert structure_request.params.num_diffn_timesteps == 200


def test_validate_accepts_valid_request(adapter, structure_request):
    assert adapter.validate(structure_request) == []


def test_validate_rejects_empty_chains(adapter, structure_request):
    structure_request.chains = []
    errors = adapter.validate(structure_request)
    assert any(e["field"] == "chains" for e in errors)


def test_validate_rejects_duplicate_chain_ids(adapter, structure_request):
    structure_request.chains[1].id = "A"
    errors = adapter.validate(structure_request)
    assert any("unique" in e["message"] for e in errors)


def test_validate_rejects_empty_seeds(adapter, structure_request):
    structure_request.seeds = []
    errors = adapter.validate(structure_request)
    assert any(e["field"] == "seeds" for e in errors)


def test_validate_rejects_unknown_binder_chain(adapter, structure_request):
    structure_request.binder_chain_id = "Z"
    errors = adapter.validate(structure_request)
    assert any(e["field"] == "binderChainId" for e in errors)


def test_validate_rejects_out_of_range_recycles(adapter, structure_request):
    structure_request.params = Chai1Params(num_trunk_recycles=50)
    errors = adapter.validate(structure_request)
    assert any(e["field"].endswith("num_trunk_recycles") for e in errors)


def test_validate_rejects_out_of_range_timesteps(adapter, structure_request):
    structure_request.params = Chai1Params(num_diffn_timesteps=5)
    errors = adapter.validate(structure_request)
    assert any(e["field"].endswith("num_diffn_timesteps") for e in errors)


def test_prepare_writes_fasta_and_config(adapter, structure_request, tmp_path):
    job = adapter.prepare(structure_request, tmp_path)
    fasta_path = pathlib.Path(job["fasta"])
    cfg_path = pathlib.Path(job["cfg"])
    assert fasta_path.exists()
    assert cfg_path.exists()

    fasta = fasta_path.read_text()
    # Chai-1 header convention + both chains present.
    assert ">protein|name=A" in fasta
    assert ">protein|name=B" in fasta
    assert "MKTAY" in fasta

    cfg = json.loads(cfg_path.read_text())
    assert cfg["num_trunk_recycles"] == 3
    assert cfg["num_diffn_timesteps"] == 200
    assert cfg["seeds"] == [42]
    assert cfg["binder_chain_id"] == "B"


def test_prepare_defaults_params_when_missing(adapter, structure_request, tmp_path):
    structure_request.params = None
    job = adapter.prepare(structure_request, tmp_path)
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["num_trunk_recycles"] == 3
    assert cfg["num_diffn_timesteps"] == 200


def test_parse_reads_chai1_layout(adapter, tmp_path):
    """Simulate the on-disk layout Chai-1 produces: seed_<N>/pred.model_idx_<M>.cif + metrics JSON."""
    out_dir = tmp_path / "predictions"
    seed_dir = out_dir / "seed_42"
    seed_dir.mkdir(parents=True)

    # Rename the canonical fixtures to match Chai-1's on-disk convention.
    shutil.copy(
        FIXTURES / "sample_output" / "prediction_0001.cif",
        seed_dir / "pred.model_idx_0.cif",
    )
    shutil.copy(
        FIXTURES / "sample_output" / "prediction_0001.json",
        seed_dir / "pred.model_idx_0.json",
    )

    result = adapter.parse({"out_dir": str(out_dir), "binder_chain_id": "B"})
    assert len(result.predictions) == 1

    pred = result.predictions[0]
    assert pred["seed"] == 42
    assert pred["model_idx"] == 0
    assert pred["structurePath"].endswith("pred.model_idx_0.cif")

    metrics = pred["metrics"]
    assert metrics["plddt_mean"] == pytest.approx(86.7)
    assert metrics["plddt_binder"] == pytest.approx(82.4)
    assert metrics["ptm"] == pytest.approx(0.78)
    assert metrics["iptm"] == pytest.approx(0.71)
    # aggregate_score = 0.6*iptm + 0.2*ptm + 0.2*(plddt_mean/100)
    expected_agg = 0.6 * 0.71 + 0.2 * 0.78 + 0.2 * (86.7 / 100.0)
    assert metrics["aggregate_score"] == pytest.approx(expected_agg)

    assert result.run_metadata["tool"] == "chai1"
    assert result.run_metadata["adapterVersion"] == ADAPTER_VERSION
    assert result.run_metadata["licenseAcknowledged"] is True


def test_parse_skips_cif_without_metrics(adapter, tmp_path):
    out_dir = tmp_path / "predictions"
    seed_dir = out_dir / "seed_7"
    seed_dir.mkdir(parents=True)
    # CIF with no paired JSON: must be ignored, not crash.
    (seed_dir / "pred.model_idx_0.cif").write_text("")
    result = adapter.parse({"out_dir": str(out_dir)})
    assert result.predictions == []


def test_parse_ignores_non_seed_directories(adapter, tmp_path):
    out_dir = tmp_path / "predictions"
    (out_dir / "scratch").mkdir(parents=True)
    (out_dir / "scratch" / "pred.model_idx_0.cif").write_text("")
    result = adapter.parse({"out_dir": str(out_dir)})
    assert result.predictions == []


@pytest.mark.integration
def test_run_invokes_upstream_chai_lab(adapter, structure_request, tmp_path):
    """Requires chai_lab + GPU + license ack — skipped outside the container."""
    job = adapter.prepare(structure_request, tmp_path)
    adapter.run(job)
