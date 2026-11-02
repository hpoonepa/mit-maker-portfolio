"""Unit tests for the Chroma adapter.

These tests exercise `validate()`, `prepare()`, and `parse()` without invoking
the upstream Chroma pipeline. Anything that would actually spawn
`python -m chroma.cli` is tagged `@pytest.mark.integration` and skipped by
default.
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
    ChromaAdapter,
    DesignRequest,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def design_request(request_payload) -> DesignRequest:
    return DesignRequest.from_json(request_payload)


@pytest.fixture()
def adapter() -> ChromaAdapter:
    return ChromaAdapter()


# ---------------------------- request parsing ---------------------------- #

def test_request_parses_from_json(design_request: DesignRequest):
    assert design_request.target_pdb == "/inputs/target.pdb"
    assert design_request.seeds == [0, 1]
    assert design_request.num_designs == 2
    assert design_request.target_chain == "A"
    assert design_request.constraints is not None
    assert design_request.constraints.length_range == [80, 120]
    tp = design_request.tool_params or {}
    assert tp["length"] == 100
    assert tp["temperature"] == 1.0
    assert tp["steps"] == 500
    assert len(tp["conditioners"]) == 2


def test_request_allows_missing_target_pdb():
    """Chroma supports unconditional generation — targetPdb is optional."""
    req = DesignRequest.from_json({
        "seeds": [7],
        "numDesigns": 1,
        "toolParams": {"length": 80},
    })
    assert req.target_pdb is None
    assert req.seeds == [7]


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
    design_request.tool_params = {
        **(design_request.tool_params or {}),
        "length_range": [200, 50],
    }
    errors = adapter.validate(design_request)
    assert any(e["field"].endswith("length_range") for e in errors)


def test_validate_rejects_bad_temperature(adapter, design_request):
    design_request.tool_params = {
        **(design_request.tool_params or {}),
        "temperature": 5.0,
    }
    errors = adapter.validate(design_request)
    assert any(e["field"].endswith("temperature") for e in errors)


def test_validate_substructure_requires_target(adapter):
    """SubstructureConditioner without a targetPdb must fail validation."""
    req = DesignRequest.from_json({
        "seeds": [0],
        "numDesigns": 1,
        "toolParams": {
            "length": 100,
            "conditioners": [{"type": "SubstructureConditioner",
                               "params": {"motif_chain": "A"}}],
        },
    })
    errors = adapter.validate(req)
    assert any(e["field"] == "targetPdb" for e in errors)


def test_validate_allows_unconditional_when_no_substructure(adapter):
    """No target PDB + no substructure conditioner is fine."""
    req = DesignRequest.from_json({
        "seeds": [0],
        "numDesigns": 1,
        "toolParams": {"length": 100},
    })
    assert adapter.validate(req) == []


# -------------------------------- prepare -------------------------------- #

def test_prepare_writes_chroma_config(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    cfg_path = pathlib.Path(job["cfg"])
    assert cfg_path.exists(), "prepare() must emit chroma.json"

    cfg = json.loads(cfg_path.read_text())
    assert cfg["target_pdb"] == "/inputs/target.pdb"
    assert cfg["target_chain"] == "A"
    assert cfg["temperature"] == 1.0
    assert cfg["steps"] == 500
    assert cfg["num_designs"] == 2
    assert cfg["seeds"] == [0, 1]
    assert cfg["unconditional"] is False
    # length from toolParams takes precedence
    assert cfg["length"] == 100
    # conditioners passed through verbatim
    assert [c["type"] for c in cfg["conditioners"]] == [
        "SymmetryConditioner", "SubstructureConditioner"
    ]


def test_prepare_job_carries_runtime_args(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    assert job["out_dir"] == "/outputs/designs"
    assert job["seeds"] == [0, 1]
    assert job["num_designs"] == 2
    assert job["temperature"] == 1.0
    assert job["steps"] == 500
    assert job["unconditional"] is False
    assert job["length_spec"] == {"length": 100}
    assert len(job["conditioners"]) == 2


def test_prepare_defaults_length_when_missing(adapter, tmp_path):
    """If no length/length_range/constraints supplied, fall back to default."""
    req = DesignRequest.from_json({
        "seeds": [0],
        "numDesigns": 1,
        "toolParams": {"temperature": 0.8},
    })
    job = adapter.prepare(req, tmp_path)
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["length"] == 100  # DEFAULT_LENGTH


def test_prepare_prefers_length_range_over_length(adapter, tmp_path):
    req = DesignRequest.from_json({
        "seeds": [0],
        "numDesigns": 1,
        "toolParams": {"length": 100, "length_range": [50, 75]},
    })
    job = adapter.prepare(req, tmp_path)
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["length_range"] == [50, 75]
    assert "length" not in cfg


def test_prepare_falls_back_to_constraints_length_range(adapter, tmp_path):
    req = DesignRequest.from_json({
        "seeds": [0],
        "numDesigns": 1,
        "constraints": {"lengthRange": [90, 110]},
    })
    job = adapter.prepare(req, tmp_path)
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["length_range"] == [90, 110]


def test_prepare_unconditional_mode(adapter, tmp_path):
    """No target, no substructure conditioner => unconditional=True."""
    req = DesignRequest.from_json({
        "seeds": [0],
        "numDesigns": 1,
        "toolParams": {
            "length": 80,
            "conditioners": [{"type": "SymmetryConditioner",
                               "params": {"symmetry": "C4"}}],
        },
    })
    job = adapter.prepare(req, tmp_path)
    assert job["unconditional"] is True
    cfg = json.loads(pathlib.Path(job["cfg"]).read_text())
    assert cfg["unconditional"] is True
    assert cfg["target_pdb"] is None


def test_prepare_handles_no_conditioners(adapter, tmp_path):
    req = DesignRequest.from_json({
        "targetPdb": "/inputs/target.pdb",
        "seeds": [0],
        "numDesigns": 1,
        "toolParams": {"length": 100},
    })
    job = adapter.prepare(req, tmp_path)
    assert job["conditioners"] == []


# --------------------------------- parse --------------------------------- #

def test_parse_reads_fixture_designs(adapter, tmp_path):
    # Copy the sample outputs into a tmp dir simulating /outputs/designs.
    out_dir = tmp_path / "designs"
    shutil.copytree(FIXTURES / "sample_output", out_dir)

    result = adapter.parse({"out_dir": str(out_dir), "unconditional": False})
    assert len(result.designs) == 1

    design = result.designs[0]
    # Backbones-only: there is NO sequence field.
    assert "sequence" not in design
    assert design["seed"] == 0
    assert design["structurePath"].endswith(".pdb")

    metrics = design["metrics"]
    assert metrics["length"] == pytest.approx(100.0)
    assert metrics["plddt_mean"] == pytest.approx(78.4)
    assert metrics["clash_score"] == pytest.approx(0.12)

    metadata = design["metadata"]
    assert metadata["conditioners_applied"] == [
        "SymmetryConditioner", "SubstructureConditioner"
    ]
    assert metadata["length_target"] == 100
    assert metadata["temperature"] == pytest.approx(1.0)
    assert metadata["steps"] == 500

    # Run metadata advertises composition hook.
    assert result.run_metadata["tool"] == "chroma"
    assert result.run_metadata["adapterVersion"] == ADAPTER_VERSION
    assert result.run_metadata["composes"] == ["proteinmpnn"]
    assert result.run_metadata["unconditional"] is False


def test_parse_marks_unconditional_in_run_metadata(adapter, tmp_path):
    out_dir = tmp_path / "designs"
    shutil.copytree(FIXTURES / "sample_output", out_dir)

    result = adapter.parse({"out_dir": str(out_dir), "unconditional": True})
    assert result.run_metadata["unconditional"] is True


def test_parse_skips_pdbs_without_sidecar(adapter, tmp_path):
    out_dir = tmp_path / "designs"
    out_dir.mkdir()
    # Only a PDB, no matching .json sidecar — must be silently skipped.
    (out_dir / "orphan.pdb").write_text("ATOM\nEND\n")
    result = adapter.parse({"out_dir": str(out_dir)})
    assert result.designs == []


# ------------------------------ integration ------------------------------ #

@pytest.mark.integration
def test_run_invokes_upstream_chroma(adapter, design_request, tmp_path):
    """Requires the `generate-chroma` pip package — skipped outside container."""
    job = adapter.prepare(design_request, tmp_path)
    adapter.run(job)
