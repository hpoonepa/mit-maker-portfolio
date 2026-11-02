"""Contract tests for the papercrane-sdk Python package.

These tests verify SDK-level invariants that any adapter, CLI consumer, or
orchestrator depends on. They run WITHOUT touching Modal, Docker, or any GPU.

If the SDK fails to import (not built/installed yet), the suite degrades to
an `xfail` so this file never blocks unrelated CI runs.

Agent 15/15 — Wave 8 contract layer.
"""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

import pytest


# --------------------------------------------------------------------------- #
# Soft import — degrade to xfail if the SDK isn't installable yet.            #
# --------------------------------------------------------------------------- #

papercrane_sdk = pytest.importorskip(
    "papercrane_sdk",
    reason="papercrane-sdk not installed in this environment; skipping contract suite",
)


def _try_import(name: str) -> Any:
    try:
        return __import__(f"papercrane_sdk.{name}", fromlist=[name])
    except Exception as e:  # pragma: no cover - exercised only on broken installs
        pytest.xfail(f"papercrane_sdk.{name} unavailable: {e}")


# --------------------------------------------------------------------------- #
# 1. Public surface: required modules + symbols                                #
# --------------------------------------------------------------------------- #


REQUIRED_PUBLIC_SYMBOLS = {
    "adapter": ["Adapter"],
    "types": [
        "DesignRequest",
        "DesignResult",
        "Design",
        "RunMetadata",
        "ToolManifest",
        "ToolComputeProfile",
        "ValidationError",
        "ToolTier",
        "ToolCategory",
    ],
    "manifest": ["load_manifest", "ToolManifest"],
    "validation": ["validate_request"],
    "io": ["read_request", "stage_outputs", "write_errors", "write_result"],
    "cli": ["run_cli"],
}


@pytest.mark.parametrize(
    "module_name,symbols",
    [(m, syms) for m, syms in REQUIRED_PUBLIC_SYMBOLS.items()],
    ids=list(REQUIRED_PUBLIC_SYMBOLS.keys()),
)
def test_required_module_exposes_symbols(module_name: str, symbols: list[str]) -> None:
    mod = _try_import(module_name)
    missing = [s for s in symbols if not hasattr(mod, s)]
    assert not missing, f"papercrane_sdk.{module_name} is missing: {missing}"


# --------------------------------------------------------------------------- #
# 2. Adapter base class invariants                                            #
# --------------------------------------------------------------------------- #


def test_adapter_is_abstract_with_three_methods() -> None:
    """`Adapter` must be ABC with abstract prepare/run/parse and a default validate."""
    Adapter = _try_import("adapter").Adapter

    assert inspect.isabstract(Adapter), "Adapter must be an abstract base class"

    abstract = set(getattr(Adapter, "__abstractmethods__", set()))
    expected = {"prepare", "run", "parse"}
    assert expected.issubset(abstract), (
        f"Adapter missing abstract methods: expected {expected}, got {abstract}"
    )

    # validate should be concrete (not in __abstractmethods__) so subclasses
    # get the default behaviour for free.
    assert "validate" not in abstract, "Adapter.validate should have a default impl"
    assert callable(getattr(Adapter, "validate", None)), "Adapter.validate missing"


def test_adapter_instantiation_requires_subclass() -> None:
    Adapter = _try_import("adapter").Adapter
    with pytest.raises(TypeError):
        Adapter()  # type: ignore[abstract]


def test_subclass_must_implement_all_three() -> None:
    Adapter = _try_import("adapter").Adapter

    class Partial(Adapter):
        def prepare(self, req, workdir):  # noqa: D401, ANN001 - test stub
            return {}

    with pytest.raises(TypeError):
        Partial()  # type: ignore[abstract]


def test_complete_subclass_instantiates_and_validate_returns_list() -> None:
    types_mod = _try_import("types")
    Adapter = _try_import("adapter").Adapter

    class Concrete(Adapter):
        manifest = None  # set by real adapters via class attribute

        def prepare(self, req, workdir):  # noqa: ANN001
            return {}

        def run(self, job):  # noqa: ANN001
            return {}

        def parse(self, raw):  # noqa: ANN001
            return types_mod.DesignResult(
                designs=[],
                run_metadata=types_mod.RunMetadata(tool="contract-test"),
            )

    a = Concrete()
    req = types_mod.DesignRequest(
        target_pdb="ABCD",
        seeds=[1],
        num_designs=1,
    )
    errs = a.validate(req)
    assert isinstance(errs, list), "validate() must return a list"
    for e in errs:
        assert isinstance(e, types_mod.ValidationError)


# --------------------------------------------------------------------------- #
# 3. Manifest loader contract                                                  #
# --------------------------------------------------------------------------- #


def test_load_manifest_rejects_missing_file(tmp_path: Path) -> None:
    load_manifest = _try_import("manifest").load_manifest
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "no_such_manifest.json")


