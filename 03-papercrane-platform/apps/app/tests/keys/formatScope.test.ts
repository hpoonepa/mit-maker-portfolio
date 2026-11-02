import { describe, it, expect } from "vitest";
import { formatScope, formatScopeDescription } from "@/lib/keys/formatScope";

/**
 * formatScope: turns ApiKeyScope enum values into human labels for badges.
 *
 * Contract:
 *   - every known scope returns a non-empty label (Title-case, ≤ 24 chars)
 *   - the wildcard "*" maps to the explicit label "All access" (not "Wildcard")
 *   - unknown scopes fall back to the raw string (defense in depth)
 *   - description returns a second line explaining consequences
 */
describe("formatScope", () => {
  it("maps known scopes to title-case labels", () => {
    expect(formatScope("jobs:read")).toBe("Jobs · read");
    expect(formatScope("jobs:write")).toBe("Jobs · write");
    expect(formatScope("designs:read")).toBe("Designs · read");
    expect(formatScope("targets:write")).toBe("Targets · write");
    expect(formatScope("usage:read")).toBe("Usage · read");
    expect(formatScope("usage:write")).toBe("Usage · write");
    expect(formatScope("keys:manage")).toBe("Keys · manage");
  });

  it("maps the wildcard to 'All access'", () => {
    expect(formatScope("*")).toBe("All access");
  });

  it("falls back to the raw value for unknown scopes", () => {
    // @ts-expect-error: testing defensive behaviour for unknown enum values
    expect(formatScope("future:scope")).toBe("future:scope");
  });

  it("labels are short enough to fit inside a badge", () => {
    const scopes = [
      "jobs:read",
      "jobs:write",
      "designs:read",
      "targets:write",
      "usage:read",
      "usage:write",
      "keys:manage",
      "*",
    ] as const;
    for (const s of scopes) {
      expect(formatScope(s).length).toBeLessThanOrEqual(24);
    }
  });
});

describe("formatScopeDescription", () => {
  it("returns a sentence for each known scope", () => {
    expect(formatScopeDescription("jobs:read")).toMatch(/job/i);
    expect(formatScopeDescription("keys:manage")).toMatch(/key/i);
    expect(formatScopeDescription("*")).toMatch(/every|all/i);
  });

  it("returns empty for unknown scopes", () => {
    // @ts-expect-error: unknown scope
    expect(formatScopeDescription("zzz")).toBe("");
  });
});
