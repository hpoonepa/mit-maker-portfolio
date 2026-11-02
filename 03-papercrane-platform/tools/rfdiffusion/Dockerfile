FROM ghcr.io/papercrane/base-cuda12:latest

ARG RFDIFFUSION_SHA=TODO_RFDIFFUSION_SHA
WORKDIR /opt

# Clone upstream RFdiffusion at a pinned commit.
RUN git clone https://github.com/RosettaCommons/RFdiffusion.git /opt/rfdiffusion \
 && cd /opt/rfdiffusion && git checkout ${RFDIFFUSION_SHA}

# RFdiffusion-specific Python deps (schnetpack + hydra pin per upstream
# env.yml). torch/numpy already in base-cuda12.
RUN pip install --no-cache-dir \
      hydra-core==1.3.2 \
      schnetpack==1.0.1 \
      e3nn==0.3.3 \
      dgl==1.0.1 \
      omegaconf==2.3.0 \
      icecream==2.1.3

# Upstream ships weights separately (Baker lab GDrive / HF mirror). Baked into
# the image at build time when a reachable URL is supplied; otherwise fetched
# at container start by run.sh (fallback path).
# TODO: replace RFDIFFUSION_WEIGHTS_URL with the real signed URL/HF repo.
ARG RFDIFFUSION_WEIGHTS_URL=TODO_WEIGHTS_URL
RUN mkdir -p /opt/rfdiffusion/models \
 && if [ "${RFDIFFUSION_WEIGHTS_URL}" != "TODO_WEIGHTS_URL" ]; then \
      wget -q -O /opt/rfdiffusion/models/Base_ckpt.pt "${RFDIFFUSION_WEIGHTS_URL}"; \
    fi

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
