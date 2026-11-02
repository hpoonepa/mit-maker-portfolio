/**
 * App env validation: server-side only.
 *
 * IMPORTANT: this module reads `SUPABASE_SERVICE_ROLE_KEY`, which must NEVER
 * be bundled into client code. Next.js will only inline `NEXT_PUBLIC_*` vars,
 * so importing this from a Server Component, Route Handler, or `getStaticProps`
 * is safe: but importing it from a Client Component will throw at request
 * time because `process.env.SUPABASE_SERVICE_ROLE_KEY` is `undefined` in the
 * browser bundle.
 *
 * Public vars (NEXT_PUBLIC_*) are exposed via `getPublicEnv()` and are safe
 * to call from anywhere.
 */

import {
  AppPublicEnvSchema,
  AppServerEnvSchema,
  parseEnv,
  type AppPublicEnv,
  type AppServerEnv,
} from "@papercrane/env";

export type { AppPublicEnv, AppServerEnv };

let publicCached: AppPublicEnv | null = null;
let serverCached: AppServerEnv | null = null;

/**
 * Validate the public (NEXT_PUBLIC_*) env. Safe to call from anywhere: these
 * vars are baked into the client bundle by Next.
 */
export function getPublicEnv(): AppPublicEnv {
  if (publicCached) return publicCached;
  publicCached = parseEnv(AppPublicEnvSchema, process.env, { service: "app" });
  return publicCached;
}

/**
 * Validate the server-only env. Throws if called from a client bundle (the
 * service-role key will be missing).
 *
 * Call this from Route Handlers, Server Actions, or any `app/` server module
 * that needs admin access to Supabase.
 */
export function getServerEnv(): AppServerEnv {
  if (serverCached) return serverCached;
  if (typeof window !== "undefined") {
    throw new Error(
      "getServerEnv() called from the browser: server-only env vars are not available in the client bundle.",
    );
  }
  serverCached = parseEnv(AppServerEnvSchema, process.env, { service: "app" });
  return serverCached;
}
