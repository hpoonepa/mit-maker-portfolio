# Paper Crane Core Platform Architecture

**Version 1.0 — 2026-04-23**
**Scope:** Core platform (auth, API, data, orchestration, storage, frontend, deployment)
**Out of scope:** Tool wrapping (plan 02), GPU scheduling (plan 03), benchmark (plan 04), billing (plan 05)

---

## 1. Overall System Architecture

Paper Crane is a **modular monolith** on the API side, with a **separate orchestrator worker** for long-running jobs. Not microservices. A two-person team cannot operate five independently-deployed services.

```
                         ┌──────────────────────────────────┐
                         │   papercrane.bio (Vercel)        │
                         │   Next.js 16 RSC + API routes    │
                         │   - Marketing + dashboard        │
                         │   - Auth callbacks (Supabase)    │
                         │   - Thin BFF over core API       │
                         └──────────────┬───────────────────┘
                                        │ tRPC/HTTPS
                                        ▼
┌──────────────────────────────────────────────────────────────────┐
│            api.papercrane.bio (Fly.io — core API)                │
│  Fastify + tRPC + Prisma                                         │
│  ├── Auth gateway (Supabase JWT + API-key middleware)            │
│  ├── Projects / Jobs / Targets / Results service modules         │
│  ├── Usage meter (seed debits)                                   │
│  └── Webhook dispatcher                                          │
└──────────────┬─────────────────────────────┬─────────────────────┘
               │                             │
               ▼                             ▼
┌────────────────────────┐        ┌─────────────────────────────┐
│  Postgres (Supabase)   │        │  Redis (Upstash)            │
│  - RLS-enforced tenant │        │  - BullMQ queue             │
│  - jobs, designs,      │        │  - Rate limits              │
│    targets, usage      │        │  - SSE pubsub               │
└────────────────────────┘        └──────────────┬──────────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │  Orchestrator (Fly.io)       │
                                  │  BullMQ worker — Node        │
                                  │  - Claims jobs               │
                                  │  - Dispatches to GPU adapter │
                                  │  - Writes artifacts + state  │
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │  GPU Adapter (plan 03 scope) │
                                  │  Modal / Vast.ai / VPC K8s   │
                                  └──────────────┬───────────────┘
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │  R2 (Cloudflare) — artifacts │
                                  │  + Supabase Storage (small)  │
                                  └──────────────────────────────┘
```

**Why this shape:**
- **Monolith API** keeps domain logic co-located. Protein design is one bounded context — splitting it into services creates distributed-systems tax we cannot pay.
- **Separate orchestrator process** because job workers must not share request lifecycle with API. Crash isolation is non-negotiable when jobs run 2–24 hours.
- **Fastify + Node** not Python: Next.js BFF speaks tRPC natively, one runtime to operate, Python lives only inside GPU workers where it must.
- **Fly.io** for API+worker: long-running processes, regions for Frontier VPC, cheaper than Vercel Functions once jobs persist connections.

---

## 2. API Design

**Recommendation: tRPC for web dashboard, REST for public API and Frontier integrations.** Two surfaces, one core.

Web uses tRPC so the Next.js dashboard gets end-to-end types with zero OpenAPI generator pipeline. The same routers are re-exported via `trpc-to-openapi` to generate a clean REST surface at `api.papercrane.bio/v1/*`.

**Core endpoints (REST):**

| Resource | Endpoints |
|---|---|
| Auth | `POST /v1/auth/token` (API key exchange), `POST /v1/auth/rotate` |
| Projects | `GET/POST /v1/projects`, `GET/PATCH/DELETE /v1/projects/:id` |
| Targets | `POST /v1/targets` (upload PDB), `GET /v1/targets/:id` |
| Jobs | `POST /v1/jobs`, `GET /v1/jobs/:id`, `POST /v1/jobs/:id/cancel`, `GET /v1/jobs/:id/events` (SSE) |
| Designs | `GET /v1/jobs/:id/designs`, `GET /v1/designs/:id`, `GET /v1/designs/:id/artifact` (presigned) |
| Webhooks | `GET/POST /v1/webhooks`, `DELETE /v1/webhooks/:id` |
| Usage | `GET /v1/usage/current`, `GET /v1/usage/history` |
| API keys | `GET/POST /v1/keys`, `DELETE /v1/keys/:id` |

