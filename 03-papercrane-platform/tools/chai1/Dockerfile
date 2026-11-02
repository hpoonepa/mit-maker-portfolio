FROM ghcr.io/papercrane/base-cuda12:latest

ARG CHAI1_SHA=TODO_CHAI1_SHA
ARG CHAI_LAB_VERSION=0.5.1

WORKDIR /opt

# Chai-1 is distributed via PyPI as `chai_lab`. Pin the version for
# reproducibility; the upstream source SHA is tracked via CHAI1_SHA for audit
# even though we install from the published wheel.
RUN pip install --no-cache-dir "chai_lab==${CHAI_LAB_VERSION}"

# Weights are downloaded lazily at runtime into /opt/chai-weights (see README).
# This keeps the image small; the job runner mounts a shared weights cache
# volume so the first-run download is amortized across jobs.
ENV CHAI_WEIGHTS_DIR=/opt/chai-weights
RUN mkdir -p "${CHAI_WEIGHTS_DIR}"

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas
COPY LICENSE-GATE.md /opt/papercrane/LICENSE-GATE.md

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
