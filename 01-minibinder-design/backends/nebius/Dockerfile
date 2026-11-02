# =============================================================================
# Mosaic Protein Design — Nebius GPU Dockerfile (V5)
# =============================================================================
# Converts the Modal image definition (src/modal_design_v5.py) to a standard
# Docker image for running V5 mosaic protein design campaigns on Nebius GPU
# instances (A100-80GB).
#
# Build:  docker build -t mosaic-design-v5 -f nebius/Dockerfile .
# Push:   docker push <registry>/mosaic-design-v5:latest
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
# Stage 4: Clone mosaic, pin to bca3152, and patch pyproject.toml
# ---------------------------------------------------------------------------
# Equivalent to Modal: run_commands(
#   "git clone https://github.com/escalante-bio/mosaic.git /opt/mosaic",
#   "cd /opt/mosaic && git checkout bca3152",
#   "cd /opt/mosaic && sed -i '...' pyproject.toml"
# )
# bca3152 = first commit with ProtenixV2(), before the 8362af3 refactor that
# breaks pickle.load of protenix weights on fresh builds. See modal_design_v5.py.
RUN git clone https://github.com/escalante-bio/mosaic.git /opt/mosaic \
    && cd /opt/mosaic \
    && git checkout bca3152 \
    && sed -i 's|jopenfold3 = { git = "https://github.com/escalante-bio/jopenfold3.git" }|jopenfold3 = { path = "/tmp/jopenfold3" }|' pyproject.toml

# ---------------------------------------------------------------------------
# Stage 5: Install Python dependencies with uv, pinning JAX to 0.9.1
# ---------------------------------------------------------------------------
# Equivalent to Modal: run_commands(
#   "cd /opt/mosaic && sed -i 's|\"jax>=0.8.1\"|\"jax==0.9.1\"|' pyproject.toml
#    && uv lock && uv sync --group jax-cuda"
# )
# JAX must be pinned to 0.9.1: jax 0.10.0 removed ShapeDtypeStruct.vma,
# breaking pickle.load of protenix weights serialised against 0.9.x.
# Also pin esmj to 7097e3c — the next commit (f300bb4) bumps esmj's jax
# requirement to >=0.10, which conflicts with our jax==0.9.1 pin and would
# break `uv lock`. 7097e3c is the last esmj commit compatible with jax<0.10.
WORKDIR /opt/mosaic
RUN uv lock && uv sync --group jax-cuda

# ---------------------------------------------------------------------------
# Stage 6: Download reference structure files
# ---------------------------------------------------------------------------
# Equivalent to Modal: run_commands(
#   "curl -fsSL -o /opt/mosaic/5G51.cif ...",
#   "curl -fsSL -o /opt/mosaic/2LGV.cif ..."
# )
# V5 entrypoint reads 5G51.cif from cwd (/opt/mosaic).
RUN curl -fsSL -o /opt/mosaic/5G51.cif https://files.rcsb.org/download/5G51.cif \
    && curl -fsSL -o /opt/mosaic/2LGV.cif https://files.rcsb.org/download/2LGV.cif || true

# ---------------------------------------------------------------------------
# Stage 7: Copy V5 source tree and configs into /opt/v5/
# ---------------------------------------------------------------------------
# Equivalent to Modal:
#   .add_local_dir("src",       remote_path="/opt/v5/src")
#   .add_local_dir("validators", remote_path="/opt/v5/validators")
#   .add_local_dir("config",    remote_path="/opt/v5/config")
# design_v5.py does sys.path.insert so `from src.losses.X` resolves under /opt/v5.
COPY src/ /opt/v5/src/
COPY validators/ /opt/v5/validators/
COPY config/ /opt/v5/config/

# ---------------------------------------------------------------------------
# Stage 8: Copy V5 entrypoint
# ---------------------------------------------------------------------------
# Use the Nebius V5 entrypoint (expects /opt/v5/src/design_v5.py,
# /opt/v5/config/v5_5g51_hotspots.yaml, and 5G51.cif at cwd /opt/mosaic).
COPY nebius/entrypoint_v5.sh /workspace/entrypoint.sh
RUN chmod +x /workspace/entrypoint.sh

# Create output directories for campaign results and model checkpoints
RUN mkdir -p /workspace/outputs /workspace/checkpoints

# ---------------------------------------------------------------------------
# Stage 9: Environment and runtime configuration
# ---------------------------------------------------------------------------
# Equivalent to Modal: ENV XLA_PYTHON_CLIENT_MEM_FRACTION=0.9
ENV XLA_PYTHON_CLIENT_MEM_FRACTION=0.9

# Activate the uv-managed virtualenv for all subsequent commands
ENV PATH="/opt/mosaic/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/mosaic/.venv"

WORKDIR /opt/mosaic

# Nebius runner appends /workspace/entrypoint.sh as the command argument.
ENTRYPOINT ["/bin/bash"]