**Rate limiting:** token bucket in Redis, keyed by `(api_key, endpoint_class)`. Free: 60 req/min, Pro: 600 req/min, Frontier: negotiated. Job submission bucket is separate and seed-budget-bound, not request-count-bound.

**Webhooks:** HMAC-SHA256 signed (`X-PaperCrane-Signature`), `job.completed`, `job.failed`, `design.top_hit` events. Retries with exponential backoff (1m, 5m, 30m, 2h, 12h), dead-lettered after 5 attempts.

---

## 3. Data Model

PostgreSQL 15 on Supabase. Every tenant-scoped table carries `org_id` and is RLS-protected.

```sql
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,
  tier TEXT NOT NULL CHECK (tier IN ('free','pro','frontier')),
  seeds_quota INT NOT NULL DEFAULT 0,
  seeds_used INT NOT NULL DEFAULT 0,
  retention_days INT NOT NULL DEFAULT 7,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE users (
  id UUID PRIMARY KEY REFERENCES auth.users(id),
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  default_org_id UUID REFERENCES organizations(id)
);

CREATE TABLE org_members (
  org_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  role TEXT CHECK (role IN ('owner','admin','member','viewer')),
  PRIMARY KEY (org_id, user_id)
);

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organizations(id),
  name TEXT NOT NULL,
  created_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE targets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organizations(id),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  pdb_id TEXT,                    -- if from RCSB
  artifact_key TEXT NOT NULL,     -- R2 object key
  hotspots JSONB,                 -- [{chain:'A', residues:[34,56]}]
  checksum TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organizations(id),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  target_id UUID REFERENCES targets(id),
  tool TEXT NOT NULL,             -- 'rfdiffusion', 'boltz2', ...
  tool_version TEXT NOT NULL,
  params JSONB NOT NULL,
  seeds_requested INT NOT NULL,
  status TEXT NOT NULL,           -- state machine in §5
  gpu_backend TEXT,               -- 'modal'|'vastai'|'vpc'
  seeds_consumed INT DEFAULT 0,
  error JSONB,
  submitted_at TIMESTAMPTZ DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL -- enforces retention
);
CREATE INDEX ON jobs (org_id, status, submitted_at DESC);
CREATE INDEX ON jobs (expires_at) WHERE status IN ('succeeded','failed');

CREATE TABLE designs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  org_id UUID NOT NULL REFERENCES organizations(id),
  seed INT NOT NULL,
  metrics JSONB NOT NULL,         -- ipsae, dockq, ptmenergy, iptm, plddt
  artifact_key TEXT NOT NULL,     -- PDB/CIF in R2
  rank INT,                       -- populated after scoring
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON designs (job_id, rank);
CREATE INDEX ON designs USING GIN (metrics);

CREATE TABLE api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organizations(id),
  name TEXT NOT NULL,
  prefix TEXT NOT NULL,           -- first 8 chars for display
  hash TEXT NOT NULL,             -- argon2id of full key
  scopes TEXT[] NOT NULL,
  last_used_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX ON api_keys (hash) WHERE revoked_at IS NULL;

CREATE TABLE usage_seeds (
  id BIGSERIAL PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES organizations(id),
  job_id UUID REFERENCES jobs(id),
  seeds INT NOT NULL,             -- +credit or -debit
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON usage_seeds (org_id, created_at DESC);
```

**RLS policy pattern** — every tenant table gets this shape:

```sql
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY jobs_tenant_isolation ON jobs
  USING (org_id IN (
    SELECT org_id FROM org_members WHERE user_id = auth.uid()
  ));
```

The API server connects with a service role that bypasses RLS, then sets `SET LOCAL app.current_user = $uid` per request. For direct Supabase client queries (rare — only user profile), RLS enforces isolation in the database itself. Defense in depth.

---

## 4. Auth & Identity

**Use Supabase Auth.** Already in toolkit, free tier covers launch, supports OAuth (Google, GitHub), magic links, and SAML SSO on Pro plan ($25/mo) — which is exactly where Frontier tier needs it. Clerk is better DX but $25/mo per tier we do not need when Supabase is already in the stack.

