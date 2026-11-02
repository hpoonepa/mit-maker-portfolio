"""Adapter base class tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from papercrane_sdk.adapter import Adapter
from papercrane_sdk.remote import RemoteAdapter
from papercrane_sdk.types import DesignRequest, ToolManifest

FIXTURES = Path(__file__).parent / "fixtures"


def _manifest() -> ToolManifest:
    return ToolManifest.model_validate(json.loads((FIXTURES / "manifest.json").read_text()))


def test_adapter_is_abstract():
    with pytest.raises(TypeError):
        Adapter()  # type: ignore[abstract]


def test_adapter_subclass_must_implement_all():
    # Subclass that only implements prepare is still abstract
    class HalfAdapter(Adapter):
        manifest = _manifest()

        def prepare(self, req, workdir):
            return {}

    with pytest.raises(TypeError):
        HalfAdapter()  # type: ignore[abstract]


def test_adapter_subclass_concrete_ok():
    class OkAdapter(Adapter):
        manifest = _manifest()

        def prepare(self, req, workdir):
            return {"workdir": str(workdir)}

        def run(self, job):
            return {"exitCode": 0, "outputDir": "/tmp"}

        def parse(self, raw):
            return {"designs": [], "runMetadata": {"tool": "bindcraft"}}

    adapter = OkAdapter()
    assert adapter.manifest.id == "bindcraft"


def test_default_validate_returns_list():
    class OkAdapter(Adapter):
        manifest = _manifest()

        def prepare(self, req, workdir):
            return {}

        def run(self, job):
            return {}

        def parse(self, raw):
            return {}

    adapter = OkAdapter()
    req = DesignRequest(target_pdb="s3://x.pdb", seeds=[1], num_designs=1)
    errors = adapter.validate(req)
    assert errors == []


def test_default_validate_catches_empty_seeds():
    class OkAdapter(Adapter):
        manifest = _manifest()

        def prepare(self, req, workdir):
            return {}

        def run(self, job):
            return {}

        def parse(self, raw):
            return {}

    adapter = OkAdapter()
    # bypass pydantic's own check to exercise the SDK validator
    req = DesignRequest.model_construct(target_pdb="s3://x.pdb", seeds=[], num_designs=1)
    errors = adapter.validate(req)
    fields = [e.field for e in errors]
    assert "seeds" in fields


def test_remote_adapter_requires_endpoint():
    class RA(RemoteAdapter):
        manifest = _manifest()

        def prepare(self, req, workdir):
            return {}

        def run(self, job):
            return {}

        def parse(self, raw):
            return {}

    with pytest.raises(ValueError):
        RA(endpoint="")


def test_remote_adapter_sets_auth_headers():
    class RA(RemoteAdapter):
        manifest = _manifest()

        def prepare(self, req, workdir):
            return {}

        def run(self, job):
            return {}

        def parse(self, raw):
            return {}

    ra = RA(endpoint="https://api.example.com/v1/run", api_key="secret-key")
    assert ra.endpoint == "https://api.example.com/v1/run"
    assert ra._headers["authorization"] == "Bearer secret-key"
    assert ra._headers["content-type"] == "application/json"


def test_remote_adapter_post_json_uses_injected_client():
    captured = {}

    def fake_post(url, payload, headers, timeout_ms):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = dict(headers)
        captured["timeout_ms"] = timeout_ms
        return {"status": 200, "data": {"ok": True}}

    class RA(RemoteAdapter):
        manifest = _manifest()

        def prepare(self, req, workdir):
            return {}

        def run(self, job):
            return self.post_json("/predict", {"hello": "world"})

        def parse(self, raw):
            return {}

    ra = RA(endpoint="https://api.example.com", api_key="k", http_post=fake_post)
    resp = ra.run({})
    assert resp == {"status": 200, "data": {"ok": True}}
    assert captured["url"] == "https://api.example.com/predict"
    assert captured["payload"] == {"hello": "world"}
    assert captured["headers"]["authorization"] == "Bearer k"
