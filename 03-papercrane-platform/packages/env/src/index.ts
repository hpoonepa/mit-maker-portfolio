/**
 * @papercrane/env — startup env validation, single source of truth.
 *
 * Usage (any service):
 *
 *     import { parseEnvOrCheckFlag, ApiEnvSchema } from "@papercrane/env";
 *     const env = parseEnvOrCheckFlag(ApiEnvSchema, process.env, process.argv, {
 *       service: "api",
 *     });
 *
 * Pass `--check-env` to validate without booting (used in CI + Docker
 * healthchecks).
 */

export {
  ApiEnvSchema,
  AppPublicEnvSchema,
  AppServerEnvSchema,
  WebEnvSchema,
  WorkerEnvSchema,
  productionRequired,
  warnIfMissing,
} from "./schema.js";

export { parseEnv, parseEnvSafe, parseEnvOrCheckFlag } from "./parse.js";
export type { ParseEnvResult } from "./parse.js";
export type {
  ApiEnv,
  AppPublicEnv,
  AppServerEnv,
  ParseEnvOptions,
  ServiceName,
  WebEnv,
  WorkerEnv,
} from "./types.js";
