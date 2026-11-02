# Paper Crane — Changelog

Wave-by-wave summary of the 14-day MVP build (2026-04-13 → 2026-04-27).
Each wave was ~10 parallel sub-agents working on non-overlapping files.

---

## Public research reports (2026-07-21)

- Replaced the always-404 `/p/[publicId]` stub with a polished, read-only
  computational campaign report for external collaborators.
- Added revocable project publishing with stable, high-entropy public ids and
  an authenticated sharing control on project pages.
- Kept RLS intact and routed anonymous reads through a field-allowlisted
  SECURITY DEFINER function; raw sequences, structures, artifacts, job
  parameters/logs, and member data are never returned.
- Added campaign summaries and target-aware experimental meta-scores for the
  five strongest public candidates, with explicit evidence limitations.

---

## Experimental LLM meta-scorer (2026-07-11)

- Added a deterministic, versioned per-target prior score to design API reads.
- Added target-prior coverage, metric contributions, liabilities, citations,
  and explicit underpowered-evaluation caveats to design detail.
- Added an optional experimental meta-score sort to the design gallery without
  changing canonical job rank.
- Preserved owned target/project identity on new jobs so target-conditioned
  scoring does not rely on display-name guesses.
- Documented the corrected benchmark MDE and the 5G51 identity discrepancy in
  `docs/LLM-META-SCORER.md`.

---

## Wave 1 — Foundation
Monorepo scaffold (turbo + pnpm), TS configs, lint preset, base packages
(`types`, `db`, `auth`, `trpc`, `billing`, `storage`, `jobs`, `observability`,
`brand`, `tools-sdk`, `ui`). Prisma schema with org/member/project/target/
job/design/api_key/webhook models. RLS migration for every tenant table.

## Wave 2-7 — Core packages + tests
Auth (Supabase + argon2), tRPC routers (15+ routers), Modal worker
integration, billing (Stripe checkout/portal/webhooks/tiers), API keys +
webhook signing, R2 storage with signed URLs.

## Wave 8 — End-to-end Playwright
First green path: signup → submit job → see design.

## Wave 9 — Quality gate
Lint + typecheck for all packages. 100+ errors fixed across 14 packages.

## Wave 10 — Observability
Pino + Sentry + PostHog wiring, request-id propagation, BetterStack shipping.

## Wave 11 — Hotspot + dashboard chrome
PDB hotspot picker (residue selection on Mol* canvas), dashboard layout, Cmd+K palette.

## Wave 12 — Onboarding
Multi-step onboarding (welcome → create-org → first-target → first-job →
invite-team → done), connect-modal for Slack/Discord.

## Wave 13 — Deploy + tools-contract + first-run polish
Vercel + Fly + GitHub Actions deploy pipelines. Tool conformance harness.
Welcome modal, sample projects (GPCR 6X1A, Antibody 1IGT, Enzyme 1CRN),
manual coachmarks.

## Wave 14 — Hardening + final smoke + handoff
Stripe checkout/portal end-to-end (76), public `/benchmark` leaderboard with
23 models + Pareto scatter (77), `@papercrane/email` package + 5 transactional
templates (78), Slack + Discord webhook integrations w/ RLS-gated schema (81),
hero polish: Mol* 6X1A spinner + animated SVG fallback (82), `papercrane` CLI
binary with commander + Homebrew tap (83), project versioning + immutable
ProjectVersion history (84), full E2E smoke walking 15 user-journey steps
(85), comprehensive engineering handoff doc + changelog + final verdict.

---

## Wave A–E (2026-04-30) — beta-launch readiness

Three-day post-handoff sprint to close the gap between "BETA-READY for invite"
and "shippable to first public users." Five parallel waves, ~30 sub-agents.

- **Wave A — Marketing depth.** Added `/benchmark/methodology`,
  `/docs/getting-started`, `/docs/api`, `/docs/cli`, `/faq`, `/beta`,
  `/blog/launching-paper-crane`, `/status`, and a stub `/p/[publicId]`
  public-design page (schema/proc deferred — see checklist PENDING).
- **Wave B — Product app surface.** New `/app/compare` (up to 4 designs side
  by side), `/app/exports` (JSONL/CSV/FASTA/PDB bundle), settings depth
  (`/keys`, `/audit`, `/members`, `/webhooks`, `/cli`, `/rate-limits` stub).
- **Wave C — Backend hardening.** BYOK Modal dispatch path wired (validation
  pending against real token), dev-stub storage adapter for local PDB/JSON,
  Prisma schema grew to 22+ migrations covering audit/invite/feedback/
  notification/version/integration/rate-tier/exports tables.
- **Wave D — Infra & DX.** `pnpm dev:check` preflight, `pnpm dev:reset`
  one-shot local re-seed, `scripts/smoke-e2e.sh` Playwright walk covering
  the full signup → export journey.
- **Wave E — Honesty pass.** Beta-launch checklist rewritten to separate
  READY / PENDING / out-of-scope. Five PENDING items called out as public-flip
  blockers: real GPU dispatch validation, prod R2, Stripe webhook live test,
  public-share schema, rate-limit telemetry proc.

No new dependencies added. No metrics or testimonials fabricated.

---

## Final stats (as of 2026-04-27)

| Metric                           | Count       |
|----------------------------------|-------------|
| TS / TSX / JS / MJS source files | 685         |
| Test files (`.test.ts` + `.spec.ts`) | 104     |
| Pages (Next App Router)          | 60 (51 app + 9 web) |
| Tool adapters / manifests        | 12          |
| Packages (`packages/*`)          | 14          |
| Apps (`apps/*`)                  | 5           |
| Agent waves                      | 14          |
| Sub-agents dispatched (approx)   | 140         |
| Days, idea → handoff             | 14          |
