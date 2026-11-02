/**
 * Tools router — public tool catalogue (plan 02 §6).
 *
 * Two read paths:
 *
 *   • `list` / `get` — return the in-memory `ToolManifest` shape from
 *     `ctx.tools`. Used by older internal callers and the OpenAPI surface.
 *
 *   • `catalog` — returns the DB-backed flat shape that the dashboard's
 *     ToolPicker / job-submission UI consume directly. Drives the public
 *     wire contract (see `CatalogEntrySchema` below). Includes Modal
 *     deployment reference + closed-weights flag.
 */
import { z } from "zod";
import { ToolManifestSchema, ToolTierSchema } from "@papercrane/types";
import { router, publicProcedure, TRPCError } from "../trpc.js";
import { isToolRunnable, toolReleaseStatus } from "../config/toolReadiness.js";

/**
 * Public catalogue entry — same shape as the internal `ToolManifest` minus
 * anything we may later want to hide from unauthenticated readers.
 */
export type ToolCatalogEntry = z.infer<typeof ToolManifestSchema>;

/**
 * Release status and execution readiness are deliberately separate. A beta
 * tool can be runnable while it accumulates production verification; an
 * explicit stub remains visible but unavailable.
 */
const ListInput = z
  .object({
    // Free-form so callers can pass DB-canonical ("backbone") or manifest
    // ("backbone_generation") values without round-tripping through enum
    // narrowing — the resolver normalises both.
    category: z.string().min(1).optional(),
    /**
     * Tier ceiling — when set, only tools at-or-below this tier are returned.
     * `free` ⊂ `pro` ⊂ `frontier`. Frontend uses this to pre-filter the
     * picker for callers that can't run frontier tools; the picker still
     * shows them visually (with a "Contact sales" overlay) when this filter
     * is omitted, so the catalog stays discoverable.
     */
    tier: ToolTierSchema.optional(),
  })
  .strict();

/**
 * Permissive list-output entry — DB and in-memory manifests historically
 * use slightly different vocabularies for `category`/`tier` (manifest:
 * `backbone_generation`/`open`, DB enum: `backbone`/`free`). Rather than
 * forcing a lossy round-trip through narrow Zod enums (which surfaced as
 * "Output validation failed" toasts in the UI), we declare the wire shape
 * with `z.string()` for free-form fields and `.passthrough()` so any extra
 * Prisma columns flow through untouched.
 */
const ListItemSchema = z
  .object({
    toolId: z.string().min(1),
    name: z.string().min(1),
    version: z.string().min(1),
    category: z.string().min(1),
    tier: z.string().min(1),
    description: z.string(),
    seedCostPerDesign: z.number().nonnegative(),
    // Catalog-honesty flag: 'ga' for Modal-verified tools, 'beta' otherwise.
    status: z.enum(["ga", "beta"]),
    runnable: z.boolean(),
    defaultParams: z.record(z.unknown()).optional(),
    inputSchema: z.record(z.unknown()).optional(),
  })
  .passthrough();

const ListOutput = z.object({
  items: z.array(ListItemSchema),
});

const TIER_RANK: Record<z.infer<typeof ToolTierSchema>, number> = {
  free: 0,
  pro: 1,
  frontier: 2,
};

/**
 * Flat-shape entry consumed by the ToolPicker UI. Built by `catalog` from the
 * Prisma `tools` table; values like `gpuType` / `gpuCount` / `minVramGb` /
 * `timePerDesignSeconds` live inside the JSONB `compute` blob in DB and are
 * lifted to top-level fields here so the UI doesn't need to know about the
 * storage layout.
 */
export const CatalogEntrySchema = z
  .object({
    id: z.string(),
    slug: z.string(),
    name: z.string(),
    version: z.string(),
    description: z.string(),
    category: z.enum([
      "backbone",
      "sequence",
      "structure",
      "composite",
      "ranking",
    ]),
    gpuType: z.string(),
    gpuCount: z.number().int().nonnegative(),
    minVramGb: z.number().nonnegative(),
    license: z.string(),
    tier: ToolTierSchema,
    timePerDesignSeconds: z.number().nonnegative(),
    seedCostPerDesign: z.number().nonnegative(),
    closedWeights: z.boolean(),
    modalApp: z.string().nullable(),
    // Catalog-honesty flag: 'ga' for Modal-verified tools, 'beta' otherwise.
    status: z.enum(["ga", "beta"]),
    runnable: z.boolean(),
    defaultParams: z.record(z.unknown()),
    inputSchema: z.record(z.unknown()).optional(),
  })
  .strict();
