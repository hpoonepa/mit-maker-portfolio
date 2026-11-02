# Paper Crane GPU base image
# CUDA 12.1 + cuDNN 8 + Python 3.11 + PyTorch 2.3.1 (cu121) + pinned scientific stack.
# Target size: <8 GB. Tool adapter images should FROM this and override CMD/ENTRYPOINT.

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

LABEL org.opencontainers.image.source="https://github.com/papercrane-bio/papercrane"
LABEL org.opencontainers.image.description="Paper Crane GPU base (CUDA 12.1, PyTorch 2.3.1)"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# System deps. Keep this list minimal — downstream tool images can add more.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-dev \
        python3.11-venv \
        python3-pip \
        git \
        build-essential \
        wget \
        curl \
        ca-certificates \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && python -m pip install --no-cache-dir --upgrade pip==24.0 setuptools==70.0.0 wheel==0.43.0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# PyTorch 2.3.1 built against CUDA 12.1.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cu121 \
        torch==2.3.1 \
        torchvision==0.18.1

# Pinned scientific + bio stack — identical versions in base-cpu/Dockerfile.
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

# Scaffold: /inputs mounted read-only at runtime, /outputs writable.
RUN mkdir -p /opt/papercrane /inputs /outputs \
    && chmod 755 /inputs /outputs

# Default entrypoint stub — tool adapter images override this.
COPY run.sh.example /opt/papercrane/run.sh
RUN chmod +x /opt/papercrane/run.sh

WORKDIR /opt/papercrane

ENTRYPOINT ["/opt/papercrane/run.sh"]
