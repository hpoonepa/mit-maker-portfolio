import { describe, expect, it } from "vitest";
import { isToolTierAllowed } from "./toolTier";

describe("isToolTierAllowed", () => {
  it("falls back to free when an organization has no usage period yet", () => {
    expect(isToolTierAllowed("free", undefined)).toBe(true);
    expect(isToolTierAllowed("pro", undefined)).toBe(false);
  });

  it("allows tiers at or below the organization tier", () => {
    expect(isToolTierAllowed("free", "pro")).toBe(true);
    expect(isToolTierAllowed("pro", "pro")).toBe(true);
    expect(isToolTierAllowed("frontier", "pro")).toBe(false);
  });
});
