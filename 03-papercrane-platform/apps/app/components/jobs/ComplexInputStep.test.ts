import { describe, expect, it } from "vitest";

import {
  isUploadedStructureReference,
  isValidPdbId,
  isValidStructureReference,
} from "./ComplexInputStep";

describe("complex structure references", () => {
  it("accepts RCSB ids and Paper Crane upload keys", () => {
    expect(isValidPdbId(" 1abc ")).toBe(true);
    expect(isUploadedStructureReference("orgs/org-1/uploads/target.cif")).toBe(
      true,
    );
    expect(isValidStructureReference("orgs/org-1/uploads/target.cif")).toBe(
      true,
    );
  });

  it("rejects labels, incomplete keys, and malformed PDB ids", () => {
    expect(isValidStructureReference("target.cif")).toBe(false);
    expect(isValidStructureReference("orgs/org-1/")).toBe(false);
    expect(isValidStructureReference("ABCD")).toBe(false);
  });
});
