/**
 * Wave 8 / Agent 4 — Modal live smoke test.
 *
 * Hits Modal with the real credentials in .env.local through the exact CLI
 * adapter used by the production worker. Must NOT run automatically in CI.
 *
 * Usage:
 *   pnpm tsx apps/worker/scripts/modal-smoke.ts
 *   # or, from this package:
 *   pnpm exec tsx scripts/modal-smoke.ts
 *
 * Behavior:
 *   • Loads .env.local from the monorepo root (via Node's --env-file or a
 *     small inline parser — no dotenv dep needed).
 *   • If MODAL_TOKEN_ID / MODAL_TOKEN_SECRET are missing, exits 0 with a
 *     log saying smoke was skipped (so foundation runs don't fail).
 *   • Runs the smallest ESM-2 model against a one-residue sequence.
 *   • Writes the full transcript to .agent-logs/04-modal-smoke.log.
 *   • Exits 0 on success, 1 on any failure.
 *
 * Secrets are NEVER printed. Only the *presence* of each token is logged.
 */

import { mkdirSync, appendFileSync, readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runViaModal } from '../src/adapters/_modalRunner';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = resolve(__dirname, '..', '..', '..');
const LOG_PATH = resolve(REPO_ROOT, '.agent-logs', '04-modal-smoke.log');
const ENV_FILES = [
  resolve(REPO_ROOT, '.env.local'),
  resolve(REPO_ROOT, 'apps', 'worker', '.env.local'),
];

// ---------- env loading (no dotenv dep) ----------

function loadEnvFile(path: string): void {
  if (!existsSync(path)) return;
  const raw = readFileSync(path, 'utf8');
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    // Strip surrounding single or double quotes.
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

// ---------- safe logging ----------

function ensureLogDir(): void {
  mkdirSync(dirname(LOG_PATH), { recursive: true });
}

function log(line: string): void {
  const stamped = `[${new Date().toISOString()}] ${line}\n`;
  appendFileSync(LOG_PATH, stamped, 'utf8');
  // Mirror to stdout so `pnpm` callers can see progress.
  process.stdout.write(stamped);
}

/** Returns a redacted indicator — never logs secret material. */
function presence(name: string): string {
  const v = process.env[name];
  if (!v) return `${name}=<missing>`;
  return `${name}=<present:len=${v.length}>`;
}

// ---------- main ----------

async function main(): Promise<number> {
  ensureLogDir();
  log('modal-smoke: starting');

  for (const f of ENV_FILES) loadEnvFile(f);

  const tokenId = process.env.MODAL_TOKEN_ID;
  const tokenSecret = process.env.MODAL_TOKEN_SECRET;
  log(`modal-smoke: env ${presence('MODAL_TOKEN_ID')} ${presence('MODAL_TOKEN_SECRET')}`);

  if (!tokenId || !tokenSecret) {
    log('modal-smoke: SKIPPED — Modal credentials not configured. Exiting 0.');
    return 0;
  }

  try {
    log('modal-smoke: invoking worker CLI adapter (esm2/8M, sequence=M)');
    const output = await runViaModal(
      'esm2',
      {
        jobId: `modal-smoke-${Date.now()}`,
        seeds: [1],
        params: {
          sequences: [{ id: 'smoke', sequence: 'M' }],
          modelSize: '8M',
          mode: 'score',
        },
      },
      {
        env: {
          ...process.env,
          MODAL_TOKEN_ID: tokenId,
          MODAL_TOKEN_SECRET: tokenSecret,
        },
        timeoutMs: 5 * 60 * 1000,
      },
    );
    if (output.designs.length !== 1) {
      log(`modal-smoke: ERROR expected one design, received ${output.designs.length}`);
      return 1;
    }
    const design = output.designs[0]!;
    if (design.sequence !== 'M' || typeof design.metrics?.pll_mean !== 'number') {
      log('modal-smoke: ERROR malformed ESM-2 seed event');
      return 1;
    }
    log('modal-smoke: SUCCESS — authenticated remote inference and NDJSON parsing passed');
    return 0;
  } catch (err) {
    const e = err as Error & { code?: string };
    log(`modal-smoke: ERROR name=${e.name ?? 'Error'} code=${e.code ?? 'n/a'} msg=${e.message}`);
    return 1;
  }
}

main()
  .then((code) => process.exit(code))
  .catch((err: unknown) => {
    try {
      ensureLogDir();
      const msg = err instanceof Error ? err.message : String(err);
      log(`modal-smoke: UNHANDLED ${msg}`);
    } catch {
      /* ignore */
    }
    process.exit(1);
  });
