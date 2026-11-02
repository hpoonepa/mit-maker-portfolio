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


def test_manifest_identity(manifest: dict):
    assert manifest["id"] == "ligandmpnn"
    assert manifest["displayName"] == "LigandMPNN"
    assert manifest["version"] == "1.0.0"
    assert manifest["adapterVersion"] == "a1"


def test_manifest_compute_profile(manifest: dict):
    compute = manifest["compute"]
    for k in ("gpu", "gpuCount", "cpuCores", "memoryGb", "estSecondsPerDesign"):
        assert k in compute, f"compute.{k} missing"
    assert compute["gpu"] == "A10"
    assert compute["gpuCount"] >= 1
    assert compute["memoryGb"] == 12
    # Catalog row sets expectation ~6s/design — allow a wide band but ensure
    # sanity (if someone bumps this past a minute/design, review it).
    assert 1 <= compute["estSecondsPerDesign"] <= 60


def test_manifest_tier_valid(manifest: dict):
    assert manifest["tier"] in {"open", "open-weights", "frontier"}


def test_manifest_category_valid(manifest: dict):
    assert manifest["category"] == "sequence_design"


def test_manifest_license(manifest: dict):
    assert manifest["license"] == "MIT"


def test_manifest_default_params(manifest: dict):
    dp = manifest["defaultParams"]
    assert dp["temperature"] == pytest.approx(0.1)
    assert dp["omit_aas"] == "CX"
    assert dp["num_seq_per_target"] == 1
    assert dp["ligand_context_radius"] == pytest.approx(8.0)


def test_manifest_schema_paths_exist(manifest: dict):
    assert (TOOL_ROOT / manifest["inputSchema"]).exists()
    assert (TOOL_ROOT / manifest["outputSchema"]).exists()


def test_input_schema_is_valid_draft7():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_output_schema_is_valid_draft7():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_fixture_request_validates_against_input_schema():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    req = json.loads((FIXTURES / "request.json").read_text())
    Draft7Validator(schema).validate(req)


def test_fixture_output_conforms_to_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    meta = json.loads(
        (FIXTURES / "sample_output" / "design_0001.json").read_text()
    )
    fake_result = {
        "designs": [
            {
                "structurePath": meta["structurePath"],
                "ligandPath": meta["ligandPath"],
                "sequence": meta["sequence"],
                "metrics": {
                    "score": meta["score"],
                    "confidence_mean": meta["confidence_mean"],
                    "ligand_context_residues": meta["ligand_context_residues"],
                },
                "seed": meta["seed"],
            }
        ],
        "runMetadata": {"tool": "ligandmpnn", "adapterVersion": "a1"},
    }
    Draft7Validator(schema).validate(fake_result)


def test_fixture_request_has_expected_shape():
    req = json.loads((FIXTURES / "request.json").read_text())
    for k in ("backbones", "seeds"):
        assert k in req
    assert isinstance(req["backbones"], list) and req["backbones"]
    assert isinstance(req["seeds"], list) and req["seeds"]
    assert "ligand_atoms" in req
    assert isinstance(req["ligand_atoms"], list) and req["ligand_atoms"]


def test_fixture_backbone_exists():
    assert (FIXTURES / "backbones" / "backbone_0001.pdb").exists()


def test_fixture_ligand_exists():
    assert (FIXTURES / "ligands" / "ligand.sdf").exists()
