"""Manifest schema tests — mirrors tools-sdk/tests/manifest.test.ts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from papercrane_sdk.manifest import ToolManifest, load_manifest

FIXTURES = Path(__file__).parent / "fixtures"
VALID = json.loads((FIXTURES / "manifest.json").read_text())


def test_parses_valid_manifest():
    m = ToolManifest.model_validate(VALID)
    assert m.id == "bindcraft"
    assert m.compute.gpu_count == 1
    assert m.tier == "open"


def test_accepts_frontier_tier_with_transport():
    data = dict(VALID, id="af3", tier="frontier", transport={
        "type": "https",
        "endpoint": "https://api.alphafold.example/v3/run",
    })
    m = ToolManifest.model_validate(data)
    assert m.tier == "frontier"
    assert m.transport is not None
    assert m.transport.type == "https"


def test_accepts_modal_transport():
    data = dict(
        VALID,
        id="alphafold3",
        category="structure_prediction",
        tier="frontier",
        licenseGate=False,
        transport={
            "type": "modal",
            "app": "alphafold3",
            "function": "papercrane_dispatch",
        },
    )
    m = ToolManifest.model_validate(data)
    assert m.transport is not None
    assert m.transport.type == "modal"
    assert m.transport.app == "alphafold3"
    assert m.license_gate is False


def test_rejects_missing_required():
    bad = {k: v for k, v in VALID.items() if k != "id"}
    with pytest.raises(PydanticValidationError):
        ToolManifest.model_validate(bad)


def test_rejects_invalid_tier():
    bad = dict(VALID, tier="not-a-tier")
    with pytest.raises(PydanticValidationError):
        ToolManifest.model_validate(bad)


def test_rejects_malformed_digest():
    bad = dict(VALID, imageDigest="not-a-digest")
    with pytest.raises(PydanticValidationError):
        ToolManifest.model_validate(bad)


def test_rejects_malformed_id():
    bad = dict(VALID, id="Bad ID With Spaces")
    with pytest.raises(PydanticValidationError):
        ToolManifest.model_validate(bad)


def test_load_manifest_from_disk(tmp_path: Path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(VALID))
    m = load_manifest(p)
    assert m.id == "bindcraft"
    assert m.adapter_version == "a3"


def test_load_manifest_file_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "does_not_exist.json")


def test_load_manifest_invalid_data(tmp_path: Path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"id": "x"}))
    with pytest.raises(Exception):
        load_manifest(p)


def test_manifest_serializes_camelcase():
    m = ToolManifest.model_validate(VALID)
    wire = m.model_dump(by_alias=True, exclude_none=True)
    assert "displayName" in wire
    assert "adapterVersion" in wire
    assert "imageDigest" in wire
    assert wire["compute"]["gpuCount"] == 1
    assert wire["compute"]["cpuCores"] == 8
    assert wire["compute"]["memoryGb"] == 32
    assert wire["compute"]["estSecondsPerDesign"] == 140
