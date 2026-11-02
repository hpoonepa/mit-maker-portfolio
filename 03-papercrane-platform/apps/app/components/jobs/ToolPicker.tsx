"use client";

import { useState, type ReactNode } from "react";
import { Clock, GitCompare, Lock, Search, Wrench, X } from "lucide-react";
import type {
  CatalogCategoryKey,
  ComboCard,
  ToolInputKind,
  ToolManifest,
  ToolTier,
} from "@papercrane/types";
import {
  CATALOG_CATEGORIES,
  combosForCategory,
  toCatalogCategory,
  toolInputSpec,
} from "@papercrane/types";
import { cn } from "@/lib/utils";
import { goodAt } from "@/lib/jobs/toolDescriptions";
import { ToolCard, ToolCardSkeleton, type EnrichedTool } from "./ToolCard";

/**
 * ToolPicker supports BOTH selection models, chosen at the call site:
 *
 *   • Single-select (legacy):  `selectedId` + `onSelect`         → radiogroup
 *   • Multi-select  (wizard):  `selectedIds` + `onSelectionChange` → checkbox group
 *
 * Multi mode is inferred whenever `selectedIds` or `onSelectionChange` is
 * provided (or `multiple` is forced true). In multi mode the container role
 * flips to "group" and clicking a card TOGGLES it; selection order is the
 * order the user clicked (stable order consumed by the allocator).
 */
type ToolPickerProps = {
  tools: ToolManifest[];

  // --- Single-select (legacy, backward-compatible) -------------------------
  /** Currently selected tool id (single-select mode). */
  selectedId?: string | null;
  /** Called with the clicked tool id (single-select mode). */
  onSelect?: (toolId: string) => void;

  // --- Multi-select (job wizard) -------------------------------------------
  /** Currently selected tool ids, in selection order (multi-select mode). */
  selectedIds?: string[];
  /** Called with the full next selection (multi-select mode). */
  onSelectionChange?: (toolIds: string[]) => void;
  /**
   * Force multi-select even without multi handlers. Inferred `true` when
   * `selectedIds` or `onSelectionChange` is supplied.
   */
  multiple?: boolean;

  /** Caller's current org tier: used to badge tools they can't run. */
  userTier?: ToolTier;
  /** Client-side filter for locked tools (just visual; submit still validates). */
  isToolAllowed?: (tool: ToolManifest) => boolean;
  /**
   * Server-sourced execution readiness. Runnable GA and beta tools are normal
   * choices; catalog-only tools move into an unavailable disclosure.
   */
  isToolRunnable?: (tool: ToolManifest) => boolean;
  /** Show a skeleton grid while the catalog is loading. */
  loading?: boolean;
};

/**
 * Auto-fit responsive grid. Cards have a min width of ~260px and stretch
 * to fill the available track; on narrow viewports they collapse to a
 * single column without squishing.
 */
const GRID_CLASS =
  "mt-4 grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]";

type CategoryFilter = "all" | CatalogCategoryKey;
type InputFilter = "all" | ToolInputKind;

const CATEGORY_FILTER_LABELS: Record<CatalogCategoryKey, string> = {
  "binder-design": "Design binders",
  "sequence-design": "Design sequences",
  "structure-prediction": "Predict structures",
  scoring: "Analyze & score",
};

const INPUT_FILTERS: ReadonlyArray<{
  key: InputFilter;
  label: string;
  searchTerms: string;
}> = [
  { key: "all", label: "Any input", searchTerms: "" },
  {
    key: "target",
    label: "Target structure",
    searchTerms: "target pdb antigen receptor hotspot binder",
  },
  {
    key: "backbone",
    label: "Protein backbone",
    searchTerms: "backbone pdb fixed structure inverse folding",
  },
  {
    key: "sequences",
    label: "Sequences / FASTA",
    searchTerms: "sequence fasta amino acids",
  },
  {
    key: "complex",
    label: "Complex / pair",
    searchTerms: "complex pair partner cofold structure",
  },
];

