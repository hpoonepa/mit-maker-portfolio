"use client";

import { cn } from "@/lib/utils";

type ActivityItem = {
  id: string;
  action: string;
  resourceType: string | null;
  resourceId: string | null;
  createdAt: Date | string;
  actorName: string | null;
  actorEmail: string | null;
};

type RecentActivityProps = {
  items: ActivityItem[];
  className?: string;
};

/**
 * Compact list of the last ~10 audit-log events for the org. Each row
 * surfaces who did what and how long ago, with a subtle dot per event
 * type so the eye picks out clusters of the same activity. Reads from
 * `dashboard.getRecentActivity` which ultimately joins `audit_logs → users`.
 */
export function RecentActivity({ items, className }: RecentActivityProps) {
  if (items.length === 0) {
    return (
      <div
        className={cn(
          "px-6 py-10 text-center",
          className,
        )}
      >
        <p className="font-sans text-[13px] text-graphite">
          No recent activity in this workspace.
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "p-6",
        className,
      )}
    >
      <div className="flex items-baseline justify-between gap-4">
        <div className="font-sans text-[12px] text-graphite-soft">
          Recent activity
        </div>
        <a
          href="/app/activity"
          className="font-sans text-[12px] text-graphite hover:text-ink"
        >
          Full log →
        </a>
      </div>

      <ol className="mt-5 divide-y divide-lattice/60">
        {items.map((it) => {
          const ts = typeof it.createdAt === "string"
            ? new Date(it.createdAt)
            : it.createdAt;
          const display = it.actorName ?? it.actorEmail ?? "System";
          return (
            <li
              key={it.id}
              className="group flex items-start gap-3 px-1 py-2 transition-colors hover:bg-paper-fold/60"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "mt-[7px] inline-block h-1.5 w-1.5 shrink-0 rounded-full",
                  actionTone(it.action),
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate font-sans text-[14px] text-ink">
                    <span className="text-graphite-soft">{display}</span>{" "}
                    <span className="text-ink">{actionVerb(it.action)}</span>
                    {it.resourceType ? (
                      <span className="text-graphite">
                        {" "}
                        {it.resourceType}
                      </span>
                    ) : null}
                  </span>
                  <span
                    className="shrink-0 font-sans tabular-nums text-[12px] text-graphite-soft tabular-nums"
                    title={ts.toISOString()}
                  >
                    {timeAgo(ts)}
                  </span>
                </div>
                {it.resourceId ? (
                  <div className="mt-0.5 truncate font-sans tabular-nums text-[12px] text-graphite-soft">
                    {it.resourceId.slice(0, 18)}
                    {it.resourceId.length > 18 ? "…" : ""}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function actionTone(action: string): string {
  if (action.includes("created") || action.includes("upgraded")) {
    return "bg-ink";
  }
  if (
    action.includes("revoked") ||
    action.includes("removed") ||
    action.includes("cancelled") ||
    action.includes("deleted")
  ) {
    return "bg-crane";
  }
  if (action.includes("rotated") || action.includes("changed")) {
    return "bg-amber-500";
  }
  return "bg-graphite-soft";
}

function actionVerb(action: string): string {
  // "api_key.created" → "created"; "subscription.upgraded" → "upgraded"
  const [scope, verb] = action.split(".");
  if (!verb || !scope) return action;
  return `${verb} ${scope.replace(/_/g, " ")}`;
}

function timeAgo(d: Date): string {
  const diffSec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (diffSec < 45) return "just now";
  if (diffSec < 90) return "1m";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m`;
  if (diffSec < 7200) return "1h";
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h`;
  if (diffSec < 172800) return "1d";
  return `${Math.floor(diffSec / 86400)}d`;
}
