import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CompareView, type CompareDesign } from "./CompareView";

vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
afterEach(cleanup);
const mpnn: CompareDesign = {
  id: "mpnn-result", seed: 103, rank: 1, tool: "proteinmpnn", provenance: "real",
  sequence: "ACDEFGHIKLMNPQRSTVWY".repeat(4), length: 80,
  metrics: { score: 0.8123, global_score: 1.2345, seq_recovery: 0.5, meta_score: 98, composite: 0.9 },
};

describe("result comparison", () => {
  it("shows native ProteinMPNN scores and complete sequences without inferred rankings", () => {
    render(<CompareView designs={[mpnn, { ...mpnn, id: "second", seed: 104, metrics: { score: 0, global_score: 1.5, seq_recovery: 0 } }]} />);
    const scoreRow = screen.getByRole("rowheader", { name: /Sequence score/ }).closest("tr")!;
    expect(within(scoreRow).getByText("0.8123")).toBeTruthy();
    expect(within(scoreRow).getByText("0")).toBeTruthy();
    expect(screen.getByText("50.00%")).toBeTruthy();
    expect(screen.getByText("0.00%")).toBeTruthy();
    expect(screen.getAllByText(mpnn.sequence!)).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "FASTA" })[0]!.getAttribute("href")).toBe("/api/designs/mpnn-result/export/fasta");
    expect(screen.queryByText("ipTM")).toBeNull();
    expect(screen.queryByText(/meta.score/i)).toBeNull();
    expect(screen.queryByText("#1")).toBeNull();
  });

  it("includes actual metrics from mixed tools and leaves unreported values blank", () => {
    render(<CompareView designs={[mpnn, { id: "structure", seed: 3, tool: "boltz2", metrics: { iptm: 0.8, custom_energy: -17.25 } }]} />);
    const iptmRow = screen.getByRole("rowheader", { name: /^ipTM/ }).closest("tr")!;
    expect(within(iptmRow).getByText("0.8")).toBeTruthy();
    expect(within(iptmRow).getByText("—")).toBeTruthy();
    expect(screen.getByText("custom energy")).toBeTruthy();
    expect(screen.getByText("-17.25")).toBeTruthy();
    expect(screen.queryByText("DockQ")).toBeNull();
  });
});
