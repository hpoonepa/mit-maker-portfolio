import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ToolManifest } from "@papercrane/types";

import { ToolParamsPanel } from "./ToolParamsPanel";

afterEach(cleanup);

const dockingTool = {
  toolId: "dock",
  name: "Dock",
  version: "1.0.0",
  category: "validation",
  tier: "free",
  description: "Dock a ligand",
  inputSchemaRef: "dock.input.v1",
  outputSchemaRef: "dock.output.v1",
  compute: {
    gpuType: "CPU",
    gpuCount: 1,
    memoryGb: 8,
    estimatedMinutes: 1,
  },
  seedCostPerDesign: 1,
  defaultParams: { exhaustiveness: 8, mode: "fast" },
  inputSchema: {
    type: "object",
    properties: {
      params: {
        type: "object",
        required: ["exhaustiveness"],
        properties: {
          targetPdb: { type: "string" },
          exhaustiveness: {
            type: "integer",
            minimum: 1,
            maximum: 128,
          },
          mode: { type: "string", enum: ["fast", "accurate"] },
        },
      },
    },
  },
} as ToolManifest & {
  defaultParams: Record<string, unknown>;
  inputSchema: Record<string, unknown>;
};

describe("ToolParamsPanel", () => {
  it("renders manifest controls and serializes typed edits", () => {
    const onChange = vi.fn();
    render(
      <ToolParamsPanel
        tools={[dockingTool]}
        rawByTool={{}}
        onChange={onChange}
      />,
    );

    expect(
      (screen.getByLabelText(/Exhaustiveness/) as HTMLInputElement).value,
    ).toBe("8");
    expect(screen.queryByLabelText("Target Pdb")).toBeNull();

    fireEvent.change(screen.getByLabelText(/Exhaustiveness/), {
      target: { value: "32" },
    });
    const [, raw] = onChange.mock.calls.at(-1) as [string, string];
    expect(JSON.parse(raw)).toEqual({ exhaustiveness: 32, mode: "fast" });
  });

  it("resets raw overrides to the manifest defaults", () => {
    const onChange = vi.fn();
    render(
      <ToolParamsPanel
        tools={[dockingTool]}
        rawByTool={{ dock: '{"exhaustiveness": 64, "mode": "accurate"}' }}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reset defaults" }));
    const [toolId, raw] = onChange.mock.calls.at(-1) as [string, string];
    expect(toolId).toBe("dock");
    expect(JSON.parse(raw)).toEqual({ exhaustiveness: 8, mode: "fast" });
  });
});
