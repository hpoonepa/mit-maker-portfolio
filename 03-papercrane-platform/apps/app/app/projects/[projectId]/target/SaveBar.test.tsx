import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  HotspotStoreProvider,
  useHotspotStore,
} from "@/lib/hotspot-store";

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  invalidateList: vi.fn(),
  invalidateGet: vi.fn(),
}));

vi.mock("@/lib/trpc/client", () => ({
  trpc: {
    useUtils: () => ({
      targets: {
        list: { invalidate: mocks.invalidateList },
        get: { invalidate: mocks.invalidateGet },
      },
    }),
    targets: {
      saveHotspots: {
        useMutation: () => ({
          mutate: mocks.mutate,
          isPending: false,
          isSuccess: false,
          error: null,
        }),
      },
    },
  },
}));

import { SaveBar } from "./page";

function ClearSelection() {
  const store = useHotspotStore();
  return (
    <button type="button" onClick={store.clear}>
      Clear selection
    </button>
  );
}

describe("project target SaveBar", () => {
  beforeEach(() => {
    mocks.mutate.mockReset();
    mocks.invalidateList.mockReset();
    mocks.invalidateGet.mockReset();
  });

  afterEach(cleanup);

  it("allows a persisted hotspot set to be cleared and saved", () => {
    render(
      <HotspotStoreProvider initial={[{ chain: "A", resi: 41 }]}>
        <ClearSelection />
        <SaveBar projectId="project-1" />
      </HotspotStoreProvider>,
    );

    const save = screen.getByRole("button", { name: /save hotspots/i });
    expect(save).toHaveProperty("disabled", true);

    fireEvent.click(screen.getByRole("button", { name: /clear selection/i }));
    expect(save).toHaveProperty("disabled", false);
    fireEvent.click(save);

    expect(mocks.mutate).toHaveBeenCalledWith({
      projectId: "project-1",
      hotspots: [],
    });
  });
});
