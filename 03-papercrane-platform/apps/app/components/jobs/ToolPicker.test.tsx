import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import type { ToolManifest } from "@papercrane/types";

import { ToolPicker } from "./ToolPicker";

afterEach(cleanup);

function tool(
  toolId: string,
  name: string,
  runnable: boolean,
  status: "ga" | "beta",
  category = "structure-prediction",
): ToolManifest {
  return {
    toolId,
    name,
    version: "1.0.0",
    category,
    tier: "free",
    description: `${name} description`,
    inputSchemaRef: `${toolId}.input.v1`,
    outputSchemaRef: `${toolId}.output.v1`,
    compute: {
      gpuType: "CPU",
      gpuCount: 0,
      memoryGb: 8,
      estimatedMinutes: 1,
    },
    seedCostPerDesign: 1,
    runnable,
    status,
  } as ToolManifest;
}

describe("ToolPicker", () => {
  it("searches the expanded catalog and allows runnable beta tools", () => {
    const onSelectionChange = vi.fn();
    render(
      <ToolPicker
        tools={[
          tool("boltz2", "Boltz-2", true, "ga"),
          tool("foldseek", "Foldseek", true, "beta"),
          tool("germinal", "Germinal", false, "beta"),
        ]}
        selectedIds={[]}
        onSelectionChange={onSelectionChange}
        userTier="free"
        isToolAllowed={(item) =>
          (item as ToolManifest & { runnable?: boolean }).runnable === true
        }
        isToolRunnable={(item) =>
          (item as ToolManifest & { runnable?: boolean }).runnable === true
        }
      />,
    );

    fireEvent.change(screen.getByRole("searchbox", { name: "Search tools" }), {
      target: { value: "foldseek" },
    });

    expect(screen.queryByTestId("e2e-job-tool-boltz2")).toBeNull();
    const foldseek = screen.getByTestId("e2e-job-tool-foldseek");
    expect(foldseek.hasAttribute("disabled")).toBe(false);
    fireEvent.click(foldseek);
    expect(onSelectionChange).toHaveBeenCalledWith(["foldseek"]);
  });

  it("filters runnable tools by research task and available input", () => {
    render(
      <ToolPicker
        tools={[
          tool("rfdiffusion", "RFdiffusion", true, "ga", "binder-design"),
          tool(
            "proteinmpnn",
            "ProteinMPNN",
            true,
            "ga",
            "sequence-design",
          ),
          tool("boltz2", "Boltz-2", true, "ga", "structure-prediction"),
        ]}
        selectedIds={[]}
        onSelectionChange={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Design sequences/ }),
    );

    expect(screen.getByTestId("e2e-job-tool-proteinmpnn")).toBeDefined();
    expect(screen.queryByTestId("e2e-job-tool-rfdiffusion")).toBeNull();
    expect(screen.queryByTestId("e2e-job-tool-boltz2")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Protein backbone" }),
    );

    expect(screen.getByTestId("e2e-job-tool-proteinmpnn")).toBeDefined();
    expect(screen.getByText(/fast, reliable inverse folding/i)).toBeDefined();
    expect(screen.queryByTestId("e2e-job-tool-rfdiffusion")).toBeNull();
    expect(screen.queryByTestId("e2e-job-tool-boltz2")).toBeNull();
  });
});
