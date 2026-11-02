#!/bin/bash
# Runs the entire seed-loop ON the VM, so SSH instability can't kill it.
# Driven by a SEEDS env var (space-separated list); writes per-seed DONE markers
# and a final /tmp/campaign.done marker the local controller polls for.
set -u

: "${SEEDS:?SEEDS env required (space-separated)}"
IMAGE="${IMAGE:-mosaic-design:5g51-v5-hotspots}"
CONFIG_PATH="${CONFIG_PATH:-/opt/v5/config/v5_5g51_hotspots.yaml}"
TARGET_CIF="${TARGET_CIF:-5G51.cif}"
XLA_MEM="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.9}"
ROOT="${ROOT:-/workspace/outputs}"
CAMPAIGN_LOG="${CAMPAIGN_LOG:-/tmp/vm_campaign.log}"
CAMPAIGN_DONE="${CAMPAIGN_DONE:-/tmp/vm_campaign.done}"

rm -f "$CAMPAIGN_DONE"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === vm_campaign starting, seeds=$SEEDS ===" > "$CAMPAIGN_LOG"

OK=0
FAIL=0
for SEED in $SEEDS; do
  PADDED=$(printf "%03d" "$SEED")
  OUT="$ROOT/seed_${PADDED}"
  mkdir -p "$OUT"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] >>> seed $SEED start" >> "$CAMPAIGN_LOG"

  docker run --rm --gpus all \
    -e "SEED=$SEED" \
    -e "CONFIG_PATH=$CONFIG_PATH" \
    -e "TARGET_CIF=$TARGET_CIF" \
    -e "XLA_PYTHON_CLIENT_MEM_FRACTION=$XLA_MEM" \
    -v "$ROOT:$ROOT" \
    "$IMAGE" /workspace/entrypoint.sh \
    >> "$CAMPAIGN_LOG" 2>&1
  RC=$?

  if [ $RC -eq 0 ] && [ -s "$OUT/csv_line.txt" ]; then
    OK=$((OK + 1))
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] <<< seed $SEED ok ($(cat $OUT/csv_line.txt))" >> "$CAMPAIGN_LOG"
  else
    FAIL=$((FAIL + 1))
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] <<< seed $SEED FAILED (rc=$RC)" >> "$CAMPAIGN_LOG"
  fi
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === vm_campaign done: ok=$OK fail=$FAIL ===" >> "$CAMPAIGN_LOG"
echo "$OK ok, $FAIL fail" > "$CAMPAIGN_DONE"
