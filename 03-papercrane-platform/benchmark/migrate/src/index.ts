#!/usr/bin/env node
/**
 * Paper Crane benchmark migration CLI.
 *
 * Usage:
 *   pnpm migrate --source god-v3b --input ./path [--dry-run] [--database-url <url>]
 *
 * Emits a JSON summary to stdout:
 *   { runs_parsed, runs_inserted, runs_skipped, designs_inserted, errors[], dry_run }
 */

import { Command } from "commander";
import { Pool } from "pg";
import { allParsers, ALL_SOURCES, getParser } from "./parsers/index.js";
import {
  ensureSchema,
  loadRuns,
  type LoadResult,
  type LoaderLike,
} from "./loaders/postgres.js";
import {
  type BenchmarkRun,
  type MigrationSummary,
  MigrationSummarySchema,
} from "./schema.js";

interface CliOptions {
  source: string;
  input: string;
  dryRun?: boolean;
  databaseUrl?: string;
}

export async function runMigration(opts: CliOptions): Promise<MigrationSummary> {
  const errors: MigrationSummary["errors"] = [];
  const runs: BenchmarkRun[] = [];

  const parsers =
    opts.source === "all"
      ? allParsers()
      : [getParser(opts.source)];

  for (const parser of parsers) {
    try {
      const parsed = await parser.parse(opts.input);
      runs.push(...parsed);
    } catch (err) {
      errors.push({
        source: parser.sourceId,
        message: (err as Error).message,
      });
    }
  }

  let loadResult: LoadResult = {
    runs_inserted: 0,
    runs_skipped: 0,
    designs_inserted: 0,
  };

  if (!opts.dryRun) {
    const databaseUrl = opts.databaseUrl ?? process.env["DATABASE_URL"];
    if (!databaseUrl) {
      throw new Error(
        "DATABASE_URL is not set and --database-url was not provided. Pass --dry-run to parse without loading.",
      );
    }
    const pgPool = new Pool({ connectionString: databaseUrl });
    // pg.Pool's overloaded signatures are compatible with our narrow
    // `LoaderLike` interface at runtime; the cast silences TS overload noise.
    const pool = pgPool as unknown as LoaderLike;
    try {
      await ensureSchema(pool);
      loadResult = await loadRuns(pool, runs);
    } finally {
      await pgPool.end();
    }
  }

  const summary: MigrationSummary = {
    runs_parsed: runs.length,
    runs_inserted: loadResult.runs_inserted,
    runs_skipped: loadResult.runs_skipped,
    designs_inserted: loadResult.designs_inserted,
    errors,
    dry_run: Boolean(opts.dryRun),
  };
  return MigrationSummarySchema.parse(summary);
}

export function buildCli(): Command {
  const program = new Command();
  program
    .name("papercrane-migrate")
    .description(
      "Port historical Paper Crane campaign results into the leaderboard Postgres schema.",
    )
    .requiredOption(
      "--source <id>",
      `parser id: ${ALL_SOURCES.join(", ")}, or 'all'`,
    )
    .requiredOption("--input <path>", "input directory to walk recursively")
    .option("--dry-run", "parse + validate only; do not write to the database")
    .option(
      "--database-url <url>",
      "override DATABASE_URL env var (ignored with --dry-run)",
    )
    .action(async (rawOpts) => {
      const opts: CliOptions = {
        source: String(rawOpts.source),
        input: String(rawOpts.input),
        dryRun: Boolean(rawOpts.dryRun),
        databaseUrl: rawOpts.databaseUrl
          ? String(rawOpts.databaseUrl)
          : undefined,
      };
      try {
        const summary = await runMigration(opts);
        process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
      } catch (err) {
        process.stderr.write(`ERROR: ${(err as Error).message}\n`);
        process.exitCode = 1;
      }
    });
  return program;
}

// Only parse argv when run directly — tests import `runMigration`.
const invokedDirectly =
  import.meta.url === `file://${process.argv[1]}` ||
  process.argv[1]?.endsWith("/benchmark/migrate/src/index.ts") ||
  process.argv[1]?.endsWith("/benchmark/migrate/dist/index.js");

if (invokedDirectly) {
  buildCli().parseAsync(process.argv).catch((err: Error) => {
    process.stderr.write(`FATAL: ${err.message}\n`);
    process.exit(1);
  });
}
