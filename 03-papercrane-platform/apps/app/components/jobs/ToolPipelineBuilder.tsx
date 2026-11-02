"use client";

import { useMemo, useState } from "react";
import { ArrowRight, Plus, Trash2, X } from "lucide-react";
import type { ToolManifest, ToolTier } from "@papercrane/types";
import { cn } from "@/lib/utils";
import { ToolCard, type EnrichedTool } from "./ToolCard";

/**
 * A pipeline is an ordered list of tool ids: first tool runs first, each
 * subsequent tool consumes the previous one's outputs. We keep it as ids
 * rather than tool refs so it round-trips cleanly through state and is
 * easy to compare for prebuilt-vs-custom detection.
 */
export type Pipeline = string[];

export type PipelinePreset = {
  id: string;
  name: string;
  description: string;
  tools: Pipeline;
};

/**
 * Curated quick-picks. Tool slugs match the Wave-10 catalog ids; if a
 * preset references a tool that the current org's tier can't run we still
 * show the preset (greyed) so the user sees what's behind an upgrade.
 */
export const PIPELINE_PRESETS: readonly PipelinePreset[] = [
  {
    id: "rfd-mpnn-boltz2",
    name: "RFdiffusion → MPNN → Boltz-2",
    description: "Open-weights default: backbones, sequences, validate.",
    tools: ["rfdiffusion", "proteinmpnn", "boltz2"],
  },
  {
    id: "protenix-boltz2",
    name: "Protenix2025 → Boltz-2",
    description: "All-atom backbones with structural validation.",
    tools: ["boltzgen", "boltz2"],
  },
  {
    id: "bindcraft",
    name: "BindCraft (composite)",
    description: "End-to-end binder hallucination with built-in AF2 check.",
    tools: ["bindcraft"],
  },
  {
    id: "soluble-boltz1",
    name: "RFdiffusion → SolubleMPNN → Boltz-1",
    description: "Solubility-tuned for E. coli expression.",
    tools: ["rfdiffusion", "solublempnn", "boltz1"],
  },
  {
    id: "frontier-af3",
    name: "RFdiffusion → MPNN → AlphaFold3",
    description: "Frontier-tier validation: highest-confidence ranking.",
    tools: ["rfdiffusion", "proteinmpnn", "alphafold3"],
  },
] as const;

export type ToolPipelineBuilderProps = {
  tools: ToolManifest[];
  /** Current pipeline (ordered tool ids). */
  value: Pipeline;
  onChange: (next: Pipeline) => void;
  userTier?: ToolTier;
  isToolAllowed?: (tool: ToolManifest) => boolean;
  /** Number of designs the run will produce: drives the GPU-seconds total. */
  numDesigns?: number;
};

/**
 * Sequential pipeline editor. Renders the current pipeline as a row of
 * compact cards joined by arrow connectors, and exposes a quick-pick
 * preset row plus an "add tool" picker. Designed to live next to
 * {@link ToolPicker}: both can write the same selection state.
 */
