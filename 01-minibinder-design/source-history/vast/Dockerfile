# =============================================================================
# Mosaic Protein Design — Vast.ai GPU Dockerfile
# =============================================================================
# Converts the Modal image definition to a standard Docker image for running
# mosaic protein design campaigns on Vast.ai GPU instances (A100/H100).
#
# Build:  docker build -t mosaic-design -f vast/Dockerfile .
# Push:   docker push <registry>/mosaic-design:latest
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Base CUDA image with Python 3.12
# ---------------------------------------------------------------------------
# Modal uses debian_slim(python_version="3.12"). We use the NVIDIA CUDA base
# image with cuDNN for JAX GPU support, then install Python 3.12 on top.
FROM nvidia/cuda:12.6.0-cudnn-devel-ubuntu22.04 AS base

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

# Install Python 3.12 from deadsnakes PPA + system dependencies
# Equivalent to Modal: debian_slim(python_version="3.12") + apt_install(...)
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        git \
        curl \
        build-essential \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Stage 2: Install uv package manager
# ---------------------------------------------------------------------------
# Equivalent to Modal: pip_install("uv")
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# ---------------------------------------------------------------------------
# Stage 3: Clone and prepare jopenfold3
# ---------------------------------------------------------------------------
# Equivalent to Modal: run_commands(
#   "git clone https://github.com/escalante-bio/jopenfold3.git /tmp/jopenfold3",
#   "rm -f /tmp/jopenfold3/jopenfold3/mosaic"
# )
RUN git clone https://github.com/escalante-bio/jopenfold3.git /tmp/jopenfold3 \
    && rm -f /tmp/jopenfold3/jopenfold3/mosaic

# ---------------------------------------------------------------------------
# Stage 4: Clone mosaic and patch pyproject.toml
# ---------------------------------------------------------------------------
# Equivalent to Modal: run_commands(
#   "git clone https://github.com/escalante-bio/mosaic.git /opt/mosaic",
#   "cd /opt/mosaic && sed -i 's|jopenfold3 = ...|jopenfold3 = { path = ...}|' pyproject.toml"
# )
RUN git clone https://github.com/escalante-bio/mosaic.git /opt/mosaic \
    && cd /opt/mosaic \
    && sed -i 's|jopenfold3 = { git = "https://github.com/escalante-bio/jopenfold3.git" }|jopenfold3 = { path = "/tmp/jopenfold3" }|' pyproject.toml

# ---------------------------------------------------------------------------
# Stage 5: Install Python dependencies with uv
# ---------------------------------------------------------------------------
# Equivalent to Modal: run_commands(
#   "cd /opt/mosaic && uv lock && uv sync --group jax-cuda"
# )
# This is the heaviest layer — Docker will cache it unless pyproject.toml changes.
WORKDIR /opt/mosaic
RUN uv lock && uv sync --group jax-cuda

# ---------------------------------------------------------------------------
# Stage 6: Download reference structure files
# ---------------------------------------------------------------------------
# Equivalent to Modal: run_commands(
#   "curl -fsSL -o /opt/mosaic/5G51.cif ...",
#   "curl -fsSL -o /opt/mosaic/2LGV.cif ..."
# )
RUN curl -fsSL -o /opt/mosaic/5G51.cif https://files.rcsb.org/download/5G51.cif \
    && curl -fsSL -o /opt/mosaic/2LGV.cif https://files.rcsb.org/download/2LGV.cif

# ---------------------------------------------------------------------------
# Stage 7: Copy design scripts and entrypoint
# ---------------------------------------------------------------------------
# COPY design campaign scripts into the mosaic directory
COPY design_2lgv.py design_5g51.py design_god.py /opt/mosaic/

# COPY Vast.ai entrypoint script and make it executable
COPY vast/entrypoint.sh /workspace/entrypoint.sh
RUN chmod +x /workspace/entrypoint.sh

# Create output directories for campaign results and model checkpoints
RUN mkdir -p /workspace/outputs /workspace/checkpoints

# ---------------------------------------------------------------------------
# Stage 8: Environment and runtime configuration
# ---------------------------------------------------------------------------
# Equivalent to Modal: ENV XLA_PYTHON_CLIENT_MEM_FRACTION=0.9
# Allows JAX to use 90% of GPU memory for protein structure prediction
ENV XLA_PYTHON_CLIENT_MEM_FRACTION=0.9

# Activate the uv-managed virtualenv for all subsequent commands
ENV PATH="/opt/mosaic/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/mosaic/.venv"

WORKDIR /opt/mosaic

# Vast.ai uses onstart-cmd to launch jobs, so we just keep the container alive
# with bash as the default entrypoint
ENTRYPOINT ["/bin/bash"]
