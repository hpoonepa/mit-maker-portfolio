#!/usr/bin/env bash
# Poll for 8xH200 capacity on Nebius every 30 min until provisioning succeeds.
# Cleans up the STOPPED instance + READY disk that Nebius leaves behind after
# each "Not enough resources" failure (otherwise the name collides on retry).
# Exits 0 with the VM up + IP recorded in nebius/.state/ when successful.
# Exits 1 after MAX_ATTEMPTS (default 48 = 24 hours) with no success.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="${HERE}/poll_for_8gpu.log"
INTERVAL="${POLL_INTERVAL_SECONDS:-1800}"   # 30 min default
MAX_ATTEMPTS="${MAX_ATTEMPTS:-48}"          # 24 hours of retries default
PROJECT_ID="$(grep '^export NEBIUS_PROJECT_ID' "${HERE}/.env" | sed -E 's/.*"([^"]+)".*/\1/')"
NEBIUS="$HOME/.nebius/bin/nebius"

if [ -z "$PROJECT_ID" ]; then
  echo "ERROR: could not read NEBIUS_PROJECT_ID from ${HERE}/.env" >&2
  exit 2
fi

ts() { date -u "+%Y-%m-%dT%H:%M:%SZ"; }

cleanup_orphans() {
  # Delete any instance named mosaic-5g51-v5 and any disk named mosaic-5g51-v5-disk.
  echo "[$(ts)] cleaning orphans..." >> "$LOG"
  $NEBIUS compute instance list --parent-id "$PROJECT_ID" --format json 2>/dev/null \
    | python3 -c "
import sys, json
for i in json.load(sys.stdin).get('items', []):
    if i['metadata'].get('name') == 'mosaic-5g51-v5':
        print(i['metadata']['id'])
" 2>/dev/null | while read -r IID; do
      [ -n "$IID" ] && $NEBIUS compute instance delete --id "$IID" >> "$LOG" 2>&1 || true
    done
  # Give the API a moment.
  sleep 5
  $NEBIUS compute disk list --parent-id "$PROJECT_ID" --format json 2>/dev/null \
    | python3 -c "
import sys, json
for i in json.load(sys.stdin).get('items', []):
    if i['metadata'].get('name') == 'mosaic-5g51-v5-disk':
        print(i['metadata']['id'])
" 2>/dev/null | while read -r DID; do
      [ -n "$DID" ] && $NEBIUS compute disk delete --id "$DID" >> "$LOG" 2>&1 || true
    done
}

echo "[$(ts)] === starting 8xH200 capacity poll, every ${INTERVAL}s, max ${MAX_ATTEMPTS} attempts ===" >> "$LOG"

ATTEMPT=0
while [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "[$(ts)] attempt $ATTEMPT/$MAX_ATTEMPTS ..." >> "$LOG"

  if "${HERE}/provision.sh" >> "$LOG" 2>&1; then
    if [ -s "${HERE}/.state/instance_ip" ]; then
      echo "[$(ts)] SUCCESS on attempt $ATTEMPT — VM up at $(cat ${HERE}/.state/instance_ip)" >> "$LOG"
      exit 0
    fi
    echo "[$(ts)] provision.sh exited 0 but no .state/instance_ip — treating as failure" >> "$LOG"
  fi

  echo "[$(ts)] attempt $ATTEMPT failed; cleaning up and waiting ${INTERVAL}s" >> "$LOG"
  cleanup_orphans
  sleep "$INTERVAL"
done

echo "[$(ts)] GIVING UP after $MAX_ATTEMPTS attempts" >> "$LOG"
exit 1
