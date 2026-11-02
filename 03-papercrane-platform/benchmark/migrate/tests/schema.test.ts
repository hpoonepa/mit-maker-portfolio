import { describe, it, expect } from "vitest";
import {
  BenchmarkRunSchema,
  BenchmarkCellSchema,
  DesignResultSchema,
  RunManifestSchema,
  SeedRangeSchema,
} from "../src/schema.js";

const VALID_HASH = "a".repeat(64);
const VALID_HASH_2 = "b".repeat(64);
const VALID_HASH_3 = "c".repeat(64);
const VALID_HASH_4 = "d".repeat(64);

function validDesign(seed = 1) {
  return {
    seed,
    sequence: "MKTAYIAKQRQISFVKSHFSRQLEERL",
    structurePath: `designs/seed_${seed}.pdb`,
    metrics: { ipsae: 0.82, dockq: 0.41, ptmenergy: -1.8 },
  };
}

function validRun() {
  return {
    run_id: "pc-run-0001",
    target_id: "pd-l1",
    tool_id: "papercrane",
    tool_version: "v4",
    config_hash: VALID_HASH,
    seed_range: [1, 60] as [number, number],
    compute_env_hash: VALID_HASH_2,
    designs: [validDesign(1), validDesign(2)],
    cost_usd: 4.28,
    wallclock_sec: 1843,
    results_digest: VALID_HASH_3,
    source: "god-v3b" as const,
  };
}

describe("DesignResultSchema", () => {
  it("accepts a valid design", () => {
    expect(() => DesignResultSchema.parse(validDesign())).not.toThrow();
  });

  it("rejects a sequence containing non-amino-acid characters", () => {
    const bad = { ...validDesign(), sequence: "MKTAY123ZZ" };
    expect(() => DesignResultSchema.parse(bad)).toThrow();
  });

  it("rejects a negative seed", () => {
    const bad = { ...validDesign(), seed: -5 };
    expect(() => DesignResultSchema.parse(bad)).toThrow();
  });

  it("allows passthrough extra metrics", () => {
    const d = {
      ...validDesign(),
      metrics: { ipsae: 0.8, helicity: 0.92, custom_metric: 3.14 },
    };
    expect(() => DesignResultSchema.parse(d)).not.toThrow();
  });
});

describe("SeedRangeSchema", () => {
  it("accepts [1, 60]", () => {
    expect(() => SeedRangeSchema.parse([1, 60])).not.toThrow();
  });
  it("rejects inverted range", () => {
    expect(() => SeedRangeSchema.parse([60, 1])).toThrow();
  });
});

describe("BenchmarkRunSchema", () => {
  it("accepts a valid run", () => {
    expect(() => BenchmarkRunSchema.parse(validRun())).not.toThrow();
  });

  it("rejects an invalid config_hash (not 64 hex chars)", () => {
    const bad = { ...validRun(), config_hash: "not-a-hash" };
    expect(() => BenchmarkRunSchema.parse(bad)).toThrow();
  });

  it("rejects an empty designs array", () => {
    const bad = { ...validRun(), designs: [] };
    expect(() => BenchmarkRunSchema.parse(bad)).toThrow();
  });

  it("rejects an unknown source", () => {
    const bad = { ...validRun(), source: "random-campaign" };
    expect(() => BenchmarkRunSchema.parse(bad)).toThrow();
  });
});

describe("BenchmarkCellSchema", () => {
  const validCell = {
    target_id: "pd-l1",
    tool_id: "papercrane",
    tool_version: "v4",
    config_hash: VALID_HASH,
    seed_range: [1, 60] as [number, number],
    compute_env_hash: VALID_HASH_2,
    run_ids: ["pc-run-0001"],
    hit_rate: 0.47,
    hit_rate_ci_low: 0.43,
    hit_rate_ci_high: 0.51,
  };

  it("accepts a valid cell", () => {
    expect(() => BenchmarkCellSchema.parse(validCell)).not.toThrow();
  });

  it("rejects a hit_rate above 1", () => {
    const bad = { ...validCell, hit_rate: 1.7 };
    expect(() => BenchmarkCellSchema.parse(bad)).toThrow();
  });

  it("rejects an empty run_ids list", () => {
    const bad = { ...validCell, run_ids: [] };
    expect(() => BenchmarkCellSchema.parse(bad)).toThrow();
  });
});

describe("RunManifestSchema", () => {
  const validManifest = {
    run_id: "pc-run-0001",
    benchmark_version: "1.0",
    target_fingerprint: VALID_HASH,
    tool: {
      id: "protenix",
      version: "2025.03.14",
      git_sha: "4f9d2e1abc000000000000000000000000000000",
    },
    config_hash: VALID_HASH_2,
    config: { lr: 0.01, seeds: 60 },
    seed_range: [1, 60] as [number, number],
    compute: {
      gpu: "A100-80GB",
      driver: "550.54.15",
      cuda: "12.4",
      container_digest: VALID_HASH_3,
      provider: "vast.ai",
    },
    results_digest: VALID_HASH_4,
    cost_usd: 4.28,
    wallclock_sec: 1843,
  };

  it("accepts a valid manifest", () => {
    expect(() => RunManifestSchema.parse(validManifest)).not.toThrow();
  });

  it("rejects a manifest missing tool.git_sha", () => {
    const bad = {
      ...validManifest,
      tool: { id: "protenix", version: "2025.03.14" },
    };
    expect(() => RunManifestSchema.parse(bad)).toThrow();
  });

  it("rejects a manifest with negative cost", () => {
    const bad = { ...validManifest, cost_usd: -1 };
    expect(() => RunManifestSchema.parse(bad)).toThrow();
  });
});
