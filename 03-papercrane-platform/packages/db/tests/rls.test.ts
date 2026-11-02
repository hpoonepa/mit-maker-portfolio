import { describe, expect, it, vi } from "vitest";
import { setCurrentUser, withRlsUser } from "../src/rls";

/**
 * RLS helper contract:
 * - `setCurrentUser(tx, userId)` issues `SET LOCAL app.current_user = $1`
 *   with the user id as a bound parameter (NOT string interpolation).
 * - `withRlsUser(prisma, userId, fn)` opens an interactive transaction,
 *   sets the local var, runs `fn(tx)`, and propagates the result.
 * - If userId is not a valid UUID the helper throws before touching the tx.
 */
describe("rls helpers", () => {
  it("setCurrentUser uses parameterized SQL and never string-interpolates the uid", async () => {
    const executeRaw = vi.fn().mockResolvedValue(1);
    const tx = { $executeRaw: executeRaw };
    const uid = "00000000-0000-0000-0000-000000000001";

    await setCurrentUser(tx as never, uid);

    expect(executeRaw).toHaveBeenCalledTimes(1);
    const [strings, ...values] = executeRaw.mock.calls[0]!;
    // Prisma tagged template: strings is a TemplateStringsArray
    expect(Array.isArray(strings)).toBe(true);
    // uid must appear as a bound value, not baked into the SQL
    expect(values).toContain(uid);
    const joinedSql = (strings as string[]).join("?");
    // Postgres `SET LOCAL` cannot accept a bound parameter, so we use the
    // equivalent `set_config(name, value, is_local=true)` form, which is
    // parameterizable and exactly equivalent.
    expect(joinedSql).toMatch(/set_config\s*\(\s*'app\.current_user'/i);
    expect(joinedSql).toMatch(/true\s*\)/i); // is_local = true
    expect(joinedSql).not.toContain(uid);
  });

  it("setCurrentUser rejects non-UUID ids to prevent injection footguns", async () => {
    const tx = { $executeRaw: vi.fn() };
    await expect(
      setCurrentUser(tx as never, "'; DROP TABLE jobs; --")
    ).rejects.toThrow(/uuid/i);
    expect((tx.$executeRaw as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled();
  });

  it("withRlsUser opens a transaction, sets the var, and returns the fn result", async () => {
    const uid = "11111111-1111-1111-1111-111111111111";
    const executeRaw = vi.fn().mockResolvedValue(1);
    const txObj = { $executeRaw: executeRaw };
    const transaction = vi.fn(async (fn: (tx: unknown) => unknown) => fn(txObj));
    const prisma = { $transaction: transaction };

    const result = await withRlsUser(prisma as never, uid, async (tx) => {
      expect(tx).toBe(txObj);
      return "ok" as const;
    });

    expect(result).toBe("ok");
    expect(transaction).toHaveBeenCalledTimes(1);
    expect(transaction).toHaveBeenCalledWith(expect.any(Function), {
      maxWait: 10_000,
    });
    expect(executeRaw).toHaveBeenCalledTimes(1);
    const [, ...values] = executeRaw.mock.calls[0]!;
    expect(values).toContain(uid);
  });
});
