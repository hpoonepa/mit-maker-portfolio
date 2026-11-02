FROM ghcr.io/papercrane/base-cuda12:latest

# ESM-2 needs fair-esm (canonical reference impl) *and* HuggingFace
# transformers (used by papercrane.esm2_runner for tokenizer + masked-LM pLL).
RUN pip install --no-cache-dir \
      fair-esm==2.0.0 \
      "transformers>=4.40,<5" \
      "accelerate>=0.27" \
      "numpy>=1.24"

# Weight cache: point HF + torch hub at /opt/esm-weights. In production this
# path is a Modal Volume mount (see README — weights lazy-loaded on first run
# and shared across subsequent invocations). Baking the ~2.6 GB weights into
# the image is supported for air-gapped deploys — uncomment the RUN below.
ENV TRANSFORMERS_CACHE=/opt/esm-weights \
    HF_HOME=/opt/esm-weights \
    TORCH_HOME=/opt/esm-weights/torch
RUN mkdir -p /opt/esm-weights

# ---- Optional: bake weights into the image (adds ~2.6 GB). --------------- #
# Uncomment for offline / air-gapped runs. Default deployment uses a Modal
# Volume mounted at /opt/esm-weights so multiple workers share one copy.
# RUN python -c "from transformers import AutoModel, AutoTokenizer; \
#     AutoTokenizer.from_pretrained('facebook/esm2_t33_650M_UR50D'); \
#     AutoModel.from_pretrained('facebook/esm2_t33_650M_UR50D')"

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
