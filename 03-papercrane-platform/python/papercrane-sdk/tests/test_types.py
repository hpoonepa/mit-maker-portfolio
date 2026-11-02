"""Pydantic round-trip tests: JSON wire format must match TypeScript camelCase."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from papercrane_sdk.types import (
    Design,
    DesignConstraints,
    DesignRequest,
    DesignResult,
    Residue,
    RunMetadata,
    ValidationError,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_residue_round_trip():
    r = Residue(chain="A", resi=42)
    data = r.model_dump(by_alias=True)
    assert data == {"chain": "A", "resi": 42}
    assert Residue.model_validate(data) == r


def test_design_constraints_camelcase_alias():
    # snake_case internal, camelCase wire (check via JSON for list shape)
    c = DesignConstraints(length_range=(60, 150), disulfides=False, solubility="strict")
    wire = json.loads(c.model_dump_json(by_alias=True, exclude_none=True))
    assert wire == {"lengthRange": [60, 150], "disulfides": False, "solubility": "strict"}
    # parse back from camelCase
    c2 = DesignConstraints.model_validate({"lengthRange": [60, 150]})
    assert c2.length_range == (60, 150)


def test_design_request_from_fixture():
    raw = json.loads((FIXTURES / "request.json").read_text())
    req = DesignRequest.model_validate(raw)
    assert req.target_pdb == "s3://papercrane-dev/targets/2lgv.pdb"
    assert req.target_chain == "A"
    assert req.num_designs == 6
    assert req.seeds == [1, 2, 3]
    assert req.hotspots is not None
    assert req.hotspots[0].chain == "A"
    assert req.hotspots[0].resi == 42
    assert req.constraints is not None
    assert req.constraints.length_range == (60, 120)
    assert req.tool_params == {"extra_knob": "value"}


def test_design_request_serializes_to_camelcase():
    req = DesignRequest(
        target_pdb="s3://x/t.pdb",
        seeds=[7],
        num_designs=1,
        target_chain="A",
    )
    wire = req.model_dump(by_alias=True, exclude_none=True)
    assert "targetPdb" in wire
    assert "targetChain" in wire
    assert "numDesigns" in wire
    assert "target_pdb" not in wire


def test_design_request_extra_forbidden():
    with pytest.raises(PydanticValidationError):
        DesignRequest.model_validate(
            {
                "targetPdb": "x",
                "seeds": [1],
                "numDesigns": 1,
                "unknownField": "oops",
            }
        )


def test_design_request_minimal():
    req = DesignRequest(target_pdb="x", seeds=[0], num_designs=1)
    assert req.hotspots is None
    assert req.constraints is None


def test_design_and_result_round_trip():
    d = Design(
        structure_path="/outputs/designs/d1.pdb",
        sequence="MKTLLL",
        metrics={"iptm": 0.82, "plddt": 91.3},
        seed=1,
    )
    wire = d.model_dump(by_alias=True)
    assert wire["structurePath"] == "/outputs/designs/d1.pdb"
    assert wire["sequence"] == "MKTLLL"
    d2 = Design.model_validate(wire)
    assert d2 == d

    result = DesignResult(
        designs=[d],
        run_metadata=RunMetadata(tool="bindcraft", adapter_version="a1"),
    )
    wire_r = result.model_dump(by_alias=True, exclude_none=True)
    assert "runMetadata" in wire_r
    assert wire_r["runMetadata"]["tool"] == "bindcraft"
    assert wire_r["runMetadata"]["adapterVersion"] == "a1"


def test_run_metadata_allows_extra():
    # RunMetadata in the TS types has an index signature — extras allowed
    m = RunMetadata.model_validate(
        {"tool": "bindcraft", "adapterVersion": "a1", "imageDigest": "sha256:abc", "customField": 123}
    )
    wire = m.model_dump(by_alias=True, exclude_none=True)
    assert wire["tool"] == "bindcraft"
    assert wire["imageDigest"] == "sha256:abc"
    assert wire["customField"] == 123


def test_validation_error_shape():
    err = ValidationError(field="seeds", message="must be non-empty")
    assert err.model_dump() == {"field": "seeds", "message": "must be non-empty"}


def test_design_constraints_solubility_enum():
    with pytest.raises(PydanticValidationError):
        DesignConstraints.model_validate({"solubility": "invalid"})
