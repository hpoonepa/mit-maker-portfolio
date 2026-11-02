#!/usr/bin/env tsx
/**
 * generate-assets.ts
 *
 * CLI that regenerates all preprint assets from the current leaderboard:
 *   - figures/hitrate-grid.pdf       (bar chart, one facet per target)
 *   - figures/cost-per-hit.pdf       (scatter / bar, log $ axis)
 *   - figures/methodology-flow.pdf   (node-link methodology diagram)
 *   - tables/results.tex             (auto-generated LaTeX booktabs table)
 *   - data/leaderboard-snapshot.json (for the Zenodo data package)
 *
 * Usage:
 *   pnpm build:assets                 # pulls from DATABASE_URL
 *   pnpm build:assets -- --dry-run    # uses FIXTURE_LEADERBOARD (no DB needed)
 *
 * Env:
 *   DATABASE_URL   Postgres connection string (required unless --dry-run)
 *   OUT_DIR        Override output root (defaults to this file's dir)
 *
 * NOTE: We deliberately keep the PDF rendering pipeline abstracted behind
 * `renderVegaToPdf` so that in unit tests we can stub it out to "touch"
 * an empty PDF instead of invoking the heavy vega runtime. The CI worker
 * installs the full dependency set and gets real PDFs.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';

// ---------------------------------------------------------------------------
// Types + schema
// ---------------------------------------------------------------------------

export const LeaderboardRowSchema = z.object({
  target_id: z.string(),
  target_name: z.string(),
  tool_id: z.string(),
  tool_name: z.string(),
  tool_version: z.string(),
  hits: z.number().int().nonnegative(),
  total_designs: z.number().int().positive(),
  hit_rate: z.number().min(0).max(1),
  cost_usd: z.number().nonnegative(),
  cost_per_hit_usd: z.number().nonnegative(),
  ci_low: z.number().min(0).max(1),
  ci_high: z.number().min(0).max(1),
});

export type LeaderboardRow = z.infer<typeof LeaderboardRowSchema>;

// ---------------------------------------------------------------------------
// Fixture data (used for --dry-run, tests, and CI sanity checks)
// ---------------------------------------------------------------------------

export const FIXTURE_LEADERBOARD: LeaderboardRow[] = [
  {
    target_id: 'pd-l1',
    target_name: 'PD-L1',
    tool_id: 'bindcraft',
    tool_name: 'BindCraft',
    tool_version: '1.2.0',
    hits: 14,
    total_designs: 60,
    hit_rate: 0.233,
    cost_usd: 48.5,
    cost_per_hit_usd: 3.46,
    ci_low: 0.14,
    ci_high: 0.35,
  },
  {
    target_id: 'pd-l1',
    target_name: 'PD-L1',
    tool_id: 'rfdiffusion_mpnn_af3',
    tool_name: 'RFdiffusion + ProteinMPNN + AF3',
    tool_version: '2025.03',
    hits: 9,
    total_designs: 60,
    hit_rate: 0.15,
    cost_usd: 120.0,
    cost_per_hit_usd: 13.33,
    ci_low: 0.07,
    ci_high: 0.26,
  },
  {
    target_id: 'rbd',
    target_name: 'SARS-CoV-2 RBD',
    tool_id: 'bindcraft',
    tool_name: 'BindCraft',
    tool_version: '1.2.0',
    hits: 7,
    total_designs: 60,
    hit_rate: 0.117,
    cost_usd: 52.0,
    cost_per_hit_usd: 7.43,
    ci_low: 0.05,
    ci_high: 0.23,
  },
  {
    target_id: 'rbd',
    target_name: 'SARS-CoV-2 RBD',
    tool_id: 'rfdiffusion_mpnn_af3',
    tool_name: 'RFdiffusion + ProteinMPNN + AF3',
    tool_version: '2025.03',
    hits: 3,
    total_designs: 60,
    hit_rate: 0.05,
    cost_usd: 125.0,
    cost_per_hit_usd: 41.67,
    ci_low: 0.01,
    ci_high: 0.14,
  },
  {
    target_id: 'il7ra',
    target_name: 'IL-7R$\\alpha$',
    tool_id: 'bindcraft',
    tool_name: 'BindCraft',
    tool_version: '1.2.0',
    hits: 2,
    total_designs: 60,
    hit_rate: 0.033,
    cost_usd: 55.0,
    cost_per_hit_usd: 27.5,
    ci_low: 0.004,
    ci_high: 0.12,
  },
  {
    target_id: 'il7ra',
    target_name: 'IL-7R$\\alpha$',
    tool_id: 'rfdiffusion_mpnn_af3',
    tool_name: 'RFdiffusion + ProteinMPNN + AF3',
    tool_version: '2025.03',
    hits: 1,
    total_designs: 60,
    hit_rate: 0.017,
    cost_usd: 130.0,
    cost_per_hit_usd: 130.0,
    ci_low: 0.0,
    ci_high: 0.09,
  },
];

// ---------------------------------------------------------------------------
// LaTeX helpers
// ---------------------------------------------------------------------------

/**
 * Escape LaTeX special characters.
 * NOTE: backslash must be replaced FIRST so we don't double-escape the
 * replacement tokens we emit for the other special chars.
 */
