# @papercrane/trpc

Shared tRPC surface for the Paper Crane platform. The Next.js dashboard
consumes this directly; `apps/api` wraps the same router tree with
[`trpc-to-openapi`](https://github.com/jlalmes/trpc-openapi) to emit the
versioned REST surface documented in `docs/plans/01-core-platform.md` §2.

## Surface

```
appRouter
├── health      // public: ping
├── projects    // protected CRUD
├── targets     // protected create (presigned PUT), get, list
├── jobs        // protected submit/get/list/cancel — tier-gated
├── designs     // protected listByJob, get (returns presigned GET URL)
├── usage       // protected current, history
├── tools       // PUBLIC list/get — tool catalogue
├── webhooks    // protected CRUD
└── keys        // protected list, create (full key ONCE), revoke
```

## Context

Procedures receive an `InnerContext` with:

- `auth` — resolved principal (user or API key) or `null`
- `prisma`, `withRlsUser` — every DB call runs inside an RLS transaction
  so Postgres enforces tenant isolation
- `enqueueJob`, `publishCancel` — queue + pubsub primitives, injected
- `presignGet` — R2 presigning, injected
- `tools` — the public tool catalogue, injected at adapter startup
- `now` — clock, overridable in tests

The Fastify adapter in `apps/api` implements `createContext({ req, res, auth })`
and passes the real prisma / BullMQ / R2 deps. Tests build an inner context
directly via `createInnerContext({ ... })` with mocks.

## Middleware

- `requireAuth` — any authenticated principal
- `requireScope(scope)` — API-key scope check; user sessions pass through
- `requireTier(min)` — enforces plan tier (free < pro < frontier)
- `rateLimit({ procedure, limit, windowSec, limiter })` — per-procedure
  Redis-backed limiter. Noop when `limiter` is omitted.

## Tier → tool allowlist

`src/config/tierTools.ts` defines which `toolId`s each tier may submit.
Free and Pro share the open-weights catalogue; Frontier additionally
unlocks closed-weights tools such as AlphaFold 3. `jobs.submit` enforces
this allowlist before any DB work.

## Running tests

```bash
pnpm --filter @papercrane/trpc test
```

The test suites (`tests/*.test.ts`) use inline mocks — no Postgres, R2, or
Redis required.
