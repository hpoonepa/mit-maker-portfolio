"""Manifest + schema validation tests for the ESM-2 adapter."""
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
    assert manifest["id"] == "esm2"
    assert manifest["displayName"] == "ESM-2"
    assert manifest["version"] == "650M-UR50D"
    assert manifest["adapterVersion"] == "a1"


def test_manifest_category_is_embedding_scoring(manifest: dict):
    """ESM-2 is NOT a design tool — category must be embedding_scoring."""
    assert manifest["category"] == "embedding_scoring"


def test_manifest_tier_valid(manifest: dict):
    assert manifest["tier"] in {"open", "open-weights", "frontier"}


def test_manifest_compute_profile(manifest: dict):
    compute = manifest["compute"]
    for k in ("gpu", "gpuCount", "cpuCores", "memoryGb", "estSecondsPerDesign"):
        assert k in compute, f"compute.{k} missing"
    assert compute["gpu"] == "A10"
    assert compute["gpuCount"] >= 1
    assert compute["memoryGb"] >= 12  # 650M needs ~8 GB + headroom
    # ESM-2 scoring is ~1 s/design on A10 — generous upper bound for CPU fallback.
    assert 1 <= compute["estSecondsPerDesign"] <= 30


def test_manifest_default_params(manifest: dict):
    dp = manifest["defaultParams"]
    assert dp["mode"] == "score"
    assert dp["pool"] == "mean"
    assert dp["layer"] == 33


def test_manifest_no_composes(manifest: dict):
    """ESM-2 is a leaf adapter — it does not orchestrate other tools."""
    assert manifest.get("composes") == []


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


def test_fixture_scores_conform_to_score_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    scores = json.loads((FIXTURES / "sample_output" / "scores.json").read_text())
    fake_result = {
        "designs": [
            {
                "id": rec["id"],
                "seed": rec["seed"],
                "mode": "score",
                "metrics": {
                    "pll_mean": rec["pll_mean"],
                    "pll_sum": rec["pll_sum"],
                    "pll_min": rec["pll_min"],
                    "ppl": rec["ppl"],
                },
            }
            for rec in scores
        ],
        "runMetadata": {
            "tool": "esm2",
            "adapterVersion": "a1",
            "mode": "score",
            "model": "esm2_t33_650M_UR50D",
        },
    }
    Draft7Validator(schema).validate(fake_result)


def test_fixture_embeddings_conform_to_embed_output_schema():
    schema = json.loads(OUTPUT_SCHEMA_PATH.read_text())
    emb = json.loads((FIXTURES / "sample_output" / "embeddings.json").read_text())
    fake_result = {
        "designs": [
            {
                "id": rec["id"],
                "seed": rec["seed"],
                "mode": "embed",
                "embedding_path": rec["path"],
                "shape": rec["shape"],
                "layer": rec["layer"],
                "pool": rec["pool"],
            }
            for rec in emb
        ],
        "runMetadata": {
            "tool": "esm2",
            "adapterVersion": "a1",
            "mode": "embed",
            "model": "esm2_t33_650M_UR50D",
        },
    }
    Draft7Validator(schema).validate(fake_result)


def test_fixture_request_has_expected_shape():
    req = json.loads((FIXTURES / "request.json").read_text())
    for k in ("sequences", "seeds"):
        assert k in req
    assert isinstance(req["sequences"], list) and req["sequences"]
    assert isinstance(req["seeds"], list) and req["seeds"]


def test_fixture_fasta_exists():
    assert (FIXTURES / "sequences.fasta").exists()
