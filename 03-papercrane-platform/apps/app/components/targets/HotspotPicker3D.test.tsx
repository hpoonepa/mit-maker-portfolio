import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const viewer = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));

vi.mock("next/dynamic", () => ({
  __esModule: true,
  default: () =>
    function ViewerStub(props: Record<string, unknown>) {
      viewer.props = props;
      return <div data-testid="viewer-stub" />;
    },
}));

import { HotspotPicker3D } from "./HotspotPicker3D";

describe("HotspotPicker3D", () => {
  beforeEach(() => {
    viewer.props = null;
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:target-structure"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(cleanup);

  it("forwards valid target-chain clicks and ignores non-residue picks", async () => {
    const onToggle = vi.fn();
    render(
      <HotspotPicker3D
        pdbText="HEADER TEST\nATOM"
        chainId="A"
        selected={new Set()}
        onToggle={onToggle}
        atCap={false}
        residues={[1, 2, 3]}
      />,
    );

    await waitFor(() => expect(viewer.props).not.toBeNull());
    expect(viewer.props?.format).toBe("pdb");
    expect(viewer.props?.targetChainIds).toEqual(["A"]);
    expect(viewer.props?.binderChainIds).toEqual([]);

    const click = viewer.props?.onResidueClick as
      | ((id: { chain: string; resi: number }) => void)
      | undefined;
    click?.({ chain: "A", resi: 2 });
    click?.({ chain: "A", resi: 99 });
    click?.({ chain: "B", resi: 2 });

    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onToggle).toHaveBeenCalledWith(2);
  });

  it("sends a fresh focus request and shows camera progress", async () => {
    render(
      <HotspotPicker3D
        pdbText="HEADER TEST\nATOM"
        chainId="A"
        selected={new Set([2, 3])}
        onToggle={vi.fn()}
        atCap={false}
        residues={[1, 2, 3]}
      />,
    );

    await waitFor(() => expect(viewer.props).not.toBeNull());
    expect(viewer.props?.focusHighlightsRequest).toBe(0);
    fireEvent.click(
      screen.getByRole("button", { name: /center camera on selected hotspots/i }),
    );

    await waitFor(() => {
      expect(viewer.props?.focusHighlightsRequest).toBe(1);
    });
    expect(screen.getByText("Centering…")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toMatch(/centering camera on 2/i);
  });

  it("detects mmCIF text and loads Molstar with the correct parser", async () => {
    render(
      <HotspotPicker3D
        pdbText={"data_demo\nloop_\n_atom_site.group_PDB\nATOM"}
        chainId="A"
        selected={new Set()}
        onToggle={vi.fn()}
        atCap={false}
        residues={[1]}
      />,
    );

    await waitFor(() => expect(viewer.props?.format).toBe("cif"));
  });

  it("renders every structure chain as target and never invents a binder", async () => {
    render(
      <HotspotPicker3D
        pdbText="HEADER MULTICHAIN\nATOM"
        chainId="C"
        targetChainIds={["A", "B", "C"]}
        selected={new Set()}
        onToggle={vi.fn()}
        atCap={false}
        residues={[1]}
      />,
    );

    await waitFor(() => expect(viewer.props).not.toBeNull());
    expect(viewer.props?.targetChainIds).toEqual(["A", "B", "C"]);
    expect(viewer.props?.binderChainIds).toEqual([]);
  });
});