| Tier | Auth methods |
|---|---|
| Free | Email+password, Google OAuth |
| Pro | Above + Google Workspace domain restriction |
| Frontier | Above + SAML/OIDC (Supabase Pro plan handles this) |

**API key format:**

```
pc_live_sk_<26 chars base62>   e.g. pc_live_sk_7Q2mN9vK4pRxL8fZ3tYwBcH1dA
pc_test_sk_<26 chars base62>
```

Storage: store `prefix` (first 8 chars visible for UI) and `argon2id(full_key)` in `api_keys.hash`. On auth, the middleware hashes the incoming key and looks it up by hash (unique index). Rotation: new key issued with 24h grace period where both work; rotation surfaced in dashboard with last-used timestamps.

```typescript
// API-key auth middleware (Fastify)
export async function authenticateApiKey(req, reply) {
  const header = req.headers.authorization?.replace('Bearer ', '');
  if (!header?.startsWith('pc_')) return reply.code(401).send();
  const hash = await argon2.hash(header, ARGON_OPTS);
  const key = await db.apiKeys.findFirst({
    where: { hash, revokedAt: null },
    include: { org: true },
  });
  if (!key) return reply.code(401).send();
  await db.apiKeys.update({ where: { id: key.id }, data: { lastUsedAt: new Date() }});
  req.auth = { orgId: key.orgId, tier: key.org.tier, scopes: key.scopes };
}
```

---

## 5. Job Orchestration

**Queue: BullMQ on Upstash Redis.** Not Postgres-based (pg_boss) because we need per-stage concurrency controls and delayed retries without hammering the main DB. Not Temporal — operational overhead too high for two people. Not SQS — Redis is already in stack for rate limits and pubsub.

**State machine:**

```
          submit
             │
             ▼
        [queued] ──cancel──> [cancelled]
             │
       claim │
             ▼
       [preparing] ──cancel──> [cancelling] ──> [cancelled]
             │
   gpu ready │
             ▼
        [running] ──cancel──> [cancelling] ──> [cancelled]
         │    │     │
    seeds│    │     │ crash
         ▼    ▼     ▼
  [partial][succeeded][failed] ──retry──> [queued]
         │                  │
      continue              └──> expire (retention) ──> [purged]
         │
         ▼
     [succeeded]
```

Key rules:
- **Partial streaming:** designs land in `designs` table as each seed finishes. Clients can poll or SSE-subscribe to `/v1/jobs/:id/events` and see results arrive live. This is a must-have for 50K-seed jobs — nobody waits 8 hours to see anything.
- **Cancellation** is cooperative: sets `status='cancelling'`, worker checks flag every seed, flushes completed designs, transitions to `cancelled`.
- **Retries:** only on infrastructure errors (GPU preemption, network), not user errors (bad input). Max 3 retries, exponential backoff. User-error jobs go straight to `failed` with structured error JSON.
- **Seed accounting:** `seeds_consumed` updated transactionally with each completed design. If job fails mid-run on a managed tier, only consumed seeds are billed.

```typescript
// job events (published to Redis pubsub by worker, SSE'd to client)
type JobEvent =
  | { type: 'status'; status: JobStatus }
  | { type: 'design'; designId: string; seed: number; metrics: Metrics }
  | { type: 'progress'; completed: number; total: number }
  | { type: 'error'; retryable: boolean; message: string };
```

---

## 6. Storage Strategy

**Cloudflare R2 for artifacts, Supabase Storage for small user-facing files (avatars, small target PDBs < 5 MB).** R2 because egress is free — critical when Frontier customers download 100 GB result sets. S3 would cost $9/TB egress. Supabase Storage is fine for small stuff and keeps auth unified.

**Layout:**
```
r2://papercrane-prod/
  orgs/{org_id}/targets/{target_id}/input.pdb
  orgs/{org_id}/jobs/{job_id}/designs/{seed}.cif
  orgs/{org_id}/jobs/{job_id}/metrics.parquet
  orgs/{org_id}/jobs/{job_id}/logs/worker-{attempt}.log
```

