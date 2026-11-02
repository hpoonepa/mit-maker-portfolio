#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# build_and_push.sh — Build and push Mosaic Docker images to Docker Hub
# ---------------------------------------------------------------------------

PUSH=true
BUILD_DESIGN=true
BUILD_BOLTZ2=true
DOCKER_USER=""

# Parse all arguments — flags and positional
for arg in "$@"; do
    case "$arg" in
        --no-push)      PUSH=false ;;
        --design-only)  BUILD_BOLTZ2=false ;;
        --boltz2-only)  BUILD_DESIGN=false ;;
        *)              DOCKER_USER="$arg" ;;
    esac
done

# Default docker user if not provided
: "${DOCKER_USER:=mosaic}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

DESIGN_TAG="$DOCKER_USER/mosaic-design:latest"
BOLTZ2_TAG="$DOCKER_USER/mosaic-boltz2:latest"

echo "============================================"
echo "  Mosaic Docker Build"
echo "============================================"
echo "  Project root : $PROJECT_ROOT"
echo "  Docker user  : $DOCKER_USER"
echo "  Push         : $PUSH"
echo "  Design image : $BUILD_DESIGN"
echo "  Boltz2 image : $BUILD_BOLTZ2"
echo "============================================"
echo ""

TOTAL_START=$(date +%s)

# --- Build design image ---------------------------------------------------
if $BUILD_DESIGN; then
    echo ">>> Building design image: $DESIGN_TAG"
    START=$(date +%s)
    docker build -t "$DESIGN_TAG" -f vast/Dockerfile .
    END=$(date +%s)
    DESIGN_TIME=$((END - START))
    DESIGN_SIZE=$(docker image inspect "$DESIGN_TAG" --format='{{.Size}}' | awk '{printf "%.1f MB", $1/1024/1024}')
    echo "    Built in ${DESIGN_TIME}s  |  Size: $DESIGN_SIZE"
    echo ""
fi

# --- Build boltz2 image ---------------------------------------------------
if $BUILD_BOLTZ2; then
    echo ">>> Building boltz2 image: $BOLTZ2_TAG"
    START=$(date +%s)
    docker build -t "$BOLTZ2_TAG" -f vast/Dockerfile.boltz2 .
    END=$(date +%s)
    BOLTZ2_TIME=$((END - START))
    BOLTZ2_SIZE=$(docker image inspect "$BOLTZ2_TAG" --format='{{.Size}}' | awk '{printf "%.1f MB", $1/1024/1024}')
    echo "    Built in ${BOLTZ2_TIME}s  |  Size: $BOLTZ2_SIZE"
    echo ""
fi

# --- Push ------------------------------------------------------------------
if $PUSH; then
    echo ">>> Pushing images to Docker Hub..."
    if $BUILD_DESIGN; then
        echo "    Pushing $DESIGN_TAG"
        docker push "$DESIGN_TAG"
    fi
    if $BUILD_BOLTZ2; then
        echo "    Pushing $BOLTZ2_TAG"
        docker push "$BOLTZ2_TAG"
    fi
    echo ""
else
    echo ">>> Skipping push (--no-push)"
    echo ""
fi

TOTAL_END=$(date +%s)
TOTAL_TIME=$((TOTAL_END - TOTAL_START))

# --- Summary ---------------------------------------------------------------
echo "============================================"
echo "  Done in ${TOTAL_TIME}s"
echo "============================================"
if $BUILD_DESIGN; then
    echo "  Design : $DESIGN_TAG  ($DESIGN_SIZE, ${DESIGN_TIME}s)"
fi
if $BUILD_BOLTZ2; then
    echo "  Boltz2 : $BOLTZ2_TAG  ($BOLTZ2_SIZE, ${BOLTZ2_TIME}s)"
fi
echo ""
echo "To use these images, set environment variables:"
echo ""
echo "  export MOSAIC_DOCKER_DESIGN=\"$DESIGN_TAG\""
echo "  export MOSAIC_DOCKER_BOLTZ2=\"$BOLTZ2_TAG\""
echo ""
echo "Or update vast/config.py with the image tags."
echo "============================================"