/**
 * Defensive read of the "closed weights" flag. The catalog payload carries a
 * `closedWeights` boolean that isn't (yet) on the shared `ToolManifestSchema`,
 * so we read it without tightening the type. Falls back to a license-string
 * heuristic when the flag is absent.
 */
function isClosedWeights(tool: EnrichedTool): boolean {
  const cw = (tool as { closedWeights?: boolean }).closedWeights;
  if (typeof cw === "boolean") return cw;
  const lic = (tool.license ?? "").toLowerCase();
  if (!lic) return false;
  return /proprietary|closed|commercial|frontier|restricted|eval|no-?redistribut/.test(
    lic,
  );
}

/**
 * Grid of tool cards, grouped by category. Cards the current tier can't
 * run are dimmed; frontier-only tools render a "contact sales" hover
 * affordance via {@link ToolCard}.
 */
export function ToolPicker({
  tools,
  selectedId = null,
  onSelect,
  selectedIds,
  onSelectionChange,
  multiple,
  userTier,
  isToolAllowed,
  isToolRunnable,
  loading = false,
}: ToolPickerProps) {
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] =
    useState<CategoryFilter>("all");
  const [inputFilter, setInputFilter] = useState<InputFilter>("all");
  const multiSelect =
    multiple ?? (selectedIds !== undefined || onSelectionChange !== undefined);

  // Normalized selection set used for rendering, regardless of mode.
  const selection = multiSelect
    ? (selectedIds ?? [])
    : selectedId
      ? [selectedId]
      : [];
  const selectedSet = new Set(selection);

  const handleActivate = (toolId: string) => {
    if (multiSelect) {
      const current = selectedIds ?? [];
      const next = current.includes(toolId)
        ? current.filter((id) => id !== toolId)
        : [...current, toolId];
      onSelectionChange?.(next);
    } else {
      onSelect?.(toolId);
    }
  };

  // One-input-kind-per-job (multi-select ONLY): the moment the user picks a
  // tool, the INPUT KIND of that selection becomes the "active input kind".
  // Tools that take a DIFFERENT input kind grey out and stop being selectable,
  // so a single comparison job never mixes inputs. This is FINER-GRAINED than
  // catalog family: Boltz-2 (co-fold, `complex`) and Boltz-1 (raw `sequences`)
  // share the `structure-prediction` family but can't share a job because they
  // need different inputs: whereas Boltz-2 + Chai-1 (both `complex`) is fine.
  // Derived purely from the current selection, so no extra props flow in from
  // the wizard. In single-select mode only one tool is ever chosen, so the lock
  // never applies.
  const firstSelectedTool =
    multiSelect && selection.length > 0
      ? (tools as EnrichedTool[]).find((t) => selectedSet.has(t.toolId))
      : undefined;
  const activeInputKind = firstSelectedTool
    ? toolInputSpec(firstSelectedTool.slug ?? firstSelectedTool.toolId)
        .inputKind
    : null;

  if (loading) {
    return (
      <div className="space-y-2" data-testid="e2e-tool-picker-loading">
        <SectionHeader label="Loading tools" count={6} />
        <div className={GRID_CLASS}>
          {Array.from({ length: 6 }).map((_, i) => (
            <ToolCardSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  if (tools.length === 0) {
    return (
      <div className="px-6 py-10 text-center font-sans text-[14px] text-graphite">
        No tools available yet. Check back shortly.
      </div>
    );
  }

  const normalizedQuery = query.trim().toLowerCase();
  const matchesQuery = (tool: EnrichedTool) => {
    if (!normalizedQuery) return true;
    const slug = tool.slug ?? tool.toolId;
    const inputKind = toolInputSpec(slug).inputKind;
    const inputMeta = INPUT_FILTERS.find((item) => item.key === inputKind);
    const catalogCategory = toCatalogCategory(tool.category);
    return [
      slug,
      tool.name,
      tool.description,
      goodAt(slug, tool.description),
      tool.category,
      tool.license,
      CATEGORY_FILTER_LABELS[catalogCategory],
      inputMeta?.label,
      inputMeta?.searchTerms,
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuery));
  };

  // Readiness is independent of GA/beta status. Integrated beta tools stay in
  // the normal grid; only catalog-only implementations are inert.
  const runnableTools: EnrichedTool[] = [];
  const unavailableTools: EnrichedTool[] = [];
  for (const t of tools as EnrichedTool[]) {
    if (!matchesQuery(t)) continue;
    if (
      categoryFilter !== "all" &&
      toCatalogCategory(t.category) !== categoryFilter
    ) {
      continue;
    }
    if (
      inputFilter !== "all" &&
      toolInputSpec(t.slug ?? t.toolId).inputKind !== inputFilter
    ) {
      continue;
    }
    if (!isToolRunnable || isToolRunnable(t)) runnableTools.push(t);
    else unavailableTools.push(t);
  }

  const filtersActive =
    Boolean(normalizedQuery) ||
    categoryFilter !== "all" ||
    inputFilter !== "all";
  const clearFilters = () => {
    setQuery("");
    setCategoryFilter("all");
    setInputFilter("all");
  };

  // Bucket every tool into one of the 4 canonical catalog categories via the
  // shared taxonomy. `toCatalogCategory` is total (it maps ANY vocab into one
  // of the 4 keys and never drops), but we keep a defensive "Other" bucket for
  // any bucket key that somehow isn't one of the 4 so nothing is ever lost.
  const buckets = new Map<string, EnrichedTool[]>();
  CATALOG_CATEGORIES.forEach((c) => buckets.set(c.key, []));
  const other: EnrichedTool[] = [];
  for (const t of runnableTools) {
    const key = toCatalogCategory(t.category);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(t);
    else other.push(t);
  }

  // Ordered sections: the 4 canonical categories (from CATALOG_CATEGORIES,
  // already in display order) plus the defensive "Other" bucket at the end.
  const sections: Array<{
    key: string;
    label: string;
    tagline?: string;
    inCat: EnrichedTool[];
  }> = CATALOG_CATEGORIES.map((c) => ({
    key: c.key,
    label: c.label,
    tagline: c.tagline,
    inCat: buckets.get(c.key) ?? [],
  }));
  if (other.length > 0) {
    sections.push({ key: "other", label: "Other", inCat: other });
  }

  return (
    <div className="space-y-8" data-testid="e2e-tool-picker">
      {multiSelect && <ModeBanner count={selectedSet.size} />}

      <div className="space-y-5 p-4 sm:p-5">
        <div>
          <label
            htmlFor="tool-search"
            className="font-sans text-[12px] text-graphite-soft"
          >
            Find a tool
          </label>
          <div className="relative mt-2">
            <Search
              className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-graphite-soft"
              aria-hidden="true"
            />
            <input
              id="tool-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by name, purpose, input, or method"
              aria-label="Search tools"
              className="w-full rounded-lg border border-lattice-strong bg-paper py-3 pl-10 pr-11 font-sans text-[14px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/20"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear tool search"
                className="absolute right-2.5 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-graphite-soft hover:bg-paper-fold hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            )}
          </div>
          {!query && (
            <p className="mt-2 font-sans text-[11.5px] text-graphite-soft">
              Try “antibody”, “small molecule”, “stability”, or “docking”.
            </p>
          )}
        </div>

        <FilterGroup label="What do you want to do?">
          <FilterButton
            active={categoryFilter === "all"}
            onClick={() => setCategoryFilter("all")}
          >
            All tools <FilterCount count={tools.length} />
          </FilterButton>
          {CATALOG_CATEGORIES.map((category) => (
            <FilterButton
              key={category.key}
              active={categoryFilter === category.key}
              onClick={() => setCategoryFilter(category.key)}
            >
              {CATEGORY_FILTER_LABELS[category.key]}
              <FilterCount
                count={
                  tools.filter(
                    (tool) =>
                      toCatalogCategory(tool.category) === category.key,
                  ).length
                }
              />
            </FilterButton>
          ))}
        </FilterGroup>

        <FilterGroup label="What do you already have?">
          {INPUT_FILTERS.map((input) => (
            <FilterButton
              key={input.key}
              active={inputFilter === input.key}
              onClick={() => setInputFilter(input.key)}
            >
              {input.label}
            </FilterButton>
          ))}
        </FilterGroup>

        <div className="flex items-center justify-between gap-4 pt-3">
          <p
            aria-live="polite"
            className="font-sans text-[12px] text-graphite"
          >
            Showing {runnableTools.length} runnable tool
            {runnableTools.length === 1 ? "" : "s"}
            {unavailableTools.length > 0 && (
              <span className="text-graphite-soft">
                {" "}+ {unavailableTools.length} catalog-only
              </span>
            )}
          </p>
          {filtersActive && (
            <button
              type="button"
              onClick={clearFilters}
              className="font-sans text-[12px] font-medium text-ink underline decoration-lattice-strong underline-offset-4 hover:decoration-ink"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      <div className="space-y-10">
        {sections.map(({ key, label, inCat }) => {
          // Combo cards live under the binder-design section as "coming soon"
          // pipeline entries; they are not selectable tools.
          const combos =
            key === "binder-design" &&
            !normalizedQuery &&
            inputFilter === "all" &&
            (categoryFilter === "all" || categoryFilter === "binder-design")
              ? combosForCategory("binder-design")
              : [];
          if (inCat.length === 0 && combos.length === 0) return null;
          // A section can be PARTIALLY locked now: its tools may span input
          // kinds (e.g. structure-prediction holds both `complex` and
          // `sequences` tools). The section-level hint only shows when the
          // WHOLE section is off-limits: every tool takes a different input
          // kind than the active selection. (Only ever true in multi mode,
          // since `activeInputKind` is null otherwise.)
          const sectionLocked =
            activeInputKind !== null &&
            inCat.length > 0 &&
            inCat.every(
              (t) =>
                toolInputSpec(t.slug ?? t.toolId).inputKind !== activeInputKind,
            );
          return (
            <section key={key} aria-label={label}>
              <SectionHeader label={label} count={inCat.length} />
              {sectionLocked && (
                <p className="mt-1.5 inline-flex items-center gap-1.5 font-sans text-[12px] italic leading-relaxed text-graphite-soft">
                  <Lock className="h-3 w-3 shrink-0" aria-hidden="true" />
                  These need a different input: clear your selection to switch.
                </p>
              )}
              <div
                role={multiSelect ? "group" : "radiogroup"}
                aria-label={label}
                className={GRID_CLASS}
              >
                {inCat.map((tool) => {
                  const allowed = isToolAllowed ? isToolAllowed(tool) : true;
                  const inputKindLocked =
                    activeInputKind !== null &&
                    toolInputSpec(tool.slug ?? tool.toolId).inputKind !==
                      activeInputKind;
                  return (
                    <ToolCardCell
                      key={tool.toolId}
                      tool={tool}
                      selected={selectedSet.has(tool.toolId)}
                      allowed={allowed}
                      inputKindLocked={inputKindLocked}
                      userTier={userTier}
                      onActivate={() => handleActivate(tool.toolId)}
                    />
                  );
                })}
                {combos.map((combo) => (
                  <ComboCardCell key={combo.id} combo={combo} />
                ))}
              </div>
            </section>
          );
        })}

        {runnableTools.length === 0 && (
          <div className="px-6 py-10 text-center font-sans text-[14px] text-graphite">
            {normalizedQuery
              ? `No runnable tools match “${query.trim()}” with these filters.`
              : filtersActive
                ? "No runnable tools match these filters."
                : "No runnable tools are available on your plan right now."}
          </div>
        )}
      </div>

      {unavailableTools.length > 0 && (
        <UnavailableDisclosure tools={unavailableTools} userTier={userTier} />
      )}
    </div>
  );
}

/**
 * Collapsed shelf for catalogued tools that jobs.submit does not accept yet.
 */
function UnavailableDisclosure({
  tools,
  userTier,
}: {
  tools: EnrichedTool[];
  userTier?: ToolTier;
}) {
  return (
    <details
      data-testid="e2e-tool-picker-experimental"
      open
      className="px-5 py-4"
    >
      <summary className="cursor-pointer list-none font-sans text-[13px] text-graphite marker:content-none hover:text-ink">
        <span className="font-sans text-[12px] text-graphite-soft">
          Catalog only
        </span>
        <span className="ml-2">
          {tools.length} unavailable tool{tools.length === 1 ? "" : "s"}: show
          anyway
        </span>
      </summary>
      <p className="mt-3 max-w-2xl font-sans text-[12.5px] leading-relaxed text-graphite">
        These tools are registered in the catalog but do not have a complete
        executable backend yet, so they can&apos;t be submitted.
      </p>
      <div className={GRID_CLASS}>
        {tools.map((tool) => (
          <ToolCardCell
            key={tool.toolId}
            tool={tool}
            selected={false}
            allowed={false}
            userTier={userTier}
            onActivate={() => {}}
          />
        ))}
      </div>
    </details>
  );
}

/**
 * Wraps a {@link ToolCard} with the plain-English purpose line and license
 * metadata. The card itself owns selection state, tier badge, specs, and the
 * frontier overlay.
 */
function ToolCardCell({
  tool,
  selected,
  allowed,
  inputKindLocked = false,
  userTier,
  onActivate,
}: {
  tool: EnrichedTool;
  selected: boolean;
  /** Tier gate: whether the caller's org tier can run this tool at all. */
  allowed: boolean;
  /**
   * True when a tool taking a different INPUT KIND is already selected
   * (multi-select one-input-kind-per-job rule). This stays separate from the
   * tier `allowed` gate so the card can explain the right lock reason.
   */
  inputKindLocked?: boolean;
  userTier?: ToolTier;
  onActivate: () => void;
}) {
  const slug = tool.slug ?? tool.toolId;
  const tip = goodAt(slug, tool.description);
  const closed = isClosedWeights(tool);

  return (
    <div
      aria-disabled={inputKindLocked || undefined}
      className={cn(
        "relative",
        inputKindLocked && "cursor-not-allowed opacity-60",
      )}
    >
      <ToolCard
        tool={tool}
        summary={tip}
        selected={selected}
        allowed={allowed}
        interactionDisabled={inputKindLocked}
        userTier={userTier}
        onSelect={inputKindLocked ? () => {} : onActivate}
      />
      {tool.license && (
        <div className="mt-1.5 flex items-center px-1">
          <span
            className={cn(
              "inline-flex items-center gap-1 font-sans text-[12px]",
              closed ? "text-crane-deep" : "text-graphite-soft",
            )}
            title={closed ? "Closed weights" : undefined}
          >
            {closed && <Lock className="h-3 w-3 shrink-0" aria-hidden="true" />}
            <span className="truncate">{tool.license}</span>
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Curated multi-stage pipeline surfaced as a card (e.g. RFdiffusion →
 * ProteinMPNN). These are NOT selectable tools: real stage chaining is a
 * follow-up milestone: so the card is a plain, dimmed, non-interactive
 * `<div>` (no button, no `onSelect`, never in `selectedSet`). It borrows the
 * ToolCard visual idiom (paper / lattice / ink / graphite / crane tokens) but
 * wears a dashed border + "Pipeline · Coming soon" badge so it reads as
 * aspirational rather than clickable.
 */
function ComboCardCell({ combo }: { combo: ComboCard }) {
  return (
    <div
      data-testid="e2e-combo-card"
      aria-disabled="true"
      className={cn(
        "relative flex w-full flex-col p-6",
        "min-h-[224px] cursor-not-allowed opacity-70",
      )}
    >
      {/* Coming-soon badge (top-right, mirrors the tier pill slot) */}
      <span className="absolute top-3 right-3 inline-flex items-center gap-1 rounded-full border border-lattice-strong bg-paper px-2.5 py-1 font-sans text-[12px] text-graphite-soft shadow-sm">
        <Clock className="w-3 h-3" aria-hidden="true" strokeWidth={2.25} />
        Pipeline · Coming soon
      </span>

      {/* Top row: pipeline icon + category tag */}
      <div className="flex items-center gap-2 pr-32">
        <span
          aria-hidden="true"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-lattice bg-paper-fold/70"
        >
          <GitCompare className="w-4 h-4 text-graphite-soft" />
        </span>
        <span className="font-sans text-[12px] text-graphite-soft">
          Pipeline
        </span>
      </div>

      {/* Title (the pretty stage chain, e.g. "RFdiffusion → ProteinMPNN") */}
      <div className="mt-3">
        <h4 className="font-display text-[19px] sm:text-[20px] font-medium tracking-tight text-ink leading-tight">
          {combo.name}
        </h4>
      </div>

      {/* Tagline */}
      <p className="mt-3 font-sans text-[13px] leading-relaxed text-graphite line-clamp-3">
        {combo.tagline}
      </p>

      {/* Stage chain (bottom, divider above: mirrors the spec block) */}
      <div className="mt-auto pt-4">
        <div className="mt-3 flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-graphite">
          {combo.stages.map((stage, i) => (
            <span key={stage} className="inline-flex items-center gap-1.5">
              <span className="rounded-md border border-lattice bg-paper px-2 py-0.5">
                {stage}
              </span>
              {i < combo.stages.length - 1 && (
                <span className="text-lattice-strong" aria-hidden="true">
                  →
                </span>
              )}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function FilterGroup({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <p className="font-sans text-[12px] text-graphite-soft">
        {label}
      </p>
      <div
        role="group"
        aria-label={label}
        className="mt-2 flex flex-wrap gap-2"
      >
        {children}
      </div>
    </div>
  );
}

function FilterButton({
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

function FilterCount({ count }: { count: number }) {
  return (
    <span className="font-mono text-[9px] tabular-nums opacity-70">
      {count}
    </span>
  );
}

/**
 * Explanatory banner that reflects the current selection count. NOT a hard
 * toggle: picking a second tool flips the copy to "compare"; dropping back
 * to one reverts it. Plain language so users understand allocation upfront.
 */
function ModeBanner({ count }: { count: number }) {
  const compare = count >= 2;
  return (
    <div
      data-testid="e2e-tool-picker-mode"
      data-mode={compare ? "compare" : "single"}
      className={cn(
        "flex items-start gap-3 py-2 transition-colors",
        compare
          ? "text-crane"
          : "text-graphite",
      )}
    >
      <span
        aria-hidden="true"
        className="mt-0.5 inline-flex h-7 w-5 shrink-0 items-center justify-center"
      >
        {compare ? (
          <GitCompare className="h-3.5 w-3.5 text-crane-deep" strokeWidth={2} />
        ) : (
          <Wrench className="h-3.5 w-3.5 text-graphite" strokeWidth={2} />
        )}
      </span>
      <div className="min-w-0">
        <p className="font-display text-[14px] leading-tight text-ink">
          {compare ? "Compare tools" : "Run one tool"}
        </p>
        <p className="mt-0.5 font-sans text-[12.5px] leading-relaxed text-graphite">
          {compare
            ? `The ${count} selected tools share the design budget. Remove tools to return to a single run.`
            : "Pick one tool. Selecting another switches to a comparison run and splits the design budget."}
        </p>
      </div>
    </div>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-baseline justify-between pb-2">
      <h3 className="font-sans text-[12px] text-ink">
        {label}
      </h3>
      <span className="font-sans text-[12px] text-graphite-soft tabular-nums">
        {count} tool{count === 1 ? "" : "s"}
      </span>
    </div>
  );
}
