import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CatalogGrid } from "./CatalogGrid";
import type { CatalogCardTool } from "./CatalogCard";

function tool(
  slug: string,
  name: string,
  category: string,
): CatalogCardTool {
  return {
    id: slug,
    slug,
    name,
    version: "1.0.0",
    description: `${name} description`,
    category,
    gpuType: "CPU",
    gpuCount: 0,
    minVramGb: 0,
    tier: "free",
    timePerDesignSeconds: 30,
    runnable: true,
  };
}

describe("CatalogGrid", () => {
  it("searches plain-English tool strengths and filters by category", () => {
    render(
      <CatalogGrid
        tools={[
          tool("bindcraft", "BindCraft", "binder-design"),
          tool("proteinmpnn", "ProteinMPNN", "sequence-design"),
          tool("boltz2", "Boltz-2", "structure-prediction"),
        ]}
      />,
    );

    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search tool catalog" }),
      { target: { value: "inverse folding" } },
    );

    expect(
      screen.getByRole("heading", { name: "ProteinMPNN" }),
    ).toBeDefined();
    expect(screen.queryByRole("heading", { name: "BindCraft" })).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Clear catalog search" }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Binder design/ }));

    expect(screen.getByRole("heading", { name: "BindCraft" })).toBeDefined();
    expect(
      screen.queryByRole("heading", { name: "ProteinMPNN" }),
    ).toBeNull();
    expect(screen.queryByRole("heading", { name: "Boltz-2" })).toBeNull();
  });
});
