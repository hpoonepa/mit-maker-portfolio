import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const designsQuery = vi.hoisted(() => ({
  data: undefined as { items: unknown[] } | undefined,
  isError: false,
}));
vi.mock("@/lib/trpc/client", () => ({
  trpc: { designs: { listByJob: { useQuery: () => designsQuery } } },
}));
vi.mock("./JobActions", () => ({
  JobActions: () => (
    <div>
      <button>Cancel</button>
      <button>Duplicate job</button>
    </div>
  ),
}));
vi.mock("./JobCompletionAlerts", () => ({
  JobAlertToggle: () => (
    <input aria-label="Notify when finished" type="checkbox" />
  ),
}));
import { JobWaitScreen, shouldShowWaitScreen } from "./JobWaitScreen";

const baseProps = {
  jobId: "019f8a46-cb11-70ed-b2eb-cd9393c26119",
  toolId: "boltz2",
  numDesigns: 8,
  completedDesigns: 0,
  submittedAt: new Date().toISOString(),
};
beforeEach(() => {
  designsQuery.data = undefined;
  designsQuery.isError = false;
});
afterEach(cleanup);

describe("JobWaitScreen", () => {
  it("uses the active view until cancellation or work actually finishes", () => {
    for (const status of [
      "queued",
      "preparing",
      "running",
      "cancelling",
    ] as const) {
      expect(shouldShowWaitScreen({ status, estimatedTotalSeconds: 10 })).toBe(
        true,
      );
    }
    expect(
      shouldShowWaitScreen({ status: "succeeded", estimatedTotalSeconds: 10 }),
    ).toBe(false);
    expect(
      shouldShowWaitScreen({ status: "partial", estimatedTotalSeconds: 10 }),
    ).toBe(false);
  });
  it("shows one queued status, no fake progress, and real actions", () => {
    render(<JobWaitScreen {...baseProps} status="queued" />);
    expect(screen.getAllByText("Queued")).toHaveLength(1);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByText("Available results")).toBeNull();
    expect(
      screen.queryByText(/worker|Updating every|Run submitted|safe to leave/i),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Duplicate job" })).toBeTruthy();
  });
  it("shows zero completed work while running, then the actual completion fraction", () => {
    const { rerender } = render(
      <JobWaitScreen {...baseProps} status="running" />,
    );
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "0",
    );
    rerender(
      <JobWaitScreen {...baseProps} status="running" completedDesigns={2} />,
    );
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "25",
    );
  });
  it("shows saved inputs and spent credits rather than random seed values", () => {
    render(
      <JobWaitScreen
        {...baseProps}
        toolId="rfdiffusion"
        status="queued"
        targetLabel="5O45"
        params={{
          request: {
            targetPdb: "5O45",
            targetChain: "A",
            hotspots: [{ chain: "A", residues: [42, 45] }],
            constraints: { lengthRange: [60, 100] },
            seeds: [12345],
          },
        }}
      />,
    );
    const inputs = within(
      screen.getByRole("complementary", { name: "Submitted inputs" }),
    );
    expect(inputs.getByText("5O45")).toBeTruthy();
    expect(inputs.getByText("A: 42, 45")).toBeTruthy();
    expect(inputs.getByText("60–100 residues")).toBeTruthy();
    expect(
      inputs.getByText("Seeds spent").nextElementSibling?.textContent,
    ).toBe("0");
    expect(screen.queryByText("12345")).toBeNull();
    expect(
      screen.getByRole("link", { name: "About RFdiffusion" }),
    ).toBeTruthy();
  });
  it("links real sequence results using that model's native metric", () => {
    designsQuery.data = {
      items: [{ id: "result1", seed: 103, metrics: { score: 0.8321 } }],
    };
    render(
      <JobWaitScreen
        {...baseProps}
        toolId="proteinmpnn"
        status="running"
        completedDesigns={1}
      />,
    );
    expect(
      screen
        .getByRole("link", { name: /Result 103 Sequence score 0.8321/ })
        .getAttribute("href"),
    ).toBe("/app/designs/result1");
    expect(screen.getByText("Not recorded")).toBeTruthy();
  });
  it("does not fabricate a new ETA after a missed estimate", () => {
    render(
      <JobWaitScreen
        {...baseProps}
        status="running"
        startedAt="2020-01-01T00:00:00Z"
        initialEtaSeconds={1}
      />,
    );
    expect(screen.queryByText("Est. remaining")).toBeNull();
    expect(screen.queryByText(/finalizing|Updating estimate/)).toBeNull();
  });
});
