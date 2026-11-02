#!/usr/bin/env bash
# Tool-adapter conformance runner — Wave 8, Agent 15/15.
#
# For every tool dir under ../, run a static conformance check:
#   1. Required files present (manifest.json | papercrane.toml,
#      adapter.py | modal_app.py, schemas/input.json, schemas/output.json,
#      README.md).
#   2. JSON Schema files parse as JSON.
#   3. If `python -m papercrane_sdk validate` is available, invoke it.
#   4. Closed-weights tools must declare tier="frontier".
#
# This script never invokes Modal, never touches GPUs, and never calls a tool's
# `run`. Exit code = number of tools that failed at least one check.
#
# Usage:  bash tools/conformance/run.sh [tool_id ...]

set -uo pipefail

# -----------------------------------------------------------------------------
# Paths and configuration
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TOOLS=(
  bindcraft
  proteinmpnn
  rfdiffusion
  boltz1
  boltz2
  chai1
  ligandmpnn
  solublempnn
  esm2
  boltzgen
  chroma
  alphafold3
)

if [ "$#" -gt 0 ]; then
  TOOLS=("$@")
fi

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
BOLD=$'\033[1m'
RESET=$'\033[0m'
if [ ! -t 1 ]; then RED=""; GREEN=""; YELLOW=""; BOLD=""; RESET=""; fi

say_pass() { printf '  %sPASS%s %s\n' "$GREEN" "$RESET" "$1"; }
say_fail() { printf '  %sFAIL%s %s\n' "$RED"   "$RESET" "$1"; }
say_warn() { printf '  %sWARN%s %s\n' "$YELLOW" "$RESET" "$1"; }

# Pure-stdlib JSON parsing: prefer python3, fall back to skipping with a warn.
have_python() { command -v python3 >/dev/null 2>&1; }

json_get() {
  # json_get <file> <dot.path>
  python3 - "$1" "$2" <<'PY' 2>/dev/null || return 1
import json, sys
path = sys.argv[2].split(".")
with open(sys.argv[1]) as f:
    data = json.load(f)
for p in path:
    if not isinstance(data, dict) or p not in data:
        sys.exit(1)
    data = data[p]
print(data)
PY
}

json_validate_file() {
  python3 - "$1" <<'PY' 2>/dev/null
import json, sys
json.load(open(sys.argv[1]))
PY
}

sdk_validate() {
  # Run the SDK validator if it exists; if not, warn and pass through.
  python3 -c "import papercrane_sdk" >/dev/null 2>&1 || return 2
  python3 -m papercrane_sdk --help >/dev/null 2>&1 || return 2
  python3 -m papercrane_sdk validate "$1" >/dev/null 2>&1
}

# -----------------------------------------------------------------------------
# Per-tool check
# -----------------------------------------------------------------------------
check_tool() {
  local tool="$1"
  local dir="$TOOLS_DIR/$tool"
  local fails=0

  printf '\n%s== %s ==%s\n' "$BOLD" "$tool" "$RESET"

  if [ ! -d "$dir" ]; then
    say_fail "directory missing: $dir"
    return 1
  fi
  say_pass "directory: $dir"

  # 1. Manifest (json or toml)
  local manifest_json="$dir/manifest.json"
  local manifest_toml="$dir/papercrane.toml"
  local manifest_kind=""
  if [ -f "$manifest_json" ]; then
    manifest_kind="json"
    say_pass "manifest.json present"
  elif [ -f "$manifest_toml" ]; then
    manifest_kind="toml"
    say_pass "papercrane.toml present"
  else
    say_fail "manifest missing (need manifest.json or papercrane.toml)"
    fails=$((fails + 1))
  fi

  # 2. Adapter entrypoint
  if [ -f "$dir/adapter.py" ]; then
    say_pass "adapter.py present"
  elif [ -f "$dir/modal_app.py" ]; then
    if have_python && grep -q '^[[:space:]]*import modal' "$dir/modal_app.py" \
        && grep -qE '^[[:space:]]*app[[:space:]]*=[[:space:]]*modal\.App\(' "$dir/modal_app.py"; then
      say_pass "modal_app.py defines \`app = modal.App(...)\`"
    else
      say_fail "modal_app.py missing \`import modal\` or \`app = modal.App(...)\`"
      fails=$((fails + 1))
    fi
  else
    say_fail "adapter entrypoint missing (adapter.py or modal_app.py)"
    fails=$((fails + 1))
  fi

  # 3. Schemas
  for s in input output; do
    local schema="$dir/schemas/${s}.json"
    if [ ! -f "$schema" ]; then
      say_fail "schemas/${s}.json missing"
      fails=$((fails + 1))
      continue
    fi
    if have_python; then
      if json_validate_file "$schema"; then
        say_pass "schemas/${s}.json parses as JSON"
      else
        say_fail "schemas/${s}.json is not valid JSON"
        fails=$((fails + 1))
      fi
    else
      say_warn "schemas/${s}.json present (python3 unavailable, parse skipped)"
    fi
  done

  # 4. README
  if [ -f "$dir/README.md" ]; then
    say_pass "README.md present"
  else
    say_fail "README.md missing"
    fails=$((fails + 1))
  fi

  # 5. Closed-weights tier check
  if [ "$manifest_kind" = "json" ] && have_python; then
    local tier
    tier="$(json_get "$manifest_json" tier || true)"
    local closed=""
    if json_get "$manifest_json" closed_weights >/dev/null 2>&1; then
      closed="$(json_get "$manifest_json" closed_weights)"
    fi
    if [ -f "$dir/LICENSE-GATE.md" ] || [ "$closed" = "True" ] || [ "$closed" = "true" ]; then
      if [ "$tier" = "frontier" ]; then
        say_pass "closed-weights tool gated by tier=frontier"
      else
        say_fail "closed-weights tool but tier=$tier (must be 'frontier' for feature_flags.closed_weights_allowed)"
        fails=$((fails + 1))
      fi
    fi
  fi

  # 6. Optional SDK-level validate (best effort; never fails the suite).
  if have_python; then
    sdk_validate "$dir"
    case $? in
      0) say_pass "papercrane_sdk validate <tool>" ;;
      2) say_warn "papercrane_sdk validate not available — skipping" ;;
      *) say_fail "papercrane_sdk validate reported errors"; fails=$((fails + 1)) ;;
    esac
  else
    say_warn "python3 unavailable — SDK validate skipped"
  fi

  return $fails
}

# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------
total_failed=0
for t in "${TOOLS[@]}"; do
  if ! check_tool "$t"; then
    total_failed=$((total_failed + 1))
  fi
done

printf '\n%sSummary:%s %d tool(s) failed of %d checked.\n' \
  "$BOLD" "$RESET" "$total_failed" "${#TOOLS[@]}"

exit "$total_failed"
