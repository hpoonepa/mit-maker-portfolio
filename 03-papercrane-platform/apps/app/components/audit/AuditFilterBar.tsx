"use client";

import { useMemo, useState } from "react";
import { Check, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  AUDIT_ACTIONS,
  formatAuditAction,
  auditActionCategory,
  type AuditAction,
} from "@/lib/audit/formatAction";
import type { AuditFilters } from "./AuditTable";

type QuickRange = "today" | "7d" | "30d" | "custom" | null;

interface AuditFilterBarProps {
  value: AuditFilters;
  onChange: (next: AuditFilters) => void;
}

const RESOURCE_TYPES = [
  "api_key",
  "webhook",
  "member",
  "subscription",
  "job",
  "tool_license",
  "org",
];

function rangeFor(q: QuickRange): { from?: Date; to?: Date } {
  if (q === null || q === "custom") return {};
  const now = new Date();
  const from = new Date(now);
  if (q === "today") from.setHours(0, 0, 0, 0);
  if (q === "7d") from.setDate(from.getDate() - 7);
  if (q === "30d") from.setDate(from.getDate() - 30);
  return { from, to: now };
}

export function AuditFilterBar({ value, onChange }: AuditFilterBarProps) {
  const [quick, setQuick] = useState<QuickRange>(null);
  const [userSearch, setUserSearch] = useState("");
  const [actionOpen, setActionOpen] = useState(false);
  const [resourceOpen, setResourceOpen] = useState(false);

  const toggleAction = (a: AuditAction) => {
    const cur = new Set(value.actions ?? []);
    if (cur.has(a)) cur.delete(a);
    else cur.add(a);
    onChange({ ...value, actions: cur.size ? Array.from(cur) : undefined });
  };

  const toggleResource = (r: string) => {
    const cur = new Set(value.resourceTypes ?? []);
    if (cur.has(r)) cur.delete(r);
    else cur.add(r);
    onChange({
      ...value,
      resourceTypes: cur.size ? Array.from(cur) : undefined,
    });
  };

  const applyQuick = (q: QuickRange) => {
    setQuick(q);
    const { from, to } = rangeFor(q);
    onChange({ ...value, from, to });
  };

  const applyUserSearch = (s: string) => {
    setUserSearch(s);
    const trimmed = s.trim();
    onChange({ ...value, users: trimmed ? [trimmed] : undefined });
  };

  const clearAll = () => {
    setQuick(null);
    setUserSearch("");
    onChange({});
  };

  const selectedActions = value.actions ?? [];
  const selectedResources = value.resourceTypes ?? [];
  const hasAnyFilter =
    !!value.actions?.length ||
    !!value.users?.length ||
    !!value.resourceTypes?.length ||
    !!value.from ||
    !!value.to;

  const groupedActions = useMemo(() => {
    const groups = new Map<string, AuditAction[]>();
    for (const a of AUDIT_ACTIONS) {
      const cat = auditActionCategory(a);
      const arr = groups.get(cat) ?? [];
      arr.push(a);
      groups.set(cat, arr);
    }
    return Array.from(groups.entries());
  }, []);

  return (
    <div className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        {/* Action multi-select */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setActionOpen((x) => !x)}
            className="inline-flex items-center gap-2 rounded-xl border border-lattice-strong bg-paper px-3 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold"
            aria-expanded={actionOpen}
            aria-haspopup="listbox"
          >
            Actions
            {selectedActions.length > 0 && (
              <span className="rounded-full bg-ink px-1.5 py-0.5 font-mono text-[10px] text-paper">
                {selectedActions.length}
              </span>
            )}
          </button>
          {actionOpen && (
            <div
              role="listbox"
              aria-label="Filter by action"
              className="absolute z-20 mt-1 w-[320px] max-h-[360px] overflow-y-auto rounded-lg border border-lattice-strong bg-paper p-2 shadow-lg"
            >
              {groupedActions.map(([cat, actions]) => (
                <div key={cat} className="mb-1">
                  <div className="px-2 py-1 font-sans text-[12px] text-graphite-soft">
                    {cat}
                  </div>
                  {actions.map((a) => {
                    const on = selectedActions.includes(a);
                    return (
                      <button
                        key={a}
                        role="option"
                        aria-selected={on}
                        type="button"
                        onClick={() => toggleAction(a)}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left font-sans text-[13px]",
                          on ? "bg-paper-fold text-ink" : "text-graphite hover:bg-paper-fold",
                        )}
                      >
                        <span
                          className={cn(
                            "inline-flex h-4 w-4 items-center justify-center rounded border",
                            on ? "border-ink bg-ink text-paper" : "border-lattice-strong",
                          )}
                        >
                          {on && <Check className="w-3 h-3" />}
                        </span>
                        {formatAuditAction(a)}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Resource multi-select */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setResourceOpen((x) => !x)}
            className="inline-flex items-center gap-2 rounded-xl border border-lattice-strong bg-paper px-3 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold"
            aria-expanded={resourceOpen}
            aria-haspopup="listbox"
          >
            Resources
            {selectedResources.length > 0 && (
              <span className="rounded-full bg-ink px-1.5 py-0.5 font-mono text-[10px] text-paper">
                {selectedResources.length}
              </span>
            )}
          </button>
          {resourceOpen && (
            <div
              role="listbox"
              aria-label="Filter by resource type"
              className="absolute z-20 mt-1 w-[220px] rounded-lg border border-lattice-strong bg-paper p-2 shadow-lg"
            >
              {RESOURCE_TYPES.map((r) => {
                const on = selectedResources.includes(r);
                return (
                  <button
                    key={r}
                    role="option"
                    aria-selected={on}
                    type="button"
                    onClick={() => toggleResource(r)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left font-sans text-[13px]",
                      on ? "bg-paper-fold text-ink" : "text-graphite hover:bg-paper-fold",
                    )}
                  >
                    <span
                      className={cn(
                        "inline-flex h-4 w-4 items-center justify-center rounded border",
                        on ? "border-ink bg-ink text-paper" : "border-lattice-strong",
                      )}
                    >
                      {on && <Check className="w-3 h-3" />}
                    </span>
                    <span className="font-mono text-[12px]">{r}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* User search */}
        <label className="relative inline-flex items-center">
          <Search className="absolute left-2 w-4 h-4 text-graphite-soft pointer-events-none" />
          <input
            type="search"
            placeholder="User id or email…"
            value={userSearch}
            onChange={(e) => applyUserSearch(e.target.value)}
            className="pl-8 pr-3 py-2 rounded-xl border border-lattice-strong bg-paper font-sans text-[13px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
        </label>

        {/* Quick date ranges */}
        <div className="inline-flex items-center gap-1 bg-paper p-1">
          {(["today", "7d", "30d", "custom"] as const).map((q) => (
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
              {q === "today" ? "Today" : q === "custom" ? "Custom" : q}
            </button>
          ))}
        </div>

        {quick === "custom" && (
          <div className="inline-flex items-center gap-2">
            <input
              type="date"
              value={value.from ? value.from.toISOString().slice(0, 10) : ""}
              onChange={(e) => {
                const d = e.target.value ? new Date(e.target.value) : undefined;
                onChange({ ...value, from: d });
              }}
              className="px-2 py-1.5 rounded-lg border border-lattice-strong bg-paper font-mono text-[12px] text-ink"
              aria-label="From date"
            />
            <span className="font-sans text-[12px] text-graphite">→</span>
            <input
              type="date"
              value={value.to ? value.to.toISOString().slice(0, 10) : ""}
              onChange={(e) => {
                const d = e.target.value ? new Date(e.target.value) : undefined;
                onChange({ ...value, to: d });
              }}
              className="px-2 py-1.5 rounded-lg border border-lattice-strong bg-paper font-mono text-[12px] text-ink"
              aria-label="To date"
            />
          </div>
        )}

        {hasAnyFilter && (
          <button
            type="button"
            onClick={clearAll}
            className="inline-flex items-center gap-1 font-sans text-[13px] text-graphite hover:text-ink"
          >
            <X className="w-3.5 h-3.5" />
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

export default AuditFilterBar;
