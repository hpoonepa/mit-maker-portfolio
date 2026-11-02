import { describe, expect, it } from "vitest";
import { formatFastaRecord, wrapSequence } from "./fasta";

describe("FASTA model outputs", () => {
  it("preserves exact ProteinMPNN scores and provenance without invented rankings", () => {
    const record = formatFastaRecord({ id: "12345678-rest", seed: 103, sequence: "MKT", provenance: "real", metrics: { score: 0.987654, global_score: 1.234567, seq_recovery: 0, sample_perplexity: 2.6789, length: 3, seed: 103, rank: 1 } });
    expect(record).toBe(">design_103_12345678 provenance=real global_score=1.234567 sample_perplexity=2.6789 score=0.987654 seq_recovery=0\nMKT\n");
  });
  it("includes native numerical metrics while omitting nonfinite values and unsafe header keys", () => {
    const record = formatFastaRecord({ id: "abc", seed: 1, sequence: "M", metrics: { iptm: 0.84567, plddt: 82.7654, bad: NaN, infinite: Infinity, "new\nrecord": 2 } });
    expect(record).toBe(">design_1_abc provenance=unknown iptm=0.84567 plddt=82.7654\nM\n");
  });
  it("wraps sequences into 60-residue lines without truncation", () => {
    const sequence = "M".repeat(76);
    expect(wrapSequence(sequence)).toBe("M".repeat(60) + "\n" + "M".repeat(16));
  });
});
