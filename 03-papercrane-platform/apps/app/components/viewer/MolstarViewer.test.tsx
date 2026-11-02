import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const controls = vi.hoisted(() => ({
  status: "error" as "idle" | "loading" | "ready" | "error",
  error: "Network error: retry" as string | null,
  structureLoading: false,
  activeRepresentation: "cartoon" as "cartoon" | "atoms",
  structureSummary: { atomCount: 30, residueCount: 3, backboneBreaks: 0, chains: [{ chainId: "A", residues: [] }] },
  retryStructure: vi.fn(),
  resetCamera: vi.fn(),
  takeScreenshot: vi.fn().mockResolvedValue(null),
  reducedMotion: false,
}));

vi.mock("./useMolstar", () => ({
  useMolstar: () => controls,
}));

import { MolstarViewer } from "./MolstarViewer";

describe("MolstarViewer states", () => {
  beforeEach(() => {
    controls.status = "error";
    controls.error = "Network error: retry";
    controls.structureLoading = false;
    controls.activeRepresentation = "cartoon";
    controls.structureSummary.backboneBreaks = 0;
    controls.retryStructure.mockReset();
  });

  afterEach(cleanup);

  it("offers a real retry action after a structure load failure", () => {
    render(<MolstarViewer structureUrl="https://r2.example/target.cif" />);

    fireEvent.click(screen.getByRole("button", { name: /retry structure/i }));
    expect(controls.retryStructure).toHaveBeenCalledTimes(1);
  });

  it("distinguishes structure parsing from viewer initialization", () => {
    controls.status = "ready";
    controls.error = null;
    controls.structureLoading = true;
    render(<MolstarViewer structureUrl="https://r2.example/target.cif" />);

    expect(screen.getByText(/loading structure/i)).toBeTruthy();
  });

  it("hides binder labeling when the structure has no binder chains", () => {
    controls.status = "ready";
    controls.error = null;
    render(
      <MolstarViewer
        structureUrl="https://r2.example/target.cif"
        targetChainIds={["A", "B", "C"]}
        binderChainIds={[]}
      />,
    );

    expect(screen.getByText("Target A")).toBeTruthy();
    expect(screen.queryByText(/Binder/)).toBeNull();
  });
});

it("labels the actual chain without inventing target and binder roles", () => {
  controls.status = "ready";
  controls.error = null;
  render(<MolstarViewer structureUrl="/result.cif" />);
  expect(screen.getByText("Chain A")).toBeTruthy();
  expect(screen.queryByText(/Target|Binder/)).toBeNull();
});

it("explains broken coordinates while keeping representation controls available", () => {
  controls.status = "ready";
  controls.error = null;
  controls.structureSummary.backboneBreaks = 23;
  controls.activeRepresentation = "atoms";
  render(<MolstarViewer structureUrl="/result.cif" />);
  expect(screen.getByText(/23 backbone breaks in the saved coordinates/)).toBeTruthy();
  expect(screen.getByRole("button", {name: "Switch representation (current: atoms)"})).toBeTruthy();
});
