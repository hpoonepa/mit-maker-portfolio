#!/usr/bin/env tsx
/**
 * Drift detector for the continuous benchmark (plan 04 §3).
 *
 * For each (tool, target) pair, computes the trailing 4-week mean + stdev of
 * the weekly hit rate. If the *latest* weekly run is more than 2σ outside
 * that mean, opens a `benchmark-incident` GitHub issue and pages Slack (if
 * SLACK_WEBHOOK_URL is set).
 *
 * Pure helpers (`zScore`, `detectDrift`) are exported for vitest tests.
 */

import { parseArgs } from 'node:util';
import pg from 'pg';

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

export interface WeeklyPoint {
  weekStart: string; // ISO date (Monday)
  hitRate: number;   // 0..1
}

export interface DriftRow {
  toolId: string;
  targetId: string;
  history: WeeklyPoint[]; // length >= 4 (trailing 4 weeks + latest)
}

export interface DriftVerdict {
  toolId: string;
  targetId: string;
  latestHitRate: number;
  baselineMean: number;
  baselineStdev: number;
  zScore: number;
  drifted: boolean;
  direction: 'up' | 'down' | 'flat';
  weekStart: string;
}

// ----------------------------------------------------------------------------
// Pure helpers (tested)
// ----------------------------------------------------------------------------

export function mean(xs: number[]): number {
  if (xs.length === 0) return 0;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function stdev(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  const variance = xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1);
  return Math.sqrt(variance);
}

export function zScore(x: number, m: number, s: number): number {
  if (s === 0) return 0;
  return (x - m) / s;
}

/**
 * Detects drift given a (tool, target) time-series. Expects:
 *   - At least 4 trailing weekly points used for baseline
 *   - A 5th point representing the latest week
 * Returns a verdict with z-score and drift boolean.
 *
 * If fewer than 4 baseline points are available, returns drifted=false
 * (insufficient history — don't page on noise).
 */
export function detectDrift(row: DriftRow, zThreshold = 2): DriftVerdict | null {
  if (row.history.length < 5) return null; // need 4 baseline + 1 latest
  const sorted = [...row.history].sort((a, b) => a.weekStart.localeCompare(b.weekStart));
  const latest = sorted[sorted.length - 1]!;
  const baseline = sorted.slice(-5, -1); // last 4 full weeks before latest
  const baselineRates = baseline.map(p => p.hitRate);
  const m = mean(baselineRates);
  const s = stdev(baselineRates);
  const z = zScore(latest.hitRate, m, s);
  const drifted = Math.abs(z) > zThreshold;
  const direction: 'up' | 'down' | 'flat' = drifted
    ? (z > 0 ? 'up' : 'down')
    : 'flat';
  return {
    toolId: row.toolId,
    targetId: row.targetId,
    latestHitRate: latest.hitRate,
    baselineMean: m,
    baselineStdev: s,
    zScore: z,
    drifted,
    direction,
    weekStart: latest.weekStart,
  };
}

// ----------------------------------------------------------------------------
// DB fetch
// ----------------------------------------------------------------------------

/**
 * Returns up to 5 trailing weekly hit-rate points (one per ISO week)
 * for every (tool, target) pair that has weekly-tier runs.
 */
export async function loadHistory(dbUrl: string): Promise<DriftRow[]> {
  const pool = new pg.Pool({ connectionString: dbUrl, max: 2 });
  try {
    const { rows } = await pool.query<{
      tool_id: string;
      target_id: string;
      week_start: string;
      hit_rate: number | null;
    }>(
      `WITH weekly AS (
         SELECT tool_id,
                target_id,
                date_trunc('week', created_at)::date AS week_start,
                AVG(hit_rate) AS hit_rate
           FROM "BenchmarkRun"
          WHERE tier = 'full'
            AND status = 'succeeded'
            AND created_at >= NOW() - INTERVAL '8 weeks'
          GROUP BY tool_id, target_id, date_trunc('week', created_at)
       )
       SELECT tool_id, target_id, week_start::text AS week_start, hit_rate
         FROM weekly
        ORDER BY tool_id, target_id, week_start`,
    );

    const grouped = new Map<string, DriftRow>();
    for (const r of rows) {
      if (r.hit_rate === null) continue;
      const key = `${r.tool_id}::${r.target_id}`;
      if (!grouped.has(key)) {
        grouped.set(key, { toolId: r.tool_id, targetId: r.target_id, history: [] });
      }
      grouped.get(key)!.history.push({ weekStart: r.week_start, hitRate: Number(r.hit_rate) });
    }
    return [...grouped.values()].map(row => ({
      ...row,
      history: row.history.slice(-5),
    }));
  } finally {
    await pool.end();
  }
}

