import { describe, expect, it, vi } from "vitest";
import {
  consumeSeed,
  computePeriodResetsAt,
  buildIdempotencyKey,
  HARD_CAPS,
  SOFT_CAPS,
  type ConsumeSeedDeps,
  type SeedMeterTx,
} from "../../services/seedMeter.js";

/**
 * Seed-meter tests — POST /v1/seeds/consume business logic.
 *
 * Plan 05 §3 contract:
 *   - Idempotency-Key dedups within 24h → cached response, counted: false
 *   - Free tier hard cap = 500 seeds/month → quotaExceeded sentinel (HTTP 402)
 *   - Pro overage produces a metered Stripe usage record once we cross SOFT_CAPS.pro
 *   - concurrent_jobs check at gateway (asserted at the input-contract level —
 *     full enforcement lives in the rateLimit/tier-enforce middleware, not here)
 *
 * The Prisma client is fully mocked — `runInTenantTx` invokes the unit-under-
 * test with whatever fake `tx` we provide. No DB, no Stripe, no Redis.
 */

const ORG_ID = "11111111-1111-1111-1111-111111111111";
const PROJECT_ID = "22222222-2222-2222-2222-222222222222";
const JOB_ID = "33333333-3333-3333-3333-333333333333";

interface FakeTxOpts {
  org?: { tier: "free" | "pro" | "frontier"; seedsUsed: number } | null;
  cachedResponse?: unknown;
  cachedExpiresAt?: Date;
  newSeedsUsed?: number;
  seedRowId?: bigint;
}

function mkTx(opts: FakeTxOpts = {}): SeedMeterTx {
  const org = opts.org ?? { tier: "pro", seedsUsed: 100 };
  const newSeedsUsed = opts.newSeedsUsed ?? org.seedsUsed + 1;
  const seedRowId = opts.seedRowId ?? 99n;

  return {
    organization: {
      findUnique: vi.fn().mockResolvedValue(
        org === null ? null : { id: ORG_ID, ...org },
      ),
      update: vi.fn().mockResolvedValue({ seedsUsed: newSeedsUsed }),
    },
    usageSeed: {
      create: vi
        .fn()
        .mockResolvedValue({ id: seedRowId, createdAt: new Date() }),
    },
    idempotencyKey: {
      findUnique: vi.fn().mockResolvedValue(
        opts.cachedResponse
          ? {
              key: "k",
              scope: "s",
              responseJson: opts.cachedResponse,
              expiresAt: opts.cachedExpiresAt ?? new Date(Date.now() + 60_000),
              createdAt: new Date(),
            }
          : null,
      ),
      create: vi.fn().mockResolvedValue(undefined),
    },
  };
}

function mkDeps(
  tx: SeedMeterTx,
  overrides: Partial<ConsumeSeedDeps> = {},
): ConsumeSeedDeps {
  return {
    input: {
      orgId: ORG_ID,
      projectId: PROJECT_ID,
      jobId: JOB_ID,
      toolChain: ["rfdiffusion", "mpnn", "boltz2"],
      gpuSeconds: 140,
      costCents: 6,
      closedWeights: false,
    },
    idempotencyKey: "idem-abc-123",
    runInTenantTx: async <T>(fn: (tx: SeedMeterTx) => Promise<T>) => fn(tx),
    logger: { warn: vi.fn(), info: vi.fn(), error: vi.fn() } as never,
    addBreadcrumb: vi.fn(),
    ...overrides,
  };
}

describe("Idempotency-Key dedup (24h window)", () => {
  it("returns the cached body with counted: false on replay", async () => {
    // Plan 05 §3: a retry with the same Idempotency-Key inside the 24h window
    // must return the same response body without bumping the counter.
    const cachedBody = {
      seedId: "seed_cached",
      counted: true,
      remainingInPeriod: 49_000,
      periodResetsAt: "2026-05-01T00:00:00.000Z",
    };
    const tx = mkTx({
      cachedResponse: cachedBody,
      cachedExpiresAt: new Date(Date.now() + 60_000),
    });

    const result = await consumeSeed(mkDeps(tx));

    // Counter must NOT advance on replay.
    expect(tx.organization.update).not.toHaveBeenCalled();
    expect(tx.usageSeed.create).not.toHaveBeenCalled();
    expect(result).toMatchObject({
      seedId: "seed_cached",
      counted: false,
      remainingInPeriod: 49_000,
    });
  });

  it("scopes the idempotency key by orgId so cross-org collisions are impossible", () => {
    const a = buildIdempotencyKey("org-a", "shared-header");
    const b = buildIdempotencyKey("org-b", "shared-header");
    expect(a).not.toBe(b);
    expect(a).toBe("seeds:consume:org-a:shared-header");
  });

  it("stores a 24h TTL row when a fresh request lands", async () => {
    const tx = mkTx({ org: { tier: "pro", seedsUsed: 0 } });
    const now = new Date("2026-04-15T12:00:00Z");
    await consumeSeed(mkDeps(tx, { now }));

    expect(tx.idempotencyKey.create).toHaveBeenCalledTimes(1);
    const args = (tx.idempotencyKey.create as ReturnType<typeof vi.fn>).mock
      .calls[0]![0];
    const ttlMs = (args.data.expiresAt as Date).getTime() - now.getTime();
    expect(ttlMs).toBe(24 * 60 * 60 * 1000);
    expect(args.data.key).toBe(`seeds:consume:${ORG_ID}:idem-abc-123`);
  });
});