export type CatalogEntry = z.infer<typeof CatalogEntrySchema>;

const CatalogOutput = z.object({
  tools: z.array(CatalogEntrySchema),
});

interface ComputeBlob {
  gpu?: string;
  gpuType?: string;
  gpuCount?: number;
  memoryGb?: number;
  estSecondsPerDesign?: number;
  minVramGb?: number;
}

/**
 * Compute → flat-field projection. Tolerates the manifest's `gpu` key as well
 * as the canonical `gpuType` so we can ingest both legacy and current schema
 * payloads without re-seeding.
 */
function projectCompute(compute: unknown): {
  gpuType: string;
  gpuCount: number;
  minVramGb: number;
  timePerDesignSeconds: number;
} {
  const c = (compute ?? {}) as ComputeBlob;
  const gpuType = c.gpuType ?? c.gpu ?? "CPU";
  const gpuCount = typeof c.gpuCount === "number" ? c.gpuCount : 0;
  // Default minVramGb: parse a "...-40GB" / "...-80GB" suffix off `gpu` if the
  // manifest didn't supply an explicit number, otherwise 0.
  let minVramGb = 0;
  if (typeof c.minVramGb === "number") {
    minVramGb = c.minVramGb;
  } else if (typeof gpuType === "string") {
    const m = /([0-9]+)GB/i.exec(gpuType);
    if (m) minVramGb = Number(m[1]);
  }
  const timePerDesignSeconds =
    typeof c.estSecondsPerDesign === "number" ? c.estSecondsPerDesign : 0;
  return { gpuType, gpuCount, minVramGb, timePerDesignSeconds };
}

/**
 * Map DB `ToolCategory` enum → manifest-style category string the UI/typed
 * clients expect. Both shapes are accepted on the input side; the output
 * uses the manifest vocabulary since that is what the existing TS client
 * (`ToolManifest.category`) reads.
 */
const DB_CATEGORY_TO_MANIFEST: Record<string, string> = {
  backbone: "binder-design",
  sequence: "sequence-design",
  structure: "structure-prediction",
  composite: "binder-design",
  ranking: "validation",
  utility: "utility",
};

/**
 * Reverse map for input filtering — accept either the DB enum value
 * ("backbone") or the manifest value ("binder-design") in the `category`
 * filter without surprising callers.
 */
function normaliseCategoryFilter(value: string): string[] {
  const dbMatches = Object.entries(DB_CATEGORY_TO_MANIFEST)
    .filter(([db, manifest]) => db === value || manifest === value)
    .map(([db]) => db);
  return dbMatches.length > 0 ? dbMatches : [value];
}

function matchesCategoryFilter(toolCategory: string, filter?: string): boolean {
  if (!filter) return true;
  const accepted = new Set(normaliseCategoryFilter(filter));
  return (
    toolCategory === filter ||
    accepted.has(toolCategory) ||
    accepted.has(DB_CATEGORY_TO_MANIFEST[toolCategory] ?? "")
  );
}

/**
 * Build a wire-shape entry from a Prisma `Tool` row. Lifts the JSONB
 * `compute` blob into the shape `ToolManifest.compute` expects so the
 * existing `ToolCard` / `estimateEta` consumers keep working without
 * needing to reshape on the client.
 */
