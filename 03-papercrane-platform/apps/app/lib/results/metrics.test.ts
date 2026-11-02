import { describe, expect, it } from "vitest";
import { expectsCoordinates, formatResultMetric, resultMetrics, toolLabel } from "./metrics";

describe("native result metrics", () => {
  it("shows the real ProteinMPNN output without inventing structure or AI metrics", () => {
    const values = resultMetrics("proteinmpnn", { score: 0.8022, global_score: 0.8022, recovery: 0.5526, sample_perplexity: 2.2304425083, sequence: "MKT", length: 3, temperature: 0.1, meta_score: 0.8, composite: 0.9, rank: 1 });
    expect(values.map((v) => v.label)).toEqual(["Sequence score", "Global score", "Sequence recovery", "Perplexity"]);
    expect(values.map(formatResultMetric)).toEqual(["0.8022", "0.8022", "55.26%", "2.2304"]);
  });
  it("keeps zero scores and unfamiliar tool outputs, but omits nonfinite numbers", () => {
    const values = resultMetrics("custom", { energy: 0, something_new: 0.0000008, bad: NaN, worse: Infinity, note: "value" });
    expect(values.map((v) => v.key)).toEqual(["energy", "something_new"]);
    expect(values.map(formatResultMetric)).toEqual(["0", "8.000e-7"]);
    expect(values[0]!.direction).toBeUndefined();
  });
  it("deduplicates metric aliases without conflating measured and predicted DockQ", () => {
    const values = resultMetrics("boltz2", { ipTM: 0.7, iptm: 0.7, DockQ: 0.1, pDockQ: 0.8 });
    expect(values.map((v) => v.label)).toEqual(["ipTM", "DockQ", "pDockQ"]);
  });
  it("does not assume a CIF artifact contains coordinates", () => {
    for (const tool of ["proteinmpnn", "solublempnn", "ligandmpnn", "esm2", "esmc", "unknown"]) expect(expectsCoordinates(tool)).toBe(false);
    expect(expectsCoordinates("boltz2")).toBe(true);
    expect(expectsCoordinates("rfdiffusion+proteinmpnn")).toBe(false);
    expect(expectsCoordinates("rfdiffusion+proteinmpnn+boltz2")).toBe(true);
    expect(toolLabel("proteinmpnn")).toBe("ProteinMPNN");
  });
  it("shows native Boltz scales and distinguishes PDE from PAE", () => {
    const values = resultMetrics("boltz2", { chain_count: 1, complex_plddt: 0.5886309, pTM: 0.3317763, confidence_score: 0.5372601, complex_pde: 0.9011224, ipTM: 0, complex_iplddt: 0.5, complex_ipde: 0, protein_iptm: 0, ligand_iptm: 0 });
    expect(values.map(v => v.label)).toEqual(["pLDDT (0–1)", "pTM", "Model confidence (0–1)", "PDE (Å)"]);
    expect(values.map(formatResultMetric)).toEqual(["0.5886", "0.3318", "0.5373", "0.9011"]);
  });
  it("retains actual zero interface metrics when multiple chains or chain count is unknown", () => {
    for (const count of [undefined, 2]) {
      const values = resultMetrics("boltz2", { chain_count: count, ipTM: 0, complex_ipde: 0 });
      expect(values.map(v => v.key)).toEqual(["ipTM", "complex_ipde"]);
      expect(values.map(formatResultMetric)).toEqual(["0", "0"]);
    }
    expect(resultMetrics("custom", {chain_count: 1, ipTM: 0}).map(v => v.key)).toEqual(["ipTM"]);
  });

});
