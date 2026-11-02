"use client";

import { useMemo, useState } from "react";
import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActivityFeedFilters } from "./ActivityFeed";

/**
 * The audit `action` enum on the server is narrower than what the activity
 * feed renders, so we keep a dashboard-side action vocabulary that mirrors
 * the spec. Unknown items still flow through; this list only powers the
 * multi-select chips.
 */
const ACTION_OPTIONS: Array<{ id: string; label: string; group: string }> = [
  { id: "project.created", label: "Project created", group: "Projects" },
  { id: "project.updated", label: "Project updated", group: "Projects" },
  { id: "project.deleted", label: "Project deleted", group: "Projects" },
  { id: "target.created", label: "Target added", group: "Targets" },
  {
    id: "target.hotspots-updated",
    label: "Hotspots updated",
    group: "Targets",
  },
  { id: "job.submitted", label: "Job submitted", group: "Jobs" },
  { id: "job.running", label: "Job running", group: "Jobs" },
  { id: "job.succeeded", label: "Job succeeded", group: "Jobs" },
  { id: "job.failed", label: "Job failed", group: "Jobs" },
  { id: "job.cancelled", label: "Job cancelled", group: "Jobs" },
  { id: "design.created", label: "Designs created", group: "Designs" },
  { id: "api_key.created", label: "Key created", group: "Keys" },
  { id: "api_key.rotated", label: "Key rotated", group: "Keys" },
  { id: "api_key.revoked", label: "Key revoked", group: "Keys" },
  { id: "member.invited", label: "Member invited", group: "Team" },
  { id: "member.removed", label: "Member removed", group: "Team" },
  { id: "member.role_changed", label: "Role changed", group: "Team" },
  { id: "subscription.upgraded", label: "Plan upgraded", group: "Billing" },
  { id: "subscription.downgraded", label: "Plan downgraded", group: "Billing" },
  { id: "webhook.created", label: "Webhook created", group: "Webhooks" },
  { id: "webhook.deleted", label: "Webhook deleted", group: "Webhooks" },
  {
    id: "webhook.secret_rotated",
    label: "Webhook rotated",
    group: "Webhooks",
  },
];

type QuickRange = "24h" | "7d" | "30d" | "custom" | null;

export interface ActivityFiltersProps {
  value: ActivityFeedFilters;
  onChange: (next: ActivityFeedFilters) => void;
  /** Org members for the actor dropdown. */
  members?: Array<{ id: string; name: string | null; email: string | null }>;
  /** Projects for the project dropdown. */
  projects?: Array<{ id: string; name: string }>;
}

function rangeFor(q: QuickRange): { from?: Date; to?: Date } {
  if (q === null || q === "custom") return {};
  const now = new Date();
  const from = new Date(now);
  if (q === "24h") from.setHours(now.getHours() - 24);
  if (q === "7d") from.setDate(from.getDate() - 7);
  if (q === "30d") from.setDate(from.getDate() - 30);
  return { from, to: now };
}

