#!/usr/bin/env bash
# ---------------------------------------------------------------
# Paper Crane — local integration smoke test
#
# Boots the full stack from a clean shell, hits health endpoints
# on every service, reports pass/fail per check, and tears
# everything down on exit (success, failure, or Ctrl-C).
#
# Usage:
#   bash scripts/smoke-test.sh             # run end-to-end
#   SKIP_DOCKER=1 bash scripts/smoke-test.sh    # assume infra is already up
#   KEEP_RUNNING=1 bash scripts/smoke-test.sh   # do not tear down on exit
#
# Requires: docker, pnpm, curl, lsof
# ---------------------------------------------------------------

set -Eeuo pipefail

# --- Repo root regardless of where script is invoked from -------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="$ROOT_DIR/.smoke-logs"
mkdir -p "$LOG_DIR"
WEB_LOG="$LOG_DIR/web.log"
APP_LOG="$LOG_DIR/app.log"
API_LOG="$LOG_DIR/api.log"
WORKER_LOG="$LOG_DIR/worker.log"

# --- Colors (only when stdout is a tty) -------------------------
if [ -t 1 ]; then
  C_GREEN=$'\e[32m'; C_RED=$'\e[31m'; C_YELLOW=$'\e[33m'; C_DIM=$'\e[2m'; C_RESET=$'\e[0m'
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_DIM=""; C_RESET=""
fi

ok()    { printf "  %s[ OK ]%s %s\n"   "$C_GREEN"  "$C_RESET" "$1"; }
fail()  { printf "  %s[FAIL]%s %s\n"   "$C_RED"    "$C_RESET" "$1"; }
warn()  { printf "  %s[WARN]%s %s\n"   "$C_YELLOW" "$C_RESET" "$1"; }
info()  { printf "%s==> %s%s\n"        "$C_DIM"    "$1" "$C_RESET"; }
hr()    { printf -- "----------------------------------------\n"; }

# --- Track results so a single check failure does not abort -----
TOTAL=0
FAILED=0
declare -a RESULTS=()
record() {
  TOTAL=$((TOTAL + 1))
  if [ "$1" = "0" ]; then
    RESULTS+=("OK   $2")
  else
    FAILED=$((FAILED + 1))
    RESULTS+=("FAIL $2")
  fi
}

# --- PIDs we need to clean up -----------------------------------
DEV_PID=""

cleanup() {
  local rc=$?
  if [ "${KEEP_RUNNING:-0}" = "1" ]; then
    warn "KEEP_RUNNING=1 — leaving services up. Logs: $LOG_DIR"
    exit "$rc"
  fi

  hr
  info "Tearing down..."

  if [ -n "$DEV_PID" ] && kill -0 "$DEV_PID" 2>/dev/null; then
    # Kill the whole process group spawned by `pnpm dev` (turbo + child Next/tsx procs)
    kill -TERM -"$DEV_PID" 2>/dev/null || kill -TERM "$DEV_PID" 2>/dev/null || true
    sleep 2
    kill -KILL -"$DEV_PID" 2>/dev/null || true
  fi

  # Belt & suspenders — kill anything still bound to our dev ports.
  for port in 3000 3001 3002 3003; do
    pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
      kill -KILL $pids 2>/dev/null || true
    fi
  done

  if [ "${SKIP_DOCKER:-0}" != "1" ]; then
    docker compose --project-directory "$ROOT_DIR" down >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

# --- 0. Load .env.local if present ------------------------------
if [ -f "$ROOT_DIR/.env.local" ]; then
  info "Loading .env.local"
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env.local"
  set +a
else
  warn ".env.local not found — services may fail to boot. Copy .env.example -> .env.local"
fi

# --- 1. Boot infra (redis + minio) ------------------------------
if [ "${SKIP_DOCKER:-0}" = "1" ]; then
  info "SKIP_DOCKER=1 — skipping docker compose up"
else
  info "Starting docker infra (redis + minio)"
  docker compose up -d redis minio minio-init >/dev/null
fi

wait_for_tcp() {
  local host="$1" port="$2" name="$3" timeout="${4:-30}"
  local i=0
  while [ "$i" -lt "$timeout" ]; do
    if (echo > "/dev/tcp/$host/$port") >/dev/null 2>&1; then
      ok "$name reachable on $host:$port"
      return 0
    fi
    sleep 1; i=$((i + 1))
  done
  fail "$name not reachable on $host:$port within ${timeout}s"
  return 1
}

wait_for_url() {
  local url="$1" name="$2" timeout="${3:-90}"
  local i=0
  while [ "$i" -lt "$timeout" ]; do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      ok "$name healthy ($url)"
      return 0
    fi
    sleep 2; i=$((i + 2))
  done
  fail "$name failed to become healthy at $url after ${timeout}s"
  return 1
}

if [ "${SKIP_DOCKER:-0}" != "1" ]; then
  wait_for_tcp 127.0.0.1 6379 "redis" 30 || record 1 "redis tcp"     ; record 0 "redis tcp"
  wait_for_tcp 127.0.0.1 9000 "minio" 30 || record 1 "minio tcp"     ; record 0 "minio tcp"
fi

# --- 2. Boot apps in the background -----------------------------
info "Starting all apps via pnpm turbo dev (logs: $LOG_DIR)"
# Turbo's `dev` task is persistent; it fans out to each app's dev script.
# Run in its own process group so cleanup() can SIGTERM the whole tree.
( setsid pnpm turbo run dev --parallel > "$LOG_DIR/turbo-dev.log" 2>&1 ) &
DEV_PID=$!

# Give turbo a moment to fork children before we start polling
sleep 3

# --- 3. Health probes -------------------------------------------
hr
info "Probing health endpoints"

# api: Fastify on 3001
if wait_for_url "http://127.0.0.1:3001/healthz" "api /healthz" 90; then record 0 "api /healthz"; else record 1 "api /healthz"; fi
# worker: tiny http listener on 3003
if wait_for_url "http://127.0.0.1:3003/healthz" "worker /healthz" 90; then record 0 "worker /healthz"; else record 1 "worker /healthz"; fi
# app: Next.js on 3002 (tRPC health route under /api/trpc/health)
if wait_for_url "http://127.0.0.1:3002/api/trpc/health" "app /api/trpc/health" 120; then record 0 "app /api/trpc/health"; else record 1 "app /api/trpc/health"; fi
# web: Next.js on 3000 (landing)
if wait_for_url "http://127.0.0.1:3000/" "web /" 120; then record 0 "web /"; else record 1 "web /"; fi

# --- 4. Report --------------------------------------------------
hr
info "Smoke test summary"
for line in "${RESULTS[@]}"; do
  case "$line" in
    OK*)   ok   "${line#OK   }" ;;
    FAIL*) fail "${line#FAIL }" ;;
  esac
done
hr
if [ "$FAILED" -eq 0 ]; then
  printf "%sAll %d checks passed%s\n" "$C_GREEN" "$TOTAL" "$C_RESET"
  exit 0
else
  printf "%s%d/%d checks failed — see %s for service logs%s\n" "$C_RED" "$FAILED" "$TOTAL" "$LOG_DIR" "$C_RESET"
  exit 1
fi
