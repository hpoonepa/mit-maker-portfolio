# Paper Crane — Engineering Handoff

This is the single document a new engineer needs to ship Paper Crane and onboard
others. Pair it with `docs/setup.md`, `docs/deploy.md`, and `docs/env-vars.md`
for deeper material — this file is the spine.

Updated 2026-04-27 after Wave 14. Authored by Wave 14 / Agent 10.

---

## 1. Architecture

### Monorepo layout (pnpm + turbo)

```
papercrane/
  apps/
    web/        Next.js 16 marketing site            (port 3000)
    app/        Next.js 16 dashboard SPA             (port 3002)
    api/        Fastify + tRPC server                (port 3001)
    worker/     BullMQ worker, GPU job runner        (port 3003 internal)
    docs/       Public docs site                     (Vercel)
  packages/
    types/        Shared zod schemas + TS types
    db/           Prisma client + migrations + seed
    auth/         Supabase + argon2 helpers, RLS guards
    trpc/         Routers used by api + app
    billing/      Stripe checkout, webhooks, tiers
    storage/      R2 (S3-compatible) client + signed URLs
    jobs/         Job orchestration (queue, status, fan-out)
    observability/ Pino, Sentry, request-id, metrics
    tools-sdk/    Adapter contract shared by the registered GPU tools
    email/        Resend templates + send helpers
    brand/        Logo, favicon, colors
    ui/           Shared React component primitives
    cli/          `papercrane` Node CLI
    eslint-config/ Shared lint preset
  apps/cli/     CLI distribution shell (Homebrew tap)
  tools/        52 registered tool manifests + adapters; 12 GA, 39 runnable
                beta integrations, and Germinal catalog-only
  python/       papercrane-sdk (PyPI), Modal entrypoints
  benchmark/    Repro of head-to-head benchmark vs RFdiffusion + BindCraft
  deploy/       Fly.toml, Vercel project configs, Modal deploy scripts
  docker/       docker-compose for Postgres + Redis dev stack
  scripts/      Migration, seed, dev runners
  docs/         (this folder)
```

### Tech stack

| Layer         | Choice                                                    |
| ------------- | --------------------------------------------------------- |
| Frontend      | Next.js 16 App Router + React Server Components           |
| Styling       | Tailwind v4 + custom UI primitives in `packages/ui`       |
| API           | Fastify + tRPC v11 + Zod                                  |
| DB            | Postgres 16 (Supabase) via Prisma 5                       |
| Auth          | Supabase Auth (email + Google OAuth) + argon2 server keys |
| Cache/Queue   | Upstash Redis + BullMQ                                    |
| Storage       | Cloudflare R2 (S3 API)                                    |
| Realtime      | Supabase Realtime (job + design + notification channels)  |
| GPU compute   | Modal (primary); Vast.ai/RunPod overflow is planned       |
| Billing       | Stripe (Checkout + Customer Portal + webhooks)            |
| Email         | Resend                                                    |
| Observability | Sentry + PostHog + BetterStack (Logtail)                  |
| Secrets       | Infisical (prod), `.env.local` (dev)                      |

### Ports (local dev)

| Port | Service                       |
| ---- | ----------------------------- |
| 3000 | apps/web (marketing)          |
| 3001 | apps/api (tRPC + REST)        |
| 3002 | apps/app (dashboard)          |
| 3003 | apps/worker (admin + healthz) |
| 5432 | Postgres (docker-compose)     |
| 6379 | Redis (docker-compose)        |
| 9090 | Worker dashboard / metrics    |

---

## 2. Local development

```bash
git clone git@github.com:papercrane-bio/papercrane.git
cd papercrane
pnpm install
cp .env.example .env.local              # fill in Supabase, R2, Stripe keys
docker compose up -d                    # Postgres + Redis
pnpm db:migrate                         # apply Prisma migrations
pnpm db:seed                            # demo org, sample projects, tools
pnpm dev                                # turbo runs all four apps
```

Demo creds (regenerated each `pnpm db:seed`) are written to
`.agent-logs/20-demo-creds.txt`. Never commit this file.

If the api process won't start, check `apps/api/dist/` exists (`pnpm build`),
then verify Postgres + Redis are reachable on the default ports.

