"""Adapter behaviour tests — all network I/O is mocked."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent


def _load_adapter_module():
    spec = importlib.util.spec_from_file_location(
        "af3_adapter", TOOL_DIR / "adapter.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def adapter_mod():
    return _load_adapter_module()


@pytest.fixture
def sample_job(tmp_path, adapter_mod):
    request = json.loads((TOOL_DIR / "tests" / "fixtures" / "request.json").read_text())
    return adapter_mod.Job(
        id="job-af3-test",
        workdir=tmp_path,
        input=request,
        params=request["params"],
    )


def _configure_legacy_https_transport(adapter):
    adapter.manifest["transport"] = {
        "type": "https",
        "endpoint": "https://api.alphafold.example/v3/run",
    }


def test_missing_token_raises(monkeypatch, adapter_mod, sample_job):
    monkeypatch.delenv("AF3_API_TOKEN", raising=False)
    adapter = adapter_mod.AlphaFold3Adapter()
    _configure_legacy_https_transport(adapter)
    with pytest.raises(adapter_mod.AdapterError, match="AF3_API_TOKEN"):
        adapter.run(sample_job)


def test_build_request_includes_ligands(adapter_mod, sample_job):
    adapter = adapter_mod.AlphaFold3Adapter()
    body = adapter._build_request(sample_job)
    assert "ligands" in body
    assert body["ligands"][0]["id"] == "ATP"
    assert body["seeds"] == [42]


def test_build_request_omits_ligands_when_absent(adapter_mod, tmp_path):
    request = {
        "chains": [{"id": "A", "sequence": "MK"}],
        "params": {"num_recycles": 1, "num_samples": 1, "num_seeds": 1},
        "seeds": [1],
    }
    job = adapter_mod.Job(
        id="j", workdir=tmp_path, input=request, params=request["params"]
    )
    adapter = adapter_mod.AlphaFold3Adapter()
    body = adapter._build_request(job)
    assert "ligands" not in body


def test_endpoint_override_env(monkeypatch, adapter_mod, sample_job):
    monkeypatch.setenv("AF3_API_TOKEN", "fake")
    monkeypatch.setenv("AF3_API_ENDPOINT", "https://override.example.com/v1/predict")

    adapter = adapter_mod.AlphaFold3Adapter()
    _configure_legacy_https_transport(adapter)

    captured = {}

    def fake_post(method, url, token, json_body=None):
        captured["url"] = url
        return {"job_id": "J1"}

    def fake_poll(endpoint, token, job_id):
        captured["poll_endpoint"] = endpoint
        sample = json.loads(
            (TOOL_DIR / "tests" / "fixtures" / "sample_output" / "prediction_0001.json").read_text()
        )
        return sample

    with mock.patch.object(adapter, "_request_with_retry", side_effect=lambda **kw: fake_post(**kw)):
        with mock.patch.object(adapter, "_poll_until_done", side_effect=lambda **kw: fake_poll(**kw)):
            with mock.patch.object(adapter, "_download_artifacts", return_value={}):
                adapter.run(sample_job)

    assert captured["url"] == "https://override.example.com/v1/predict"
    assert captured["poll_endpoint"] == "https://override.example.com/v1/predict"


def test_poll_raises_on_failed_state(monkeypatch, adapter_mod):
    adapter = adapter_mod.AlphaFold3Adapter()
    monkeypatch.setattr(adapter_mod, "POLL_INTERVAL_SEC", 0)
    with mock.patch.object(
        adapter,
        "_request_with_retry",
        return_value={"status": "failed", "error": "OOM"},
    ):
        with pytest.raises(adapter_mod.AdapterError, match="OOM"):
            adapter._poll_until_done(
                endpoint="https://x", token="t", job_id="J"
            )


def test_poll_returns_result_on_success(monkeypatch, adapter_mod):
    adapter = adapter_mod.AlphaFold3Adapter()
    monkeypatch.setattr(adapter_mod, "POLL_INTERVAL_SEC", 0)
    result_payload = {"predictions": [{"structurePath": "p.cif", "seed": 1, "metrics": {}}]}
    responses = iter([
        {"status": "running"},
        {"status": "succeeded", "result": result_payload},
    ])
    with mock.patch.object(
        adapter,
        "_request_with_retry",
        side_effect=lambda **kw: next(responses),
    ):
        got = adapter._poll_until_done(endpoint="https://x", token="t", job_id="J")
    assert got == result_payload


def test_backoff_is_monotonic_nondecreasing(adapter_mod):
    a = adapter_mod.AlphaFold3Adapter._backoff(1)
    b = adapter_mod.AlphaFold3Adapter._backoff(2)
    c = adapter_mod.AlphaFold3Adapter._backoff(3)
    # base doubles each attempt; even with jitter, attempt-3 base (4.0) > attempt-1 base+jitter (max 1.5)
    assert c > a
    assert b >= 1.0
