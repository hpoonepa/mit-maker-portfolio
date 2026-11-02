"use client";

import { useMemo, useState } from "react";
import { PUBLIC_TOOL_CATALOG, type PublicTool } from "@/lib/tool-catalog";

const CATEGORY_LABELS: Record<string, string> = {
  binder_design: "Binder design",
  backbone_generation: "Backbone generation",
  sequence_design: "Sequence design",
  structure_prediction: "Structure prediction",
  embedding_scoring: "Embeddings & scoring",
};

const CATEGORY_ORDER = [
  "binder_design",
  "backbone_generation",
  "sequence_design",
  "structure_prediction",
  "embedding_scoring",
];

export function PublicToolCatalog() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      PUBLIC_TOOL_CATALOG.filter((tool) => {
        const matchesCategory = category === "all" || tool.category === category;
        const matchesQuery = !normalizedQuery || [tool.name, tool.slug, tool.category, tool.license]
          .some((value) => value.toLowerCase().includes(normalizedQuery));
        return matchesCategory && matchesQuery;
      }),
    [category, normalizedQuery],
  );

  return (
    <div>
      <div className="mb-10 space-y-4 border-y border-lattice-strong bg-paper-fold/20 py-5">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search tools by name, category, or license"
          aria-label="Search public tool catalog"
          className="w-full rounded-lg border border-lattice-strong bg-paper px-4 py-3 font-sans text-[14px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/20"
        />
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter public tool catalog">
          <FilterButton active={category === "all"} onClick={() => setCategory("all")}>
            All tools <span className="opacity-60">{PUBLIC_TOOL_CATALOG.length}</span>
          </FilterButton>
          {CATEGORY_ORDER.map((key) => (
            <FilterButton key={key} active={category === key} onClick={() => setCategory(key)}>
              {CATEGORY_LABELS[key]} <span className="opacity-60">{PUBLIC_TOOL_CATALOG.filter((tool) => tool.category === key).length}</span>
            </FilterButton>
          ))}
        </div>
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-graphite-soft" aria-live="polite">
          {filtered.length} of {PUBLIC_TOOL_CATALOG.length} tools shown
        </p>
      </div>

      {filtered.length === 0 ? (
        <p className="border-b border-lattice py-12 text-center font-sans text-[14px] text-graphite">No tools match that search.</p>
      ) : (
        <div className="grid gap-px bg-lattice-strong hairline-border sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((tool, index) => <ToolCard key={tool.slug} tool={tool} index={index} />)}
        </div>
      )}
    </div>
  );
}

function ToolCard({ tool, index }: { tool: PublicTool; index: number }) {
  return (
    <article className="group relative min-h-[185px] bg-paper p-6 transition-colors hover:bg-paper-fold">
      <div className="flex items-start justify-between gap-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-graphite-soft">
          {String(index + 1).padStart(2, "0")} · {tool.version}
        </span>
        <span className={tool.status === "ga" ? "text-crane" : "text-graphite-soft"}>
          <span className="font-mono text-[10px] uppercase tracking-[0.15em]">{tool.status}</span>
        </span>
      </div>
      <h2 className="mt-8 font-display text-[25px] leading-none tracking-tight text-ink">{tool.name}</h2>
      <div className="absolute bottom-6 left-6 right-6 flex items-end justify-between gap-4">
        <span className="font-sans text-[12px] text-graphite">{CATEGORY_LABELS[tool.category] ?? tool.category}</span>
        <span className="max-w-[45%] text-right font-mono text-[9px] uppercase tracking-[0.12em] text-graphite-soft">{tool.license}</span>
      </div>
      {!tool.runnable && <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.12em] text-crane">Catalog only · not runnable</p>}
    </article>
  );
}

function FilterButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 font-sans text-[12px] transition-colors ${active ? "border-ink bg-ink text-paper" : "border-lattice-strong bg-paper text-graphite hover:border-ink/40 hover:text-ink"}`}
    >
      {children}
    </button>
  );
}
