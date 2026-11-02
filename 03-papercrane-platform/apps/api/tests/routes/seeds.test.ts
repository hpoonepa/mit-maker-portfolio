import Fastify from "fastify";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { errorHandler } from "../../src/middleware/errorHandler.js";
import { registerSeedRoutes } from "../../src/routes/rest/seeds.js";
import type { ApiKeyPrincipal } from "@papercrane/auth";

/**
 * Integration tests for POST /v1/seeds/consume.
 *
 * We build a minimal Fastify instance, short-circuit auth by pre-populating
 * `req.auth` through a preHandler, and stub Prisma for the seed-meter service.
 * This mirrors the pattern used by `healthz.test.ts` — we do not boot the full
 * server.
 */

const ORG = "11111111-1111-1111-1111-111111111111";

function apiKeyAuth(scopes: string[] = ["usage:write"]): ApiKeyPrincipal {
  return {
    kind: "apiKey",
    apiKeyId: "00000000-0000-0000-0000-00000000000a",
    orgId: ORG,
    tier: "pro",
    scopes: scopes as ApiKeyPrincipal["scopes"],
    prefix: "pc_live_",
  };
}

function makePrisma(opts: {
  tier?: "free" | "pro" | "frontier";
  seedsUsed?: number;
  cached?: unknown;
} = {}) {
  const tier = opts.tier ?? "pro";
  let seedsUsed = opts.seedsUsed ?? 0;
  let createdUsageSeed = 0;
  let createdIdem = 0;
  const prisma: Record<string, unknown> = {
    // withRlsUser opens `prisma.$transaction(async tx => { await tx.$executeRaw`...`; return fn(tx); })`.
    // Our fake passes `prisma` itself in as the tx so all model methods are available.
    $transaction: async <T>(fn: (tx: unknown) => Promise<T>): Promise<T> => fn(prisma),
    // Tagged-template form used by setCurrentUser — just ignore the binding.
    $executeRaw: async () => 1,
    $executeRawUnsafe: async () => 1,
    $queryRawUnsafe: async () => [],
    organization: {
      findUnique: vi.fn().mockImplementation(async () => ({
        id: ORG,
        tier,
        seedsUsed,
      })),
      update: vi.fn().mockImplementation(async ({ data }: { data: { seedsUsed?: { increment: number } } }) => {
        seedsUsed += data.seedsUsed?.increment ?? 0;
        return { id: ORG, tier, seedsUsed };
      }),
    },
    usageSeed: {
      create: vi.fn().mockImplementation(async () => {
        createdUsageSeed += 1;
        return {
          id: BigInt(1000 + createdUsageSeed),
          orgId: ORG,
          jobId: "33333333-3333-3333-3333-333333333333",
          seeds: 1,
          reason: "consume",
          createdAt: new Date("2026-04-23T12:00:00Z"),
        };
      }),
    },
    idempotencyKey: {
      findUnique: vi.fn().mockImplementation(async () => opts.cached ?? null),
      create: vi.fn().mockImplementation(async () => {
        createdIdem += 1;
        return {};
      }),
    },
    // Exposed to tests for assertion on counters.
    __debug: {
      get seedsUsed() {
        return seedsUsed;
      },
      get createdUsageSeed() {
        return createdUsageSeed;
      },
      get createdIdem() {
        return createdIdem;
      },
    },
  };
  return prisma as unknown as Parameters<typeof registerSeedRoutes>[1]["prisma"] & {
    __debug: { seedsUsed: number; createdUsageSeed: number; createdIdem: number };
  };
}

async function buildApp(
  prisma: ReturnType<typeof makePrisma>,
  ...authArgs: Array<ApiKeyPrincipal | undefined>
) {
  // Only apply the default when no second arg was passed at all. Previously a
  // JS default kicked in for an explicit `undefined`, which silently re-armed
  // auth in the "missing auth" test case (regression caught Wave 9).
  const auth: ApiKeyPrincipal | undefined =
    authArgs.length === 0 ? apiKeyAuth() : authArgs[0];
  const app = Fastify({ logger: false });
  app.setErrorHandler(errorHandler);
  app.addHook("preHandler", async (req) => {
    req.auth = auth;
  });
  await registerSeedRoutes(app, { prisma });
  return app;
}

const BODY = {
  orgId: ORG,
  projectId: "22222222-2222-2222-2222-222222222222",
  jobId: "33333333-3333-3333-3333-333333333333",
  toolChain: ["rfdiffusion"],
  gpuSeconds: 140,
  costCents: 6,
  closedWeights: false,
};

const IDEM = "018f9a1e-7b3e-7c0c-8a2f-1234567890ab";

