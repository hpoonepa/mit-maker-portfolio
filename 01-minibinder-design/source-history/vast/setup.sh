#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Vast.ai Campaign Setup
# Installs prerequisites and verifies environment for running campaigns.
# ---------------------------------------------------------------------------

# -- Colors -----------------------------------------------------------------
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

ok()   { echo -e "${GREEN}[OK]${NC}    $1"; }
err()  { echo -e "${RED}[ERR]${NC}   $1"; }
skip() { echo -e "${YELLOW}[SKIP]${NC}  $1"; }
info() { echo -e "${CYAN}[INFO]${NC}  $1"; }

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo -e "${BOLD}Vast.ai Campaign Setup${NC}"
echo "======================================"
echo ""

# -- 1. vastai CLI ----------------------------------------------------------
info "Checking vastai CLI..."
if command -v vastai &>/dev/null; then
    ok "vastai CLI already installed ($(vastai --version 2>/dev/null || echo 'unknown version'))"
else
    info "Installing vastai CLI via pip..."
    if pip install vastai; then
        ok "vastai CLI installed"
    else
        err "Failed to install vastai CLI. Make sure pip is available."
        exit 1
    fi
fi

# -- 2. Docker ---------------------------------------------------------------
info "Checking Docker..."
if ! command -v docker &>/dev/null; then
    err "Docker is not installed. Install it from https://docs.docker.com/get-docker/"
    exit 1
fi

if docker info &>/dev/null; then
    ok "Docker is installed and running"
else
    err "Docker is installed but the daemon is not running. Start Docker Desktop or the docker service."
    exit 1
fi

# -- 3. Vast.ai API key ------------------------------------------------------
info "Checking Vast.ai API key..."
VASTAI_KEY_FILE="$HOME/.vastai_api_key"

if [ -n "$VASTAI_API_KEY" ]; then
    ok "VASTAI_API_KEY is set in environment"
    # Persist to file so vastai CLI can use it
    if [ ! -f "$VASTAI_KEY_FILE" ]; then
        echo "$VASTAI_API_KEY" > "$VASTAI_KEY_FILE"
        chmod 600 "$VASTAI_KEY_FILE"
        ok "Saved API key to $VASTAI_KEY_FILE"
    fi
elif [ -f "$VASTAI_KEY_FILE" ]; then
    ok "API key found at $VASTAI_KEY_FILE"
    export VASTAI_API_KEY="$(cat "$VASTAI_KEY_FILE")"
else
    echo ""
    read -rp "Enter your Vast.ai API key: " api_key
    if [ -z "$api_key" ]; then
        err "No API key provided. Get one at https://cloud.vast.ai/account/"
        exit 1
    fi
    echo "$api_key" > "$VASTAI_KEY_FILE"
    chmod 600 "$VASTAI_KEY_FILE"
    export VASTAI_API_KEY="$api_key"
    ok "API key saved to $VASTAI_KEY_FILE"
fi

# Configure vastai CLI with the key
vastai set api-key "$(cat "$VASTAI_KEY_FILE")" &>/dev/null || true

# -- 4. Verify vastai auth ---------------------------------------------------
info "Verifying Vast.ai authentication..."
if vastai show machines &>/dev/null; then
    ok "Vast.ai authentication successful"
else
    err "Vast.ai authentication failed. Check your API key."
    err "Update $VASTAI_KEY_FILE or set VASTAI_API_KEY and re-run."
    exit 1
fi

# -- 5. Local directories ----------------------------------------------------
info "Creating local directories..."

for dir in vast_outputs vast_checkpoints; do
    target="$PROJECT_ROOT/$dir"
    if [ -d "$target" ]; then
        skip "$target already exists"
    else
        mkdir -p "$target"
        ok "Created $target"
    fi
done

# -- 6. SSH key ---------------------------------------------------------------
info "Checking SSH key..."
SSH_KEY="$HOME/.ssh/id_rsa"

if [ -f "$SSH_KEY" ]; then
    ok "SSH key exists at $SSH_KEY"
else
    info "Generating SSH key pair..."
    mkdir -p "$HOME/.ssh"
    ssh-keygen -t rsa -b 4096 -f "$SSH_KEY" -N "" -C "vastai-campaign"
    ok "SSH key generated at $SSH_KEY"
fi

# -- Quick-start guide -------------------------------------------------------
echo ""
echo "======================================"
echo -e "${BOLD}${GREEN}Setup complete!${NC}"
echo "======================================"
echo ""
echo -e "${BOLD}Quick Start:${NC}"
echo ""
echo "  1. Build Docker images:"
echo -e "     ${CYAN}bash vast/build_and_push.sh${NC}"
echo ""
echo "  2. Run RBX1 design campaign (50 seeds):"
echo -e "     ${CYAN}python -m vast.vast_2lgv --num-seeds 50${NC}"
echo ""
echo "  3. Monitor progress:"
echo -e "     ${CYAN}python -m vast.monitor --campaign rbx1-design${NC}"
echo ""
echo "  4. Resume if interrupted:"
echo -e "     ${CYAN}python -m vast.resume resume rbx1-design${NC}"
echo ""
echo "  5. Run Boltz2 validation:"
echo -e "     ${CYAN}python -m vast.vast_boltz2${NC}"
echo ""
echo "  6. Clean up all instances:"
echo -e "     ${CYAN}python -m vast.cleanup destroy-all${NC}"
echo ""
