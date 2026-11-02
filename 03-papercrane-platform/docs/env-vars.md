# Paper Crane — Environment Variables Reference

Every environment variable consumed by the Paper Crane platform. Source of
truth is `.env.example` at the repo root; this table explains what each one
is for, where to obtain it, and which services need it.

**Scope legend**

- `web` — `apps/web` (Next.js frontend)
- `api` — `apps/api` (backend service)
- `worker` — `apps/worker` (GPU job runner)
- `all` — every app and every long-running tool

**Required legend**

- `yes` — app will refuse to start without it
- `prod` — required in production, optional locally
- `no` — optional; feature-gated or has a sensible default

## Core

| Name        | Required | Scope | Description                                           | Where to get it                 | Default       |
|-------------|----------|-------|-------------------------------------------------------|---------------------------------|---------------|
| `NODE_ENV`  | yes      | all   | Runtime environment flag.                             | Set per deploy target.          | `development` |
| `LOG_LEVEL` | no       | all   | Pino log level: trace/debug/info/warn/error/fatal.    | Pick per environment.           | `info`        |

## Supabase (Auth + Postgres)

| Name                             | Required | Scope       | Description                                                      | Where to get it                                                                  | Default                                                   |
|----------------------------------|----------|-------------|------------------------------------------------------------------|----------------------------------------------------------------------------------|-----------------------------------------------------------|
| `NEXT_PUBLIC_SUPABASE_URL`       | yes      | web, api    | Public project URL, `https://<ref>.supabase.co`.                 | Supabase dashboard > Project Settings > API.                                     | —                                                         |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY`  | yes      | web, api    | Public anon key; safe in the browser.                            | Supabase dashboard > Project Settings > API.                                     | —                                                         |
| `SUPABASE_SERVICE_ROLE_KEY`      | yes      | api, worker | Privileged server key. Never ship to the client.                 | Supabase dashboard > Project Settings > API (Service Role section).              | —                                                         |
| `SUPABASE_PROJECT_REF`           | yes      | api, worker | Project ref slug, used by the CLI and migrations.                | The `<ref>` segment of the Supabase URL.                                         | —                                                         |
| `DATABASE_URL`                   | yes      | api, worker | Postgres connection string used by Prisma.                       | Local: the Docker compose value. Hosted: Supabase > Project Settings > Database. | `postgres://postgres:postgres@localhost:5432/papercrane`  |

## Redis (Upstash)

| Name        | Required | Scope       | Description                                  | Where to get it                                 | Default |
|-------------|----------|-------------|----------------------------------------------|-------------------------------------------------|---------|
| `REDIS_URL` | yes      | api, worker | Upstash Redis connection string (TLS).       | Upstash console > Database > Connect > Node.js. | —       |

## Object Storage (Cloudflare R2)

| Name                   | Required | Scope       | Description                                       | Where to get it                                                   | Default           |
|------------------------|----------|-------------|---------------------------------------------------|-------------------------------------------------------------------|-------------------|
| `R2_ACCOUNT_ID`        | yes      | api, worker | Cloudflare account ID.                            | Cloudflare dashboard > R2 landing page.                           | —                 |
| `R2_ACCESS_KEY_ID`     | yes      | api, worker | R2 API token access key ID.                       | Cloudflare dashboard > R2 > Manage API Tokens.                    | —                 |
| `R2_SECRET_ACCESS_KEY` | yes      | api, worker | Secret paired with the access key ID.             | Shown once at token creation; store in password manager.          | —                 |
| `R2_BUCKET`            | yes      | api, worker | Bucket name for uploads and design artifacts.     | Cloudflare dashboard > R2 > Overview.                             | `papercrane-dev`  |

## Stripe

| Name                        | Required | Scope | Description                                           | Where to get it                                                              | Default |
|-----------------------------|----------|-------|-------------------------------------------------------|------------------------------------------------------------------------------|---------|
| `STRIPE_SECRET_KEY`         | yes      | api   | Server secret key (`sk_test_` / `sk_live_`).          | Stripe dashboard > Developers > API keys.                                    | —       |
| `STRIPE_WEBHOOK_SECRET`     | yes      | api   | Endpoint signing secret (`whsec_`).                   | Stripe dashboard > Developers > Webhooks, or `stripe listen` output locally. | —       |
| `STRIPE_PRICE_PRO_MONTHLY`  | yes      | api   | Recurring price ID for Pro monthly plan.              | Stripe dashboard > Products.                                                 | —       |
| `STRIPE_PRICE_PRO_ANNUAL`   | yes      | api   | Recurring price ID for Pro annual plan.               | Stripe dashboard > Products.                                                 | —       |
| `STRIPE_PRICE_SEAT_ADDON`   | yes      | api   | Price ID for the per-seat add-on.                     | Stripe dashboard > Products.                                                 | —       |
| `STRIPE_PRICE_PACK_10K`     | yes      | api   | Price ID for the 10k-credit one-time pack.            | Stripe dashboard > Products.                                                 | —       |

