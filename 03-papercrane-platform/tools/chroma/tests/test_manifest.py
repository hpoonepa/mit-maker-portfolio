"""Manifest + schema validation tests for the Chroma adapter."""
from __future__ import annotations

import json
import pathlib

import pytest
from jsonschema import Draft7Validator

TOOL_ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = TOOL_ROOT / "manifest.json"
INPUT_SCHEMA_PATH = TOOL_ROOT / "schemas" / "input.json"
OUTPUT_SCHEMA_PATH = TOOL_ROOT / "schemas" / "output.json"
FIXTURES = TOOL_ROOT / "tests" / "fixtures"


@pytest.fixture()
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_has_required_fields(manifest: dict):
    required = {
        "id", "displayName", "version", "adapterVersion", "category",
        "tier", "license", "image", "imageDigest", "compute",
        "inputSchema", "outputSchema",
    }
    missing = required - manifest.keys()
    assert not missing, f"manifest missing keys: {missing}"


def test_manifest_id_and_category(manifest: dict):
    assert manifest["id"] == "chroma"
    assert manifest["category"] == "backbone_generation"


def test_manifest_license_is_apache(manifest: dict):
    assert manifest["license"] == "Apache-2.0"


def test_manifest_compute_profile(manifest: dict):
    """Catalog locks Chroma to A100 / ~50 s/design."""
    compute = manifest["compute"]
    for k in ("gpu", "gpuCount", "cpuCores", "memoryGb", "estSecondsPerDesign"):
        assert k in compute, f"compute.{k} missing"
    assert compute["gpuCount"] >= 1
    assert compute["memoryGb"] > 0
    assert compute["gpu"].startswith("A100")
    assert compute["estSecondsPerDesign"] == 50


def test_manifest_tier_valid(manifest: dict):
    assert manifest["tier"] in {"open", "open-weights", "frontier"}


def test_manifest_composes_proteinmpnn(manifest: dict):
    """Chroma emits backbones only — must signal the compose hook for MPNN."""
    assert "composes" in manifest
    assert manifest["composes"] == ["proteinmpnn"]


def test_manifest_default_params(manifest: dict):
    defaults = manifest["defaultParams"]
    assert defaults["num_designs"] == 10
    assert defaults["length"] == 100
    assert defaults["temperature"] == 1.0


def test_manifest_schema_paths_exist(manifest: dict):
    assert (TOOL_ROOT / manifest["inputSchema"]).exists()
    assert (TOOL_ROOT / manifest["outputSchema"]).exists()


def test_input_schema_is_valid_draft7():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_output_schema_is_valid_draft7():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_input_schema_accepts_conditioner_array():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    sample = {
        "length": 100,
        "temperature": 1.0,
        "conditioners": [
            {"type": "SymmetryConditioner", "params": {"symmetry": "C3"}},
            {"type": "SubstructureConditioner", "params": {"motif_chain": "A"}},
        ],
    }
    Draft7Validator(schema).validate(sample)


def test_input_schema_accepts_unconditional_length_only():
    """Pure de novo: just a length, nothing else."""
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    Draft7Validator(schema).validate({"length": 120})


def test_input_schema_requires_length_or_range():
    """Neither length nor length_range should fail the oneOf."""
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors({"temperature": 1.0}))
    assert errors, "schema should reject inputs with no length spec"


def test_fixture_output_conforms_to_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    design_pdb = FIXTURES / "sample_output" / "design_0001.pdb"
    design_meta = json.loads(
        (FIXTURES / "sample_output" / "design_0001.json").read_text()
    )
    fake_result = {
        "designs": [
            {
                "structurePath": str(design_pdb),
                "seed": design_meta["seed"],
                "metrics": {
                    "length": float(design_meta["length"]),
                    "plddt_mean": float(design_meta["plddt_mean"]),
                    "clash_score": float(design_meta["clash_score"]),
                },
                "metadata": {
                    "conditioners_applied": design_meta["conditioners_applied"],
                    "length_target": design_meta["length_target"],
                    "temperature": design_meta["temperature"],
                    "steps": design_meta["steps"],
                },
            }
        ],
        "runMetadata": {
            "tool": "chroma",
            "adapterVersion": "a1",
            "composes": ["proteinmpnn"],
            "unconditional": False,
        },
    }
    Draft7Validator(schema).validate(fake_result)


def test_fixture_request_has_expected_shape():
    req = json.loads((FIXTURES / "request.json").read_text())
    for k in ("seeds", "numDesigns"):
        assert k in req
    assert isinstance(req["seeds"], list) and req["seeds"]
    # targetPdb is present in this fixture (substructure conditioner is used)
    assert req["targetPdb"] == "/inputs/target.pdb"
    assert any(
        c["type"] == "SubstructureConditioner"
        for c in req["toolParams"]["conditioners"]
    )
