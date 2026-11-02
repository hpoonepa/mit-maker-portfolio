"""Unit tests for the BindCraft adapter.

These tests exercise `prepare()` and `parse()` without invoking the upstream
BindCraft pipeline. Anything that would actually spawn `/opt/bindcraft/bindcraft.py`
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
    BindCraftAdapter,
    DesignRequest,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def design_request(request_payload) -> DesignRequest:
    return DesignRequest.model_validate(request_payload)


@pytest.fixture()
def adapter() -> BindCraftAdapter:
    return BindCraftAdapter()


def test_request_parses_from_json(design_request: DesignRequest):
    assert design_request.target_pdb == "/inputs/target.pdb"
    assert design_request.seeds == [0, 1]
    assert design_request.num_designs == 2
    assert design_request.target_chain == "A"
    assert design_request.hotspots is not None
    assert design_request.hotspots[0].chain == "A"
    assert design_request.hotspots[0].resi == 42
    assert design_request.constraints is not None
    assert design_request.constraints.length_range == (70, 110)
    assert design_request.tool_params == {"protocol": "default"}


def test_validate_accepts_valid_request(adapter, design_request):
    assert adapter.validate(design_request) == []


def test_validate_rejects_empty_seeds(adapter, design_request):
    design_request.seeds = []
    errors = adapter.validate(design_request)
    assert any(e.field == "seeds" for e in errors)


def test_validate_rejects_bad_length_range(adapter, design_request):
    design_request.constraints.length_range = [200, 50]
    errors = adapter.validate(design_request)
    assert any(e.field.endswith("lengthRange") for e in errors)


def test_prepare_writes_bindcraft_config(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    cfg_path = pathlib.Path(job["cfg"])
    assert cfg_path.exists(), "prepare() must emit bindcraft.json"

    cfg = json.loads(cfg_path.read_text())
    assert cfg["target_chain"] == "A"
    assert cfg["hotspots"] == ["A42", "A47"]
    assert cfg["binder_length_range"] == [70, 110]
    assert cfg["num_designs"] == 2
    assert cfg["seeds"] == [0, 1]
    # tool_params passthrough
    assert cfg["protocol"] == "default"


def test_prepare_defaults_length_range_when_missing(adapter, design_request, tmp_path):
    design_request.constraints = None
    job = adapter.prepare(design_request, tmp_path)
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["binder_length_range"] == [60, 150]


def test_parse_reads_fixture_designs(adapter, tmp_path):
    # Copy the sample outputs into a tmp dir simulating /outputs/designs.
    out_dir = tmp_path / "designs"
    shutil.copytree(FIXTURES / "sample_output", out_dir)

    result = adapter.parse({"out_dir": str(out_dir)})
    assert len(result.designs) == 1

    design = result.designs[0]
    assert design.sequence.startswith("MKTAY")
    assert design.seed == 0
    metrics = design.metrics
    assert metrics["iptm"] == pytest.approx(0.82)
    assert metrics["plddt"] == pytest.approx(88.4)
    assert metrics["i_pae"] == pytest.approx(7.1)
    assert metrics["hotspot_contact"] == pytest.approx(0.73)

    assert result.run_metadata.tool == "bindcraft"
    assert result.run_metadata.adapter_version == ADAPTER_VERSION


@pytest.mark.integration
def test_run_invokes_upstream_bindcraft(adapter, design_request, tmp_path):
    """Requires /opt/bindcraft/bindcraft.py — skipped outside the container."""
    job = adapter.prepare(design_request, tmp_path)
    adapter.run(job)
