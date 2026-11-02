"""Manage Vast.ai instances and persist campaign state.

Split out of `orchestrator.py` when this code was consolidated for the
portfolio; the campaign logic that drives these primitives stayed there."""

import subprocess
import json
import threading
import time
import os
import csv
import pathlib
from dataclasses import dataclass, field, fields
from typing import Optional

from . import config


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Instance:
    id: int
    ssh_host: str = ""
    ssh_port: int = 22
    status: str = "pending"
    seed: Optional[int] = None
    label: Optional[str] = None


@dataclass
class CampaignState:
    """Persistent campaign state for checkpointing and resume."""
    campaign_id: str
    docker_image: str
    total_seeds: int
    completed_seeds: list = field(default_factory=list)
    failed_seeds: list = field(default_factory=list)
    results: list = field(default_factory=list)
    active_instances: dict = field(default_factory=dict)
    started_at: str = ""
    last_checkpoint: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def save(self, path: pathlib.Path):
        """Save campaign state to JSON checkpoint (atomic, thread-safe)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.last_checkpoint = time.strftime("%Y-%m-%d %H:%M:%S")
            data = {f.name: getattr(self, f.name) for f in fields(self) if f.name != '_lock'}
            tmp_path = str(path) + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, path)
        print(f"  [checkpoint] Saved to {path}")

    @classmethod
    def load(cls, path: pathlib.Path) -> "CampaignState":
        """Load campaign state from checkpoint."""
        with open(path) as f:
            data = json.load(f)
        data.pop("_lock", None)
        return cls(**data)

    def pending_seeds(self, all_seeds: list) -> list:
        """Return seeds not yet completed (failed seeds are retried)."""
        done = set(self.completed_seeds)
        return [s for s in all_seeds if s not in done]


# ---------------------------------------------------------------------------
# Vast.ai CLI helpers
# ---------------------------------------------------------------------------

def _run_vastai(args: list[str], parse_json: bool = True):
    """Run a vastai CLI command and return parsed output."""
    cmd = ["vastai"] + args
    if parse_json and "--raw" not in args:
        cmd.append("--raw")
    env = os.environ.copy()
    if config.VASTAI_API_KEY:
        env["VAST_API_KEY"] = config.VASTAI_API_KEY
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"vastai {' '.join(args)} failed: {result.stderr}")
    if parse_json:
        return json.loads(result.stdout)
    return result.stdout


def search_offers(
    gpu_name: str = None,
    max_price: float = None,
    min_disk: int = None,
    limit: int = 20,
) -> list[dict]:
    """Search Vast.ai marketplace for available GPU instances."""
    gpu = gpu_name or config.GPU_NAME
    price = max_price or config.MAX_PRICE_PER_HOUR
    disk = min_disk or config.DISK_GB
    query = (
        f"gpu_name={gpu} num_gpus=1 rentable=true "
        f"disk_space>={disk} dph_total<={price}"
    )
    offers = _run_vastai(["search", "offers", query])
    offers.sort(key=lambda o: o.get("dph_total", 999))
    return offers[:limit]


def create_instance(
    offer_id: int,
    docker_image: str,
    env_vars: dict = None,
    onstart_cmd: str = None,
    disk_gb: int = None,
    label: str = None,
) -> int:
    """Rent a Vast.ai instance and return its ID."""
    args = [
        "create", "instance", str(offer_id),
        "--image", docker_image,
        "--disk", str(disk_gb or config.DISK_GB),
    ]
    if env_vars:
        env_parts = [f"-e {k}={v}" for k, v in env_vars.items()]
        args.extend(["--env", " ".join(env_parts)])
    if onstart_cmd:
        args.extend(["--onstart-cmd", onstart_cmd])
    if label:
        args.extend(["--label", label])
    result = _run_vastai(args)
    if isinstance(result, dict):
        return result.get("new_contract", result.get("id"))
    return int(result)


def get_instance_info(instance_id: int) -> dict:
    """Get current instance status and connection info."""
    return _run_vastai(["show", "instance", str(instance_id)])


def wait_for_running(instance_id: int, timeout: int = None) -> Instance:
    """Block until instance reaches 'running' status."""
    timeout = timeout or config.INSTANCE_STARTUP_TIMEOUT
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = get_instance_info(instance_id)
        status = info.get("actual_status", info.get("status_msg", "unknown"))
        if status == "running":
            return Instance(
                id=instance_id,
                ssh_host=info.get("ssh_host", ""),
                ssh_port=info.get("ssh_port", 22),
                status="running",
            )
        if status in ("exited", "error", "destroyed"):
            raise RuntimeError(f"Instance {instance_id} status: {status}")
        time.sleep(config.POLL_INTERVAL)
    raise TimeoutError(f"Instance {instance_id} not ready within {timeout}s")


def ssh_exec(instance: Instance, command: str, timeout: int = 30) -> str:
    """Execute a command on a running instance via SSH."""
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
        "-p", str(instance.ssh_port),
        f"root@{instance.ssh_host}",
        command,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout


def scp_download(instance: Instance, remote_path: str, local_path: str):
    """Download files/directory from instance via SCP."""
    pathlib.Path(local_path).mkdir(parents=True, exist_ok=True)
    cmd = [
        "scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
        "-r", "-P", str(instance.ssh_port),
        f"root@{instance.ssh_host}:{remote_path}",
        local_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def destroy_instance(instance_id: int):
    """Destroy a Vast.ai instance."""
    _run_vastai(
        ["destroy", "instance", str(instance_id)], parse_json=False
    )


