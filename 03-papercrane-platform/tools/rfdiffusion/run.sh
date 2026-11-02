#!/usr/bin/env bash
set -euo pipefail

# Fallback: fetch weights at runtime if not baked into the image.
if [ ! -f /opt/rfdiffusion/models/Base_ckpt.pt ]; then
  if [ -n "${RFDIFFUSION_WEIGHTS_URL:-}" ]; then
    echo "[rfdiffusion] fetching weights from ${RFDIFFUSION_WEIGHTS_URL}"
    mkdir -p /opt/rfdiffusion/models
    wget -q -O /opt/rfdiffusion/models/Base_ckpt.pt "${RFDIFFUSION_WEIGHTS_URL}"
  else
    echo "[rfdiffusion] WARNING: no weights present and RFDIFFUSION_WEIGHTS_URL unset" >&2
  fi
fi

python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --target /inputs/target.pdb \
  --output /outputs
