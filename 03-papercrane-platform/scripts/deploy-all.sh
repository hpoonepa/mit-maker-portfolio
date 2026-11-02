#!/usr/bin/env bash
# scripts/deploy-all.sh — Deploy all four production services in order.
#
# Order: web (Vercel) -> app (Vercel) -> api (Fly) -> worker (Fly).
#
# Usage:
#   bash scripts/deploy-all.sh [--dry-run]
#
# Each step is sequential: a failure aborts the run (set -e). On success,
# prints a bullet list of public URLs at the end.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN_FLAG=""
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN_FLAG="--dry-run" ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[deploy-all] unknown arg: ${arg}" >&2; exit 2 ;;
  esac
done

banner() {
  printf '\n=========================================================\n'
  printf '   %s\n' "$*"
  printf '=========================================================\n\n'
}

START_TS=$(date +%s)

banner "1/4  apps/web  ->  Vercel"
bash "${SCRIPT_DIR}/deploy-web.sh" ${DRY_RUN_FLAG}

banner "2/4  apps/app  ->  Vercel"
bash "${SCRIPT_DIR}/deploy-app.sh" ${DRY_RUN_FLAG}

banner "3/4  apps/api  ->  Fly.io (papercrane-api)"
bash "${SCRIPT_DIR}/deploy-api.sh" ${DRY_RUN_FLAG}

banner "4/4  apps/worker  ->  Fly.io (papercrane-worker)"
bash "${SCRIPT_DIR}/deploy-worker.sh" ${DRY_RUN_FLAG}

ELAPSED=$(( $(date +%s) - START_TS ))

cat <<EOF

=========================================================
   Deploy complete in ${ELAPSED}s
=========================================================

Public URLs:
  - web     https://papercrane.bio              (Vercel)
  - app     https://app.papercrane.bio          (Vercel)
  - api     https://api.papercrane.bio          (Fly.io)
  - worker  (internal)                          (Fly.io — no public URL)

Verify:
  curl -fsS https://papercrane.bio
  curl -fsS https://api.papercrane.bio/healthz
  curl -fsS https://app.papercrane.bio/api/trpc/health

EOF
