import Fastify from "fastify";
import { describe, expect, it, vi } from "vitest";
import { registerHealthz } from "../src/routes/rest/healthz.js";

/**
 * Healthz integration test. Spins up a minimal Fastify instance with a fake
 * Prisma and a fake Redis, then asserts the status-code contract:
 *
 *   - all checks pass → 200 with `ok: true`
 *   - any check fails → 503 with `ok: false`
 *
 * We don't assert the exact durationMs or timestamp values — only the
 * structural shape.
 */

function makePrisma(ok: boolean) {
  return {
    $queryRaw: ok
      ? vi.fn().mockResolvedValue([{ "?column?": 1 }])
      : vi.fn().mockRejectedValue(new Error("db down")),
  } as never;
}

function makeRedis(ok: boolean) {
  return {
    ping: ok
      ? vi.fn().mockResolvedValue("PONG")
      : vi.fn().mockResolvedValue("WRONG"),
  } as never;
}

describe("GET /healthz", () => {
  it("returns 200 when all checks pass", async () => {
    const app = Fastify({ logger: false });
    await registerHealthz(app, { prisma: makePrisma(true), redis: makeRedis(true) });
    const res = await app.inject({ method: "GET", url: "/healthz" });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { ok: boolean; checks: Record<string, { ok: boolean }> };
    expect(body.ok).toBe(true);
    expect(body.checks.db?.ok).toBe(true);
    expect(body.checks.redis?.ok).toBe(true);
    await app.close();
  });

  it("returns 503 when the db check fails", async () => {
    const app = Fastify({ logger: false });
    await registerHealthz(app, { prisma: makePrisma(false), redis: makeRedis(true) });
    const res = await app.inject({ method: "GET", url: "/healthz" });
    expect(res.statusCode).toBe(503);
    const body = res.json() as { ok: boolean; checks: Record<string, { ok: boolean }> };
    expect(body.ok).toBe(false);
    expect(body.checks.db?.ok).toBe(false);
    await app.close();
  });

  it("returns 503 when redis is unhealthy", async () => {
    const app = Fastify({ logger: false });
    await registerHealthz(app, { prisma: makePrisma(true), redis: makeRedis(false) });
    const res = await app.inject({ method: "GET", url: "/healthz" });
    expect(res.statusCode).toBe(503);
    await app.close();
  });

  it("works without redis (optional dependency)", async () => {
    const app = Fastify({ logger: false });
    await registerHealthz(app, { prisma: makePrisma(true), redis: null });
    const res = await app.inject({ method: "GET", url: "/healthz" });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { checks: Record<string, unknown> };
    expect(body.checks.redis).toBeUndefined();
    await app.close();
  });
});
