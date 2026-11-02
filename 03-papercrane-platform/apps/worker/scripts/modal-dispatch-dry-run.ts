/**
 * Dry-run smoke test for the Modal dispatch wiring (Wave 2).
 *
 * Resolves the exact deployed-function bridge command `runViaModal()` uses for a
 * representative tool, WITHOUT spawning anything. Lets us validate:
 *   1. modalFunctionMap.ts resolves the right workspace + function name.
 *   2. _modalRunner.ts produces a sane CLI invocation.
 *   3. PAPERCRANE_MODAL_DRY_RUN=1 short-circuits before spawn.
 *
 * Usage:
 *   pnpm tsx apps/worker/scripts/modal-dispatch-dry-run.ts
 *   # or, from this package:
 *   pnpm exec tsx scripts/modal-dispatch-dry-run.ts
 *
 * Exits 0 on success, 1 on resolution failure. Does not call Modal.
 */

import { resolveModalCommand, runViaModal } from '../src/adapters/_modalRunner';
import { KNOWN_TOOL_SLUGS } from '../src/adapters/registry';
import type { ToolInput } from '@papercrane/jobs';

const SAMPLES: Array<{ slug: string; input: ToolInput }> = KNOWN_TOOL_SLUGS.map((slug) => ({
  slug,
  input: {
    jobId: `dryrun-${slug}`,
    params: {},
    seeds: [42],
  },
}));

async function main(): Promise<number> {
  let failed = 0;

  // 1. Resolve every implemented deployed app and require its source file to exist.
  for (const { slug, input } of SAMPLES) {
    try {
      const cmd = resolveModalCommand(slug, input);
      const expectedEntrypoint = slug === 'solublempnn' ? 'predict' : 'papercrane_dispatch';
      const functionIndex = cmd.args.indexOf('--function-name');
      const appIndex = cmd.args.indexOf('--app-name');
      if (
        !cmd.args[0]?.endsWith('apps/worker/scripts/invoke-deployed-modal.py') ||
        cmd.args[functionIndex + 1] !== expectedEntrypoint ||
        cmd.args[appIndex + 1] !== cmd.fn.appName
      ) {
        console.error(`FAIL: ${slug} did not resolve to ${cmd.fn.appName}::${expectedEntrypoint} (got ${cmd.args.join(' ')})`);
        failed += 1;
        continue;
      }
      if (cmd.args.includes('run') || cmd.display.includes('modal run')) {
        console.error(`FAIL: ${slug} still uses an ephemeral modal run`);
        failed += 1;
        continue;
      }
      console.log(`OK  ${slug.padEnd(12)} -> ${cmd.fn.appName}::${expectedEntrypoint}`);
      console.log(
        `       fn workspace=${cmd.fn.workspace} name=${cmd.fn.name} version=${cmd.fn.version ?? '-'}`,
      );
    } catch (err) {
      console.error(`FAIL: ${slug} resolution error: ${(err as Error).message}`);
      failed += 1;
    }
  }

  // 2. Dry-run mode — exercises runViaModal end-to-end without spawning.
  process.env.PAPERCRANE_MODAL_DRY_RUN = '1';
  try {
    const chaiSample = SAMPLES.find((sample) => sample.slug === 'chai1')!;
    const out = await runViaModal('chai1', chaiSample.input).catch((err) => err as Error);
    if (out instanceof Error) {
      console.error(`FAIL runViaModal dry-run: ${out.message}`);
      failed += 1;
    } else {
      const meta = out.meta as Record<string, unknown> | undefined;
      console.log(`OK  runViaModal dry-run produced command: ${meta?.command}`);
      if (!meta?.dryRun) {
        console.error('FAIL: dry-run output did not have meta.dryRun=true');
        failed += 1;
      }
    }
  } finally {
    delete process.env.PAPERCRANE_MODAL_DRY_RUN;
  }

  if (failed > 0) {
    console.error(`\n${failed} dry-run check(s) failed`);
    return 1;
  }
  console.log('\nAll dry-run checks passed.');
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err: unknown) => {
    console.error('UNHANDLED:', err instanceof Error ? err.stack : err);
    process.exit(1);
  });
