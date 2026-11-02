"""Unit tests for the ESM-2 adapter.

These tests exercise `prepare()` and `parse()` without invoking the upstream
ESM runner. Anything that would actually spawn `papercrane.esm2_runner` (and
therefore load ~2.6 GB of weights) is tagged `@pytest.mark.integration` and
skipped by default.
"""
from __future__ import annotations

import json
import math
import pathlib
import shutil
import sys

import pytest

TOOL_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = TOOL_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(TOOL_ROOT))

from adapter import (  # noqa: E402
    ADAPTER_VERSION,
    MODEL_NAME,
    DesignRequest,
    ESM2Adapter,
    ESM2Params,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def design_request(request_payload) -> DesignRequest:
    return DesignRequest.from_json(request_payload)


@pytest.fixture()
def adapter() -> ESM2Adapter:
    return ESM2Adapter()


# ------------------------- Request parsing ------------------------- #

def test_request_parses_from_json(design_request: DesignRequest):
    assert len(design_request.sequences) == 2
    assert design_request.sequences[0].id == "design_0001"
    assert design_request.sequences[0].sequence.startswith("MKTAY")
    assert design_request.seeds == [0]
    assert design_request.params.mode == "score"
    assert design_request.params.pool == "mean"
    assert design_request.params.layer == 33


def test_params_default_mode_is_score():
    """Default mode when params is omitted must be `score` (catalog default)."""
    req = DesignRequest.from_json({
        "sequences": [{"id": "a", "sequence": "MKTAY"}],
        "seeds": [0],
    })
    assert req.params.mode == "score"
    assert req.params.pool == "mean"
    assert req.params.layer == 33


def test_params_round_trip_defaults_match_manifest():
    """Keep manifest defaultParams in sync with ESM2Params defaults."""
    p = ESM2Params()
    manifest = json.loads((TOOL_ROOT / "manifest.json").read_text())
    dp = manifest["defaultParams"]
    assert p.mode == dp["mode"]
    assert p.pool == dp["pool"]
    assert p.layer == dp["layer"]


# ------------------------- Validation ------------------------- #

def test_validate_accepts_valid_request(adapter, design_request):
    assert adapter.validate(design_request) == []


def test_validate_rejects_empty_sequences(adapter, design_request):
    design_request.sequences = []
    errors = adapter.validate(design_request)
    assert any(e["field"] == "sequences" for e in errors)


def test_validate_rejects_empty_seeds(adapter, design_request):
    design_request.seeds = []
    errors = adapter.validate(design_request)
    assert any(e["field"] == "seeds" for e in errors)


def test_validate_rejects_non_canonical_aa(adapter, design_request):
    design_request.sequences[0].sequence = "MKTAYB"  # B is non-canonical
    errors = adapter.validate(design_request)
    assert any("sequence" in e["field"] for e in errors)


def test_validate_rejects_bad_mode(adapter, design_request):
    design_request.params.mode = "predict"
    errors = adapter.validate(design_request)
    assert any(e["field"] == "params.mode" for e in errors)


def test_validate_rejects_bad_pool(adapter, design_request):
    design_request.params.pool = "max"
    errors = adapter.validate(design_request)
    assert any(e["field"] == "params.pool" for e in errors)


def test_validate_rejects_layer_out_of_range(adapter, design_request):
    design_request.params.layer = 99
    errors = adapter.validate(design_request)
    assert any(e["field"] == "params.layer" for e in errors)


# ------------------------- prepare() ------------------------- #

def test_prepare_writes_fasta(adapter, design_request, tmp_path):
    job = adapter.prepare(design_request, tmp_path)
    fasta_path = pathlib.Path(job["fasta_path"])
    assert fasta_path.exists()

    content = fasta_path.read_text()
    assert ">design_0001" in content
    assert ">design_0002" in content
    assert "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ" in content


def test_prepare_captures_mode_and_embed_args(adapter, design_request, tmp_path):
    design_request.params.mode = "embed"
    design_request.params.pool = "cls"
    design_request.params.layer = 30
    job = adapter.prepare(design_request, tmp_path)
    assert job["mode"] == "embed"
    assert job["pool"] == "cls"
    assert job["layer"] == 30
    assert job["seeds"] == [0]


# ------------------------- parse() — score mode ------------------------- #

def test_parse_score_mode_reads_scores_json(adapter, design_request, tmp_path):
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    shutil.copy(FIXTURES / "sample_output" / "scores.json", out_dir / "scores.json")

    job = adapter.prepare(design_request, tmp_path / "workdir")
    raw = {"out_dir": str(out_dir), "mode": "score", "job": job}
    result = adapter.parse(raw)

    assert len(result.designs) == 2

    d0 = result.designs[0]
    assert d0["id"] == "design_0001"
    assert d0["mode"] == "score"
    assert d0["seed"] == 0
    assert d0["metrics"]["pll_mean"] == pytest.approx(-1.42)
    assert d0["metrics"]["pll_sum"] == pytest.approx(-46.86)
    assert d0["metrics"]["pll_min"] == pytest.approx(-4.11)
    assert d0["metrics"]["ppl"] == pytest.approx(4.137, rel=1e-3)
    # parse() should echo back the sequence since prepare() captured it
    assert d0["sequence"].startswith("MKTAY")

    assert result.run_metadata["tool"] == "esm2"
    assert result.run_metadata["mode"] == "score"
    assert result.run_metadata["model"] == MODEL_NAME
    assert result.run_metadata["adapterVersion"] == ADAPTER_VERSION


def test_parse_score_mode_computes_ppl_when_missing(adapter, design_request, tmp_path):
    """If the runner forgets to emit `ppl`, parse() derives it from pll_mean."""
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    (out_dir / "scores.json").write_text(json.dumps([
        {"id": "design_0001", "seed": 0, "pll_mean": -1.0, "pll_sum": -30.0, "pll_min": -3.0}
    ]))

    job = adapter.prepare(design_request, tmp_path / "workdir")
    raw = {"out_dir": str(out_dir), "mode": "score", "job": job}
    result = adapter.parse(raw)
    assert result.designs[0]["metrics"]["ppl"] == pytest.approx(math.exp(1.0), rel=1e-6)


# ------------------------- parse() — embed mode ------------------------- #

def test_parse_embed_mode_reads_embeddings_json(adapter, design_request, tmp_path):
    design_request.params.mode = "embed"
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    shutil.copy(FIXTURES / "sample_output" / "embeddings.json", out_dir / "embeddings.json")

    job = adapter.prepare(design_request, tmp_path / "workdir")
    raw = {"out_dir": str(out_dir), "mode": "embed", "job": job}
    result = adapter.parse(raw)

    assert len(result.designs) == 2
    d0 = result.designs[0]
    assert d0["mode"] == "embed"
    assert d0["embedding_path"] == "design_0001.npy"
    assert d0["shape"] == [1, 1280]
    assert d0["pool"] == "mean"
    assert d0["layer"] == 33
    assert d0["sequence"].startswith("MKTAY")
    assert result.run_metadata["mode"] == "embed"


def test_parse_embed_mode_unpooled_shape(adapter, design_request, tmp_path):
    """When pool=none the shape is [seq_len, 1280], not [1, 1280]."""
    design_request.params.mode = "embed"
    design_request.params.pool = "none"
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    (out_dir / "embeddings.json").write_text(json.dumps([
        {
            "id": "design_0001",
            "seed": 0,
            "path": "design_0001.npy",
            "shape": [33, 1280],
            "layer": 33,
            "pool": "none",
        }
    ]))

    job = adapter.prepare(design_request, tmp_path / "workdir")
    raw = {"out_dir": str(out_dir), "mode": "embed", "job": job}
    result = adapter.parse(raw)

    d0 = result.designs[0]
    assert d0["shape"] == [33, 1280]
    assert d0["pool"] == "none"


def test_parse_rejects_unknown_mode(adapter, tmp_path):
    with pytest.raises(ValueError):
        adapter.parse({"out_dir": str(tmp_path), "mode": "classify"})


# ------------------------- Integration ------------------------- #

@pytest.mark.integration
def test_run_invokes_upstream_runner(adapter, design_request, tmp_path):
    """Requires papercrane.esm2_runner + ESM-2 weights — skipped outside the container."""
    job = adapter.prepare(design_request, tmp_path)
    job["out_dir"] = str(tmp_path)
    adapter.run(job)
