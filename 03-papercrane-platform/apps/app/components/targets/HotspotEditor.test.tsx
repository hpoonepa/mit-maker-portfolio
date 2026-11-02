import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChainEntry } from "@/lib/pdb/parse";

const mocks = vi.hoisted(() => ({
  mutateAsync: vi.fn(),
  invalidateGet: vi.fn(),
  invalidateList: vi.fn(),
}));

vi.mock("@/lib/trpc/client", () => ({
  trpc: {
    useUtils: () => ({
      targets: {
        get: { invalidate: mocks.invalidateGet },
        list: { invalidate: mocks.invalidateList },
      },
    }),
    targets: {
      updateHotspots: {
        useMutation: () => ({
          mutateAsync: mocks.mutateAsync,
          isPending: false,
        }),
      },
    },
  },
}));

vi.mock("@/components/targets/HotspotPickerTabs", () => ({
  HotspotPickerTabs: ({
    selected,
    onChange,
  }: {
    selected: Set<number>;
    onChange: (next: Set<number>) => void;
  }) => (
    <button
      type="button"
      onClick={() => onChange(new Set([...selected, 2]))}
    >
      Add residue 2
    </button>
  ),
}));

vi.mock("@/components/targets/ResidueList", () => ({
  ResidueList: ({ onClear }: { onClear: () => void }) => (
    <button type="button" onClick={onClear}>
      Clear all
    </button>
  ),
}));

import { HotspotEditor } from "./HotspotEditor";

const chain: ChainEntry = {
  id: "A",
  sequence: "AGS",
  residues: [
    { index: 1, authSeqId: 1, insCode: "", resName: "ALA", oneLetter: "A" },
    { index: 2, authSeqId: 2, insCode: "", resName: "GLY", oneLetter: "G" },
    { index: 3, authSeqId: 3, insCode: "", resName: "SER", oneLetter: "S" },
  ],
};

describe("HotspotEditor", () => {
  beforeEach(() => {
    mocks.mutateAsync.mockReset().mockResolvedValue({ target: {} });
    mocks.invalidateGet.mockReset().mockResolvedValue(undefined);
    mocks.invalidateList.mockReset().mockResolvedValue(undefined);
  });

  afterEach(cleanup);

  it("persists the selected chain and sorted residue positions", async () => {
    render(
      <HotspotEditor
        targetId="target-1"
        chain={chain}
        initialHotspots={[3]}
      />,
    );

    const save = screen.getByRole("button", { name: /save hotspots/i });
    expect(save).toHaveProperty("disabled", true);
    expect(screen.getByRole("status").textContent).toMatch(/up to date/i);

    fireEvent.click(screen.getByRole("button", { name: /add residue 2/i }));
    expect(save).toHaveProperty("disabled", false);
    expect(screen.getByRole("status").textContent).toMatch(/unsaved changes/i);
    fireEvent.click(save);

    await waitFor(() => {
      expect(mocks.mutateAsync).toHaveBeenCalledWith({
        targetId: "target-1",
        hotspots: [{ chain: "A", residues: [2, 3] }],
      });
    });
    expect(mocks.invalidateGet).toHaveBeenCalledWith({ id: "target-1" });
    expect(mocks.invalidateList).toHaveBeenCalled();
    expect(save).toHaveProperty("disabled", true);
    expect(screen.getByRole("status").textContent).toMatch(/saved/i);
    expect(screen.getByText(/saved /i)).toBeTruthy();
  });

  it("can save an empty array to clear previously stored hotspots", async () => {
    render(
      <HotspotEditor
        targetId="target-1"
        chain={chain}
        initialHotspots={[3]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /clear all/i }));
    fireEvent.click(screen.getByRole("button", { name: /save hotspots/i }));

    await waitFor(() => {
      expect(mocks.mutateAsync).toHaveBeenCalledWith({
        targetId: "target-1",
        hotspots: [],
      });
    });
  });

  it("surfaces a useful error and keeps edits dirty when persistence fails", async () => {
    mocks.mutateAsync.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(
      <HotspotEditor
        targetId="target-1"
        chain={chain}
        initialHotspots={[3]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /add residue 2/i }));
    const save = screen.getByRole("button", { name: /save hotspots/i });
    fireEvent.click(save);

    expect(
      await screen.findByText(/can't reach the server/i),
    ).toBeTruthy();
    expect(save).toHaveProperty("disabled", false);
  });
});
