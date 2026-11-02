import { describe, it, expect, vi } from "vitest";
import { appRouter } from "../src/routers/index.js";
import { createInnerContext } from "../src/context.js";
import type { ToolCatalogEntry } from "../src/routers/tools.js";

/**
 * Tools router — public catalogue. No auth required, so unauthenticated
 * callers should be able to list & fetch tool manifests.
 */

const SAMPLE_TOOLS: ToolCatalogEntry[] = [
  {
    toolId: "rfdiffusion",
    name: "RFdiffusion",
    version: "1.0.0",
    category: "binder-design",
    tier: "free",
    description: "De novo backbone generation",
    inputSchemaRef: "rfdiffusion.input.v1",
    outputSchemaRef: "rfdiffusion.output.v1",
    compute: {
      gpuType: "A100",
      gpuCount: 1,
      memoryGb: 40,
      estimatedMinutes: 10,
    },
    seedCostPerDesign: 1,
  },
  {
    toolId: "alphafold3",
    name: "AlphaFold 3",
    version: "3.0.0",
    category: "structure-prediction",
    tier: "frontier",
    description: "Closed-weights structure prediction",
    inputSchemaRef: "af3.input.v1",
    outputSchemaRef: "af3.output.v1",
    compute: {
      gpuType: "H100",
      gpuCount: 1,
      memoryGb: 80,
      estimatedMinutes: 5,
    },
    seedCostPerDesign: 5,
  },
  {
    toolId: "boltz2",
    name: "Boltz-2",
    version: "2.0.0",
    category: "structure-prediction",
    tier: "pro",
    description: "Open-weights structure prediction",
    inputSchemaRef: "boltz2.input.v1",
    outputSchemaRef: "boltz2.output.v1",
    compute: {
      gpuType: "A100",
      gpuCount: 1,
      memoryGb: 40,
      estimatedMinutes: 6,
    },
    seedCostPerDesign: 2,
  },
];

function buildCtx() {
  return createInnerContext({
    auth: null,
    tools: SAMPLE_TOOLS,
  });
}

describe("tools router — public catalogue", () => {
  it("tools.list returns the full catalogue without auth", async () => {
    const caller = appRouter.createCaller(buildCtx());
    const result = await caller.tools.list({});
    expect(result.items).toHaveLength(3);
    expect(result.items.map((t) => t.toolId).sort()).toEqual([
      "alphafold3",
      "boltz2",
      "rfdiffusion",
    ]);
  });

  it("tools.list marks every public catalog tool as runnable", async () => {
    const caller = appRouter.createCaller(buildCtx());
    const result = await caller.tools.list({});
    const byId = new Map(result.items.map((t) => [t.toolId, t]));
    expect((byId.get("boltz2") as { status?: string }).status).toBe("ga");
    expect((byId.get("alphafold3") as { status?: string }).status).toBe("ga");
    expect((byId.get("rfdiffusion") as { status?: string }).status).toBe("ga");
    expect((byId.get("rfdiffusion") as { runnable?: boolean }).runnable).toBe(
      true,
    );
  });

  it("reports beta readiness separately from release status", async () => {
    const betaTools: ToolCatalogEntry[] = [
      {
        ...SAMPLE_TOOLS[0]!,
        toolId: "foldseek",
        name: "Foldseek",
      },
      {
        ...SAMPLE_TOOLS[0]!,
        toolId: "germinal",
        name: "Germinal",
        tier: "frontier",
      },
    ];
    const caller = appRouter.createCaller(
      createInnerContext({ auth: null, tools: betaTools }),
    );

    const result = await caller.tools.list({});
    const byId = new Map(result.items.map((tool) => [tool.toolId, tool]));
    expect(byId.get("foldseek")).toMatchObject({
      status: "beta",
      runnable: true,
    });
    expect(byId.get("germinal")).toMatchObject({
      status: "beta",
      runnable: false,
    });
  });

  it("tools.list filters by category", async () => {
    const caller = appRouter.createCaller(buildCtx());
    const result = await caller.tools.list({ category: "binder-design" });
    expect(result.items).toHaveLength(1);
    expect(result.items[0]!.toolId).toBe("rfdiffusion");
  });

  it("tools.get returns a single tool manifest", async () => {
    const caller = appRouter.createCaller(buildCtx());
    const tool = await caller.tools.get({ toolId: "rfdiffusion" });
    expect(tool.toolId).toBe("rfdiffusion");
    expect(tool.name).toBe("RFdiffusion");
  });

  it("tools.get throws NOT_FOUND for unknown tool", async () => {
    const caller = appRouter.createCaller(buildCtx());
    await expect(caller.tools.get({ toolId: "nonexistent" })).rejects.toThrow(
      /not.?found/i,
    );
  });

  it("returns manifest defaults from the DB-backed list", async () => {
    const findMany = vi.fn().mockResolvedValue([
      {
        id: "foldseek",
        displayName: "Foldseek",
        version: "10.0.0",
        category: "ranking",
        tier: "free",
        compute: {
          gpu: "CPU",
          gpuCount: 0,
          memoryGb: 8,
          estSecondsPerDesign: 8,
        },
        defaultParams: { alignmentType: 1 },
        inputSchema: {
          type: "object",
          properties: { alignmentType: { type: "integer", enum: [0, 1, 2] } },
        },
        composes: [],
      },
    ]);
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: null,
        tools: [],
        prisma: { tool: { findMany } } as never,
      }),
    );

    const result = await caller.tools.list({});
    expect(result.items[0]).toMatchObject({
      toolId: "foldseek",
      defaultParams: { alignmentType: 1 },
      inputSchema: expect.objectContaining({ type: "object" }),
    });
  });
});
