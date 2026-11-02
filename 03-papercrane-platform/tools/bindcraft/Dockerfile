FROM ghcr.io/papercrane/base-cuda12:latest

ARG BINDCRAFT_SHA=TODO_BINDCRAFT_SHA
WORKDIR /opt

RUN git clone https://github.com/martinpacesa/BindCraft.git /opt/bindcraft \
 && cd /opt/bindcraft && git checkout ${BINDCRAFT_SHA} \
 && pip install --no-cache-dir -r requirements.txt

COPY adapter.py /opt/papercrane/adapter.py
COPY run.sh /opt/papercrane/run.sh
COPY manifest.json /opt/papercrane/manifest.json
COPY schemas /opt/papercrane/schemas

RUN chmod +x /opt/papercrane/run.sh

ENTRYPOINT ["/opt/papercrane/run.sh"]