- **Presigned URLs:** all downloads go through `/v1/designs/:id/artifact` which generates a 15-minute presigned GET. Uploads use presigned PUT with content-length and checksum enforced server-side after upload.
- **Input validation:** PDB/CIF files scanned with a sandboxed parser (gemmi) before storage. Reject malformed structures, enforce size limits (50 MB targets free, 500 MB Pro).
- **Retention enforcement:** a nightly cron on the orchestrator node runs `DELETE FROM jobs WHERE expires_at < now() AND status IN ('succeeded','failed')`. A trigger cascades to `designs`, and a separate sweeper deletes R2 objects by prefix. Retention set per-tier on job creation.
- **Frontier VPC:** R2 replaced with customer-owned S3 bucket via assume-role. Artifacts never leave their account.

---

## 7. Frontend Architecture

**Next.js 16 with App Router and RSC-first.**

| Page | Rendering |
|---|---|
| Marketing (`/`, `/pricing`, `/benchmark`, `/docs`) | Static RSC |
| Dashboard shell (`/app/*`) | RSC with streaming |
| Job submission form | Client component, tRPC mutation |
| Job detail view | RSC initial render + client SSE subscription |
| 3D viewer | Client component, dynamic import, no SSR |

**3D viewer: Mol*** (not NGL). Mol* is the modern standard, maintained, ships as a web component, handles CIF/mmCIF/PDB natively, renders binder+target complexes with surface + cartoon overlays. NGL is fine but maintenance has slowed.

**State management:** React Server Components for reads, tRPC + React Query for mutations and live updates. No Redux, no Zustand — overkill. Local component state for transient UI (form drafts, sort order).

**Real-time updates:** Server-Sent Events over websockets. SSE is one-directional (server→client), which is all we need for job progress. Cheaper on Fly.io, survives HTTP/2, no sticky session juggling. The endpoint `GET /v1/jobs/:id/events` streams `text/event-stream`, backed by Redis pubsub channel `job:{id}`. Client uses `EventSource` with a reconnect wrapper.

**Result browser:** virtualized table (TanStack Table + React Virtual) for 50K-design result sets, multi-axis filtering on `metrics` JSONB (ipSAE >= 0.7, pTMEnergy <= -30, etc.), compare-mode selects N designs and shows side-by-side Mol* viewers.

---

## 8. Deployment Topology

| Component | Host | Why |
|---|---|---|
| `papercrane.bio` (Next.js) | Vercel | Already in stack; RSC streaming best-in-class |
| `api.papercrane.bio` (Fastify) | Fly.io (2 machines, sfo+iad) | Long-lived connections, SSE, cheaper than Vercel Functions for steady traffic |
| Orchestrator worker | Fly.io (1 machine, sfo) | Co-located with API, scales by queue depth |
| Postgres | Supabase (project `papercrane-prod`) | Already in stack; RLS + Auth + realtime |
| Redis | Upstash | Serverless Redis, pay-per-request, BullMQ-compatible |
| Object storage | Cloudflare R2 | Zero egress fees |
| DNS + edge | Cloudflare | R2 parity, WAF on API |

**Environments:**
- `dev` — local, Docker Compose (postgres + redis + minio), seeded via `prisma db seed`
- `staging` — `staging.papercrane.bio`, separate Supabase project, separate Fly app, staging Modal workspace, real R2 bucket, synthetic data only
- `prod` — `papercrane.bio`, separate Supabase project, Fly apps in 2 regions

**Frontier VPC deploys:** one-click via a Terraform module that provisions Supabase Dedicated + Fly org + customer-AWS R2 + Modal tenant. Day-1 target: 3-day white-glove deploy. Year-1 target: 1-hour self-serve.

---

## 9. Observability

| Concern | Tool | Reason |
|---|---|---|
| Logs | Better Stack (Logtail) | Cheaper than Axiom at our volume; structured JSON; native Fly drain |
| Metrics | Prometheus on Fly + Grafana Cloud free tier | Open standards; no vendor lock when we scale |
| Errors | Sentry | Industry default; Next.js + Node instrumentation excellent |
| Product analytics | PostHog (self-host later, cloud now) | Open source; event + session + feature flags in one |
| Uptime | Better Stack Uptime | Bundled with logs; external probes on `/healthz` every 30s |
| Traces | Sentry Performance (OpenTelemetry) | Already have Sentry; OTel gives job-level traces across API→worker |

