import { describe, expect, it } from "vitest";
import { prisma } from "../src/index";

/**
 * Schema surface contract for newly-added models.
 *
 * The API and worker packages import typed delegates from `@papercrane/db`
 * (e.g. `prisma.webhook.findMany`). If the Prisma client is regenerated
 * without these models present, consumers break at compile time.
 *
 * These tests assert only the presence of the delegate objects — they do not
 * execute any SQL. Schema-level correctness (column names, indexes, FKs) is
 * covered by the migration SQL and Prisma's own generator.
 */
describe("@papercrane/db schema surface — webhook/audit/idempotency", () => {
  it("exposes a `webhook` delegate on the Prisma client", () => {
    expect(prisma.webhook).toBeDefined();
    expect(typeof prisma.webhook.findMany).toBe("function");
    expect(typeof prisma.webhook.create).toBe("function");
  });

  it("exposes a `webhookDelivery` delegate on the Prisma client", () => {
    expect(prisma.webhookDelivery).toBeDefined();
    expect(typeof prisma.webhookDelivery.findMany).toBe("function");
    expect(typeof prisma.webhookDelivery.create).toBe("function");
  });

  it("exposes a `jobAudit` delegate on the Prisma client", () => {
    expect(prisma.jobAudit).toBeDefined();
    expect(typeof prisma.jobAudit.findMany).toBe("function");
    expect(typeof prisma.jobAudit.create).toBe("function");
  });

  it("exposes an `idempotencyKey` delegate on the Prisma client", () => {
    expect(prisma.idempotencyKey).toBeDefined();
    expect(typeof prisma.idempotencyKey.findUnique).toBe("function");
    expect(typeof prisma.idempotencyKey.create).toBe("function");
  });
});
