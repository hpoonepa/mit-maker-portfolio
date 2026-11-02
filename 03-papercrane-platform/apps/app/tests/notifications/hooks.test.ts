import { describe, it, expect } from "vitest";
import {
  computeUnreadCount,
  formatUnreadBadge,
  categoryIcon,
} from "@/lib/notifications/hooks";

/**
 * Pure helpers exported from `lib/notifications/hooks.ts` so we can test
 * business rules without spinning up the tRPC/React-Query/Supabase stack.
 *
 * The full `useNotifications` / `useUnreadCount` / `markRead` hooks are
 * thin wrappers around `trpc.notifications.*` calls: their correctness
 * is enforced by the tRPC router tests (server side) and the provider
 * tests (client side), not here.
 */

describe("computeUnreadCount", () => {
  it("returns 0 for an empty list", () => {
    expect(computeUnreadCount([])).toBe(0);
  });

  it("counts only rows with readAt === null", () => {
    const rows = [
      { id: "a", readAt: null },
      { id: "b", readAt: new Date().toISOString() },
      { id: "c", readAt: null },
    ];
    expect(computeUnreadCount(rows)).toBe(2);
  });
});

describe("formatUnreadBadge", () => {
  it("returns empty string when count is zero", () => {
    expect(formatUnreadBadge(0)).toBe("");
  });

  it("returns the integer for 1..99", () => {
    expect(formatUnreadBadge(1)).toBe("1");
    expect(formatUnreadBadge(42)).toBe("42");
    expect(formatUnreadBadge(99)).toBe("99");
  });

  it("caps at 99+ for counts above 99", () => {
    expect(formatUnreadBadge(100)).toBe("99+");
    expect(formatUnreadBadge(9999)).toBe("99+");
  });
});

describe("categoryIcon", () => {
  it("maps every known category to a non-empty string identifier", () => {
    for (const cat of ["job", "billing", "webhook", "invite", "system"] as const) {
      const icon = categoryIcon(cat);
      expect(typeof icon).toBe("string");
      expect(icon.length).toBeGreaterThan(0);
    }
  });
});