// ----------------------------------------------------------------------------
// Reporting (GitHub issue + Slack)
// ----------------------------------------------------------------------------

export function incidentTitle(v: DriftVerdict): string {
  return `benchmark-incident: ${v.toolId}/${v.targetId} drift ${v.weekStart}`;
}

export function incidentBody(v: DriftVerdict): string {
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
  const arrow = v.direction === 'up' ? 'UP' : v.direction === 'down' ? 'DOWN' : '~';
  return [
    `**Tool:** \`${v.toolId}\``,
    `**Target:** \`${v.targetId}\``,
    `**Week:** ${v.weekStart}`,
    '',
    `- Latest hit rate: **${pct(v.latestHitRate)}** (${arrow})`,
    `- 4-week baseline mean: ${pct(v.baselineMean)}`,
    `- 4-week baseline stdev: ${(v.baselineStdev * 100).toFixed(2)} pp`,
    `- z-score: **${v.zScore.toFixed(2)}**`,
    '',
    '## Action required',
    '',
    '1. Verify the container digest for this tool+target did not change unexpectedly.',
    '2. Diff the most recent tool release vs the previous one.',
    '3. If the drift is real, pin the previous version and investigate.',
    '4. If the drift is methodology-caused, fork a new methodology version (v1.x).',
    '',
    '_This issue was opened automatically by `scripts/benchmark/drift-detect.ts`._',
  ].join('\n');
}

async function openGithubIssue(v: DriftVerdict): Promise<void> {
  const token = process.env.GITHUB_TOKEN;
  const repo = process.env.GITHUB_REPOSITORY;
  if (!token || !repo) {
    console.error('[drift] missing GITHUB_TOKEN / GITHUB_REPOSITORY — skipping issue creation');
    return;
  }
  const resp = await fetch(`https://api.github.com/repos/${repo}/issues`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      title: incidentTitle(v),
      body: incidentBody(v),
      labels: ['benchmark', 'incident'],
    }),
  });
  if (!resp.ok) {
    console.error(`[drift] issue creation failed: ${resp.status} ${await resp.text()}`);
  }
}

async function pageSlack(v: DriftVerdict): Promise<void> {
  const webhook = process.env.SLACK_WEBHOOK_URL;
  if (!webhook) return;
  const text = [
    `:rotating_light: *benchmark drift* :rotating_light:`,
    `\`${v.toolId}\` / \`${v.targetId}\` — z=${v.zScore.toFixed(2)} (${v.direction})`,
    `latest ${(v.latestHitRate * 100).toFixed(1)}% vs 4wk mean ${(v.baselineMean * 100).toFixed(1)}%`,
  ].join('\n');
  await fetch(webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }).catch(err => console.error(`[drift] slack page failed: ${(err as Error).message}`));
}

// ----------------------------------------------------------------------------
// Main
// ----------------------------------------------------------------------------

interface Args {
  tier: string;
  zThreshold: number;
}

function parseCli(argv: string[]): Args {
  const { values } = parseArgs({
    args: argv,
    options: {
      tier: { type: 'string', default: 'full' },
      'z-threshold': { type: 'string', default: '2' },
    },
    strict: true,
    allowPositionals: false,
  });
  return {
    tier: String(values.tier),
    zThreshold: Number(values['z-threshold']),
  };
}

async function main() {
  const args = parseCli(process.argv.slice(2));
  const dbUrl = process.env.DATABASE_URL;
  if (!dbUrl) { console.error('DATABASE_URL missing'); process.exit(1); }

  const history = await loadHistory(dbUrl);
  console.error(`[drift] evaluating ${history.length} (tool,target) pairs (tier=${args.tier}, z>${args.zThreshold})`);

  const drifts: DriftVerdict[] = [];
  for (const row of history) {
    const verdict = detectDrift(row, args.zThreshold);
    if (verdict?.drifted) drifts.push(verdict);
  }

  if (drifts.length === 0) {
    console.error('[drift] no drift detected');
    return;
  }

  console.error(`[drift] ${drifts.length} drift(s) detected — opening issues + paging slack`);
  for (const v of drifts) {
    await openGithubIssue(v);
    await pageSlack(v);
  }
}

const isDirect = import.meta.url === `file://${process.argv[1]}`;
if (isDirect) {
  main().catch(err => { console.error(err); process.exit(1); });
}
