#!/usr/bin/env bash
# scripts/deploy-app.sh — One-shot Vercel deploy for apps/app
#
# Reads env from .env.local and pushes any missing vars to Vercel via
# `vercel env add`. Idempotent: skips vars already set on the project.
#
# Usage:
#   bash scripts/deploy-app.sh [--dry-run] [--preview]
#
# Flags:
#   --dry-run   Print actions without executing.
#   --preview   Deploy to a preview URL instead of production.
#
# Env-vars-on-Vercel handling:
#   We diff `.env.local` against `vercel env ls` and only add the missing
#   ones to the production environment. Values are piped via stdin so
#   they never appear in process listings or shell history.
#
# Constraints:
#   - Must NOT echo secret values.
#   - Must work from any CWD (uses absolute REPO_ROOT).

set -euo pipefail

# -----------------------------------------------------------------------------
# Resolve repo root (this script lives at <repo>/scripts/deploy-app.sh)
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${REPO_ROOT}/apps/app"
ENV_FILE="${REPO_ROOT}/.env.local"

DRY_RUN=0
PROD=1

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --preview) PROD=0 ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      echo "[deploy-app] unknown arg: ${arg}" >&2
      exit 2
      ;;
  esac
done

log()  { printf '[deploy-app] %s\n' "$*"; }
warn() { printf '[deploy-app] WARN: %s\n' "$*" >&2; }
die()  { printf '[deploy-app] ERROR: %s\n' "$*" >&2; exit 1; }
run()  {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[deploy-app] dry-run: %s\n' "$*"
  else
    eval "$@"
  fi
}

# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------
command -v vercel >/dev/null 2>&1 || die "vercel CLI not found. Install with: npm i -g vercel"
[[ -d "${APP_DIR}" ]] || die "apps/app not found at ${APP_DIR}"
[[ -f "${ENV_FILE}" ]] || warn ".env.local not found at ${ENV_FILE} — env push will be skipped"

ENV_TARGET="production"
[[ "${PROD}" -eq 0 ]] && ENV_TARGET="preview"
log "target environment: ${ENV_TARGET}"
log "app dir: ${APP_DIR}"

# -----------------------------------------------------------------------------
# Sync env vars to Vercel (idempotent)
# Reads keys from .env.local (skips comments and PUBLIC_-only ones not used at
# build). For each missing key on Vercel, pipes the value via stdin to
# `vercel env add <KEY> <env>`.
# -----------------------------------------------------------------------------
sync_env() {
  [[ ! -f "${ENV_FILE}" ]] && return 0

  local allowlist=(
    NEXT_PUBLIC_SITE_URL
    NEXT_PUBLIC_APP_URL
    NEXT_PUBLIC_API_URL
    NEXT_PUBLIC_API_BASE_URL
    API_BASE_URL
    NEXT_PUBLIC_SUPABASE_URL
    NEXT_PUBLIC_SUPABASE_ANON_KEY
    NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
    NEXT_PUBLIC_POSTHOG_KEY
    NEXT_PUBLIC_POSTHOG_HOST
    NEXT_PUBLIC_SENTRY_DSN
    SUPABASE_SERVICE_ROLE_KEY
    SENTRY_AUTH_TOKEN
    SENTRY_ORG
    SENTRY_PROJECT
  )

  log "diffing .env.local against Vercel project env..."
  local existing
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    existing=""
  else
    existing="$(vercel env ls "${ENV_TARGET}" --cwd "${APP_DIR}" 2>/dev/null | awk 'NR>2 {print $1}' || true)"
  fi

  for key in "${allowlist[@]}"; do
    local line
    line="$(grep -E "^${key}=" "${ENV_FILE}" || true)"
    [[ -z "${line}" ]] && continue
    # strip optional surrounding quotes/whitespace from value (do NOT print it)
    local value="${line#*=}"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"

    if echo "${existing}" | grep -qx "${key}"; then
      log "  skip ${key} (already set)"
      continue
    fi

    if [[ "${DRY_RUN}" -eq 1 ]]; then
      printf '[deploy-app] dry-run: would add env %s to %s\n' "${key}" "${ENV_TARGET}"
    else
      # NOTE: piping via stdin — value never appears in argv or shell trace.
      printf '%s' "${value}" | vercel env add "${key}" "${ENV_TARGET}" --cwd "${APP_DIR}" >/dev/null \
        || warn "failed to add ${key}"
      log "  added ${key}"
    fi
  done
}

sync_env

# -----------------------------------------------------------------------------
# Deploy
# -----------------------------------------------------------------------------
if [[ "${PROD}" -eq 1 ]]; then
  log "deploying to PRODUCTION..."
  run "vercel --prod --cwd '${APP_DIR}' --yes"
else
  log "deploying preview..."
  run "vercel deploy --cwd '${APP_DIR}' --yes"
fi

log "done."
