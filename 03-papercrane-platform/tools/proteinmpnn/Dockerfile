FROM ghcr.io/papercrane/base-cuda12:latest

# Pinned to last commit on dauparas/ProteinMPNN main as of 2026-06-02
# (commit date 2023-06-27). Keep in sync with tools/proteinmpnn/modal_app.py
# PROTEINMPNN_COMMIT.
ARG PROTEINMPNN_SHA=8907e6671bfbfc92303b5f79c4b5e6ce47cdef57
WORKDIR /opt

RUN git clone https://github.com/dauparas/ProteinMPNN.git /opt/proteinmpnn \
 && cd /opt/proteinmpnn && git checkout ${PROTEINMPNN_SHA}

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
