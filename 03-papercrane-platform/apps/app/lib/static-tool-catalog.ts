import { PUBLIC_TOOL_CATALOG } from "../../web/lib/tool-catalog";
import type { CatalogCardTool } from "@/components/tools/CatalogCard";
import type { ToolManifest } from "@papercrane/types";

const CATEGORY_MAP: Record<string, string> = {
  binder_design: "backbone",
  backbone_generation: "backbone",
  sequence_design: "sequence",
  structure_prediction: "structure",
  embedding_scoring: "ranking",
};

/**
 * Local fallback for the platform catalog. The API remains the source of
 * truth when available; this keeps the platform discoverable during local
 * development when Postgres is stopped or a remote Supabase project is stale.
 */
export const STATIC_TOOL_CATALOG: CatalogCardTool[] = PUBLIC_TOOL_CATALOG.map(
  (tool) => ({
    id: tool.slug,
    slug: tool.slug,
    name: tool.name,
    version: tool.version,
    description: `${tool.name} ${tool.version}`,
    category: CATEGORY_MAP[tool.category] ?? tool.category,
    gpuType: "CPU",
    gpuCount: 0,
    minVramGb: 0,
    tier: tool.status === "ga" ? "free" : "pro",
    timePerDesignSeconds: 0,
    status: tool.status,
    runnable: tool.runnable,
    metadataOffline: true,
  }),
);

const MANIFEST_CATEGORY_MAP: Record<string, ToolManifest["category"]> = {
  binder_design: "binder-design",
  backbone_generation: "binder-design",
  sequence_design: "sequence-design",
  structure_prediction: "structure-prediction",
  embedding_scoring: "validation",
};

/** Minimum manifest shape needed to keep the job picker discoverable offline. */
type StaticToolManifest = ToolManifest & {
  status: "ga" | "beta";
  runnable: boolean;
  defaultParams: Record<string, unknown>;
  inputSchema: Record<string, unknown>;
};

export const STATIC_TOOL_MANIFESTS: StaticToolManifest[] =
  PUBLIC_TOOL_CATALOG.map((tool) => ({
    toolId: tool.slug,
    name: tool.name,
    version: tool.version,
    category: MANIFEST_CATEGORY_MAP[tool.category] ?? "validation",
    tier: "free",
    description: `${tool.name} ${tool.version}`,
    inputSchemaRef: `tools/${tool.slug}/schemas/input.json`,
    outputSchemaRef: `tools/${tool.slug}/schemas/output.json`,
    compute: {
      gpuType: "CPU",
      gpuCount: 1,
      memoryGb: 8,
      estimatedMinutes: 1,
    },
    seedCostPerDesign: 1,
    status: tool.status,
    runnable: tool.runnable,
    defaultParams: {},
    inputSchema: {},
  }));
