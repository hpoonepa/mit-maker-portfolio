# @papercrane/api

Fastify + tRPC core API for Paper Crane. Mounts REST endpoints under `/v1/*`,
the tRPC router at `/trpc`, SSE job streams, and the Swagger UI / OpenAPI
spec. Wires Supabase JWT + API-key auth, Redis-backed rate limits,
RLS-scoped Prisma calls, and Sentry error capture.

## Scripts

| Script          | What it does                                      |
|-----------------|---------------------------------------------------|
| `pnpm dev`      | `tsx watch src/server.ts` (local Fastify w/ HMR)  |
| `pnpm build`    | `tsc -b` — produces `dist/`                       |
| `pnpm start`    | `node dist/server.js`                             |
| `pnpm test`     | `vitest run` — unit + Fastify integration tests   |
| `pnpm typecheck`| `tsc --noEmit`                                    |

## Environment

Loaded via `src/config.ts`. Required in production:

- `DATABASE_URL` — Postgres connection string
- `REDIS_URL` — Upstash Redis (rate limits + SSE pubsub)
- `SUPABASE_PROJECT_REF` — for JWT verification
- `SENTRY_DSN` — error reporting

Optional / defaulted: `PORT` (3001), `NODE_ENV`, `LOG_LEVEL`, `CORS_ORIGIN`,
`APP_URL`, `API_KEY_PEPPER`, `SUPABASE_JWT_AUDIENCE`,
`SENTRY_TRACES_SAMPLE_RATE`.

Local dev can omit the prod-required vars; `buildServer` no-ops external
integrations (rate limits become a warn-log, JWT auth is rejected with a
clear error, Sentry stays dormant).

## Request pipeline

```
  incoming
     │
     ▼
  sensible + cors + sse + openapi      (plugins)
     │
     ▼
  public route? ─── yes ──▶ handler
     │ no
     ▼
  auth preHandler                      (Bearer pc_... | Supabase JWT)
     │
     ▼
  rateLimit preHandler                 (Redis token bucket, 60/600/∞ per tier)
     │
     ▼
  route handler                        (REST or tRPC; wraps Prisma in withRlsUser)
     │
     ▼
  errorHandler                         (Zod/Auth/Forbidden/500 mapping)
```

## tRPC mount

The router lives in `@papercrane/trpc` and is dynamically imported at boot.
If the package exports nothing yet (Wave 2 still in flight), the API logs an
info line and serves REST only. No code changes are needed in this app once
the router is published.

## Public routes

Opt out of auth + rate limit by marking a route with
`config: { public: true, rateLimit: false }`. Only `/healthz`, `/openapi.json`,
and `/docs/*` should need this.

## Decisions

- **Error handler is a function, not a plugin.** Registered via
  `app.setErrorHandler(errorHandler)` so it applies to the root app and
  nested plugins without encapsulation surprises.
- **Rate limit open-fails.** A Redis blip yields `allowed: true` rather than
  cascading 503s across every endpoint. We alert on Redis health separately.
- **`withRlsUser` wraps every tenant query.** The service role bypasses RLS
  at the DB level, so we re-enforce tenant isolation per request via
  `SET LOCAL app.current_user`. API-key principals fall back to the orgId as
  the RLS identity (policies that key on `auth.uid()` will correctly return
  no rows for those callers — which is the intended behavior until API-key
  -> user mapping lands).
- **tRPC mount is lazy.** Missing router at boot is a warning, not an error.
