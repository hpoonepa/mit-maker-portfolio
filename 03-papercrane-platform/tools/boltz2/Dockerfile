FROM ghcr.io/papercrane/base-cuda12:latest

ARG BOLTZ2_SHA=TODO
WORKDIR /opt

# Boltz-2 ships on PyPI; the SHA arg is kept for reproducibility and can be
# swapped for a git install when the user needs an unreleased upstream fix.
RUN pip install --no-cache-dir boltz==2.0.0

# Model weights are NOT baked into the image — they are large (~5 GB) and
# licensed separately. The platform mounts a Modal persistent volume at
# /root/.boltz (see README "Model weights"); on first launch `boltz predict`
# downloads them into that volume so subsequent jobs reuse the cache.
ENV BOLTZ_CACHE=/root/.boltz

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
