# Paper Crane — Production Deployment

End-to-end guide to take Paper Crane from `git clone` to traffic at
`papercrane.bio`. The target topology:

```
 papercrane.bio          → Vercel    → apps/web     (marketing landing)
 app.papercrane.bio      → Vercel    → apps/app     (product, Supabase auth)
 api.papercrane.bio      → Fly.io    → apps/api     (Fastify + tRPC)
 (internal)              → Fly.io    → apps/worker  (BullMQ + Modal providers)
 ──────────────────────────────────────────────────────────────────────
 Supabase (Postgres + Auth + Storage, RLS policies in packages/db/migrations)
 Upstash  (Redis for BullMQ + rate limit)
 Cloudflare R2 (artifacts: PDBs, logs, trajectories)
 Stripe   (billing, webhook → api.papercrane.bio/v1/billing/webhook)
 Modal    (GPU worker backend called from apps/worker)
 Sentry   (errors, release tracking)
 PostHog  (product analytics)
```

Nothing in this directory triggers a deploy on its own — secrets must be set
first. Everything is config.

---

## 0. One-time prerequisites

```bash
# CLIs
brew install flyctl supabase/tap/supabase terraform
npm i -g vercel@latest wrangler@latest

# Auth
fly auth login
vercel login
supabase login
wrangler login
```

You will also need accounts at: **Supabase**, **Upstash**, **Cloudflare (R2 on)**,
**Vercel**, **Fly.io**, **Stripe**, **Modal**, **Sentry**, **PostHog**.

---

## 1. Domain

