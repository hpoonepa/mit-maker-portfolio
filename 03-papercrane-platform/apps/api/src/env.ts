/**
 * API service env validation.
 *
 * Imported once at startup from `server.ts`. Re-exports the parsed env so any
 * module that needs it can `import { env } from "./env.js"` instead of poking
 * `process.env` directly. Touching this file should be the only place we add
 * new vars to the API surface.
 */

import { parseEnvOrCheckFlag, ApiEnvSchema, type ApiEnv } from "@papercrane/env";

export type { ApiEnv };

let cached: ApiEnv | null = null;

/**
 * Validate `process.env` and return the typed env. Honors the `--check-env`
 * CLI flag (process exits 0/1 with a status banner).
 *
 * Safe to call multiple times — the result is memoized for the process.
 */
export function loadApiEnv(argv: readonly string[] = process.argv): ApiEnv {
  if (cached) return cached;
  cached = parseEnvOrCheckFlag(ApiEnvSchema, process.env, argv, { service: "api" });
  return cached;
}
