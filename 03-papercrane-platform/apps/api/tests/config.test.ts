import { describe, expect, it } from "vitest";
import {
  loadConfig,
  preferSessionPoolForDevServer,
} from "../src/config.js";

describe("loadConfig", () => {
  it("shares the worker localhost Redis default outside production", () => {
    expect(loadConfig({ NODE_ENV: "development" }).redisUrl).toBe(
      "redis://localhost:6379",
    );
    expect(loadConfig({ NODE_ENV: "test", REDIS_URL: "" }).redisUrl).toBe(
      "redis://localhost:6379",
    );
  });

  it("honors an explicit Redis URL", () => {
    expect(
      loadConfig({ NODE_ENV: "development", REDIS_URL: "redis://cache:6380" })
        .redisUrl,
    ).toBe("redis://cache:6380");
  });

  it("still requires Redis in production", () => {
    expect(() =>
      loadConfig({
        NODE_ENV: "production",
        DATABASE_URL: "postgresql://db.example.test/papercrane",
        SUPABASE_PROJECT_REF: "project-ref",
        SENTRY_DSN: "https://public@example.test/1",
      }),
    ).toThrow(/redisUrl/);
  });
});

describe("preferSessionPoolForDevServer", () => {
  it("uses the session pool for the persistent local API process", () => {
    const env = {
      NODE_ENV: "development",
      DATABASE_URL: "postgresql://pooler.example.test:6543/postgres",
      DIRECT_URL: "postgresql://pooler.example.test:5432/postgres",
    };

    preferSessionPoolForDevServer(env);

    expect(env.DATABASE_URL).toBe(env.DIRECT_URL);
  });

  it("does not replace the production database URL", () => {
    const env = {
      NODE_ENV: "production",
      DATABASE_URL: "postgresql://pooler.example.test:6543/postgres",
      DIRECT_URL: "postgresql://db.example.test:5432/postgres",
    };

    preferSessionPoolForDevServer(env);

    expect(env.DATABASE_URL).toContain(":6543/");
  });
});
