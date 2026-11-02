import { describe, it, expect, vi, beforeEach } from "vitest";
import { loadRuns, BATCH_SIZE } from "../src/loaders/postgres.js";
import type { BenchmarkRun } from "../src/schema.js";

// -------------------- mock pg client/pool --------------------------------

interface FakeCall {
  sql: string;
  params?: unknown[];
}

function makeFakeClient(opts: {
  conflictRunIds?: Set<string>;
} = {}) {
  const conflicts = opts.conflictRunIds ?? new Set<string>();
  const calls: FakeCall[] = [];
  let released = 0;

  const query = vi.fn(async (sql: string, params?: unknown[]) => {
    calls.push({ sql, params });
    const trimmed = sql.trim();

    if (/BEGIN|COMMIT|ROLLBACK/i.test(trimmed.split(/\s+/)[0] ?? "")) {
      return { rows: [], rowCount: 0 };
    }

    if (/INSERT INTO benchmark_runs/i.test(sql)) {
      const runId = String(params?.[0] ?? "");
      if (conflicts.has(runId)) {
        return { rows: [], rowCount: 0 };
      }
      return { rows: [{ run_id: runId }], rowCount: 1 };
    }

    if (/INSERT INTO designs/i.test(sql)) {
      // Number of (... , ..., ..., ..., ..., ...) tuples == params / 6.
      const inserted = params ? params.length / 6 : 0;
      return { rows: [], rowCount: inserted };
    }

    return { rows: [], rowCount: 0 };
  });

  const client = {
    query,
    release: vi.fn(() => {
      released += 1;
    }),
  };

  const pool = {
    connect: vi.fn(async () => client),
    query: vi.fn(async () => ({ rows: [], rowCount: 0 })),
    end: vi.fn(async () => undefined),
  };

  return {
    pool: pool as unknown as Parameters<typeof loadRuns>[0],
    calls,
    client,
    getReleased: () => released,
  };
}

// -------------------- fixture builders -----------------------------------

const H = (c: string) => c.repeat(64);

function makeRun(runId: string, seedOffset = 0): BenchmarkRun {
  return {
    run_id: runId,
    target_id: "pd-l1",
    tool_id: "papercrane",
    tool_version: "v4",
    config_hash: H("a"),
    seed_range: [1, 2],
    compute_env_hash: H("b"),
    designs: [
      {
        seed: 1 + seedOffset,
        sequence: "MKTAYIAKQ",
        structurePath: "designs/seed_1.pdb",
        metrics: { ipsae: 0.82 },
      },
      {
        seed: 2 + seedOffset,
        sequence: "GQPAYERLI",
        structurePath: "designs/seed_2.pdb",
        metrics: { ipsae: 0.71 },
      },
    ],
    cost_usd: 4.28,
    wallclock_sec: 100,
    results_digest: H("c"),
    source: "god-v3b",
  };
}

// -------------------- tests ----------------------------------------------

describe("loadRuns", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("inserts a single run with batched design insert and commits", async () => {
    const { pool, calls, getReleased } = makeFakeClient();
    const run = makeRun("pc-run-0001");
    const res = await loadRuns(pool, [run]);

    expect(res).toEqual({
      runs_inserted: 1,
      runs_skipped: 0,
      designs_inserted: 2,
    });

    // Transaction lifecycle.
    expect(calls[0]!.sql.trim()).toBe("BEGIN");
    expect(calls.at(-1)!.sql.trim()).toBe("COMMIT");

    // Run insert uses ON CONFLICT DO NOTHING on run_id.
    const runInsert = calls.find((c) => /INSERT INTO benchmark_runs/i.test(c.sql))!;
    expect(runInsert.sql).toMatch(/ON CONFLICT \(run_id\) DO NOTHING/i);
    expect(runInsert.params?.[0]).toBe("pc-run-0001");

    // Designs are inserted in a single multi-row INSERT.
    const designInsert = calls.find((c) => /INSERT INTO designs/i.test(c.sql))!;
    expect(designInsert).toBeDefined();
    expect(designInsert.sql).toMatch(/ON CONFLICT \(run_id, seed\) DO NOTHING/i);
    expect(designInsert.params).toHaveLength(2 * 6); // 2 designs * 6 columns

    // Client released once after COMMIT.
    expect(getReleased()).toBe(1);
  });

  it("skips inserting designs when run_id conflict fires", async () => {
    const { pool, calls } = makeFakeClient({
      conflictRunIds: new Set(["pc-run-0001"]),
    });
    const res = await loadRuns(pool, [makeRun("pc-run-0001")]);

    expect(res).toEqual({
      runs_inserted: 0,
      runs_skipped: 1,
      designs_inserted: 0,
    });

    const designInsert = calls.find((c) => /INSERT INTO designs/i.test(c.sql));
    expect(designInsert).toBeUndefined();
  });

  it("idempotency: two sequential loads of the same run produce net one insert", async () => {
    // First pass: empty conflict set — insert succeeds.
    const first = makeFakeClient();
    const r1 = await loadRuns(first.pool, [makeRun("pc-run-0001")]);
    expect(r1.runs_inserted).toBe(1);

    // Second pass: db now has that run_id, so ON CONFLICT fires.
    const second = makeFakeClient({ conflictRunIds: new Set(["pc-run-0001"]) });
    const r2 = await loadRuns(second.pool, [makeRun("pc-run-0001")]);
    expect(r2.runs_inserted).toBe(0);
    expect(r2.runs_skipped).toBe(1);
  });

  it("batches inserts into transactions of BATCH_SIZE runs", async () => {
    const { pool, calls, getReleased } = makeFakeClient();
    const n = BATCH_SIZE + 3;
    const runs: BenchmarkRun[] = [];
    for (let i = 0; i < n; i++) {
      runs.push(makeRun(`pc-run-${String(i).padStart(4, "0")}`, i * 2));
    }
    const res = await loadRuns(pool, runs);
    expect(res.runs_inserted).toBe(n);

    const beginCount = calls.filter((c) => /^BEGIN/i.test(c.sql.trim())).length;
    const commitCount = calls.filter((c) => /^COMMIT/i.test(c.sql.trim())).length;
    expect(beginCount).toBe(2); // 100 + 3
    expect(commitCount).toBe(2);
    expect(getReleased()).toBe(2);
  });

  it("rolls back on query failure inside a batch", async () => {
    // A client whose INSERT INTO benchmark_runs throws, so loadRuns must
    // issue ROLLBACK and release the client before re-throwing.
    const failingClient = {
      query: vi.fn(async (sql: string) => {
        if (/^BEGIN/i.test(sql.trim())) return { rows: [], rowCount: 0 };
        if (/INSERT INTO benchmark_runs/i.test(sql)) throw new Error("boom");
        if (/^ROLLBACK/i.test(sql.trim())) return { rows: [], rowCount: 0 };
        return { rows: [], rowCount: 0 };
      }),
      release: vi.fn(),
    };
    const failingPool = {
      connect: vi.fn(async () => failingClient),
      query: vi.fn(),
    } as unknown as Parameters<typeof loadRuns>[0];

    await expect(
      loadRuns(failingPool, [makeRun("pc-run-0001")]),
    ).rejects.toThrow(/boom/);

    const sqls = failingClient.query.mock.calls.map((c) => String(c[0]));
    expect(sqls.some((s) => /^ROLLBACK/i.test(s.trim()))).toBe(true);
    expect(failingClient.release).toHaveBeenCalledTimes(1);
  });
});
