#!/bin/bash
# Tri-objective scoring run. Resumable: re-running skips designs already scored.
set -euo pipefail

SEQUENCES="${SEQUENCES:?SEQUENCES env var required (FASTA or CSV of name,sequence)}"
TARGET_CIF="${TARGET_CIF:-/opt/mosaic/5G51.cif}"
OUTDIR="${OUTDIR:-/workspace/outputs}"
PROTENIX_SEEDS="${PROTENIX_SEEDS:-5}"
BOLTZ2_SAMPLES="${BOLTZ2_SAMPLES:-3}"
MSA_RETRIES="${MSA_RETRIES:-3}"
export XLA_PYTHON_CLIENT_MEM_FRACTION="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.9}"
export MOSAIC_ESMFOLD_PYTHON="${MOSAIC_ESMFOLD_PYTHON:-/opt/esmfold/.venv/bin/python}"
export PYTHONPATH="/opt/v5:${PYTHONPATH:-}"

mkdir -p "$OUTDIR" /workspace/logs
LOG="/workspace/logs/tri_$(date -u +%Y%m%dT%H%M%SZ).log"
OUT_CSV="$OUTDIR/tri_scores.csv"

echo ">>> tri-objective run"            | tee -a "$LOG"
echo "    sequences : $SEQUENCES"        | tee -a "$LOG"
echo "    target    : $TARGET_CIF"       | tee -a "$LOG"
echo "    protenix  : ${PROTENIX_SEEDS} seeds (>=2 needed for seed spread)" | tee -a "$LOG"
echo "    out       : $OUT_CSV"          | tee -a "$LOG"

# Fail fast on the things that actually go wrong, before burning GPU time.
[ -f "$SEQUENCES"  ] || { echo "FATAL: $SEQUENCES not found"  | tee -a "$LOG"; exit 1; }
[ -f "$TARGET_CIF" ] || { echo "FATAL: $TARGET_CIF not found" | tee -a "$LOG"; exit 1; }
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | tee -a "$LOG" \
    || { echo "FATAL: no GPU visible" | tee -a "$LOG"; exit 1; }
"$MOSAIC_ESMFOLD_PYTHON" -c "import esm,torch;print('esmfold venv OK, cuda',torch.cuda.is_available())" \
    2>&1 | tee -a "$LOG" || echo "WARNING: esmfold venv broken - expression axis will be skipped" | tee -a "$LOG"

cd /opt/mosaic
# ColabFold MSA failures on RunPod are transient (rate limiting / server blips),
# not a bad input. Retry with backoff before declaring the run dead.
for attempt in $(seq 1 "$MSA_RETRIES"); do
    echo ">>> attempt $attempt/$MSA_RETRIES" | tee -a "$LOG"
    if python /opt/v5/validators/tri_consensus.py \
            --sequences "$SEQUENCES" \
            --target-cif "$TARGET_CIF" \
            --out "$OUT_CSV" \
            --protenix-seeds "$PROTENIX_SEEDS" \
            --boltz2-samples "$BOLTZ2_SAMPLES" 2>&1 | tee -a "$LOG"; then
        echo "OK" > "$OUTDIR/DONE"
        echo ">>> complete -> $OUT_CSV" | tee -a "$LOG"
        exit 0
    fi
    echo ">>> attempt $attempt failed; sleeping $((attempt * 60))s" | tee -a "$LOG"
    sleep $((attempt * 60))
done

echo "FAILED" > "$OUTDIR/DONE"
echo ">>> all $MSA_RETRIES attempts failed - see $LOG" | tee -a "$LOG"
exit 1
