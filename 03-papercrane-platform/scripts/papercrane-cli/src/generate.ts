/**
 * Walk `src/templates/`, render every `*.hbs` file with Handlebars, and write
 * the result to `tools/<slug>/` (stripping the `.hbs` suffix). Non-`.hbs`
 * files are copied verbatim.
 */
import {
  copyFileSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import Handlebars from 'handlebars';

import type { Category, Gpu, ScaffoldAnswers, Tier } from './prompts.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/** Where the template tree lives, relative to this file. */
export const TEMPLATE_ROOT = join(__dirname, 'templates');

/** Rendering context — every variable referenced in `*.hbs` must live here. */
export interface ScaffoldContext {
  id: string;
  displayName: string;
  category: Category;
  tier: Tier;
  license: string;
  gpu: Gpu;
  memoryGb: number;
  estSeconds: number;
  upstreamRepo: string;
  composes: string[];
  /** Placeholder SHA — real value is set by CI when the image is built. */
  shaPlaceholder: string;
  /** Python class name derived from display name, e.g. "MyNewToolAdapter". */
  adapterClassName: string;
  /** ISO date of generation — stamped into generated README. */
  generatedAt: string;
}

/**
 * Build a full render context from `ScaffoldAnswers` + the slug. Pure function
 * — callable from tests without mocking anything.
 */
export function buildContext(
  slug: string,
  answers: ScaffoldAnswers,
  opts: { now?: Date } = {},
): ScaffoldContext {
  const now = opts.now ?? new Date();
  const adapterClassName = `${answers.displayName.replace(/[^A-Za-z0-9]/g, '')}Adapter`;
  return {
    id: slug,
    displayName: answers.displayName,
    category: answers.category,
    tier: answers.tier,
    license: answers.license,
    gpu: answers.gpu,
    memoryGb: answers.memoryGb,
    estSeconds: answers.estSeconds,
    upstreamRepo: answers.upstreamRepo,
    composes: [...answers.composes],
    shaPlaceholder: 'TODO',
    adapterClassName,
    generatedAt: now.toISOString().slice(0, 10),
  };
}

export interface GenerateOptions {
  /** Target directory for the scaffold — usually `<repoRoot>/tools/<slug>`. */
  targetDir: string;
  /** Override the template source dir (tests point this at a fixture). */
  templateRoot?: string;
}

export interface GenerateResult {
  /** Absolute paths of every file written. */
  written: string[];
}

/**
 * Walk `templateRoot` recursively, render each file into `targetDir`.
 *
 * - Files ending in `.hbs` are treated as Handlebars templates and rendered
 *   with `context`; the output path strips the `.hbs` suffix.
 * - All other files (plain fixtures like `target.pdb`, `requirements-dev.txt`)
 *   are copied verbatim.
 */
export function generateScaffold(
  context: ScaffoldContext,
  opts: GenerateOptions,
): GenerateResult {
  const templateRoot = opts.templateRoot ?? TEMPLATE_ROOT;
  mkdirSync(opts.targetDir, { recursive: true });

  const written: string[] = [];
  walk(templateRoot, (absSrc) => {
    const rel = relative(templateRoot, absSrc);
    const isTemplate = rel.endsWith('.hbs');
    const destRel = isTemplate ? rel.slice(0, -'.hbs'.length) : rel;
    const destAbs = join(opts.targetDir, destRel);
    mkdirSync(dirname(destAbs), { recursive: true });

    if (isTemplate) {
      const src = readFileSync(absSrc, 'utf8');
      const compiled = Handlebars.compile(src, { noEscape: true });
      const rendered = compiled(context);
      writeFileSync(destAbs, rendered);
    } else {
      copyFileSync(absSrc, destAbs);
    }
    written.push(destAbs);
  });

  return { written };
}

/** Recursive directory walker yielding absolute file paths in sorted order. */
function walk(root: string, visit: (absPath: string) => void): void {
  const entries = readdirSync(root).sort();
  for (const name of entries) {
    const abs = join(root, name);
    const st = statSync(abs);
    if (st.isDirectory()) {
      walk(abs, visit);
    } else if (st.isFile()) {
      visit(abs);
    }
  }
}
