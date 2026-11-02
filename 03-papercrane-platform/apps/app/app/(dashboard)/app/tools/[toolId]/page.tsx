import { notFound } from "next/navigation";
import { createServerTrpc } from "@/lib/trpc/server";
import { ToolDetailHero } from "@/components/tools/ToolDetailHero";
import { ParametersTable } from "@/components/tools/ParametersTable";
import {
  familyLabel,
  formatGpuClass,
  formatRuntime,
} from "@/components/tools/CatalogChip";

/**
 * Tool detail page.
 *
 * Resolves the slug against `tools.catalog` (already used by the index) so
 * the wire shape is identical: no second proc, no second source of truth.
 * The CTA opens the job wizard with this tool preselected so catalog browsing
 * leads directly into a runnable workflow.
 */
export const dynamic = "force-dynamic";

type Params = { toolId: string };

export default async function ToolDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { toolId } = await params;
  const trpc = await createServerTrpc();

  let tool: Awaited<ReturnType<typeof trpc.tools.catalog.query>>["tools"][number] | null = null;
  try {
    const res = await trpc.tools.catalog.query();
    tool = res.tools.find((t) => t.slug === toolId || t.id === toolId) ?? null;
  } catch {
    tool = null;
  }

  if (!tool) {
    notFound();
  }

  const ctaHref = `/app/jobs/new?tool=${encodeURIComponent(tool.slug)}`;

  const rows = [
    { label: "Tool ID", value: tool.id },
    { label: "Version", value: `v${tool.version}` },
    { label: "Family", value: familyLabel(tool.category) },
    { label: "Tier", value: tool.tier.toUpperCase() },
    {
      label: "GPU class",
      value: formatGpuClass(tool.gpuType, tool.gpuCount, tool.minVramGb),
    },
    { label: "Runtime", value: formatRuntime(tool.timePerDesignSeconds) },
    { label: "License", value: tool.license || "Not reported" },
    {
      label: "Seed cost",
      value: `${tool.seedCostPerDesign} seed${tool.seedCostPerDesign === 1 ? "" : "s"} / design`,
    },
    {
      label: "Weights",
      value: tool.closedWeights ? "Closed" : "Open",
    },
    {
      label: "Modal app",
      value: tool.modalApp ?? "Not deployed",
    },
  ];

  return (
    <div className="space-y-12">
      <ToolDetailHero
        name={tool.name}
        version={tool.version}
        category={tool.category}
        description={tool.description}
        ctaHref={ctaHref}
      />

      <ParametersTable rows={rows} />

      <section className="pt-8">
        <p className="max-w-xl font-sans text-[14px] leading-relaxed text-graphite">
          Need different parameters or a workflow that chains this tool with
          others? Start a project, pick this tool from the picker, and the
          full parameters editor opens with sensible defaults.
        </p>
      </section>
    </div>
  );
}
