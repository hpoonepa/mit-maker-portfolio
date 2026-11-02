# Check runner contracts using local fixtures.
import concurrent.futures
import hashlib
import json
from pathlib import Path

import pytest

from senba_sprint.runner import BudgetError, BudgetLedger, ManifestValidationError, plan_jobs, preflight, validate_manifest


def manifest():
    return {
        "concurrency": 1,
        "budget": {"total_usd": 60, "reserve_usd": 10, "paid_enabled": False},
        "provenance": {
            "model": {"source": "repo", "revision": "a" * 40, "checkpoint": "step-1"},
            "dataset": {"source": "dataset", "revision": "b" * 40, "split": "train",
                        "split_manifest_sha256": "c" * 64},
            "source_seed": 0,
            "parent_seed": 1,
            "excludes_495_test": True,
        },
        "jobs": [{"id": "one", "seed": 1, "gpu_timeout_seconds": 3600,
                  "gpu_hourly_rate_usd": None, "startup_retry_overhead_usd": 0}],
    }


def test_rate_unset_blocks_and_plan_is_inert():
    report = preflight(manifest())
    assert not report["ok"] and "rate:one" in report["blocked"]
    plan = plan_jobs(manifest())
    assert plan[0]["status"] == "BLOCKED" and plan[0]["launch_adapter"] is None


def test_local_job_cost_is_zero_and_its_plan_does_not_depend_on_paid_gate():
    data = manifest()
    data["jobs"][0]["kind"] = "offline_analysis"
    report = preflight(data)
    plan = plan_jobs(data)[0]
    assert report["estimates"]["one"] == 0.0
    assert "rate:one" not in report["blocked"]
    assert "paid_enabled is false" not in plan["blocked_by"]


def test_preflight_checks_declared_local_artifact_hash(tmp_path):
    artifact = tmp_path / "input.json"
    artifact.write_text("known input")
    data = manifest()
    data["artifacts"] = [{"path": artifact.name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}]
    report = preflight(data, base_dir=tmp_path)
    assert report["checks"] == [{"path": str(artifact), "ok": True,
                                  "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}]


@pytest.mark.parametrize("artifact", [{}, {"path": ""}, {"path": "x", "sha256": "not-a-hash"}])
def test_malformed_artifacts_are_validation_errors_not_preflight_type_errors(artifact):
    data = manifest()
    data["artifacts"] = [artifact]
    with pytest.raises(ManifestValidationError):
        validate_manifest(data)
    report = preflight(data)
    assert report["errors"]


def test_excludes_495_test_cannot_be_false():
    data = manifest()
    data["provenance"]["excludes_495_test"] = False
    with pytest.raises(ManifestValidationError):
        validate_manifest(data)


def test_plan_key_binds_the_manifest_provenance_and_honors_base_dir(tmp_path):
    data = manifest()
    data["artifacts"] = [{"path": "missing-input"}]
    first = plan_jobs(data, base_dir=tmp_path)[0]
    changed = manifest()
    changed["provenance"]["model"]["revision"] = "d" * 40
    changed["artifacts"] = [{"path": "missing-input"}]
    second = plan_jobs(changed, base_dir=tmp_path)[0]
    assert first["idempotency_key"] != second["idempotency_key"]
    assert first["manifest_fingerprint"] != second["manifest_fingerprint"]
    assert "artifact:" + str(tmp_path / "missing-input") in first["blocked_by"]


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), -0.01])
def test_invalid_rates_rejected(rate):
    data = manifest()
    data["jobs"][0]["gpu_hourly_rate_usd"] = rate
    with pytest.raises(ManifestValidationError):
        validate_manifest(data)


def test_floating_revision_is_rejected():
    data = manifest()
    data["provenance"]["model"]["revision"] = "main"
    with pytest.raises(ManifestValidationError):
        validate_manifest(data)


def test_supplied_pins_do_not_unblock_missing_coordinates_or_adaptation_code():
    config_path = Path(__file__).parents[1] / "configs" / "sprint.json"
    config = json.loads(config_path.read_text())
    report = preflight(config, base_dir=config_path.parent)
    provenance = config["provenance"]
    assert provenance["model"]["revision"] == "90cce9e822d511459a206ae3a06cbd8dbb243b09"
    assert provenance["dataset"]["split_manifest_sha256"] == "163ab0043d86b5a2731e1b1a233af27fb069049897d657fd5c39bd54b1343b3f"
    assert provenance["lag"] == {"value": 50, "units": "saved_frames", "physical_interval_verified": False}
    assert "provenance.model.source" not in report["blocked"]
    assert "artifact-input:raw paired endpoint coordinates" in report["blocked"]
    assert "artifact-input:adaptation code repository, revision, and lockfile" in report["blocked"]
    # Downloaded checkpoint/summary receipts still do not supply raw coordinates.
    assert not report["ok"]


def test_intrinsic_adaptation_and_physical_blocks_survive_manual_list_removal():
    config_path = Path(__file__).parents[1] / "configs" / "sprint.json"
    config = json.loads(config_path.read_text())
    config["required_artifact_inputs"] = []
    report = preflight(config, base_dir=config_path.parent)
    assert "provenance.adaptation_code.source" in report["blocked"]
    assert "provenance.adaptation_code.revision" in report["blocked"]
    assert "provenance.physical_interval_unverified" in report["blocked"]
    assert "artifact-input:raw paired endpoint coordinates" not in report["blocked"]


def test_config_uses_actual_rng_seed_values_not_ordinal_labels():
    config = json.loads((Path(__file__).parents[1] / "configs" / "sprint.json").read_text())
    assert config["provenance"]["parent_seed"] == 20260825
    assert config["provenance"]["replication_seeds"] == [
        {"ordinal_label": 2, "rng_seed": 20260826, "status": "receipt_only"},
        {"ordinal_label": 3, "rng_seed": 20260827, "status": "receipt_only"},
    ]
    assert config["jobs"][2]["parameters"]["additional_seeds"] == [20260826, 20260827]


def test_reserve_settle_idempotency_and_no_resurrection(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json", 60, 10)
    assert ledger.reserve("a", 20)["status"] == "reserved"
    assert ledger.reserve("a", 20)["status"] == "reserved"
    ledger.reconcile("a", 15)
    with pytest.raises(BudgetError):
        ledger.reserve("a", 15)
    assert ledger.snapshot()["jobs"]["a"]["actual_usd"] == 15


def test_failed_holds_and_budget_overflow(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json", 60, 10)
    ledger.reserve("a", 45)
    ledger.mark_failed("a")
    with pytest.raises(BudgetError):
        ledger.reserve("b", 6)
    with pytest.raises(BudgetError):
        ledger.reserve("too-large", 51)


def test_actual_overrun_freezes_ledger(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json", 60, 10)
    ledger.reserve("a", 20)
    ledger.reserve("b", 20)
    ledger.reconcile("a", 35)
    assert ledger.snapshot()["frozen"]
    with pytest.raises(BudgetError):
        ledger.reserve("c", 1)


def test_settled_spend_counts_toward_later_reservations(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json", 60, 10)
    ledger.reserve("a", 40)
    ledger.reconcile("a", 45)
    with pytest.raises(BudgetError):
        ledger.reserve("b", 6)


def test_concurrent_reservations_do_not_overcommit(tmp_path):
    ledger_path = tmp_path / "ledger.json"

    def reserve(name):
        try:
            BudgetLedger(ledger_path, 60, 10).reserve(name, 30)
            return True
        except BudgetError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, ["a", "b"]))
    assert outcomes.count(True) == 1
    assert len(json.loads(ledger_path.read_text())["jobs"]) == 1
