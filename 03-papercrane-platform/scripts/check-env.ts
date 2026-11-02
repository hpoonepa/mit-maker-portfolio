#!/usr/bin/env -S npx tsx
/**
 * check-env.ts
 *
 * Validates that `.env.local` at the repo root contains every required
 * environment variable with a non-empty value. Exits with a non-zero status
 * code and prints the missing variables grouped by scope when validation
 * fails.
 *
 * Usage:
 *   npx tsx scripts/check-env.ts
 *
 * The script does not load secrets anywhere — it only reads `.env.local` to
 * confirm the shape of the developer's local config.
 */

import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

type Scope = 'web' | 'api' | 'worker' | 'all';

interface EnvSpec {
  name: string;
  scope: Scope;
  required: boolean;
}

// Mirror of `.env.example`. Keep in sync manually; the set of required vars
// rarely changes and a hand-maintained list is easier to audit than a parser.
const SPEC: EnvSpec[] = [
  // Core
  { name: 'NODE_ENV', scope: 'all', required: true },
  { name: 'LOG_LEVEL', scope: 'all', required: false },

  // Supabase
  { name: 'NEXT_PUBLIC_SUPABASE_URL', scope: 'web', required: true },
  { name: 'NEXT_PUBLIC_SUPABASE_ANON_KEY', scope: 'web', required: true },
  { name: 'SUPABASE_SERVICE_ROLE_KEY', scope: 'api', required: true },
  { name: 'SUPABASE_PROJECT_REF', scope: 'api', required: true },
  { name: 'DATABASE_URL', scope: 'api', required: true },

  // Redis
  { name: 'REDIS_URL', scope: 'api', required: true },

  // R2
  { name: 'R2_ACCOUNT_ID', scope: 'api', required: true },
  { name: 'R2_ACCESS_KEY_ID', scope: 'api', required: true },
  { name: 'R2_SECRET_ACCESS_KEY', scope: 'api', required: true },
  { name: 'R2_BUCKET', scope: 'api', required: true },

  // Stripe
  { name: 'STRIPE_SECRET_KEY', scope: 'api', required: true },
  { name: 'STRIPE_WEBHOOK_SECRET', scope: 'api', required: true },
  { name: 'STRIPE_PRICE_PRO_MONTHLY', scope: 'api', required: true },
  { name: 'STRIPE_PRICE_PRO_ANNUAL', scope: 'api', required: true },
  { name: 'STRIPE_PRICE_SEAT_ADDON', scope: 'api', required: true },
  { name: 'STRIPE_PRICE_PACK_10K', scope: 'api', required: true },

  // GPU providers
  { name: 'MODAL_TOKEN_ID', scope: 'worker', required: true },
  { name: 'MODAL_TOKEN_SECRET', scope: 'worker', required: true },
  { name: 'MODAL_WORKSPACE', scope: 'worker', required: true },
  { name: 'VASTAI_API_KEY', scope: 'worker', required: false },
  { name: 'RUNPOD_API_KEY', scope: 'worker', required: false },

  // Observability
  { name: 'SENTRY_DSN', scope: 'all', required: false },
  { name: 'SENTRY_ENVIRONMENT', scope: 'all', required: false },
  { name: 'POSTHOG_KEY', scope: 'web', required: false },
  { name: 'POSTHOG_HOST', scope: 'web', required: false },
  { name: 'LOGTAIL_SOURCE_TOKEN', scope: 'api', required: false },

  // Infisical
  { name: 'INFISICAL_CLIENT_ID', scope: 'worker', required: false },
  { name: 'INFISICAL_CLIENT_SECRET', scope: 'worker', required: false },
  { name: 'INFISICAL_PROJECT_ID', scope: 'worker', required: false },

  // URLs
  { name: 'NEXT_PUBLIC_APP_URL', scope: 'web', required: true },
  { name: 'API_BASE_URL', scope: 'api', required: true },
  { name: 'WORKER_URL', scope: 'worker', required: true },

  // Feature flags
  { name: 'FEATURE_FRONTIER_TIER', scope: 'web', required: false },
  { name: 'FEATURE_PUBLIC_LEADERBOARD', scope: 'web', required: false },

  // Security
  { name: 'API_KEY_PEPPER', scope: 'api', required: true },
];

const SCOPE_ORDER: Scope[] = ['all', 'web', 'api', 'worker'];

function parseDotEnv(contents: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    // Strip wrapping quotes if present.
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

function main(): number {
  const here = dirname(fileURLToPath(import.meta.url));
  const repoRoot = resolve(here, '..');
  const envPath = resolve(repoRoot, '.env.local');

  if (!existsSync(envPath)) {
    console.error(`[check-env] Missing .env.local at ${envPath}`);
    console.error('[check-env] Copy .env.example to .env.local and fill in values.');
    return 1;
  }

  const contents = readFileSync(envPath, 'utf8');
  const parsed = parseDotEnv(contents);

  const missing: Record<Scope, string[]> = {
    all: [],
    web: [],
    api: [],
    worker: [],
  };

  for (const spec of SPEC) {
    if (!spec.required) continue;
    const value = parsed[spec.name];
    if (value === undefined || value.length === 0) {
      missing[spec.scope].push(spec.name);
    }
  }

  const totalMissing = SCOPE_ORDER.reduce((n, s) => n + missing[s].length, 0);

  if (totalMissing === 0) {
    console.log('[check-env] OK — all required environment variables are set.');
    return 0;
  }

  console.error(`[check-env] Missing ${totalMissing} required variable(s):`);
  for (const scope of SCOPE_ORDER) {
    const vars = missing[scope];
    if (vars.length === 0) continue;
    console.error(`\n  [${scope}]`);
    for (const name of vars) {
      console.error(`    - ${name}`);
    }
  }
  console.error('\n[check-env] See docs/env-vars.md for where to source each value.');
  return 1;
}

process.exit(main());
