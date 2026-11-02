# @papercrane/types

Shared zod schemas and TypeScript types consumed by the Paper Crane API,
worker, SDK, and dashboard. This package is foundational — it has **zero
dependencies on other `@papercrane/*` packages**.

## Layout

| Module | Contents |
|--------|----------|
| `design.ts` | `DesignRequest`, `DesignResult`, `DesignMetrics`, `Hotspot`, `DesignConstraints` |
| `job.ts` | `JobStatus`, `JobSubmission`, `JobSummary`, `JobEvent` (discriminated union) |
| `tool.ts` | `ToolManifest`, `ToolTier`, `ToolCategory`, `ComputeProfile` |
| `target.ts` | `Target`, `TargetClass`, `TargetTier` (re-exports `Hotspot`) |
| `auth.ts` | `AuthContext`, `Tier`, `ApiKeyScope` |
| `usage.ts` | `SeedConsumeRequest`, `SeedConsumeResponse`, `UsagePeriod` |
| `benchmark.ts` | `BenchmarkRun`, `RunManifest`, `BenchmarkCell`, `BenchmarkRunStatus` |
| `webhook.ts` | `WebhookEvent`, `WebhookSubscription`, `WebhookEventType` |

## Conventions

- Every schema is exported as both a zod schema (`FooSchema`) and an inferred
  TypeScript type (`Foo`).
- All object schemas are `.strict()` — unknown keys are rejected.
- Enums use `z.enum([...] as const)` so both the zod value and the TS type stay
  aligned.
- Dates are ISO-8601 strings (`z.string().datetime()`), never `Date` objects,
  so payloads serialize cleanly across the wire.
- UUIDs: `z.string().uuid()`. Slug-like ids (`toolId`, `orgSlug`, `slug`) use
  kebab/snake regex validators.
- Metrics are `z.record(z.string(), z.number())` so new metrics can be added
  without breaking old consumers.

## Usage

```ts
import { DesignRequestSchema, type DesignRequest } from '@papercrane/types';

const req: DesignRequest = DesignRequestSchema.parse(rawBody);
```

## Scripts

```bash
pnpm test       # vitest run
pnpm typecheck  # tsc --noEmit
pnpm build      # tsc -p tsconfig.json
```
