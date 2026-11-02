"use client";

/**
 * DesignsFilterPanel: children content for the FilterBar on /app/designs.
 * Extracted from page.tsx to keep the page under the 500-line cap and to
 * isolate the multi-input grid (tool / metric ranges / project / job /
 * starred toggle) so it can evolve independently.
 */

import { toolLabel } from "@/lib/results/metrics";
import { Star } from "lucide-react";
import { cn } from "@/lib/utils";
import { MultiSelectChips } from "@/components/filters/MultiSelectChips";
import { RangeSlider } from "@/components/filters/RangeSlider";

export interface DesignsFilters {
  tools: string[];
  iptm: { min: number; max: number };
  pae: { min: number; max: number };
  pdockq: { min: number; max: number };
  length: { min: number; max: number };
  project: string;
  job: string;
  starredOnly: string;
  [k: string]: unknown;
}

export interface DesignsFilterPanelProps {
  filters: DesignsFilters;
  bounds: {
    iptm: { min: number; max: number };
    pae: { min: number; max: number };
    pdockq: { min: number; max: number };
    length: { min: number; max: number };
  };
  tools: string[];
  projects: { id: string; name: string }[];
  jobsForProject: { id: string; count: number }[];
  availableMetrics?: string[];
  setFilter: <K extends keyof DesignsFilters>(
    key: K,
    value: DesignsFilters[K],
  ) => void;
}

export function DesignsFilterPanel({
  filters,
  bounds,
  tools,
  projects,
  jobsForProject,
  availableMetrics = [],
  setFilter,
}: DesignsFilterPanelProps) {
  return (
    <div className="grid gap-5 md:grid-cols-2">
      <MultiSelectChips
        label="Tool"
        options={tools.map((id) => ({ id, label: toolLabel(id) }))}
        value={filters.tools}
        onChange={(v) => setFilter("tools", v)}
        className="md:col-span-2"
      />
      {availableMetrics.includes("ipTM") && (
        <RangeSlider
          label="ipTM"
          min={bounds.iptm.min}
          max={bounds.iptm.max}
          step={0.01}
          value={filters.iptm}
          onChange={(v) => setFilter("iptm", v)}
          format={(n) => n.toFixed(2)}
        />
      )}
      {availableMetrics.includes("PAE") && (
        <RangeSlider
          label="pAE"
          min={bounds.pae.min}
          max={bounds.pae.max}
          step={0.5}
          value={filters.pae}
          onChange={(v) => setFilter("pae", v)}
          format={(n) => n.toFixed(1)}
        />
      )}
      {availableMetrics.includes("pDockQ") && (
        <RangeSlider
          label="pDockQ"
          min={bounds.pdockq.min}
          max={bounds.pdockq.max}
          step={0.01}
          value={filters.pdockq}
          onChange={(v) => setFilter("pdockq", v)}
          format={(n) => n.toFixed(2)}
        />
      )}
      <fieldset className="space-y-2">
        <legend className="text-xs text-graphite">Sequence length (aa)</legend>
        <div className="flex items-center gap-2">
          <input
            type="number"
            aria-label="Minimum sequence length"
            min={0}
            placeholder="No minimum"
            value={
              filters.length.min === bounds.length.min ? "" : filters.length.min
            }
            onChange={(e) =>
              setFilter("length", {
                ...filters.length,
                min:
                  e.target.value === ""
                    ? bounds.length.min
                    : Math.max(0, Number(e.target.value)),
              })
            }
            className="w-full rounded-lg border border-lattice bg-paper px-3 py-2 text-sm"
          />
          <span className="text-graphite-soft">to</span>
          <input
            type="number"
            aria-label="Maximum sequence length"
            min={0}
            placeholder="No maximum"
            value={
              filters.length.max === bounds.length.max ? "" : filters.length.max
            }
            onChange={(e) =>
              setFilter("length", {
                ...filters.length,
                max:
                  e.target.value === ""
                    ? bounds.length.max
                    : Math.max(0, Number(e.target.value)),
              })
            }
            className="w-full rounded-lg border border-lattice bg-paper px-3 py-2 text-sm"
          />
        </div>
      </fieldset>
      <div className="space-y-2">
        <div className="font-sans text-[12px] text-graphite-soft">
          Project
        </div>
        <select
          value={filters.project}
          onChange={(e) => {
            setFilter("project", e.target.value);
            setFilter("job", ""); // job ids are project-scoped
          }}
          className="w-full rounded-xl border border-lattice bg-paper px-3 py-1.5 font-sans text-[13px] text-ink focus:outline-none focus:border-ink"
        >
          <option value="">{projects[0]?.name ?? "Select project"}</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-2">
        <div className="font-sans text-[12px] text-graphite-soft">
          Job
        </div>
        <select
          value={filters.job}
          onChange={(e) => setFilter("job", e.target.value)}
          className="w-full rounded-xl border border-lattice bg-paper px-3 py-1.5 font-sans text-[13px] text-ink focus:outline-none focus:border-ink"
        >
          <option value="">All jobs in project</option>
          {jobsForProject.map((j) => (
            <option key={j.id} value={j.id}>
              {j.id.slice(0, 8)} ({j.count})
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-2 md:col-span-2">
        <div className="flex items-center justify-between">
          <div className="font-sans text-[12px] text-graphite-soft">
            Saved results
          </div>
          <label className="inline-flex items-center gap-1.5 font-sans text-[12px] text-graphite">
            <input
              type="checkbox"
              checked={filters.starredOnly === "1"}
              onChange={(e) =>
                setFilter("starredOnly", e.target.checked ? "1" : "")
              }
              className="h-3.5 w-3.5 accent-amber-400"
            />
            <Star
              className={cn(
                "h-3.5 w-3.5",
                filters.starredOnly === "1"
                  ? "fill-amber-400 text-amber-500"
                  : "text-graphite-soft",
              )}
            />
            Starred only
          </label>
        </div>
      </div>
    </div>
  );
}
