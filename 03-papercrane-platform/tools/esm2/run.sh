#!/usr/bin/env bash
set -euo pipefail
python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --output  /outputs
