# Paper Crane — Deploy Env Mapping

Per-host glossary of which env vars must be set, where, and how. For the full
glossary of *what each variable means*, see `docs/env-vars.md`. For the deploy
runbook (rollback, GitHub secrets, troubleshooting), see `docs/deploy.md`.

Legend
- **PUBLIC** — `NEXT_PUBLIC_*` baked into the JS bundle at build time. Safe to
  expose to the browser.
- **SECRET** — server-only. NEVER expose to the browser, NEVER commit.
- **build** — required when the build runs (Vercel build / Docker build).
- **runtime** — required when the process starts (Fly machine boot, Vercel
  Function cold start).

---

## Vercel · `apps/app` (dashboard, https://app.papercrane.bio)

| Var                                  | Type   | When    | Notes                                   |
|--------------------------------------|--------|---------|-----------------------------------------|
| `NEXT_PUBLIC_SITE_URL`               | PUBLIC | build   | Marketing site origin                   |
| `NEXT_PUBLIC_APP_URL`                | PUBLIC | build   | This app's own origin                   |
| `NEXT_PUBLIC_BETA_GATE`              | PUBLIC | build/runtime | `true` for invite-only; must match API; apply admission migrations first |
| `NEXT_PUBLIC_API_URL`                | PUBLIC | build   | Fly api origin                          |
| `NEXT_PUBLIC_API_BASE_URL`           | PUBLIC | build   | Same value as `NEXT_PUBLIC_API_URL`; used by tRPC client |
| `API_BASE_URL`                       | SECRET | runtime | Same value as API origin; used by server-side tRPC calls |
| `NEXT_PUBLIC_SUPABASE_URL`           | PUBLIC | build   | Supabase project URL                    |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY`      | PUBLIC | build   | Supabase anon key                       |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | PUBLIC | build   | Stripe pk_                              |
| `NEXT_PUBLIC_POSTHOG_KEY`            | PUBLIC | build   |                                         |
| `NEXT_PUBLIC_POSTHOG_HOST`           | PUBLIC | build   |                                         |
| `NEXT_PUBLIC_SENTRY_DSN`             | PUBLIC | build   | Browser-side Sentry                     |
| `SUPABASE_SERVICE_ROLE_KEY`          | SECRET | runtime | Server-side admin client                |
| `SENTRY_AUTH_TOKEN`                  | SECRET | build   | Source map upload                       |
| `SENTRY_ORG`                         | SECRET | build   | Source map upload                       |
| `SENTRY_PROJECT`                     | SECRET | build   | App project slug                        |

Sample (run from `apps/app/`):

```bash
# Adds a value (will prompt for the value, or pipe via stdin):
printf '%s' "$VALUE" | vercel env add NEXT_PUBLIC_API_URL production
# List existing:
vercel env ls production
```

The all-in-one `scripts/deploy-app.sh` already handles this idempotently from
`.env.local`.

---

## Vercel · `apps/web` (marketing, https://papercrane.bio)

| Var                              | Type   | When    | Notes                              |
|----------------------------------|--------|---------|------------------------------------|
| `NEXT_PUBLIC_SITE_URL`           | PUBLIC | build   | Self-origin                        |
| `NEXT_PUBLIC_APP_URL`            | PUBLIC | build   | App origin (CTA links)             |
| `NEXT_PUBLIC_API_URL`            | PUBLIC | build   | API origin (login form)            |
| `NEXT_PUBLIC_SUPABASE_URL`       | PUBLIC | build   |                                    |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY`  | PUBLIC | build   |                                    |
| `NEXT_PUBLIC_POSTHOG_KEY`        | PUBLIC | build   |                                    |
| `NEXT_PUBLIC_POSTHOG_HOST`       | PUBLIC | build   |                                    |
| `NEXT_PUBLIC_SENTRY_DSN`         | PUBLIC | build   | Web project DSN                    |
| `SENTRY_AUTH_TOKEN`              | SECRET | build   |                                    |
| `SENTRY_ORG`                     | SECRET | build   |                                    |
| `SENTRY_PROJECT`                 | SECRET | build   | Web project slug                   |

The `apps/web` site is deployed by its own pipeline (`deploy-web.yml`); not in
the local `deploy-all.sh` flow by design.

---

## Fly.io · `papercrane-api` (api.papercrane.bio)

All values are SECRETs (runtime). Non-secret runtime config is hardcoded in
`apps/api/fly.toml` `[env]` (NODE_ENV, PORT, HOST, LOG_LEVEL).

