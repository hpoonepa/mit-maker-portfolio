#!/bin/bash
set -e
set -o pipefail

SEED="${SEED:?SEED environment variable is required}"
SEQUENCE="${SEQUENCE:?SEQUENCE environment variable is required}"
CANDIDATE_ID="${CANDIDATE_ID:-unknown}"
export XLA_PYTHON_CLIENT_MEM_FRACTION="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.9}"

OUTDIR="/workspace/outputs"

mkdir -p "$OUTDIR"

# -------------------------------------------------------------------
# Trap: on ANY failure, salvage whatever we have and mark FAILED
# -------------------------------------------------------------------
cleanup_on_failure() {
    local exit_code=$?
    echo ">>> entrypoint_boltz2.sh: caught failure (exit $exit_code), salvaging outputs..."

    # Save error info
    {
        echo "exit_code=$exit_code"
        echo "seed=$SEED"
        echo "candidate_id=$CANDIDATE_ID"
        echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$OUTDIR/error.txt"

    # Grab any PDB files produced before the crash
    cp /opt/mosaic/rbx1_boltz2_seed*.pdb "$OUTDIR/" 2>/dev/null || true
    cp /opt/mosaic/2lgv_boltz2_seed*.pdb "$OUTDIR/" 2>/dev/null || true

    echo "FAILED" > "$OUTDIR/DONE"
    echo ">>> entrypoint_boltz2.sh: marked FAILED, outputs saved to $OUTDIR"
}
trap cleanup_on_failure ERR

# -------------------------------------------------------------------
# Build and run the validation command
# -------------------------------------------------------------------
cd /opt/mosaic

CMD=(/opt/mosaic/.venv/bin/python /opt/mosaic/validate_boltz2.py "$SEED" "$SEQUENCE")
if [ -n "$TARGET_SEQ" ]; then
    CMD+=("$TARGET_SEQ")
fi

"${CMD[@]}" 2> "$OUTDIR/stderr.txt" | tee "$OUTDIR/log.txt"

# -------------------------------------------------------------------
# Collect outputs
# -------------------------------------------------------------------
grep "^CSV:" "$OUTDIR/log.txt" | head -1 | cut -c5- > "$OUTDIR/csv_line.txt" || true
cp /opt/mosaic/rbx1_boltz2_seed*.pdb "$OUTDIR/" 2>/dev/null || true
cp /opt/mosaic/2lgv_boltz2_seed*.pdb "$OUTDIR/" 2>/dev/null || true

echo "DONE" > "$OUTDIR/DONE"
echo ">>> entrypoint_boltz2.sh: completed successfully for candidate=$CANDIDATE_ID seed=$SEED"
