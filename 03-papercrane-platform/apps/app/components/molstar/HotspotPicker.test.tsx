import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  HotspotStoreProvider,
  useHotspotStore,
} from "@/lib/hotspot-store";

const viewer = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));

vi.mock("next/dynamic", () => ({
  __esModule: true,
  default: () =>
    function ViewerStub(props: Record<string, unknown>) {
      viewer.props = props;
      return <div data-testid="project-viewer-stub" />;
    },
}));

import { HotspotPicker } from "./HotspotPicker";

function SelectionProbe() {
  const store = useHotspotStore();
  return (
    <output data-testid="selection-probe">
      {[...store.selection].sort().join(",")}
    </output>
  );
}

describe("project HotspotPicker", () => {
  beforeEach(() => {
    viewer.props = null;
  });

  afterEach(cleanup);

  it("only accepts clicks from the configured target chain", async () => {
    render(
      <HotspotStoreProvider>
        <HotspotPicker
          structureUrl="https://r2.example/target.cif"
          targetChainIds={["A"]}
        />
        <SelectionProbe />
      </HotspotStoreProvider>,
    );

    await waitFor(() => expect(viewer.props).not.toBeNull());
    const click = viewer.props?.onResidueClick as
      | ((id: { chain: string; resi: number }) => void)
      | undefined;

    act(() => click?.({ chain: "B", resi: 9 }));
    expect(screen.getByTestId("selection-probe").textContent).toBe("");

    act(() => click?.({ chain: "A", resi: 9 }));
    expect(screen.getByTestId("selection-probe").textContent).toBe("A:9");
    await waitFor(() => {
      expect(viewer.props?.highlights).toEqual([
        expect.objectContaining({ chainId: "A", resi: 9 }),
      ]);
    });
  });
});
