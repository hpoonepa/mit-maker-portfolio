import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * Client singleton contract:
 * - `prisma` is exported
 * - importing the module twice within the same process reuses the same
 *   PrismaClient instance via a globalThis cache (Next.js hot-reload guard).
 */
describe("@papercrane/db client", () => {
  afterEach(() => {
    vi.resetModules();
    // clean the singleton slot between tests
    delete (globalThis as unknown as Record<string, unknown>).__papercranePrisma;
  });

  it(
    "exports a `prisma` instance that looks like a PrismaClient",
    async () => {
      const mod = await import("../src/index");
      expect(mod.prisma).toBeDefined();
      // PrismaClient exposes $connect / $disconnect / $transaction
      expect(typeof mod.prisma.$connect).toBe("function");
      expect(typeof mod.prisma.$disconnect).toBe("function");
      expect(typeof mod.prisma.$transaction).toBe("function");
    },
    // The root Turbo run starts many Vitest workers at once. Prisma's generated
    // client can take longer than Vitest's 5 s default to load under that CPU
    // contention even though this test never opens a database connection.
    15_000,
  );

  it("reuses the same PrismaClient across imports (singleton pattern)", async () => {
    const first = (await import("../src/index")).prisma;
    vi.resetModules();
    const second = (await import("../src/index")).prisma;
    expect(first).toBe(second);
  });

  it("stores the singleton on globalThis under a namespaced key", async () => {
    await import("../src/index");
    const cached = (globalThis as unknown as Record<string, unknown>)
      .__papercranePrisma;
    expect(cached).toBeDefined();
  });

  it("re-exports the Prisma namespace and enum types", async () => {
    const mod = await import("../src/index");
    expect(mod.Prisma).toBeDefined();
  });
});
