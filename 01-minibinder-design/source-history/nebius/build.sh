#!/usr/bin/env bash
# Rsync the mosaic working tree onto the VM and build both Docker images.
# Run AFTER provision.sh. Reads the VM IP from nebius/.state/instance_ip.
#
# The mosaic project is not a git repo, so we rsync the local tree rather than
# git-cloning a remote.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MOSAIC_ROOT="$(cd "$HERE/.." && pwd)"
IP=$(cat "$HERE/.state/instance_ip")
SSH_KEY_PATH="${NEBIUS_SSH_KEY:-$HOME/.ssh/id_ed25519}"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $SSH_KEY_PATH"
SSH="ssh $SSH_OPTS ubuntu@$IP"
REMOTE_REPO="/opt/mosaic-src"

echo ">> Waiting for Docker on the VM (cloud-init still installing it)..."
for i in $(seq 1 30); do
  if $SSH "docker --version" >/dev/null 2>&1; then echo "   docker ready"; break; fi
  sleep 20
done
$SSH "docker --version" >/dev/null 2>&1 || { echo "ERROR: Docker not ready on VM." >&2; exit 1; }

echo ">> Preparing remote repo dir..."
$SSH "sudo mkdir -p $REMOTE_REPO && sudo chown -R ubuntu:ubuntu $REMOTE_REPO"

echo ">> Rsyncing working tree to VM (excluding large unrelated dirs)..."
rsync -az --delete \
  -e "ssh $SSH_OPTS" \
  --exclude 'papercrane/' \
  --exclude 'hive/' \
  --exclude 'CLAUDEVAULT/' \
  --exclude 'olas-defi-agent/' \
  --exclude 'stocks/' \
  --exclude 'rna2/' \
  --exclude '*_outputs*/' \
  --exclude 'modal_outputs*/' \
  --exclude 'boltz2_outputs*/' \
  --exclude 'god_outputs*/' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'nebius/.venv' \
  --exclude 'nebius/outputs' \
  --exclude 'nebius/checkpoints' \
  --exclude 'nebius/.state' \
  --exclude 'vast/__pycache__' \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude 'node_modules' \
  --exclude '.next' \
  "$MOSAIC_ROOT/" "ubuntu@$IP:$REMOTE_REPO/"

echo ">> Building design image (mosaic-design:5g51-v4)..."
$SSH "cd $REMOTE_REPO && docker build -f nebius/Dockerfile -t mosaic-design:5g51-v4 ."

echo ">> Building boltz2 image (mosaic-boltz2:5g51-v4)..."
$SSH "cd $REMOTE_REPO && docker build -f nebius/Dockerfile.boltz2 -t mosaic-boltz2:5g51-v4 ."

echo ">> Images on VM:"
$SSH "docker images | grep mosaic"
echo ">> Build complete."
