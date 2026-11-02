"""Manifest + schema sanity tests for the AF3 adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((TOOL_DIR / "manifest.json").read_text())


def test_manifest_identity():
    assert MANIFEST["id"] == "alphafold3"
    assert MANIFEST["category"] == "structure_prediction"
    assert MANIFEST["tier"] == "frontier"
    assert MANIFEST["licenseGate"] is False


def test_manifest_uses_protenix_on_modal():
    assert MANIFEST["transport"] == {
        "type": "modal",
        "app": "alphafold3",
        "function": "papercrane_dispatch",
    }
    assert MANIFEST["license"].startswith("Apache-2.0")


def test_modal_entrypoint_exists():
    assert (TOOL_DIR / "modal_app.py").exists()


def test_schema_files_present_and_valid_json():
    for name in ("input.json", "output.json"):
        path = TOOL_DIR / "schemas" / name
        assert path.exists(), f"missing schema: {name}"
        json.loads(path.read_text())  # raises if malformed


def test_default_params_present():
    dp = MANIFEST["defaultParams"]
    for key in ("num_recycles", "num_samples", "num_seeds"):
        assert key in dp, f"defaultParams missing {key}"


def test_open_protenix_backend_has_no_license_gate():
    assert MANIFEST["licenseGate"] is False
    assert not (TOOL_DIR / "LICENSE-GATE.md").exists()


def test_input_fixture_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((TOOL_DIR / "schemas" / "input.json").read_text())
    request = json.loads(
        (TOOL_DIR / "tests" / "fixtures" / "request.json").read_text()
    )
    jsonschema.validate(request, schema)


def test_output_fixture_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((TOOL_DIR / "schemas" / "output.json").read_text())
    payload = json.loads(
        (TOOL_DIR / "tests" / "fixtures" / "sample_output" / "prediction_0001.json").read_text()
    )
    jsonschema.validate(payload, schema)
