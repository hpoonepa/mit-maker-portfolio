#!/usr/bin/env bash
set -euo pipefail
python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --target /inputs/target.pdb \
  --output /outputs