---

## 3. Deploy (per service env vars)

Service map: web + app on Vercel, api + worker on Fly.io, Postgres + auth on
Supabase, queue on Upstash Redis, GPU on Modal, billing on Stripe, files on R2.

### Vercel (apps/web — marketing)

- `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_POSTHOG_KEY`, `NEXT_PUBLIC_POSTHOG_HOST`
- `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT`

### Vercel (apps/app — dashboard)

- All of the above plus `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`
- `RESEND_FROM_EMAIL` for transactional links

### Fly.io (apps/api)

- `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PROJECT_REF`
- `REDIS_URL`, `R2_*` (4 vars), `STRIPE_*` (6 vars)
- `RESEND_API_KEY`, `RESEND_FROM_EMAIL`
- `SENTRY_DSN`, `LOGTAIL_SOURCE_TOKEN`
- `WORKER_URL` (internal Fly DNS)

### Fly.io (apps/worker)

- All api Fly vars **plus** `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`,
  `MODAL_WORKSPACE`
- `VASTAI_API_KEY`, `RUNPOD_API_KEY` are reserved for planned overflow providers
- `INFISICAL_CLIENT_ID/SECRET/PROJECT_ID` for prod secret bootstrap

### Supabase

- Run `supabase db push` in CI on `main`
- RLS policies live in `packages/db/prisma/migrations/*_rls.sql` —
  every table that joins on `org_id` has an `(org_id = auth.org_id())` policy
- `supabase functions deploy` is not used; we run server functions in api/worker

### Stripe

- 6 prices: Pro monthly, Pro annual, seat add-on, three credit packs (10k, 50k, 250k)
- Webhook endpoint: `https://api.papercrane.bio/v1/billing/webhook`
- Events: `checkout.session.completed`, `customer.subscription.updated`,
  `customer.subscription.deleted`, `invoice.payment_failed`,
  `invoice.payment_succeeded`

### R2

- Bucket `papercrane-prod`, public-read disabled
- CORS allow `https://app.papercrane.bio` and the Vercel preview wildcard
- All access via signed URLs from `packages/storage`

### Modal

- Workspace `papercrane-prod`
- Apps: `pc-rfdiffusion`, `pc-boltz1`, `pc-boltz2`, `pc-bindcraft`,
  `pc-boltzgen`, `pc-esm2`, `pc-alphafold3`, `pc-chai1`, `pc-chroma`,
  `pc-proteinmpnn`, `pc-ligandmpnn`, `pc-solublempnn`
- Deploy with `modal deploy tools/<name>/modal_app.py`

---

## 4. Operations

### Migrations

```bash
pnpm db:migrate:create -- --name "<change>"   # author migration
pnpm db:migrate                               # apply locally
# CI on main runs `prisma migrate deploy` against Supabase
```

### Seed

```bash
pnpm db:seed                                  # demo + sample projects
pnpm db:seed:tools                            # only refresh tool manifests
```

### Tests

```bash
pnpm test                          # all packages, vitest
pnpm test:tools                    # 52 manifest/schema/registry contracts
pnpm test --filter @papercrane/trpc
pnpm test:e2e                      # Playwright (apps/app)
```

### Logs

- Local: stdout from `pnpm dev` (json pino lines)
- Prod: `flyctl logs -a papercrane-api`, `flyctl logs -a papercrane-worker`
- BetterStack dashboard for searchable history
- Sentry for error groups + replay
- PostHog for product analytics

### View running jobs

`https://api.papercrane.bio/admin/queues` (Bull-Board, basic-auth gated by
`BULL_ADMIN_USER` / `BULL_ADMIN_PASSWORD`).

---

## 5. Tools — adding an adapter

Each tool is `tools/<name>/{manifest.json, adapter.ts, modal_app.py}`. To add
one:

1. Drop a `manifest.json` matching `packages/tools-sdk/src/manifest.ts`
   (id, version, inputs, outputs, gpu_class, expected_runtime_s, costs).