Every job emits a trace spanning API submission → queue wait → worker claim → GPU adapter → storage write. This is what lets us debug "why did seed 4,371 take 12 minutes."

---

## 10. Security & Compliance

- **Tenant isolation:** org_id on every row, RLS at DB, org_id check in every API handler, R2 prefix isolation, queue namespacing (`queue:{org_id}:jobs`).
- **Secrets:** Infisical for app secrets (API keys for Modal, Anthropic, Stripe, etc.). Vercel env vars only for Next.js public vars. Fly secrets for infra bootstrap. No secrets in Git, ever. Pre-commit hook with `gitleaks`.
- **Input validation:** zod schemas at every API boundary, re-used by tRPC and OpenAPI generator. File uploads: MIME sniff, size check, gemmi parse, then accept.
- **File upload scanning:** PDB/CIF files parsed in a worker sandbox (separate Fly machine with no secrets, no network). Rejected files never reach main storage.
- **Data residency:** Free/Pro is US-east (Supabase + Fly iad + R2 auto). Frontier offers EU (eu-west-1) and customer-VPC options. SOC 2 Type I targeted by month 9, Type II by month 18.
- **Rate limiting + abuse:** Cloudflare WAF in front of everything. Signup requires verified email + hCaptcha. Free tier seeds quota prevents GPU abuse.

---

## 11. Build Sequence — 8 Milestones

Harsha is part-time during school (Apr 23 – May 23, Aug 5+) and full-time summer (May 24 – Aug 4). Vedant assumed similar. **10 weeks summer full-time + ~3 days/week during school.**

| M | Scope | Team-weeks | Calendar target |
|---|---|---|---|
| **M1: Auth + dashboard shell** | Supabase Auth, org/user/member tables, dashboard layout, empty project list, API-key CRUD UI | 2 | May 18 |
| **M2: First job E2E (BindCraft)** | One tool wrapped, job submission form, queue, worker, Modal adapter, results page with Mol*, SSE | 4 | Jun 15 |
| **M3: Targets + projects + storage** | Upload target PDB, hotspot picker, R2 presigned flow, retention cron, project organization | 2 | Jun 29 |
| **M4: Public REST API + keys** | OpenAPI generated from tRPC, API-key middleware, rate limits, Python client stub | 1.5 | Jul 10 |
| **M5: Seed accounting + usage** | usage_seeds ledger, quota enforcement, dashboard usage charts (billing plan 05 picks up invoicing) | 1.5 | Jul 21 |
| **M6: Tools 2–6 + result browser** | ProteinMPNN, RFdiffusion, Boltz-2, Chai-1, AF3 wrapped; virtualized result table; filter/compare | 3 | Aug 11 |
| **M7: Webhooks + SSO + org mgmt** | Webhook subscriptions, HMAC signing, Google Workspace SSO, member roles/invites | 1.5 | Sep 1 |
| **M8: Frontier prep (VPC, SAML, audit log)** | Terraform module, SAML wiring, audit log table, data residency flag, SOC 2 prep | 2 | Sep 22 |

**Nov 1 real-users target:** M1–M5 shipped end of July → private beta with 10 advisor-sourced labs in August → public launch with M6+M7 in September → Frontier pilot conversations with Bryan Bryson's network by Nov 1.

---

## 12. Tech Stack Summary

