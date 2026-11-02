"""Manifest + schema validation tests."""
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


def test_manifest_id_is_boltzgen(manifest: dict):
    assert manifest["id"] == "boltzgen"


def test_manifest_compute_profile(manifest: dict):
    compute = manifest["compute"]
    for k in ("gpu", "gpuCount", "cpuCores", "memoryGb", "estSecondsPerDesign"):
        assert k in compute, f"compute.{k} missing"
    assert compute["gpuCount"] >= 1
    assert compute["memoryGb"] > 0


def test_manifest_tier_valid(manifest: dict):
    assert manifest["tier"] in {"open", "open-weights", "frontier"}


def test_manifest_category_valid(manifest: dict):
    assert manifest["category"] == "binder_design"


def test_manifest_schema_paths_exist(manifest: dict):
    assert (TOOL_ROOT / manifest["inputSchema"]).exists()
    assert (TOOL_ROOT / manifest["outputSchema"]).exists()


def test_manifest_default_params_present(manifest: dict):
    defaults = manifest.get("defaultParams", {})
    for k in ("num_designs", "diffusion_steps", "temperature", "length_range"):
        assert k in defaults, f"defaultParams.{k} missing"


def test_input_schema_is_valid_draft7():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_input_schema_declares_ligand():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    assert "ligand" in schema["properties"]
    assert schema["properties"]["ligand"]["type"] == "string"


def test_output_schema_is_valid_draft7():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_fixture_output_conforms_to_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    meta = json.loads((FIXTURES / "sample_output" / "design_0001.json").read_text())
    fake_result = {
        "designs": [
            {
                "structurePath": str(FIXTURES / "sample_output" / "design_0001.pdb"),
                "sequence": meta["sequence"],
                "metrics": {
                    "plddt_mean": 87.3,
                    "clash_score": 0.05,
                    "sidechain_confidence": 0.81,
                    "hotspot_contact": 0.74,
                    "ligand_rmsd": 1.42,
                },
                "seed": 0,
            }
        ],
        "runMetadata": {"tool": "boltzgen", "adapterVersion": "a1"},
    }
    Draft7Validator(schema).validate(fake_result)


def test_fixture_request_has_expected_shape():
    req = json.loads((FIXTURES / "request.json").read_text())
    for k in ("targetPdb", "seeds", "numDesigns"):
        assert k in req
    assert isinstance(req["seeds"], list) and req["seeds"]
    # Ligand is the BoltzGen-specific field.
    assert req.get("ligand", "").endswith((".sdf", ".pdb"))