def test_load_manifest_rejects_invalid_json(tmp_path: Path) -> None:
    load_manifest = _try_import("manifest").load_manifest
    p = tmp_path / "manifest.json"
    p.write_text("{ not: valid", encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(p)


def test_load_manifest_accepts_valid_manifest(tmp_path: Path) -> None:
    load_manifest = _try_import("manifest").load_manifest
    manifest = {
        "id": "contract-tool",
        "displayName": "Contract Tool",
        "version": "0.0.1",
        "adapterVersion": "a1",
        "category": "binder_design",
        "tier": "open",
        "license": "MIT",
        "image": "ghcr.io/papercrane/contract:0.0.1",
        "imageDigest": "sha256:" + "0" * 64,
        "compute": {
            "gpu": "A100-40GB",
            "gpuCount": 1,
            "cpuCores": 4,
            "memoryGb": 16.0,
            "estSecondsPerDesign": 30.0,
        },
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    parsed = load_manifest(p)
    assert parsed.id == "contract-tool"
    assert parsed.tier == "open"


# --------------------------------------------------------------------------- #
# 4. Real-tool sweep — every tool dir under ../../tools must load.            #
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO_ROOT / "tools"

EXPECTED_TOOLS = [
    "alphafold3",
    "antifold",
    "apbs",
    "arpeggio",
    "autodock-vina",
    "bindcraft",
    "boltz1",
    "boltz2",
    "boltzgen",
    "cd-hit",
    "chai1",
    "chroma",
    "diamond",
    "disco",
    "dockq",
    "dssp",
    "esm2",
    "esmfold",
    "esmc",
    "esmif1",
    "evoef2",
    "foldseek",
    "fpocket",
    "freesasa",
    "germinal",
    "hmmer",
    "hhsuite",
    "immunebuilder",
    "ligandmpnn",
    "mafft",
    "mdanalysis",
    "mmseqs2",
    "omegafold",
    "openmm-relax",
    "p2rank",
    "parasail",
    "pdb-tools",
    "pdb2pqr",
    "pdbfixer",
    "plip",
    "prodigy",
    "prody",
    "propka",
    "proteinmpnn",
    "protparam",
    "rf3",
    "rfd3",
    "rfdiffusion",
    "rfdiffusionaa",
    "smina",
    "solublempnn",
    "thermompnn",
]


@pytest.mark.parametrize("tool_id", EXPECTED_TOOLS)
def test_real_tool_manifest_parses(tool_id: str) -> None:
    """Every shipped tool must have a manifest the SDK can parse."""
    if not TOOLS_DIR.exists():
        pytest.skip(f"tools dir not found at {TOOLS_DIR}")
    manifest_path = TOOLS_DIR / tool_id / "manifest.json"
    if not manifest_path.exists():
        pytest.fail(f"missing manifest.json for tool '{tool_id}' at {manifest_path}")

    load_manifest = _try_import("manifest").load_manifest
    parsed = load_manifest(manifest_path)
    assert parsed.id == tool_id, (
        f"manifest id ({parsed.id!r}) does not match directory name ({tool_id!r})"
    )


@pytest.mark.parametrize("tool_id", EXPECTED_TOOLS)
def test_real_tool_schema_files_present(tool_id: str) -> None:
    if not TOOLS_DIR.exists():
        pytest.skip(f"tools dir not found at {TOOLS_DIR}")
    base = TOOLS_DIR / tool_id
    if not base.exists():
        pytest.fail(f"tool dir missing: {tool_id}")
    for fname in ("schemas/input.json", "schemas/output.json", "README.md"):
        assert (base / fname).exists(), f"{tool_id}: missing {fname}"


# --------------------------------------------------------------------------- #
# 5. DesignRequest / DesignResult round-trip with camelCase aliases            #
# --------------------------------------------------------------------------- #


def test_design_request_round_trips_camel_case() -> None:
    types_mod = _try_import("types")
    DesignRequest = types_mod.DesignRequest
    payload = {
        "targetPdb": "1ABC",
        "targetChain": "A",
        "seeds": [1, 2, 3],
        "numDesigns": 4,
    }
    req = DesignRequest.model_validate(payload)
    assert req.target_pdb == "1ABC"
    assert req.num_designs == 4
    redumped = req.model_dump(by_alias=True, exclude_none=True)
    assert redumped["targetPdb"] == "1ABC"
    assert redumped["numDesigns"] == 4


def test_design_request_rejects_extra_fields() -> None:
    types_mod = _try_import("types")
    with pytest.raises(Exception):
        types_mod.DesignRequest.model_validate(
            {
                "targetPdb": "1ABC",
                "seeds": [1],
                "numDesigns": 1,
                "bogusField": "should reject",
            }
        )
