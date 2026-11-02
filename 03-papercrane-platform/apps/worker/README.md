# @papercrane/worker

The Paper Crane orchestrator worker. Claims jobs from per-tier BullMQ queues
(`jobs:free`, `jobs:pro`, `jobs:frontier`), dispatches them to GPU adapter
providers (Modal in production, Vast.ai / RunPod later), streams per-seed results
as `JobEvent`s on Redis pubsub, and enforces the state machine defined in
`docs/plans/01-core-platform.md` §5.

## Layout

| File | Purpose |
|---|---|
| `src/server.ts` | Process entrypoint: load config, wire context, bootstrap workers, handle SIGTERM. |
| `src/index.ts` | `bootstrapWorkers(ctx, config)` — one BullMQ `Worker` per tier + retention cron. |
| `src/config.ts` | Env-driven `WorkerConfig` (Redis, DB, per-tier concurrency, provider tokens). |
| `src/context.ts` | `WorkerContext` singleton passed into every handler. |
| `src/jobProcessor.ts` | Main per-job handler: claim → preparing → spawn → stream seeds → complete/fail. |
| `src/transitions.ts` | DB-aware wrapper around `transition()` with audit log in a single tx. |
| `src/events.ts` | `RedisEventPublisher` — publishes validated `JobEvent`s to `job:<id>`. |
| `src/cancellation.ts` | `pc:cancel:*` psub listener + in-memory `CancellationManager`. |
| `src/retention.ts` | Repeatable BullMQ job — marks expired succeeded/failed jobs as `purged`. |
| `src/retryQueue.ts` | Computes backoff and requeues infra-error jobs with bumped attempt. |
| `src/providers/` | Provider interface + deployed Modal Function provider; fake stream only for credential-free development. |

## Design notes

- **Per-tier workers.** `WORKER_CONCURRENCY_FREE=5`, `_PRO=20`, `_FRONTIER=50`.
  A Frontier 50K-seed job can't starve Pro; each tier has its own `Worker`.
- **Modal provider.** `providers/modal.ts` looks up deployed Functions with the
  official Modal Python SDK and parses their NDJSON events. Multi-seed jobs use
  bounded fan-out (two GPU or four CPU calls by default). A missing app is
  deployed once on first use when `PAPERCRANE_MODAL_AUTO_DEPLOY` is enabled;
  later jobs reuse the named deployment. If credentials are absent, local
  development uses a fake seed stream; production fails closed.
- **Cancellation.** Cooperative, per plan 01 §5. The API publishes
  `pc:cancel:<jobId>`; a dedicated subscriber flips an in-memory flag; the
  processor checks between seeds, flushes completed work, and transitions
  through `cancelling → cancelled`.
- **Retries.** Only on infra error codes (`GPU_PREEMPT`, `NETWORK_TIMEOUT`, …),
  never on user errors. Backoff comes from `@papercrane/jobs`. Retries derive
  completed seeds from persisted designs, request only missing seeds, and use
  `createMany(..., skipDuplicates)` so a replay cannot double-bill usage.
- **Stuck recovery.** Active attempts heartbeat into Postgres. A periodic
  sweeper conditionally fences expired attempts, records `WORKER_STALLED`, and
  requeues on the original tier without allowing the stale worker to persist.
- **Graceful shutdown.** SIGTERM drains in-flight jobs up to
  `SHUTDOWN_TIMEOUT_SECONDS` (default 30s), then force-exits.

## Env

| Var | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | BullMQ + pubsub + cancel channel |
| `DATABASE_URL` | local Postgres | Prisma connection |
| `WORKER_CONCURRENCY_FREE` | 5 | Free-tier worker concurrency |
| `WORKER_CONCURRENCY_PRO` | 20 | Pro-tier worker concurrency |
| `WORKER_CONCURRENCY_FRONTIER` | 50 | Frontier-tier worker concurrency |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | — | Modal provider creds (stub warns if missing) |
| `MODAL_CREDENTIAL_ENCRYPTION_KEY` | — | 32-byte base64/hex key for decrypting linked organization Modal credentials |
| `MODAL_WORKSPACE` | configured profile | Modal workspace slug |
| `MODAL_SEED_PARALLELISM` | 2 GPU / 4 CPU | Per-job seed fan-out; clamped to 1–8 |
| `PAPERCRANE_MODAL_AUTO_DEPLOY` | `1` | Deploy a missing tool app once in the linked workspace |
| `VASTAI_API_KEY` | — | Reserved; provider not implemented |
| `RUNPOD_API_KEY` | — | Reserved; provider not implemented |
| `LOG_LEVEL` | `info` | pino level |
| `RETENTION_INTERVAL_SECONDS` | 86400 | Cron cadence for expired-job purge |
| `JOB_HEARTBEAT_TIMEOUT_SECONDS` | 1200 | Fence an active worker attempt after this heartbeat age |
| `STUCK_JOB_SWEEP_INTERVAL_SECONDS` | 60 | Cadence for stale-attempt recovery |
| `SHUTDOWN_TIMEOUT_SECONDS` | 30 | Max drain time on SIGTERM |

## Testing

```
pnpm --filter @papercrane/worker test
```

Vitest suites cover:
- `jobProcessor.test.ts` — happy path, cancellation mid-run, infra retry, user error
- `transitions.test.ts` — illegal transitions rejected, DB + audit in one tx, idempotent
- `retention.test.ts` — expired jobs purged, non-expired untouched
- `modalRunner.test.ts` — deployed bridge parsing, cancellation, bounded fan-out, outage classification
- `providers/modalClient.test.ts` — legacy injected-client compatibility tests
- `providers/modal.test.ts` — happy path, error events, cancel, infra retry, missing-token fallback

All tests stub Prisma / Redis / the provider registry in memory — no
infrastructure required.

## Modal runtime contract

Production uses `modal.Function.from_name(app, "papercrane_dispatch")` through
`scripts/invoke-deployed-modal.py`. The worker passes job ID, one or more seeds,
and JSON parameters over stdin so signed URLs never appear in argv or logs.
Each deployed function must return or emit this NDJSON contract:

Stream event contract (what each deployed `papercrane-*` Function must emit):

```
{"type":"log","level":"info","message":"..."}
{"type":"seed","seed":1,"designId":"...","metrics":{...},"artifactKey":"..."}
{"type":"done"}
{"type":"error","code":"GPU_PREEMPT","message":"...","retryable":true}
```

Control-plane connection failures and hard timeouts are classified as
retryable infrastructure failures. User cancellation cancels every active
FunctionCall. Each call has a timeout floor of 15 minutes.

Tool → Function mapping lives in `providers/modalFunctionMap.ts`. Adding a
new tool requires adding an entry there and a `PAPERCRANE_ENTRYPOINTS` mapping
in `adapters/_modalRunner.ts`.

## TODO

- [ ] Vast.ai provider (plan 03 §3.2).
- [ ] RunPod provider (plan 03 §3.3).
- [ ] Audit-log table (`jobAudit`) in Prisma schema — currently written
      best-effort in `transitions.ts` via a soft check.
