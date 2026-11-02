/**
 * Inferred AppEnv types per service. Re-exported through the barrel so
 * downstream code can write `import type { ApiEnv } from "@papercrane/env"`.
 */

import type { z } from "zod";
import type {
  ApiEnvSchema,
  AppPublicEnvSchema,
  AppServerEnvSchema,
  WebEnvSchema,
  WorkerEnvSchema,
} from "./schema.js";

export type ApiEnv = z.infer<typeof ApiEnvSchema>;
export type WorkerEnv = z.infer<typeof WorkerEnvSchema>;
export type AppPublicEnv = z.infer<typeof AppPublicEnvSchema>;
export type AppServerEnv = z.infer<typeof AppServerEnvSchema>;
export type WebEnv = z.infer<typeof WebEnvSchema>;

/** Service identifier used by `parseEnv` to look up production requirements. */
export type ServiceName = "api" | "worker" | "app" | "web";

export interface ParseEnvOptions {
  /** Service name — drives the production-required + warn-if-missing lists. */
  service: ServiceName;
  /** When true, the parser logs warnings + a banner but never throws. */
  checkOnly?: boolean;
  /** Override stdout/stderr for tests. */
  out?: (line: string) => void;
  err?: (line: string) => void;
}
