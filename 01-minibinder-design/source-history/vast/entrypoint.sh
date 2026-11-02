#!/bin/bash
set -e
set -o pipefail

SEED="${SEED:?SEED environment variable is required}"
DESIGN_SCRIPT="${DESIGN_SCRIPT:-design_2lgv.py}"
export XLA_PYTHON_CLIENT_MEM_FRACTION="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.9}"

OUTDIR="/workspace/outputs"
CKPTDIR="/workspace/checkpoints"

mkdir -p "$OUTDIR" "$CKPTDIR"

# -------------------------------------------------------------------
# Trap: on ANY failure, salvage whatever we have and mark FAILED
# -------------------------------------------------------------------
cleanup_on_failure() {
    local exit_code=$?
    echo ">>> entrypoint.sh: caught failure (exit $exit_code), salvaging outputs..."

    # Save error info
    {
        echo "exit_code=$exit_code"
        echo "seed=$SEED"
        echo "script=$DESIGN_SCRIPT"
        echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$OUTDIR/error.txt"

    # Grab any PDB/PNG files produced before the crash
    cp /opt/mosaic/*.pdb "$OUTDIR/" 2>/dev/null || true
    cp /opt/mosaic/*.png "$OUTDIR/" 2>/dev/null || true

    echo "FAILED" > "$OUTDIR/DONE"
    echo ">>> entrypoint.sh: marked FAILED, outputs saved to $OUTDIR"
}
trap cleanup_on_failure ERR

# -------------------------------------------------------------------
# Run the design script
# -------------------------------------------------------------------
cd /opt/mosaic

/opt/mosaic/.venv/bin/python "/opt/mosaic/${DESIGN_SCRIPT}" "$SEED" \
    2> "$OUTDIR/stderr.txt" | tee "$OUTDIR/log.txt"

# -------------------------------------------------------------------
# Checkpoint: collect all outputs
# -------------------------------------------------------------------
grep "^CSV:" "$OUTDIR/log.txt" | head -1 | cut -c5- > "$OUTDIR/csv_line.txt" || true
cp /opt/mosaic/*.pdb "$OUTDIR/" 2>/dev/null || true
cp /opt/mosaic/*.png "$OUTDIR/" 2>/dev/null || true

echo "DONE" > "$OUTDIR/DONE"
echo ">>> entrypoint.sh: completed successfully for seed=$SEED"
