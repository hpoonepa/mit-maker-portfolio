"use client";

import { useEffect } from "react";
import { Globe, Monitor, User, X } from "lucide-react";
import { formatAuditAction } from "@/lib/audit/formatAction";
import type { AuditRow } from "./AuditTable";

interface AuditDetailDrawerProps {
  row: AuditRow;
  onClose: () => void;
}

function fmtTime(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d) : d;
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "long",
  });
}

/**
 * Slide-in drawer showing the full audit entry: action, actor, metadata JSON,
 * user-agent, IP, and a placeholder block for IP-geolocation (wired up in
 * a later pass: for now we render the raw IP and a "lookup" affordance).
 */
export function AuditDetailDrawer({ row, onClose }: AuditDetailDrawerProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Audit entry details"
      className="fixed inset-0 z-50 flex"
    >
      {/* scrim */}
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="flex-1 bg-ink/30"
      />

      {/* panel */}
      <aside className="w-full sm:w-[540px] bg-paper border-l border-lattice-strong h-full overflow-y-auto">
        <header className="flex items-start justify-between gap-4 px-6 py-5">
          <div>
            <p className="font-sans text-[12px] text-graphite-soft">
              Audit entry
            </p>
            <h2 className="mt-1 font-display text-[22px] text-ink">
              {formatAuditAction(row.action)}
            </h2>
            <p className="mt-1 font-mono text-[11px] text-graphite tabular-nums">
              {fmtTime(row.createdAt)}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-graphite hover:bg-paper-fold hover:text-ink"
            aria-label="Close details"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="px-6 py-5 space-y-6">
          <section>
            <h3 className="font-sans text-[12px] text-graphite-soft">
              Identity
            </h3>
            <div className="mt-2 grid grid-cols-[20px_1fr] gap-x-3 gap-y-2 font-sans text-[13px] text-ink">
              <User className="w-4 h-4 text-graphite mt-0.5" />
              <div>
                <div>{row.actorName ?? row.actorEmail ?? "N/A"}</div>
                {row.userId && (
                  <div className="font-mono text-[11px] text-graphite">
                    {row.userId}
                  </div>
                )}
              </div>
              <Globe className="w-4 h-4 text-graphite mt-0.5" />
              <div>
                <div className="font-mono text-[12px]">
                  {row.ipAddress ?? "N/A"}
                </div>
                <div className="font-sans text-[11px] text-graphite-soft">
                  Geolocation lookup will surface here (follow-up).
                </div>
              </div>
              <Monitor className="w-4 h-4 text-graphite mt-0.5" />
              <div className="font-mono text-[12px] break-all">
                {row.userAgent ?? "N/A"}
              </div>
            </div>
          </section>

          <section>
            <h3 className="font-sans text-[12px] text-graphite-soft">
              Resource
            </h3>
            <div className="mt-2 font-mono text-[12px] text-ink">
              {row.resourceType ? (
                <>
                  <span className="text-graphite">{row.resourceType}</span>
                  <span className="text-graphite-soft"> · </span>
                  <span>{row.resourceId ?? "N/A"}</span>
                </>
              ) : (
                <span className="text-graphite">N/A</span>
              )}
            </div>
          </section>

          <section>
            <h3 className="font-sans text-[12px] text-graphite-soft">
              Metadata
            </h3>
            <pre className="mt-2 rounded-xl border border-lattice bg-paper-fold/60 px-3 py-3 font-mono text-[11px] text-ink overflow-x-auto max-h-[360px]">
              {row.metadata ? JSON.stringify(row.metadata, null, 2) : "{}"}
            </pre>
          </section>

          <section>
            <h3 className="font-sans text-[12px] text-graphite-soft">
              Event id
            </h3>
            <div className="mt-1 font-mono text-[11px] text-graphite break-all">
              {row.id}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}

export default AuditDetailDrawer;
