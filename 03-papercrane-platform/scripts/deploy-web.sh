#!/usr/bin/env bash
# scripts/deploy-web.sh — One-shot Vercel deploy for apps/web
#
# Usage:
#   bash scripts/deploy-web.sh [--dry-run] [--preview]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${REPO_ROOT}/apps/web"
ENV_FILE="${REPO_ROOT}/.env.local"

DRY_RUN=0
PROD=1

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --preview) PROD=0 ;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[deploy-web] unknown arg: ${arg}" >&2; exit 2 ;;
  esac
done

log()  { printf '[deploy-web] %s\n' "$*"; }
warn() { printf '[deploy-web] WARN: %s\n' "$*" >&2; }
die()  { printf '[deploy-web] ERROR: %s\n' "$*" >&2; exit 1; }
run()  {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf '[deploy-web] dry-run: %s\n' "$*"
  else
    eval "$@"
  fi
}

command -v vercel >/dev/null 2>&1 || die "vercel CLI not found. Install with: npm i -g vercel"
[[ -d "${APP_DIR}" ]] || die "apps/web not found at ${APP_DIR}"
[[ -f "${ENV_FILE}" ]] || warn ".env.local not found at ${ENV_FILE} — env push will be skipped"

ENV_TARGET="production"
[[ "${PROD}" -eq 0 ]] && ENV_TARGET="preview"
log "target environment: ${ENV_TARGET}"
log "app dir: ${APP_DIR}"

sync_env() {
  [[ ! -f "${ENV_FILE}" ]] && return 0

  local allowlist=(
    NEXT_PUBLIC_SITE_URL
    NEXT_PUBLIC_APP_URL
    NEXT_PUBLIC_API_URL
    NEXT_PUBLIC_SUPABASE_URL
    NEXT_PUBLIC_SUPABASE_ANON_KEY
    NEXT_PUBLIC_POSTHOG_KEY
    NEXT_PUBLIC_POSTHOG_HOST
    NEXT_PUBLIC_SENTRY_DSN
    SENTRY_AUTH_TOKEN
    SENTRY_ORG
    SENTRY_PROJECT
  )

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
    local value="${line#*=}"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"

    if echo "${existing}" | grep -qx "${key}"; then
      log "  skip ${key} (already set)"
      continue
    fi

    if [[ "${DRY_RUN}" -eq 1 ]]; then
      printf '[deploy-web] dry-run: would add env %s to %s\n' "${key}" "${ENV_TARGET}"
    else
      printf '%s' "${value}" | vercel env add "${key}" "${ENV_TARGET}" --cwd "${APP_DIR}" >/dev/null \
        || warn "failed to add ${key}"
      log "  added ${key}"
    fi
  done
}

sync_env

if [[ "${PROD}" -eq 1 ]]; then
  log "deploying to PRODUCTION..."
  run "vercel --prod --cwd '${APP_DIR}' --yes"
else
  log "deploying preview..."
  run "vercel deploy --cwd '${APP_DIR}' --yes"
fi

log "done."
