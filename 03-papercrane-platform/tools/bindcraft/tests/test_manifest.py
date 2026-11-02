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


def test_input_schema_is_valid_draft7():
    schema = json.loads(INPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_output_schema_is_valid_draft7():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    Draft7Validator.check_schema(schema)


def test_fixture_output_conforms_to_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    fake_result = {
        "designs": [
            {
                "structurePath": str(FIXTURES / "sample_output" / "design_0001.pdb"),
                "sequence": json.loads(
                    (FIXTURES / "sample_output" / "design_0001.json").read_text()
                )["sequence"],
                "metrics": {
                    "iptm": 0.82, "plddt": 88.4, "i_pae": 7.1, "hotspot_contact": 0.73
                },
                "seed": 0,
            }
        ],
        "runMetadata": {"tool": "bindcraft", "adapterVersion": "a1"},
    }
    Draft7Validator(schema).validate(fake_result)


def test_fixture_request_has_expected_shape():
    req = json.loads((FIXTURES / "request.json").read_text())
    for k in ("targetPdb", "seeds", "numDesigns"):
        assert k in req
    assert isinstance(req["seeds"], list) and req["seeds"]


def test_modal_runner_executes_upstream_script_without_package_import():
    """Regression: importing bindcraft.py as a package fails on `functions`."""
    source = (TOOL_ROOT / "modal_app.py").read_text()
    assert "from bindcraft import bindcraft" not in source
    assert 'cwd="/root/bindcraft"' in source
    assert 'env["PYTHONPATH"]' in source


def test_modal_image_patches_current_pyrosetta_docking_partners_api():
    source = (TOOL_ROOT / "modal_app.py").read_text()
    assert "DockingPartners.docking_partners_from_string" in source


def test_modal_runner_does_not_count_nonzero_exit_as_completed():
    source = (TOOL_ROOT / "modal_app.py").read_text()
    assert "raise BindCraftRunError" in source
    assert "except BindCraftRunError as e:" in source


def test_modal_smoke_uses_a_unique_cache_key():
    source = (TOOL_ROOT / "modal_app.py").read_text()
    assert '"job_id": f"smoke-{secrets.token_hex(6)}"' in source


def test_modal_runner_does_not_duplicate_structure_relpath():
    source = (TOOL_ROOT / "modal_app.py").read_text()
    assert "if structure_relpath" in source
    assert 'str(structure_relpath)' in source
