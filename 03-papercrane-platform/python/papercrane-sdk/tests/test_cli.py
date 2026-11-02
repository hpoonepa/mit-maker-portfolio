"""CLI tests — run_cli parses request, invokes adapter, writes result/errors."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from papercrane_sdk.adapter import Adapter
from papercrane_sdk.cli import run_cli
from papercrane_sdk.types import DesignResult, ToolManifest, ValidationError

FIXTURES = Path(__file__).parent / "fixtures"


def _manifest() -> ToolManifest:
    return ToolManifest.model_validate(json.loads((FIXTURES / "manifest.json").read_text()))


class _StubAdapter(Adapter):
    manifest = _manifest()

    def prepare(self, req, workdir):
        return {"cfg": str(workdir / "cfg.json"), "seeds": req.seeds}

    def run(self, job):
        return {"exitCode": 0, "outputDir": "/outputs/designs", "seeds": job["seeds"]}

    def parse(self, raw):
        return DesignResult.model_validate(
            {
                "designs": [
                    {
                        "structurePath": "/outputs/designs/d0.pdb",
                        "sequence": "MKT",
                        "metrics": {"iptm": 0.8, "plddt": 90.0},
                        "seed": int(raw["seeds"][0]),
                    }
                ],
                "runMetadata": {"tool": "bindcraft", "adapterVersion": "a1"},
            }
        )


class _FailingValidationAdapter(_StubAdapter):
    def validate(self, req):
        return [ValidationError(field="seeds", message="must be non-empty")]


def _setup_io(tmp_path: Path) -> tuple[Path, Path, Path]:
    req_path = tmp_path / "request.json"
    target_path = tmp_path / "target.pdb"
    out_path = tmp_path / "outputs"
    shutil.copy(FIXTURES / "request.json", req_path)
    target_path.write_text("ATOM ...\n")
    out_path.mkdir()
    return req_path, target_path, out_path


def test_run_cli_happy_path(tmp_path: Path):
    req_path, target_path, out_path = _setup_io(tmp_path)
    rc = run_cli(
        _StubAdapter,
        argv=["--request", str(req_path), "--target", str(target_path), "--output", str(out_path)],
    )
    assert rc == 0
    result_file = out_path / "result.json"
    assert result_file.exists()
    data = json.loads(result_file.read_text())
    assert "designs" in data
    assert "runMetadata" in data
    assert data["runMetadata"]["tool"] == "bindcraft"
    assert data["designs"][0]["seed"] == 1
    assert data["designs"][0]["structurePath"] == "/outputs/designs/d0.pdb"
    # no errors.json on success
    assert not (out_path / "errors.json").exists()


def test_run_cli_writes_errors_and_returns_2_on_validation_fail(tmp_path: Path):
    req_path, target_path, out_path = _setup_io(tmp_path)
    rc = run_cli(
        _FailingValidationAdapter,
        argv=["--request", str(req_path), "--target", str(target_path), "--output", str(out_path)],
    )
    assert rc == 2
    errors_file = out_path / "errors.json"
    assert errors_file.exists()
    data = json.loads(errors_file.read_text())
    assert "errors" in data
    assert data["errors"][0]["field"] == "seeds"
    # result.json should NOT be written on validation failure
    assert not (out_path / "result.json").exists()


def test_run_cli_requires_request_arg(tmp_path: Path):
    with pytest.raises(SystemExit):
        run_cli(_StubAdapter, argv=[])


def test_run_cli_creates_output_dir(tmp_path: Path):
    req_path = tmp_path / "request.json"
    target_path = tmp_path / "target.pdb"
    out_path = tmp_path / "does_not_exist_yet"
    shutil.copy(FIXTURES / "request.json", req_path)
    target_path.write_text("ATOM\n")

    rc = run_cli(
        _StubAdapter,
        argv=["--request", str(req_path), "--target", str(target_path), "--output", str(out_path)],
    )
    assert rc == 0
    assert (out_path / "result.json").exists()
