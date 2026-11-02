"""Vast.ai configuration for mosaic protein design campaigns."""

import os
import pathlib

# ---------------------------------------------------------------------------
# Vast.ai credentials
# ---------------------------------------------------------------------------
VASTAI_API_KEY = os.environ.get("VASTAI_API_KEY", "")

# ---------------------------------------------------------------------------
# GPU / instance configuration
# ---------------------------------------------------------------------------
GPU_NAME = "A100_80GB"          # Vast.ai GPU identifier
MAX_PRICE_PER_HOUR = 2.00       # USD — reject offers above this
DISK_GB = 50                     # minimum disk per instance
MAX_CONCURRENT = 10              # simultaneous instances

# ---------------------------------------------------------------------------
# Docker images — push to Docker Hub before use
#   docker build -t <user>/mosaic-design:latest -f vast/Dockerfile .
#   docker push <user>/mosaic-design:latest
# ---------------------------------------------------------------------------
DOCKER_IMAGE_DESIGN = os.environ.get(
    "MOSAIC_DOCKER_DESIGN", "mosaic/mosaic-design:latest"
)
DOCKER_IMAGE_BOLTZ2 = os.environ.get(
    "MOSAIC_DOCKER_BOLTZ2", "mosaic/mosaic-boltz2:latest"
)

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
INSTANCE_STARTUP_TIMEOUT = 600   # wait for instance → running
JOB_TIMEOUT = 3600               # max wall-clock per design job
POLL_INTERVAL = 30               # status-check frequency

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCAL_OUTPUT_DIR = PROJECT_ROOT / "vast_outputs"
CHECKPOINT_DIR = PROJECT_ROOT / "vast_checkpoints"

REMOTE_WORKSPACE = "/workspace"
REMOTE_OUTPUT_DIR = "/workspace/outputs"
REMOTE_CHECKPOINT_DIR = "/workspace/checkpoints"

# ---------------------------------------------------------------------------
# JAX / XLA
# ---------------------------------------------------------------------------
XLA_MEM_FRACTION = "0.9"
