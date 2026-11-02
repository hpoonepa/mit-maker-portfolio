"""Run remote jobs over SSH and collect their result CSVs."""
from __future__ import annotations
import shlex
import subprocess
import time
from pathlib import Path

from . import config


def ssh_exec(host: str, command: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a command on the VM over SSH. Returns the CompletedProcess (check yourself).
    ConnectTimeout=20 keeps short polls from blocking indefinitely on a dead network."""
    ssh_cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
        "-i", str(config.SSH_KEY_PATH),
        f"{config.SSH_USER}@{host}", command,
    ]
    return subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)


def scp_download(host: str, remote_path: str, local_dir: Path) -> None:
    """Recursively copy a remote path from the VM into local_dir."""
    local_dir.mkdir(parents=True, exist_ok=True)
    scp_cmd = [
        "scp", "-r", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-i", str(config.SSH_KEY_PATH),
        f"{config.SSH_USER}@{host}:{remote_path}", str(local_dir),
    ]
    result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"scp failed for {remote_path}: {result.stderr}")


def run_one_job(host: str, image: str, seed: int, config_path: str, target_cif: str,
                local_out_root: Path, gpu_id: int | None = None) -> dict:
    """Run a single seed/candidate in a V5 container on the VM, wait for the DONE
    marker, download outputs. Returns {'seed', 'csv_line', 'output_dir'} on success.
    Raises RuntimeError on failure (caller records it).

    Args:
        host: VM public IP.
        image: Docker image tag to run.
        seed: Integer seed for the design run.
        config_path: Path inside the container to the V5 YAML config
            (e.g. /opt/v5/config/v5_5g51_hotspots.yaml).
        target_cif: CIF filename consumed by the V5 entrypoint (e.g. 5G51.cif).
        local_out_root: Local directory under which per-seed outputs are downloaded.
        gpu_id: If set, pins the container to a single GPU by index via
            CUDA_VISIBLE_DEVICES (for multi-GPU VM fan-out). None = all GPUs visible.
    """
    return _run_detached_job(
        host=host, seed=seed, local_out_root=local_out_root,
        image=image, gpu_id=gpu_id,
        env={
            "SEED": str(seed),
            "CONFIG_PATH": config_path,
            "TARGET_CIF": target_cif,
            "XLA_PYTHON_CLIENT_MEM_FRACTION": config.XLA_MEM_FRACTION,
        },
        entrypoint="/workspace/entrypoint.sh",
        job_label="design",
    )


def _run_detached_job(host, seed, local_out_root, image, env, entrypoint,
                      job_label, gpu_id=None):
    """Launch a container detached on the VM (nohup+disown), poll a marker file
    every 60s until SUCCESS or FAILED, then SCP outputs back.

    A flaky SSH connection cannot kill the job — the container runs as a
    daemon-owned process on the VM, and each poll is a short-lived SSH call
    that survives transient network issues.
    """
    remote_out = f"{config.REMOTE_OUTPUTS}/seed_{seed:03d}"
    marker = f"{remote_out}/_RUN_DONE"      # distinct from entrypoint's own DONE marker
    job_log = f"{remote_out}/_run.log"
    gpu_env = f"-e CUDA_VISIBLE_DEVICES={gpu_id} " if gpu_id is not None else ""
    env_args = " ".join(f"-e {k}={shlex.quote(str(v))}" for k, v in env.items())

    container_cmd = (
        f"docker run --rm --gpus all "
        f"{gpu_env}"
        f"{env_args} "
        f"-v {config.REMOTE_OUTPUTS}:{config.REMOTE_OUTPUTS} "
        f"{shlex.quote(image)} {entrypoint}"
    )

    # Launch detached. The marker captures SUCCESS or FAILED depending on docker's exit.
    launch_cmd = (
        f"mkdir -p {remote_out} && rm -f {marker} && "
        f"(nohup bash -c '{container_cmd} && echo SUCCESS > {marker} "
        f"|| echo FAILED > {marker}' > {job_log} 2>&1 & disown) && echo launched"
    )
    proc = ssh_exec(host, launch_cmd, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"seed {seed}: failed to launch detached {job_label} job: "
                           f"rc={proc.returncode} stderr={proc.stderr[-1000:]}")

    # Poll for marker. Each ssh_exec is short (<30s); transient SSH failures
    # are ignored and the next poll will retry.
    poll_deadline = time.time() + config.JOB_TIMEOUT
    while time.time() < poll_deadline:
        time.sleep(60)
        try:
            check = ssh_exec(host, f"cat {marker} 2>/dev/null || echo INPROGRESS", timeout=30)
            state = (check.stdout or "").strip()
        except subprocess.TimeoutExpired:
            continue  # transient SSH hiccup; keep polling
        if state == "SUCCESS":
            break
        if state == "FAILED":
            try:
                log_tail = ssh_exec(host, f"tail -50 {job_log}", timeout=30).stdout[-2000:]
            except Exception:
                log_tail = "(could not retrieve log)"
            raise RuntimeError(f"seed {seed}: container reported FAILED: {log_tail}")
    else:
        raise RuntimeError(f"seed {seed}: timed out after {config.JOB_TIMEOUT}s "
                           f"waiting for {marker}")

    # Pull outputs back. SCP with a generous timeout; retry once on transient failure.
    local_seed_dir = local_out_root / f"seed_{seed:03d}"
    for attempt in (1, 2):
        try:
            scp_download(host, remote_out, local_out_root)
            break
        except RuntimeError as e:
            if attempt == 2:
                raise RuntimeError(f"seed {seed}: scp failed twice: {e}") from e
            time.sleep(15)

    csv_file = local_seed_dir / "csv_line.txt"
    csv_line = csv_file.read_text().strip() if csv_file.exists() else ""
    if not csv_line:
        raise RuntimeError(f"seed {seed}: empty or missing csv_line.txt after scp")
    return {"seed": seed, "csv_line": csv_line, "output_dir": str(local_seed_dir)}


def run_validation_job(host: str, image: str, seed: int, sequence: str,
                       candidate_id: str, local_out_root: Path) -> dict:
    """Run a single Boltz2 validation job. Uses SEED + SEQUENCE + TARGET_SEQ env
    vars because entrypoint_boltz2.sh reads them directly and appends TARGET_SEQ
    as validate_boltz2.py's optional 3rd positional arg (the target CIF filename)."""
    return _run_detached_job(
        host=host, seed=seed, local_out_root=local_out_root,
        image=image, gpu_id=None,
        env={
            "SEED": str(seed),
            "SEQUENCE": sequence,
            "CANDIDATE_ID": candidate_id,
            "TARGET_SEQ": config.TARGET_CIF,
            "XLA_PYTHON_CLIENT_MEM_FRACTION": config.XLA_MEM_FRACTION,
        },
        entrypoint="/workspace/entrypoint_boltz2.sh",
        job_label="boltz2-validation",
    )


def merge_csv(header: str, rows: list[str], out_path: Path) -> None:
    """Write header + non-empty rows to out_path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clean = [r for r in rows if r and r.strip()]
    out_path.write_text("\n".join([header, *clean]) + "\n")


def wait_for_ssh(host: str, timeout: int = config.INSTANCE_STARTUP_TIMEOUT) -> None:
    """Poll until the VM accepts SSH (cloud-init finished installing Docker)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        probe = ssh_exec(host, "docker --version", timeout=15)
        if probe.returncode == 0 and "Docker version" in probe.stdout:
            return
        time.sleep(config.SSH_POLL_INTERVAL)
    raise RuntimeError(f"VM {host} not SSH-ready (or Docker not installed) within {timeout}s")