2. Implement `adapter.ts exporting `run(input, ctx) -> output`. Use
`@papercrane/tools-sdk` types.
3. Add `modal_app.py` with `@app.function(gpu="A100")` entrypoint.
4. Run `pnpm tools:conformance` — the harness in `tools/conformance/` will
   validate I/O shape, timeout, error path, and metrics.
5. Add a row to `pnpm db:seed:tools` so the tool picker shows it.
6. Append to the deploy GitHub Action `services` matrix.

`pnpm db:seed:tools` embeds each manifest's input/output schema and defaults in
the Tool row. The dashboard uses that input schema for typed advanced controls,
and `jobs.submit` validates tool-specific parameters before reserving quota or
writing a job. Re-run the command whenever a schema or default changes.

### Current 12 GA tools

`rfdiffusion · bindcraft · boltzgen · proteinmpnn · ligandmpnn · solublempnn ·
alphafold3 · boltz1 · boltz2 · chai1 · esm2 · chroma`

Runnable beta adapters (submission-enabled, pending GA remote smoke promotion):
`rfdiffusionaa · esmc · rfd3 · antifold · thermompnn · pdbfixer ·
rf3 · esmfold · disco · esmif1 · evoef2 · omegafold · immunebuilder · openmm-relax ·
foldseek · p2rank · freesasa · autodock-vina · plip · mmseqs2 · hmmer · mafft ·
dssp · fpocket · mdanalysis · pdb2pqr · propka · apbs · smina · protparam ·
parasail · cd-hit · diamond · hhsuite · prody · pdb-tools · prodigy · arpeggio ·
dockq`

Germinal is catalog-only and rejected before compute reservation because its
Modal image still contains a zeroed upstream commit placeholder.

---

## 6. Billing

Tiers (`packages/billing/src/tiers.ts`):

- **Free** — 500 designs/mo, 1 seat, public projects only, no API access
- **Pro** — 50,000 designs/mo, 5 seats, private projects, API + webhooks,
  priority queue
- **Frontier** — custom volume, SSO, audit log retention, dedicated support

Stripe price IDs (env-injected):
`STRIPE_PRICE_PRO_MONTHLY`, `STRIPE_PRICE_PRO_ANNUAL`,
`STRIPE_PRICE_SEAT_ADDON`, `STRIPE_PRICE_PACK_10K` / `_PACK_50K` / `_PACK_250K`.

Webhook setup: in Stripe → Developers → Webhooks add
`https://api.papercrane.bio/v1/billing/webhook` and copy the signing secret
into `STRIPE_WEBHOOK_SECRET`. Replay with `stripe trigger
checkout.session.completed` for local testing.

---

## 7. Email (Resend)

Templates live in `packages/email/templates/`:

- `welcome.tsx` — sent after signup
- `invite.tsx` — org invite link
- `job-finished.tsx` — pipeline completion
- `weekly-digest.tsx` — Monday 9am ET
- `payment-failed.tsx` — Stripe dunning

Test locally with `pnpm --filter @papercrane/email preview` (opens Resend's
React Email preview at :3010). Sends in dev are stubbed unless
`RESEND_API_KEY` is set; the worker logs a `[email:stub]` line instead.

---

## 8. Integrations

### Slack

OAuth dance in `apps/api/src/integrations/slack/`. Config: create a Slack app
with `chat:write` and `links:read` scopes, set redirect to
`https://api.papercrane.bio/v1/integrations/slack/callback`, store
`SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_SIGNING_SECRET`.

### Discord

Webhook-only (no OAuth). Users paste a webhook URL in Project → Settings →
Notifications. Verified with `Discord-Signature` header.

### Google OAuth

Handled by Supabase. In Supabase → Auth → Providers enable Google with
`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`. Redirect URI:
`https://<ref>.supabase.co/auth/v1/callback`. See `docs/supabase-oauth-setup.md`.

---

## 9. CLI

```bash
brew install papercrane-bio/papercrane/papercrane    # Homebrew tap
papercrane login
papercrane projects list
papercrane jobs submit --project <slug> --tools boltzgen --target 5J89
papercrane jobs status <jobId>
papercrane designs download <designId> --format fasta
```

CLI source: `packages/cli/src/`. Distribution shell + Homebrew formula in
`apps/cli/`. Build: `pnpm --filter @papercrane/cli build`.

