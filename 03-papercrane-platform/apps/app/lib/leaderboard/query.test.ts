import { describe, expect, it } from "vitest";
import {
  aggregateLeaderboard,
  type BenchmarkRunRow,
  type ToolRow,
  type TargetRow,
} from "./query.js";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const tools: ToolRow[] = [
  {
    id: "papercrane-v4",
    displayName: "PaperCrane V4",
    version: "4.0.0",
    tier: "frontier",
    category: "composite",
  },
  {
    id: "rfdiffusion",
    displayName: "RFdiffusion",
    version: "1.1.0",
    tier: "open",
    category: "backbone",
  },
];

const targets: TargetRow[] = [
  { id: "pdl1", displayName: "PD-L1", tier: "easy", class: "cytokine_receptor" },
  { id: "il7ra", displayName: "IL-7Rα", tier: "hard", class: "cytokine_receptor" },
];

function run(
  toolId: string,
  targetId: string,
  opts: {
    id?: string;
    seedRangeStart?: number;
    seedRangeEnd?: number;
    costUsd?: number | null;
    perSeedHits?: boolean[];
    meanIpsae?: number;
    meanDockq?: number;
    meanPtmenergy?: number;
    status?: string;
    completedAt?: string | null;
  } = {}
): BenchmarkRunRow {
  const start = opts.seedRangeStart ?? 1;
  const end = opts.seedRangeEnd ?? 30;
  return {
    id: opts.id ?? `run-${toolId}-${targetId}-${start}-${end}`,
    runSlug: `pc-run-${opts.id ?? toolId + "-" + start}`,
    benchmarkVersion: "1.0",
    toolId,
    toolVersion: "x",
    targetId,
    configHash: "c0ffee",
    seedRangeStart: start,
    seedRangeEnd: end,
    costUsd: opts.costUsd ?? 10.0,
    status: opts.status ?? "succeeded",
    createdAt: "2026-04-20T00:00:00Z",
    completedAt: opts.completedAt ?? "2026-04-20T01:00:00Z",
    config: {
      results: {
        perSeedHits: opts.perSeedHits,
        meanIpsae: opts.meanIpsae,
        meanDockq: opts.meanDockq,
        meanPtmenergy: opts.meanPtmenergy,
      },
    },
  };
}