export function ToolPipelineBuilder({
  tools,
  value,
  onChange,
  userTier,
  isToolAllowed,
  numDesigns = 1,
}: ToolPipelineBuilderProps) {
  const byId = useMemo(() => {
    const m = new Map<string, EnrichedTool>();
    for (const t of tools as EnrichedTool[]) m.set(t.toolId, t);
    return m;
  }, [tools]);

  const [adding, setAdding] = useState(false);

  const resolved = value
    .map((id) => byId.get(id))
    .filter((t): t is EnrichedTool => !!t);

  const totalGpuSeconds = useMemo(
    () =>
      resolved.reduce(
        (acc, t) =>
          acc +
          t.compute.gpuCount * t.compute.estimatedMinutes * 60 * numDesigns,
        0,
      ),
    [resolved, numDesigns],
  );

  const totalSeeds = useMemo(
    () =>
      resolved.reduce((acc, t) => acc + t.seedCostPerDesign * numDesigns, 0),
    [resolved, numDesigns],
  );

  const matchedPreset = PIPELINE_PRESETS.find(
    (p) =>
      p.tools.length === value.length &&
      p.tools.every((id, i) => value[i] === id),
  );

  return (
    <section
      aria-label="Pipeline builder"
      data-testid="e2e-tool-pipeline-builder"
      className="bg-paper p-5"
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <h4 className="font-display text-[16px] text-ink">Pipeline</h4>
          <p className="mt-0.5 font-sans text-[12px] text-graphite">
            Chain tools sequentially: outputs of step <em>n</em> feed step{" "}
            <em>n+1</em>.
          </p>
        </div>
        {matchedPreset && (
          <span className="inline-flex items-center gap-1 rounded-full border border-crane/30 bg-crane-glow px-2 py-0.5 font-sans text-[12px] text-crane-deep">
            {matchedPreset.name}
          </span>
        )}
      </header>

      {/* Quick-pick preset chips */}
      <div className="mt-4">
        <p className="font-sans text-[12px] text-graphite-soft">
          Quick picks
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {PIPELINE_PRESETS.map((preset) => {
            const active = matchedPreset?.id === preset.id;
            return (
              <button
                key={preset.id}
                type="button"
                onClick={() => onChange([...preset.tools])}
                data-testid={`e2e-pipeline-preset-${preset.id}`}
                title={preset.description}
                className={cn(
                  "rounded-full border px-3 py-1 font-sans text-[12px] transition-colors",
                  active
                    ? "border-ink bg-ink text-paper"
                    : "border-lattice bg-paper-fold/40 text-graphite hover:border-lattice-strong hover:text-ink",
                )}
              >
                {preset.name}
              </button>
            );
          })}
        </div>
      </div>

      {/* Pipeline strip */}
      <div className="mt-5">
        {resolved.length === 0 ? (
          <div className="px-4 py-6 text-center font-sans text-[13px] text-graphite">
            No steps yet: pick a preset above or{" "}
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="underline decoration-lattice-strong underline-offset-2 hover:text-ink"
            >
              add a tool
            </button>
            .
          </div>
        ) : (
          <ol className="flex flex-wrap items-stretch gap-2">
            {resolved.map((tool, i) => (
              <li
                key={`${tool.toolId}-${i}`}
                className="flex items-stretch gap-2"
              >
                <PipelineStep
                  tool={tool}
                  index={i}
                  userTier={userTier}
                  allowed={isToolAllowed ? isToolAllowed(tool) : true}
                  onRemove={() => {
                    const next = value.slice();
                    next.splice(i, 1);
                    onChange(next);
                  }}
                  onMoveLeft={
                    i > 0
                      ? () => {
                          const next = value.slice();
                          const prev = next[i - 1]!;
                          const cur = next[i]!;
                          next[i - 1] = cur;
                          next[i] = prev;
                          onChange(next);
                        }
                      : undefined
                  }
                  onMoveRight={
                    i < resolved.length - 1
                      ? () => {
                          const next = value.slice();
                          const cur = next[i]!;
                          const after = next[i + 1]!;
                          next[i] = after;
                          next[i + 1] = cur;
                          onChange(next);
                        }
                      : undefined
                  }
                />
                {i < resolved.length - 1 && (
                  <ArrowRight
                    className="self-center w-5 h-5 text-graphite-soft"
                    aria-hidden="true"
                  />
                )}
              </li>
            ))}
            <li className="flex items-stretch">
              <button
                type="button"
                onClick={() => setAdding((v) => !v)}
                data-testid="e2e-pipeline-add"
                className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-lattice-strong bg-paper px-4 py-3 font-sans text-[12px] text-graphite hover:border-ink hover:text-ink"
              >
                <Plus className="w-4 h-4" aria-hidden="true" />
                Add tool
              </button>
            </li>
          </ol>
        )}
      </div>

      {/* Inline picker for appending a tool */}
      {adding && (
        <div className="mt-4 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="font-sans text-[12px] text-graphite-soft">
              Append tool to pipeline
            </p>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="rounded-full p-1 text-graphite-soft hover:text-ink"
              aria-label="Close picker"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="mt-3 grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]">
            {(tools as EnrichedTool[]).map((tool) => (
              <ToolCard
                key={tool.toolId}
                tool={tool}
                selected={false}
                allowed={isToolAllowed ? isToolAllowed(tool) : true}
                userTier={userTier}
                compact
                onSelect={() => {
                  onChange([...value, tool.toolId]);
                  setAdding(false);
                }}
              />
            ))}
          </div>
        </div>
      )}

      {/* Sticky-style footer with cumulative compute estimate */}
      <footer className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-paper-fold/50 px-4 py-3">
        <dl className="flex flex-wrap items-center gap-x-6 gap-y-1 font-mono text-[11px] text-graphite">
          <div>
            <dt className="text-graphite-soft uppercase tracking-[0.14em]">
              Steps
            </dt>
            <dd className="font-display text-[15px] text-ink">
              {resolved.length}
            </dd>
          </div>
          <div>
            <dt className="text-graphite-soft uppercase tracking-[0.14em]">
              GPU-seconds
            </dt>
            <dd className="font-display text-[15px] text-ink">
              {formatGpuSeconds(totalGpuSeconds)}
            </dd>
          </div>
          <div>
            <dt className="text-graphite-soft uppercase tracking-[0.14em]">
              Seeds
            </dt>
            <dd className="font-display text-[15px] text-ink">
              {totalSeeds.toFixed(1)}
            </dd>
          </div>
        </dl>
        {resolved.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="inline-flex items-center gap-1.5 rounded-full border border-lattice px-3 py-1 font-sans text-[11px] text-graphite hover:border-ink hover:text-ink"
          >
            <Trash2 className="w-3 h-3" aria-hidden="true" />
            Clear pipeline
          </button>
        )}
      </footer>
    </section>
  );
}

function PipelineStep({
  tool,
  index,
  allowed,
  userTier,
  onRemove,
  onMoveLeft,
  onMoveRight,
}: {
  tool: EnrichedTool;
  index: number;
  allowed: boolean;
  userTier?: ToolTier;
  onRemove: () => void;
  onMoveLeft?: () => void;
  onMoveRight?: () => void;
}) {
  return (
    <div className="relative w-[240px]">
      <span className="absolute -left-2 -top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-ink bg-paper font-mono text-[10px] font-medium text-ink shadow-sm">
        {index + 1}
      </span>
      <ToolCard
        tool={tool}
        selected
        allowed={allowed}
        userTier={userTier}
        compact
        onSelect={() => {
          /* selection inside the strip is a no-op; reorder via buttons */
        }}
      />
      <div className="mt-1 flex items-center justify-between gap-1 px-1">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onMoveLeft}
            disabled={!onMoveLeft}
            className="rounded p-0.5 text-graphite-soft hover:text-ink disabled:opacity-30"
            aria-label="Move step left"
          >
            ←
          </button>
          <button
            type="button"
            onClick={onMoveRight}
            disabled={!onMoveRight}
            className="rounded p-0.5 text-graphite-soft hover:text-ink disabled:opacity-30"
            aria-label="Move step right"
          >
            →
          </button>
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-0.5 text-graphite-soft hover:text-ink"
          aria-label="Remove step"
        >
          <Trash2 className="w-3 h-3" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

function formatGpuSeconds(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  const m = s / 60;
  if (m < 60) return `${m.toFixed(1)}m`;
  const h = m / 60;
  return `${h.toFixed(2)}h`;
}
