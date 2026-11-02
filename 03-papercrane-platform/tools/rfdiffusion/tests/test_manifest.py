"""Manifest + schema validation tests for the RFdiffusion adapter."""
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
    assert manifest["id"] == "rfdiffusion"
    assert manifest["category"] == "backbone_generation"


def test_manifest_compute_profile(manifest: dict):
    """Catalog (plan 02 §8) locks RFdiffusion to A100 / ~35 s/design."""
    compute = manifest["compute"]
    for k in ("gpu", "gpuCount", "cpuCores", "memoryGb", "estSecondsPerDesign"):
        assert k in compute, f"compute.{k} missing"
    assert compute["gpuCount"] >= 1
    assert compute["memoryGb"] > 0
    assert compute["gpu"].startswith("A100")
    assert compute["estSecondsPerDesign"] == 35


def test_manifest_tier_valid(manifest: dict):
    assert manifest["tier"] in {"open", "open-weights", "frontier"}


def test_manifest_composes_proteinmpnn(manifest: dict):
    """RFdiffusion must signal the compose hook for ProteinMPNN."""
    assert "composes" in manifest
    assert manifest["composes"] == ["proteinmpnn"]


def test_manifest_default_params(manifest: dict):
    defaults = manifest["defaultParams"]
    assert defaults["num_designs"] == 1
    assert defaults["binder_length_range"] == [60, 150]
    assert defaults["noise_scale"] == 1.0


def test_manifest_schema_paths_exist(manifest: dict):
    assert (TOOL_ROOT / manifest["inputSchema"]).exists()
    assert (TOOL_ROOT / manifest["outputSchema"]).exists()


def test_input_schema_is_valid_draft7():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_output_schema_is_valid_draft7():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_fixture_output_conforms_to_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    backbone_pdb = FIXTURES / "sample_output" / "backbone_0001.pdb"
    backbone_meta = json.loads(
        (FIXTURES / "sample_output" / "backbone_0001.json").read_text()
    )
    fake_result = {
        "designs": [
            {
                "structurePath": str(backbone_pdb),
                "seed": backbone_meta["seed"],
                "metrics": {
                    "length": float(backbone_meta["length"]),
                    "plddt_contig_mean": float(backbone_meta["plddt_contig_mean"]),
                },
                "metadata": {
                    "contigs_used": backbone_meta["contigs_used"],
                    "noise_scale": backbone_meta["noise_scale"],
                    "hotspots": backbone_meta["hotspots"],
                },
            }
        ],
        "runMetadata": {
            "tool": "rfdiffusion",
            "adapterVersion": "a1",
            "composes": ["proteinmpnn"],
        },
    }
    Draft7Validator(schema).validate(fake_result)


def test_fixture_request_has_expected_shape():
    req = json.loads((FIXTURES / "request.json").read_text())
    for k in ("targetPdb", "seeds", "numDesigns"):
        assert k in req
    assert isinstance(req["seeds"], list) and req["seeds"]