const methodology = { version: "1.0", commitSha: null, signedAt: null };

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("aggregateLeaderboard", () => {
  it("rolls up per-seed hits into cell hit rates", () => {
    // PaperCrane V4 on PD-L1: one run with 18/30 hits.
    const hits = [
      ...Array(18).fill(true),
      ...Array(12).fill(false),
    ];
    const snapshot = aggregateLeaderboard({
      runs: [
        run("papercrane-v4", "pdl1", {
          perSeedHits: hits,
          meanIpsae: 0.72,
          meanDockq: 0.3,
          meanPtmenergy: -1.4,
          costUsd: 8.0,
        }),
      ],
      tools,
      targets,
      methodology,
    });

    expect(snapshot.totalRuns).toBe(1);
    expect(snapshot.rows).toHaveLength(1);

    const row = snapshot.rows[0]!;
    expect(row.toolId).toBe("papercrane-v4");
    expect(row.meanHitRate).toBeCloseTo(18 / 30, 6);

    const cell = row.cells.pdl1!;
    expect(cell.totalSeeds).toBe(30);
    expect(cell.totalHits).toBe(18);
    expect(cell.hitRate).toBeCloseTo(18 / 30, 6);
    expect(cell.meanIpsae).toBeCloseTo(0.72, 6);
    expect(cell.costPerHit).toBeCloseTo(8.0 / 18, 6);
    expect(cell.ci).not.toBeNull();
    const [lo, hi] = cell.ci!;
    // Bootstrap CI must strictly bracket the point estimate.
    expect(lo).toBeLessThanOrEqual(cell.hitRate + 1e-9);
    expect(hi).toBeGreaterThanOrEqual(cell.hitRate - 1e-9);
  });

  it("concatenates per-seed vectors across multiple runs in the same cell", () => {
    const snapshot = aggregateLeaderboard({
      runs: [
        run("papercrane-v4", "pdl1", {
          id: "a",
          seedRangeStart: 1,
          seedRangeEnd: 10,
          perSeedHits: Array(10).fill(true),
          meanIpsae: 0.8,
          meanDockq: 0.4,
          meanPtmenergy: -1.5,
          costUsd: 5,
        }),
        run("papercrane-v4", "pdl1", {
          id: "b",
          seedRangeStart: 11,
          seedRangeEnd: 20,
          perSeedHits: Array(10).fill(false),
          meanIpsae: 0.6,
          meanDockq: 0.2,
          meanPtmenergy: -1.0,
          costUsd: 5,
        }),
      ],
      tools,
      targets,
      methodology,
    });

    const cell = snapshot.rows[0]!.cells.pdl1!;
    expect(cell.totalSeeds).toBe(20);
    expect(cell.totalHits).toBe(10);
    expect(cell.hitRate).toBeCloseTo(0.5, 6);
    // Mean ipSAE weighted by seed count: runs are equal size so straight avg.
    expect(cell.meanIpsae).toBeCloseTo(0.7, 6);
    expect(cell.runCount).toBe(2);
    expect(cell.perRunHitRates).toEqual([1, 0]);
    // CV across [1.0, 0.0] = stddev/mean = (0.7071 / 0.5) = 1.4142
    expect(cell.cv).toBeCloseTo(Math.sqrt(0.5) / 0.5, 3);
    // Total cost $10 / 10 hits = $1.00/hit
    expect(cell.costPerHit).toBeCloseTo(1.0, 6);
  });

  it("excludes non-succeeded runs", () => {
    const snapshot = aggregateLeaderboard({
      runs: [
        run("papercrane-v4", "pdl1", {
          id: "ok",
          perSeedHits: Array(30).fill(true),
          meanIpsae: 0.9,
          costUsd: 5,
        }),
        run("papercrane-v4", "pdl1", {
          id: "failed",
          status: "failed",
          perSeedHits: Array(30).fill(false),
          costUsd: 2,
        }),
      ],
      tools,
      targets,
      methodology,
    });

    expect(snapshot.totalRuns).toBe(1);
    const cell = snapshot.rows[0]!.cells.pdl1!;
    expect(cell.totalSeeds).toBe(30);
    expect(cell.totalHits).toBe(30);
    expect(cell.hitRate).toBe(1);
    expect(cell.costUsd).toBe(5); // failed run's cost is excluded
  });

  it("ranks rows by hit rate descending, cost-per-hit as tiebreaker", () => {
    const snapshot = aggregateLeaderboard({
      runs: [
        // PaperCrane V4: 50% hit rate on PD-L1, $10/hit
        run("papercrane-v4", "pdl1", {
          perSeedHits: [...Array(15).fill(true), ...Array(15).fill(false)],
          costUsd: 150,
        }),
        // RFdiffusion: 50% hit rate on PD-L1, $5/hit (wins the tiebreak)
        run("rfdiffusion", "pdl1", {
          perSeedHits: [...Array(15).fill(true), ...Array(15).fill(false)],
          costUsd: 75,
        }),
      ],
      tools,
      targets,
      methodology,
    });

    expect(snapshot.rows[0]!.toolId).toBe("rfdiffusion");
    expect(snapshot.rows[1]!.toolId).toBe("papercrane-v4");
  });

  it("handles the empty-DB case without throwing", () => {
    const snapshot = aggregateLeaderboard({
      runs: [],
      tools,
      targets,
      methodology,
    });
    expect(snapshot.rows).toEqual([]);
    expect(snapshot.totalRuns).toBe(0);
    expect(snapshot.lastUpdatedAt).toBeNull();
  });

  it("computes seed-weighted mean hit rate across cells", () => {
    const snapshot = aggregateLeaderboard({
      runs: [
        // PD-L1: 20/20 = 100%
        run("papercrane-v4", "pdl1", {
          seedRangeStart: 1,
          seedRangeEnd: 20,
          perSeedHits: Array(20).fill(true),
          costUsd: 10,
        }),
        // IL-7Rα: 5/30 = 16.7%
        run("papercrane-v4", "il7ra", {
          seedRangeStart: 1,
          seedRangeEnd: 30,
          perSeedHits: [...Array(5).fill(true), ...Array(25).fill(false)],
          costUsd: 20,
        }),
      ],
      tools,
      targets,
      methodology,
    });

    // Weighted: (20 * 1.0 + 30 * (5/30)) / 50 = (20 + 5) / 50 = 0.5
    expect(snapshot.rows[0]!.meanHitRate).toBeCloseTo(0.5, 6);
  });
});
