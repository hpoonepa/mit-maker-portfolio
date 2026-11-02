import { describe, expect, it } from "vitest";
import { interpretDesign, readMetric } from "./MetricInterpretation";

describe("ipSAE metric resolution", () => {
  it.each([
    "ipSAE",
    "ipsae",
    "min_ipsae",
    "best_ipsae",
    "computational__boltz2_min_ipsae",
  ])("recognises %s as ipSAE", (key) => {
    expect(readMetric({ [key]: 0.81 }, "ipSAE")).toBe(0.81);
  });

  it("uses a stored research-schema ipSAE value in the design verdict", () => {
    const verdict = interpretDesign({
      computational__boltz2_min_ipsae: 0.81,
      DockQ: 0.3,
      ptmenergy: -1.4,
    });

    expect(verdict.criteria.find((item) => item.metric === "ipSAE")?.value).toBe(
      0.81,
    );
    expect(verdict.level).toBe("strong");
  });

  it("does not substitute ipTM or mean PAE when ipSAE was not computed", () => {
    expect(readMetric({ ipTM: 0.82, pae_mean: 2.1 }, "ipSAE")).toBeNull();
  });
});
