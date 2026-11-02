#!/bin/bash
set -e
set -o pipefail

SEED="${SEED:?SEED environment variable is required}"
CONFIG_PATH="${CONFIG_PATH:-/opt/v5/config/v5_5g51_hotspots.yaml}"
TARGET_CIF="${TARGET_CIF:-5G51.cif}"
export XLA_PYTHON_CLIENT_MEM_FRACTION="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.9}"

# Per-seed output dir so multiple seeds don't clobber each other when fanning out.
SEED_PADDED=$(printf "%03d" "$SEED")
OUTDIR="/workspace/outputs/seed_${SEED_PADDED}"
mkdir -p "$OUTDIR"

# -------------------------------------------------------------------
# Trap: on ANY failure, salvage whatever we have and mark FAILED
# -------------------------------------------------------------------
cleanup_on_failure() {
    local exit_code=$?
    echo ">>> entrypoint_v5.sh: caught failure (exit $exit_code), salvaging outputs..."

    {
        echo "exit_code=$exit_code"
        echo "seed=$SEED"
        echo "config_path=$CONFIG_PATH"
        echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$OUTDIR/error.txt"

    cp /opt/mosaic/*.pdb "$OUTDIR/" 2>/dev/null || true

    echo "FAILED" > "$OUTDIR/DONE"
    echo ">>> entrypoint_v5.sh: marked FAILED, outputs saved to $OUTDIR"
}
trap cleanup_on_failure ERR

# -------------------------------------------------------------------
# Run the V5 design script
# -------------------------------------------------------------------
cd /opt/mosaic

/opt/mosaic/.venv/bin/python /opt/v5/src/design_v5.py \
    --seed "$SEED" \
    --target-structure "$TARGET_CIF" \
    --config "$CONFIG_PATH" \
    --output-dir "$OUTDIR" \
    2> "$OUTDIR/stderr.txt" | tee "$OUTDIR/log.txt"

# -------------------------------------------------------------------
# Collect outputs
# -------------------------------------------------------------------
grep "^CSV:" "$OUTDIR/log.txt" | head -1 | cut -c5- > "$OUTDIR/csv_line.txt" || true

echo "DONE" > "$OUTDIR/DONE"
echo ">>> entrypoint_v5.sh: completed successfully for seed=$SEED config_path=$CONFIG_PATH"