export function ActivityFilters({
  value,
  onChange,
  members = [],
  projects = [],
}: ActivityFiltersProps) {
  const [quick, setQuick] = useState<QuickRange>(null);
  const selectedActions = value.actions ?? [];

  const grouped = useMemo(() => {
    const groups = new Map<string, typeof ACTION_OPTIONS>();
    for (const a of ACTION_OPTIONS) {
      const arr = groups.get(a.group) ?? [];
      arr.push(a);
      groups.set(a.group, arr);
    }
    return Array.from(groups.entries());
  }, []);

  const toggleAction = (id: string) => {
    const cur = new Set(selectedActions);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    onChange({ ...value, actions: cur.size ? Array.from(cur) : undefined });
  };

  const setActor = (id: string) => {
    onChange({ ...value, users: id ? [id] : undefined });
  };

  const setProject = (id: string) => {
    onChange({
      ...value,
      resourceIds: id ? [id] : undefined,
      resourceTypes: id ? ["project"] : undefined,
    });
  };

  const applyQuick = (q: QuickRange) => {
    setQuick(q);
    const { from, to } = rangeFor(q);
    onChange({ ...value, from, to });
  };

  const clearAll = () => {
    setQuick(null);
    onChange({});
  };

  const hasAny =
    !!value.actions?.length ||
    !!value.users?.length ||
    !!value.resourceIds?.length ||
    !!value.from ||
    !!value.to;

  return (
    <div className="space-y-4 px-5 py-4">
      {/* Action chips */}
      <div>
        <p className="font-sans text-[12px] text-graphite-soft">
          Action type
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {grouped.map(([group, items]) => (
            <div
              key={group}
              className="flex flex-wrap items-center gap-1.5"
              role="group"
              aria-label={`${group} actions`}
            >
              {items.map((a) => {
                const on = selectedActions.includes(a.id);
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => toggleAction(a.id)}
                    aria-pressed={on}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-sans text-[12px] transition-colors",
                      on
                        ? "border-ink bg-ink text-paper"
                        : "border-lattice-strong bg-paper text-graphite hover:text-ink hover:border-ink",
                    )}
                  >
                    {on && <Check className="w-3 h-3" />}
                    {a.label}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        {/* Actor dropdown */}
        <label className="flex flex-col gap-1">
          <span className="font-sans text-[12px] text-graphite-soft">
            Actor
          </span>
          <select
            value={value.users?.[0] ?? ""}
            onChange={(e) => setActor(e.target.value)}
            className="rounded-xl border border-lattice-strong bg-paper px-3 py-2 font-sans text-[13px] text-ink focus:border-ink focus:outline-none"
          >
            <option value="">Anyone</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name ?? m.email ?? m.id}
              </option>
            ))}
          </select>
        </label>

        {/* Project dropdown */}
        <label className="flex flex-col gap-1">
          <span className="font-sans text-[12px] text-graphite-soft">
            Project
          </span>
          <select
            value={value.resourceIds?.[0] ?? ""}
            onChange={(e) => setProject(e.target.value)}
            className="rounded-xl border border-lattice-strong bg-paper px-3 py-2 font-sans text-[13px] text-ink focus:border-ink focus:outline-none"
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        {/* Date range */}
        <div className="flex flex-col gap-1">
          <span className="font-sans text-[12px] text-graphite-soft">
            Date range
          </span>
          <div className="inline-flex items-center gap-1 bg-paper p-1">
            {(["24h", "7d", "30d", "custom"] as const).map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => applyQuick(q)}
                className={cn(
                  "px-2 py-1 rounded-lg font-sans text-[12px]",
                  quick === q
                    ? "bg-ink text-paper"
                    : "text-graphite hover:bg-paper-fold",
                )}
              >
                {q === "24h" ? "Last 24h" : q === "custom" ? "Custom" : `Last ${q}`}
              </button>
            ))}
          </div>
        </div>

        {quick === "custom" && (
          <div className="inline-flex items-center gap-2">
            <input
              type="date"
              value={value.from ? value.from.toISOString().slice(0, 10) : ""}
              onChange={(e) =>
                onChange({
                  ...value,
                  from: e.target.value ? new Date(e.target.value) : undefined,
                })
              }
              className="px-2 py-1.5 rounded-lg border border-lattice-strong bg-paper font-mono text-[12px] text-ink"
              aria-label="From date"
            />
            <span className="font-sans text-[12px] text-graphite">→</span>
            <input
              type="date"
              value={value.to ? value.to.toISOString().slice(0, 10) : ""}
              onChange={(e) =>
                onChange({
                  ...value,
                  to: e.target.value ? new Date(e.target.value) : undefined,
                })
              }
              className="px-2 py-1.5 rounded-lg border border-lattice-strong bg-paper font-mono text-[12px] text-ink"
              aria-label="To date"
            />
          </div>
        )}

        {hasAny && (
          <button
            type="button"
            onClick={clearAll}
            className="ml-auto inline-flex items-center gap-1 font-sans text-[13px] text-graphite hover:text-ink"
          >
            <X className="w-3.5 h-3.5" />
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

export default ActivityFilters;
