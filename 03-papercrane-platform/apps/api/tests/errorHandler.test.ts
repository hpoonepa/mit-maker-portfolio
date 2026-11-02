import Fastify from "fastify";
import { describe, expect, it } from "vitest";
import { ZodError, z } from "zod";
import { AuthError, ForbiddenError } from "@papercrane/auth";
import { errorHandler } from "../src/middleware/errorHandler.js";

/**
 * Error-handler mapping tests. We register one route per case that throws
 * the target error, then assert the response code and body shape.
 */

async function buildApp() {
  const app = Fastify({ logger: false });
  app.setErrorHandler(errorHandler);
  app.get("/auth", async () => {
    throw new AuthError("nope", "bad_token");
  });
  app.get("/forbidden", async () => {
    throw new ForbiddenError("denied", "scope_denied");
  });
  app.get("/zod", async () => {
    // Trigger a real ZodError to exercise the instanceof branch.
    const schema = z.object({ x: z.number() }).strict();
    schema.parse({});
  });
  app.get("/boom", async () => {
    throw new Error("kaboom");
  });
  return app;
}

describe("errorHandler", () => {
  it("maps AuthError to 401 with the provided code", async () => {
    const app = await buildApp();
    const res = await app.inject({ method: "GET", url: "/auth" });
    expect(res.statusCode).toBe(401);
    expect(res.json()).toMatchObject({ error: "bad_token", message: "nope" });
    await app.close();
  });

  it("maps ForbiddenError to 403", async () => {
    const app = await buildApp();
    const res = await app.inject({ method: "GET", url: "/forbidden" });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toMatchObject({ error: "scope_denied" });
    await app.close();
  });

  it("maps ZodError to 400 with issues", async () => {
    const app = await buildApp();
    const res = await app.inject({ method: "GET", url: "/zod" });
    expect(res.statusCode).toBe(400);
    const body = res.json() as { error: string; issues: Array<{ path: string }> };
    expect(body.error).toBe("validation_error");
    expect(Array.isArray(body.issues)).toBe(true);
    expect(body.issues.length).toBeGreaterThan(0);
    await app.close();
  });

  it("maps generic Error to 500 with a redacted message", async () => {
    const app = await buildApp();
    const res = await app.inject({ method: "GET", url: "/boom" });
    expect(res.statusCode).toBe(500);
    const body = res.json() as { error: string; message: string };
    expect(body.error).toBe("internal_error");
    // Never leak the raw error text in prod-shape responses.
    expect(body.message).not.toContain("kaboom");
    await app.close();
  });

  it("directly invoked with ZodError returns 400", () => {
    // Smoke check for the pure mapping, independent of Fastify.
    let status = 0;
    let payload: unknown = null;
    const reply = {
      code(c: number) {
        status = c;
        return this;
      },
      send(p: unknown) {
        payload = p;
      },
    } as never;
    const log = {
      info: () => {},
      error: () => {},
    };
    try {
      z.number().parse("nope");
    } catch (err) {
      errorHandler(err as unknown as Parameters<typeof errorHandler>[0], { log, id: "t", url: "/", method: "GET" } as never, reply);
    }
    expect(status).toBe(400);
    expect((payload as { error: string }).error).toBe("validation_error");
  });
});
