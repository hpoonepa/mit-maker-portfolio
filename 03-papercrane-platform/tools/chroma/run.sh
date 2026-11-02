#!/usr/bin/env bash
set -euo pipefail

# Fallback: fetch weights at runtime if not baked into the image.
if [ ! -f /opt/chroma/weights/chroma_backbone.pt ]; then
  if [ -n "${CHROMA_WEIGHTS_URL:-}" ]; then
    echo "[chroma] fetching weights from ${CHROMA_WEIGHTS_URL}"
    mkdir -p /opt/chroma/weights
    wget -q -O /opt/chroma/weights/chroma_backbone.pt "${CHROMA_WEIGHTS_URL}"
  else
    echo "[chroma] WARNING: no weights present and CHROMA_WEIGHTS_URL unset" >&2
  fi
fi

# Target PDB is optional for Chroma — unconditional generation is a first-class
# mode. Only the request.json is required.
TARGET_ARG=()
if [ -f /inputs/target.pdb ]; then
  TARGET_ARG=(--target /inputs/target.pdb)
fi

python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  "${TARGET_ARG[@]}" \
  --output /outputs