| Var                                 | When    | Notes                                  |
|-------------------------------------|---------|----------------------------------------|
| `DATABASE_URL`                      | runtime | Supabase pooled connection             |
| `DIRECT_URL`                        | runtime | Direct Postgres (migrations only)      |
| `NEXT_PUBLIC_SUPABASE_URL`          | runtime | Supabase project URL                   |
| `NEXT_PUBLIC_BETA_GATE`             | runtime | `true` for invite-only; must match the app build |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY`     | runtime | Supabase anon key                      |
| `SUPABASE_PROJECT_REF`              | runtime | Supabase project ref for JWT verification |
| `SUPABASE_SERVICE_ROLE_KEY`         | runtime |                                        |
| `REDIS_URL`                         | runtime | Upstash (BullMQ producer)              |
| `R2_ACCOUNT_ID`                     | runtime | Cloudflare account id                  |
| `R2_ACCESS_KEY_ID`                  | runtime | R2 access key                          |
| `R2_SECRET_ACCESS_KEY`              | runtime | R2 secret                              |
| `R2_BUCKET`                         | runtime | R2 bucket                              |
| `R2_ENDPOINT`                       | runtime | Optional endpoint override             |
| `STRIPE_SECRET_KEY`                 | runtime |                                        |
| `STRIPE_WEBHOOK_SECRET`             | runtime |                                        |
| `SENTRY_DSN`                        | runtime | Server-side Sentry                     |
| `RESEND_API_KEY`                    | runtime | Transactional email                    |
| `MODAL_TOKEN_ID`                    | runtime | Optional API-side Modal dry runs       |
| `MODAL_TOKEN_SECRET`                | runtime | Optional API-side Modal dry runs       |
| `MODAL_WORKSPACE`                   | runtime | Optional workspace label for logs      |
| `MODAL_ENVIRONMENT`                 | runtime | Optional Modal environment             |

Sample:

```bash
flyctl secrets set --app papercrane-api \
  DATABASE_URL='postgres://...' \
  REDIS_URL='rediss://...'
flyctl secrets list --app papercrane-api
```

`scripts/deploy-api.sh` does this in one batched `secrets set --stage` call so
machines only restart once (during the subsequent `deploy`).

---

## Fly.io · `papercrane-worker` (no public URL)

Same set as api, minus the Stripe HTTP-frontend keys, plus compute-backend
tokens. Internal health endpoint on port 3003.

| Var                                 | When    | Notes                                  |
|-------------------------------------|---------|----------------------------------------|
| `DATABASE_URL`                      | runtime |                                        |
| `DIRECT_URL`                        | runtime |                                        |
| `NEXT_PUBLIC_SUPABASE_URL`          | runtime | Supabase project URL                   |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY`     | runtime | Supabase anon key                      |
| `SUPABASE_PROJECT_REF`              | runtime | Supabase project ref                   |
| `SUPABASE_SERVICE_ROLE_KEY`         | runtime |                                        |
| `REDIS_URL`                         | runtime | Same Upstash URL as api                |
| `R2_ACCOUNT_ID`                     | runtime |                                        |
| `R2_ACCESS_KEY_ID`                  | runtime |                                        |
| `R2_SECRET_ACCESS_KEY`              | runtime |                                        |
| `R2_BUCKET`                         | runtime |                                        |
| `R2_ENDPOINT`                       | runtime | Optional endpoint override             |
| `SENTRY_DSN`                        | runtime |                                        |
| `RESEND_API_KEY`                    | runtime |                                        |
| `WORKER_CONCURRENCY`                | runtime | Optional override of fly.toml default  |
| `PORT_HEALTH`                       | runtime | Must be `3003` on Fly                  |
| `MODAL_TOKEN_ID`                    | runtime | Modal compute backend                  |
| `MODAL_TOKEN_SECRET`                | runtime | Modal compute backend                  |
| `MODAL_WORKSPACE`                   | runtime | Optional workspace label for logs      |
| `MODAL_ENVIRONMENT`                 | runtime | Optional Modal environment             |
| `MODAL_SEED_PARALLELISM`            | runtime | Optional bounded seed fan-out (1–8)    |
| `VASTAI_API_KEY`                    | reserved | Provider not implemented              |
| `RUNPOD_API_KEY`                    | reserved | Provider not implemented              |

Sample:

```bash
flyctl secrets set --app papercrane-worker \
  MODAL_TOKEN_ID='ak-...' \
  MODAL_TOKEN_SECRET='as-...'
```

Or use `scripts/deploy-worker.sh` (recommended).

---

## CI: GitHub Environment `production`

The CI pipeline reads its secrets from the `production` GitHub Environment
(`docs/deploy.md` § "Required GitHub Secrets"). Those are NOT the same as
the per-host runtime vars above — CI just needs the tokens to *push* to the
host providers:

- Vercel: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID_APP`,
  `VERCEL_PROJECT_ID_WEB`
- Fly: `FLY_API_TOKEN` (org-scoped, used by both api and worker workflows)
- Supabase: `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD`,
  `SUPABASE_PROJECT_REF`

The actual per-host runtime vars are configured once on Vercel/Fly directly
(via these scripts or the dashboard) and persist across deploys.