---

## 10. API

- **tRPC**: routers in `packages/trpc/src/routers/` mounted at
  `https://api.papercrane.bio/trpc/*`. Apps consume via
  `@trpc/react-query`.
- **REST**: thin REST shims for partners at `/v1/projects`, `/v1/jobs`,
  `/v1/designs`. Full surface in `apps/api/src/rest/`.
- **OpenAPI**: served at `https://api.papercrane.bio/openapi.json`,
  rendered docs at `https://docs.papercrane.bio/api`.

API keys: `pcr_live_...` (32 bytes random + checksum suffix). Hashed with
argon2id; only the hash is stored. Scopes: `designs:read`, `designs:write`,
`jobs:read`, `jobs:write`, `targets:read`, `keys:rotate`, `admin:*`.

---

## 11. Security

- **RLS**: every multi-tenant table (`org_member`, `project`, `target`,
  `design`, `job`, `api_key`, `webhook`, `notification`) has a Postgres
  policy keyed on `org_id = auth.org_id()`. The `auth.org_id()` function
  reads from the JWT custom claim.
- **API keys**: argon2id hashed, prefix-indexed for fast lookup, never logged.
- **Webhook signing**: HMAC-SHA256 with timestamp + nonce; verifier in
  `packages/billing/src/verifySignature.ts` and
  `apps/worker/src/webhooks/signer.ts`.
- **Secrets**: never in repo. Local dev = `.env.local` (gitignored). Prod =
  Infisical machine identity.
- **Rate limit**: per-key sliding window via Redis Lua script
  (`packages/jobs/src/ratelimit.ts`). Defaults: 60 rpm Free, 600 rpm Pro.

---

## 12. Troubleshooting

| Symptom                                  | Cause                                                               | Fix                                                                                                                     |
| ---------------------------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `502 GET /api/trpc/*` from app           | api process not listening on 3001                                   | Check `pnpm --filter @papercrane/api dev` logs; common: Prisma `startsWith` on int                                      |
| `/app/settings` 500                      | Server passing function as a Client Component prop                  | Pass icon by string id; resolve in client. See `apps/app/components/settings/`                                          |
| Realtime channel never fires             | Supabase Realtime not enabled for the table                         | Supabase → Database → Replication → toggle table                                                                        |
| Mol\* viewer blank                       | PDB blob never resolved or chain id missing                         | See `apps/app/components/viewer/useMolstar.ts`; ensure `target.pdbBlobUrl` set                                          |
| Stripe webhook 400 "no signatures match" | `STRIPE_WEBHOOK_SECRET` mismatch (`stripe listen` vs prod endpoint) | Use the right secret per env; webhooks have separate dev + prod signing secrets                                         |
| Job stuck in `queued`                    | Worker not consuming; `redis:false` in `/healthz`                   | Verify `REDIS_URL`, then `flyctl logs -a papercrane-worker`                                                             |
| Modal job fails with `quota exceeded`    | Workspace concurrency cap hit                                       | Modal dashboard → Workspace → raise the cap or reduce `MODAL_SEED_PARALLELISM`; no overflow provider is implemented yet |
| Seed produces zero designs for demo org  | `seed.ts` skipped sample-project step                               | `pnpm db:seed` (full) — `db:seed:tools` only refreshes tool table                                                       |

---

## 13. Roadmap (post-Wave-14)

- **Real Modal deployment** — currently the worker uses a synth processor for
  status flips; switch each adapter's `modal_app.py` deploy to live in CI.
- **Stripe live mode** — flip `sk_test_` → `sk_live_`, run end-to-end Pro
  upgrade, verify webhook deliveries in Stripe dashboard.
- **Marketing copy review** — `apps/web` sections written for placeholder
  imagery; await Veo + Nano Banana Pro assets, swap, re-render OG cards.
- **Mol\* reliability** — `apps/app/components/viewer/useMolstar.ts` has 11
  TS suppressions; finish the typed wrapper.
- **iGEM HS Best Software defense** — bench-mark page (`/benchmark`) needs
  the published numbers + reproducible notebook link.
- **YC S26 demo** — 3-min walkthrough script aligned with this smoke flow.
