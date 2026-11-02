/**
 * Interactive prompt flow for `papercrane-cli scaffold-tool <name>`.
 *
 * Kept isolated from the command so unit tests can stub it out and scripted
 * callers can bypass prompts entirely by passing a pre-built `ScaffoldContext`
 * into `generateScaffold()`.
 */
import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import prompts from 'prompts';

export type Category =
  | 'binder_design'
  | 'sequence_design'
  | 'structure_prediction'
  | 'backbone_generation'
  | 'embedding_scoring';

export type Tier = 'open' | 'open-weights' | 'frontier';

export type Gpu = 'A10' | 'A100-40GB' | 'A100-80GB' | 'H100';

export const CATEGORIES: readonly Category[] = [
  'binder_design',
  'sequence_design',
  'structure_prediction',
  'backbone_generation',
  'embedding_scoring',
];

export const TIERS: readonly Tier[] = ['open', 'open-weights', 'frontier'];

export const GPUS: readonly Gpu[] = ['A10', 'A100-40GB', 'A100-80GB', 'H100'];

export interface ScaffoldAnswers {
  displayName: string;
  category: Category;
  tier: Tier;
  license: string;
  gpu: Gpu;
  memoryGb: number;
  estSeconds: number;
  upstreamRepo: string;
  composes: string[];
}

function defaultDisplayName(slug: string): string {
  // "my-new-tool" -> "MyNewTool"
  return slug
    .split('-')
    .filter((part) => part.length > 0)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}

/**
 * Enumerate existing tool ids under `tools/` so we can offer them as
 * multi-select choices for the `composes` field.
 */
export function listExistingTools(repoRoot: string): string[] {
  const toolsDir = join(repoRoot, 'tools');
  try {
    return readdirSync(toolsDir)
      .filter((name) => {
        if (name.startsWith('.') || name.startsWith('_')) return false;
        try {
          return statSync(join(toolsDir, name)).isDirectory();
        } catch {
          return false;
        }
      })
      .sort();
  } catch {
    return [];
  }
}

export interface PromptOptions {
  slug: string;
  repoRoot: string;
  /** Override the prompts implementation for tests. */
  promptsImpl?: typeof prompts;
}

export async function promptScaffoldAnswers(
  opts: PromptOptions,
): Promise<ScaffoldAnswers> {
  const impl = opts.promptsImpl ?? prompts;
  const existing = listExistingTools(opts.repoRoot);

  const onCancel = (): void => {
    throw new Error('scaffold cancelled by user');
  };

  const answers = await impl(
    [
      {
        type: 'text',
        name: 'displayName',
        message: 'Display name',
        initial: defaultDisplayName(opts.slug),
      },
      {
        type: 'select',
        name: 'category',
        message: 'Category',
        choices: CATEGORIES.map((c) => ({ title: c, value: c })),
        initial: 0,
      },
      {
        type: 'select',
        name: 'tier',
        message: 'Tier',
        choices: TIERS.map((t) => ({ title: t, value: t })),
        initial: 0,
      },
      {
        type: 'text',
        name: 'license',
        message: 'License',
        initial: 'MIT',
      },
      {
        type: 'select',
        name: 'gpu',
        message: 'GPU type',
        choices: GPUS.map((g) => ({ title: g, value: g })),
        initial: 1, // default A100-40GB
      },
      {
        type: 'number',
        name: 'memoryGb',
        message: 'Memory (GB)',
        initial: 16,
        min: 1,
        max: 1024,
      },
      {
        type: 'number',
        name: 'estSeconds',
        message: 'Estimated seconds per design',
        initial: 60,
        min: 1,
        max: 86_400,
      },
      {
        type: 'text',
        name: 'upstreamRepo',
        message: 'Upstream repo URL',
        validate: (v: string): true | string =>
          /^https?:\/\/\S+$/.test(v.trim()) || 'must be a http(s) URL',
      },
      {
        type: existing.length > 0 ? 'multiselect' : null,
        name: 'composes',
        message: 'Composes (tools this one calls internally)',
        choices: existing.map((id) => ({ title: id, value: id })),
        hint: '- space to select, enter to submit',
        instructions: false,
      },
    ],
    { onCancel },
  );

  // prompts returns partial answers on cancel; onCancel throws so we should be
  // safe here, but guard anyway to keep TypeScript narrow.
  if (!answers.displayName || !answers.category || !answers.tier) {
    throw new Error('scaffold cancelled by user');
  }

  return {
    displayName: String(answers.displayName).trim(),
    category: answers.category as Category,
    tier: answers.tier as Tier,
    license: String(answers.license ?? 'MIT').trim() || 'MIT',
    gpu: answers.gpu as Gpu,
    memoryGb: Number(answers.memoryGb ?? 16),
    estSeconds: Number(answers.estSeconds ?? 60),
    upstreamRepo: String(answers.upstreamRepo ?? '').trim(),
    composes: Array.isArray(answers.composes) ? (answers.composes as string[]) : [],
  };
}
