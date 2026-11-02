"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Activity as ActivityIcon } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { ActivityItem, type ActivityRow } from "./ActivityItem";
import { EmptyState } from "@/components/empty/EmptyState";

export interface ActivityFeedFilters {
  /** Multi-select action ids (e.g. `job.submitted`). */
  actions?: string[];
  /** Filter by user ids. */
  users?: string[];
  /** Filter by resource type (e.g. `project`, `job`). */
  resourceTypes?: string[];
  /** Scope feed to a specific resource: used on project pages. */
  resourceIds?: string[];
  from?: Date;
  to?: Date;
}

interface ActivityFeedProps {
  initialRows: ActivityRow[];
  initialNextCursor: string | null;
  filters?: ActivityFeedFilters;
  /** When true, hide load-more chrome (compact dashboard preview). */
  compact?: boolean;
  /** Page size for follow-up fetches. */
  limit?: number;
  /** Empty-state CTA: shown when the feed has zero rows. */
  emptyCta?: { href: string; label: string };
}

/**
 * Group consecutive rows that share the same `action` and `userId` into a
 * single feed item with a `groupCount`. Useful for "5 designs created" rollups
 * after a batch finishes.
 */
function groupRows(rows: ActivityRow[]): ActivityRow[] {
  const out: ActivityRow[] = [];
  for (const r of rows) {
    const last = out[out.length - 1];
    if (
      last &&
      last.action === r.action &&
      last.userId === r.userId &&
      last.resourceType === r.resourceType &&
      // Only roll up batch-style actions; don't collapse distinct project ops.
      (r.action === "design.created" || r.action === "webhook.delivered")
    ) {
      last.groupCount = (last.groupCount ?? 1) + 1;
      continue;
    }
    out.push({ ...r });
  }
  return out;
}

export function ActivityFeed({
  initialRows,
  initialNextCursor,
  filters,
  compact = false,
  limit = 25,
  emptyCta,
}: ActivityFeedProps) {
  const [rows, setRows] = useState<ActivityRow[]>(initialRows);
  const [cursor, setCursor] = useState<string | null>(initialNextCursor);

  // Reset when filters change (filterKey is shallow JSON of the filter shape).
  const filterKey = useMemo(() => JSON.stringify(filters ?? {}), [filters]);
  const lastFilterKey = useRef(filterKey);

  // tRPC client is loosely typed in this codebase: `audit.list` exists but
  // isn't always picked up by the generated types in this monorepo build.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anyTrpc = trpc as any;

  const refetch = anyTrpc.audit.list.useQuery(
    { cursor: undefined, limit, filters: filters ?? {} },
    {
      enabled: lastFilterKey.current !== filterKey,
      refetchOnWindowFocus: false,
    },
  );
  useEffect(() => {
    if (lastFilterKey.current !== filterKey && refetch.data) {
      const data = refetch.data as {
        items: ActivityRow[];
        nextCursor: string | null;
      };
      setRows(data.items);
      setCursor(data.nextCursor);
      lastFilterKey.current = filterKey;
    }
  }, [filterKey, refetch.data]);

  const more = anyTrpc.audit.list.useQuery(
    { cursor, limit, filters: filters ?? {} },
    { enabled: false, refetchOnWindowFocus: false },
  );

  const loadMore = async () => {
    if (!cursor) return;
    const res = await more.refetch();
    const data = res.data as
      | { items: ActivityRow[]; nextCursor: string | null }
      | undefined;
    if (!data) return;
    setRows((prev) => [...prev, ...data.items]);
    setCursor(data.nextCursor);
  };

  const grouped = useMemo(() => groupRows(rows), [rows]);

  if (grouped.length === 0) {
    return (
      <EmptyState
        icon={<ActivityIcon className="h-5 w-5" />}
        title="Nothing has happened here yet"
        description="As your team submits jobs, comments, and ships designs, the feed will populate."
        primaryCta={
          emptyCta ? { label: emptyCta.label, href: emptyCta.href } : undefined
        }
      />
    );
  }

  return (
    <div>
      <ul className="divide-y divide-lattice/60">
        {grouped.map((row) => (
          <li key={row.id}>
            <ActivityItem row={row} />
          </li>
        ))}
      </ul>
      {!compact && cursor && (
        <div className="flex justify-center mt-4">
          <button
            type="button"
            onClick={loadMore}
            disabled={more.isFetching}
            className="inline-flex items-center gap-1.5 rounded-xl border border-lattice-strong bg-paper px-4 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold transition-colors disabled:opacity-60"
          >
            <ChevronDown className="w-4 h-4" />
            {more.isFetching ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}

export default ActivityFeed;
