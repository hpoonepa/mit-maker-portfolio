# Paper Crane — Deploy Runbook

Short operational guide for deploying the four production services. For local
setup, see `docs/setup.md`. For the env var glossary (what each variable
means), see `docs/env-vars.md`.

## Topology

| Service | Stack         | Host    | URL (prod)                | Port (local) |
|---------|---------------|---------|---------------------------|--------------|
| web     | Next.js       | Vercel  | https://papercrane.bio    | 3000         |
| app     | Next.js       | Vercel  | https://app.papercrane.bio| 3002         |
| api     | Fastify/tRPC  | Fly.io  | https://api.papercrane.bio| 3001         |
| worker  | BullMQ Node   | Fly.io  | (no public URL)           | 3003         |

Postgres + auth + storage are managed by Supabase. Redis is provided by
Upstash in production and by `docker compose` locally.

## Pipelines

Pushes to `main` trigger `.github/workflows/deploy.yml`, which:

1. Runs the CI gate (lint + typecheck + test + build) once for the whole repo.
2. Fans out into the four per-service workflows in parallel:
   `deploy-web.yml`, `deploy-app.yml`, `deploy-api.yml`, `deploy-worker.yml`.
3. Each per-service job verifies a health endpoint and auto-rolls back on
   failure (Vercel `vercel rollback`, Fly `flyctl deploy --image-label v<prev>`).
4. A `summary` job posts a per-service pass/fail table to the run summary.

You can also deploy a subset on demand:

```
gh workflow run deploy.yml -f services=api,worker
```

Or trigger a single service workflow directly via `workflow_dispatch`.

## Required GitHub Secrets

All secrets live on the `production` GitHub Environment. Names only — never
commit values.

### Shared (all four services)

- `SUPABASE_ACCESS_TOKEN`
- `SUPABASE_DB_PASSWORD`
- `SUPABASE_PROJECT_REF`

### Vercel (web + app)

- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID_WEB`
- `VERCEL_PROJECT_ID_APP`

### Fly.io (api + worker)

- `FLY_API_TOKEN` (single org-scoped token used by both apps)

## Required Vercel Project Env Vars

Set these per project (`web`, `app`) in Vercel → Settings → Environment
Variables, scoped to `production` and `preview`. Names match the `env` block
in each app's `vercel.json`.

### `apps/web` (landing)

- `NEXT_PUBLIC_SITE_URL`
- `NEXT_PUBLIC_APP_URL`
- `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_API_BASE_URL`
- `API_BASE_URL`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_POSTHOG_KEY`
- `NEXT_PUBLIC_POSTHOG_HOST`
- `NEXT_PUBLIC_SENTRY_DSN`
- `SENTRY_AUTH_TOKEN`
- `SENTRY_ORG`
- `SENTRY_PROJECT` (web project slug)

### `apps/app` (dashboard)

All web vars above except web-specific Sentry project, plus:

- `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SENTRY_PROJECT` (app project slug)

## Required Fly Secrets

Set with `fly secrets set --app <app> KEY=value`. Non-secret runtime config
already lives in `fly.toml`'s `[env]` block.

### `papercrane-api`

- `DATABASE_URL`
- `DIRECT_URL`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `SUPABASE_PROJECT_REF`
- `SUPABASE_SERVICE_ROLE_KEY`
- `REDIS_URL` (Upstash)
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `SENTRY_DSN`
- `RESEND_API_KEY`
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `MODAL_WORKSPACE`
- `MODAL_CREDENTIAL_ENCRYPTION_KEY` (same 32-byte base64/hex value on API and worker)

### `papercrane-worker`

Same as api, minus the Stripe keys, plus:

- `WORKER_CONCURRENCY` (optional override of the `[env]` default)
- `PORT_HEALTH` (set to `3003` on Fly)
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` (compute backends)
- `VASTAI_API_KEY`, `RUNPOD_API_KEY` are reserved; do not configure them until
  those providers and their artifact-contract tests are implemented.

## Manual Deploy / Rollback

### Vercel (web | app)

```
# Deploy
vercel deploy --prod --cwd apps/web   --token "$VERCEL_TOKEN"
vercel deploy --prod --cwd apps/app   --token "$VERCEL_TOKEN"

# Rollback to previous production deployment
vercel rollback --cwd apps/web --token "$VERCEL_TOKEN" --yes
vercel rollback --cwd apps/app --token "$VERCEL_TOKEN" --yes
```

### Fly (api | worker)

```
# Deploy
flyctl deploy --app papercrane-api    --config apps/api/fly.toml    --dockerfile apps/api/Dockerfile    --remote-only
flyctl deploy --app papercrane-worker --config apps/worker/fly.toml --dockerfile apps/worker/Dockerfile --remote-only

# List releases (find the one to roll back to)
flyctl releases --app papercrane-api

# Rollback to a specific image tag
flyctl deploy --app papercrane-api --image-label v42 --remote-only --strategy immediate
```

Both deploy workflows accept a `rollback_to` input via
`gh workflow run deploy-api.yml -f rollback_to=v42`.

## Local Integration Smoke Test

Boots the entire stack and probes every health endpoint:

```
bash scripts/smoke-test.sh
```

Useful flags:

- `SKIP_DOCKER=1` — assume `redis`/`minio` are already running.
- `KEEP_RUNNING=1` — leave services up after the run (useful for debugging).

Logs land in `.smoke-logs/`. Cleanup runs on every exit path (success,
failure, Ctrl-C) via a bash `trap`.

## Health Endpoints

| Service | Path                  | Notes                              |
|---------|-----------------------|------------------------------------|
| web     | `/`                   | 200 = page rendered                |
| app     | `/api/trpc/health`    | tRPC `health` procedure            |
| api     | `/healthz`            | Fastify route, used by Fly checks  |
| worker  | `/healthz`            | Internal-only port 3003 liveness   |

## Troubleshooting

- **Vercel build fails with `pnpm: command not found`** — ensure
  `ENABLE_EXPERIMENTAL_COREPACK=1` is in the project's build env.
- **Fly health check stuck `pending`** — `flyctl logs --app <app>` and check
  the container is binding to `0.0.0.0`, not `127.0.0.1`.
- **Worker deploy succeeds but jobs do not run** — verify `REDIS_URL` is set
  via `flyctl secrets list --app papercrane-worker` and matches the api's.
- **Smoke test hangs on `app`** — first `next dev` of a clean checkout
  compiles the entire route tree; bump the `wait_for_url` timeout or warm
  with `pnpm --filter @papercrane/app build` first.
