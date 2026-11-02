"""Adapter abstract base class.

Mirrors `packages/tools-sdk/src/adapter.ts`. Concrete adapters subclass this
and implement `prepare/run/parse`. The default `validate()` delegates to the
SDK-wide rules; subclasses may override to layer tool-specific checks on top.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .types import DesignRequest, DesignResult, ToolManifest, ValidationError
from .validation import validate_request


class Adapter(ABC):
    """Base class for every local-container tool wrapped by Paper Crane.

    For closed-weight HTTPS-backed tools, subclass `RemoteAdapter` instead.
    """

    #: Tool manifest — must be set by the subclass (class attribute).
    manifest: ToolManifest

    def validate(self, req: DesignRequest) -> list[ValidationError]:
        """Return a list of validation errors (empty = valid).

        Subclasses may override this to layer tool-specific rules. Prefer
        calling `super().validate(req)` first and extending the result.
        """
        return validate_request(req)

    @abstractmethod
    def prepare(self, req: DesignRequest, workdir: Path) -> Any:
        """Stage inputs on disk and materialize tool-specific config.

        MUST be pure: no container spawn, no network. Return a ``job`` dict
        (or any object) that ``run()`` consumes.
        """

    @abstractmethod
    def run(self, job: Any) -> Any:
        """Execute the tool and return raw outputs.

        For container tools this typically shells out to the tool binary
        inside the same container. For remote tools (see ``RemoteAdapter``)
        this makes the HTTPS call.
        """

    @abstractmethod
    def parse(self, raw: Any) -> DesignResult:
        """Normalize tool-native outputs into a `DesignResult`."""


__all__ = ["Adapter"]
