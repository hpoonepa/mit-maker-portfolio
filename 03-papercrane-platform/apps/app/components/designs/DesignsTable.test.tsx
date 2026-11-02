import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));
vi.mock("@/components/annotations/StarButton", () => ({
  StarButton: () => <button>Star</button>,
}));
import {
  DesignsTable,
  sortDesignRows,
  type DesignTableRow,
} from "./DesignsTable";
afterEach(cleanup);
const props = {
  hoverId: null,
  onHover: vi.fn(),
  selectedIds: new Set<string>(),
  onToggleSelect: vi.fn(),
  onSelectAll: vi.fn(),
  onClearAll: vi.fn(),
  starredSet: new Set<string>(),
  sortBy: "created:desc",
  onToggleSort: vi.fn(),
};
describe("DesignsTable native measurements", () => {
  it("shows ProteinMPNN's actual metrics without unrelated ranking or interface columns", () => {
    render(
      <DesignsTable
        {...props}
        rows={[
          {
            id: "mpnn",
            seed: 103,
            tool: "proteinmpnn",
            provenance: "real",
            metrics: {
              score: 0.7812,
              global_score: 0.8991,
              recovery: 0.5,
              sample_perplexity: 2.18,
              length: 76,
              composite: 0.9,
            },
          },
        ]}
      />,
    );
    for (const label of [
      "Sequence score",
      "Global score",
      "Sequence recovery",
      "Perplexity",
    ])
      expect(screen.getByRole("columnheader", { name: label })).toBeTruthy();
    for (const label of [
      "Rank",
      "Meta",
      "Composite",
      "Reading",
      "ipTM",
      "DockQ",
    ])
      expect(screen.queryByRole("columnheader", { name: label })).toBeNull();
    expect(screen.getByText("0.7812")).toBeTruthy();
    expect(screen.getByText("50.00%")).toBeTruthy();
  });
  it("keeps ipSAE distinct from ipTM and handles aliased output keys", () => {
    render(
      <DesignsTable
        {...props}
        rows={[
          {
            id: "boltz",
            seed: 7,
            tool: "boltz2",
            metrics: { computational__boltz2_min_ipsae: 0.81, iptm: 0.2 },
          },
        ]}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "ipSAE" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "ipTM" })).toBeTruthy();
    const row = screen.getAllByRole("row")[1]!;
    expect(within(row).getByText("0.81")).toBeTruthy();
    expect(within(row).getByText("0.2")).toBeTruthy();
  });
  it("does not label another tool's generic score as a ProteinMPNN sequence score", () => {
    render(
      <DesignsTable
        {...props}
        rows={[
          { id: "mpnn", seed: 1, tool: "proteinmpnn", metrics: { score: 1.2 } },
          { id: "other", seed: 2, tool: "other", metrics: { score: 0.4 } },
        ]}
      />,
    );
    expect(
      screen.getByRole("columnheader", { name: "Sequence score" }),
    ).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "score" })).toBeTruthy();
  });
  it("sorts both directions, preserves zero, and keeps absent measurements last", () => {
    const rows: DesignTableRow[] = [
      { id: "missing", seed: 0, tool: "proteinmpnn", metrics: {} },
      { id: "high", seed: 2, tool: "proteinmpnn", metrics: { score: 2 } },
      { id: "zero", seed: 1, tool: "proteinmpnn", metrics: { score: 0 } },
    ];
    expect(
      sortDesignRows(rows, "metric:Sequence score:asc").map((r) => r.id),
    ).toEqual(["zero", "high", "missing"]);
    expect(
      sortDesignRows(rows, "metric:Sequence score:desc").map((r) => r.id),
    ).toEqual(["high", "zero", "missing"]);
    expect(sortDesignRows(rows, "seed:desc").map((r) => r.seed)).toEqual([
      2, 1, 0,
    ]);
  });
});
