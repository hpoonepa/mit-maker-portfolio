import { describe, expect, it } from "vitest";
import {
  jobDesignKey,
  jobLogKey,
  jobMetricsKey,
  jobPrefix,
  orgPrefix,
  orgTargetKey,
} from "../src/paths";

/**
 * Path-builder contract (plan 01 §6):
 *   orgs/{org_id}/targets/{target_id}/input.pdb
 *   orgs/{org_id}/jobs/{job_id}/designs/{seed}.cif
 *   orgs/{org_id}/jobs/{job_id}/logs/worker-{attempt}.log
 *
 * All ids are validated — empty or malformed ids must throw before we
 * interpolate them into a key (defence against path traversal).
 */
describe("orgTargetKey", () => {
  it("builds the canonical target input key", () => {
    expect(orgTargetKey("org_abc", "tgt_123")).toBe(
      "orgs/org_abc/targets/tgt_123/input.pdb",
    );
  });

  it("rejects empty org id", () => {
    expect(() => orgTargetKey("", "tgt_1")).toThrow(/orgId/);
  });

  it("rejects empty target id", () => {
    expect(() => orgTargetKey("org_1", "")).toThrow(/targetId/);
  });

  it("rejects path-traversal attempts", () => {
    expect(() => orgTargetKey("org_1", "../evil")).toThrow();
    expect(() => orgTargetKey("..", "tgt_1")).toThrow();
    expect(() => orgTargetKey("org_1", "a/b")).toThrow();
  });

  it("rejects leading underscore / dash (only alnum start)", () => {
    expect(() => orgTargetKey("_bad", "tgt_1")).toThrow();
    expect(() => orgTargetKey("-bad", "tgt_1")).toThrow();
  });
});

describe("jobDesignKey", () => {
  it("builds the canonical design key with integer seed", () => {
    expect(jobDesignKey("org_1", "job_xyz", 42)).toBe(
      "orgs/org_1/jobs/job_xyz/designs/42.cif",
    );
  });

  it("allows seed = 0", () => {
    expect(jobDesignKey("org_1", "job_xyz", 0)).toBe(
      "orgs/org_1/jobs/job_xyz/designs/0.cif",
    );
  });

  it("rejects non-integer seed", () => {
    expect(() => jobDesignKey("org_1", "job_xyz", 3.14)).toThrow(/seed/);
  });

  it("rejects negative seed", () => {
    expect(() => jobDesignKey("org_1", "job_xyz", -1)).toThrow(/seed/);
  });

  it("rejects empty job id", () => {
    expect(() => jobDesignKey("org_1", "", 0)).toThrow(/jobId/);
  });
});

describe("jobLogKey", () => {
  it("builds the worker log key with attempt number", () => {
    expect(jobLogKey("org_1", "job_xyz", 3)).toBe(
      "orgs/org_1/jobs/job_xyz/logs/worker-3.log",
    );
  });

  it("allows attempt = 0", () => {
    expect(jobLogKey("org_1", "job_xyz", 0)).toBe(
      "orgs/org_1/jobs/job_xyz/logs/worker-0.log",
    );
  });

  it("rejects non-integer attempt", () => {
    expect(() => jobLogKey("org_1", "job_xyz", 1.5)).toThrow(/attempt/);
  });

  it("rejects negative attempt", () => {
    expect(() => jobLogKey("org_1", "job_xyz", -1)).toThrow(/attempt/);
  });
});

describe("prefix helpers", () => {
  it("jobPrefix ends with trailing slash for ListObjectsV2", () => {
    expect(jobPrefix("org_1", "job_xyz")).toBe("orgs/org_1/jobs/job_xyz/");
  });

  it("orgPrefix covers an entire tenant", () => {
    expect(orgPrefix("org_1")).toBe("orgs/org_1/");
  });

  it("jobMetricsKey points at the parquet blob", () => {
    expect(jobMetricsKey("org_1", "job_xyz")).toBe(
      "orgs/org_1/jobs/job_xyz/metrics.parquet",
    );
  });

  it("prefix helpers reject empty ids", () => {
    expect(() => jobPrefix("", "job_1")).toThrow();
    expect(() => jobPrefix("org_1", "")).toThrow();
    expect(() => orgPrefix("")).toThrow();
  });
});
