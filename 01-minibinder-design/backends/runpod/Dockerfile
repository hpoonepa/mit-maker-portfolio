# =============================================================================
# Mosaic tri-objective (Protenix + Boltz2 + ESMFold) — RunPod image
# =============================================================================
# Build:  docker build -t <user>/mosaic-tri:latest -f runpod/Dockerfile .
# Push:   docker push <user>/mosaic-tri:latest
#
# TWO VENVS, ON PURPOSE:
#   /opt/mosaic/.venv   JAX 0.9.1 — protenix + boltz2. DO NOT pip into this.
#   /opt/esmfold/.venv  PyTorch   — fair-esm[esmfold].
# jax 0.10 removed ShapeDtypeStruct.vma, which breaks unpickling the protenix
# weights, so the jax pin is load-bearing. Putting torch in the same venv is
# how that pin gets silently clobbered.
#
# TRAP: `pip install esm` gets an UNRELATED PyPI package. ESMFold is
#       `fair-esm[esmfold]`. Same trap applies to `protenix` and `boltz` —
#       mosaic's real deps come from [tool.uv.sources], which pip cannot see.
#       Always `uv sync`, never `pip install -r`.
# =============================================================================
FROM nvidia/cuda:12.6.0-cudnn-devel-ubuntu22.04 AS base
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
        git curl build-essential openssh-client rsync jq \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python  python  /usr/bin/python3.12 1 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# --- jopenfold3 (path-substituted into mosaic's pyproject) -------------------
RUN git clone https://github.com/escalante-bio/jopenfold3.git /tmp/jopenfold3 \
    && rm -f /tmp/jopenfold3/jopenfold3/mosaic

# --- mosaic @ bca3152: first commit with ProtenixV2(), before the 8362af3 -----
#     refactor that breaks pickle.load of the protenix weights.
RUN git clone https://github.com/escalante-bio/mosaic.git /opt/mosaic \
    && cd /opt/mosaic \
    && git checkout bca3152 \
    && sed -i 's|jopenfold3 = { git = "https://github.com/escalante-bio/jopenfold3.git" }|jopenfold3 = { path = "/tmp/jopenfold3" }|' pyproject.toml

WORKDIR /opt/mosaic
RUN uv lock && uv sync --group jax-cuda

# --- ESMFold, isolated -------------------------------------------------------
# openfold's CUDA kernels are not needed for inference; fair-esm falls back to
# the pure-PyTorch path. Skipping them avoids a long, fragile nvcc build.
RUN python3 -m venv /opt/esmfold/.venv \
    && /opt/esmfold/.venv/bin/pip install --no-cache-dir -U pip wheel \
    && /opt/esmfold/.venv/bin/pip install --no-cache-dir \
         torch --index-url https://download.pytorch.org/whl/cu124 \
    && /opt/esmfold/.venv/bin/pip install --no-cache-dir \
         "fair-esm[esmfold]" gemmi numpy \
    && /opt/esmfold/.venv/bin/pip install --no-cache-dir \
         "dllogger @ git+https://github.com/NVIDIA/dllogger.git" \
         "openfold @ git+https://github.com/aqlaboratory/openfold.git@4b41059694619831a7db195b7e0988fc4ff3a307" \
       || echo "openfold extras skipped - fair-esm uses its pure-torch fallback"

# Bake the ESMFold weights in (~2.6 GB) so a cold pod does not re-download them.
RUN /opt/esmfold/.venv/bin/python -c "\
import esm, torch; esm.pretrained.esmfold_v1(); print('esmfold weights cached')" \
    || echo "WARNING: esmfold weights not pre-cached; first run will download them"

# --- reference targets -------------------------------------------------------
RUN curl -fsSL -o /opt/mosaic/5G51.cif https://files.rcsb.org/download/5G51.cif \
    && curl -fsSL -o /opt/mosaic/4EUL.cif https://files.rcsb.org/download/4EUL.cif || true

# --- project tree ------------------------------------------------------------
COPY src/        /opt/v5/src/
COPY validators/ /opt/v5/validators/
COPY config/     /opt/v5/config/
COPY scripts/consensus_rank.py /opt/v5/scripts/consensus_rank.py
COPY runpod/esmfold_worker.py  /opt/v5/runpod/esmfold_worker.py
COPY runpod/entrypoint_tri.sh  /workspace/entrypoint.sh
RUN chmod +x /workspace/entrypoint.sh && mkdir -p /workspace/outputs /workspace/logs

ENV XLA_PYTHON_CLIENT_MEM_FRACTION=0.9 \
    MOSAIC_ESMFOLD_PYTHON=/opt/esmfold/.venv/bin/python \
    PYTHONPATH=/opt/v5 \
    PATH="/opt/mosaic/.venv/bin:/root/.local/bin:$PATH" \
    VIRTUAL_ENV=/opt/mosaic/.venv

WORKDIR /opt/mosaic
ENTRYPOINT ["/bin/bash"]
