"use client";

import { cn } from "@/lib/utils";

type TopUser = {
  userId: string;
  name: string | null;
  email: string | null;
  seedsConsumed: number;
  jobCount: number;
};

type TopUsersTableProps = {
  items: TopUser[];
  className?: string;
};

/**
 * Top 10 users in the org ranked by seed spend this period. Renders a
 * compact horizontal-bar style row per user so spend is visible at a
 * glance without an extra chart.
 */
export function TopUsersTable({ items, className }: TopUsersTableProps) {
  if (items.length === 0) {
    return (
      <div
        className={cn(
          "px-6 py-10 text-center",
          className,
        )}
      >
        <p className="font-sans text-[13px] text-graphite">
          No user activity yet this period.
        </p>
      </div>
    );
  }

  const max = Math.max(...items.map((i) => i.seedsConsumed), 1);

  return (
    <div
      className={cn(
        "p-6",
        className,
      )}
    >
      <div className="flex items-baseline justify-between">
        <div>
          <div className="font-sans text-[12px] text-graphite-soft">
            Team usage
          </div>
          <div className="mt-2 font-sans font-medium text-[20px] text-ink tracking-[-0.01em]">
            {items.length} {items.length === 1 ? "member" : "members"} this
            period
          </div>
        </div>
        <span className="font-sans text-[12px] text-graphite-soft">
          Seeds · Jobs
        </span>
      </div>

      <ol className="mt-5 space-y-2.5">
        {items.map((u) => {
          const pct = (u.seedsConsumed / max) * 100;
          const display = u.name ?? u.email ?? "Unknown user";
          return (
            <li
              key={u.userId}
              className="group border-transparent px-3 py-2 transition-colors"
            >
              <div className="flex items-center gap-3">
                <Avatar name={display} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate font-sans text-[14px] text-ink">
                      {display}
                    </span>
                    <span className="shrink-0 font-sans tabular-nums text-[12px] text-ink">
                      {formatCount(u.seedsConsumed)}
                      <span className="text-graphite-soft"> · {u.jobCount}</span>
                    </span>
                  </div>
                  <div className="mt-1 h-[3px] w-full overflow-hidden rounded-full bg-lattice">
                    <div
                      className="h-full bg-ink transition-[width] duration-700 ease-out group-hover:bg-crane"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("") || "?";
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-paper-deep font-sans tabular-nums text-[12px] text-ink-soft">
      {initials}
    </span>
  );
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toString();
}
