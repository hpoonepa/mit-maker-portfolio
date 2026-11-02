import { afterEach, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/index.js";
import { loadConfig } from "../src/config.js";

const DASHBOARD_BATCH = [
  "notifications.list",
  "usage.getCurrentPeriodUsage",
  "usage.getProjection",
  "usage.getGpuHoursByTool",
  "usage.getTopUsers",
  "dashboard.getRecentActivity",
  "dashboard.getTopProjects",
].join(",");

describe("tRPC batching", () => {
  let app: FastifyInstance | undefined;

  afterEach(async () => {
    await app?.close();
  });

  it("routes the dashboard batch instead of rejecting its long path", async () => {
    app = await buildServer({
      config: loadConfig({ NODE_ENV: "test" }),
      prisma: {} as never,
      redis: null,
      fastifyOpts: { logger: false },
    });

    const response = await app.inject({
      method: "GET",
      url: `/trpc/${DASHBOARD_BATCH}?batch=1`,
    });

    expect(DASHBOARD_BATCH.length).toBeGreaterThan(100);
    expect(response.statusCode).not.toBe(404);
    expect(response.headers["content-type"]).toContain("application/json");
  });
});