1. Buy `papercrane.bio` (or your chosen domain) at Cloudflare Registrar or Namecheap.
2. Add it to Cloudflare as a Zone (free plan is fine).
3. Records (created automatically in later steps, but here's the target):

   | Host | Type  | Target                              |
   |------|-------|-------------------------------------|
   | `@`  | CNAME | `cname.vercel-dns.com`              |
   | `www`| CNAME | `cname.vercel-dns.com`              |
   | `app`| CNAME | `cname.vercel-dns.com`              |
   | `api`| CNAME | `papercrane-api.fly.dev`            |

4. After deploys succeed, run:
   ```bash
   vercel domains add papercrane.bio     --token=$VERCEL_TOKEN
   vercel domains add app.papercrane.bio --token=$VERCEL_TOKEN
   fly certs add api.papercrane.bio --app papercrane-api
   ```

---

## 2. Provision backend services

### 2a. Supabase (CLI)

```bash
supabase projects create papercrane-prod \
  --org-id <ORG_ID> \
  --db-password "$(openssl rand -base64 32)" \
  --region us-east-1
# → note the project ref (e.g. abcxyz123)

supabase link --project-ref <REF>
supabase db push --file packages/db/migrations
```

Record from the dashboard → **Project Settings → API**:
- `SUPABASE_URL` (`https://<ref>.supabase.co`)
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`   **(server-only, treat as crown jewel)**
- `DATABASE_URL` (pooler), `DIRECT_URL` (direct)

### 2b. Upstash Redis

Dashboard → **Create Database**:
- name `papercrane-queue`, region us-east-1, TLS on, eviction on
- copy `REDIS_URL` (rediss://) and `UPSTASH_REDIS_REST_*` tokens

### 2c. Cloudflare R2

```bash
wrangler r2 bucket create papercrane-artifacts
# Dashboard → R2 → Manage R2 API Tokens → Create
# Scope: Object R/W on papercrane-artifacts
# Save: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT
```

CORS (paste into dashboard or use `deploy/terraform/r2.tf`):
```json
[{ "AllowedOrigins": ["https://papercrane.bio","https://app.papercrane.bio"],
   "AllowedMethods": ["GET","PUT","POST","HEAD"],
   "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600 }]
```

### 2d. Stripe

Dashboard → **Developers → API Keys**:
- `STRIPE_SECRET_KEY` (sk_live_…)
- `STRIPE_PUBLISHABLE_KEY` (pk_live_…)

Webhook endpoint → `https://api.papercrane.bio/v1/billing/webhook`, events:
`checkout.session.completed`, `customer.subscription.updated`,
`customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`.
Copy the `whsec_…` signing secret as `STRIPE_WEBHOOK_SECRET`.

### 2e. Modal

```bash
modal token new --env papercrane-prod
# captures MODAL_TOKEN_ID + MODAL_TOKEN_SECRET
```

### 2f. Sentry

Create one project per app (`web`, `app`, `api`, `worker`). Copy each DSN.
Create an auth token (org:read, project:releases) → `SENTRY_AUTH_TOKEN`.

### 2g. PostHog

Create project → copy `POSTHOG_KEY` and `POSTHOG_HOST`
(`https://us.i.posthog.com`).

---

## 3. Optional: terraform for R2 + Upstash

See `deploy/terraform/README.md`. First deploy can skip this.

---

## 4. Create Vercel + Fly apps

### Vercel
```bash
# web
vercel link --project papercrane-web --yes --cwd apps/web
# app
vercel link --project papercrane-app --yes --cwd apps/app
```
Note the resulting `VERCEL_PROJECT_ID_WEB` and `VERCEL_PROJECT_ID_APP`.
In **Settings → Git**, disable "Auto-deploy on push" (GitHub Actions owns that).

### Fly.io
```bash
fly apps create papercrane-api    --org <ORG>
fly apps create papercrane-worker --org <ORG>
fly volumes create pc_api_tmp    --app papercrane-api    --region iad --size 1
```

---

## 5. Load secrets

### Vercel (web + app)
```bash
# from repo root, one-by-one or use `vercel env import .env.production`
vercel env add NEXT_PUBLIC_SUPABASE_URL         production --cwd apps/app
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY    production --cwd apps/app
vercel env add NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY production --cwd apps/app
# ...repeat for every NEXT_PUBLIC_* and SUPABASE_SERVICE_ROLE_KEY
# Same for web (subset — no service role, no stripe).
```

### Fly (api + worker)
```bash
fly secrets set --app papercrane-api \
  DATABASE_URL="..." DIRECT_URL="..." \
  SUPABASE_URL="..." SUPABASE_ANON_KEY="..." SUPABASE_SERVICE_ROLE_KEY="..." \
  REDIS_URL="rediss://..." \
  STRIPE_SECRET_KEY="..." STRIPE_WEBHOOK_SECRET="..." \
  R2_ACCESS_KEY_ID="..." R2_SECRET_ACCESS_KEY="..." R2_ENDPOINT="..." R2_BUCKET="papercrane-artifacts" \
  MODAL_TOKEN_ID="..." MODAL_TOKEN_SECRET="..." \
  SENTRY_DSN="..." \
  POSTHOG_KEY="..." POSTHOG_HOST="https://us.i.posthog.com"

fly secrets set --app papercrane-worker \
  DATABASE_URL="..." \
  REDIS_URL="rediss://..." \
  R2_ACCESS_KEY_ID="..." R2_SECRET_ACCESS_KEY="..." R2_ENDPOINT="..." R2_BUCKET="papercrane-artifacts" \
  MODAL_TOKEN_ID="..." MODAL_TOKEN_SECRET="..." \
  SENTRY_DSN="..."
```

### GitHub Actions secrets
Set under **Settings → Secrets and variables → Actions**:

| Secret                          | Consumers                                |
|---------------------------------|------------------------------------------|
| `VERCEL_TOKEN`                  | deploy-web.yml, deploy-app.yml           |
| `VERCEL_ORG_ID`                 | deploy-web.yml, deploy-app.yml           |
| `VERCEL_PROJECT_ID_WEB`         | deploy-web.yml                           |
| `VERCEL_PROJECT_ID_APP`         | deploy-app.yml                           |
| `FLY_API_TOKEN`                 | deploy-api.yml, deploy-worker.yml        |
| `SUPABASE_ACCESS_TOKEN`         | deploy-api.yml (migrate job)             |
| `SUPABASE_PROJECT_REF`          | deploy-api.yml                           |
| `SUPABASE_DB_PASSWORD`          | deploy-api.yml                           |
| `SENTRY_AUTH_TOKEN`             | deploy-web.yml, deploy-app.yml (sourcemaps) |
| `SENTRY_ORG`                    | deploy-web.yml, deploy-app.yml           |
| `SENTRY_PROJECT_WEB`            | deploy-web.yml                           |
| `SENTRY_PROJECT_APP`            | deploy-app.yml                           |

Everything else (Supabase keys, Stripe, Modal, R2, Upstash, PostHog) lives in
Vercel/Fly environments — **not** in GitHub Actions.

---

## 6. First deploy

```bash
git push origin main
```

Pipelines fire in parallel:
- `deploy-web.yml`     → Vercel
- `deploy-app.yml`     → Vercel
- `deploy-api.yml`     → migrate Supabase → deploy Fly
- `deploy-worker.yml`  → deploy Fly

Watch: `gh run watch`.

---

## 7. Verify

```bash
curl -I https://papercrane.bio                 # 200 from Vercel
curl -I https://app.papercrane.bio             # 200 from Vercel
curl    https://api.papercrane.bio/healthz     # {"status":"ok"}
fly status --app papercrane-worker             # Machines healthy
```

Stripe: **Developers → Webhooks → Send test event** → 200.

---

## 8. Rollback

### Vercel (web/app)
```bash
vercel rollback --cwd apps/web --token=$VERCEL_TOKEN
vercel rollback --cwd apps/app --token=$VERCEL_TOKEN
# or via the "Promote a previous deployment" UI button
```
Or trigger the workflow manually with the previous SHA.

### Fly (api/worker)
```bash
fly releases --app papercrane-api       # find previous version
fly deploy  --app papercrane-api --image-label v<N> --strategy immediate
# Or: trigger `deploy-api.yml` with rollback_to=v<N>
```

### Database
Supabase snapshot restore (Dashboard → Backups → Restore). Or targeted:
```bash
supabase db dump --db-url "$DATABASE_URL" > snap.sql
psql "$DATABASE_URL" < snap.sql
```

---

## 9. Post-deploy checklist

- [ ] Stripe webhook delivers to `api.papercrane.bio/v1/billing/webhook`
- [ ] Sentry receives error from test crash (`curl api/.../boom`)
- [ ] PostHog captures pageview on `app.papercrane.bio`
- [ ] Fly scale: `fly scale count 2 --region iad,sfo --app papercrane-api`
- [ ] Upstash alerts configured (eviction warning)
- [ ] R2 lifecycle rules active (90d logs, 365d artifacts)
- [ ] Uptime monitor (BetterStack / Pingdom) on all three public URLs

See `deploy/secrets-rotation.md` for the rotation runbook.
