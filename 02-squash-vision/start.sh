#!/bin/bash
set -euo pipefail

project_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
web_root="$project_root/src/squashvision/web"
launcher_path="$project_root/src/squashvision/launcher.py"
export PYTHONDONTWRITEBYTECODE=1

fail() {
  printf 'SquashVision: %s\n' "$*" >&2
  exit 1
}

python_candidate="${SQUASHVISION_PYTHON:-}"
if [[ -z "$python_candidate" ]]; then
  if [[ -x "$project_root/src/squashvision/backend/.venv/bin/python" ]]; then
    python_candidate="$project_root/src/squashvision/backend/.venv/bin/python"
  else
    python_candidate="$HOME/Library/Application Support/Mosaic Squash/runtime/squashvision/backend/.venv/bin/python3.12"
  fi
fi
python_binary="$(command -v "$python_candidate" 2>/dev/null || true)"
[[ -n "$python_binary" && -x "$python_binary" ]] || fail "Set SQUASHVISION_PYTHON to a Python 3.12+ environment with the backend dependencies installed."
case "$python_binary" in /*) ;; *) python_binary="$PWD/$python_binary" ;; esac
"$python_binary" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' || fail "The selected Python must be version 3.12 or newer."

case "$(uname -m)" in
  arm64|aarch64) native_node_arch="arm64" ;;
  x86_64|amd64) native_node_arch="x64" ;;
  *) native_node_arch="" ;;
esac

usable_node() {
  [[ -n "$1" && -x "$1" ]] || return 1
  "$1" -e '
    const [major, minor] = process.versions.node.split(".").map(Number);
    const supported = major >= 22 && (major !== 22 || minor >= 12);
    const native = !process.argv[1] || process.arch === process.argv[1];
    process.exit(supported && native ? 0 : 1);
  ' "$native_node_arch" >/dev/null 2>&1
}

node_binary=""
if [[ -n "${SQUASHVISION_NODE:-}" ]]; then
  node_binary="$(command -v "$SQUASHVISION_NODE" 2>/dev/null || true)"
  usable_node "$node_binary" || fail "SQUASHVISION_NODE must point to native Node 22.12+ (matching this computer's architecture)."
else
  path_node="$(command -v node 2>/dev/null || true)"
  if usable_node "$path_node"; then
    node_binary="$path_node"
  else
    for candidate in "$HOME"/.nvm/versions/node/v22.*/bin/node; do
      if usable_node "$candidate"; then
        node_binary="$candidate"
      fi
    done
  fi
  [[ -n "$node_binary" ]] || fail "Native Node 22.12+ was not found. Set SQUASHVISION_NODE or install it through nvm."
fi
case "$node_binary" in /*) ;; *) node_binary="$PWD/$node_binary" ;; esac

[[ -f "$web_root/node_modules/typescript/bin/tsc" && -f "$web_root/node_modules/vite/bin/vite.js" ]] || fail "Web dependencies are missing. Install the existing lockfile in src/squashvision/web before starting."

# Keep this copy's build and Python bytecode away from the installed application.
export PATH="$(dirname "$node_binary"):$PATH"
unset MOSAIC_SQUASH_DATABASE_PATH MOSAIC_SQUASH_STORAGE_ROOT

printf 'Building SquashVision with %s\n' "$node_binary"
cd "$web_root"
"$node_binary" node_modules/typescript/bin/tsc -p tsconfig.build.json
"$node_binary" node_modules/vite/bin/vite.js build

cd "$project_root"
exec "$python_binary" "$launcher_path" \
  --api-port 8950 \
  --no-browser \
  --data-dir "$project_root/runtime/demo-data" \
  "$@"
