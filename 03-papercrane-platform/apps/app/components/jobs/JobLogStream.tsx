"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Search, AlertCircle, Pause, Play } from "lucide-react";

import { subscribeToPgChanges } from "@/lib/realtime/supabase-rt";
import { cn } from "@/lib/utils";

/**
 * Live tail of a job's log lines.
 *
 * Backing store: Supabase Realtime on `audit_logs` filtered to this job's
 * resource id. Each row carries `metadata.line` and `metadata.level` when it
 * came from the worker's log shipper (action='job.log_line'). Status
 * transition rows (action='job.status_changed') are also folded in as info
 * lines so the operator sees a unified stream.
 *
 * Behaviour:
 *   - Keeps the last 200 lines in memory (cheap; rendering is virtualised by
 *     the browser via overflow-y).
 *   - Auto-scrolls to bottom on each new line UNLESS the user scrolled up,
 *     in which case scrolling is paused until they hit the resume button.
 *   - Filter input narrows the visible set by substring (case-insensitive).
 *   - "Errors only" toggle hides info/warn levels.
 *   - Color codes: info=graphite, warn=amber, error=crane-deep.
 */

export type LogLevel = "info" | "warn" | "error";

export interface JobLogLine {
  id: string;
  ts: string; // ISO
  level: LogLevel;
  message: string;
  source?: string; // e.g. 'rfdiffusion', 'queue', 'worker'
}

interface AuditRow {
  id: string;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  metadata?: { line?: string; level?: string; source?: string } | null;
  created_at: string;
}

interface JobLogStreamProps {
  jobId: string;
  initialLines?: JobLogLine[];
  className?: string;
}

const MAX_LINES = 200;

export function JobLogStream({ jobId, initialLines = [], className }: JobLogStreamProps) {
  const [lines, setLines] = useState<JobLogLine[]>(initialLines);
  const [filter, setFilter] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [paused, setPaused] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);

  useEffect(() => {
    const unsubscribe = subscribeToPgChanges<AuditRow>({
      channelName: `rt:audit_logs:job:${jobId}`,
      table: "audit_logs",
      event: "INSERT",
      filter: `resource_id=eq.${jobId}`,
      onChange: (payload) => {
        const row = payload.new as Partial<AuditRow> | undefined;
        if (!row || !row.id) return;
        const meta = row.metadata ?? {};
        const message = meta.line ?? (row.action ? humanizeAction(row.action) : "");
        if (!message) return;
        const level = normalizeLevel(meta.level);
        setLines((prev) => {
          const next: JobLogLine[] = [
            ...prev,
            {
              id: row.id!,
              ts: row.created_at ?? new Date().toISOString(),
              level,
              message,
              source: meta.source,
            },
          ];
          return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
        });
      },
    });
    return unsubscribe;
  }, [jobId]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return lines.filter((l) => {
      if (errorsOnly && l.level !== "error") return false;
      if (needle && !l.message.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [lines, filter, errorsOnly]);

  // Auto-scroll bottom on new line unless user scrolled up.
  useEffect(() => {
    if (paused) return;
    const el = scrollRef.current;
    if (!el) return;
    if (userScrolledRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [visible, paused]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    userScrolledRef.current = !atBottom;
  };

  const resumeTail = () => {
    userScrolledRef.current = false;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setPaused(false);
  };

  return (
    <section aria-label="Job logs" className={cn("space-y-3", className)}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="font-sans text-[12px] text-graphite-soft">
          Logs
        </h2>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-graphite-soft" />
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter lines"
              aria-label="Filter log lines"
              className="pl-8 pr-3 py-1.5 rounded-lg border border-lattice bg-paper font-mono text-[11px] text-ink placeholder:text-graphite-soft w-44 focus:outline-none focus:border-ink"
            />
          </div>
          <button
            type="button"
            onClick={() => setErrorsOnly((v) => !v)}
            aria-pressed={errorsOnly}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 font-sans text-[12px] transition-colors",
              errorsOnly
                ? "border-crane-deep bg-crane-glow text-crane-deep"
                : "border-lattice bg-paper text-graphite hover:text-ink",
            )}
          >
            <AlertCircle className="w-3 h-3" />
            Errors only
          </button>
          {(paused || userScrolledRef.current) && (
            <button
              type="button"
              onClick={resumeTail}
              className="inline-flex items-center gap-1.5 rounded-lg border border-ink bg-ink px-2.5 py-1.5 font-sans text-[12px] text-paper hover:opacity-90"
            >
              <Play className="w-3 h-3" />
              Resume tail
            </button>
          )}
          <button
            type="button"
            onClick={() => setPaused((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-lattice bg-paper px-2.5 py-1.5 font-sans text-[12px] text-graphite hover:text-ink"
            aria-label={paused ? "Resume autoscroll" : "Pause autoscroll"}
          >
            {paused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
            {paused ? "Resume" : "Pause"}
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        className="bg-ink text-paper font-mono text-[11px] leading-relaxed h-72 overflow-y-auto p-4"
      >
        {visible.length === 0 ? (
          <p className="text-graphite-soft italic">
            {lines.length === 0 ? "Waiting for log lines…" : "No lines match filters."}
          </p>
        ) : (
          <ol className="space-y-0.5" role="list">
            {visible.map((l) => (
              <li key={l.id} className="flex gap-3 hover:bg-white/5 px-1 -mx-1 rounded">
                <span className="text-graphite-soft shrink-0 select-none w-20">
                  {fmtTime(l.ts)}
                </span>
                <span
                  className={cn(
                    "shrink-0 select-none w-12 uppercase tracking-[0.12em]",
                    levelColor(l.level),
                  )}
                >
                  {l.level}
                </span>
                {l.source && (
                  <span className="text-paper-fold shrink-0 select-none">
                    [{l.source}]
                  </span>
                )}
                <span className="break-all whitespace-pre-wrap">{l.message}</span>
              </li>
            ))}
          </ol>
        )}
      </div>

      <p className="font-mono text-[10px] text-graphite-soft">
        Showing {visible.length} of {lines.length} lines (max {MAX_LINES} retained).
      </p>
    </section>
  );
}

function levelColor(level: LogLevel): string {
  switch (level) {
    case "error":
      return "text-crane";
    case "warn":
      return "text-amber-400";
    case "info":
    default:
      return "text-paper-fold";
  }
}

function normalizeLevel(raw?: string): LogLevel {
  const v = (raw ?? "").toLowerCase();
  if (v === "error" || v === "err" || v === "fatal") return "error";
  if (v === "warn" || v === "warning") return "warn";
  return "info";
}

function humanizeAction(action: string): string {
  // Convert 'job.status_changed' → 'job status changed'.
  return action.replace(/[._]/g, " ");
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "--:--:--";
  }
}
