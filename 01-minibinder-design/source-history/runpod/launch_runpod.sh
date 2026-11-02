#!/bin/bash
# Stage the bundle onto a running RunPod pod and start the scoring run.
#
# Usage:
#   export POD_HOST=... POD_PORT=...     # DIRECT ssh, NOT the proxy (see README)
#   ./runpod/launch_runpod.sh designs.fasta 5G51.cif
set -euo pipefail

SEQ_FILE="${1:?usage: launch_runpod.sh <designs.fasta|csv> [target.cif]}"
TARGET="${2:-}"
POD_HOST="${POD_HOST:?set POD_HOST (direct ssh host, e.g. 213.x.x.x)}"
POD_PORT="${POD_PORT:-22}"
POD_USER="${POD_USER:-root}"
SSH="ssh -p $POD_PORT -o StrictHostKeyChecking=no ${POD_USER}@${POD_HOST}"

echo ">>> staging to ${POD_USER}@${POD_HOST}:${POD_PORT}"
$SSH "mkdir -p /workspace/in /workspace/outputs"
scp -P "$POD_PORT" -o StrictHostKeyChecking=no "$SEQ_FILE" \
    "${POD_USER}@${POD_HOST}:/workspace/in/$(basename "$SEQ_FILE")"
REMOTE_TARGET="/opt/mosaic/5G51.cif"
if [ -n "$TARGET" ]; then
    scp -P "$POD_PORT" -o StrictHostKeyChecking=no "$TARGET" \
        "${POD_USER}@${POD_HOST}:/workspace/in/$(basename "$TARGET")"
    REMOTE_TARGET="/workspace/in/$(basename "$TARGET")"
fi

# Detached with nohup: an ssh drop must not kill a multi-hour scoring run.
$SSH "cd /workspace && \
  SEQUENCES=/workspace/in/$(basename "$SEQ_FILE") \
  TARGET_CIF=$REMOTE_TARGET \
  nohup bash /workspace/entrypoint.sh > /workspace/logs/nohup.log 2>&1 &
  echo started"

cat <<EOF

>>> running detached. Poll with:
    $SSH 'cat /workspace/outputs/DONE 2>/dev/null || tail -5 /workspace/logs/nohup.log'

>>> fetch results when DONE says OK:
    scp -P $POD_PORT ${POD_USER}@${POD_HOST}:/workspace/outputs/tri_scores.csv .

>>> STOP THE POD when finished. H100 at ~\$2.59/hr bills whether or not it is working.
EOF
