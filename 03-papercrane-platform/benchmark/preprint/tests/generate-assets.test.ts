import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  FIXTURE_LEADERBOARD,
  buildHitRateGridSpec,
  buildCostPerHitSpec,
  buildMethodologyFlowSpec,
  escapeLatex,
  generateAssets,
  renderResultsTable,
  type LeaderboardRow,
} from '../generate-assets';

describe('escapeLatex', () => {
  it('escapes LaTeX special characters to avoid table corruption', () => {
    expect(escapeLatex('foo & bar')).toBe('foo \\& bar');
    expect(escapeLatex('50% success')).toBe('50\\% success');
    expect(escapeLatex('a_b_c')).toBe('a\\_b\\_c');
    expect(escapeLatex('#1 tool')).toBe('\\#1 tool');
    expect(escapeLatex('path\\to\\file')).toBe('path\\textbackslash{}to\\textbackslash{}file');
    expect(escapeLatex('price $5')).toBe('price \\$5');
    expect(escapeLatex('a{b}c')).toBe('a\\{b\\}c');
    expect(escapeLatex('a~b^c')).toBe('a\\textasciitilde{}b\\textasciicircum{}c');
  });

  it('handles empty and plain strings unchanged', () => {
    expect(escapeLatex('')).toBe('');
    expect(escapeLatex('plain text 123')).toBe('plain text 123');
  });
});

describe('renderResultsTable', () => {
  it('produces a valid booktabs LaTeX table with escaped content', () => {
    const rows: LeaderboardRow[] = [
      {
        target_id: 'pd-l1',
        target_name: 'PD-L1',
        tool_id: 'bindcraft',
        tool_name: 'BindCraft',
        tool_version: '1.2.0',
        hits: 12,
        total_designs: 60,
        hit_rate: 0.2,
        cost_usd: 48.5,
        cost_per_hit_usd: 4.04,
        ci_low: 0.11,
        ci_high: 0.31,
      },
      {
        target_id: 'rbd',
        target_name: 'SARS-CoV-2 RBD',
        tool_id: 'rfdiffusion_mpnn_af3',
        tool_name: 'RFdiffusion + ProteinMPNN + AF3',
        tool_version: '2025.03',
        hits: 5,
        total_designs: 100,
        hit_rate: 0.05,
        cost_usd: 210.0,
        cost_per_hit_usd: 42.0,
        ci_low: 0.02,
        ci_high: 0.11,
      },
    ];

    const latex = renderResultsTable(rows);

    expect(latex).toContain('\\begin{table}');
    expect(latex).toContain('\\begin{tabular}');
    expect(latex).toContain('\\toprule');
    expect(latex).toContain('\\midrule');
    expect(latex).toContain('\\bottomrule');
    expect(latex).toContain('\\end{tabular}');
    expect(latex).toContain('\\end{table}');

    // Caption and label
    expect(latex).toContain('\\caption{');
    expect(latex).toContain('\\label{tab:results}');

    // Contents — names present, version escaped (underscores)
    expect(latex).toContain('BindCraft');
    expect(latex).toContain('RFdiffusion + ProteinMPNN + AF3');
    expect(latex).toContain('PD-L1');
    expect(latex).toContain('SARS-CoV-2 RBD');

    // Numeric formatting (hit rate as percent, dollars)
    expect(latex).toContain('20.0');
    expect(latex).toContain('\\$4.04');
  });

  it('handles tool names with special LaTeX characters', () => {
    const rows: LeaderboardRow[] = [
      {
        target_id: 't1',
        target_name: 'Target_1',
        tool_id: 'tool_x',
        tool_name: 'Tool_X & Friends',
        tool_version: '1.0%beta',
        hits: 1,
        total_designs: 10,
        hit_rate: 0.1,
        cost_usd: 5,
        cost_per_hit_usd: 5,
        ci_low: 0,
        ci_high: 0.4,
      },
    ];
    const latex = renderResultsTable(rows);
    expect(latex).toContain('Tool\\_X \\& Friends');
    expect(latex).toContain('Target\\_1');
    expect(latex).toContain('1.0\\%beta');
  });
});

describe('vega-lite spec builders', () => {
  it('builds a valid hit-rate grid spec with one mark per target', () => {
    const spec = buildHitRateGridSpec(FIXTURE_LEADERBOARD);
    expect(spec.$schema).toMatch(/vega-lite/);
    expect(spec.mark).toBeDefined();
    // column/facet encoding for per-target grid
    expect(JSON.stringify(spec.encoding)).toContain('target_name');
    expect(spec.data).toBeDefined();
  });

  it('builds a cost-per-hit spec with log scale on dollars', () => {
    const spec = buildCostPerHitSpec(FIXTURE_LEADERBOARD);
    expect(spec.$schema).toMatch(/vega-lite/);
    expect(JSON.stringify(spec.encoding)).toContain('cost_per_hit_usd');
  });

  it('builds a methodology flow spec (static node-link diagram)', () => {
    const spec = buildMethodologyFlowSpec();
    expect(spec.$schema).toMatch(/vega-lite/);
    expect(spec.data).toBeDefined();
  });
});

describe('generateAssets (dry-run with fixture data)', () => {
  let outDir: string;

  beforeEach(() => {
    outDir = mkdtempSync(join(tmpdir(), 'papercrane-preprint-'));
  });

  afterEach(() => {
    rmSync(outDir, { recursive: true, force: true });
  });

  it('writes all artifact files to outDir', async () => {
    await generateAssets({
      dryRun: true,
      outDir,
      rows: FIXTURE_LEADERBOARD,
    });

    expect(existsSync(join(outDir, 'figures', 'hitrate-grid.pdf'))).toBe(true);
    expect(existsSync(join(outDir, 'figures', 'cost-per-hit.pdf'))).toBe(true);
    expect(existsSync(join(outDir, 'figures', 'methodology-flow.pdf'))).toBe(true);
    expect(existsSync(join(outDir, 'tables', 'results.tex'))).toBe(true);
    expect(existsSync(join(outDir, 'data', 'leaderboard-snapshot.json'))).toBe(true);
  });

  it('writes a valid JSON snapshot with metadata and rows', async () => {
    await generateAssets({
      dryRun: true,
      outDir,
      rows: FIXTURE_LEADERBOARD,
    });
    const snapshot = JSON.parse(
      readFileSync(join(outDir, 'data', 'leaderboard-snapshot.json'), 'utf8'),
    );
    expect(snapshot).toHaveProperty('generated_at');
    expect(snapshot).toHaveProperty('benchmark_version');
    expect(snapshot).toHaveProperty('rows');
    expect(Array.isArray(snapshot.rows)).toBe(true);
    expect(snapshot.rows.length).toBe(FIXTURE_LEADERBOARD.length);
  });

  it('writes a LaTeX results table that includes all fixture rows', async () => {
    await generateAssets({
      dryRun: true,
      outDir,
      rows: FIXTURE_LEADERBOARD,
    });
    const tex = readFileSync(join(outDir, 'tables', 'results.tex'), 'utf8');
    for (const row of FIXTURE_LEADERBOARD) {
      // target_name may contain special chars; check the escaped form
      expect(tex).toContain(escapeLatex(row.target_name));
    }
  });
});
