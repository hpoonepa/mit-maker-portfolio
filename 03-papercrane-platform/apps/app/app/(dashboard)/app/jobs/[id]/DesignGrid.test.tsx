import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DesignGrid } from "./DesignGrid";

vi.mock("@/lib/trpc/client", () => ({ trpc: { designs: { listByJob: { useQuery: () => ({ data: { items: [{ id: "result-1", seed: 103, provenance: "real", sequence: "MKT", metrics: { score: 0.8022, global_score: 0.8022, recovery: 0.5526, sample_perplexity: 2.2304425, length: 3 } }] } }) } } } }));
afterEach(cleanup);
describe("job results", () => {
  it("renders native ProteinMPNN values and working export destinations", () => {
    render(<DesignGrid jobId="job-1" toolId="proteinmpnn" />);
    expect(screen.getAllByText("Sequence score")[0]).toBeTruthy();
    expect(screen.getAllByText("0.8022")).toHaveLength(2);
    expect(screen.getByText("55.26%")).toBeTruthy();
    expect(screen.getByText("2.2304")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download FASTA" }).getAttribute("href")).toBe("/api/designs/result-1/export/fasta");
    expect(screen.queryByText(/rank this|meta.?score|unranked|insufficient metrics/i)).toBeNull();
    expect(screen.queryByText("ipTM")).toBeNull();
    expect(screen.queryByText("DockQ")).toBeNull();
    expect(screen.queryByText(/DSSP/)).toBeNull();
  });
});
