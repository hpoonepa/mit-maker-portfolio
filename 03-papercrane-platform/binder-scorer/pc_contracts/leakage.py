"""Leakage guard — prevents experimental outcomes from becoming model inputs."""
from typing import Iterable

EXPERIMENTAL_PREFIX = "experimental__"

KNOWN_EXPERIMENTAL_COLUMNS: frozenset[str] = frozenset({
    "experimental__binding",
    "experimental__expressed",
    "experimental__expression_yield",
    "experimental__kd",
    "experimental__koff",
    "experimental__kon",
})


class LeakageError(Exception):
    """Raised when a column that encodes an experimental outcome is found
    in a dataset that should contain only computational features."""


def assert_no_leakage(columns: Iterable[str]) -> None:
    """Raise :class:`LeakageError` if any column would leak experimental labels.

    A column is considered leaky if it:
    - starts with ``experimental__``, OR
    - is in :data:`KNOWN_EXPERIMENTAL_COLUMNS`.

    Returns ``None`` when the column set is clean.
    """
    for col in columns:
        # The `in` check is currently redundant with the prefix check (every
        # known column is prefixed), but KNOWN_EXPERIMENTAL_COLUMNS may hold
        # non-prefixed legacy names in the future — keep it as a safety net.
        if col.startswith(EXPERIMENTAL_PREFIX) or col in KNOWN_EXPERIMENTAL_COLUMNS:
            raise LeakageError(
                f"Experimental column detected — this would leak labels into "
                f"model inputs: {col!r}"
            )
