# Paper Crane — Master Technical Plan

**Version:** 1.0
**Date:** 2026-04-23
**Founders:** Harsha Poonepalle, Vedant Kalipatnapu
**Status:** YC S26 applicant, MVP sprint, real users target Nov 1 2026

---

## Executive Summary

Paper Crane is the unified platform for protein binder design — "Hugging Face for protein design." This master plan integrates five sub-plans (Core Platform, Tool Integration, Compute Infrastructure, Benchmark Engine, Billing) into one executable roadmap.

**Target outcomes:**
- Live product with 20+ paying lab users by Nov 1 2026
- Continuously updated public benchmark as a bioRxiv preprint (MIT EA artifact + YC traction signal)
- YC S26 Demo Day shipping
- $1M ARR path within 12 months of GA — ~280 Pro orgs OR 2–3 Frontier deals OR mix

**Critical architecture decisions (locked):**
- Modular Node monolith (Fastify + tRPC) + separate BullMQ worker. Not microservices. Not k8s.
- Next.js 16 + Mol* on Vercel for frontend
- Postgres on Supabase (RLS multi-tenancy) + Redis on Upstash + R2 on Cloudflare ($0 egress)
- Modal primary GPU + Vast.ai spot batch + RunPod fallback
- Stripe for Pro subscriptions, raw Stripe Invoices for Frontier
- Benchmark engine is the moat — neutral arbiter, external submissions, GPG-signed methodology

---

## Consolidated Build Calendar

Harsha part-time school (Apr 23 – May 23, Aug 5+) + full-time summer (May 24 – Aug 4). Vedant similar. Weeks normalized across all 5 sub-plans:

| Wk | Core Platform | Tool Integration | Compute Infra | Benchmark | Billing |
|----|---|---|---|---|---|
| **W1** (May 18) | Auth + dashboard shell | SDK scaffold + GHCR + base images | Modal-only adapter, warm pool | Port 540 runs into Postgres `/leaderboard` | Stripe Checkout + webhook |
| **W2** (May 25) | First job E2E w/ SSE | BindCraft wrapped end-to-end | Cost ledger, Postgres counters | Run manifests + IPFS pinning | Metering API w/ idempotency |
| **W3** (Jun 1) | Targets + projects + R2 | Validator image (ipSAE/DockQ/pTMEnergy) | BYOC free tier + KMS envelope | Nightly cron → Vast.ai smoke tier | Customer Portal + dunning |
| **W4** (Jun 8) | Public REST API + keys | +MPNN, RFdiffusion, Boltz-2 | Vast.ai spot fallback + router scoring | Drift detection + Slack alerts | Top-up packs UX |
| **W5** (Jun 15) | Seed accounting + quotas | +Chai-1, BoltzGen, Ligand/Soluble MPNN, ESM2, Boltz-1, Chroma (11 total) | Pro budget enforce + monitoring | Submission repo + dry-run CI | Multi-seat + org admin |
| **W6** (Jun 22) | Result browser + filters | Remote adapter + AF3 tier-gated (12 tools) | Grafana dashboards + PagerDuty | Preprint + Zenodo release pipeline | A/B setup for pricing |
| **W7** (Jun 29) | Webhooks + Google SSO | Reproducibility audit + scaffold CLI OSS | Frontier dedicated Modal workspace | Target expansion 3→5 (add TrkA, CXCR4) | Frontier Invoice + MSA template |
| **W8** (Jul 6) | Audit log + SAML (Frontier) | — | Terraform BYOC-enterprise module | Community target nomination | Overage metering |
| **W9** (Jul 13) | **Private beta — 10 labs onboarded** | — | VPC-deploy first pharma pilot (white-glove) | 5 external submissions accepted | — |
| **W10** (Jul 20) | Polish, feedback, bug bash | — | — | — | Pricing A/B running |

**Post-summer (school-week pace, ~15 hrs/week):**
- **Aug–Sep:** public launch, press outreach, MIT squash camp (Harsha), YC application materials
- **Oct:** Lincou pre-read, iGEM 2026 prep with Paper Crane integration, refine Frontier pipeline
- **Nov 1:** MIT EA submission with live platform + preprint + paying users

---

## Cross-Cutting Decisions

### What's one-runtime-only (Node/TS)
Backend API, orchestrator worker, frontend. Python lives only inside GPU worker containers (tool execution), never outside.

