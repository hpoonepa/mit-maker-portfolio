#!/usr/bin/env tsx
/**
 * Paper Crane CLI entrypoint.
 *
 * Wires commander subcommands. Today we ship a single command — `scaffold-tool`
 * — per plan 02 §10 "<4 hour onboarding". Future commands (`publish-tool`,
 * `verify-manifest`, etc.) slot in here.
 */
import { Command } from 'commander';
import chalk from 'chalk';

import { registerScaffoldTool } from '../src/commands/scaffoldTool.js';

const program = new Command();

program
  .name('papercrane-cli')
  .description('Paper Crane developer CLI — scaffold tools, verify manifests.')
  .version('0.1.0');

registerScaffoldTool(program);

program.parseAsync(process.argv).catch((err: unknown) => {
  const msg = err instanceof Error ? err.message : String(err);
  // eslint-disable-next-line no-console
  console.error(chalk.red(`papercrane-cli: ${msg}`));
  process.exit(1);
});
