# Paper Crane — Beta Launch Checklist

Updated 2026-04-30 after Wave A–E readiness pass. Honest snapshot of what
ships, what is stubbed, and what blocks a public flip.

> **Verdict:** **BETA-READY for invite-only.** Public launch gated on five
> PENDING items below (real GPU dispatch validation, prod R2, Stripe webhook
> live test, public-share schema/proc, rate-limit telemetry proc).

---

## READY — Marketing site (`apps/web`)

- [x] `/` — landing with hero, demo, pricing, footer.
- [x] `/benchmark` — leaderboard (23 models) + Pareto scatter.
- [x] `/benchmark/methodology` — dataset, metrics, scoring, reproducibility notes.
- [x] `/docs/getting-started` — 10-minute first-design walkthrough.
- [x] `/docs/api` — REST + tRPC reference, auth headers, error codes.
- [x] `/docs/cli` — `papercrane` command reference, install, auth, examples.
- [x] `/faq` — 24 questions across pricing, BYOK, compute, data handling.
- [x] `/beta` — invite-code request form + what-to-expect copy.
- [x] `/blog/launching-paper-crane` — public launch post (long-form).
- [x] `/status` — live service health (web/app/api/worker), incident list.
- [x] `/p/[publicId]` — live, revocable public computational project report.
- [x] `/terms`, `/privacy`, cookie banner, sitemap, robots, OG images.

## READY — Product app (`apps/app`)

- [x] `/app/designs` — list (filters, sort, pagination) + `/app/designs/[id]`
  detail with Mol\* viewer, metrics, downloads.
- [x] `/app/jobs` — list with realtime status + `/app/jobs/[id]` detail
  (logs tail, artifacts, cancel).
- [x] `/app/tools` — 12-tool catalog (Boltz-2, Chai-1, AF-Multimer, RFDiffusion,
  BindCraft, BoltzGen, ProteinMPNN, SolubleMPNN, LigandMPNN, ESM2, Foldseek, ipSAE).
- [x] `/app/compare` — side-by-side design comparison (up to 4) on metrics + structures.
- [x] `/app/exports` — JSONL/CSV/FASTA/PDB bundle export with signed URL.
- [x] `/app/settings/keys` — Argon2id-hashed API keys, plaintext-once, rotate/revoke + 24h grace.
- [x] `/app/settings/audit` — org-scoped audit log, JSONL export.
- [x] `/app/settings/members` — invite/role/leave with last-owner guard.
- [x] `/app/settings/webhooks` — outbound webhooks, HMAC-signed, delivery log + retry.
- [x] `/app/settings/cli` — token mint + install instructions.
- [x] `/app/settings/rate-limits` — **stub UI**; renders current tier limits
  but live telemetry proc not wired (see PENDING).
- [x] Onboarding, projects, targets, notifications, integrations, billing,
  feedback widget — all carried over from Wave 14.

## READY — Backend (`apps/api`, `packages/*`)

- [x] **Auth** — Supabase email + magic link + Google + GitHub OAuth, password reset.
- [x] **tRPC** — 16+ routers with `withRlsUser`; org-scoped RLS on every tenant table.
- [x] **BYOK Modal** — per-org Modal token storage (encrypted), dispatch path
  in `apps/worker/src/dispatch.ts`. Synth processor still default in dev.
- [x] **Dev-stub upload** — local FS adapter at `packages/storage/src/dev.ts`
  for PDB/JSON uploads when R2 creds absent.
- [x] **Schema** — Prisma schema with **22+ migrations** (org/member/project/
  target/job/design/api_key/webhook/audit/invite/feedback/notification/version/
  integration/rate_tier/exports + RLS migrations).
- [x] **Billing** — Stripe checkout + portal + signature-verified webhooks (test mode).
- [x] **Email** — Resend gated, console fallback when key absent.
- [x] **Realtime** — Supabase channel + worker tap for job status + notifications.
- [x] **Observability** — Pino + Sentry (DSN-gated) + PostHog + request-id propagation.
- [x] **Security** — strict CSP, CORS allowlist, rate limits (anon 5/min, authed tiers).

## READY — Infra & DX

- [x] **`pnpm dev`** — orchestrates web (3000), api (3001), app (3002),
  docs (3004), worker via turbo.
- [x] **`pnpm dev:check`** — preflight: env vars, DB reachable, Supabase up,
  Stripe keys present (stub OK), ports free.
- [x] **`pnpm dev:reset`** — drops local DB, re-runs migrations, re-seeds
  invite codes + sample projects.
- [x] **`scripts/smoke-e2e.sh`** — Playwright walk: signup → invite-code →
  create project → submit job → see design → export.
- [x] **`scripts/deploy-all.sh --dry-run`** — preview prod deploy plan.
- [x] CI: lint + typecheck + unit + Playwright smoke on PR.

---

## PENDING — must close before public flip

- [ ] **Real GPU dispatch validation** — BYOK Modal path is wired but has not
  been end-to-end validated against a real Modal token + GPU run. Synth
  processor still answers in dev. Owner: founder + 1 SRE day.
- [ ] **R2 storage in prod** — dev-stub upload works; prod R2 bucket, lifecycle
  rules, signed-URL TTL, and CORS not provisioned.
- [ ] **Stripe webhook end-to-end test** — webhook signature verifier passes
  in tests; full subscription lifecycle (trial → paid → past_due → canceled)
  not yet rehearsed against live test-mode events.
- [x] **Public project reports** — revocable `Project.isPublic` + opaque
  `publicId`, authenticated publish/unpublish mutation, rate-limited public
  read path, field-allowlisted SECURITY DEFINER query, and live
  `/p/[publicId]` report. Raw sequences, structures, job internals, and member
  data remain private.
- [ ] **Rate-limits telemetry proc** — `/app/settings/rate-limits` UI is
  stubbed to static tier values. Needs `usage.getRateLimitWindow` proc
  reading from Redis sliding-window counters.
- [ ] **Third-party SOC 2 audit** — Type I window opened with auditor,
  evidence collection in progress; not blocking beta but blocks enterprise.

## Out of scope (post-beta)

- GitHub connector.
- iGEM-grade reproducibility bundle export (ZIP-of-everything).
- Self-serve org provisioning beyond invite-code flow.

---

## Pre-launch operational checks

1. `pnpm dev:check` clean.
2. `pnpm dev` — all five services green.
3. `bash scripts/smoke-e2e.sh` — full Playwright walk.
4. `pnpm --filter @papercrane/api typecheck && pnpm --filter @papercrane/app typecheck`.
5. Seed invite codes — `bun .agent-logs/seed-invite-codes.ts`.
6. Verify Stripe test webhooks against `stripe listen` CLI.
7. Smoke email — `pnpm --filter @papercrane/email run send-test`.
8. After admission migrations and invites are verified, set `NEXT_PUBLIC_BETA_GATE=true`
   in both the app and API environments and rebuild the app. The callback, UI and
   authenticated API routes share the parser; `on/off` and `1/0` are accepted aliases.
   Verify an admitted user can enter and an unadmitted user is denied on direct API calls.

## Day-one watch items

- Sentry events tagged `release:beta-1` — investigate any 5xx within 5 min.
- Realtime fallback when Redis is down — worker logs `redis:false`.
- Synth-vs-real dispatch parity — any drift logs to `worker:dispatch:mismatch`.
