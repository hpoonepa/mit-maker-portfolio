/**
 * Worker service env validation.
 *
 * Note: REDIS_URL is optional in the schema because the worker has a Wave 10
 * dev fallback (in-memory queue). Production-required overlay in
 * `@papercrane/env` still enforces it when NODE_ENV=production.
 */

import { parseEnvOrCheckFlag, WorkerEnvSchema, type WorkerEnv } from "@papercrane/env";

export type { WorkerEnv };

let cached: WorkerEnv | null = null;

export function loadWorkerEnv(argv: readonly string[] = process.argv): WorkerEnv {
  if (cached) return cached;
  cached = parseEnvOrCheckFlag(WorkerEnvSchema, process.env, argv, { service: "worker" });
  return cached;
}
