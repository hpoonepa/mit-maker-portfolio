# @papercrane/jobs

Canonical job state machine, event schemas, retry policy, and BullMQ queue
helpers for the Paper Crane orchestrator.

Implements the design in `docs/plans/01-core-platform.md` §5.

## State machine

```
queued    → preparing, cancelled
preparing → running, cancelling
running   → partial, succeeded, failed, cancelling
partial   → succeeded, failed, cancelling     // partial → succeeded via `continue`
cancelling→ cancelled
succeeded → purged                            // retention cron
failed    → queued, purged                    // queued = retry
cancelled → —
purged    → —
```

Terminal states: `succeeded`, `failed`, `cancelled`, `purged`.

## Usage

### Guard a status write

```ts
import { transition, IllegalTransitionError } from '@papercrane/jobs';

try {
  const next = transition(job.status, 'running'); // throws on illegal
  await db.update({ id: job.id, status: next });
} catch (err) {
  if (err instanceof IllegalTransitionError) {
    logger.error({ from: err.from, next: err.next }, 'bad transition');
  }
  throw err;
}
```

### Publish an event

```ts
import { statusEvent, serializeEvent } from '@papercrane/jobs';
import { redis } from './redis';

await redis.publish(
  `jobs:${jobId}:events`,
  serializeEvent(statusEvent('running')),
);
```

### Validate a wire message (SSE handler)

```ts
import { deserializeEvent } from '@papercrane/jobs';

redis.subscribe(`jobs:${jobId}:events`, (raw) => {
  const event = deserializeEvent(raw); // throws on malformed / wrong schema
  sseClient.send(event);
});
```

### Retry logic

```ts
import { shouldRetry, backoffSeconds } from '@papercrane/jobs';

if (shouldRetry(error, attempt)) {
  await queue.add(jobData, { delay: backoffSeconds(attempt) * 1000 });
} else {
  await db.markFailed(jobId, error);
}
```

Only infra errors are retried (`GPU_PREEMPT`, `NETWORK_TIMEOUT`,
`CONTAINER_OOM`, `PROVIDER_UNAVAILABLE`). User errors (`INVALID_INPUT`,
`BAD_PDB`, `QUOTA_EXCEEDED`) are never retried.

Backoff: 60s, 120s, 240s, capped at 600s.

### Per-tier queues

```ts
import { jobQueueName, type Tier } from '@papercrane/jobs';
import { Queue } from 'bullmq';

const q = new Queue(jobQueueName(tier), { connection: redis });
```

## Layout

| File | Responsibility |
|---|---|
| `src/status.ts` | `JobStatus` union + `isTerminal` / `canTransition` |
| `src/transitions.ts` | Transition table + `transition()` guard + `IllegalTransitionError` |
| `src/events.ts` | `JobEvent` discriminated union, zod schemas, builder helpers |
| `src/retry.ts` | `shouldRetry` + `backoffSeconds` + error code constants |
| `src/queue.ts` | BullMQ queue name constants + `jobQueueName(tier)` |
| `src/serde.ts` | `serializeEvent` / `deserializeEvent` (zod-validated) |

## Scripts

```bash
npm test        # vitest
npm run typecheck
```
