/**
 * `papercrane-cli scaffold-tool <name>` — create a working tool adapter
 * skeleton under `tools/<name>/`.
 *
 * Flow:
 *   1. Validate the slug and refuse collisions.
 *   2. Prompt for display name, category, tier, license, GPU profile,
 *      memory, seconds/design, upstream repo, and existing tools to compose.
 *   3. Render the Handlebars templates into `tools/<slug>/`.
 *   4. Print next-step commands.
 */
import { resolve } from 'node:path';

import chalk from 'chalk';
import type { Command } from 'commander';

import { buildContext, generateScaffold } from '../generate.js';
import { promptScaffoldAnswers } from '../prompts.js';
import { validateToolName } from '../validate.js';

export interface ScaffoldCommandOptions {
  /** Repo root override — defaults to `process.cwd()`. */
  cwd?: string;
}

export function registerScaffoldTool(program: Command): void {
  program
    .command('scaffold-tool')
    .argument('<name>', 'tool id (slug) — lowercase, digits, hyphens')
    .description('Create a new tool adapter under `tools/<name>/`.')
    .option(
      '-C, --cwd <dir>',
      'override repo root (defaults to process.cwd())',
    )
    .action(async (name: string, opts: { cwd?: string }) => {
      const repoRoot = resolve(opts.cwd ?? process.cwd());
      const slug = validateToolName(name, { repoRoot });

      // eslint-disable-next-line no-console
      console.log(chalk.cyan(`\nscaffolding tool "${slug}" in ${repoRoot}/tools/${slug}\n`));

      const answers = await promptScaffoldAnswers({ slug, repoRoot });
      const context = buildContext(slug, answers);
      const targetDir = resolve(repoRoot, 'tools', slug);
      const { written } = generateScaffold(context, { targetDir });

      // eslint-disable-next-line no-console
      console.log(chalk.green(`\nwrote ${written.length} files:`));
      for (const path of written) {
        // eslint-disable-next-line no-console
        console.log(`  ${chalk.dim(path)}`);
      }

      // eslint-disable-next-line no-console
      console.log(chalk.bold('\nnext steps:'));
      // eslint-disable-next-line no-console
      console.log(`  ${chalk.yellow(`cd tools/${slug}`)}`);
      // eslint-disable-next-line no-console
      console.log(`  ${chalk.yellow('pip install -r requirements-dev.txt')}`);
      // eslint-disable-next-line no-console
      console.log(`  ${chalk.yellow('pytest')}`);
      // eslint-disable-next-line no-console
      console.log(`  ${chalk.yellow('docker build .')}`);
    });
}
