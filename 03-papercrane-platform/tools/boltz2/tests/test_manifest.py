"""Manifest + schema validation tests for the Boltz-2 adapter."""
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
        "inputSchema", "outputSchema", "defaultParams",
    }
    missing = required - manifest.keys()
    assert not missing, f"manifest missing keys: {missing}"


def test_manifest_compute_profile(manifest: dict):
    compute = manifest["compute"]
    for k in ("gpu", "gpuCount", "cpuCores", "memoryGb", "estSecondsPerDesign"):
        assert k in compute, f"compute.{k} missing"
    assert compute["gpuCount"] >= 1
    assert compute["memoryGb"] > 0
    # L40S handles normal beta workloads. Very large complexes can override
    # the Modal GPU setting to request an A100-80GB.
    assert compute["gpu"] == "L40S"


def test_manifest_tier_valid(manifest: dict):
    assert manifest["tier"] in {"open", "open-weights", "frontier"}


def test_manifest_category_is_structure_prediction(manifest: dict):
    assert manifest["category"] == "structure_prediction"


def test_manifest_id_and_image_pin(manifest: dict):
    assert manifest["id"] == "boltz2"
    # Image tag must encode both the upstream version and the adapterVersion.
    assert manifest["version"] in manifest["image"]
    assert manifest["adapterVersion"] in manifest["image"]


def test_manifest_default_params_reasonable(manifest: dict):
    p = manifest["defaultParams"]
    assert p["recycling_steps"] >= 1
    assert p["sampling_steps"] >= 10
    assert p["diffusion_samples"] >= 1


def test_manifest_schema_paths_exist(manifest: dict):
    assert (TOOL_ROOT / manifest["inputSchema"]).exists()
    assert (TOOL_ROOT / manifest["outputSchema"]).exists()


def test_input_schema_is_valid_draft7():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_output_schema_is_valid_draft7():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_fixture_request_conforms_to_input_schema():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    req = json.loads((FIXTURES / "request.json").read_text())
    Draft7Validator(schema).validate(req)


def test_fixture_request_has_expected_shape():
    req = json.loads((FIXTURES / "request.json").read_text())
    for k in ("targetSeq", "binders"):
        assert k in req
    assert isinstance(req["binders"], list) and req["binders"]
    assert all("sequence" in b and "seed" in b for b in req["binders"])


def test_fixture_output_conforms_to_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    sample_metrics = json.loads(
        (FIXTURES / "sample_output" / "prediction_0001.json").read_text()
    )
    fake_result = {
        "predictions": [
            {
                "structurePath": str(
                    FIXTURES / "sample_output" / "prediction_0001.cif"
                ),
                "seed": 0,
                "metrics": sample_metrics,
            }
        ],
        "runMetadata": {"tool": "boltz2", "adapterVersion": "a1"},
    }
    Draft7Validator(schema).validate(fake_result)
