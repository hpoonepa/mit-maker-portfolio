"""Default request validator shared by every `Adapter`.

Mirrors `packages/tools-sdk/src/validation.ts`. Subclasses of `Adapter` may
override `validate()` to add tool-specific rules, but should still call this
first (or call `validate_request(req)`).
"""
from __future__ import annotations

from typing import Any

from .types import DesignRequest, ValidationError

UINT32_MAX = 0xFFFFFFFF


def validate_request(req: DesignRequest | Any) -> list[ValidationError]:
    """Return a list of validation errors (empty = valid).

    Accepts a `DesignRequest` instance (including `model_construct`-bypassed
    ones) so the SDK can defend against invalid inputs even when pydantic was
    skipped upstream.
    """
    errors: list[ValidationError] = []

    target_pdb = getattr(req, "target_pdb", None)
    if not isinstance(target_pdb, str) or target_pdb.strip() == "":
        errors.append(ValidationError(field="targetPdb", message="targetPdb is required"))

    seeds = getattr(req, "seeds", None)
    if not isinstance(seeds, list) or len(seeds) == 0:
        errors.append(ValidationError(field="seeds", message="seeds must be a non-empty array"))
    else:
        for idx, s in enumerate(seeds):
            if not isinstance(s, int) or isinstance(s, bool) or s < 0 or s > UINT32_MAX:
                errors.append(
                    ValidationError(
                        field="seeds",
                        message=f"seeds[{idx}] ({s}) must be an integer in [0, 2^32)",
                    )
                )

    num_designs = getattr(req, "num_designs", None)
    if not isinstance(num_designs, int) or isinstance(num_designs, bool) or num_designs <= 0:
        errors.append(
            ValidationError(field="numDesigns", message="numDesigns must be a positive integer")
        )

    hotspots = getattr(req, "hotspots", None)
    if hotspots is not None:
        if not isinstance(hotspots, list):
            errors.append(ValidationError(field="hotspots", message="hotspots must be an array"))
        else:
            for idx, h in enumerate(hotspots):
                chain = getattr(h, "chain", None)
                resi = getattr(h, "resi", None)
                if not isinstance(chain, str) or len(chain) != 1:
                    errors.append(
                        ValidationError(
                            field=f"hotspots[{idx}].chain",
                            message="chain must be a single-letter string",
                        )
                    )
                if not isinstance(resi, int) or isinstance(resi, bool) or resi < 1:
                    errors.append(
                        ValidationError(
                            field=f"hotspots[{idx}].resi",
                            message="resi must be a positive integer",
                        )
                    )

    constraints = getattr(req, "constraints", None)
    length_range = getattr(constraints, "length_range", None) if constraints else None
    if length_range is not None:
        try:
            lo, hi = length_range
        except (TypeError, ValueError):
            errors.append(
                ValidationError(
                    field="constraints.lengthRange",
                    message=f"lengthRange must be [min, max], got {length_range!r}",
                )
            )
        else:
            if (
                not isinstance(lo, int)
                or not isinstance(hi, int)
                or isinstance(lo, bool)
                or isinstance(hi, bool)
                or lo < 1
                or hi < lo
            ):
                errors.append(
                    ValidationError(
                        field="constraints.lengthRange",
                        message=f"lengthRange must be [min, max] with 1 <= min <= max, got [{lo}, {hi}]",
                    )
                )

    return errors


__all__ = ["validate_request"]
