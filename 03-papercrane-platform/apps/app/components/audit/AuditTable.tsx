"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import {
  formatAuditAction,
  auditActionCategory,
  type AuditAction,
} from "@/lib/audit/formatAction";
import { AuditDetailDrawer } from "./AuditDetailDrawer";

export interface AuditRow {
  id: string;
  orgId: string;
  userId: string | null;
  action: AuditAction;
  resourceType: string | null;
  resourceId: string | null;
  metadata: Record<string, unknown> | null;
  ipAddress: string | null;
  userAgent: string | null;
  createdAt: string | Date;
  actorEmail?: string | null;
  actorName?: string | null;
}

export interface AuditFilters {
  actions?: AuditAction[];
  users?: string[];
  resourceTypes?: string[];
  from?: Date;
  to?: Date;
}

interface AuditTableProps {
  /** Initial rows (server-rendered first page). */
  initialRows: AuditRow[];
  initialNextCursor: string | null;
  filters: AuditFilters;
  limit?: number;
}

const ROW_HEIGHT = 52;
const OVERSCAN = 6;

function formatTime(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "N/A";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatRelative(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "N/A";
  const diffMs = Date.now() - date.getTime();
  const sec = Math.round(diffMs / 1000);
  if (sec < 5) return "JUST NOW";
  if (sec < 60) return `${sec}S AGO`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}M AGO`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}H AGO`;
  const day = Math.round(hr / 24);
  if (day < 30) return `${day}D AGO`;
  const mo = Math.round(day / 30);
  if (mo < 12) return `${mo}MO AGO`;
  return `${Math.round(mo / 12)}Y AGO`;
}

function actor(row: AuditRow): string {
  if (row.actorName) return row.actorName;
  if (row.actorEmail) return row.actorEmail;
  if (row.userId) return row.userId.slice(0, 8);
  return "system";
}

function metadataPreview(meta: Record<string, unknown> | null): string {
  if (!meta) return "";
  const keys = Object.keys(meta);
  if (keys.length === 0) return "";
  const first = keys
    .slice(0, 3)
    .map((k) => {
      const v = meta[k];
      const s =
        typeof v === "string"
          ? v
          : typeof v === "number" || typeof v === "boolean"
            ? String(v)
            : JSON.stringify(v);
      return `${k}=${s.length > 20 ? s.slice(0, 20) + "…" : s}`;
    })
    .join(" ");
  return keys.length > 3 ? `${first} +${keys.length - 3}` : first;
}

/**
 * Virtualized audit-log table.
 *
 * - Server hands us the first page; subsequent pages load via
 *   `trpc.audit.list` with the `nextCursor`.
 * - Row virtualization keeps DOM light for 10k+ rows. We don't use a library
 *   to avoid a new dep: a windowed slice over the merged array is enough.
 * - Each row is a `<button>` for keyboard access; clicking opens the detail
 *   drawer.
 */
