"""Manifest + schema validation tests for the Chai-1 adapter."""
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
LICENSE_GATE_PATH = TOOL_ROOT / "LICENSE-GATE.md"


@pytest.fixture()
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_has_required_fields(manifest: dict):
    required = {
        "id", "displayName", "version", "adapterVersion", "category",
        "tier", "license", "image", "imageDigest", "compute",
        "inputSchema", "outputSchema", "licenseGate",
    }
    missing = required - manifest.keys()
    assert not missing, f"manifest missing keys: {missing}"


def test_manifest_identity(manifest: dict):
    assert manifest["id"] == "chai1"
    assert manifest["displayName"] == "Chai-1"
    assert manifest["adapterVersion"] == "a1"


def test_manifest_category(manifest: dict):
    assert manifest["category"] == "structure_prediction"


def test_manifest_tier_is_frontier(manifest: dict):
    # Chai-1 has a non-commercial license and remains behind the explicit
    # Frontier acknowledgement gate.
    assert manifest["tier"] == "frontier"
    assert manifest["tier"] in {"open", "open-weights", "frontier"}


def test_manifest_license_gate_enabled(manifest: dict):
    """Chai-1 non-commercial license → platform MUST render EULA modal."""
    assert manifest["licenseGate"] is True, (
        "Chai-1 must have licenseGate: true so the UI renders the EULA modal "
        "before each run (see LICENSE-GATE.md and plan 02 §§8, 9)."
    )
    assert "non-commercial" in manifest["license"].lower()


def test_manifest_compute_profile(manifest: dict):
    compute = manifest["compute"]
    for k in ("gpu", "gpuCount", "cpuCores", "memoryGb", "estSecondsPerDesign"):
        assert k in compute, f"compute.{k} missing"
    # Chai-1 needs A100-80GB per plan 02 §8.
    assert "80GB" in compute["gpu"]
    assert compute["gpuCount"] >= 1
    assert compute["memoryGb"] > 0


def test_manifest_default_params(manifest: dict):
    defaults = manifest["defaultParams"]
    assert defaults["num_trunk_recycles"] == 3
    assert defaults["num_diffn_timesteps"] == 200
    # Per-run seeds are canonical request fields, not adapter defaults.
    assert "seed" not in defaults


def test_manifest_schema_paths_exist(manifest: dict):
    assert (TOOL_ROOT / manifest["inputSchema"]).exists()
    assert (TOOL_ROOT / manifest["outputSchema"]).exists()


def test_license_gate_doc_exists():
    assert LICENSE_GATE_PATH.exists(), (
        "LICENSE-GATE.md is required for any tool with licenseGate: true"
    )
    body = LICENSE_GATE_PATH.read_text().lower()
    assert "non-commercial" in body
    assert "chai discovery" in body


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


def test_fixture_output_conforms_to_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    sample_meta = json.loads(
        (FIXTURES / "sample_output" / "prediction_0001.json").read_text()
    )
    fake_result = {
        "predictions": [
            {
                "structurePath": str(FIXTURES / "sample_output" / "prediction_0001.cif"),
                "seed": sample_meta["seed"],
                "model_idx": sample_meta["model_idx"],
                "metrics": {
                    "plddt_mean": sample_meta["plddt_mean"],
                    "plddt_binder": sample_meta["plddt_binder"],
                    "ptm": sample_meta["ptm"],
                    "iptm": sample_meta["iptm"],
                    "aggregate_score": 0.6 * sample_meta["iptm"]
                    + 0.2 * sample_meta["ptm"]
                    + 0.2 * (sample_meta["plddt_mean"] / 100.0),
                },
            }
        ],
        "runMetadata": {
            "tool": "chai1",
            "adapterVersion": "a1",
            "licenseAcknowledged": True,
        },
    }
    Draft7Validator(schema).validate(fake_result)


def test_fixture_request_has_expected_shape():
    req = json.loads((FIXTURES / "request.json").read_text())
    assert "chains" in req and isinstance(req["chains"], list) and req["chains"]
    assert "seeds" in req and req["seeds"]
    for chain in req["chains"]:
        assert "id" in chain and "sequence" in chain
