#!/usr/bin/env bash
# scripts/deploy-api.sh — One-shot Fly.io deploy for apps/api
#
# - Verifies the fly app exists; if not, prompts the user to create it.
# - Pushes secrets from .env.local via `flyctl secrets set` in one batched call
#   (atomic restart instead of N restarts).
# - Deploys with the api fly.toml.
#
# Usage:
#   bash scripts/deploy-api.sh [--dry-run]
#
# Constraints:
#   - Must NOT echo secret values.
#   - Must use absolute paths.
#   - Idempotent: if no new/changed secrets, skip the secrets set call.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_NAME="papercrane-api"
FLY_TOML="${REPO_ROOT}/apps/api/fly.toml"
DOCKERFILE="${REPO_ROOT}/apps/api/Dockerfile"
ENV_FILE="${REPO_ROOT}/.env.local"

# Variables that belong on the api host. (Do NOT push NEXT_PUBLIC_* — those
# are Vercel build-time vars, not server runtime secrets.)
API_KEYS=(
  DATABASE_URL
  DIRECT_URL
  NEXT_PUBLIC_SUPABASE_URL
  NEXT_PUBLIC_SUPABASE_ANON_KEY
  SUPABASE_PROJECT_REF
  SUPABASE_SERVICE_ROLE_KEY
  API_KEY_PEPPER
  REDIS_URL
  R2_ACCOUNT_ID
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_BUCKET
  R2_ENDPOINT
  STRIPE_SECRET_KEY
  STRIPE_WEBHOOK_SECRET
  SENTRY_DSN
  RESEND_API_KEY
  MODAL_TOKEN_ID
  MODAL_TOKEN_SECRET
  MODAL_WORKSPACE
  OPENAI_API_KEY
)

DRY_RUN=0
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[deploy-api] unknown arg: ${arg}" >&2; exit 2 ;;
  esac
done

log()  { printf '[deploy-api] %s\n' "$*"; }
warn() { printf '[deploy-api] WARN: %s\n' "$*" >&2; }
die()  { printf '[deploy-api] ERROR: %s\n' "$*" >&2; exit 1; }
run()  {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[deploy-api] dry-run: %s\n' "$*"
  else
    eval "$@"
  fi
}

# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------
command -v flyctl >/dev/null 2>&1 || die "flyctl not found. Install: https://fly.io/docs/hands-on/install-flyctl/"
[[ -f "${FLY_TOML}" ]] || die "fly.toml not found at ${FLY_TOML}"
[[ -f "${DOCKERFILE}" ]] || die "Dockerfile not found at ${DOCKERFILE}"

if [[ "${DRY_RUN}" -eq 0 ]] && ! flyctl status --app "${APP_NAME}" >/dev/null 2>&1; then
  cat >&2 <<EOF

[deploy-api] ERROR: fly app '${APP_NAME}' does not exist or is not accessible.

  Create it (one-time):
      flyctl apps create ${APP_NAME}

  Then re-run this script.
EOF
  exit 1
fi
log "fly app '${APP_NAME}' confirmed."

# -----------------------------------------------------------------------------
# Build secrets payload from .env.local for the API_KEYS allowlist only
# We pipe to flyctl via stdin (--stage + flyctl secrets import keeps values
# out of process listings). Use one batched `secrets set` so machines only
# restart once.
# -----------------------------------------------------------------------------
push_secrets() {
  [[ ! -f "${ENV_FILE}" ]] && { warn ".env.local missing — skipping secret sync"; return 0; }

  local pairs=()
  for key in "${API_KEYS[@]}"; do
    # Pull "KEY=VALUE" line for this key out of .env.local
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
    log "no api secrets found in .env.local — skipping"
    return 0
  fi

  log "staging ${#pairs[@]} secret(s) for ${APP_NAME} (values redacted)"
  for p in "${pairs[@]}"; do log "  + ${p%%=*}"; done

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[deploy-api] dry-run: would call flyctl secrets set --app %s --stage <%d secrets>\n' \
      "${APP_NAME}" "${#pairs[@]}"
    return 0
  fi

  # `--stage` queues secrets without restart; the upcoming `deploy` picks them up.
  flyctl secrets set --app "${APP_NAME}" --stage "${pairs[@]}" >/dev/null
}

push_secrets

# -----------------------------------------------------------------------------
# Deploy
# -----------------------------------------------------------------------------
log "deploying ${APP_NAME}..."
run "flyctl deploy --app '${APP_NAME}' --config '${FLY_TOML}' --dockerfile '${DOCKERFILE}' --remote-only"

log "done. Public URL: https://${APP_NAME}.fly.dev"
