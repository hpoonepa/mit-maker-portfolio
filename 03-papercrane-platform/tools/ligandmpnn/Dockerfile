FROM ghcr.io/papercrane/base-cuda12:latest

# Pinned to last commit on dauparas/LigandMPNN main as of 2026-06-02
# (commit date 2025-02-06). Keep in sync with tools/ligandmpnn/modal_app.py
# LIGANDMPNN_SHA.
ARG LIGANDMPNN_SHA=26ec57ac976ade5379920dbd43c7f97a91cf82de
WORKDIR /opt

RUN git clone https://github.com/dauparas/LigandMPNN.git /opt/ligandmpnn \
 && cd /opt/ligandmpnn && git checkout ${LIGANDMPNN_SHA}

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
