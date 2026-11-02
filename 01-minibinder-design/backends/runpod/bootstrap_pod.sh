#!/bin/bash
# Build the tri-objective environment ON a running pod. Use this instead of
# runpod/Dockerfile when you cannot build/push an image (no local Docker).
#
#   ssh into the pod, then:
#     curl -fsSL <raw-url>/bootstrap_pod.sh | bash
#   or scp this file over and: bash bootstrap_pod.sh
#
# Start from a stock RunPod "PyTorch 2.x / CUDA 12.4" template.
# Takes ~30-45 min. Everything lands under /workspace so it survives a restart.
set -euo pipefail

MOSAIC_COMMIT="bca3152"   # first commit with ProtenixV2(); 8362af3 breaks the pickled weights
LOG=/workspace/logs/bootstrap.log
mkdir -p /workspace/logs /workspace/outputs /workspace/in
exec > >(tee -a "$LOG") 2>&1
echo ">>> bootstrap started $(date -u)"

nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
df -h /workspace | tail -1

apt-get update -qq
apt-get install -y -qq git curl build-essential python3.12 python3.12-venv python3.12-dev jq \
  || apt-get install -y -qq git curl build-essential python3-venv jq
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# ---- JAX side: mosaic + protenix + boltz2 -----------------------------------
# NEVER `pip install -r` here. mosaic's real deps live in [tool.uv.sources],
# which pip cannot see — it would fetch unrelated PyPI packages named
# protenix / boltz / esm and the run would fail in confusing ways.
if [ ! -d /workspace/mosaic ]; then
  git clone -q https://github.com/escalante-bio/jopenfold3.git /workspace/jopenfold3
  rm -f /workspace/jopenfold3/jopenfold3/mosaic
  git clone -q https://github.com/escalante-bio/mosaic.git /workspace/mosaic
  cd /workspace/mosaic && git checkout -q "$MOSAIC_COMMIT"
  sed -i 's|jopenfold3 = { git = "https://github.com/escalante-bio/jopenfold3.git" }|jopenfold3 = { path = "/workspace/jopenfold3" }|' pyproject.toml
fi
cd /workspace/mosaic
uv lock && uv sync --group jax-cuda
echo ">>> mosaic venv ready"

# ---- Torch side: ESMFold, isolated ------------------------------------------
# jax==0.9.1 is load-bearing (jax 0.10 removed ShapeDtypeStruct.vma, which
# breaks unpickling the protenix weights). Torch gets its own venv so it can
# never clobber that pin.
if [ ! -d /workspace/esmfold/.venv ]; then
  python3 -m venv /workspace/esmfold/.venv
  /workspace/esmfold/.venv/bin/pip install -q -U pip wheel
  /workspace/esmfold/.venv/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cu124
  # 'fair-esm[esmfold]' -- plain `pip install esm` is an UNRELATED package.
  /workspace/esmfold/.venv/bin/pip install -q "fair-esm[esmfold]" gemmi numpy
fi
/workspace/esmfold/.venv/bin/python - <<'PY'
import esm, torch
esm.pretrained.esmfold_v1()
print("esmfold weights cached; cuda:", torch.cuda.is_available())
PY

# ---- targets ----------------------------------------------------------------
for pdb in 5G51 4EUL; do
  [ -f "/workspace/mosaic/${pdb}.cif" ] || \
    curl -fsSL -o "/workspace/mosaic/${pdb}.cif" "https://files.rcsb.org/download/${pdb}.cif" || true
done

cat > /workspace/env.sh <<'ENVEOF'
export PATH="/workspace/mosaic/.venv/bin:$HOME/.local/bin:$PATH"
export VIRTUAL_ENV=/workspace/mosaic/.venv
export PYTHONPATH=/workspace/v5
export MOSAIC_ESMFOLD_PYTHON=/workspace/esmfold/.venv/bin/python
export XLA_PYTHON_CLIENT_MEM_FRACTION=0.9
ENVEOF

echo ">>> bootstrap complete $(date -u)"
echo ">>> next:  source /workspace/env.sh"
echo ">>>        scp your src/ validators/ runpod/ into /workspace/v5/"
echo ">>>        SEQUENCES=/workspace/in/designs.fasta bash /workspace/v5/runpod/entrypoint_tri.sh"
