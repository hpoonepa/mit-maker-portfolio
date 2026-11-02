/**
 * Smoke runner: spawns `pnpm --filter @papercrane/web dev`, waits for the
 * server to answer, probes every route in parallel, writes junit-xml, and
 * tears the server down cleanly.
 */

import { execa, type ResultPromise } from 'execa';
import { writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ROUTES, type RouteSpec } from './routes.js';
import { probeRoute, waitForReady, type ProbeResult } from './probe.js';

export type RunnerConfig = {
  /** Port the dev server listens on. Default 3002 (3000 is often busy). */
  port?: number;
  /** Host/IP to connect to when probing. Default 127.0.0.1. */
  host?: string;
  /** Maximum ms to wait for server readiness. Default 90_000. */
  maxReadyMs?: number;
  /** Retries per route. Default 3 (i.e. 4 attempts). */
  retriesPerRoute?: number;
  /** Per-attempt probe timeout in ms. Default 10_000. */
  probeTimeoutMs?: number;
  /** JUnit XML output path. Default `scripts/smoke/results.xml`. */
  resultsPath?: string;
  /** Root of the pnpm monorepo, defaults to three levels above this file. */
  monorepoRoot?: string;
  /** Skip spawning — probe an already-running server. */
  skipSpawn?: boolean;
  /** Routes to probe. Defaults to ROUTES. */
  routes?: RouteSpec[];
  /** Logger. Defaults to console. */
  logger?: Pick<Console, 'log' | 'warn' | 'error'>;
};

export type RunnerResult = {
  passed: boolean;
  results: ProbeResult[];
  resultsPath: string;
  durationMs: number;
};

const SIGKILL_GRACE_MS = 5_000;

export async function runSmoke(config: RunnerConfig = {}): Promise<RunnerResult> {
  const started = Date.now();
  const port = config.port ?? Number(process.env.SMOKE_PORT ?? 3002);
  const host = config.host ?? '127.0.0.1';
  const baseUrl = `http://${host}:${port}`;
  const monorepoRoot = config.monorepoRoot ?? defaultMonorepoRoot();
  const resultsPath =
    config.resultsPath ?? resolve(monorepoRoot, 'scripts/smoke/results.xml');
  const logger = config.logger ?? console;
  const routes = config.routes ?? ROUTES;

  let devProcess: ResultPromise | undefined;

  try {
    if (!config.skipSpawn) {
      logger.log(`[smoke] launching @papercrane/web on port ${port}`);
      devProcess = execa(
        'pnpm',
        ['--filter', '@papercrane/web', 'dev', '--port', String(port)],
        {
          cwd: monorepoRoot,
          env: {
            ...process.env,
            PORT: String(port),
            NEXT_TELEMETRY_DISABLED: '1',
            // Next will still boot without Supabase env; the smoke routes
            // exercise the fallback branches documented in routes.ts.
            CI: '1',
          },
          stdio: ['ignore', 'pipe', 'pipe'],
          reject: false,
          cleanup: true,
        }
      );

      pipeOutput(devProcess, logger);
    } else {
      logger.log(`[smoke] skipSpawn=true — probing existing server at ${baseUrl}`);
    }

    logger.log(`[smoke] waiting for ${baseUrl} to respond (up to ${config.maxReadyMs ?? 90_000}ms)`);
    await waitForReady(baseUrl, {
      maxWaitMs: config.maxReadyMs ?? 90_000,
      onAttempt: (n) => {
        if (n % 10 === 0) logger.log(`[smoke] readiness attempt ${n}`);
      },
    });
    logger.log(`[smoke] server ready. probing ${routes.length} routes in parallel.`);

    const results = await Promise.all(
      routes.map((route) =>
        probeRoute(baseUrl, route, {
          retries: config.retriesPerRoute ?? 3,
          timeoutMs: config.probeTimeoutMs ?? 10_000,
        })
      )
    );

    const passed = results.every((r) => r.passed);
    renderSummary(results, logger);

    await writeJUnit(results, resultsPath, Date.now() - started);
    logger.log(`[smoke] junit written to ${resultsPath}`);

    return {
      passed,
      results,
      resultsPath,
      durationMs: Date.now() - started,
    };
  } finally {
    if (devProcess) {
      await shutdown(devProcess, logger);
    }
  }
}

