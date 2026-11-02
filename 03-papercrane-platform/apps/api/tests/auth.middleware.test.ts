import { describe, expect, it, vi } from "vitest";
import { AuthError, ForbiddenError, requireScope } from "@papercrane/auth";
import {
  buildAuthPreHandler,
  extractBearerToken,
  resolveApiKey,
} from "../src/middleware/auth.js";

/**
 * Auth middleware unit tests.
 *
 * These tests exercise the pure functions — `extractBearerToken`,
 * `resolveApiKey`, and the preHandler directly. We do NOT spin up a full
 * Fastify instance; the Fastify-integration tests live in `healthz.test.ts`
 * where the app surface is tested end-to-end.
 */

describe("extractBearerToken", () => {
  it("returns the token when header is well-formed", () => {
    expect(extractBearerToken("Bearer abc123")).toBe("abc123");
  });
  it("is case-insensitive on the Bearer prefix", () => {
    expect(extractBearerToken("bearer abc")).toBe("abc");
  });
  it("returns undefined for missing header", () => {
    expect(extractBearerToken(undefined)).toBeUndefined();
  });
  it("returns undefined for malformed header", () => {
    expect(extractBearerToken("Basic abc")).toBeUndefined();
    expect(extractBearerToken("Bearer ")).toBeUndefined();
  });
});

describe("resolveApiKey", () => {
  it("throws AuthError when no candidates match", async () => {
    const prisma = {
      apiKey: {
        findMany: vi.fn().mockResolvedValue([]),
        update: vi.fn(),
      },
    } as unknown as Parameters<typeof resolveApiKey>[1];
    await expect(resolveApiKey("pc_live_sk_badkey", prisma)).rejects.toThrow(
      AuthError,
    );
  });
});

describe("buildAuthPreHandler", () => {
  const prisma = { apiKey: { findMany: vi.fn(), update: vi.fn() } } as never;
  const config = {
    nodeEnv: "test" as const,
    logLevel: "info" as const,
    port: 3001,
    host: "0.0.0.0",
    supabaseJwtAudience: "authenticated",
    sentryTracesSampleRate: 0.1,
    corsOrigin: "*",
    appUrl: "http://localhost:3000",
    webUrl: "http://localhost:3000",
  };

  it("skips auth for public routes", async () => {
    const handler = buildAuthPreHandler({ prisma, config });
    const req = {
      headers: {},
      routeOptions: { config: { public: true } },
    } as never;
    await expect(handler(req, {} as never)).resolves.toBeUndefined();
  });

  it("throws when no token is present and anonymous is disallowed", async () => {
    const handler = buildAuthPreHandler({ prisma, config });
    const req = { headers: {}, routeOptions: {} } as never;
    await expect(handler(req, {} as never)).rejects.toThrow(AuthError);
  });

  it("allows anonymous when opted in", async () => {
    const handler = buildAuthPreHandler(
      { prisma, config },
      { allowAnonymous: true },
    );
    const req = { headers: {}, routeOptions: {} } as never;
    await expect(handler(req, {} as never)).resolves.toBeUndefined();
  });
});

describe("requireScope", () => {
  it("passes through for user principals (scope is an api-key concept)", () => {
    expect(() =>
      requireScope(
        { kind: "user", userId: "u1", role: "authenticated" },
        "jobs:write",
      ),
    ).not.toThrow();
  });

  it("allows wildcard scopes", () => {
    expect(() =>
      requireScope(
        {
          kind: "apiKey",
          apiKeyId: "k1",
          orgId: "o1",
          tier: "pro",
          scopes: ["*"],
        },
        "jobs:write",
      ),
    ).not.toThrow();
  });

  it("throws ForbiddenError when required scope is absent", () => {
    expect(() =>
      requireScope(
        {
          kind: "apiKey",
          apiKeyId: "k1",
          orgId: "o1",
          tier: "pro",
          scopes: ["jobs:read"],
        },
        "jobs:write",
      ),
    ).toThrow(ForbiddenError);
  });
});
