"""Unit tests for the BoltzGen adapter.

These tests exercise `prepare()` and `parse()` without invoking the upstream
BoltzGen pipeline. Anything that would actually spawn
`/opt/boltzgen/scripts/design.py` is tagged `@pytest.mark.integration` and
skipped by default.
"""
from __future__ import annotations

import dataclasses
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
    BoltzGenAdapter,
    DesignRequest,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def design_request(request_payload) -> DesignRequest:
    return DesignRequest.from_json(request_payload)


@pytest.fixture()
def adapter() -> BoltzGenAdapter:
    return BoltzGenAdapter()


def test_request_parses_from_json(design_request: DesignRequest):
    assert design_request.target_pdb == "/inputs/target.pdb"
    assert design_request.seeds == [0, 1]
    assert design_request.num_designs == 2
    assert design_request.target_chain == "A"
    assert design_request.hotspots is not None
    assert design_request.hotspots[0].chain == "A"
    assert design_request.hotspots[0].resi == 42
    assert design_request.constraints is not None
    assert design_request.constraints.length_range == [70, 110]
    assert design_request.tool_params == {
        "diffusion_steps": 200,
        "temperature": 0.1,
    }
    # Ligand is a first-class field — parsed off the top-level request.
    assert design_request.ligand == "/inputs/ligand.sdf"


def test_validate_accepts_valid_request(adapter, design_request):
    assert adapter.validate(design_request) == []


def test_validate_rejects_empty_seeds(adapter, design_request):
    design_request.seeds = []
    errors = adapter.validate(design_request)
    assert any(e["field"] == "seeds" for e in errors)


def test_validate_rejects_bad_length_range(adapter, design_request):
    design_request.constraints.length_range = [200, 50]
    errors = adapter.validate(design_request)
    assert any(e["field"].endswith("lengthRange") for e in errors)


def test_validate_rejects_bad_diffusion_steps(adapter, design_request):
    design_request.tool_params = {"diffusion_steps": 5}
    errors = adapter.validate(design_request)
    assert any(e["field"] == "toolParams.diffusion_steps" for e in errors)


def test_validate_rejects_bad_temperature(adapter, design_request):
    design_request.tool_params = {"temperature": 5.0}
    errors = adapter.validate(design_request)
    assert any(e["field"] == "toolParams.temperature" for e in errors)


def test_prepare_writes_boltzgen_yaml(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    cfg_path = pathlib.Path(job["cfg"])
    assert cfg_path.exists(), "prepare() must emit config.yaml"
    assert cfg_path.name == "config.yaml"

    cfg = cfg_path.read_text()
    assert "target_pdb: /inputs/target.pdb" in cfg
    assert "target_chain: A" in cfg
    assert "- A42" in cfg
    assert "- A47" in cfg
    assert "length_range: [70, 110]" in cfg
    assert "num_designs: 2" in cfg
    assert "diffusion_steps: 200" in cfg
    assert "temperature: 0.1" in cfg
    # Ligand line emitted when supplied.
    assert "ligand: /inputs/ligand.sdf" in cfg
    # Seeds passed through for the per-seed run loop.
    assert job["seeds"] == [0, 1]
    assert job["ligand"] == "/inputs/ligand.sdf"


def test_prepare_defaults_length_range_when_missing(adapter, design_request, tmp_path):
    design_request.constraints = None
    job = adapter.prepare(design_request, tmp_path)
    cfg = pathlib.Path(job["cfg"]).read_text()
    assert "length_range: [60, 150]" in cfg


def test_prepare_defaults_diffusion_and_temperature(adapter, design_request, tmp_path):
    design_request.tool_params = {}
    job = adapter.prepare(design_request, tmp_path)
    cfg = pathlib.Path(job["cfg"]).read_text()
    assert "diffusion_steps: 200" in cfg
    assert "temperature: 0.1" in cfg


def test_prepare_omits_ligand_line_when_absent(adapter, design_request, tmp_path):
    design_request.ligand = None
    design_request.tool_params = {}
    job = adapter.prepare(design_request, tmp_path)
    cfg = pathlib.Path(job["cfg"]).read_text()
    assert "ligand:" not in cfg
    assert job["ligand"] is None


def test_prepare_reads_ligand_from_tool_params(adapter, design_request, tmp_path):
    # Top-level `ligand` is preferred, but toolParams.ligand is a valid
    # escape hatch when the caller hasn't lifted it to a first-class field.
    design_request.ligand = None
    design_request.tool_params = {"ligand": "/inputs/ligand.pdb"}
    job = adapter.prepare(design_request, tmp_path)
    cfg = pathlib.Path(job["cfg"]).read_text()
    assert "ligand: /inputs/ligand.pdb" in cfg
    assert job["ligand"] == "/inputs/ligand.pdb"


def test_prepare_uses_default_chain_when_missing(adapter, design_request, tmp_path):
    design_request.target_chain = None
    job = adapter.prepare(design_request, tmp_path)
    cfg = pathlib.Path(job["cfg"]).read_text()
    assert "target_chain: A" in cfg


def test_parse_reads_fixture_designs(adapter, tmp_path):
    # Copy the sample outputs into a tmp dir simulating /outputs/designs.
    out_dir = tmp_path / "designs"
    shutil.copytree(FIXTURES / "sample_output", out_dir)

    result = adapter.parse({"out_dir": str(out_dir)})
    assert len(result.designs) == 1

    design = result.designs[0]
    assert design["sequence"].startswith("MKTAY")
    assert design["seed"] == 0
    metrics = design["metrics"]
    assert metrics["plddt_mean"] == pytest.approx(87.3)
    assert metrics["clash_score"] == pytest.approx(0.05)
    assert metrics["sidechain_confidence"] == pytest.approx(0.81)
    assert metrics["hotspot_contact"] == pytest.approx(0.74)
    # Ligand_rmsd is only present when the fixture declared a ligand.
    assert metrics["ligand_rmsd"] == pytest.approx(1.42)

    assert result.run_metadata["tool"] == "boltzgen"
    assert result.run_metadata["adapterVersion"] == ADAPTER_VERSION


def test_parse_omits_ligand_rmsd_when_absent(adapter, tmp_path):
    # Strip ligand_rmsd from the fixture metadata to simulate a ligand-free
    # run — the adapter must not synthesize a metric value.
    out_dir = tmp_path / "designs"
    shutil.copytree(FIXTURES / "sample_output", out_dir)
    meta_path = out_dir / "design_0001.json"
    meta = json.loads(meta_path.read_text())
    meta.pop("ligand_rmsd", None)
    meta_path.write_text(json.dumps(meta))

    result = adapter.parse({"out_dir": str(out_dir)})
    assert "ligand_rmsd" not in result.designs[0]["metrics"]


def test_design_result_to_json_roundtrip(adapter, tmp_path):
    out_dir = tmp_path / "designs"
    shutil.copytree(FIXTURES / "sample_output", out_dir)
    result = adapter.parse({"out_dir": str(out_dir)})
    blob = result.to_json()
    assert "designs" in blob and "runMetadata" in blob
    assert blob["runMetadata"]["tool"] == "boltzgen"


@pytest.mark.integration
def test_run_invokes_upstream_boltzgen(adapter, design_request, tmp_path):
    """Requires /opt/boltzgen/scripts/design.py — skipped outside the container."""
    job = adapter.prepare(design_request, tmp_path)
    adapter.run(job)


# Keep dataclass import reachable for static-analysis tooling.
_ = dataclasses
