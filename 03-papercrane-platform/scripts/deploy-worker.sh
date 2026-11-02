#!/usr/bin/env bash
# scripts/deploy-worker.sh — One-shot Fly.io deploy for apps/worker
#
# Same pattern as deploy-api.sh, but for the BullMQ worker (no public HTTP).
#
# Usage:
#   bash scripts/deploy-worker.sh [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_NAME="papercrane-worker"
FLY_TOML="${REPO_ROOT}/apps/worker/fly.toml"
DOCKERFILE="${REPO_ROOT}/apps/worker/Dockerfile"
ENV_FILE="${REPO_ROOT}/.env.local"

# Worker uses the same DB/storage/queue secrets as the api (minus public-facing
# Stripe HTTP keys), plus compute backend tokens.
WORKER_KEYS=(
  DATABASE_URL
  DIRECT_URL
  NEXT_PUBLIC_SUPABASE_URL
  NEXT_PUBLIC_SUPABASE_ANON_KEY
  SUPABASE_PROJECT_REF
  SUPABASE_SERVICE_ROLE_KEY
  REDIS_URL
  R2_ACCOUNT_ID
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_BUCKET
  R2_ENDPOINT
  SENTRY_DSN
  RESEND_API_KEY
  OPENAI_API_KEY
  WORKER_CONCURRENCY
  PORT_HEALTH
  MODAL_TOKEN_ID
  MODAL_TOKEN_SECRET
  MODAL_WORKSPACE
  VASTAI_API_KEY
  RUNPOD_API_KEY
)

DRY_RUN=0
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[deploy-worker] unknown arg: ${arg}" >&2; exit 2 ;;
  esac
done

log()  { printf '[deploy-worker] %s\n' "$*"; }
warn() { printf '[deploy-worker] WARN: %s\n' "$*" >&2; }
die()  { printf '[deploy-worker] ERROR: %s\n' "$*" >&2; exit 1; }
run()  {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[deploy-worker] dry-run: %s\n' "$*"
  else
    eval "$@"
  fi
}

command -v flyctl >/dev/null 2>&1 || die "flyctl not found. Install: https://fly.io/docs/hands-on/install-flyctl/"
[[ -f "${FLY_TOML}" ]] || die "fly.toml not found at ${FLY_TOML}"
[[ -f "${DOCKERFILE}" ]] || die "Dockerfile not found at ${DOCKERFILE}"

if [[ "${DRY_RUN}" -eq 0 ]] && ! flyctl status --app "${APP_NAME}" >/dev/null 2>&1; then
  cat >&2 <<EOF

[deploy-worker] ERROR: fly app '${APP_NAME}' does not exist or is not accessible.

  Create it (one-time):
      flyctl apps create ${APP_NAME}

  Then re-run this script.
EOF
  exit 1
fi
log "fly app '${APP_NAME}' confirmed."

push_secrets() {
  [[ ! -f "${ENV_FILE}" ]] && { warn ".env.local missing — skipping secret sync"; return 0; }

  local pairs=()
  for key in "${WORKER_KEYS[@]}"; do
    local line
    line="$(grep -E "^${key}=" "${ENV_FILE}" || true)"
    [[ -z "${line}" ]] && continue
    local value="${line#*=}"
    if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]] ||
       [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
    [[ -z "${value}" ]] && continue
    pairs+=("${key}=${value}")
  done

  if [[ "${#pairs[@]}" -eq 0 ]]; then
    log "no worker secrets found in .env.local — skipping"
    return 0
  fi

  log "staging ${#pairs[@]} secret(s) for ${APP_NAME} (values redacted)"
  for p in "${pairs[@]}"; do log "  + ${p%%=*}"; done

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[deploy-worker] dry-run: would call flyctl secrets set --app %s --stage <%d secrets>\n' \
      "${APP_NAME}" "${#pairs[@]}"
    return 0
  fi

  flyctl secrets set --app "${APP_NAME}" --stage "${pairs[@]}" >/dev/null
}

push_secrets

log "deploying ${APP_NAME}..."
run "flyctl deploy --app '${APP_NAME}' --config '${FLY_TOML}' --dockerfile '${DOCKERFILE}' --remote-only"

log "done. (worker has no public URL — internal health on :3003)"
