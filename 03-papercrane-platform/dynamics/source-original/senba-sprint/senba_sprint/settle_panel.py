"""Reconcile the eight completed K4 apps against provider-reported charges.

This is a one-use sprint receipt, not a billing integration. A separate $2
commitment covers delayed charges; the account's $10 reserve is unchanged.
"""
import json
import argparse
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone

from .runner import BudgetLedger

ROOT = Path(__file__).resolve().parents[1]
APPS = {
    "pilot-1e7uA04-k4-v2": "ap-OFWoTF9AIsGeU8eNkGeTjM",
    "panel-1rquA01-k4-v1": "ap-InV37kGhkqhnJPTdCcBVPa",
    "panel-1q16B03-k4-v1": "ap-Ke9SBhj9vqY1CajVU95KRs",
    "panel-1d1rA00-k4-v1": "ap-tEV5zFnVUXPdQdqqEjks6Y",
    "panel-2k4qA00-k4-v1": "ap-qn83Ge7aEcAkMtQLgZnXfQ",
    "panel-2f2cA02-k4-v1": "ap-j7FGvxeK2LXBjz034FVsNg",
    "panel-5k2mA01-k4-v1": "ap-dZ5JaV8tMOd1fcxFj5Y7Yl",
    "panel-2dp9A01-k4-v1": "ap-d38iK8NSI9OaEKV6L443wl",
}
SAMPLING_APPS = {
    "augment-1e7uA04-k16-v1": "ap-7tqSvfeR4EwZXoniaxchwA",
    "augment-1rquA01-k16-v1": "ap-W3puy2tlYZ4BfiujCQ47J7",
    "augment-1q16B03-k16-v1": "ap-j53K0Kl5l8M5nUrXXh6ots",
    "augment-1d1rA00-k16-v1": "ap-sRHc3Xg03Yvq6gCaQxsboX",
    "augment-2k4qA00-k16-v1": "ap-xbCjXzQzOzvSlXcV5Hu6bW",
    "augment-2f2cA02-k16-v1": "ap-F8qwYDxT0fReH8cMdnIYiO",
    "augment-5k2mA01-k16-v1": "ap-byU426DLM7pzZHo5B1YQQy",
    "augment-2dp9A01-k16-v1": "ap-LmKwnBt6YaRh56xPHryKht",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sampling", action="store_true")
    args = parser.parse_args()
    apps = SAMPLING_APPS if args.sampling else APPS
    expected_count = 60 if args.sampling else 20
    if os.environ.get("MODAL_PROFILE") != "senba-sprint":
        raise ValueError("Explicit senba-sprint profile required")
    def modal_json(*args):
        return json.loads(subprocess.check_output(["modal", *args, "--json"], text=True))
    states = modal_json("app", "list")
    billing = modal_json("billing", "report", "--for", "today", "--resolution", "h")
    by_app = {r["App ID"]: r for r in states}
    costs = {}
    for run, app in apps.items():
        completion = json.loads((ROOT / "artifacts/runs" / run / "completion.json").read_text())
        if not completion["complete"] or completion["transitions"] != expected_count:
            raise ValueError(f"Incomplete run: {run}")
        if by_app[app]["State"] != "stopped" or int(by_app[app]["Tasks"]) != 0:
            raise ValueError(f"App not stopped with zero tasks: {app}")
        cost = sum(float(r["Cost"]) for r in billing if r["Object ID"] == app)
        if cost <= 0:
            raise ValueError(f"No positive provider charge available for {app}")
        costs[run] = cost
    receipt = {
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "provider_reported_costs_not_final_invoice",
        "late_charge_allowance_usd": 2.0,
        "apps": apps, "states": states, "billing": billing, "costs": costs,
    }
    name = "k16" if args.sampling else "k4"
    path = ROOT / f"artifacts/{name}-billing-reconciliation.json"
    with path.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    ledger = BudgetLedger(ROOT / "artifacts/budget-ledger.json", 30.0, 10.0)
    ledger.reserve("late-billing-overhead-allowance", 2.0)
    for run, cost in costs.items():
        ledger.reconcile(run, cost)
    print(json.dumps({"provider_reported_usd": sum(costs.values()),
                      "late_charge_allowance_usd": 2.0, "receipt": str(path)}))


if __name__ == "__main__":
    main()
