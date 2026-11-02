#!/usr/bin/env node
// Paper Crane pre-flight health check. Diagnose dev env in <5s.
// Usage: pnpm dev:check  (exit 0 = green, non-zero = something to fix)

import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const ENV_PATH = join(ROOT, '.env.local');

const RED = '\x1b[31m';
const GREEN = '\x1b[32m';
const YELLOW = '\x1b[33m';
const DIM = '\x1b[2m';
const RESET = '\x1b[0m';

let failed = 0;
const pass = (label) => console.log(`${GREEN}PASS${RESET} ${label}`);
const fail = (label, hint) => {
  failed++;
  console.log(`${RED}FAIL${RESET} ${label}`);
  if (hint) console.log(`     ${DIM}-> ${hint}${RESET}`);
};
const warn = (label, hint) => {
  console.log(`${YELLOW}WARN${RESET} ${label}`);
  if (hint) console.log(`     ${DIM}-> ${hint}${RESET}`);
};

// --- Parse .env.local without printing values ---
function parseEnvFile(path) {
  if (!existsSync(path)) return null;
  const out = {};
  const raw = readFileSync(path, 'utf8');
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq < 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let val = trimmed.slice(eq + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (key) out[key] = val;
  }
  return out;
}

// --- Check 1: .env.local exists ---
console.log(`${DIM}Paper Crane pre-flight check${RESET}`);
console.log('');
const env = parseEnvFile(ENV_PATH);
if (env) {
  pass('.env.local exists');
} else {
  fail('.env.local missing', `create ${ENV_PATH} (copy from .env.example if present)`);
}

// --- Check 2: required env vars set ---
const REQUIRED = [
  'DATABASE_URL',
  'DIRECT_URL',
  'NEXT_PUBLIC_SUPABASE_URL',
  'NEXT_PUBLIC_SUPABASE_ANON_KEY',
  'SUPABASE_SERVICE_ROLE_KEY',
];
const missing = env ? REQUIRED.filter((k) => !env[k] || env[k].length === 0) : REQUIRED;
if (missing.length === 0) {
  pass(`required env vars set (${REQUIRED.length})`);
} else {
  fail(`missing env vars: ${missing.join(', ')}`, 'add them to .env.local');
}

// --- tcp port check helper ---
function probePort(host, port, timeoutMs = 600) {
  return new Promise((resolve) => {
    const sock = new net.Socket();
    let done = false;
    const finish = (state) => {
      if (done) return;
      done = true;
      try { sock.destroy(); } catch {}
      resolve(state);
    };
    sock.setTimeout(timeoutMs);
    sock.once('connect', () => finish('open'));
    sock.once('timeout', () => finish('timeout'));
    sock.once('error', () => finish('closed'));
    sock.connect(port, host);
  });
}

function parsePgUrl(url) {
  try {
    const u = new URL(url);
    return {
      host: u.hostname,
      port: u.port ? Number(u.port) : 5432,
    };
  } catch {
    return null;
  }
}

// --- Check 3: postgres reachable ---
const dbUrl = env?.DATABASE_URL;
let pgClient = null;
let pgReachable = false;
if (!dbUrl) {
  fail('postgres reachable', 'DATABASE_URL not set');
} else {
  const parsed = parsePgUrl(dbUrl);
  if (!parsed) {
    fail('postgres reachable', `DATABASE_URL not parseable as URL`);
  } else {
    const state = await probePort(parsed.host, parsed.port, 800);
    if (state === 'open') {
      pass(`postgres port reachable (${parsed.host}:${parsed.port})`);
      pgReachable = true;
    } else {
      fail(
        `postgres unreachable (${parsed.host}:${parsed.port}, ${state})`,
        'start your db: docker compose up -d postgres (or check Supabase status)'
      );
    }
  }
}

// --- Check 4 & 5: migrations + seed (require @prisma/client) ---
async function loadPrisma() {
  if (!pgReachable) return null;
  // @prisma/client lives in packages/db/node_modules — import via file URL
  // so resolution works regardless of cwd.
  const candidates = [
    join(ROOT, 'packages/db/node_modules/@prisma/client/default.js'),
    join(ROOT, 'node_modules/@prisma/client/default.js'),
  ];
  let mod = null;
  let lastErr = null;
  for (const c of candidates) {
    if (!existsSync(c)) continue;
    try {
      mod = await import(`file://${c}`);
      break;
    } catch (err) {
      lastErr = err;
    }
  }
  if (!mod) {
    return {
      __errorKind: 'client',
      __error: lastErr || new Error('@prisma/client not found in workspace'),
    };
  }
  try {
    const { PrismaClient } = mod;
    const preflightUrl = new URL(dbUrl);
    // Keep this health check fast even when a remote pooler accepts TCP but
    // cannot route the configured tenant.
    preflightUrl.searchParams.set('connect_timeout', '4');
    preflightUrl.searchParams.set('pool_timeout', '4');
    preflightUrl.searchParams.set('connection_limit', '1');
    const client = new PrismaClient({
      datasources: { db: { url: preflightUrl.toString() } },
      log: [],
    });
    await client.$connect();
    return client;
  } catch (err) {
    return { __errorKind: 'connection', __error: err };
  }
}

