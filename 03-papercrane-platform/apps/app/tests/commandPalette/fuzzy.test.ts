import { describe, it, expect } from "vitest";
import { fuzzyMatch, fuzzyRank } from "@/lib/commandPalette/fuzzy";

/**
 * fuzzy match helper tests
 *
 * The palette must rank commands without pulling in fuse.js or any other
 * dependency. Requirements we verify:
 *   1. empty queries are a pass-through (show everything in original order)
 *   2. exact substring matches outrank scattered-letter matches
 *   3. prefix matches outrank mid-string matches
 *   4. completely non-matching queries return score 0 / are filtered
 *   5. case-insensitivity
 */
describe("fuzzyMatch", () => {
  it("returns a truthy score for an exact substring", () => {
    expect(fuzzyMatch("Projects", "proj")).toBeGreaterThan(0);
  });

  it("returns 0 when no letters from query appear in order", () => {
    expect(fuzzyMatch("Dashboard", "zzzz")).toBe(0);
  });

  it("is case-insensitive", () => {
    const lower = fuzzyMatch("Dashboard", "dash");
    const upper = fuzzyMatch("Dashboard", "DASH");
    expect(lower).toBeGreaterThan(0);
    expect(lower).toBe(upper);
  });

  it("ranks prefix matches above mid-string matches", () => {
    const prefix = fuzzyMatch("Projects", "pro");
    const middle = fuzzyMatch("Deep Projects Archive", "pro");
    expect(prefix).toBeGreaterThan(middle);
  });

  it("ranks contiguous substring matches above scattered matches", () => {
    const contiguous = fuzzyMatch("upload target", "upt");
    const scattered = fuzzyMatch("unlock private tier", "upt");
    expect(contiguous).toBeGreaterThan(scattered);
  });

  it("treats keywords as equally valid match targets", () => {
    const score = fuzzyMatch("Submit Job", "run", ["run", "execute"]);
    expect(score).toBeGreaterThan(0);
  });
});

describe("fuzzyRank", () => {
  const items = [
    { id: "a", title: "Projects", keywords: [] },
    { id: "b", title: "Jobs", keywords: ["run", "submit"] },
    { id: "c", title: "Go to Projects", keywords: ["nav"] },
    { id: "d", title: "Create Project", keywords: ["new"] },
    { id: "e", title: "Totally Unrelated", keywords: [] },
  ];

  it("returns all items in original order when query is empty", () => {
    const ranked = fuzzyRank(items, "");
    expect(ranked.map((item) => item.id)).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("returns all items in original order when query is whitespace", () => {
    const ranked = fuzzyRank(items, "   ");
    expect(ranked.map((item) => item.id)).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("drops items that do not match at all", () => {
    const ranked = fuzzyRank(items, "project");
    const ids = ranked.map((item) => item.id);
    expect(ids).toContain("a");
    expect(ids).toContain("c");
    expect(ids).toContain("d");
    expect(ids).not.toContain("e");
  });

  it("ranks prefix matches first", () => {
    const ranked = fuzzyRank(items, "proj");
    expect(ranked[0]?.id).toBe("a");
  });

  it("uses keywords when title does not match", () => {
    const ranked = fuzzyRank(items, "run");
    expect(ranked.map((item) => item.id)).toContain("b");
  });
});
