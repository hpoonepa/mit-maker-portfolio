#!/usr/bin/env bash
# Provision a single Nebius H100 VM for the 5G51 V4 campaign.
# Prerequisites (see nebius/README.md): nebius CLI installed + `nebius profile create`
# done, H100 GPU quota granted, NEBIUS_PROJECT_ID and NEBIUS_SUBNET_ID exported,
# SSH key at $NEBIUS_SSH_KEY (default ~/.ssh/id_ed25519).
set -euo pipefail

# Make the nebius CLI reachable when it was installed to ~/.nebius/bin (the
# default install location). Without this, scripts run from a non-interactive
# shell (e.g. Claude Code's Bash tool) won't find the binary.
export PATH="$HOME/.nebius/bin:$PATH"

# Source local launch config (project/subnet IDs) if present.
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$HERE/.env" ] && set -a && . "$HERE/.env" && set +a

INSTANCE_NAME="mosaic-5g51-v5"
DISK_NAME="mosaic-5g51-v5-disk"
# Defaults: 8x H200 for parallel fan-out (run_campaign.py supports --max-parallel 8).
# Override at run time, e.g. for a single GPU smoke test:
#   NEBIUS_PRESET=1gpu-16vcpu-200gb ./provision.sh
PLATFORM="${NEBIUS_PLATFORM:-gpu-h200-sxm}"
PRESET="${NEBIUS_PRESET:-8gpu-128vcpu-1600gb}"
IMAGE_FAMILY="ubuntu24.04-cuda12"
DISK_GIB=200
SSH_KEY_PATH="${NEBIUS_SSH_KEY:-$HOME/.ssh/id_ed25519}"

# --- Preflight checks ---
command -v nebius >/dev/null 2>&1 || {
  echo "ERROR: 'nebius' CLI not found. Install it and run 'nebius profile create'." >&2
  exit 1
}
nebius iam get-access-token >/dev/null 2>&1 || {
  echo "ERROR: nebius CLI not authenticated. Run 'nebius profile create'." >&2
  exit 1
}
: "${NEBIUS_PROJECT_ID:?Set NEBIUS_PROJECT_ID (see nebius/README.md)}"
: "${NEBIUS_SUBNET_ID:?Set NEBIUS_SUBNET_ID (see nebius/README.md)}"
[ -f "${SSH_KEY_PATH}.pub" ] || {
  echo "ERROR: SSH public key ${SSH_KEY_PATH}.pub not found." >&2
  exit 1
}

echo ">> Creating boot disk ($DISK_GIB GiB, $IMAGE_FAMILY)..."
DISK_ID=$(nebius compute disk create \
  --name "$DISK_NAME" \
  --parent-id "$NEBIUS_PROJECT_ID" \
  --size-gibibytes "$DISK_GIB" \
  --type network_ssd \
  --source-image-family-image-family "$IMAGE_FAMILY" \
  --format json | jq -r '.metadata.id')
echo "   disk: $DISK_ID"

# cloud-init: inject SSH key + install Docker (CUDA image has NVIDIA toolkit, not Docker).
CLOUD_INIT=$(cat <<EOF
#cloud-config
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - $(cat "${SSH_KEY_PATH}.pub")
runcmd:
  - curl -fsSL https://get.docker.com | sh
  - usermod -aG docker ubuntu
  - nvidia-ctk runtime configure --runtime=docker || true
  - systemctl restart docker
EOF
)

echo ">> Creating instance ($PLATFORM / $PRESET)..."
INSTANCE_ID=$(nebius compute instance create \
  --name "$INSTANCE_NAME" \
  --parent-id "$NEBIUS_PROJECT_ID" \
  --resources-platform "$PLATFORM" \
  --resources-preset "$PRESET" \
  --boot-disk-existing-disk-id "$DISK_ID" \
  --boot-disk-attach-mode read_write \
  --cloud-init-user-data "$CLOUD_INIT" \
  --network-interfaces "[{\"name\":\"eth0\",\"ip_address\":{},\"public_ip_address\":{},\"subnet_id\":\"$NEBIUS_SUBNET_ID\"}]" \
  --format json | jq -r '.metadata.id')
echo "   instance: $INSTANCE_ID"

echo ">> Waiting for RUNNING + public IP..."
for i in $(seq 1 30); do
  INFO=$(nebius compute instance get --id "$INSTANCE_ID" --format json 2>/dev/null || true)
  STATE=$(echo "$INFO" | jq -r '.status.state // empty' 2>/dev/null || true)
  IP=$(echo "$INFO" | jq -r '.status.network_interfaces[0].public_ip_address.address // empty' 2>/dev/null | sed 's|/.*||' || true)
  if [ "$STATE" = "RUNNING" ] && [ -n "$IP" ]; then break; fi
  sleep 20
done
[ -n "${IP:-}" ] || { echo "ERROR: instance did not reach RUNNING with a public IP." >&2; exit 1; }

echo ""
echo "============================================================"
echo " VM READY"
echo "   instance id : $INSTANCE_ID"
echo "   public ip   : $IP"
echo "   ssh         : ssh -i $SSH_KEY_PATH ubuntu@$IP"
echo ""
echo " TEARDOWN when done:"
echo "   nebius compute instance delete --id $INSTANCE_ID"
echo "============================================================"

# Persist for the other scripts.
mkdir -p "$(dirname "$0")/.state"
echo "$INSTANCE_ID" > "$(dirname "$0")/.state/instance_id"
echo "$IP" > "$(dirname "$0")/.state/instance_ip"

# NOTE: Some nebius CLI details below were not 100% confirmed at plan time and
# should be verified against `nebius ... --help` or actual JSON output before relying on them:
#   - JSON paths for state/IP in `instance get` output (.status.state,
#     .status.network_interfaces[0].public_ip_address.address)
#   - whether `instance get --id` is the right query verb (alternative:
#     `instance get-by-name --parent-id ... --name ...`)
