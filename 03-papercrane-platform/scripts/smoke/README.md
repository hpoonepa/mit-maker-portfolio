# `@papercrane/smoke`

End-to-end smoke test for Paper Crane's web app. Boots `apps/web` in dev mode,
probes the critical routes, asserts they render, writes junit-xml, and
tears the server down cleanly.

Exists as a CI gate so regressions like the `/leaderboard` and `/login` 500s
don't ship silently again.

## Why it lives outside the pnpm workspace

Same rationale as `scripts/benchmark/`: this package is only ever consumed by
GitHub Actions. Keeping it out of the workspace root means CI can `pnpm install`
inside `scripts/smoke/` without pulling the entire monorepo graph and without
polluting `apps/web` with smoke-only dependencies.

## Layout

```
scripts/smoke/
  package.json        # @papercrane/smoke — standalone, Node 20+
  tsconfig.json
  vitest.config.ts
  src/
    index.ts          # CLI entrypoint
    runner.ts         # spawns pnpm --filter @papercrane/web dev, probes, junit
    probe.ts          # fetch helper: retries + timeout + assertions
    routes.ts         # table of routes + expected statuses (the source of truth)
  tests/
    routes.test.ts    # vitest: table is well-formed + regressions covered
    probe.test.ts     # vitest: probe helper retries + assertion behaviour
  results.xml         # produced at run time; uploaded by CI
```

## Running locally

```bash
cd scripts/smoke
pnpm install
pnpm smoke                 # defaults: port 3002, junit at scripts/smoke/results.xml
SMOKE_PORT=3010 pnpm smoke # override port
pnpm smoke -- --skip-spawn # probe an already-running dev server on SMOKE_PORT
pnpm test                  # run unit tests for routes + probe
```

Exit code is `0` when every route passes, `1` otherwise (including spawn or
readiness failures).

## Routes

The authoritative list lives in `src/routes.ts`. At the time of writing:

| Route                         | Accepts      | Notes                                                              |
| ----------------------------- | ------------ | ------------------------------------------------------------------ |
| `GET /`                       | 200 + "Paper Crane" in body | Must always render the brand.                       |
| `GET /leaderboard`            | 200 or 500   | 500 tolerated only while tRPC has no empty-state fallback wired.   |
| `GET /.well-known/security.txt` | 200 + text/plain | RFC 9116 contact doc.                                          |
| `GET /login`                  | 200          | Must fall back to a "Supabase not configured" page when env is absent. A 500 is a regression. |
| `GET /logout`                 | 302/303/307/405 | POST-only; a GET should redirect or 405.                        |

## Flaky / degrades-gracefully routes

- **`/leaderboard`** — permitted to return 500 while the page throws when
  the tRPC `leaderboard.list` query fails (Supabase env missing in CI).
  Tighten to `statuses: [200]` once the route is wrapped in an error boundary
  that renders an empty leaderboard. Documented in `routes.ts` notes.
- **`/login`** — intentionally required to render 200 even without
  `NEXT_PUBLIC_SUPABASE_URL`. The expectation is that the page renders a
  "Supabase not configured" fallback. If this probe fails, either the env
  regressed or the fallback branch was removed — either way, it's a real bug.
- **`/logout`** — the GET method is not supported in production, so the probe
  accepts any of `302/303/307/405`. Only tighten if we settle on one shape.

## Runner behaviour

- Spawns `pnpm --filter @papercrane/web dev --port $SMOKE_PORT` from the
  monorepo root, inheriting the environment plus `NEXT_TELEMETRY_DISABLED=1`
  and `CI=1`.
- Polls `GET /` until any HTTP status comes back, or 90 s elapses.
- Probes every route **in parallel** once the server is ready.
- Each probe: up to 3 retries with exponential backoff (250 ms base),
  10 s per-attempt timeout. Assertion failures short-circuit (no point retrying
  a clean 404).
- On completion (pass or fail), sends `SIGTERM` to the dev server, waits 5 s,
  then escalates to `SIGKILL`.
- Writes `scripts/smoke/results.xml` (junit-xml) regardless of pass/fail.

## CI

See `.github/workflows/smoke.yml`. The workflow runs on every PR that touches
`apps/web/**` or `packages/**`, installs deps inside `scripts/smoke/`, runs
`pnpm smoke`, and uploads `results.xml` as an artifact.
