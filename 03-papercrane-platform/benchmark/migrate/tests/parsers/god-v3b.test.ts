import { describe, it, expect } from "vitest";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import godV3b from "../../src/parsers/god-v3b.js";
import { parse as parseGod } from "../../src/parsers/god-v3b.js";
import { parse as parse5g51 } from "../../src/parsers/fivegfiveone-v4.js";
import { parse as parseRbx1 } from "../../src/parsers/rbx1.js";
import { getParser, ALL_SOURCES } from "../../src/parsers/index.js";
import { BenchmarkRunSchema } from "../../src/schema.js";

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURES = resolve(here, "..", "fixtures");

describe("parsers.registry", () => {
  it("returns a parser for every known source", () => {
    for (const id of ALL_SOURCES) {
      expect(getParser(id).sourceId).toBe(id);
    }
  });

  it("throws on unknown source id", () => {
    expect(() => getParser("not-a-source")).toThrow(/unknown source/);
  });
});

describe("god-v3b parser", () => {
  it("exposes the correct sourceId", () => {
    expect(godV3b.sourceId).toBe("god-v3b");
  });

  it("parses the fixture directory into a valid BenchmarkRun", async () => {
    const dir = resolve(FIXTURES, "god-v3b-sample");
    const runs = await parseGod(dir);
    expect(runs.length).toBe(1);
    const run = runs[0]!;

    expect(() => BenchmarkRunSchema.parse(run)).not.toThrow();

    expect(run.run_id).toBe("god-v3b-run-0001");
    expect(run.source).toBe("god-v3b");
    expect(run.target_id).toBe("pd-l1");
    expect(run.designs).toHaveLength(3);
    expect(run.designs.map((d) => d.seed).sort()).toEqual([1, 2, 3]);

    // Hashes must be 64-char hex (deterministic from fixture content).
    expect(run.config_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(run.compute_env_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(run.results_digest).toMatch(/^[0-9a-f]{64}$/);
  });

  it("produces a deterministic results_digest", async () => {
    const dir = resolve(FIXTURES, "god-v3b-sample");
    const a = await parseGod(dir);
    const b = await parseGod(dir);
    expect(a[0]!.results_digest).toBe(b[0]!.results_digest);
    expect(a[0]!.config_hash).toBe(b[0]!.config_hash);
  });

  it("skips runs whose campaign field does not match", async () => {
    // 5g51 fixture has campaign='5g51-v4' — god parser should skip it.
    const dir = resolve(FIXTURES, "5g51-v4-sample");
    const runs = await parseGod(dir);
    expect(runs).toHaveLength(0);
  });
});

describe("5g51-v4 parser", () => {
  it("parses the fixture directory", async () => {
    const dir = resolve(FIXTURES, "5g51-v4-sample");
    const runs = await parse5g51(dir);
    expect(runs).toHaveLength(1);
    const run = runs[0]!;
    expect(run.source).toBe("5g51-v4");
    expect(run.target_id).toBe("5g51");
    expect(run.designs).toHaveLength(3);
    // Extra metric (helicity) must be preserved on each design.
    expect(run.designs[0]!.metrics).toHaveProperty("helicity");
  });
});

describe("rbx1 parser", () => {
  it("parses the fixture directory", async () => {
    const dir = resolve(FIXTURES, "rbx1-sample");
    const runs = await parseRbx1(dir);
    expect(runs).toHaveLength(1);
    const run = runs[0]!;
    expect(run.source).toBe("rbx1");
    expect(run.target_id).toBe("rbx1");
    expect(run.designs).toHaveLength(3);
  });
});
