# Paper Crane — Secrets Rotation Runbook

Rotate at least every 90 days, and immediately on any suspected exposure.
Every step here is **non-destructive** if followed in order (new key issued →
pushed → verified → old key revoked).

---

## Rotation order (if rotating everything at once)

1. Supabase service-role key       (highest blast radius)
2. Stripe secret + webhook secret
3. Modal token id/secret
4. `DATABASE_URL` password
5. R2 API token
6. Upstash Redis password
7. Sentry auth token
8. PostHog project key
9. Vercel, Fly, GitHub Actions platform tokens last (so you can still push)

Never rotate GitHub/Fly/Vercel platform tokens BEFORE app secrets — you may
lock yourself out of the very tools needed to push new app secrets.

---

## 1. Supabase `SUPABASE_SERVICE_ROLE_KEY`

**Where it's used:** `apps/api`, `apps/app` (server-side route handlers only).

```bash
# Dashboard → Project Settings → API → "Service role key" → Reset
NEW_KEY="<new service_role key>"

# Push to Fly (api) — triggers a rolling restart
fly secrets set --app papercrane-api SUPABASE_SERVICE_ROLE_KEY="$NEW_KEY"

# Push to Vercel (app) — affects the next deploy
vercel env rm  SUPABASE_SERVICE_ROLE_KEY production --cwd apps/app --yes
vercel env add SUPABASE_SERVICE_ROLE_KEY production --cwd apps/app <<< "$NEW_KEY"

# Re-deploy app (service-role is bundled into the build env)
gh workflow run deploy-app.yml --ref main

# Verify: curl -I https://app.papercrane.bio/api/health (should remain 200)
```

The old key is revoked automatically by Supabase when you click "Reset".

---

## 2. Stripe

### Webhook signing secret (`STRIPE_WEBHOOK_SECRET`)

```bash
# Dashboard → Developers → Webhooks → select the api.papercrane.bio endpoint
# → "Roll" (issues a new whsec_... and keeps the old one live for 24h)
NEW="whsec_..."
fly secrets set --app papercrane-api STRIPE_WEBHOOK_SECRET="$NEW"

# Verify: Dashboard → Webhooks → Send test event → 200
# Then in Stripe: "Expire rolled secret now" to kill the old one.
```

### API secret key (`STRIPE_SECRET_KEY`)

```bash
# Dashboard → Developers → API keys → "Roll" on restricted key
NEW="sk_live_..."
fly secrets set --app papercrane-api STRIPE_SECRET_KEY="$NEW"
# Verify a test charge; then revoke the old key from the dashboard.
```

---

## 3. Modal tokens (`MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`)

```bash
modal token new --env papercrane-prod --source ci-rotation
# Output: MODAL_TOKEN_ID + MODAL_TOKEN_SECRET

fly secrets set --app papercrane-api \
  MODAL_TOKEN_ID="..." MODAL_TOKEN_SECRET="..."
fly secrets set --app papercrane-worker \
  MODAL_TOKEN_ID="..." MODAL_TOKEN_SECRET="..."

# Once green for 10 min, revoke old token:
modal token list
modal token revoke <old-token-id>
```

---

## 4. `DATABASE_URL` (Postgres password)

**Risk:** writing the wrong thing here takes the API offline instantly. Run
during a low-traffic window and have a rollback value ready.

```bash
# Dashboard → Project Settings → Database → "Reset database password"
NEW="<new password>"

# Rebuild the pooler + direct URLs
REF="<supabase_project_ref>"
DB_URL="postgresql://postgres.${REF}:${NEW}@aws-0-us-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true"
DIRECT="postgresql://postgres:${NEW}@db.${REF}.supabase.co:5432/postgres?sslmode=require"

fly secrets set --app papercrane-api    DATABASE_URL="$DB_URL" DIRECT_URL="$DIRECT"
fly secrets set --app papercrane-worker DATABASE_URL="$DB_URL" DIRECT_URL="$DIRECT"

# If the app uses Supabase client via NEXT_PUBLIC_SUPABASE_URL + ANON_KEY only,
# you don't need to touch Vercel. If server code uses DATABASE_URL, rotate there too:
vercel env rm  DATABASE_URL production --cwd apps/app --yes
vercel env add DATABASE_URL production --cwd apps/app <<< "$DB_URL"
gh workflow run deploy-app.yml --ref main

# Verify: curl api/healthz (includes DB ping)
```

---

## 5. Cloudflare R2 API token

```bash
# Dashboard → R2 → Manage R2 API Tokens → Create new (R/W on papercrane-artifacts)
# → capture R2_ACCESS_KEY_ID + R2_SECRET_ACCESS_KEY

fly secrets set --app papercrane-api    R2_ACCESS_KEY_ID="..." R2_SECRET_ACCESS_KEY="..."
fly secrets set --app papercrane-worker R2_ACCESS_KEY_ID="..." R2_SECRET_ACCESS_KEY="..."

# Verify via /healthz (storage ping) then revoke old token.
```

---

## 6. Upstash Redis

```bash
# Dashboard → Database → "Reset Password"
# New endpoint stays the same; password changes.
NEW_URL="rediss://default:<new>@<endpoint>:<port>"
fly secrets set --app papercrane-api    REDIS_URL="$NEW_URL"
fly secrets set --app papercrane-worker REDIS_URL="$NEW_URL"
# BullMQ reconnects automatically on the rolling restart.
```

---

## 7. Sentry auth token (GitHub Actions only)

```bash
# Dashboard → User → Auth Tokens → New (scopes: project:releases, org:read)
# Update GitHub Actions: Settings → Secrets → SENTRY_AUTH_TOKEN
# Revoke the old token.
```

---

## 8. PostHog project API key

Client-side so exposure risk is lower, but still rotate ~quarterly.
PostHog doesn't "rotate" — you create a new project API key, swap it in,
then deactivate the old.

---

## 9. Platform tokens (rotate last)

| Token                 | Where                           | How                                         |
|-----------------------|----------------------------------|---------------------------------------------|
| `VERCEL_TOKEN`        | GH Actions secret                | vercel.com → Account → Tokens → Create      |
| `FLY_API_TOKEN`       | GH Actions secret                | `fly tokens create deploy -x 87600h`        |
| `SUPABASE_ACCESS_TOKEN`| GH Actions secret               | Supabase → Account → Access Tokens          |

---

## Break-glass: total compromise

1. Pause Stripe: dashboard → Developers → API keys → "Reveal / Roll" ALL.
2. Pause Fly machines: `fly scale count 0 --app papercrane-api`.
3. Revoke Supabase keys: dashboard → API → Reset anon + service-role.
4. Rotate Cloudflare API tokens + R2 tokens.
5. Rotate Upstash password.
6. Deploy fresh images with new secrets, scale back up.
7. File an incident report — what leaked, how, for how long.

---

## Rollback notes

Rotating a secret does **not** change code, so a Fly rollback (`fly deploy
--image-label v<prev>`) keeps using the most-recently-set secret value.
If the new secret is bad, `fly secrets set` the old value back immediately —
rolling restart picks it up in <30s.

Vercel promotes are atomic; if the new envs are broken, **Promote previous
deployment** from the Vercel UI reverts both code and environment.
