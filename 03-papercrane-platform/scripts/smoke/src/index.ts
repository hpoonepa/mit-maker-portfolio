#!/usr/bin/env -S node --import tsx
/**
 * CLI entrypoint for `@papercrane/smoke`.
 *
 * Usage:
 *   pnpm smoke                     # default config
 *   SMOKE_PORT=3010 pnpm smoke     # custom port
 *   pnpm smoke -- --skip-spawn     # probe an already-running dev server
 *
 * Exit code 0 on all-pass, 1 on any failure (including spawn/ready errors).
 */

import { runSmoke } from './runner.js';

function parseArgs(argv: string[]): { skipSpawn: boolean } {
  return {
    skipSpawn: argv.includes('--skip-spawn'),
  };
}

async function main(): Promise<void> {
  const { skipSpawn } = parseArgs(process.argv.slice(2));
  try {
    const result = await runSmoke({ skipSpawn });
    const failed = result.results.filter((r) => !r.passed).length;
    console.log(
      `[smoke] done in ${result.durationMs}ms — ${result.results.length - failed}/${result.results.length} passed`
    );
    process.exit(result.passed ? 0 : 1);
  } catch (err) {
    console.error('[smoke] fatal error:', err instanceof Error ? err.stack ?? err.message : err);
    process.exit(1);
  }
}

void main();
