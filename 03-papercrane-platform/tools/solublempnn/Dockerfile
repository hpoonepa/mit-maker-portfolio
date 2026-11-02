FROM ghcr.io/papercrane/base-cuda12:latest

# SolubleMPNN ships inside the ProteinMPNN repo; the only functional delta is
# the checkpoint name loaded at runtime (`soluble_v_48_020.pt`). Pin the repo
# SHA here and let the adapter pass --model_name through.
# Same SHA as proteinmpnn — SolubleMPNN's weights ship inside the
# dauparas/ProteinMPNN repo at `soluble_model_weights/`. Pinned to last commit
# on main as of 2026-06-02 (commit date 2023-06-27). Keep in sync with
# tools/solublempnn/modal_app.py PROTEINMPNN_SHA and with
# tools/proteinmpnn/Dockerfile PROTEINMPNN_SHA.
ARG SOLUBLEMPNN_SHA=8907e6671bfbfc92303b5f79c4b5e6ce47cdef57
WORKDIR /opt

RUN git clone https://github.com/dauparas/ProteinMPNN.git /opt/solublempnn \
 && cd /opt/solublempnn && git checkout ${SOLUBLEMPNN_SHA}

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
