"""Explicit local model-execution gate; not a provider billing control."""

from dataclasses import dataclass


class ComputeDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionPolicy:
    allow_model_execution: bool = False

    def require_model_execution(self, action: str) -> None:
        if not self.allow_model_execution:
            raise ComputeDisabled(
                f"{action} is disabled. This build session permits planning and local contract checks only. "
                "After explicit user authorization, use a separate model-execution session."
            )
