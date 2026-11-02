# Paper Crane CPU base image
# Python 3.11 slim + pinned scientific stack (no PyTorch).
# Target size: <2 GB. Use for validators, orchestrators, and lightweight tools
# that don't need CUDA.

FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/papercrane-bio/papercrane"
LABEL org.opencontainers.image.description="Paper Crane CPU base (Python 3.11 slim)"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# System deps. slim-bookworm is bare — we need compilers for gemmi/scipy wheels
# on unusual arches, plus git/wget/curl for runtime fetches.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        wget \
        curl \
        ca-certificates \
    && python -m pip install --no-cache-dir --upgrade pip==24.0 setuptools==70.0.0 wheel==0.43.0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Pinned scientific + bio stack — identical versions to base-cuda12/Dockerfile.
# No PyTorch in the CPU base; downstream images that need CPU torch can add
# `pip install torch==2.3.1 --index-url https://download.pytorch.org/whl/cpu`.
RUN pip install --no-cache-dir \
        numpy==1.26.4 \
        scipy==1.11.4 \
        biopython==1.83 \
        gemmi==0.6.5 \
        pandas==2.2.2 \
        requests==2.32.3 \
        boto3==1.34.131 \
        tqdm==4.66.4 \
        pydantic==2.7.1 \
        pyyaml==6.0.1

# Scaffold mirrors base-cuda12 so tool adapters can target either base.
RUN mkdir -p /opt/papercrane /inputs /outputs \
    && chmod 755 /inputs /outputs

COPY run.sh.example /opt/papercrane/run.sh
RUN chmod +x /opt/papercrane/run.sh

WORKDIR /opt/papercrane

ENTRYPOINT ["/opt/papercrane/run.sh"]