function buildListItem(r: {
  id: string;
  displayName: string;
  version: string;
  category: string;
  tier: "free" | "pro" | "frontier";
  compute?: unknown;
  composes?: string[] | null;
  defaultParams?: unknown;
  inputSchema?: unknown;
}): {
  toolId: string;
  name: string;
  version: string;
  category: string;
  tier: string;
  description: string;
  seedCostPerDesign: number;
  status: "ga" | "beta";
  runnable: boolean;
  defaultParams: Record<string, unknown>;
  inputSchema?: Record<string, unknown>;
  compute: {
    gpuType: string;
    gpuCount: number;
    memoryGb: number;
    estimatedMinutes: number;
    minVramGb?: number;
  };
} {
  const composes = (r.composes ?? []).filter(Boolean);
  const description =
    composes.length > 0
      ? `Composes: ${composes.join(" → ")}`
      : `${r.displayName} ${r.version}`;
  const c = (r.compute ?? {}) as {
    gpu?: string;
    gpuType?: string;
    gpuCount?: number;
    memoryGb?: number;
    estSecondsPerDesign?: number;
    estimatedMinutes?: number;
    minVramGb?: number;
  };
  const gpuType = c.gpuType ?? c.gpu ?? "CPU";
  const gpuCount = typeof c.gpuCount === "number" ? c.gpuCount : 1;
  const memoryGb = typeof c.memoryGb === "number" ? c.memoryGb : 8;
  const estimatedMinutes =
    typeof c.estimatedMinutes === "number"
      ? c.estimatedMinutes
      : typeof c.estSecondsPerDesign === "number"
        ? Math.max(c.estSecondsPerDesign / 60, 0.01)
        : 1;
  let minVramGb: number | undefined =
    typeof c.minVramGb === "number" ? c.minVramGb : undefined;
  if (minVramGb === undefined && typeof gpuType === "string") {
    const m = /([0-9]+)GB/i.exec(gpuType);
    if (m) minVramGb = Number(m[1]);
  }
  return {
    toolId: r.id,
    name: r.displayName,
    version: r.version,
    category: DB_CATEGORY_TO_MANIFEST[r.category] ?? r.category,
    tier: r.tier,
    description,
    seedCostPerDesign: 1,
    status: toolReleaseStatus(r.id),
    runnable: isToolRunnable(r.id),
    defaultParams:
      r.defaultParams &&
      typeof r.defaultParams === "object" &&
      !Array.isArray(r.defaultParams)
        ? (r.defaultParams as Record<string, unknown>)
        : {},
    ...(r.inputSchema &&
    typeof r.inputSchema === "object" &&
    !Array.isArray(r.inputSchema)
      ? { inputSchema: r.inputSchema as Record<string, unknown> }
      : {}),
    compute: {
      gpuType,
      gpuCount,
      memoryGb,
      estimatedMinutes,
      ...(minVramGb !== undefined ? { minVramGb } : {}),
    },
  };
}

