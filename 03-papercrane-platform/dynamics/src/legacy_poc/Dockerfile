# Paper Crane dynamics POC image
# -----------------------------------------------------------------------------
# Contents:
#   - CUDA 12.4.1 runtime + cuDNN (Ubuntu 22.04)
#   - Miniconda on PATH (HPacker setup is venv-based but BioEmu's README marks
#     conda + CUDA12 as the supported environment for `bioemu.sidechain_relax`)
#   - BioEmu (pinned commit 135031611c2acf11b293ff58dfd91fa97592ebd2, microsoft/bioemu)
#     installed with the `cuda` and `md` extras (jax[cuda12] + openmm-cuda-12)
#   - fpocket (Ubuntu universe, apt)
#   - Project Python deps from dynamics/requirements.txt
#   - The dynamics/ package copied in
#
# Entrypoint: `python -m dynamics.run_target`
# -----------------------------------------------------------------------------
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONDA_DIR=/opt/conda \
    PATH=/opt/conda/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# -----------------------------------------------------------------------------
# System dependencies
#   - fpocket: pocket detection (Ubuntu 22.04 universe ships v3.x)
#   - python3-venv: BioEmu's bundled hpacker_setup creates a venv at runtime
#   - build-essential: needed by some pip wheels (mdtraj, openmm helpers)
#   - git: BioEmu install from GitHub + bundled hpacker setup clones gvisani/hpacker
#   - curl/ca-certificates: miniconda installer
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository universe \
    && apt-get update && apt-get install -y --no-install-recommends \
        fpocket \
        python3-venv \
        build-essential \
        git \
        curl \
        ca-certificates \
        bzip2 \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# Miniconda (provides `conda` on PATH; required by BioEmu sidechain_relax docs)
# -----------------------------------------------------------------------------
RUN curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh \
    && bash /tmp/miniconda.sh -b -p /opt/conda \
    && rm /tmp/miniconda.sh \
    && /opt/conda/bin/conda install -y python=3.11 \
    && /opt/conda/bin/conda clean -afy

# -----------------------------------------------------------------------------
# BioEmu — pinned commit from microsoft/bioemu main (Task 1 verified)
# Use both extras:
#   - [cuda] -> jax[cuda12]==0.4.35 + nvidia-cuda-nvcc-cu12 (for sampling)
#   - [md]   -> openmm==8.4.0 + openmm-cuda-12==8.4.0 (for sidechain_relax)
# -----------------------------------------------------------------------------
ARG BIOEMU_COMMIT=135031611c2acf11b293ff58dfd91fa97592ebd2
RUN pip install "bioemu[cuda,md] @ git+https://github.com/microsoft/bioemu.git@${BIOEMU_COMMIT}"

# -----------------------------------------------------------------------------
# Project Python deps + package code
# -----------------------------------------------------------------------------
WORKDIR /app

COPY dynamics/requirements.txt /app/dynamics/requirements.txt
RUN pip install -r /app/dynamics/requirements.txt

COPY dynamics/ /app/dynamics/

ENV PYTHONPATH=/app

# -----------------------------------------------------------------------------
# Entrypoint: per-target driver. `--help` for usage.
# -----------------------------------------------------------------------------
ENTRYPOINT ["python", "-m", "dynamics.run_target"]
