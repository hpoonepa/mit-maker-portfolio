"""Unit tests for the Boltz-1 adapter.

These tests exercise `validate()`, `prepare()`, and `parse()` without invoking
the upstream `boltz` CLI. Anything that would actually spawn boltz is tagged
`@pytest.mark.integration` and skipped by default.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

TOOL_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = TOOL_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(TOOL_ROOT))

from adapter import (  # noqa: E402
    ADAPTER_VERSION,
    Boltz1Adapter,
    Boltz1Request,
    _emit_boltz_yaml,
)


@pytest.fixture()
def request_payload() -> dict:
    return json.loads((FIXTURES / "request.json").read_text())


@pytest.fixture()
def boltz_request(request_payload) -> Boltz1Request:
    return Boltz1Request.from_json(request_payload)


@pytest.fixture()
def adapter() -> Boltz1Adapter:
    return Boltz1Adapter()


def test_request_parses_from_json(boltz_request: Boltz1Request):
    assert boltz_request.target_pdb == "/inputs/target.pdb"
    assert boltz_request.target_seq.startswith("MKTAY")
    assert len(boltz_request.binders) == 2
    assert boltz_request.binders[0].seed == 0
    assert boltz_request.binders[0].sequence.startswith("MKQLE")
    assert boltz_request.binders[1].seed == 1
    assert boltz_request.params.recycling_steps == 3
    assert boltz_request.params.sampling_steps == 200
    assert boltz_request.params.diffusion_samples == 3


def test_request_params_default_when_absent():
    req = Boltz1Request.from_json({
        "targetSeq": "MKTAY",
        "binders": [{"sequence": "GAAG", "seed": 0}],
    })
    assert req.params.recycling_steps == 3
    assert req.params.sampling_steps == 200
    assert req.params.diffusion_samples == 3
    assert req.target_pdb is None


def test_validate_accepts_valid_request(adapter, boltz_request):
    assert adapter.validate(boltz_request) == []


def test_validate_rejects_missing_binders(adapter, boltz_request):
    boltz_request.binders = []
    errors = adapter.validate(boltz_request)
    assert any(e["field"] == "binders" for e in errors)


def test_validate_rejects_duplicate_seeds(adapter, boltz_request):
    boltz_request.binders[1].seed = boltz_request.binders[0].seed
    errors = adapter.validate(boltz_request)
    assert any("duplicate seed" in e["message"] for e in errors)


def test_validate_rejects_out_of_range_params(adapter, boltz_request):
    boltz_request.params.recycling_steps = 0
    boltz_request.params.sampling_steps = 5
    boltz_request.params.diffusion_samples = 99
    errors = adapter.validate(boltz_request)
    fields = {e["field"] for e in errors}
    assert "params.recycling_steps" in fields
    assert "params.sampling_steps" in fields
    assert "params.diffusion_samples" in fields


def test_emit_boltz_yaml_includes_both_chains():
    yaml_text = _emit_boltz_yaml(
        target_seq="MKTAY",
        binder_seq="GAAG",
        template_path=None,
    )
    assert "version: 1" in yaml_text
    assert "id: A" in yaml_text
    assert "sequence: MKTAY" in yaml_text
    assert "id: B" in yaml_text
    assert "sequence: GAAG" in yaml_text
    # No template block when no path provided.
    assert "templates:" not in yaml_text


def test_emit_boltz_yaml_adds_template_block():
    yaml_text = _emit_boltz_yaml(
        target_seq="MKTAY",
        binder_seq="GAAG",
        template_path="/inputs/target.pdb",
    )
    assert "templates:" in yaml_text
    assert "cif_url: /inputs/target.pdb" in yaml_text


def test_prepare_emits_one_yaml_per_binder(adapter, boltz_request, tmp_path):
    job = adapter.prepare(boltz_request, tmp_path)
    assert len(job["jobs"]) == 2
    for sub, binder in zip(job["jobs"], boltz_request.binders):
        cfg_path = pathlib.Path(sub["cfg"])
        assert cfg_path.exists()
        text = cfg_path.read_text()
        assert f"sequence: {boltz_request.target_seq}" in text
        assert f"sequence: {binder.sequence}" in text
        assert sub["seed"] == binder.seed


def test_prepare_passes_params_through(adapter, boltz_request, tmp_path):
    job = adapter.prepare(boltz_request, tmp_path)
    assert job["params"]["recycling_steps"] == 3
    assert job["params"]["sampling_steps"] == 200
    assert job["params"]["diffusion_samples"] == 3


def test_prepare_omits_template_when_no_target_pdb(adapter, boltz_request, tmp_path):
    boltz_request.target_pdb = None
    job = adapter.prepare(boltz_request, tmp_path)
    cfg_text = pathlib.Path(job["jobs"][0]["cfg"]).read_text()
    assert "templates:" not in cfg_text


def test_parse_reads_fixture_predictions(adapter, tmp_path):
    # Simulate what run() would have produced: one seed dir with a nested
    # out/ tree containing the sample prediction pair.
    seed_out = tmp_path / "seed_0" / "out"
    shutil.copytree(FIXTURES / "sample_output", seed_out)

    raw = {
        "jobs": [
            {"seed": 0, "cfg": "ignored", "out_dir": str(seed_out)},
        ],
    }
    result = adapter.parse(raw)

    assert len(result.predictions) == 1
    pred = result.predictions[0]
    assert pred["seed"] == 0
    assert pred["structurePath"].endswith("prediction_0001.cif")

    metrics = pred["metrics"]
    assert metrics["plddt_mean"] == pytest.approx(79.1)
    assert metrics["plddt_binder"] == pytest.approx(75.6)
    assert metrics["ptm"] == pytest.approx(0.72)
    assert metrics["iptm"] == pytest.approx(0.65)
    assert metrics["ipae_mean"] == pytest.approx(9.7)
    assert metrics["per_chain_ptm"]["A"] == pytest.approx(0.76)
    assert metrics["per_chain_ptm"]["B"] == pytest.approx(0.68)

    assert result.run_metadata["tool"] == "boltz1"
    assert result.run_metadata["adapterVersion"] == ADAPTER_VERSION


def test_parse_skips_seeds_without_predictions(adapter, tmp_path):
    # One seed has a prediction pair; the other is empty.
    good_dir = tmp_path / "seed_0" / "out"
    shutil.copytree(FIXTURES / "sample_output", good_dir)
    bad_dir = tmp_path / "seed_1" / "out"
    bad_dir.mkdir(parents=True)

    raw = {
        "jobs": [
            {"seed": 0, "cfg": "ignored", "out_dir": str(good_dir)},
            {"seed": 1, "cfg": "ignored", "out_dir": str(bad_dir)},
        ],
    }
    result = adapter.parse(raw)
    assert len(result.predictions) == 1
    assert result.predictions[0]["seed"] == 0


@pytest.mark.integration
def test_run_invokes_upstream_boltz(adapter, boltz_request, tmp_path):
    """Requires the `boltz` CLI — skipped outside the container."""
    job = adapter.prepare(boltz_request, tmp_path)
    adapter.run(job)
