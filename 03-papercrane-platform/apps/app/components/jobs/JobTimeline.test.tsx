import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { JobTimeline } from "./JobTimeline";

afterEach(cleanup);
const times = { submittedAt: "2026-09-30T17:00:00Z", startedAt: "2026-09-30T17:00:05Z", finishedAt: "2026-09-30T17:00:15Z" };

describe("JobTimeline", () => {
  it("shows only recorded lifecycle events without inventing tool stages", () => {
    render(<JobTimeline {...times} status="succeeded" toolChain={["proteinmpnn", "boltz2"]} />);
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText("+5s")).toBeTruthy();
    expect(screen.getByText("+10s")).toBeTruthy();
    expect(screen.queryByText(/proteinmpnn/)).toBeNull();
    expect(screen.queryByText("N/A")).toBeNull();
  });
  it.each([["partial", "Partially completed"], ["cancelled", "Cancelled"], ["failed", "Failed"], ["purged", "Purged"]] as const)("labels %s accurately", (status, label) => {
    render(<JobTimeline {...times} status={status} />);
    expect(screen.getByText(label)).toBeTruthy();
    expect(screen.queryByText("Succeeded")).toBeNull();
    expect(screen.queryByText("Completed")).toBeNull();
  });
  it("does not claim a queued job started or succeeded", () => {
    render(<JobTimeline submittedAt={times.submittedAt} status="queued" />);
    expect(screen.getByText("Queued")).toBeTruthy();
    expect(screen.queryByText("Started")).toBeNull();
    expect(screen.queryByText("Succeeded")).toBeNull();
  });
  it("retains explicit recorded tool events", () => {
    render(<JobTimeline {...times} status="succeeded" extraEvents={[{id: "tool:0", label: "ProteinMPNN", at: "2026-09-30T17:00:08Z", done: true}]} />);
    expect(screen.getByText("ProteinMPNN")).toBeTruthy();
  });
});
