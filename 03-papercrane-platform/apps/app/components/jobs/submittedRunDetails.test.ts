import { describe, expect, it } from "vitest";
import { submittedRunDetails } from "./submittedRunDetails";

describe("submitted run details", () => {
  it("prioritizes the canonical request over adapter mirrors", () => {
    expect(
      submittedRunDetails({
        request: {
          targetPdb: "5O45",
          targetChain: "A",
          toolParams: {
            targetPdb: "1CRN",
            targetChain: "B",
            binder_length_range: [60, 150],
          },
        },
      }),
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: "Target", value: "5O45" }),
        expect.objectContaining({ label: "Chain", value: "A" }),
        expect.objectContaining({
          label: "Binder length",
          value: "60–150 residues",
        }),
      ]),
    );
  });
  it("shows explicit contigs instead of a length they override", () => {
    const rows = submittedRunDetails({
      toolParams: { contigs: "A1-100/0 60-80", binder_length_range: [60, 150] },
    });
    expect(rows.find((row) => row.label === "Contigs")?.value).toBe(
      "A1-100/0 60-80",
    );
    expect(rows.find((row) => row.label === "Binder length")).toBeUndefined();
  });
  it("does not invent a target or chain for sequence input", () => {
    expect(
      submittedRunDetails({ toolParams: { sequences: ["AAA", "CCC"] } }),
    ).toEqual([{ label: "Input sequences", value: "2" }]);
  });
});
