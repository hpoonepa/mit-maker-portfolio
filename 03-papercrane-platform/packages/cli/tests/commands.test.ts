import { describe, expect, it } from "vitest";
import { formatJobLog, parseHotspots } from "../src/commands/jobs.js";
import { slugify } from "../src/commands/projects.js";

describe("slugify", () => {
  it("builds a server-valid project slug", () => {
    expect(slugify("  GLP-1R Binder Campaign  ")).toBe("glp-1r-binder-campaign");
  });
});

describe("parseHotspots", () => {
  it("groups residues by chain for the API schema", () => {
    expect(parseHotspots("A:42,A:87,B:10")).toEqual([
      { chain: "A", residues: [42, 87] },
      { chain: "B", residues: [10] },
    ]);
  });

  it("returns an empty list when omitted", () => {
    expect(parseHotspots()).toEqual([]);
  });
});

describe("formatJobLog", () => {
  it("renders timestamp, level, event, and redacted message", () => {
    const line = formatJobLog({
      id: "log-1",
      level: "error",
      event: "error",
      message: "token=[REDACTED]",
      metadata: { retryable: false },
      createdAt: "2026-07-13T18:00:00.000Z",
    });

    expect(line).toContain("2026-07-13T18:00:00.000Z");
    expect(line).toContain("ERROR");
    expect(line).toContain("token=[REDACTED]");
  });
});
