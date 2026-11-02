"use client";

import {
  Atom,
  Boxes,
  Check,
  Clock,
  Cpu,
  FileBadge,
  FileInput,
  Layers,
  Lock,
  Mail,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import {
  toolInputSpec,
  type ToolInputKind,
  type ToolManifest,
  type ToolTier,
} from "@papercrane/types";
import { cn } from "@/lib/utils";

/**
 * Extra fields that may travel on the catalog payload but aren't in the
 * shared `ToolManifestSchema` (yet). The Wave-10 seeds populate `license`
 * and `composes`; we read them defensively so the card is forward-compatible
 * without tightening the shared zod schema.
 */
export type EnrichedTool = ToolManifest & {
  license?: string;
  composes?: string[];
  slug?: string;
  /**
   * Release status from the tools API. GA tools completed live verification;
   * beta tools get a badge even when they are runnable.
   */
  status?: "ga" | "beta";
  /** Whether jobs.submit currently accepts this tool. */
  runnable?: boolean;
};

export type ToolCardProps = {
  tool: EnrichedTool;
  /** Plain-English purpose line shown instead of implementation-centric copy. */
  summary?: string;
  selected: boolean;
  /** False when the tool is unavailable or the user's tier cannot run it. */
  allowed: boolean;
  /** Disabled because the current comparison uses a different input kind. */
  interactionDisabled?: boolean;
  /** Caller's current tier: used to format the upgrade overlay. */
  userTier?: ToolTier;
  onSelect: () => void;
  /** Compact mode renders a tighter card for the pipeline-builder strip. */
  compact?: boolean;
};

type TierMeta = {
  label: string;
  pillClass: string;
  Icon: LucideIcon;
};

function tierMetaFor(tier: ToolTier): TierMeta {
  switch (tier) {
    case "free":
      return {
        label: "Open",
        pillClass: "bg-paper-fold text-graphite border-lattice-strong",
        Icon: ShieldCheck,
      };
    case "pro":
      return {
        label: "Pro",
        pillClass: "bg-ink text-paper border-ink",
        Icon: Cpu,
      };
    case "frontier":
    default:
      return {
        label: "Frontier",
        pillClass: "bg-crane-deep text-paper border-crane-deep",
        Icon: Lock,
      };
  }
}

/**
 * Per-category accent icon. Picked to read at a glance in a dense grid.
 * Maps both kebab-case (TS schema) and bare-word (DB enum) categories.
 */
const CATEGORY_ICON: Record<string, LucideIcon> = {
  "binder-design": Atom,
  composite: Layers,
  "structure-prediction": Atom,
  structure: Atom,
  "sequence-design": Boxes,
  sequence: Boxes,
  validation: FileBadge,
  ranking: FileBadge,
  utility: Layers,
  backbone: Layers,
  "backbone-generation": Layers,
};

/**
 * Visual card for a single tool. Self-contained so it can be rendered both
 * inside the picker grid *and* the pipeline builder strip without dragging
 * in the picker's grouping logic.
 *
 * Layout (full mode):
 *   ┌─────────────────────────────────────┐
 *   │ [ico] [category-tag]    [tier-pill] │  ← top row
 *   │                                     │
 *   │ Tool Name                v1.2.0     │  ← display title
 *   │ TOOL-SLUG                           │  ← mono caption
 *   │                                     │
 *   │ Short description, two or three     │  ← body
 *   │ lines, line-clamped.                │
 *   │ ───────────────────────────         │
 *   │ ☐ GPU 1× A100 (80GB)                │  ← spec rows
 *   │ ☐ ~6s/design · 1.00 seeds           │
 *   └─────────────────────────────────────┘
 */
export function ToolCard({
  tool,
  summary,
  selected,
  allowed,
  interactionDisabled = false,
  userTier,
  onSelect,
  compact = false,
}: ToolCardProps) {
  const tierMeta = tierMetaFor(tool.tier);
  const TierIcon = tierMeta.Icon;
  const CategoryIcon = CATEGORY_ICON[tool.category] ?? Cpu;

  // Frontier tools are commercially gated. Free/Pro callers see a sales
  // overlay rather than a generic "upgrade" tooltip: reflects pricing model.
  const isFrontier = tool.tier === "frontier";
  const executionUnavailable = tool.runnable === false;
  const needsUpgrade = Boolean(
    !interactionDisabled &&
      !executionUnavailable &&
      !allowed &&
      userTier &&
      userTier !== tool.tier,
  );
  const showContactSales = isFrontier && needsUpgrade;
  const isLocked = !allowed || interactionDisabled;

  const isBeta = tool.status === "beta";
  const slug = tool.slug ?? tool.toolId;
  const inputLabel = inputLabelFor(toolInputSpec(slug).inputKind);
  const minVram = tool.compute.minVramGb;
  const gpuLabel = `${tool.compute.gpuCount}× ${tool.compute.gpuType}${
    minVram ? ` (${minVram}GB)` : ""
  }`;

  if (compact) {
    return (
      <button
        type="button"
        role="radio"
        aria-checked={selected}
        aria-disabled={isLocked}
        disabled={isLocked}
        onClick={onSelect}
        data-testid={`e2e-job-tool-${tool.toolId}`}
        className={cn(
          "group relative w-full text-left rounded-lg bg-transparent p-4 transition-all",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-paper",
          selected
            ? "bg-crane-glow"
            : "hover:bg-paper-fold/50",
          !allowed && "opacity-70",
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="shrink-0 inline-flex h-6 w-6 items-center justify-center rounded-md border border-lattice bg-paper-fold/60">
              <CategoryIcon className="w-3 h-3 text-graphite" />
            </span>
            <span className="font-display text-[14px] text-ink leading-tight">
              {tool.name}
            </span>
            {isBeta && <BetaBadge />}
          </div>
          <span
            className={cn(
              "shrink-0 inline-flex items-center rounded-full border px-1.5 py-0.5 font-sans text-[9px]",
              tierMeta.pillClass,
            )}
          >
            {tierMeta.label}
          </span>
        </div>
        <div className="mt-2 font-mono text-[10px] text-graphite-soft tabular-nums">
          v{tool.version} · {gpuLabel}
        </div>
      </button>
    );
  }

  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-disabled={isLocked}
      disabled={isLocked}
      onClick={onSelect}
      data-testid={`e2e-job-tool-${tool.toolId}`}
      className={cn(
        "group relative flex w-full flex-col text-left rounded-lg bg-transparent p-6 transition-all duration-150",
        "min-h-[224px]",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:ring-offset-paper",
        selected ? "bg-crane-glow" : "hover:bg-paper-fold/50",
        !allowed && "opacity-75",
      )}
    >
      {/* Selection check (top-left, only when selected) */}
      {selected && (
        <span
          aria-hidden="true"
          className="absolute -top-2 -left-2 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-ink bg-ink text-paper shadow-sm"
        >
          <Check className="w-3.5 h-3.5" strokeWidth={3} />
        </span>
      )}

      {/* Tier pill (top-right, absolute, never overlaps title) */}
      <span
        className={cn(
          "absolute top-3 right-3 inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-sans text-[12px] shadow-sm",
          tierMeta.pillClass,
        )}
      >
        <TierIcon className="w-3 h-3" aria-hidden="true" strokeWidth={2.25} />
        {tierMeta.label}
      </span>

      {/* Top row: category icon */}
      <div className="flex items-center gap-2 pr-24">
        <span
          aria-hidden="true"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-lattice bg-paper-fold/70"
        >
          <CategoryIcon className="w-4 h-4 text-graphite-soft" />
        </span>
        <span className="font-sans text-[12px] text-graphite-soft">
          {categoryLabel(tool.category)}
        </span>
      </div>

      {/* Title block */}
      <div className="mt-3">
        <div className="flex items-center gap-2">
          <h4 className="font-display text-[19px] sm:text-[20px] font-medium tracking-tight text-ink leading-tight">
            {tool.name}
          </h4>
          {isBeta && <BetaBadge />}
        </div>
        <div className="mt-1 flex items-center gap-2 font-sans text-[12px] text-graphite-soft tabular-nums">
          <span className="truncate">{slug}</span>
          <span className="text-lattice-strong" aria-hidden="true">
            ·
          </span>
          <span>v{tool.version}</span>
        </div>
      </div>

      {/* Description */}
      <p className="mt-3 font-sans text-[13px] leading-relaxed text-graphite line-clamp-3">
        {summary ?? tool.description}
      </p>

      {/* Spec block (bottom, divider above) */}
      <div className="mt-auto pt-4">
        <dl className="mt-3 space-y-1.5 font-mono text-[11.5px] tabular-nums text-ink">
          <div className="flex items-center gap-2">
            <FileInput
              className="w-3.5 h-3.5 text-graphite-soft shrink-0"
              aria-hidden="true"
              strokeWidth={1.75}
            />
            <dt className="sr-only">Input</dt>
            <dd className="truncate">Starts with {inputLabel}</dd>
          </div>
          <div className="flex items-center gap-2">
            <Cpu
              className="w-3.5 h-3.5 text-graphite-soft shrink-0"
              aria-hidden="true"
              strokeWidth={1.75}
            />
            <dt className="sr-only">GPU</dt>
            <dd className="truncate">{gpuLabel}</dd>
          </div>
          <div className="flex items-center gap-2">
            <Clock
              className="w-3.5 h-3.5 text-graphite-soft shrink-0"
              aria-hidden="true"
              strokeWidth={1.75}
            />
            <dt className="sr-only">Runtime &amp; cost</dt>
            <dd className="truncate">
              <span>
                ~{formatMinutes(tool.compute.estimatedMinutes)}/design
              </span>
              <span className="mx-1.5 text-lattice-strong">·</span>
              <span>
                {tool.seedCostPerDesign.toFixed(2)} seed
                {tool.seedCostPerDesign === 1 ? "" : "s"}
              </span>
            </dd>
          </div>
        </dl>
      </div>

      {/* Frontier-locked overlay (only if user can't access). Uses paper-fold
          tone over the card and reveals "Contact sales" on hover only: keeps
          the resting state clean. */}
      {isLocked && (
        <div
          aria-hidden="true"
          className={cn(
            "pointer-events-none absolute inset-0 rounded-lg bg-paper-fold/40 transition-opacity",
            "flex items-end justify-center pb-4 px-4",
          )}
        >
          {interactionDisabled ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-lattice-strong bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite shadow-sm">
              <Lock className="w-3 h-3" />
              Different input
            </span>
          ) : executionUnavailable ? (
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-paper px-3 py-1.5",
                "font-sans text-[12px] text-amber-700 shadow-sm",
              )}
            >
              <Clock className="w-3 h-3" />
              Not yet runnable
            </span>
          ) : showContactSales ? (
            <span
              className={cn(
                "pointer-events-auto inline-flex items-center gap-1.5 rounded-full border border-crane/40 bg-paper px-3 py-1.5",
                "font-sans text-[12px] text-crane-deep shadow-sm",
                "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity",
              )}
            >
              <Mail className="w-3 h-3" />
              Contact sales
            </span>
          ) : (
            <span
              className={cn(
                "pointer-events-auto inline-flex items-center gap-1.5 rounded-full border border-lattice-strong bg-paper px-3 py-1.5",
                "font-sans text-[12px] text-graphite shadow-sm",
                "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity",
              )}
            >
              <Lock className="w-3 h-3" />
              Requires {tierMeta.label}
            </span>
          )}
        </div>
      )}
    </button>
  );
}

