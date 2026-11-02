"""Reservation ledger for future jobs. This does NOT enforce cloud billing."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .io import atomic_write_json, read_json

DEFAULT_ALLOCATIONS = {
    "smoke": "25.00",
    "cached_features": "65.00",
    "training_development": "50.00",
    "frozen_evaluation": "35.00",
    "contingency": "25.00",
}


def money(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Invalid monetary amount") from error
    if not result.is_finite() or result < 0:
        raise ValueError("Money must be finite and nonnegative")
    return result


class BudgetLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def _locked(self):
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def initialize(self, allocations: dict[str, str] | None = None) -> dict:
        allocations = allocations if allocations is not None else DEFAULT_ALLOCATIONS
        if not allocations or any(money(value) <= 0 for value in allocations.values()):
            raise ValueError("Budget allocations must be positive")
        with self._locked():
            if self.path.exists():
                raise FileExistsError(self.path)
            state = {
                "schema_version": "1",
                "currency": "USD",
                "spend_authorized": False,
                "allocations": {key: str(money(value)) for key, value in allocations.items()},
                "jobs": {},
                "note": "Accounting only; provider timeout, authorization and shutdown are separate.",
            }
            atomic_write_json(self.path, state)
            return state

    @staticmethod
    def summary(state: dict) -> dict:
        result = {}
        for stage, cap in state["allocations"].items():
            jobs = [job for job in state["jobs"].values() if job["stage"] == stage]
            actual = sum((money(j["actual_usd"]) for j in jobs if j["status"] == "settled"), Decimal(0))
            reserved = sum((money(j["maximum_usd"]) for j in jobs if j["status"] == "reserved"), Decimal(0))
            result[stage] = {
                "cap": str(money(cap)),
                "actual": str(actual),
                "reserved": str(reserved),
                "remaining": str(money(cap) - actual - reserved),
                "over_cap": actual + reserved > money(cap),
            }
        return {
            "stages": result,
            "over_cap": any(row["over_cap"] for row in result.values()),
            "total_cap_usd": str(sum((money(x) for x in state["allocations"].values()), Decimal(0))),
            "cloud_billing_enforced": False,
        }

    def reserve(self, job_id: str, stage: str, maximum_usd, *, input_sha256: str) -> dict:
        from .schema import require_hash, require_text

        require_text(job_id, "job_id")
        require_hash(input_sha256, "job input_sha256")
        maximum = money(maximum_usd)
        if maximum == 0:
            raise ValueError("Reserve a conservative positive maximum")
        with self._locked():
            state = read_json(self.path)
            if stage not in state["allocations"]:
                raise ValueError("Unknown budget stage")
            existing = state["jobs"].get(job_id)
            if existing:
                if (
                    existing["stage"] != stage
                    or money(existing["maximum_usd"]) != maximum
                    or existing["input_sha256"] != input_sha256
                ):
                    raise ValueError("Job ID reused with different inputs or reservation")
                return existing  # idempotent, including already settled jobs
            summary = self.summary(state)
            if summary["over_cap"] or maximum > Decimal(summary["stages"][stage]["remaining"]):
                raise ValueError("Reservation would breach an allocation; evaluation reserve is unavailable")
            job = {
                "stage": stage,
                "maximum_usd": str(maximum),
                "input_sha256": input_sha256,
                "status": "reserved",
            }
            state["jobs"][job_id] = job
            atomic_write_json(self.path, state)
            return job

    def settle(self, job_id: str, actual_usd, *, receipt_sha256: str) -> dict:
        from .schema import require_hash

        require_hash(receipt_sha256, "billing receipt_sha256")
        actual = money(actual_usd)
        with self._locked():
            state = read_json(self.path)
            job = state["jobs"][job_id]
            if job["status"] == "settled":
                if money(job["actual_usd"]) != actual or job["receipt_sha256"] != receipt_sha256:
                    raise ValueError("Settled job requires an explicit accounting amendment")
                return job
            job.update(
                status="settled",
                actual_usd=str(actual),
                receipt_sha256=receipt_sha256,
                exceeded_reservation=actual > money(job["maximum_usd"]),
            )
            # Always record real spend, even above the reservation. Never hide it
            # by rejecting the receipt; summary blocks subsequent reservations.
            atomic_write_json(self.path, state)
            return job


def project_cost(
    profiles: list[dict],
    cohort_counts: dict[str, int],
    *,
    hourly_usd,
    fixed_usd="0",
    failure_multiplier: float = 1.5,
) -> dict:
    """Use measured end-to-end seconds in each length stratum; no assumed rates."""
    import math

    if not math.isfinite(failure_multiplier) or failure_multiplier < 1:
        raise ValueError("Failure multiplier must be finite and >=1")
    rate, fixed = money(hourly_usd), money(fixed_usd)
    by_stratum = {}
    for profile in profiles:
        seconds = float(profile["total_seconds"])
        if not math.isfinite(seconds) or seconds <= 0 or profile.get("end_to_end_measured") is not True:
            raise ValueError("A measured positive end-to-end runtime is required")
        by_stratum.setdefault(profile["stratum"], []).append(Decimal(str(seconds)))
    seconds = Decimal(0)
    for stratum, count in cohort_counts.items():
        if type(count) is not int or count < 0:
            raise ValueError("Cohort counts must be nonnegative integers")
        if count and stratum not in by_stratum:
            raise ValueError(f"Missing measured profile for {stratum}")
        if count:
            seconds += max(by_stratum[stratum]) * count
    total = seconds / Decimal(3600) * rate * Decimal(str(failure_multiplier)) + fixed
    return {
        "projected_usd": str(total),
        "base_seconds": str(seconds),
        "failure_multiplier": failure_multiplier,
        "hourly_usd": str(rate),
        "fixed_usd": str(fixed),
        "note": "Conservative measured-stratum extrapolation, not a provider quote or hard spend cap.",
    }
