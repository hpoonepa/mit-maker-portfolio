"""Offline manifest checks and conservative local budget accounting for SENBA.

This module intentionally contains no SDK imports, subprocess execution, secret
handling, or network calls.  A future deployment adapter must consume its plan
only after the inputs it marks as blocked are resolved.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class ManifestValidationError(ValueError):
    """The manifest lacks a safety-critical field or has an invalid value."""


class BudgetError(RuntimeError):
    """A ledger operation would violate a budget or an immutable job state."""


def _finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestValidationError(f"{field} must be a finite non-negative number")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ManifestValidationError(f"{field} must be a finite non-negative number")
    return value


def _required_string(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{field} is required")


def _pinned_hex(value: Any, field: str, length: int | None = None) -> None:
    if value is None:
        return
    pattern = rf"[0-9a-fA-F]{{{length}}}" if length else r"[0-9a-fA-F]{7,64}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        detail = f"a {length}-character SHA-256" if length else "an immutable commit hash"
        raise ManifestValidationError(f"{field} must be {detail} or null")


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestValidationError(f"{field} must be an object")
    return value


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Validate structural and monetary safety invariants without touching I/O.

    Provenance fields may be ``None`` while inputs are being assembled.  They
    remain a preflight block rather than being replaced with invented values.
    """
    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest must be an object")
    budget = _mapping(manifest.get("budget"), "budget")
    total = _finite_nonnegative(budget.get("total_usd"), "budget.total_usd")
    reserve = _finite_nonnegative(budget.get("reserve_usd"), "budget.reserve_usd")
    if reserve > total:
        raise ManifestValidationError("budget.reserve_usd cannot exceed budget.total_usd")
    _finite_nonnegative(budget.get("cpu_storage_overhead_usd", 0), "budget.cpu_storage_overhead_usd")
    if budget.get("paid_enabled", False) is not False and not isinstance(budget["paid_enabled"], bool):
        raise ManifestValidationError("budget.paid_enabled must be boolean")
    if manifest.get("concurrency", 1) != 1:
        raise ManifestValidationError("concurrency must be exactly 1 until a reviewed scheduler exists")
    provenance = _mapping(manifest.get("provenance"), "provenance")
    model = _mapping(provenance.get("model"), "provenance.model")
    dataset = _mapping(provenance.get("dataset"), "provenance.dataset")
    for name, record, fields in (
        ("provenance.model", model, ("source", "revision", "checkpoint")),
        ("provenance.dataset", dataset, ("source", "revision", "split", "split_manifest_sha256")),
    ):
        for field in fields:
            value = record.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ManifestValidationError(f"{name}.{field} must be a non-empty string or null")
    _pinned_hex(model.get("revision"), "provenance.model.revision")
    _pinned_hex(dataset.get("revision"), "provenance.dataset.revision")
    _pinned_hex(dataset.get("split_manifest_sha256"), "provenance.dataset.split_manifest_sha256", 64)
    if provenance.get("excludes_495_test") is not True:
        raise ManifestValidationError("provenance.excludes_495_test must be true")
    adaptation = provenance.get("adaptation_code")
    if adaptation is not None:
        adaptation = _mapping(adaptation, "provenance.adaptation_code")
        for field in ("source", "revision", "lockfile_sha256"):
            value = adaptation.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ManifestValidationError(f"provenance.adaptation_code.{field} must be a non-empty string or null")
        _pinned_hex(adaptation.get("revision"), "provenance.adaptation_code.revision")
        _pinned_hex(adaptation.get("lockfile_sha256"), "provenance.adaptation_code.lockfile_sha256", 64)
    for field in ("source_seed", "parent_seed"):
        if provenance.get(field) is not None and not isinstance(provenance[field], int):
            raise ManifestValidationError(f"provenance.{field} must be an integer or null")
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ManifestValidationError("jobs must be a non-empty list")
    seen: set[str] = set()
    for index, job in enumerate(jobs):
        job = _mapping(job, f"jobs[{index}]")
        job_id = job.get("id")
        _required_string(job_id, f"jobs[{index}].id")
        if job_id in seen:
            raise ManifestValidationError(f"duplicate job id: {job_id}")
        seen.add(job_id)
        if not isinstance(job.get("seed"), int):
            raise ManifestValidationError(f"jobs[{index}].seed must be an integer")
        timeout = job.get("gpu_timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise ManifestValidationError(f"jobs[{index}].gpu_timeout_seconds must be a positive integer")
        rate = job.get("gpu_hourly_rate_usd")
        if rate is not None:
            _finite_nonnegative(rate, f"jobs[{index}].gpu_hourly_rate_usd")
        _finite_nonnegative(job.get("startup_retry_overhead_usd", 0), f"jobs[{index}].startup_retry_overhead_usd")
        if "retries" in job and (not isinstance(job["retries"], int) or job["retries"] < 0):
            raise ManifestValidationError(f"jobs[{index}].retries must be a non-negative integer")
    required_artifacts = manifest.get("required_artifact_inputs", [])
    if not isinstance(required_artifacts, list) or any(not isinstance(item, str) or not item.strip() for item in required_artifacts):
        raise ManifestValidationError("required_artifact_inputs must be a list of non-empty names")
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ManifestValidationError("artifacts must be a list")
    for index, artifact in enumerate(artifacts):
        artifact = _mapping(artifact, f"artifacts[{index}]")
        _required_string(artifact.get("path"), f"artifacts[{index}].path")
        if artifact.get("sha256") is not None:
            _pinned_hex(artifact["sha256"], f"artifacts[{index}].sha256", 64)


def _missing_provenance(manifest: dict[str, Any]) -> list[str]:
    p = manifest["provenance"]
    fields = (("model", "source"), ("model", "revision"), ("model", "checkpoint"),
              ("dataset", "source"), ("dataset", "revision"), ("dataset", "split"),
              ("dataset", "split_manifest_sha256"), (None, "source_seed"), (None, "parent_seed"))
    missing = []
    for group, field in fields:
        value = p.get(field) if group is None else p[group].get(field)
        if not value and value != 0:
            missing.append(f"provenance.{field}" if group is None else f"provenance.{group}.{field}")
    adaptation = p.get("adaptation_code") if isinstance(p.get("adaptation_code"), dict) else {}
    for field in ("source", "revision", "lockfile_sha256"):
        if not adaptation.get(field):
            missing.append(f"provenance.adaptation_code.{field}")
    lag = p.get("lag")
    lag_verified = isinstance(lag, dict) and lag.get("physical_interval_verified") is True
    if p.get("physical_ns_per_frame") is None or not lag_verified:
        missing.append("provenance.physical_interval_unverified")
    return missing


def _estimate_job(job: dict[str, Any], budget: dict[str, Any]) -> float | None:
    if job.get("kind") in {"known_row_reproduce", "offline_analysis"}:
        return 0.0
    rate = job.get("gpu_hourly_rate_usd")
    if rate is None:
        return None
    # Timeout bounds one attempt.  Retries are explicit, never assumed.
    attempts = 1 + job.get("retries", 0)
    return round(
        (job["gpu_timeout_seconds"] / 3600.0) * float(rate) * attempts
        + float(job.get("startup_retry_overhead_usd", 0))
        + float(budget.get("cpu_storage_overhead_usd", 0)),
        8,
    )


def _artifact_checks(manifest: dict[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for artifact in manifest.get("artifacts", []):
        if not isinstance(artifact, dict) or not artifact.get("path"):
            checks.append({"path": None, "ok": False, "reason": "invalid artifact declaration"})
            continue
        path = Path(artifact["path"])
        path = path if path.is_absolute() else base_dir / path
        item: dict[str, Any] = {"path": str(path), "ok": path.is_file()}
        if not item["ok"]:
            item["reason"] = "file missing"
        elif artifact.get("sha256"):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            item["sha256"] = digest
            item["ok"] = digest == artifact["sha256"]
            if not item["ok"]:
                item["reason"] = "sha256 mismatch"
        checks.append(item)
    return checks


def preflight(manifest: dict[str, Any], *, base_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return a no-network readiness report; never reads credentials or secrets."""
    report: dict[str, Any] = {"ok": False, "errors": [], "blocked": [], "checks": [], "estimates": {}}
    try:
        validate_manifest(manifest)
    except ManifestValidationError as exc:
        report["errors"].append(str(exc))
        return report
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    report["checks"] = _artifact_checks(manifest, root)
    report["blocked"].extend(_missing_provenance(manifest))
    report["blocked"].extend("artifact-input:" + item for item in manifest.get("required_artifact_inputs", []))
    report["blocked"].extend("artifact:" + check["path"] for check in report["checks"] if not check["ok"])
    estimates: dict[str, float | None] = {}
    for job in manifest["jobs"]:
        estimate = _estimate_job(job, manifest["budget"])
        estimates[job["id"]] = estimate
        if estimate is None:
            report["blocked"].append(f"rate:{job['id']}")
    report["estimates"] = estimates
    if any(value is None for value in estimates.values()):
        report["blocked"].append("complete explicit rate card or measured pilot before paid launch")
    else:
        max_cost = sum(value for value in estimates.values() if value is not None)
        report["estimates"]["all_jobs_max_usd"] = max_cost
        if max_cost + manifest["budget"]["reserve_usd"] > manifest["budget"]["total_usd"]:
            report["blocked"].append("all job maximums plus reserve exceed total budget")
    if not manifest["budget"].get("paid_enabled", False):
        report["blocked"].append("paid_enabled is false")
    report["ok"] = not report["errors"] and not report["blocked"]
    return report


def plan_jobs(manifest: dict[str, Any], *, base_dir: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    """Build inert, stable job records.  This function never makes jobs runnable."""
    report = preflight(manifest, base_dir=base_dir)
    if report["errors"]:
        raise ManifestValidationError(report["errors"][0])
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    plans = []
    for job in manifest["jobs"]:
        payload = {"manifest_fingerprint": fingerprint, "id": job["id"], "kind": job.get("kind"), "seed": job["seed"],
                   "parameters": job.get("parameters", {})}
        key = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        local = job.get("kind") in {"known_row_reproduce", "offline_analysis"}
        blocked = list(report["blocked"])
        if local:
            blocked = [reason for reason in blocked if reason not in {
                "paid_enabled is false",
                "complete explicit rate card or measured pilot before paid launch",
                "all job maximums plus reserve exceed total budget",
            }]
        plans.append({"job_id": job["id"], "idempotency_key": key, "manifest_fingerprint": fingerprint,
                      "kind": job.get("kind"),
                      "seed": job["seed"], "stage": job.get("stage"), "status": "BLOCKED",
                      "blocked_by": blocked,
                      "estimated_max_usd": report["estimates"].get(job["id"]),
                      "launch_adapter": None})
    return plans


class BudgetLedger:
    """A small atomic ledger: reserves and failed jobs remain committed until reconciled."""

    def __init__(self, path: str | os.PathLike[str], total_usd: float, reserve_usd: float = 10.0) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.total_usd = _finite_nonnegative(total_usd, "total_usd")
        self.reserve_usd = _finite_nonnegative(reserve_usd, "reserve_usd")
        if self.reserve_usd > self.total_usd:
            raise ManifestValidationError("reserve_usd cannot exceed total_usd")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "total_usd": self.total_usd, "reserve_usd": self.reserve_usd,
                    "frozen": False, "freeze_reason": None, "jobs": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BudgetError(f"ledger is unreadable; refusing to launch: {exc}") from exc
        if data.get("total_usd") != self.total_usd or data.get("reserve_usd") != self.reserve_usd:
            raise BudgetError("ledger budget settings differ from this invocation")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        encoded = json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _committed(data: dict[str, Any]) -> float:
        return sum(float(job["reserved_usd"]) for job in data["jobs"].values()
                   if job["status"] in {"reserved", "failed"})

    @staticmethod
    def _spent(data: dict[str, Any]) -> float:
        return sum(float(job["actual_usd"] or 0) for job in data["jobs"].values()
                   if job["status"] == "settled")

    def snapshot(self) -> dict[str, Any]:
        with self._locked():
            return copy.deepcopy(self._read())

    def reserve(self, job_id: str, estimated_usd: float) -> dict[str, Any]:
        _required_string(job_id, "job_id")
        estimate = _finite_nonnegative(estimated_usd, "estimated_usd")
        with self._locked():
            data = self._read()
            if data["frozen"]:
                raise BudgetError(f"ledger frozen: {data['freeze_reason']}")
            existing = data["jobs"].get(job_id)
            if existing:
                if existing["status"] == "reserved" and existing["reserved_usd"] == estimate:
                    return copy.deepcopy(existing)  # idempotent retry; no second reservation
                raise BudgetError(f"job id {job_id!r} already exists in state {existing['status']}")
            if self._spent(data) + self._committed(data) + estimate + self.reserve_usd > self.total_usd:
                raise BudgetError("reservation would exceed total budget after committed costs and reserve")
            item = {"status": "reserved", "reserved_usd": estimate, "actual_usd": None}
            data["jobs"][job_id] = item
            self._write(data)
            return copy.deepcopy(item)

    def mark_failed(self, job_id: str) -> dict[str, Any]:
        with self._locked():
            data = self._read()
            job = data["jobs"].get(job_id)
            if not job or job["status"] != "reserved":
                raise BudgetError("only a reserved job can be marked failed")
            job["status"] = "failed"  # retains its full reservation until billed/reconciled
            self._write(data)
            return copy.deepcopy(job)

    def reconcile(self, job_id: str, actual_usd: float) -> dict[str, Any]:
        """Settle a reserved/failed job.  Overrun freezes subsequent reservations."""
        actual = _finite_nonnegative(actual_usd, "actual_usd")
        with self._locked():
            data = self._read()
            job = data["jobs"].get(job_id)
            if not job or job["status"] not in {"reserved", "failed"}:
                raise BudgetError("only a reserved or failed job can be reconciled once")
            job["status"] = "settled"
            job["actual_usd"] = actual
            # Settled charges are actual; still-unbilled reservations stay conservative.
            spent = self._spent(data)
            if spent + self._committed(data) + self.reserve_usd > self.total_usd:
                data["frozen"] = True
                data["freeze_reason"] = "actual charges plus committed reservations and reserve exceed total budget"
            self._write(data)
            return copy.deepcopy(job)