export const toolsRouter = router({
  list: publicProcedure
    .meta({
      openapi: {
        method: "GET",
        path: "/tools",
        tags: ["tools"],
        summary: "List public tool catalogue",
      },
    })
    .input(ListInput)
    .output(ListOutput)
    .query(async ({ ctx, input }) => {
      if (ctx.tools.length > 0) {
        const ceiling = input.tier ? TIER_RANK[input.tier] : null;
        const items = ctx.tools
          .filter((tool) => {
            const categoryOk = matchesCategoryFilter(
              tool.category,
              input.category,
            );
            const tierOk =
              ceiling == null
                ? true
                : (TIER_RANK[tool.tier as keyof typeof TIER_RANK] ?? 0) <=
                  ceiling;
            return categoryOk && tierOk;
          })
          .map((tool) => ({
            ...tool,
            status: toolReleaseStatus(tool.toolId),
            runnable: isToolRunnable(tool.toolId),
          }));
        return { items };
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = (await (ctx.prisma as any).tool.findMany({
        where: {
          active: true,
          ...(input.category
            ? { category: { in: normaliseCategoryFilter(input.category) } }
            : {}),
        },
        orderBy: [{ category: "asc" }, { displayName: "asc" }],
      })) as Array<{
        id: string;
        displayName: string;
        version: string;
        category: string;
        tier: "free" | "pro" | "frontier";
        license?: string;
        compute?: unknown;
        composes?: string[] | null;
        defaultParams?: unknown;
        inputSchema?: unknown;
      }>;

      const ceiling = input.tier ? TIER_RANK[input.tier] : null;
      const items = rows
        .filter((r) =>
          ceiling == null
            ? true
            : (TIER_RANK[r.tier as keyof typeof TIER_RANK] ?? 0) <= ceiling,
        )
        .map((r) => buildListItem(r));

      return { items };
    }),

  /**
   * DB-backed flat-shape catalogue used by the dashboard's ToolPicker.
   * Reads from `tools` table directly so the UI sees newly-seeded entries
   * without an API restart. Filters out `active=false` rows.
   */
  catalog: publicProcedure
    .meta({
      openapi: {
        method: "GET",
        path: "/tools/catalog",
        tags: ["tools"],
        summary: "List tool catalogue (flat shape) for ToolPicker UI",
      },
    })
    .input(z.object({}).strict().optional())
    .output(CatalogOutput)
    .query(async ({ ctx }) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = await (ctx.prisma as any).tool.findMany({
        where: { active: true },
        orderBy: [{ category: "asc" }, { displayName: "asc" }],
      });

      const tools: CatalogEntry[] = rows.map(
        (r: {
          id: string;
          displayName: string;
          version: string;
          category: string;
          tier: "free" | "pro" | "frontier";
          license: string;
          compute: unknown;
          composes?: string[] | null;
          modalApp?: string | null;
          closedWeights?: boolean | null;
          defaultParams?: unknown;
          inputSchema?: unknown;
        }) => {
          const { gpuType, gpuCount, minVramGb, timePerDesignSeconds } =
            projectCompute(r.compute);
          // Description: composes pipeline if present, else displayName + version.
          // Long-form prose lives in the manifest README; the UI surfaces version
          // and tier badges separately.
          const composes = (r.composes ?? []).filter(Boolean);
          const description =
            composes.length > 0
              ? `Composes: ${composes.join(" → ")}`
              : `${r.displayName} ${r.version}`;
          return {
            id: r.id,
            slug: r.id,
            name: r.displayName,
            version: r.version,
            description,
            category: r.category as CatalogEntry["category"],
            gpuType,
            gpuCount,
            minVramGb,
            license: r.license,
            tier: r.tier,
            timePerDesignSeconds,
            // Cost model: 1 seed per design today. Pro/frontier tools may
            // charge more per design once the meter row is wired (Wave 9).
            seedCostPerDesign: 1,
            closedWeights: Boolean(r.closedWeights),
            modalApp: r.modalApp ?? null,
            status: toolReleaseStatus(r.id),
            runnable: isToolRunnable(r.id),
            defaultParams:
              r.defaultParams &&
              typeof r.defaultParams === "object" &&
              !Array.isArray(r.defaultParams)
                ? (r.defaultParams as Record<string, unknown>)
                : {},
            ...(r.inputSchema &&
            typeof r.inputSchema === "object" &&
            !Array.isArray(r.inputSchema)
              ? { inputSchema: r.inputSchema as Record<string, unknown> }
              : {}),
          };
        },
      );

      return { tools };
    }),

  get: publicProcedure
    .meta({
      openapi: {
        method: "GET",
        path: "/tools/{toolId}",
        tags: ["tools"],
        summary: "Get a tool manifest by id",
      },
    })
    .input(z.object({ toolId: z.string().min(1) }))
    .output(ListItemSchema)
    .query(async ({ ctx, input }) => {
      if (ctx.tools.length > 0) {
        const tool = ctx.tools.find((entry) => entry.toolId === input.toolId);
        if (!tool) {
          throw new TRPCError({
            code: "NOT_FOUND",
            message: `tool not found: ${input.toolId}`,
          });
        }
        return {
          ...tool,
          status: toolReleaseStatus(tool.toolId),
          runnable: isToolRunnable(tool.toolId),
        };
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const r = (await (ctx.prisma as any).tool.findUnique({
        where: { id: input.toolId },
      })) as {
        id: string;
        displayName: string;
        version: string;
        category: string;
        tier: "free" | "pro" | "frontier";
        compute?: unknown;
        composes?: string[] | null;
        defaultParams?: unknown;
        inputSchema?: unknown;
      } | null;
      if (!r) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: `tool not found: ${input.toolId}`,
        });
      }
      return buildListItem(r as Parameters<typeof buildListItem>[0]);
    }),
});
