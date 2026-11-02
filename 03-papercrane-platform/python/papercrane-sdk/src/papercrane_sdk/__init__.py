"""papercrane_sdk — Python SDK for Paper Crane tool adapters.

Public API mirrors the TypeScript `@papercrane/tools-sdk` contract. Tool
containers import from here to wire their CLI entrypoint into the Paper Crane
orchestrator.
"""
from __future__ import annotations

from .adapter import Adapter
from .cli import run_cli
from .manifest import load_manifest
from .remote import RemoteAdapter
from .types import (
    Design,
    DesignConstraints,
    DesignRequest,
    DesignResult,
    PreparedJob,
    PreparedStage,
    RawOutput,
    Residue,
    RunMetadata,
    ToolCategory,
    ToolComputeProfile,
    ToolManifest,
    ToolTier,
    ToolTransport,
    ValidationError,
)
from .validation import validate_request

__version__ = "0.1.0"

__all__ = [
    # Base classes
    "Adapter",
    "RemoteAdapter",
    # Request / response models
    "DesignRequest",
    "DesignResult",
    "Design",
    "Residue",
    "DesignConstraints",
    "RunMetadata",
    # Manifest
    "ToolManifest",
    "ToolCategory",
    "ToolTier",
    "ToolComputeProfile",
    "ToolTransport",
    "load_manifest",
    # Runtime
    "PreparedJob",
    "PreparedStage",
    "RawOutput",
    # Validation
    "ValidationError",
    "validate_request",
    # CLI
    "run_cli",
    # Metadata
    "__version__",
]
