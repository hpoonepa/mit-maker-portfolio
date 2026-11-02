# @papercrane/observability

Shared observability primitives for Paper Crane services: structured logging,
error tracking, Prometheus metrics, optional tracing, and a standard health
check response shape.

## Modules

| Module        | Exports                                                        | Purpose                                    |
| ------------- | -------------------------------------------------------------- | ------------------------------------------ |
| `logger`      | `createLogger`, `createChildLogger`, `REDACT_PATHS`            | pino logger, JSON in prod / pretty in dev  |
| `sentry`      | `initSentry`, `captureException`, `isSentryInitialized`        | Sentry (Node) wrapper, safe no-op w/o DSN  |
| `metrics`     | `counter`, `histogram`, `metricsRegistry`, `enableDefaultMetrics` | Thin prom-client wrapper                 |
| `trace`       | `withSpan`                                                     | OTel passthrough when available            |
| `healthz`     | `buildHealthResponse`                                          | Standard `{ ok, checks }` response         |

Client-side Sentry init for the Next.js web app lives in that app — this package
is Node-only.

## Usage

### Logger

```ts
import { createLogger, createChildLogger } from '@papercrane/observability';

const log = createLogger({ service: 'jobs-worker' });
const reqLog = createChildLogger(log, { requestId: 'req-abc' });

reqLog.info({ userId: 'u-1' }, 'handling request');
```

Redacted fields: `authorization` (incl. `req.headers.authorization`),
`api_key`, `apiKey`, `token`, `password`, `r2_secret_access_key`.

### Sentry

```ts
import { initSentry, captureException } from '@papercrane/observability';

initSentry({
  dsn: process.env.SENTRY_DSN,
  environment: process.env.NODE_ENV ?? 'development',
  release: process.env.GIT_SHA,
  tracesSampleRate: 0.1,
});

try {
  await doWork();
} catch (err) {
  captureException(err, { jobId });
  throw err;
}
```

### Metrics

```ts
import { counter, histogram, metricsRegistry } from '@papercrane/observability';

const jobsTotal = counter('papercrane_jobs_total', 'Jobs processed', ['status']);
const jobDuration = histogram('papercrane_job_duration_seconds', 'Job duration');

jobsTotal.inc({ status: 'ok' });
const end = jobDuration.startTimer();
await runJob();
end();

// Expose at /metrics:
// res.setHeader('Content-Type', metricsRegistry.contentType);
// res.send(await metricsRegistry.metrics());
```

Default buckets for `histogram(name, help)` (seconds):
`[0.1, 0.5, 1, 5, 10, 30, 60, 300, 1800, 3600, 14400]`.

### Tracing

```ts
import { withSpan } from '@papercrane/observability';

await withSpan('design.predict', async () => {
  return await predictor.run(input);
});
```

`withSpan` is a no-op when `@opentelemetry/api` isn't loaded in the process, so
services opt in by installing an OTel SDK themselves.

### Health checks

```ts
import { buildHealthResponse } from '@papercrane/observability';

app.get('/healthz', async (_req, res) => {
  const body = await buildHealthResponse({
    db: async () => (await db.query('select 1')).rowCount === 1,
    r2: async () => await storage.ping(),
  });
  res.status(body.ok ? 200 : 503).json(body);
});
```

## Scripts

```bash
pnpm test        # vitest
pnpm typecheck   # tsc --noEmit
```