export function escapeLatex(input: string): string {
  if (!input) return '';
  const backslashPlaceholder = '\u0000';
  return input
    .replace(/\\/g, backslashPlaceholder)
    .replace(/&/g, '\\&')
    .replace(/%/g, '\\%')
    .replace(/\$/g, '\\$')
    .replace(/#/g, '\\#')
    .replace(/_/g, '\\_')
    .replace(/\{/g, '\\{')
    .replace(/\}/g, '\\}')
    .replace(/~/g, '\\textasciitilde{}')
    .replace(/\^/g, '\\textasciicircum{}')
    .replaceAll(backslashPlaceholder, '\\textbackslash{}');
}

export function renderResultsTable(rows: LeaderboardRow[]): string {
  const header = [
    '% Auto-generated by benchmark/preprint/generate-assets.ts — DO NOT EDIT BY HAND.',
    '\\begin{table}[h]',
    '\\centering',
    '\\small',
    '\\caption{Hit rates and cost-per-hit by target and tool. Values are the current Paper Crane leaderboard; confidence intervals are 95\\% Wilson bootstrap. See Methodology v1.0 for the hit definition.}',
    '\\label{tab:results}',
    '\\begin{tabular}{llrrrr}',
    '\\toprule',
    'Target & Tool (version) & Hits / N & Hit rate (\\%) & 95\\% CI & Cost/hit (USD) \\\\',
    '\\midrule',
  ];

  const body = rows.map((r) => {
    const target = escapeLatex(r.target_name);
    const tool = `${escapeLatex(r.tool_name)} (${escapeLatex(r.tool_version)})`;
    const hitRatePct = (r.hit_rate * 100).toFixed(1);
    const ciLow = (r.ci_low * 100).toFixed(1);
    const ciHigh = (r.ci_high * 100).toFixed(1);
    const costPerHit = `\\$${r.cost_per_hit_usd.toFixed(2)}`;
    return `${target} & ${tool} & ${r.hits}/${r.total_designs} & ${hitRatePct} & [${ciLow}, ${ciHigh}] & ${costPerHit} \\\\`;
  });

  const footer = [
    '\\bottomrule',
    '\\end{tabular}',
    '\\end{table}',
    '',
  ];

  return [...header, ...body, ...footer].join('\n');
}

// ---------------------------------------------------------------------------
// Vega-Lite spec builders
// ---------------------------------------------------------------------------

// Intentionally typed as `Record<string, unknown>` — a full vega-lite TopLevelSpec
// type would pull the vega-lite types into every consumer; for our purposes we
// just need a plain JSON-shaped object.
type VLSpec = Record<string, unknown>;

const VL_SCHEMA = 'https://vega.github.io/schema/vega-lite/v5.json';

export function buildHitRateGridSpec(rows: LeaderboardRow[]): VLSpec {
  return {
    $schema: VL_SCHEMA,
    description: 'Hit rate per target and tool.',
    data: { values: rows },
    width: 540,
    height: 220,
    mark: { type: 'bar', tooltip: true },
    encoding: {
      x: { field: 'target_name', type: 'nominal', title: 'Target' },
      xOffset: { field: 'tool_name' },
      y: { field: 'hit_rate', type: 'quantitative', title: 'Hit rate', axis: { format: '.0%' } },
      color: { field: 'tool_name', type: 'nominal', title: 'Tool' },
      tooltip: [
        { field: 'target_name', type: 'nominal' },
        { field: 'tool_name', type: 'nominal' },
        { field: 'hits', type: 'quantitative' },
        { field: 'total_designs', type: 'quantitative' },
        { field: 'hit_rate', type: 'quantitative', format: '.1%' },
      ],
    },
  };
}

export function buildCostPerHitSpec(rows: LeaderboardRow[]): VLSpec {
  return {
    $schema: VL_SCHEMA,
    description: 'Cost per hit (USD, log scale) by tool and target.',
    data: { values: rows },
    mark: { type: 'circle', size: 120, tooltip: true },
    encoding: {
      x: { field: 'tool_name', type: 'nominal', title: 'Tool', axis: { labelAngle: -45 } },
      y: {
        field: 'cost_per_hit_usd',
        type: 'quantitative',
        title: 'Cost per hit (USD, log)',
        scale: { type: 'log' },
      },
      color: { field: 'target_name', type: 'nominal', title: 'Target' },
      tooltip: [
        { field: 'target_name', type: 'nominal' },
        { field: 'tool_name', type: 'nominal' },
        { field: 'cost_per_hit_usd', type: 'quantitative', format: '$.2f' },
      ],
    },
  };
}

export function buildMethodologyFlowSpec(): VLSpec {
  // Simple node-link diagram rendered via two layered rule+text marks.
  // In production this is replaced with a richer diagram, but a simple
  // flow covers the preprint's Figure 3 slot.
  const nodes = [
    { id: 'targets', x: 1, y: 1, label: 'Targets (PDB + hotspots)' },
    { id: 'tools', x: 2, y: 1, label: 'Tool catalog (12 tools)' },
    { id: 'dispatch', x: 3, y: 1, label: 'Vast.ai dispatcher' },
    { id: 'predict', x: 4, y: 1, label: 'Structure prediction (Boltz-2 / AF3)' },
    { id: 'metrics', x: 5, y: 1, label: 'Metrics: ipSAE, DockQ, pTMEnergy' },
    { id: 'leaderboard', x: 6, y: 1, label: 'Public leaderboard' },
  ];
  const edges = [
    { from: 'targets', to: 'dispatch' },
    { from: 'tools', to: 'dispatch' },
    { from: 'dispatch', to: 'predict' },
    { from: 'predict', to: 'metrics' },
    { from: 'metrics', to: 'leaderboard' },
  ];
  return {
    $schema: VL_SCHEMA,
    description: 'Paper Crane benchmark methodology flow.',
    width: 720,
    height: 160,
    data: { values: nodes },
    layer: [
      {
        mark: { type: 'rect', cornerRadius: 6, stroke: 'black', fill: '#f4f4f4' },
        encoding: {
          x: { field: 'x', type: 'quantitative', axis: null },
          y: { field: 'y', type: 'quantitative', axis: null },
        },
      },
      {
        mark: { type: 'text', fontSize: 11 },
        encoding: {
          x: { field: 'x', type: 'quantitative' },
          y: { field: 'y', type: 'quantitative' },
          text: { field: 'label', type: 'nominal' },
        },
      },
    ],
    // edges are a second data source; kept inline so the spec is a single unit
    // (vega-lite doesn't natively do DAG layout, so this is a hand-placed flow)
    params: [{ name: 'edges', value: edges }],
  };
}

// ---------------------------------------------------------------------------
// PDF rendering (real in CI, stubbed under --dry-run)
// ---------------------------------------------------------------------------

async function renderVegaToPdf(
  spec: VLSpec,
  outPath: string,
  opts: { dryRun: boolean },
): Promise<void> {
  if (opts.dryRun) {
    // Emit a minimal valid one-page PDF so downstream LaTeX includes don't crash.
    // This is intentionally tiny — real renders happen under `make assets`.
    const stub = Buffer.from(
      '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n' +
        '2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n' +
        'xref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000055 00000 n \n' +
        'trailer<</Size 3/Root 1 0 R>>\nstartxref\n100\n%%EOF\n',
      'utf8',
    );
    writeFileSync(outPath, stub);
    return;
  }

  // Full path: compile vega-lite → vega → SVG → PDF.
  // vega does not natively emit PDF; we emit SVG and let the CI worker
  // convert via `rsvg-convert` (installed by the Makefile `assets` target).
  // We emit the SVG alongside the PDF path with a `.svg` suffix — the
  // Makefile handles conversion. This keeps the JS dependency surface small.
  // NOTE: We do the dynamic imports inside the function so tests can stub
  // this whole function out via `opts.dryRun = true`.
  const [{ compile }, vega] = await Promise.all([
    import('vega-lite'),
    import('vega'),
  ]);
  const compiled = compile(spec as never).spec;
  const runtime = vega.parse(compiled);
  const view = new vega.View(runtime, { renderer: 'none' }).initialize();
  const svg = await view.toSVG();
  const svgPath = outPath.replace(/\.pdf$/, '.svg');
  writeFileSync(svgPath, svg, 'utf8');
  // Write a placeholder PDF — Makefile converts .svg → .pdf via rsvg-convert.
  writeFileSync(outPath, Buffer.alloc(0));
}

// ---------------------------------------------------------------------------
// DB loader
// ---------------------------------------------------------------------------

const LEADERBOARD_SQL = `
  SELECT
    t.target_id,
    t.display_name        AS target_name,
    tl.tool_id,
    tl.display_name       AS tool_name,
    tl.version            AS tool_version,
    br.hits,
    br.total_designs,
    br.hit_rate,
    br.cost_usd,
    br.cost_per_hit_usd,
    br.ci_low,
    br.ci_high
  FROM benchmark_runs br
  JOIN tools   tl ON tl.tool_id   = br.tool_id
  JOIN targets t  ON t.target_id  = br.target_id
  WHERE br.status = 'complete'
    AND br.benchmark_version = $1
  ORDER BY t.target_id ASC, br.hit_rate DESC
`;

async function loadLeaderboardFromDb(benchmarkVersion: string): Promise<LeaderboardRow[]> {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error('DATABASE_URL is required when --dry-run is not set.');
  }
  // Dynamic import so tests don't need `pg` installed.
  const { Client } = await import('pg');
  const client = new Client({ connectionString });
  await client.connect();
  try {
    const result = await client.query(LEADERBOARD_SQL, [benchmarkVersion]);
    return result.rows.map((r) => LeaderboardRowSchema.parse(r));
  } finally {
    await client.end();
  }
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

export interface GenerateAssetsOptions {
  dryRun: boolean;
  outDir: string;
  rows?: LeaderboardRow[];
  benchmarkVersion?: string;
}

export async function generateAssets(opts: GenerateAssetsOptions): Promise<void> {
  const benchmarkVersion = opts.benchmarkVersion ?? '1.0';
  const rows =
    opts.rows ??
    (opts.dryRun ? FIXTURE_LEADERBOARD : await loadLeaderboardFromDb(benchmarkVersion));

  // Ensure output dirs exist
  const figuresDir = join(opts.outDir, 'figures');
  const tablesDir = join(opts.outDir, 'tables');
  const dataDir = join(opts.outDir, 'data');
  mkdirSync(figuresDir, { recursive: true });
  mkdirSync(tablesDir, { recursive: true });
  mkdirSync(dataDir, { recursive: true });

  // Figures
  await renderVegaToPdf(
    buildHitRateGridSpec(rows),
    join(figuresDir, 'hitrate-grid.pdf'),
    { dryRun: opts.dryRun },
  );
  await renderVegaToPdf(
    buildCostPerHitSpec(rows),
    join(figuresDir, 'cost-per-hit.pdf'),
    { dryRun: opts.dryRun },
  );
  await renderVegaToPdf(
    buildMethodologyFlowSpec(),
    join(figuresDir, 'methodology-flow.pdf'),
    { dryRun: opts.dryRun },
  );

  // LaTeX table
  writeFileSync(join(tablesDir, 'results.tex'), renderResultsTable(rows), 'utf8');

  // JSON snapshot for Zenodo
  const snapshot = {
    generated_at: new Date().toISOString(),
    benchmark_version: benchmarkVersion,
    row_count: rows.length,
    rows,
  };
  writeFileSync(
    join(dataDir, 'leaderboard-snapshot.json'),
    JSON.stringify(snapshot, null, 2),
    'utf8',
  );
}

// ---------------------------------------------------------------------------
// CLI wrapper
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const dryRun = argv.includes('--dry-run');

  const here = dirname(fileURLToPath(import.meta.url));
  const outDir = process.env.OUT_DIR ? resolve(process.env.OUT_DIR) : here;

  await generateAssets({ dryRun, outDir });

  // eslint-disable-next-line no-console
  console.log(`[preprint] assets written to ${outDir} (dryRun=${dryRun})`);
}

// Only run main when invoked directly (not when imported by tests)
const isDirectInvocation =
  typeof process !== 'undefined' &&
  process.argv[1] &&
  fileURLToPath(import.meta.url) === resolve(process.argv[1]);

if (isDirectInvocation) {
  main().catch((err) => {
    // eslint-disable-next-line no-console
    console.error(err);
    process.exit(1);
  });
}
