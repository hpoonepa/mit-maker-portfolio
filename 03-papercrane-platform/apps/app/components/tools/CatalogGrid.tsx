"use client";

import { useState, type ReactNode } from "react";
import { Search, X } from "lucide-react";
import {
  CATALOG_CATEGORIES,
  toCatalogCategory,
  type CatalogCategoryKey,
} from "@papercrane/types";
import { cn } from "@/lib/utils";
import { goodAt } from "@/lib/jobs/toolDescriptions";
import { CatalogCard, type CatalogCardTool } from "./CatalogCard";

type CategoryFilter = "all" | CatalogCategoryKey;

/** Searchable catalog with direct entry into each tool’s inputs. */
export function CatalogGrid({ tools }: { tools: CatalogCardTool[] }) {
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [categoryFilter, setCategoryFilter] =
    useState<CategoryFilter>("all");
  const normalizedQuery = query.trim().toLowerCase();

  const matchesQuery = (tool: CatalogCardTool) => {
    if (!normalizedQuery) return true;
    return [
      tool.name,
      tool.slug,
      tool.description,
      tool.category,
      goodAt(tool.slug),
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuery));
  };

  const filteredTools = tools.filter(
    (tool) =>
      (showAll || (tool.runnable === true && !tool.metadataOffline)) &&
      matchesQuery(tool) &&
      (categoryFilter === "all" ||
        toCatalogCategory(tool.category) === categoryFilter),
  );
  const byCategory = new Map<CatalogCategoryKey, CatalogCardTool[]>();
  for (const t of filteredTools) {
    const key = toCatalogCategory(t.category);
    const bucket = byCategory.get(key);
    if (bucket) bucket.push(t);
    else byCategory.set(key, [t]);
  }

  const sections = CATALOG_CATEGORIES.filter(
    (category) =>
      categoryFilter === "all" || category.key === categoryFilter,
  )
    .map((category) => ({
      category,
      tools: byCategory.get(category.key) ?? [],
    }))
    .filter((s) => s.tools.length > 0);

  if (tools.length === 0) {
    return (
      <p className="border-t border-lattice py-12 font-sans text-[14px] text-graphite">
        No tools published yet. Check back shortly.
      </p>
    );
  }

  return (
    <div className="space-y-10">
      <div className="space-y-4 py-5">
        <div className="flex items-center gap-5" role="group" aria-label="Tool availability">
          <button type="button" onClick={() => setShowAll(false)} aria-pressed={!showAll} className={!showAll ? "text-sm text-crane" : "text-sm text-graphite"}>Ready to run</button>
          <button type="button" onClick={() => setShowAll(true)} aria-pressed={showAll} className={showAll ? "text-sm text-crane" : "text-sm text-graphite"}>Full catalog</button>
        </div>
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-graphite-soft"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tools by name, purpose, or method"
            aria-label="Search tool catalog"
            className="w-full rounded-lg border-0 bg-paper-fold/60 py-3 pl-10 pr-11 font-sans text-[14px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/20"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear catalog search"
              className="absolute right-2.5 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-graphite-soft hover:bg-paper-fold hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>

        <div
          role="group"
          aria-label="Filter catalog by tool type"
          className="flex flex-wrap gap-2"
        >
          <CatalogFilterButton
            active={categoryFilter === "all"}
            onClick={() => setCategoryFilter("all")}
          >
            All tools <span className="opacity-60">{tools.length}</span>
          </CatalogFilterButton>
          {CATALOG_CATEGORIES.map((category) => (
            <CatalogFilterButton
              key={category.key}
              active={categoryFilter === category.key}
              onClick={() => setCategoryFilter(category.key)}
            >
              {category.label}
              <span className="opacity-60">
                {
                  tools.filter(
                    (tool) =>
                      toCatalogCategory(tool.category) === category.key,
                  ).length
                }
              </span>
            </CatalogFilterButton>
          ))}
        </div>

        <div className="flex items-center justify-between gap-4">
          <p aria-live="polite" className="font-sans text-[12px] text-graphite">
            {filteredTools.length} matching tool
            {filteredTools.length === 1 ? "" : "s"}
          </p>
          {(query || categoryFilter !== "all") && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setCategoryFilter("all");
              }}
              className="font-sans text-[12px] font-medium text-ink underline decoration-lattice-strong underline-offset-4 hover:decoration-ink"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {sections.length === 0 && (
        <div className="py-12 text-center">
          <p className="font-display text-[20px] text-ink">No tools found</p>
          <p className="mt-2 font-sans text-[13px] text-graphite">
            Try another search or switch to the full catalog to see upcoming tools.
          </p>
        </div>
      )}

      {sections.map(({ category, tools: sectionTools }) => {
        const count = sectionTools.length;
        return (
          <section key={category.key}>
            <div className="flex items-baseline justify-between gap-4 pb-3">
              <h2 className="font-sans text-[19px] text-ink">
                {category.label}
              </h2>
              <span className="shrink-0 font-sans text-[12px] text-graphite-soft">
                {count}
              </span>
            </div>

            <div className="mt-2 grid gap-x-16 gap-y-2 md:grid-cols-2">
              {sectionTools.map((t) => (
                <CatalogCard key={t.id} tool={t} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function CatalogFilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 font-sans text-[13px] transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/30",
        active
          ? "bg-paper-fold text-crane"
          : "text-graphite hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
