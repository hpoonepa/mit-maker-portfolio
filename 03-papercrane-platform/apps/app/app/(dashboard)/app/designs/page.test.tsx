import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
const fixtures = vi.hoisted(() => ({
  rows: [
    {
      id: "short-result",
      seed: 1,
      tool: "proteinmpnn",
      provenance: "real",
      metrics: { length: 10, sequence: "ACDEFGHIKL", score: 1.2 },
    },
    {
      id: "long-result",
      seed: 2,
      tool: "proteinmpnn",
      provenance: "real",
      metrics: { length: 400, sequence: "A".repeat(400), score: 0.8 },
    },
  ],
}));
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));
vi.mock("@/lib/trpc/client", () => ({
  trpc: {
    projects: {
      list: {
        useQuery: () => ({
          data: { items: [{ id: "project", name: "ProteinMPNN project" }] },
        }),
      },
    },
    designs: {
      listByProject: { useQuery: () => ({ data: { items: fixtures.rows } }) },
    },
    annotations: { starredIds: { useQuery: () => ({ data: { ids: [] } }) } },
  },
}));
vi.mock("@/lib/hooks/useFilters", async (original) => {
  const actual = await original<typeof import("@/lib/hooks/useFilters")>();
  return {
    ...actual,
    useFilters: (schema: Record<string, { default: unknown }>) => ({
      filters: Object.fromEntries(
        Object.entries(schema).map(([key, codec]) => [key, codec.default]),
      ),
      setFilter: vi.fn(),
      applyAll: vi.fn(),
      reset: vi.fn(),
      isDefault: true,
    }),
  };
});
vi.mock("@/components/annotations/StarButton", () => ({
  StarButton: () => <button>Star</button>,
}));
vi.mock("@/components/designs/BatchSelectBar", () => ({
  BatchSelectBar: () => null,
}));
vi.mock("@/components/designs/DesignScatterPlot", () => ({
  DesignScatterPlot: () => <div>Scatter plot</div>,
}));
vi.mock("@/components/filters/FilterBar", () => ({
  FilterBar: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));
import DesignsListPage from "./page";
afterEach(cleanup);
describe("results library", () => {
  it("shows sequences outside the old 50–200 residue range by default", () => {
    render(<DesignsListPage />);
    expect(screen.getByText("10 aa")).toBeTruthy();
    expect(screen.getByText("400 aa")).toBeTruthy();
    expect(
      screen.getByRole("columnheader", { name: "Sequence score" }),
    ).toBeTruthy();
  });
  it("omits irrelevant structural filters and empty plots for sequence results", () => {
    render(<DesignsListPage />);
    expect(screen.queryByLabelText("ipTM minimum")).toBeNull();
    expect(screen.queryByText("No ipTM/pAE values to plot.")).toBeNull();
    expect(screen.queryByText("Scatter plot")).toBeNull();
    expect(screen.getByLabelText("Results project")).toBeTruthy();
  });
});
