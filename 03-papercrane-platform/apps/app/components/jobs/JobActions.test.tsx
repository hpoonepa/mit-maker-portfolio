import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/trpc/client", () => ({ trpc: {
  useUtils: () => ({ jobs: { get: { invalidate: vi.fn() }, list: { invalidate: vi.fn() } } }),
  jobs: { cancel: { useMutation: () => ({ mutate: vi.fn(), isPending: false, error: null }) } },
} }));
vi.mock("@/components/exports/ExportPanel", () => ({ ExportPanel: ({ mode, targetId }: { mode: string; targetId: string }) => <div data-testid="export-panel">{mode}:{targetId}</div> }));
import { JobActions } from "./JobActions";
afterEach(cleanup);

describe("job result download action", () => {
  it("opens the existing scoped export flow for this job", () => {
    render(<JobActions jobId="job-103" toolId="proteinmpnn" status="succeeded" />);
    fireEvent.click(screen.getByRole("button", { name: "Download all" }));
    expect(screen.getByTestId("export-panel").textContent).toBe("job:job-103");
    expect(screen.getByRole("button", { name: "Download all" }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("export-panel")).toBeNull();
  });
  it("does not offer result downloads before a job produces completed results", () => {
    render(<JobActions jobId="job-103" toolId="proteinmpnn" status="running" />);
    expect(screen.queryByRole("button", { name: "Download all" })).toBeNull();
  });
});


it("duplicates by ID without putting research inputs in the URL", () => {
  render(<JobActions jobId="job-103" toolId="proteinmpnn" status="succeeded" params={{ sequences: ["PRIVATESEQUENCE"] }} />);
  fireEvent.click(screen.getByRole("button", { name: "Duplicate job" }));
  expect(push).toHaveBeenCalledWith("/app/jobs/new?tool=proteinmpnn&cloneOf=job-103&preset=1");
});
