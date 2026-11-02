"""Core domain types for the Paper Crane Python SDK.

Mirrors `packages/tools-sdk/src/types.ts`. JSON wire format is camelCase to
stay byte-compatible with the TypeScript orchestrator; Python code uses
snake_case internally via pydantic field aliases.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------- Base config -------------------------------------------------------


class _Strict(BaseModel):
    """Base model: strict (extra='forbid'), camelCase aliases on wire."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=None,
        str_strip_whitespace=False,
    )


class _StrictAllowExtra(BaseModel):
    """Same as `_Strict` but permits extra fields (for RunMetadata)."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
    )


# ---------- Normalized request shapes ----------------------------------------


class Residue(_Strict):
    chain: str = Field(..., min_length=1, max_length=1, description="Single-letter chain id")
    resi: int = Field(..., ge=1, description="1-indexed residue number")


SolubilityMode = Literal["strict", "default"]


class DesignConstraints(_Strict):
    length_range: Optional[tuple[int, int]] = Field(default=None, alias="lengthRange")
    disulfides: Optional[bool] = None
    solubility: Optional[SolubilityMode] = None

    @field_validator("length_range")
    @classmethod
    def _check_range(cls, v: Optional[tuple[int, int]]) -> Optional[tuple[int, int]]:
        if v is None:
            return v
        lo, hi = v
        if lo < 1 or hi < lo:
            raise ValueError(f"lengthRange must be [min, max] with 1 <= min <= max, got [{lo}, {hi}]")
        return v


class DesignRequest(_Strict):
    target_pdb: str = Field(..., alias="targetPdb", min_length=1)
    target_chain: Optional[str] = Field(default=None, alias="targetChain")
    hotspots: Optional[list[Residue]] = None
    seeds: list[int]
    num_designs: int = Field(..., alias="numDesigns", gt=0)
    constraints: Optional[DesignConstraints] = None
    tool_params: Optional[dict[str, Any]] = Field(default=None, alias="toolParams")


# ---------- Result shapes -----------------------------------------------------


class Design(_Strict):
    structure_path: str = Field(..., alias="structurePath")
    sequence: str
    metrics: dict[str, float]
    seed: int


class RunMetadata(_StrictAllowExtra):
    """Open-ended metadata; matches the TS index-signature shape."""

    tool: str
    adapter_version: Optional[str] = Field(default=None, alias="adapterVersion")
    stages: Optional[list[str]] = None


class DesignResult(_Strict):
    designs: list[Design]
    run_metadata: RunMetadata = Field(..., alias="runMetadata")


# ---------- Runtime shapes ----------------------------------------------------


class PreparedStage(_Strict):
    tool_id: str = Field(..., alias="toolId")
    request_path: str = Field(..., alias="requestPath")
    inputs_dir: str = Field(..., alias="inputsDir")
    outputs_dir: str = Field(..., alias="outputsDir")
    tool_artifacts: dict[str, Any] = Field(default_factory=dict, alias="toolArtifacts")


class PreparedJob(_Strict):
    workdir: str
    inputs_dir: str = Field(..., alias="inputsDir")
    outputs_dir: str = Field(..., alias="outputsDir")
    request_path: str = Field(..., alias="requestPath")
    target_path: str = Field(..., alias="targetPath")
    tool_artifacts: dict[str, Any] = Field(default_factory=dict, alias="toolArtifacts")
    stages: Optional[list[PreparedStage]] = None


class RawOutput(_StrictAllowExtra):
    output_dir: str = Field(..., alias="outputDir")
    exit_code: int = Field(..., alias="exitCode")
    stdout: str = ""
    stderr: str = ""


# ---------- Validation --------------------------------------------------------


class ValidationError(_Strict):
    field: str
    message: str


# ---------- Manifest shapes ---------------------------------------------------

ToolTier = Literal["open", "open-weights", "frontier"]
ToolCategory = Literal[
    "backbone",
    "backbone_generation",
    "sequence",
    "sequence_design",
    "binder_design",
    "structure",
    "structure_prediction",
    "embed",
    "embedding_scoring",
    "generative",
    "composite",
    "other",
]


class ToolComputeProfile(_Strict):
    gpu: str = Field(..., min_length=1)
    gpu_count: int = Field(..., alias="gpuCount", ge=0)
    cpu_cores: int = Field(..., alias="cpuCores", ge=1)
    memory_gb: float = Field(..., alias="memoryGb", gt=0)
    est_seconds_per_design: float = Field(..., alias="estSecondsPerDesign", gt=0)
    note: Optional[str] = None


class HttpsToolTransport(_Strict):
    type: Literal["https"]
    endpoint: str = Field(..., pattern=r"^https?://")


class ModalToolTransport(_Strict):
    type: Literal["modal"]
    app: str = Field(..., min_length=1)
    function: str = Field(..., min_length=1)


ToolTransport = Annotated[
    Union[HttpsToolTransport, ModalToolTransport],
    Field(discriminator="type"),
]


class ToolManifest(_Strict):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        alias_generator=None,
        str_strip_whitespace=False,
    )

    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(..., alias="displayName", min_length=1)
    version: str = Field(..., min_length=1)
    adapter_version: str = Field(..., alias="adapterVersion", min_length=1)
    category: ToolCategory
    tier: ToolTier
    license_gate: Optional[bool] = Field(default=None, alias="licenseGate")
    license: str = Field(..., min_length=1)
    image: str = Field(..., min_length=1)
    image_digest: str = Field(
        ...,
        alias="imageDigest",
        pattern=r"^sha256:[a-f0-9]{64}$",
        description='must be "sha256:<64 hex chars>"',
    )
    compute: ToolComputeProfile
    input_schema: Optional[str] = Field(default=None, alias="inputSchema")
    output_schema: Optional[str] = Field(default=None, alias="outputSchema")
    default_params: Optional[dict[str, Any]] = Field(default=None, alias="defaultParams")
    composes: Optional[list[str]] = None
    transport: Optional[ToolTransport] = None


__all__ = [
    "Residue",
    "DesignConstraints",
    "DesignRequest",
    "Design",
    "RunMetadata",
    "DesignResult",
    "PreparedStage",
    "PreparedJob",
    "RawOutput",
    "ValidationError",
    "ToolTier",
    "ToolCategory",
    "ToolComputeProfile",
    "HttpsToolTransport",
    "ModalToolTransport",
    "ToolTransport",
    "ToolManifest",
    "SolubilityMode",
]