pgClient = await loadPrisma();

if (!pgReachable) {
  fail('migrations applied', 'postgres unreachable - fix above first');
  fail('seed populated (tools)', 'postgres unreachable - fix above first');
} else if (!pgClient || pgClient.__error) {
  const msg = pgClient?.__error?.message || 'unknown';
  if (pgClient?.__errorKind === 'connection') {
    fail('postgres authentication/query failed', msg.split('\n')[0]);
    fail('migrations applied', 'fix DATABASE_URL, then rerun pnpm dev:check');
    fail('seed populated (tools)', 'fix DATABASE_URL, then rerun pnpm dev:check');
  } else {
    fail('@prisma/client unavailable', `cannot run db checks (${msg.split('\n')[0]})`);
    fail(
      'migrations applied',
      'install/generate prisma client: pnpm --filter @papercrane/db exec prisma generate'
    );
    fail('seed populated (tools)', 'install/generate prisma client first');
  }
} else {
  // Migrations
  try {
    // Exclude rolled-back rows from the denominator. Prisma keeps history
    // entries for failed migrations until they're explicitly resolved; those
    // shouldn't count as "missing" once the user has rolled them back and
    // re-run deploy.
    const rows = await pgClient.$queryRawUnsafe(
      'SELECT COUNT(*) FILTER (WHERE rolled_back_at IS NULL)::int AS n, COUNT(*) FILTER (WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL)::int AS applied FROM _prisma_migrations'
    );
    const n = rows?.[0]?.n ?? 0;
    const applied = rows?.[0]?.applied ?? 0;
    if (n === 0 || applied === 0) {
      fail(
        `migrations not applied (${applied}/${n})`,
        'pnpm --filter @papercrane/db exec prisma migrate deploy'
      );
    } else if (applied < n) {
      fail(
        `migrations partially applied (${applied}/${n})`,
        'pnpm --filter @papercrane/db exec prisma migrate deploy'
      );
    } else {
      const history = await pgClient.$queryRawUnsafe(
        'SELECT migration_name FROM _prisma_migrations WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL'
      );
      const appliedNames = new Set(history.map((row) => row.migration_name));
      const migrationDir = join(ROOT, 'packages/db/prisma/migrations');
      const localNames = readdirSync(migrationDir, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && existsSync(join(migrationDir, entry.name, 'migration.sql')))
        .map((entry) => entry.name);
      const pending = localNames.filter((name) => !appliedNames.has(name));
      if (pending.length) {
        fail(`pending migrations (${pending.length}): ${pending.join(', ')}`, 'review and apply migrations with prisma migrate deploy');
      } else {
        pass(`migrations applied (${localNames.length}/${localNames.length} checked-in migrations)`);
      }
    }
  } catch (err) {
    const msg = String(err?.message || err);
    if (msg.includes('_prisma_migrations') || msg.includes('does not exist')) {
      fail(
        'migrations table missing',
        'pnpm --filter @papercrane/db exec prisma migrate deploy'
      );
    } else {
      fail('migrations check failed', msg.split('\n')[0]);
    }
  }

  // Seed (tools)
  try {
    const rows = await pgClient.$queryRawUnsafe('SELECT COUNT(*)::int AS n FROM tools');
    const n = rows?.[0]?.n ?? 0;
    if (n > 0) {
      pass(`seed populated (tools=${n})`);
    } else {
      fail('tools table empty', 'pnpm --filter @papercrane/db run db:seed');
    }
  } catch (err) {
    const msg = String(err?.message || err);
    if (msg.toLowerCase().includes('relation') && msg.toLowerCase().includes('tools')) {
      fail('tools table missing', 'run migrations then seed');
    } else {
      fail('seed check failed', msg.split('\n')[0]);
    }
  }

  try { await pgClient.$disconnect(); } catch {}
}

// --- Check 6: ports free or owned by us ---
const PORTS = [3000, 3001, 3002];
const portStates = await Promise.all(PORTS.map((p) => probePort('127.0.0.1', p, 300)));
PORTS.forEach((port, i) => {
  const state = portStates[i];
  if (state !== 'open') {
    pass(`port ${port} free`);
  } else {
    // We can't cheaply tell if it's "us" without lsof; warn rather than fail.
    warn(
      `port ${port} in use`,
      `run: lsof -nP -iTCP:${port} -sTCP:LISTEN  (kill with: kill $(lsof -tiTCP:${port} -sTCP:LISTEN))`
    );
  }
});

// --- Final ---
console.log('');
if (failed === 0) {
  console.log(`${GREEN}ALL GREEN${RESET} - dev env ready (pnpm dev)`);
  process.exit(0);
} else {
  console.log(`${RED}${failed} CHECK${failed === 1 ? '' : 'S'} FAILED${RESET} - see above`);
  process.exit(1);
}
