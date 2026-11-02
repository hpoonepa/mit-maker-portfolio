# Paper Crane canonical-metrics validator.
#
# Runs as stage-2 after any design tool (BindCraft, RFdiffusion, Boltz-2, ...)
# has populated /outputs. Reads /inputs/designs.json plus the existing
# /outputs/*.pdb files, computes ipSAE / DockQ / pTMEnergy / LIS / Overath /
# hotspot contact / ESM2 pLL, and writes /outputs/validated.json.
#
# Target: A10 or T4 GPU at runtime (smaller than design-stage tools — the
# only metric that touches the GPU today is ESM2 pLL, and it is happy on
# 16 GB VRAM).
#
# Image size budget: base-cuda12 (~8 GB) + fair-esm + weights mounted at
# runtime -> should stay under 9 GB on disk without weights baked in.
FROM ghcr.io/papercrane/base-cuda12:latest

LABEL org.opencontainers.image.source="https://github.com/papercrane-bio/papercrane"
LABEL org.opencontainers.image.description="Paper Crane canonical-metrics validator"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# --- Python deps ---------------------------------------------------------
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# --- Validator package ---------------------------------------------------
# Copy the `src/` layout into /opt/papercrane/validator, then make the
# package importable as `papercrane_validator` on the PYTHONPATH.
COPY src /opt/papercrane/validator/src
ENV PYTHONPATH="/opt/papercrane/validator/src:${PYTHONPATH}"

# Weights mount point for ESM2. Empty by default — the runner mounts a
# read-only volume here (see docs/plans/02-tool-integration.md §5). If the
# directory is empty at runtime, esm_pll.py falls back to a heuristic.
RUN mkdir -p /opt/papercrane/weights/esm2

# --- Entrypoint ----------------------------------------------------------
# The base image already declares ENTRYPOINT ["/opt/papercrane/run.sh"] —
# we override the FILE via COPY so we don't need a second ENTRYPOINT line.
COPY run.sh /opt/papercrane/run.sh
RUN chmod +x /opt/papercrane/run.sh

# --- Smoke-test hook ----------------------------------------------------
# CI can override the entrypoint to run pytest against the bundled fixtures
# to validate that the image is well-formed before promoting it to `latest`.
COPY tests /opt/papercrane/validator/tests

# Documented default invocation. Tool runner mounts /inputs + /outputs and
# optionally /opt/papercrane/weights/esm2 before calling the entrypoint.