### What's managed (not self-hosted)
Supabase (Postgres + Auth), Upstash (Redis), Cloudflare (R2 + WAF + CDN), Vercel (web), Fly.io (API + worker), Modal (GPU primary), Stripe (billing), Sentry (errors), Better Stack (logs), Infisical (secrets).

### What's the moat
The public benchmark. Not the tool wrapping. Not the UI. The benchmark is the neutral arbiter position that makes every new tool author want to submit — and every new researcher cite Paper Crane.

### What we DON'T build
Kubernetes, custom scheduler, in-house auth, self-hosted logging stack, microservices split. Two-person constraint.

---

## Unified Tech Stack

| Layer | Choice |
|---|---|
| Frontend framework | Next.js 16 (App Router, RSC-first) |
| UI kit | shadcn/ui + Tailwind |
| 3D viewer | Mol* |
| API transport (internal) | tRPC |
| API transport (public REST) | `trpc-to-openapi` generator |
| API runtime | Fastify on Node 20 |
| Job queue | BullMQ on Upstash Redis |
| ORM | Prisma |
| Database | Postgres on Supabase (with RLS) |
| Auth | Supabase Auth (SAML add-on for Frontier) |
| Object storage (large) | Cloudflare R2 |
| Object storage (small) | Supabase Storage |
| Secrets | Infisical |
| Hosting (web) | Vercel |
| Hosting (API + worker) | Fly.io (2 regions, iad+sfo) |
| GPU backend (primary) | Modal |
| GPU backend (cost-opt) | Vast.ai spot |
| GPU backend (fallback) | RunPod |
| GPU for Frontier VPC | Customer AWS/GCP via Terraform |
| Container registry | GHCR |
| Base Docker images | `papercrane/base-cuda12`, `papercrane/base-cpu` |
| Billing | Stripe (Subscriptions + Invoices) |
| Logs | Better Stack |
| Errors | Sentry |
| Analytics | PostHog |
| Uptime | Better Stack Uptime |
| Traces | Sentry Performance (OpenTelemetry) |
| IaC | Terraform |
| CI | GitHub Actions |
| Benchmark methodology versioning | Git-signed commits + Zenodo DOIs |
| Benchmark artifact pinning | IPFS + S3 (R2-backed) |

---

## Unified Data Model (canonical)

Primary tables (from Core Platform + Billing + Benchmark agents):

- `organizations` — tier, seeds_quota, seeds_used, retention_days
- `users`, `org_members` — identity + RBAC
- `projects` — grouping
- `targets` — user-uploaded PDBs + hotspots
- `jobs` — tool, version, params, state, gpu_backend, seeds_consumed, expires_at
- `designs` — per-seed outputs with metrics JSONB
- `api_keys` — argon2id hashed, scope array
- `usage_seeds` — ledger of debits/credits per org
- `seed_usage` (rolled up) — fast gate-check counter
- `subscriptions` — Stripe mirror
- `feature_flags` — per-org tier overrides (retention_days, max_concurrent, vpc_enabled, closed_weights_allowed)
- `tools` — catalog (seeded from `tools.manifest.json`)
- `benchmark_runs` — per-cell run manifests (target, tool_version, seed_range, results_digest, cost)
- `benchmark_submissions` — external tool author submissions

All tenant tables carry `org_id` and RLS-protected.

---

## Integrated Risk Register

| # | Risk | Impact | Source | Mitigation |
|---|---|---|---|---|
| R1 | Two-person team can't operate distributed system | High | Core | Modular monolith, managed services everywhere |
| R2 | Free tier abuse burns GPU | High | Core + Compute + Billing | BYOC-only for Free — we never front GPU on free |
| R3 | Modal outage takes down Pro | High | Compute | Router auto-drains to RunPod; SLA credit |
| R4 | Spot preemption on Vast.ai | Medium | Compute | Max 1 spot retry → on-demand, then refund seed |
| R5 | Upstream tool change breaks adapter | Medium | Tools | Adapters pinned to git SHA; CI smoke test each version |
| R6 | License drift on closed-weight tools | Medium | Tools | `tier` + `license` manifest fields; EULA gate; legal review |
| R7 | Benchmark accused of curation bias | High | Benchmark | External advisory panel, public comment, literature-sourced hotspots |
| R8 | Methodology dispute forks community | Medium | Benchmark | Methodology versioned — forks create new leaderboard, old frozen |
| R9 | Harsha school-year velocity collapse | High | Core + Schedule | Summer front-loads M1–M6; M7–M8 async-friendly; Vedant owns deploys during school |
| R10 | Security incident | High | Core | Argon2id keys, sandboxed parser, Cloudflare WAF, quarterly rotation |
| R11 | Seed unit economics collapse (GPU price shock) | High | Compute + Billing | Quarterly cost review; ToS allows 10% adjustment w/ 60-day notice; multi-cloud hedge |
| R12 | Frontier deal slippage (6–9 month cycles) | High | Billing | Don't count Frontier in MRR forecast; Pro must independently reach $1M path |
| R13 | Supabase vendor lock-in | Medium | Core | Prisma abstracts DB; migration to self-hosted is 2-week project if ever needed |
| R14 | Free-tier abuse sweep via alt accounts | Medium | Billing | GitHub OAuth, email throttles, IP signup throttles, abuse heuristics |
| R15 | Tenant data leak across orgs | Critical | Core | RLS at DB, org_id in every API handler, R2 prefix isolation, queue namespacing |