describe("POST /v1/seeds/consume", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("happy path: creates a usage row and returns counted=true", async () => {
    const prisma = makePrisma({ tier: "pro", seedsUsed: 100 });
    const app = await buildApp(prisma);
    const res = await app.inject({
      method: "POST",
      url: "/v1/seeds/consume",
      headers: {
        authorization: "Bearer pc_live_test",
        "idempotency-key": IDEM,
        "content-type": "application/json",
      },
      payload: BODY,
    });
    expect(res.statusCode).toBe(200);
    const body = res.json() as {
      seedId: string;
      counted: boolean;
      remainingInPeriod: number;
      periodResetsAt: string;
    };
    expect(body.counted).toBe(true);
    expect(body.remainingInPeriod).toBe(75_000 - 101);
    expect(body.seedId).toMatch(/^\d+$/);
    expect(body.periodResetsAt).toMatch(/^2026-\d{2}-\d{2}T/);
    expect(prisma.__debug.seedsUsed).toBe(101);
    expect(prisma.__debug.createdUsageSeed).toBe(1);
    expect(prisma.__debug.createdIdem).toBe(1);
    await app.close();
  });

  it("rejects missing Idempotency-Key header with 422", async () => {
    const prisma = makePrisma();
    const app = await buildApp(prisma);
    const res = await app.inject({
      method: "POST",
      url: "/v1/seeds/consume",
      headers: {
        authorization: "Bearer pc_live_test",
        "content-type": "application/json",
      },
      payload: BODY,
    });
    expect(res.statusCode).toBe(422);
    const body = res.json() as { error: string };
    expect(body.error).toBe("idempotency_key_required");
    await app.close();
  });

  it("returns 400 on zod validation failure", async () => {
    const prisma = makePrisma();
    const app = await buildApp(prisma);
    const res = await app.inject({
      method: "POST",
      url: "/v1/seeds/consume",
      headers: {
        authorization: "Bearer pc_live_test",
        "idempotency-key": IDEM,
        "content-type": "application/json",
      },
      payload: { ...BODY, gpuSeconds: -1 },
    });
    expect(res.statusCode).toBe(400);
    const body = res.json() as { error: string };
    expect(body.error).toBe("validation_error");
    await app.close();
  });

  it("returns 402 QUOTA_EXCEEDED when org is at hard cap", async () => {
    const prisma = makePrisma({ tier: "free", seedsUsed: 500 });
    const auth = { ...apiKeyAuth(), tier: "free" as const };
    const app = await buildApp(prisma, auth);
    const res = await app.inject({
      method: "POST",
      url: "/v1/seeds/consume",
      headers: {
        authorization: "Bearer pc_live_test",
        "idempotency-key": IDEM,
        "content-type": "application/json",
      },
      payload: BODY,
    });
    expect(res.statusCode).toBe(402);
    const body = res.json() as { error: string; remaining: number };
    expect(body.error).toBe("QUOTA_EXCEEDED");
    expect(body.remaining).toBe(0);
    expect(prisma.__debug.createdUsageSeed).toBe(0);
    await app.close();
  });

  it("idempotent replay returns the cached response with counted=false", async () => {
    const cachedBody = {
      seedId: "555",
      counted: true,
      remainingInPeriod: 74_999,
      periodResetsAt: "2026-05-01T00:00:00.000Z",
    };
    const prisma = makePrisma({
      tier: "pro",
      seedsUsed: 10,
      cached: {
        key: `seeds:consume:${ORG}:${IDEM}`,
        scope: `seeds:consume:${ORG}`,
        responseJson: cachedBody,
        expiresAt: new Date(Date.now() + 3600_000),
        createdAt: new Date(),
      },
    });
    const app = await buildApp(prisma);
    const res = await app.inject({
      method: "POST",
      url: "/v1/seeds/consume",
      headers: {
        authorization: "Bearer pc_live_test",
        "idempotency-key": IDEM,
        "content-type": "application/json",
      },
      payload: BODY,
    });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { counted: boolean; seedId: string };
    expect(body.counted).toBe(false);
    expect(body.seedId).toBe("555");
    expect(prisma.__debug.createdUsageSeed).toBe(0);
    await app.close();
  });

  it("returns 403 when the API key lacks usage:write scope", async () => {
    const prisma = makePrisma();
    const auth: ApiKeyPrincipal = {
      ...apiKeyAuth(),
      scopes: ["usage:read"] as ApiKeyPrincipal["scopes"],
    };
    const app = await buildApp(prisma, auth);
    const res = await app.inject({
      method: "POST",
      url: "/v1/seeds/consume",
      headers: {
        authorization: "Bearer pc_live_test",
        "idempotency-key": IDEM,
        "content-type": "application/json",
      },
      payload: BODY,
    });
    expect(res.statusCode).toBe(403);
    await app.close();
  });

  it("returns 401 when auth is missing", async () => {
    const prisma = makePrisma();
    const app = await buildApp(prisma, undefined);
    const res = await app.inject({
      method: "POST",
      url: "/v1/seeds/consume",
      headers: {
        "idempotency-key": IDEM,
        "content-type": "application/json",
      },
      payload: BODY,
    });
    expect(res.statusCode).toBe(401);
    await app.close();
  });
});