/**
 * Subtle "Beta" pill shown next to tools that have not completed the GA
 * verification pass. Beta tools may still be runnable.
 */
function BetaBadge() {
  return (
    <span
      className="shrink-0 inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 font-sans text-[9px] text-amber-700"
      title="Beta: integrated, with limited production verification"
    >
      Beta
    </span>
  );
}

function categoryLabel(category: string): string {
  switch (category) {
    case "binder-design":
    case "composite":
      return "Composite";
    case "structure-prediction":
    case "structure":
      return "Structure";
    case "sequence-design":
    case "sequence":
      return "Sequence";
    case "validation":
    case "ranking":
      return "Validation";
    case "backbone":
    case "backbone-generation":
      return "Backbone";
    case "utility":
      return "Utility";
    default:
      return category.replace(/[-_]/g, " ");
  }
}

function formatMinutes(m: number): string {
  if (m < 1) return `${Math.round(m * 60)}s`;
  if (m < 10) return `${m.toFixed(1)}m`;
  return `${Math.round(m)}m`;
}

function inputLabelFor(kind: ToolInputKind): string {
  switch (kind) {
    case "target":
      return "a target structure";
    case "backbone":
      return "a protein backbone";
    case "complex":
      return "a complex or pair";
    case "sequences":
      return "sequences / FASTA";
  }
}