describe("Free tier hard cap (500 seeds → HTTP 402)", () => {
  it("blocks debit at exactly 500 used (cap is inclusive upper bound)", async () => {
    expect(HARD_CAPS.free).toBe(500);
    const tx = mkTx({ org: { tier: "free", seedsUsed: 500 } });
    const result = await consumeSeed(mkDeps(tx));

    expect("quotaExceeded" in result && result.quotaExceeded).toBe(true);
    expect(result.counted).toBe(false);
    expect(result.remainingInPeriod).toBe(0);
    if ("tier" in result) expect(result.tier).toBe("free");
    // No row inserted, no counter bumped.
    expect(tx.usageSeed.create).not.toHaveBeenCalled();
    expect(tx.organization.update).not.toHaveBeenCalled();
  });

  it("permits the 500th seed (seedsUsed=499 → 500) but blocks the 501st", async () => {
    const tx499 = mkTx({
      org: { tier: "free", seedsUsed: 499 },
      newSeedsUsed: 500,
    });
    const r499 = await consumeSeed(mkDeps(tx499));
    expect("quotaExceeded" in r499 && r499.quotaExceeded).toBeFalsy();
    expect(r499.counted).toBe(true);

    const tx500 = mkTx({ org: { tier: "free", seedsUsed: 500 } });
    const r500 = await consumeSeed(mkDeps(tx500));
    expect("quotaExceeded" in r500 && r500.quotaExceeded).toBe(true);
  });
});

describe("Pro overage (>50K seeds → metered Stripe usage record)", () => {
  it("logs an overage signal once Pro crosses SOFT_CAPS.pro (50,000)", async () => {
    expect(SOFT_CAPS.pro).toBe(50_000);
    const tx = mkTx({
      org: { tier: "pro", seedsUsed: SOFT_CAPS.pro },
      newSeedsUsed: SOFT_CAPS.pro + 1,
    });
    const info = vi.fn();
    const result = await consumeSeed(
      mkDeps(tx, {
        logger: { warn: vi.fn(), info, error: vi.fn() } as never,
      }),
    );
    // The actual Stripe call is gated by FeatureFlag.onCap (deferred per
    // TODO(billing/m4)). Until then we assert the signal is logged so ops
    // can monitor overage volume during M2/M3.
    expect(info).toHaveBeenCalled();
    const overageLogCall = info.mock.calls.find((c) =>
      String(c[1] ?? "").includes("overage"),
    );
    expect(overageLogCall).toBeDefined();
    expect(result.counted).toBe(true);
  });

  it("does NOT emit an overage signal while Pro is below the soft cap", async () => {
    const tx = mkTx({
      org: { tier: "pro", seedsUsed: 100 },
      newSeedsUsed: 101,
    });
    const info = vi.fn();
    await consumeSeed(
      mkDeps(tx, {
        logger: { warn: vi.fn(), info, error: vi.fn() } as never,
      }),
    );
    const overageLogCall = info.mock.calls.find((c) =>
      String(c[1] ?? "").includes("overage"),
    );
    expect(overageLogCall).toBeUndefined();
  });

  it("emits 80% threshold breadcrumb (Sentry) on the cross-over", async () => {
    // soft80 for pro = ceil(50000 * 0.8) = 40000.
    const tx = mkTx({
      org: { tier: "pro", seedsUsed: 39_999 },
      newSeedsUsed: 40_000,
    });
    const addBreadcrumb = vi.fn();
    await consumeSeed(mkDeps(tx, { addBreadcrumb }));
    expect(addBreadcrumb).toHaveBeenCalledTimes(1);
    expect(addBreadcrumb.mock.calls[0]![0]).toMatchObject({
      category: "usage.threshold",
      level: "warning",
      data: { threshold: 0.8, tier: "pro" },
    });
  });
});

describe("Validation + period rollover (concurrent_jobs gateway prereqs)", () => {
  it("rejects malformed input (zod) — gateway must not pass invalid bodies through", async () => {
    const tx = mkTx();
    await expect(
      consumeSeed(
        mkDeps(tx, {
          input: {
            // Missing jobId — zod fails before the tenant tx opens.
            orgId: ORG_ID,
            projectId: PROJECT_ID,
            toolChain: ["rfdiffusion"],
            gpuSeconds: 100,
            costCents: 5,
            closedWeights: false,
          },
        }),
      ),
    ).rejects.toThrow();
    expect(tx.organization.findUnique).not.toHaveBeenCalled();
  });

  it("computes periodResetsAt as the first UTC day of next month (handles Dec→Jan rollover)", () => {
    expect(
      computePeriodResetsAt(new Date("2026-04-15T12:00:00Z")).toISOString(),
    ).toBe("2026-05-01T00:00:00.000Z");
    // Dec→Jan rollover (Date.UTC(2026, 12, 1) === 2027-01-01).
    expect(
      computePeriodResetsAt(new Date("2026-12-31T23:59:59Z")).toISOString(),
    ).toBe("2027-01-01T00:00:00.000Z");
  });
});