| Layer | Choice | Rejected | Why |
|---|---|---|---|
| Frontend framework | Next.js 16 | Remix, SvelteKit | Already scaffolded; RSC maturity |
| UI kit | shadcn/ui + Tailwind | MUI, Chakra | Copy-paste, no lock-in |
| 3D viewer | Mol* | NGL, 3Dmol.js | Maintained, handles large complexes |
| API transport (web) | tRPC | GraphQL | Zero codegen, type-safe, one team |
| API transport (public) | REST via `trpc-to-openapi` | GraphQL | Scientists expect REST + Python client |
| API runtime | Fastify on Node 20 | Hono, Express, Python FastAPI | Fast, typed, same runtime as frontend |
| ORM | Prisma | Drizzle, Kysely | Schema-first, migrations mature |
| Database | Postgres (Supabase) | PlanetScale, Neon | RLS + Auth bundled |
| Auth | Supabase Auth | Clerk, Auth.js | Already paid for |
| Queue | BullMQ on Upstash | pg_boss, Temporal, SQS | Redis already in stack |
| Object storage | Cloudflare R2 | S3, Supabase Storage | Zero egress |
| Small files | Supabase Storage | — | Unified auth |
| Hosting (web) | Vercel | Netlify, Cloudflare Pages | RSC support, already there |
| Hosting (API) | Fly.io | Railway, Render | Long-lived conns, regions |
| GPU backend | Modal first, Vast.ai second | RunPod, Lambda | Already validated |
| Logs | Better Stack | Axiom, Datadog | Cost at our volume |
| Errors | Sentry | Rollbar | Ubiquitous |
| Analytics | PostHog | Mixpanel, Amplitude | Self-host path |
| Secrets | Infisical | Doppler, AWS SM | OSS, cheap |
| IaC | Terraform | Pulumi | Operator familiarity |
| CI | GitHub Actions | CircleCI | Free for OSS, integrated |

---

## 13. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Two-person team can't run a distributed system | High | Modular monolith, one runtime (Node), managed services everywhere (Supabase, Upstash, R2). No k8s until Frontier VPC forces it. |
| Long-running jobs break on serverless cold starts | High | API on Fly (not Vercel Functions), worker is a real process with BullMQ, not cron |
| Free tier abuse burns GPU budget | High | Free tier is BYOC only — we never front GPU on free. Hard seed quotas on Pro. |
| Supabase vendor lock-in | Medium | Prisma abstracts DB, Auth callable behind our own `/v1/auth/*`. Migration to self-hosted Postgres + Ory is a 2-week project if ever needed. |
| R2 becomes a bottleneck for 100 GB results | Medium | Streaming multipart uploads, parquet for metrics (not JSON), presigned multi-range downloads, CDN-cache artifacts for benchmark page |
| SSE/websocket scale issues | Low | Redis pubsub handles 10K concurrent subs per node; Fly auto-scales; fallback to 5-second poll if EventSource fails |
| Frontier VPC deploy blocks a deal | High | M8 ships Terraform module; first Frontier deal is white-glove (we deploy) to buy time for self-serve |
| Data corruption / lost jobs | Medium | Daily pg_dump to R2 (7-day retention), Supabase PITR, BullMQ `removeOnComplete: false` for 24h audit window, all artifact writes are idempotent keyed by `(job_id, seed)` |
| Harsha school-year velocity collapse | High | Summer sprint front-loads M1–M6 (real users before school restarts Aug). M7–M8 are smaller, async-friendly. Vedant owns deploys during school weeks. |
| Security incident (leaked API key, upload exploit) | High | Argon2id key hashes, sandboxed parser, Cloudflare WAF, Sentry alerting, quarterly rotation reminder, bug bounty page on `/security` before launch |

---

## Key File Paths (for reference)

- **Landing page source:** `/Users/harsha/Desktop/claudeprojects/mosaic/papercrane/`
- **Target monorepo structure** at `/Users/harsha/Desktop/claudeprojects/mosaic/papercrane/apps/`:
  - `apps/web` — the Next.js app (move current `papercrane/` here)
  - `apps/api` — Fastify + tRPC core API
  - `apps/worker` — BullMQ orchestrator
  - `packages/db` — Prisma schema + client
  - `packages/trpc` — shared routers
  - `packages/types` — shared zod + TypeScript types
- **pnpm workspace + Turborepo** at the mosaic/papercrane root once M1 begins.

---

**Decision summary in one paragraph:** Modular Node monolith (Fastify + tRPC) with a separate BullMQ worker, Postgres (Supabase) with RLS for multi-tenancy, R2 for artifacts, Fly.io for long-lived services, Vercel for the Next.js frontend with Mol* viewer. Ship M1–M6 by end of summer to hit Nov 1 real-user goal; M7–M8 mature the platform into Pro/Frontier-readiness before YC interviews.
