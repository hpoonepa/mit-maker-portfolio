#!/usr/bin/env tsx
/**
 * Pulls the results of a benchmark run from Postgres and posts a compact
 * summary as a GitHub commit comment + (optional) Slack message.
 *
 * Invoked by the `finalize` job in each benchmark workflow after dispatch.
 */

import { parseArgs } from 'node:util';
import pg from 'pg';

interface Args {
  tier: string;
  runId: string;
  tool?: string;
  toolVersion?: string;
  targets?: string;
  publishZenodo: boolean;
}

function parseCli(argv: string[]): Args {
  const { values } = parseArgs({
    args: argv,
    options: {
      tier: { type: 'string' },
      'run-id': { type: 'string' },
      tool: { type: 'string' },
      'tool-version': { type: 'string' },
      targets: { type: 'string' },
      'publish-zenodo': { type: 'boolean', default: false },
    },
    strict: true,
    allowPositionals: false,
  });
  if (!values.tier) throw new Error('--tier required');
  if (!values['run-id']) throw new Error('--run-id required');
  return {
    tier: String(values.tier),
    runId: String(values['run-id']),
    tool: values.tool ? String(values.tool) : undefined,
    toolVersion: values['tool-version'] ? String(values['tool-version']) : undefined,
    targets: values.targets ? String(values.targets) : undefined,
    publishZenodo: Boolean(values['publish-zenodo']),
  };
}

interface Row {
  tool_id: string;
  tool_version: string;
  target_id: string;
  seeds_run: number;
  hit_rate: number | null;
  status: string;
  cost_usd: number;
  wallclock_sec: number;
}

async function fetchRows(dbUrl: string, runId: string): Promise<Row[]> {
  const pool = new pg.Pool({ connectionString: dbUrl, max: 2 });
  try {
    const { rows } = await pool.query<Row>(
      `SELECT tool_id, tool_version, target_id, seeds_run, hit_rate, status,
              cost_usd, wallclock_sec
         FROM "BenchmarkRun"
         WHERE run_id = $1
         ORDER BY tool_id, target_id`,
      [runId],
    );
    return rows;
  } finally {
    await pool.end();
  }
}

function renderMarkdown(args: Args, rows: Row[]): string {
  if (rows.length === 0) {
    return `### Benchmark \`${args.tier}\` run \`${args.runId}\`\n\n_No BenchmarkRun rows recorded._`;
  }

  const succeeded = rows.filter(r => r.status === 'succeeded');
  const failed = rows.filter(r => r.status === 'failed');
  const totalCost = rows.reduce((a, r) => a + Number(r.cost_usd ?? 0), 0);

  const lines: string[] = [];
  lines.push(`### Benchmark \`${args.tier}\` run \`${args.runId}\``);
  lines.push('');
  lines.push(`- Cells: **${rows.length}** total · ${succeeded.length} succeeded · ${failed.length} failed`);
  lines.push(`- Actual cost: **$${totalCost.toFixed(2)}**`);
  if (args.tool) lines.push(`- Tool: \`${args.tool}@${args.toolVersion ?? 'n/a'}\``);
  if (args.targets) lines.push(`- Targets: \`${args.targets}\``);
  lines.push('');
  lines.push('| Tool | Target | Hit rate | Seeds | Status | Cost |');
  lines.push('|---|---|---|---|---|---|');
  for (const r of rows) {
    const hit = r.hit_rate === null ? '—' : `${(Number(r.hit_rate) * 100).toFixed(1)}%`;
    lines.push(
      `| \`${r.tool_id}@${r.tool_version}\` | \`${r.target_id}\` | ${hit} | ${r.seeds_run} | ${r.status} | $${Number(r.cost_usd).toFixed(2)} |`,
    );
  }
  return lines.join('\n');
}

async function postGithubCommitComment(markdown: string) {
  const token = process.env.GITHUB_TOKEN;
  const repo = process.env.GITHUB_REPOSITORY;
  const sha = process.env.GITHUB_SHA;
  if (!token || !repo || !sha) {
    console.error('[report] missing GITHUB_TOKEN/GITHUB_REPOSITORY/GITHUB_SHA — skipping commit comment');
    return;
  }
  const url = `https://api.github.com/repos/${repo}/commits/${sha}/comments`;
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ body: markdown }),
  });
  if (!resp.ok) {
    console.error(`[report] commit comment failed: ${resp.status} ${await resp.text()}`);
  }
}

async function postSlack(markdown: string) {
  const webhook = process.env.SLACK_WEBHOOK_URL;
  if (!webhook) return;
  await fetch(webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: markdown.slice(0, 3800) }),
  }).catch(err => console.error(`[report] slack post failed: ${(err as Error).message}`));
}

async function publishZenodoSnapshot(args: Args, rows: Row[]) {
  const token = process.env.ZENODO_TOKEN;
  if (!token) {
    console.error('[report] ZENODO_TOKEN missing — skipping publish');
    return;
  }
  console.error(`[report] would publish ${rows.length} cells from run ${args.runId} to Zenodo (impl pending)`);
  // Real impl: create deposition, upload summary JSON + PDB tarballs, publish.
}

async function main() {
  const args = parseCli(process.argv.slice(2));
  const dbUrl = process.env.DATABASE_URL;
  if (!dbUrl) { console.error('DATABASE_URL missing'); process.exit(1); }

  const rows = await fetchRows(dbUrl, args.runId);
  const markdown = renderMarkdown(args, rows);

  // Always print to stdout for workflow logs
  process.stdout.write(markdown + '\n');

  await Promise.all([
    postGithubCommitComment(markdown),
    postSlack(markdown),
  ]);

  if (args.publishZenodo) {
    await publishZenodoSnapshot(args, rows);
  }
}

const isDirect = import.meta.url === `file://${process.argv[1]}`;
if (isDirect) {
  main().catch(err => { console.error(err); process.exit(1); });
}

export { parseCli, renderMarkdown };