export function AuditTable({
  initialRows,
  initialNextCursor,
  filters,
  limit = 50,
}: AuditTableProps) {
  const [rows, setRows] = useState<AuditRow[]>(initialRows);
  const [cursor, setCursor] = useState<string | null>(initialNextCursor);
  const [openRow, setOpenRow] = useState<AuditRow | null>(null);

  // Reset when filters change.
  const filterKey = JSON.stringify(filters);
  const lastFilterKey = useRef(filterKey);

  // TODO(@papercrane/trpc): tRPC client here uses the declared audit router.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anyTrpc = trpc as any;
  const refetchInitial = anyTrpc.audit.list.useQuery(
    { cursor: undefined, limit, filters },
    {
      enabled: lastFilterKey.current !== filterKey,
      refetchOnWindowFocus: false,
    },
  );
  useEffect(() => {
    if (lastFilterKey.current !== filterKey && refetchInitial.data) {
      const data = refetchInitial.data as {
        items: AuditRow[];
        nextCursor: string | null;
      };
      setRows(data.items);
      setCursor(data.nextCursor);
      lastFilterKey.current = filterKey;
    }
  }, [filterKey, refetchInitial.data]);

  const fetchMore = anyTrpc.audit.list.useQuery(
    { cursor, limit, filters },
    { enabled: false, refetchOnWindowFocus: false },
  );

  const loadMore = async () => {
    if (!cursor) return;
    const res = await fetchMore.refetch();
    const data = res.data as
      | { items: AuditRow[]; nextCursor: string | null }
      | undefined;
    if (!data) return;
    setRows((prev) => [...prev, ...data.items]);
    setCursor(data.nextCursor);
  };

  // --- virtualization ------------------------------------------------------
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(560);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => setScrollTop(el.scrollTop);
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight));
    ro.observe(el);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      ro.disconnect();
    };
  }, []);

  const total = rows.length;
  const totalH = total * ROW_HEIGHT;
  const visibleStart = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const visibleEnd = Math.min(
    total,
    Math.ceil((scrollTop + viewportH) / ROW_HEIGHT) + OVERSCAN,
  );
  const window = useMemo(
    () => rows.slice(visibleStart, visibleEnd),
    [rows, visibleStart, visibleEnd],
  );

  if (total === 0) {
    return (
      <div className="px-8 py-14 text-center">
        <p className="font-sans text-[14px] text-graphite">
          No audit events match these filters.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="overflow-hidden">
        <div
          ref={scrollRef}
          className="max-h-[560px] overflow-y-auto"
          role="grid"
          aria-label="Audit log entries"
        >
          <div className="sticky top-0 z-10 grid grid-cols-[180px_200px_200px_1fr_240px_140px] gap-0 border-b border-lattice bg-paper-fold/95 px-5 py-3">
            <Th>Time</Th>
            <Th>Actor</Th>
            <Th>Action</Th>
            <Th>Resource / Metadata</Th>
            <Th>IP / UA</Th>
            <Th>&nbsp;</Th>
          </div>
          <div style={{ height: totalH, position: "relative" }}>
            <div
              style={{
                position: "absolute",
                top: visibleStart * ROW_HEIGHT,
                left: 0,
                right: 0,
              }}
            >
              {window.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  onClick={() => setOpenRow(row)}
                  className={cn(
                    "group grid w-full grid-cols-[180px_200px_200px_1fr_240px_140px]",
                    "gap-0 items-center px-5 text-left",
                    "border-t border-lattice/60 hover:bg-paper/60 transition-colors",
                    "focus:outline-none focus:ring-2 focus:ring-ink/20",
                  )}
                  style={{ height: ROW_HEIGHT }}
                  aria-label={`${formatAuditAction(row.action)} by ${actor(row)} at ${formatTime(row.createdAt)}`}
                >
                  <span
                    className="font-sans text-[12px] text-graphite tabular-nums truncate"
                    title={formatTime(row.createdAt)}
                  >
                    <span className="group-hover:hidden">{formatRelative(row.createdAt)}</span>
                    <span className="hidden group-hover:inline normal-case tracking-normal">
                      {formatTime(row.createdAt)}
                    </span>
                  </span>
                  <span className="font-sans text-[13px] text-ink truncate" title={actor(row)}>
                    {actor(row)}
                  </span>
                  <span className="font-sans text-[13px] text-ink">
                    <span
                      className="inline-flex items-center gap-1.5 rounded-full border border-lattice bg-paper px-2 py-0.5 font-sans text-[12px] text-graphite"
                      data-category={auditActionCategory(row.action)}
                    >
                      {formatAuditAction(row.action)}
                    </span>
                  </span>
                  <span className="font-mono text-[12px] text-graphite truncate">
                    {row.resourceType ? `${row.resourceType}:${row.resourceId ?? "N/A"} ` : ""}
                    {metadataPreview(row.metadata)}
                  </span>
                  <span
                    className="font-mono text-[11px] text-graphite truncate"
                    title={row.userAgent ?? ""}
                  >
                    <span className="group-hover:hidden">{row.ipAddress ?? "N/A"}</span>
                    <span className="hidden group-hover:inline">
                      {row.ipAddress ?? "N/A"}
                      {row.userAgent ? ` · ${row.userAgent.slice(0, 28)}${row.userAgent.length > 28 ? "…" : ""}` : ""}
                    </span>
                  </span>
                  <span className="font-sans text-[12px] text-graphite group-hover:text-ink text-right">
                    Details →
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {cursor && (
        <div className="flex justify-center mt-4">
          <button
            type="button"
            onClick={loadMore}
            disabled={fetchMore.isFetching}
            className="inline-flex items-center gap-1.5 rounded-xl border border-lattice-strong bg-paper px-4 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold transition-colors disabled:opacity-60"
          >
            <ChevronDown className="w-4 h-4" />
            {fetchMore.isFetching ? "Loading…" : "Load more"}
          </button>
        </div>
      )}

      {openRow && (
        <AuditDetailDrawer
          row={openRow}
          onClose={() => setOpenRow(null)}
        />
      )}
    </>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-sans text-[12px] text-graphite-soft">
      {children}
    </span>
  );
}

export default AuditTable;
