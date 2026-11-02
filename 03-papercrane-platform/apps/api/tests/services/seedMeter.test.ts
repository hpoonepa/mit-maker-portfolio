import { describe, expect, it, vi, beforeEach } from "vitest";
import { ZodError } from "zod";
import {
  SeedConsumeInputSchema,
  consumeSeed,
  HARD_CAPS,
  SOFT_CAPS,
  computePeriodResetsAt,
  buildIdempotencyKey,
} from "../../src/services/seedMeter.js";

/**
 * Unit tests for the seed-meter service. Prisma is mocked to avoid any DB
 * roundtrip — we only assert the control flow: validation, idempotency,
 * cap arithmetic, and the threshold breadcrumb emission.
 */

const VALID_INPUT = {
  orgId: "11111111-1111-1111-1111-111111111111",
  projectId: "22222222-2222-2222-2222-222222222222",
  jobId: "33333333-3333-3333-3333-333333333333",
  toolChain: ["rfdiffusion", "proteinmpnn"],
  gpuSeconds: 142,
  costCents: 8,
  closedWeights: false,
};

function makeTx(org: { tier: "free" | "pro" | "frontier"; seedsUsed: number }) {
  const tx = {
    organization: {
      findUnique: vi.fn().mockResolvedValue({
        id: VALID_INPUT.orgId,
        tier: org.tier,
        seedsUsed: org.seedsUsed,
      }),
      update: vi.fn().mockImplementation(async ({ data }) => ({
        id: VALID_INPUT.orgId,
        tier: org.tier,
        seedsUsed: org.seedsUsed + (data.seedsUsed?.increment ?? 0),
      })),
    },
    usageSeed: {
      create: vi.fn().mockResolvedValue({
        id: 1234n,
        orgId: VALID_INPUT.orgId,
        jobId: VALID_INPUT.jobId,
        seeds: 1,
        reason: "consume",
        createdAt: new Date("2026-04-23T12:00:00Z"),
      }),
    },
    idempotencyKey: {
      findUnique: vi.fn().mockResolvedValue(null),
      create: vi.fn().mockResolvedValue({}),
    },
  };
  return tx;
}

// The service is dependency-injected with a `runInTenantTx` that normally
// wraps withRlsUser; in tests we just pass through to the mock tx.
function makeRunTx(tx: ReturnType<typeof makeTx>) {
  return async <T>(fn: (t: typeof tx) => Promise<T>) => fn(tx);
}

describe("SeedConsumeInputSchema", () => {
  it("accepts a well-formed payload", () => {
    const parsed = SeedConsumeInputSchema.parse(VALID_INPUT);
    expect(parsed.orgId).toBe(VALID_INPUT.orgId);
    expect(parsed.toolChain).toEqual(["rfdiffusion", "proteinmpnn"]);
  });

  it("rejects a non-uuid orgId", () => {
    expect(() =>
      SeedConsumeInputSchema.parse({ ...VALID_INPUT, orgId: "not-a-uuid" }),
    ).toThrow(ZodError);
  });

  it("rejects a negative gpuSeconds", () => {
    expect(() =>
      SeedConsumeInputSchema.parse({ ...VALID_INPUT, gpuSeconds: -1 }),
    ).toThrow(ZodError);
  });

  it("rejects a non-integer costCents", () => {
    expect(() =>
      SeedConsumeInputSchema.parse({ ...VALID_INPUT, costCents: 1.5 }),
    ).toThrow(ZodError);
  });

  it("rejects empty toolChain", () => {
    expect(() =>
      SeedConsumeInputSchema.parse({ ...VALID_INPUT, toolChain: [] }),
    ).toThrow(ZodError);
  });

  it("rejects missing closedWeights flag", () => {
    const { closedWeights: _omit, ...rest } = VALID_INPUT;
    expect(() => SeedConsumeInputSchema.parse(rest)).toThrow(ZodError);
  });
});

describe("HARD_CAPS / SOFT_CAPS", () => {
  it("matches the plan doc §3 tier matrix", () => {
    expect(HARD_CAPS.free).toBe(500);
    expect(HARD_CAPS.pro).toBe(75_000);
    expect(HARD_CAPS.frontier).toBe(1_000_000);
    expect(SOFT_CAPS.pro).toBe(50_000);
    expect(SOFT_CAPS.free).toBe(500);
    expect(SOFT_CAPS.frontier).toBe(1_000_000);
  });
});

describe("computePeriodResetsAt", () => {
  it("returns the first of next month in UTC", () => {
    const now = new Date("2026-04-23T15:17:00Z");
    expect(computePeriodResetsAt(now).toISOString()).toBe(
      "2026-05-01T00:00:00.000Z",
    );
  });
  it("wraps December to January of the next year", () => {
    const now = new Date("2026-12-31T23:59:59Z");
    expect(computePeriodResetsAt(now).toISOString()).toBe(
      "2027-01-01T00:00:00.000Z",
    );
  });
});

describe("buildIdempotencyKey", () => {
  it("namespaces by scope + header value", () => {
    expect(
      buildIdempotencyKey(
        "11111111-1111-1111-1111-111111111111",
        "01HXZABCDEF",
      ),
    ).toBe("seeds:consume:11111111-1111-1111-1111-111111111111:01HXZABCDEF");
  });
});

