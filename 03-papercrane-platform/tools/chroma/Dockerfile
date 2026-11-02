FROM ghcr.io/papercrane/base-cuda12:latest

ARG CHROMA_SHA=TODO_CHROMA_SHA
WORKDIR /opt

# Clone upstream Chroma at a pinned commit for reproducibility. The pip-installed
# `generate-chroma` package supplies the runtime library; the cloned source is
# kept around for reference/CLI entrypoints that upstream ships as scripts.
RUN git clone https://github.com/generatebio/chroma.git /opt/chroma \
 && cd /opt/chroma && git checkout ${CHROMA_SHA}

# Chroma-specific Python deps. torch/numpy already in base-cuda12.
# `generate-chroma` pulls in its own diffusion + GNN stack.
RUN pip install --no-cache-dir \
      generate-chroma==1.0.0 \
      biotite==0.40.0 \
      einops==0.7.0 \
      pyyaml==6.0.1

# Chroma weights are licensed (Apache-2.0) and gated behind Generate Biomedicines'
# HuggingFace / direct-download flow. Baked into the image at build time when a
# reachable URL is supplied; otherwise fetched at container start by run.sh.
# TODO: replace CHROMA_WEIGHTS_URL with the real signed URL/HF repo.
ARG CHROMA_WEIGHTS_URL=TODO_WEIGHTS_URL
RUN mkdir -p /opt/chroma/weights \
 && if [ "${CHROMA_WEIGHTS_URL}" != "TODO_WEIGHTS_URL" ]; then \
      wget -q -O /opt/chroma/weights/chroma_backbone.pt "${CHROMA_WEIGHTS_URL}"; \
    fi

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