/**
 * Skeleton placeholder used while the catalog is loading. Same dimensions
 * as a real card so the grid doesn't reflow on first paint.
 */
export function ToolCardSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="relative flex w-full flex-col bg-paper p-6 min-h-[224px] overflow-hidden animate-pulse"
    >
      <div className="flex items-center gap-2">
        <span className="h-8 w-8 rounded-lg bg-paper-fold" />
        <span className="h-2.5 w-20 rounded bg-paper-fold" />
      </div>
      <div className="mt-3 space-y-2">
        <span className="block h-4 w-3/5 rounded bg-paper-fold" />
        <span className="block h-2.5 w-2/5 rounded bg-paper-fold/70" />
      </div>
      <div className="mt-3 space-y-1.5">
        <span className="block h-2.5 w-full rounded bg-paper-fold/70" />
        <span className="block h-2.5 w-11/12 rounded bg-paper-fold/70" />
        <span className="block h-2.5 w-3/4 rounded bg-paper-fold/70" />
      </div>
      <div className="mt-auto pt-4">
        <div className="mt-3 space-y-1.5">
          <span className="block h-2.5 w-2/3 rounded bg-paper-fold/70" />
          <span className="block h-2.5 w-1/2 rounded bg-paper-fold/70" />
        </div>
      </div>
    </div>
  );
}
