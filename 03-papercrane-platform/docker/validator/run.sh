#!/usr/bin/env bash
# Paper Crane validator entrypoint — overrides the placeholder shipped by
# base-cuda12. The runner (docs/plans/02-tool-integration.md §3) mounts
# /inputs read-only and /outputs writable before invoking us.
set -euo pipefail

: "${PC_DESIGNS_JSON:=/inputs/designs.json}"
: "${PC_OUTPUTS_DIR:=/outputs}"

if [[ ! -f "${PC_DESIGNS_JSON}" ]]; then
    echo "papercrane-validator: missing input manifest at ${PC_DESIGNS_JSON}" >&2
    exit 2
fi

mkdir -p "${PC_OUTPUTS_DIR}"

exec python -m papercrane_validator.validate \
    --designs-json "${PC_DESIGNS_JSON}" \
    --outputs-dir "${PC_OUTPUTS_DIR}"
