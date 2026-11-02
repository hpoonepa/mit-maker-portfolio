FROM ghcr.io/papercrane/base-cuda12:latest

ARG BOLTZGEN_SHA=TODO_BOLTZGEN_SHA
WORKDIR /opt

RUN git clone https://github.com/jwohlwend/boltzgen.git /opt/boltzgen \
 && cd /opt/boltzgen && git checkout ${BOLTZGEN_SHA} \
 && pip install --no-cache-dir -r requirements.txt

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
