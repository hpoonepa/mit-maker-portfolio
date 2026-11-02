import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ build: vi.fn(), query: vi.fn() }));
vi.mock("@/lib/trpc/client", () => ({ trpc: {
  useUtils: () => ({ client: { designs: { exportPage: { query: mocks.query } } } }),
  designs: {
    listByProject: { useQuery: () => ({ data: { items: [{ id: "d1", seed: 1 }] } }) },
    listByJob: { useQuery: () => ({ data: { items: [{ id: "d1", seed: 1 }] } }) },
  },
} }));
vi.mock("@/lib/export/archive", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/export/archive")>()),
  buildResearchArchive: mocks.build,
}));
import { ExportPanel } from "./ExportPanel";

beforeEach(() => {
  mocks.query.mockResolvedValue({ items: [{ id: "d1", seed: 1 }], nextCursor: null });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL() { return "blob:archive"; }
    static revokeObjectURL() {}
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); mocks.build.mockReset(); mocks.query.mockReset(); });

describe("ExportPanel completion reporting", () => {
  it("keeps an incomplete archive visible and never records full completion", async () => {
    mocks.build.mockResolvedValue({ bytes: new Uint8Array([1]), manifest: {
      complete: false, exportedFiles: 1, requestedFiles: 2, failedFiles: 1, completeDesigns: 0,
    } });
    const onDone = vi.fn();
    render(<ExportPanel mode="job" targetId="j1" onDone={onDone} />);
    fireEvent.click(screen.getByRole("button", { name: "Download bundle" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("1/2 files exported"));
    expect(onDone).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Download bundle" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("reports completed designs only after every requested file is accounted for", async () => {
    mocks.build.mockResolvedValue({ bytes: new Uint8Array([1]), manifest: {
      complete: true, exportedFiles: 2, requestedFiles: 2, failedFiles: 0, completeDesigns: 1,
    } });
    const onDone = vi.fn();
    render(<ExportPanel mode="job" targetId="j1" onDone={onDone} />);
    fireEvent.click(screen.getByRole("button", { name: "Download bundle" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(1));
    expect(screen.getByRole("status").textContent).toContain("Archive ready");
  });
});
