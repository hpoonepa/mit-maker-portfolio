import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { UploadPhase } from "@/components/upload/PdbUploadProgress";
import { Step3 } from "./CreateTargetWizard";

/**
 * Regression: the confirm-step error banner used to be `submitError &&
 * phase.phase !== "error"`, which HID the error exactly when one occurred.
 * For the RCSB source there is no PdbUploadProgress to surface it, so a failed
 * "Create target" silently did nothing. The banner must render whenever a
 * submitError is set on a non-upload source: including the "error" phase.
 */

const baseProps = {
  source: "rcsb" as const,
  name: "sa",
  pdbId: "6X1A",
  chain: "A",
  chosenChainSeq: "",
  chosenChainResidues: 0,
  payloadFilename: "",
  payloadSize: 0,
};

describe("CreateTargetWizard Step3 error banner", () => {
  it("shows the error on the 'error' phase for an RCSB target (was silently hidden)", () => {
    render(
      <Step3
        {...baseProps}
        phase={{ phase: "error", message: "boom" } as UploadPhase}
        submitError="Could not download 6X1A from RCSB (status 404)"
      />,
    );
    expect(
      screen.getByText("Could not download 6X1A from RCSB (status 404)"),
    ).toBeTruthy();
  });

  it("still shows validation errors on the idle phase", () => {
    render(
      <Step3
        {...baseProps}
        phase={{ phase: "idle" } as UploadPhase}
        submitError="Invalid PDB ID"
      />,
    );
    expect(screen.getByText("Invalid PDB ID")).toBeTruthy();
  });
});