## GPU Providers

| Name                 | Required | Scope  | Description                                     | Where to get it                              | Default           |
|----------------------|----------|--------|-------------------------------------------------|----------------------------------------------|-------------------|
| `MODAL_TOKEN_ID`     | yes      | worker | Modal auth token ID.                            | `modal token new` on your machine.           | —                 |
| `MODAL_TOKEN_SECRET` | yes      | worker | Modal auth token secret.                        | `modal token new` (paired with the ID).      | —                 |
| `MODAL_CREDENTIAL_ENCRYPTION_KEY` | yes in prod | api, worker | AES-256 key for linked organization Modal credentials. | `openssl rand -base64 32`; store the same value on API and worker. | — |

Before deploying the encryption-required worker over an existing database, set
the key on both services and run `pnpm modal:encrypt-credentials` once with
`DATABASE_URL` configured. The command reports row counts only and never prints
credential values.
| `MODAL_WORKSPACE`    | no       | worker | Optional workspace label used in logs. The token selects the real workspace. | —                              | —                 |
| `MODAL_ENVIRONMENT`  | no       | worker | Modal environment for system and linked-account jobs. | Modal dashboard > Environments.          | workspace default |
| `MODAL_SEED_PARALLELISM` | no   | worker | Per-job seed fan-out, clamped to 1–8.            | Set deliberately after capacity testing.     | 2 GPU / 4 CPU     |
| `VASTAI_API_KEY`     | no       | worker | Reserved; Vast.ai provider is not implemented.  | —                                            | —                 |
| `RUNPOD_API_KEY`     | no       | worker | Reserved; RunPod provider is not implemented.   | —                                            | —                 |

## Observability

| Name                   | Required | Scope       | Description                                          | Where to get it                                                | Default                      |
|------------------------|----------|-------------|------------------------------------------------------|----------------------------------------------------------------|------------------------------|
| `SENTRY_DSN`           | prod     | all         | Sentry project DSN for error reporting.              | Sentry dashboard > Project > Settings > Client Keys.           | —                            |
| `SENTRY_ENVIRONMENT`   | no       | all         | Tag attached to all Sentry events.                   | Pick per deploy target.                                        | `development`                |
| `POSTHOG_KEY`          | prod     | web, api    | PostHog project API key for product analytics.       | PostHog dashboard > Project settings.                          | —                            |
| `POSTHOG_HOST`         | no       | web, api    | PostHog ingest host.                                 | PostHog dashboard (US vs EU cloud).                            | `https://us.i.posthog.com`   |
| `LOGTAIL_SOURCE_TOKEN` | prod     | api, worker | BetterStack (Logtail) source token for log shipping. | BetterStack > Logs > Sources.                                  | —                            |

## Infisical (secrets bootstrap)

| Name                       | Required | Scope  | Description                                                   | Where to get it                                          | Default |
|----------------------------|----------|--------|---------------------------------------------------------------|----------------------------------------------------------|---------|
| `INFISICAL_CLIENT_ID`      | prod     | worker | Machine identity client ID used to fetch prod secrets.        | Infisical dashboard > Organization > Machine identities. | —       |
| `INFISICAL_CLIENT_SECRET`  | prod     | worker | Machine identity client secret.                               | Infisical dashboard > Machine identities > credentials.  | —       |
| `INFISICAL_PROJECT_ID`     | prod     | worker | Project holding the production secret bundle.                 | Infisical dashboard > Project > Settings.                | —       |

## App URLs

| Name                   | Required | Scope       | Description                                   | Where to get it                 | Default                 |
|------------------------|----------|-------------|-----------------------------------------------|---------------------------------|-------------------------|
| `NEXT_PUBLIC_APP_URL`  | yes      | web, api    | Public web app origin.                        | Set per environment.            | `http://localhost:3000` |
| `API_BASE_URL`         | yes      | web, worker | Internal API base URL (service-to-service).   | Set per environment.            | `http://localhost:3001` |
| `WORKER_URL`           | yes      | api         | Worker service URL for callbacks and status.  | Set per environment.            | `http://localhost:3002` |

## Feature Flags

| Name                        | Required | Scope    | Description                                     | Where to get it                 | Default |
|-----------------------------|----------|----------|-------------------------------------------------|---------------------------------|---------|
| `FEATURE_FRONTIER_TIER`     | no       | web, api | Enables enterprise Frontier SKU surfaces.       | Ops decision per environment.   | `false` |
| `FEATURE_PUBLIC_LEADERBOARD`| no       | web, api | Shows the public community leaderboard.         | Ops decision per environment.   | `true`  |

## Security

| Name              | Required | Scope | Description                                                   | Where to get it                    | Default                         |
|-------------------|----------|-------|---------------------------------------------------------------|------------------------------------|---------------------------------|
| `API_KEY_PEPPER`  | yes      | api   | 32-byte hex pepper added to API key hashes. Rotate per env.   | Generate: `openssl rand -hex 32`.  | `change-me-to-32-random-bytes`  |