---

## Funding + Milestone Proof Points

Milestones that unlock specific outcomes:

| Milestone | Week | Proof | Unlocks |
|---|---|---|---|
| First internal E2E job | W2 | Video demo | YC application "it works" |
| Free-tier BYOC live | W3 | 5 friends-and-family signups | YC application traction |
| Leaderboard v1 live | W2 | Public URL | Press/Twitter moment, preprint intro |
| 5 tools integrated | W4 | Dashboard screenshot | YC interview demo |
| Private beta, 10 labs | W9 | Usage data + testimonials | YC interview "we have users" |
| First Frontier pilot (VPC) | W9–10 | Signed MSA | YC interview "$50K ARR already" |
| bioRxiv preprint | W8 | DOI | MIT EA individual-output anchor |
| Public launch | Aug | Product Hunt / Hacker News | Top-of-funnel traffic |
| YC Demo Day | Nov | Live product + $X ARR | Next round fundraise |
| MIT EA submission | Nov 1 | Common App + preprint + recruit | Admit |

---

## Immediate Next Actions (this week — Apr 23 to 30)

1. **Fix resume placeholders** (1 hour) — `________`, `[Add bullet points later]`, `Where do you run?`, `How often?`. Critical: any reader (Lincou, Bryson, prof, journalist) seeing these right now hurts.
2. **Reserve papercrane.bio** if not already done; Paper Crane currently on `papercrane-h2im.vercel.app`.
3. **Pin advisor names on landing page** — Bryson (MIT), UCLA, UPenn, Metzker. Free credibility. Ask permission first.
4. **Set up pnpm workspace + Turborepo** at `mosaic/papercrane/` with `apps/web`, `apps/api`, `apps/worker`, `packages/db`, `packages/trpc`, `packages/types`. Move existing landing to `apps/web/`.
5. **Stand up Supabase project + Fly org** — two environments (staging + prod). Provision Upstash Redis.
6. **Cut first issue list in GitHub Projects** — one per milestone from consolidated calendar above.
7. **Ask Bryson for LOR ask + early-user intro** for private beta (W9 target of 10 labs).

---

## Sub-Plan Index

Full details for each domain:

1. `01-core-platform.md` — Architecture, API, data model, auth, orchestration, deployment, observability, security
2. `02-tool-integration.md` — ToolAdapter SDK, Docker strategy, 12-tool catalog, playbook for adding tool #13
3. `03-compute-infrastructure.md` — Multi-provider router, BYOC, managed pool, Frontier VPC, unit economics, sequence diagram
4. `04-benchmark-engine.md` — Methodology versioning, reproducibility, continuous runs, external submissions, target expansion 3→10
5. `05-billing-pricing.md` — Stripe architecture, tier enforcement, top-up flow, multi-seat, Frontier invoicing, unit economics

---

## Decision Log (capture as you go)

| Date | Decision | Rationale | Revisit |
|---|---|---|---|
| 2026-04-23 | Modular Node monolith | 2-person team constraint | At 5 engineers |
| 2026-04-23 | Modal primary GPU | Already in user toolkit, Python-native | At 100 orgs or provider outage |
| 2026-04-23 | R2 over S3 | Zero egress fees on 100 GB results | Never (keep) |
| 2026-04-23 | BYOC-only Free tier | Cannot subsidize free GPU | Revisit post-$1M ARR |
| 2026-04-23 | tRPC internal + REST public | Type safety + scientist expectations | Never (keep) |
| 2026-04-23 | Benchmark as the moat | Neutral arbiter positioning | Never (keep) |

Keep this table updated as decisions accumulate.
