import { toCatalogCategory } from "@papercrane/types";
import { createServerTrpc } from "@/lib/trpc/server";
import { CatalogGrid } from "@/components/tools/CatalogGrid";
import type { CatalogCardTool } from "@/components/tools/CatalogCard";
import { STATIC_TOOL_CATALOG } from "@/lib/static-tool-catalog";

/**
 * Tools catalog: workspace-level index of every tool Paper Crane exposes.
 *
 * Server component, fetches the public `tools.catalog` proc (DB-backed flat
 * shape from packages/trpc/src/routers/tools.ts). Renders the brief's
 * editorial 2-column grid. No new tRPC procs are introduced: we read what
 * the platform already publishes.
 *
 * Sister to /app/projects and /app/targets: same header rhythm.
 */
export const dynamic = "force-dynamic";

export default async function ToolsCatalogPage() {
  const trpc = await createServerTrpc();

  let tools: CatalogCardTool[] = [];
  let loadError: string | null = null;
  try {
    const res = await trpc.tools.catalog.query();
    tools = (res.tools ?? []).map((t) => ({
      id: t.id,
      slug: t.slug,
      name: t.name,
      version: t.version,
      description: t.description,
      category: t.category,
      gpuType: t.gpuType,
      gpuCount: t.gpuCount,
      minVramGb: t.minVramGb,
      tier: t.tier,
      timePerDesignSeconds: t.timePerDesignSeconds,
      status: t.status,
      runnable: t.runnable,
    }));
  } catch (err) {
    loadError = err instanceof Error ? err.message : "Catalog unavailable";
  }

  return (
    <div className="space-y-8">
      <header className="flex items-end justify-between gap-6 pb-2">
        <div>
          <h1 className="font-sans font-medium text-display-md text-ink">
            Tools
          </h1>
          <p className="mt-3 text-[15px] text-graphite">Choose a tool, add your inputs, and review your run.</p>
        </div>
        <p className="hidden shrink-0 font-sans tabular-nums text-[12px] text-graphite-soft md:block">
          {tools.length || STATIC_TOOL_CATALOG.length} tools · {countFamilies(tools.length > 0 ? tools : STATIC_TOOL_CATALOG)} families
        </p>
      </header>

      {loadError ? (
        <>
          <p className="rounded-2xl border border-crane/20 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep">
            Live catalog details are unavailable, so we&apos;re showing the
            checked-in manifest catalog. Current availability will appear when the connection is restored.
          </p>
          <CatalogGrid tools={STATIC_TOOL_CATALOG} />
        </>
      ) : (
        <CatalogGrid tools={tools} />
      )}
    </div>
  );
}

function countFamilies(tools: CatalogCardTool[]): number {
  const set = new Set<string>();
  for (const t of tools) set.add(toCatalogCategory(t.category));
  return set.size;
}
