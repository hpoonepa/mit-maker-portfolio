import { describe, expect, it } from "vitest";

import { buildJobRequest } from "./buildRequest";

const base = {
  ligandReq: "none" as const,
  ligand: { mode: "none" as const },
  complex: {
    targetPdb: "",
    targetChain: "",
    partnerPdb: "",
    partnerChain: "",
  },
  backbone: { pdb: "", chain: "" },
  sequences: { raw: "", sequences: [] },
  effectiveTargetPdb: "",
  targetChain: null,
  projectId: null,
  targetId: null,
};

describe("buildJobRequest", () => {
  it("mirrors target identity into adapter params", () => {
    expect(
      buildJobRequest({
        ...base,
        inputKind: "target",
        effectiveTargetPdb: "1ABC",
        targetChain: "A",
        projectId: "project-1",
        targetId: "target-1",
      }),
    ).toEqual({
      fields: { targetPdb: "1ABC", targetChain: "A" },
      toolParams: {
        projectId: "project-1",
        targetId: "target-1",
        targetPdb: "1ABC",
        targetChain: "A",
        target_chain: "A",
        chain: "A",
        chainId: "A",
      },
    });
  });

  it("mirrors both complex structures and chains into adapter params", () => {
    expect(
      buildJobRequest({
        ...base,
        inputKind: "complex",
        complex: {
          targetPdb: "1ABC",
          targetChain: "A",
          partnerPdb: "2DEF",
          partnerChain: "B",
        },
      }),
    ).toEqual({
      fields: {
        targetPdb: "1ABC",
        targetChain: "A",
        partnerPdb: "2DEF",
        partnerChain: "B",
      },
      toolParams: {
        targetPdb: "1ABC",
        targetChain: "A",
        target_chain: "A",
        chain: "A",
        chainId: "A",
        partnerPdb: "2DEF",
        partnerChain: "B",
        partner_chain: "B",
      },
    });
  });

  it("preserves private upload keys for both complex structures", () => {
    const targetPdb = "orgs/org-1/uploads/target.cif";
    const partnerPdb = "orgs/org-1/uploads/partner.pdb";
    expect(
      buildJobRequest({
        ...base,
        inputKind: "complex",
        complex: {
          targetPdb,
          targetChain: "",
          partnerPdb,
          partnerChain: "",
        },
      }),
    ).toEqual({
      fields: { targetPdb, partnerPdb },
      toolParams: { targetPdb, partnerPdb },
    });
  });

  it("keeps sequence-only input out of the request top level", () => {
    const sequences = [{ id: "query", sequence: "ACDE" }];
    expect(
      buildJobRequest({
        ...base,
        inputKind: "sequences",
        sequences: { raw: ">query\nACDE", sequences },
      }),
    ).toEqual({
      fields: {},
      toolParams: { sequences },
    });
  });
});
