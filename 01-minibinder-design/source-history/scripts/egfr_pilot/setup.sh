#!/usr/bin/env bash
# Run on a Linux NVIDIA GPU host. Creates separate environments, never provisions GPUs.
set -euo pipefail
if [[ $(uname -s) != Linux ]]; then
  echo 'Run engine setup on Linux with an NVIDIA GPU, not this Mac.' >&2; exit 1
fi
command -v uv >/dev/null || { echo 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 1; }
command -v git >/dev/null
command -v nvidia-smi >/dev/null
destination=${1:?Usage: bash setup.sh /absolute/path/to/NEW/engine-directory}
if [[ -e "$destination" ]]; then echo 'Choose a new directory; setup refuses to overwrite environments.' >&2; exit 1; fi
mkdir -p "$destination"
destination=$(cd "$destination" && pwd)
uv venv --python 3.12 "$destination/control"
uv pip install --python "$destination/control/bin/python" biopython==1.85 numpy==2.2.6
git clone https://github.com/PacesaLab/BindCraft2.git "$destination/BindCraft2"
git -C "$destination/BindCraft2" checkout a8d0f2002df373842b86a3c20c5a060c5cfdf980
(
  cd "$destination/BindCraft2"
  unset VIRTUAL_ENV CONDA_PREFIX BINDCRAFT_PYTHON
  bash install.sh cuda12
  .venv/bin/python -m pip freeze > "$destination/bindcraft2-freeze.txt"
)
git clone https://github.com/escalante-bio/mosaic.git "$destination/mosaic"
git -C "$destination/mosaic" checkout b94b9d4eb9907a700a6d78ed2d29d3704c5df46c
(
  cd "$destination/mosaic"
  uv sync --python 3.12 --group jax-cuda
  uv pip freeze --python .venv/bin/python > "$destination/mosaic-freeze.txt"
  cp uv.lock "$destination/mosaic-resolved.lock"
  .venv/bin/python -c 'import jax; from mosaic.models.protenix import Protenix2025; from mosaic.models.boltz2 import Boltz2; assert jax.default_backend() == "gpu"; Protenix2025(); Boltz2(); print("Mosaic weights loaded")'
)
echo "Setup complete. Control Python: $destination/control/bin/python"
