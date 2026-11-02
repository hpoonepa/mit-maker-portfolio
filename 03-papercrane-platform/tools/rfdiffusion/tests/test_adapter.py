"""Unit tests for the RFdiffusion adapter.

These tests exercise `prepare()` and `parse()` without invoking the upstream
RFdiffusion pipeline. Anything that would actually spawn
`/opt/rfdiffusion/scripts/run_inference.py` is tagged `@pytest.mark.integration`
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
    RFdiffusionAdapter,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def design_request(request_payload) -> DesignRequest:
    return DesignRequest.from_json(request_payload)


@pytest.fixture()
def adapter() -> RFdiffusionAdapter:
    return RFdiffusionAdapter()


# ---------------------------- request parsing ---------------------------- #

def test_request_parses_from_json(design_request: DesignRequest):
    assert design_request.target_pdb == "/inputs/target.pdb"
    assert design_request.seeds == [0, 1]
    assert design_request.num_designs == 2
    assert design_request.target_chain == "A"
    assert design_request.hotspots is not None
    assert design_request.hotspots[0].chain == "A"
    assert design_request.hotspots[0].resi == 56
    assert design_request.hotspots[1].resi == 115
    assert design_request.constraints is not None
    assert design_request.constraints.length_range == [70, 110]
    assert design_request.tool_params == {"noise_scale": 1.0}


# ------------------------------- validate ------------------------------- #

def test_validate_accepts_valid_request(adapter, design_request):
    assert adapter.validate(design_request) == []


def test_validate_rejects_empty_seeds(adapter, design_request):
    design_request.seeds = []
    errors = adapter.validate(design_request)
    assert any(e["field"] == "seeds" for e in errors)


def test_validate_rejects_zero_num_designs(adapter, design_request):
    design_request.num_designs = 0
    errors = adapter.validate(design_request)
    assert any(e["field"] == "numDesigns" for e in errors)


def test_validate_rejects_bad_length_range(adapter, design_request):
    design_request.constraints.length_range = [200, 50]
    errors = adapter.validate(design_request)
    assert any(e["field"].endswith("lengthRange") for e in errors)


# -------------------------------- prepare -------------------------------- #

def test_prepare_writes_rfdiffusion_config(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    cfg_path = pathlib.Path(job["cfg"])
    assert cfg_path.exists(), "prepare() must emit rfdiffusion.json"

    cfg = json.loads(cfg_path.read_text())
    assert cfg["target_chain"] == "A"
    assert cfg["hotspots"] == ["A56", "A115"]
    assert cfg["binder_length_range"] == [70, 110]
    assert cfg["num_designs"] == 2
    assert cfg["seeds"] == [0, 1]
    assert cfg["noise_scale"] == 1.0
    # Contig string embeds chain + length range.
    assert cfg["contigs"].startswith("[A")
    assert "70-110" in cfg["contigs"]


def test_prepare_job_carries_runtime_args(adapter, design_request, tmp_path):
    """The `run` step needs contigs/hotspots/noise plucked out of the config."""
    job = adapter.prepare(design_request, tmp_path)
    assert job["contigs"].startswith("[A")
    assert job["hotspots"] == ["A56", "A115"]
    assert job["noise_scale"] == 1.0
    assert job["seeds"] == [0, 1]
    assert job["num_designs"] == 2
    assert job["out_dir"] == "/outputs/designs"


def test_prepare_defaults_length_range_when_missing(adapter, design_request, tmp_path):
    design_request.constraints = None
    job = adapter.prepare(design_request, tmp_path)
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["binder_length_range"] == [60, 150]
    assert "60-150" in cfg["contigs"]


def test_prepare_respects_contigs_override(adapter, design_request, tmp_path):
    design_request.tool_params = {"contigs": "[A1-50/10-20/A60-100/0 60-120]"}
    job = adapter.prepare(design_request, tmp_path)
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["contigs"] == "[A1-50/10-20/A60-100/0 60-120]"


def test_prepare_handles_missing_hotspots(adapter, design_request, tmp_path):
    design_request.hotspots = None
    job = adapter.prepare(design_request, tmp_path)
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["hotspots"] == []


def test_prepare_passes_through_noise_scale(adapter, design_request, tmp_path):
    design_request.tool_params = {"noise_scale": 0.5}
    job = adapter.prepare(design_request, tmp_path)
    assert job["noise_scale"] == 0.5


# --------------------------------- parse --------------------------------- #

def test_parse_reads_fixture_backbones(adapter, tmp_path):
    # Copy the sample outputs into a tmp dir simulating /outputs/designs.
    out_dir = tmp_path / "designs"
    shutil.copytree(FIXTURES / "sample_output", out_dir)

    result = adapter.parse({"out_dir": str(out_dir)})
    assert len(result.designs) == 1

    design = result.designs[0]
    # Backbones-only: there is NO sequence field.
    assert "sequence" not in design
    assert design["seed"] == 0
    assert design["structurePath"].endswith(".pdb")

    metrics = design["metrics"]
    assert metrics["length"] == pytest.approx(85.0)
    assert metrics["plddt_contig_mean"] == pytest.approx(82.3)

    metadata = design["metadata"]
    assert metadata["contigs_used"] == "[A1-150/0 70-110]"
    assert metadata["noise_scale"] == pytest.approx(1.0)
    assert metadata["hotspots"] == ["A56", "A115"]

    # Run metadata advertises composition hook.
    assert result.run_metadata["tool"] == "rfdiffusion"
    assert result.run_metadata["adapterVersion"] == ADAPTER_VERSION
    assert result.run_metadata["composes"] == ["proteinmpnn"]


def test_parse_skips_pdbs_without_sidecar(adapter, tmp_path):
    out_dir = tmp_path / "designs"
    out_dir.mkdir()
    # Only a PDB, no matching .json sidecar — must be silently skipped.
    (out_dir / "orphan.pdb").write_text("ATOM\nEND\n")
    result = adapter.parse({"out_dir": str(out_dir)})
    assert result.designs == []


# ------------------------------ integration ------------------------------ #

@pytest.mark.integration
def test_run_invokes_upstream_rfdiffusion(adapter, design_request, tmp_path):
    """Requires /opt/rfdiffusion/scripts/run_inference.py — skipped outside container."""
    job = adapter.prepare(design_request, tmp_path)
    adapter.run(job)
