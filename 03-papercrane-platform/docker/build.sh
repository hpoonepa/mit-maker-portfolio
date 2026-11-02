#!/usr/bin/env bash
# builds both base images with configurable tag
set -euo pipefail
TAG="${BASE_TAG:-latest}"
docker build -t ghcr.io/papercrane/base-cuda12:${TAG} docker/base-cuda12
docker build -t ghcr.io/papercrane/base-cpu:${TAG} docker/base-cpu
echo "built base-cuda12:${TAG} and base-cpu:${TAG}"