describe("consumeSeed", () => {
  const logger = { warn: vi.fn(), info: vi.fn(), error: vi.fn() } as unknown as {
    warn: ReturnType<typeof vi.fn>;
    info: ReturnType<typeof vi.fn>;
    error: ReturnType<typeof vi.fn>;
  };
  const breadcrumb = vi.fn();

  beforeEach(() => {
    breadcrumb.mockClear();
  });

  it("happy path: debits and returns counted=true with remaining", async () => {
    const tx = makeTx({ tier: "pro", seedsUsed: 100 });
    const result = await consumeSeed({
      input: VALID_INPUT,
      idempotencyKey: "11111111-1111-1111-1111-aaaaaaaaaaaa",
      runInTenantTx: makeRunTx(tx),
      logger,
      now: new Date("2026-04-23T12:00:00Z"),
      addBreadcrumb: breadcrumb,
    });
    expect(result.counted).toBe(true);
    expect(result.remainingInPeriod).toBe(75_000 - 101);
    expect(result.seedId).toMatch(/^\d+$/);
    expect(result.periodResetsAt).toBe("2026-05-01T00:00:00.000Z");
    expect(tx.usageSeed.create).toHaveBeenCalledTimes(1);
    expect(tx.organization.update).toHaveBeenCalledWith(
      expect.objectContaining({
        data: { seedsUsed: { increment: 1 } },
      }),
    );
    expect(tx.idempotencyKey.create).toHaveBeenCalledTimes(1);
  });

  it("hard cap: returns 402 payload when seedsUsed >= hard cap", async () => {
    const tx = makeTx({ tier: "free", seedsUsed: 500 });
    const result = await consumeSeed({
      input: VALID_INPUT,
      idempotencyKey: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      runInTenantTx: makeRunTx(tx),
      logger,
      now: new Date("2026-04-23T12:00:00Z"),
      addBreadcrumb: breadcrumb,
    });
    expect(result.quotaExceeded).toBe(true);
    expect(result.counted).toBe(false);
    expect(result.remainingInPeriod).toBe(0);
    expect(tx.usageSeed.create).not.toHaveBeenCalled();
    expect(tx.organization.update).not.toHaveBeenCalled();
    expect(logger.warn).toHaveBeenCalledWith(
      expect.objectContaining({
        orgId: VALID_INPUT.orgId,
        tier: "free",
      }),
      expect.stringContaining("quota exceeded"),
    );
  });

  it("idempotent replay: returns cached response with counted=false", async () => {
    const tx = makeTx({ tier: "pro", seedsUsed: 100 });
    const cached = {
      seedId: "999",
      counted: true,
      remainingInPeriod: 74_899,
      periodResetsAt: "2026-05-01T00:00:00.000Z",
    };
    tx.idempotencyKey.findUnique.mockResolvedValue({
      key: "seeds:consume:11111111-1111-1111-1111-111111111111:replay-key",
      scope: "seeds:consume:11111111-1111-1111-1111-111111111111",
      responseJson: cached,
      expiresAt: new Date("2026-04-24T12:00:00Z"),
      createdAt: new Date("2026-04-23T12:00:00Z"),
    });

    const result = await consumeSeed({
      input: VALID_INPUT,
      idempotencyKey: "replay-key",
      runInTenantTx: makeRunTx(tx),
      logger,
      now: new Date("2026-04-23T12:00:00Z"),
      addBreadcrumb: breadcrumb,
    });
    expect(result.counted).toBe(false);
    expect(result.seedId).toBe("999");
    expect(result.remainingInPeriod).toBe(74_899);
    expect(tx.usageSeed.create).not.toHaveBeenCalled();
    expect(tx.organization.update).not.toHaveBeenCalled();
  });

  it("emits a threshold breadcrumb when crossing 80%", async () => {
    // Pro soft cap 50000 * 0.80 = 40000. Seed n goes 39999 -> 40000.
    const tx = makeTx({ tier: "pro", seedsUsed: 39_999 });
    await consumeSeed({
      input: VALID_INPUT,
      idempotencyKey: "80pct-key",
      runInTenantTx: makeRunTx(tx),
      logger,
      now: new Date("2026-04-23T12:00:00Z"),
      addBreadcrumb: breadcrumb,
    });
    expect(breadcrumb).toHaveBeenCalledWith(
      expect.objectContaining({
        category: "usage.threshold",
        data: expect.objectContaining({
          orgId: VALID_INPUT.orgId,
          threshold: 0.8,
        }),
      }),
    );
  });

  it("emits a threshold breadcrumb when crossing 95%", async () => {
    // Pro hard cap 75000 * 0.95 = 71250.
    const tx = makeTx({ tier: "pro", seedsUsed: 71_249 });
    await consumeSeed({
      input: VALID_INPUT,
      idempotencyKey: "95pct-key",
      runInTenantTx: makeRunTx(tx),
      logger,
      now: new Date("2026-04-23T12:00:00Z"),
      addBreadcrumb: breadcrumb,
    });
    // One of the breadcrumb invocations should have threshold=0.95.
    const calls = breadcrumb.mock.calls.map((c) => c[0]);
    expect(
      calls.some(
        (c: { category: string; data: { threshold: number } }) =>
          c.category === "usage.threshold" && c.data.threshold === 0.95,
      ),
    ).toBe(true);
  });

  it("returns 404-style error when org is missing", async () => {
    const tx = makeTx({ tier: "pro", seedsUsed: 0 });
    tx.organization.findUnique.mockResolvedValue(null);
    await expect(
      consumeSeed({
        input: VALID_INPUT,
        idempotencyKey: "missing-org-key",
        runInTenantTx: makeRunTx(tx),
        logger,
        now: new Date("2026-04-23T12:00:00Z"),
        addBreadcrumb: breadcrumb,
      }),
    ).rejects.toThrow(/org not found/i);
  });
});
