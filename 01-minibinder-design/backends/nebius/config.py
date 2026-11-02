"""Configuration for the Nebius single-VM V5 5G51-hotspots campaign runner."""
import os
from pathlib import Path

# --- GPU / VM flavor (Nebius no longer offers A100; H100 is the floor) ---
GPU_PLATFORM = "gpu-h100-sxm"
GPU_PRESET = "1gpu-16vcpu-200gb"
REGION = "eu-north1"
BOOT_IMAGE_FAMILY = "ubuntu24.04-cuda12"
BOOT_DISK_GIB = 200
DISK_TYPE = "network_ssd"

# --- Instance naming ---
INSTANCE_NAME = "mosaic-5g51-v4"
DISK_NAME = "mosaic-5g51-v4-disk"

# --- Remote paths on the VM (match vast/entrypoint.sh expectations) ---
REMOTE_WORKSPACE = "/workspace"
REMOTE_OUTPUTS = "/workspace/outputs"
REMOTE_REPO = "/opt/mosaic-src"  # where build.sh clones the repo

# --- Local paths (all under nebius/) ---
_NEBIUS_DIR = Path(__file__).parent
OUTPUTS_DIR = _NEBIUS_DIR / "outputs"
CHECKPOINTS_DIR = _NEBIUS_DIR / "checkpoints"
STATE_DIR = _NEBIUS_DIR / ".state"

# --- Docker image tags (built locally on the VM by build.sh) ---
DESIGN_IMAGE = "mosaic-design:5g51-v5-hotspots"
BOLTZ2_IMAGE = "mosaic-boltz2:5g51-v4"

# --- Campaign parameters ---
DEFAULT_SEEDS = 50
DESIGN_CONFIG_PATH = "/opt/v5/config/v5_5g51_hotspots.yaml"
VALIDATE_SCRIPT = "src/minibinder/fold/validate_boltz2.py"
TARGET_CIF = "5G51.cif"

# --- Timeouts (seconds) ---
INSTANCE_STARTUP_TIMEOUT = 600
JOB_TIMEOUT = 3600          # per-seed wall clock
SSH_POLL_INTERVAL = 20

# --- Runtime env passed into the container ---
XLA_MEM_FRACTION = "0.9"

# --- SSH ---
SSH_KEY_PATH = Path(os.environ.get("NEBIUS_SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519")))
SSH_USER = "ubuntu"


def _require(var: str) -> str:
    val = os.environ.get(var)
    if not val:
        raise RuntimeError(
            f"Environment variable {var} is not set. "
            f"Set it before running Nebius scripts (see nebius/README.md)."
        )
    return val


def project_id() -> str:
    """Nebius project ID, used as --parent-id. From env NEBIUS_PROJECT_ID."""
    return _require("NEBIUS_PROJECT_ID")


def subnet_id() -> str:
    """Subnet ID in REGION for the instance network interface. From env NEBIUS_SUBNET_ID."""
    return _require("NEBIUS_SUBNET_ID")