function defaultMonorepoRoot(): string {
  // this file: <root>/scripts/smoke/src/runner.ts
  const here = dirname(fileURLToPath(import.meta.url));
  return resolve(here, '..', '..', '..');
}

function pipeOutput(
  proc: ResultPromise,
  logger: Pick<Console, 'log' | 'warn'>
): void {
  proc.stdout?.on('data', (chunk: Buffer) => {
    const line = chunk.toString('utf8').trimEnd();
    if (line) logger.log(`[web] ${line}`);
  });
  proc.stderr?.on('data', (chunk: Buffer) => {
    const line = chunk.toString('utf8').trimEnd();
    if (line) logger.warn(`[web!] ${line}`);
  });
}

async function shutdown(
  proc: ResultPromise,
  logger: Pick<Console, 'log' | 'warn'>
): Promise<void> {
  if (proc.exitCode != null) return;
  logger.log('[smoke] sending SIGTERM to dev server');
  try {
    proc.kill('SIGTERM');
  } catch (err) {
    logger.warn(`[smoke] SIGTERM failed: ${String(err)}`);
  }

  const graceTimer = new Promise<'timeout'>((resolvePromise) => {
    setTimeout(() => resolvePromise('timeout'), SIGKILL_GRACE_MS);
  });
  const procPromise: Promise<'done'> = Promise.resolve(proc)
    .then(() => 'done' as const)
    .catch(() => 'done' as const);
  const winner = await Promise.race([graceTimer, procPromise]);

  if (winner === 'timeout') {
    logger.warn('[smoke] dev server did not exit in 5s — sending SIGKILL');
    try {
      proc.kill('SIGKILL');
    } catch (err) {
      logger.warn(`[smoke] SIGKILL failed: ${String(err)}`);
    }
  }
}

function renderSummary(
  results: ProbeResult[],
  logger: Pick<Console, 'log' | 'error'>
): void {
  for (const r of results) {
    const tag = r.passed ? 'PASS' : 'FAIL';
    const status = r.status ?? '---';
    logger.log(
      `[smoke] ${tag} ${r.route.method.padEnd(4)} ${r.route.path.padEnd(32)} ${status} ${r.durationMs}ms (${r.attempts} attempts)`
    );
    if (!r.passed) {
      logger.error(`[smoke]      reason: ${r.failureReason ?? '(none)'}`);
      if (r.bodySnippet) {
        logger.error(`[smoke]      body  : ${r.bodySnippet.replace(/\n/g, ' ')}`);
      }
    }
  }
}

export async function writeJUnit(
  results: ProbeResult[],
  path: string,
  durationMs: number
): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, renderJUnit(results, durationMs), 'utf8');
}

export function renderJUnit(results: ProbeResult[], durationMs: number): string {
  const failures = results.filter((r) => !r.passed).length;
  const total = results.length;
  const timeSec = (durationMs / 1000).toFixed(3);

  const cases = results.map((r) => {
    const name = xmlAttr(`${r.route.method} ${r.route.path}`);
    const classname = xmlAttr(`papercrane.smoke.${r.route.id}`);
    const time = (r.durationMs / 1000).toFixed(3);
    if (r.passed) {
      return `    <testcase classname="${classname}" name="${name}" time="${time}"/>`;
    }
    const message = xmlAttr(r.failureReason ?? 'unknown failure');
    const detail = xmlText(
      [
        `url: ${r.url}`,
        `status: ${r.status ?? '(none)'}`,
        `attempts: ${r.attempts}`,
        r.bodySnippet ? `body: ${r.bodySnippet}` : '',
      ]
        .filter(Boolean)
        .join('\n')
    );
    return [
      `    <testcase classname="${classname}" name="${name}" time="${time}">`,
      `      <failure message="${message}">${detail}</failure>`,
      `    </testcase>`,
    ].join('\n');
  });

  return [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<testsuites name="papercrane-smoke" tests="${total}" failures="${failures}" time="${timeSec}">`,
    `  <testsuite name="papercrane-smoke" tests="${total}" failures="${failures}" time="${timeSec}">`,
    ...cases,
    `  </testsuite>`,
    `</testsuites>`,
    '',
  ].join('\n');
}

function xmlAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function xmlText(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
