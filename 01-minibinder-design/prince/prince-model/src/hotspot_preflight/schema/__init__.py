# SPDX-License-Identifier: MIT
"""The published JSON Schema for the run record.

Kept as a data file rather than a Python dict so that it can be handed to a
reviewer, a CI job or a tool in another language without importing this package.
Loaded through :mod:`importlib.resources` so it resolves identically whether the
package is installed or run from a source checkout.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

__all__ = ["SCHEMA_FILENAME", "load_schema", "schema_text"]

SCHEMA_FILENAME = "run_record.schema.json"


def schema_text() -> str:
    """The schema document verbatim, for writing out or diffing."""
    return (
        files(__package__).joinpath(SCHEMA_FILENAME).read_text(encoding="utf-8")
    )


def load_schema() -> dict[str, Any]:
    """The schema parsed into a dict, ready for a validator."""
    return json.loads(schema_text())
