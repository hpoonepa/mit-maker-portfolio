/**
 * Marketing site env. Almost nothing required — `NEXT_PUBLIC_SITE_URL`
 * defaults to localhost so `pnpm dev` works with zero config.
 */

import { WebEnvSchema, parseEnv, type WebEnv } from "@papercrane/env";

export type { WebEnv };

let cached: WebEnv | null = null;

export function getWebEnv(): WebEnv {
  if (cached) return cached;
  cached = parseEnv(WebEnvSchema, process.env, { service: "web" });
  return cached;
}
