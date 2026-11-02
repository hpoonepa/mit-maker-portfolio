"use client";

import { useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "new", label: "New" },
  { value: "reviewing", label: "Reviewing" },
  { value: "addressed", label: "Addressed" },
  { value: "won_t_fix", label: "Won’t fix" },
] as const;

const CATEGORY_OPTIONS = [
  { value: "", label: "All categories" },
  { value: "bug", label: "Bug" },
  { value: "feature", label: "Feature" },
  { value: "improvement", label: "Improvement" },
  { value: "praise", label: "Praise" },
  { value: "other", label: "Other" },
] as const;

type StatusValue = (typeof STATUS_OPTIONS)[number]["value"];
type CategoryValue = (typeof CATEGORY_OPTIONS)[number]["value"];
type FeedbackStatus = Exclude<StatusValue, "">;
type FeedbackCategory = Exclude<CategoryValue, "">;
type FeedbackListInput = {
  status?: FeedbackStatus;
  category?: FeedbackCategory;
  since?: string;
  limit: number;
};

type FeedbackItem = {
  id: string;
  orgId: string | null;
  userId: string | null;
  category: "bug" | "feature" | "improvement" | "praise" | "other";
  rating: number | null;
  body: string;
  pageUrl: string | null;
  userAgent: string | null;
  screenshotKey: string | null;
  metadata: Record<string, unknown> | null;
  status: string;
  createdAt: string;
};

/**
 * Admin-only feedback inbox. Visible to org owners/admins; the tRPC route
 * enforces the role check (this page just calls `feedback.list` and the
 * server returns FORBIDDEN for non-admins, which we render as a friendly
 * "you don't have access" empty state).
 */
export default function AdminFeedbackPage() {
  const [status, setStatus] = useState<StatusValue>("new");
  const [category, setCategory] = useState<CategoryValue>("");
  const [since, setSince] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const listInput = useMemo(() => {
    const input: FeedbackListInput = { limit: 50 };
    if (status) input.status = status;
    if (category) input.category = category;
    if (since) {
      const d = new Date(since);
      if (!Number.isNaN(d.getTime())) input.since = d.toISOString();
    }
    return input;
  }, [status, category, since]);

  const list = trpc.feedback.list.useQuery(listInput, {
    refetchOnWindowFocus: false,
  });
  const utils = trpc.useUtils();
  const updateStatus = trpc.feedback.updateStatus.useMutation({
    onSuccess: () => {
      void utils.feedback.list.invalidate();
    },
  });

  const items: FeedbackItem[] = list.data?.items ?? [];
  const selected = items.find((i) => i.id === selectedId) ?? null;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
      <header className="mb-5 flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="font-mono text-[13px] uppercase tracking-[0.16em] text-ink">
            feedback
          </h1>
          <span className="font-mono text-[11px] text-ink/50">
            {list.data?.items?.length ?? 0} shown · in-app widget
          </span>
        </div>
      </header>

      <section className="mb-4 flex flex-wrap items-end gap-3">
        <Filter
          label="Status"
          value={status}
          onChange={(v) => setStatus(v as StatusValue)}
          options={STATUS_OPTIONS}
        />
        <Filter
          label="Category"
          value={category}
          onChange={(v) => setCategory(v as CategoryValue)}
          options={CATEGORY_OPTIONS}
        />
        <label className="flex flex-col gap-1">
          <span className="font-sans text-[11px] uppercase tracking-wide text-ink/60">
            Since
          </span>
          <input
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            className="rounded border border-lattice bg-paper px-2 py-1 font-sans text-[12.5px] text-ink"
          />
        </label>
      </section>

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="overflow-hidden rounded-lg border border-lattice bg-paper">
          {list.isLoading ? (
            <div className="flex items-center justify-center px-4 py-10 text-ink/60">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : list.isError ? (
            <div
              className="px-4 py-10 text-center font-sans text-[13px] text-ink/60"
              data-testid="feedback-admin-error"
            >
              {list.error?.data?.code === "FORBIDDEN"
                ? "You don’t have access to this org’s feedback."
                : list.error?.message ?? "Could not load feedback."}
            </div>
          ) : items.length === 0 ? (
            <div className="px-4 py-10 text-center font-sans text-[13px] text-ink/60">
              No feedback yet.
            </div>
          ) : (
            <table className="w-full font-sans text-[12.5px]">
              <thead className="border-b border-lattice bg-paper-fold/50 text-left text-[11px] uppercase tracking-wide text-ink/60">
                <tr>
                  <th className="px-3 py-2">When</th>
                  <th className="px-3 py-2">Category</th>
                  <th className="px-3 py-2">Body</th>
                  <th className="px-3 py-2">Rating</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => setSelectedId(row.id)}
                    className={
                      "cursor-pointer border-b border-lattice/60 hover:bg-paper-fold/40 " +
                      (selectedId === row.id ? "bg-paper-fold/60" : "")
                    }
                  >
                    <td className="px-3 py-2 align-top text-ink/70">
                      {new Date(row.createdAt).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 align-top">
                      <CategoryChip category={row.category} />
                    </td>
                    <td className="max-w-md truncate px-3 py-2 align-top text-ink">
                      {row.body}
                    </td>
                    <td className="px-3 py-2 align-top text-ink/70">
                      {row.rating ?? "N/A"}
                    </td>
                    <td className="px-3 py-2 align-top">
                      <StatusChip status={row.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <aside className="rounded-lg border border-lattice bg-paper">
          {selected ? (
            <DetailPanel
              item={selected}
              onStatusChange={(s) =>
                updateStatus.mutate({ id: selected.id, status: s })
              }
              busy={updateStatus.isPending}
            />
          ) : (
            <div className="px-4 py-10 text-center font-sans text-[13px] text-ink/60">
              Select an entry to see details.
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

// ─── Subcomponents ──────────────────────────────────────────────────────────

function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title={`Copy ${id}`}
      onClick={() => {
        void navigator.clipboard?.writeText(id);
        setCopied(true);
        setTimeout(() => setCopied(false), 1100);
      }}
      className="rounded border border-lattice bg-paper-fold/40 px-1.5 py-0.5 font-mono text-[10.5px] text-ink/70 hover:border-ink/30 hover:text-ink"
    >
      {copied ? "copied" : id.slice(0, 8)}
    </button>
  );
}

function Filter({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="font-sans text-[11px] uppercase tracking-wide text-ink/60">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-lattice bg-paper px-2 py-1 font-sans text-[12.5px] text-ink"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function CategoryChip({ category }: { category: FeedbackItem["category"] }) {
  // Brand: only Crane red for bugs (urgent/destructive). Everything else is
  // ink-on-paper utility: admin is not editorial.
  const cls =
    category === "bug"
      ? "border-crane/40 bg-crane/10 text-crane"
      : "border-lattice bg-paper-fold/50 text-ink/70";
  return (
    <span
      className={
        "inline-flex rounded border px-1.5 py-0 font-mono text-[10.5px] uppercase tracking-wide " +
        cls
      }
    >
      {category}
    </span>
  );
}

function StatusChip({ status }: { status: string }) {
  // Status-led, monochrome. "new" gets the only filled treatment so the
  // inbox unread count stays scannable.
  const cls =
    status === "new"
      ? "border-ink bg-ink text-paper"
      : status === "reviewing"
        ? "border-ink/40 bg-paper text-ink"
        : status === "addressed"
          ? "border-lattice bg-paper-fold/50 text-ink/60"
          : "border-lattice bg-paper-fold/30 text-ink/50 line-through";
  return (
    <span
      className={
        "inline-flex rounded border px-1.5 py-0 font-mono text-[10.5px] uppercase tracking-wide " +
        cls
      }
    >
      {status === "won_t_fix" ? "won’t fix" : status}
    </span>
  );
}

function DetailPanel({
  item,
  onStatusChange,
  busy,
}: {
  item: FeedbackItem;
  onStatusChange: (s: "new" | "reviewing" | "addressed" | "won_t_fix") => void;
  busy: boolean;
}) {
  const screenshotInline =
    item.screenshotKey?.startsWith("inline:") ?? false;
  return (
    <div className="flex flex-col gap-3 px-4 py-4">
      <div className="flex items-center justify-between">
        <CategoryChip category={item.category} />
        <CopyId id={item.id} />
      </div>
      <p className="whitespace-pre-wrap font-sans text-[13px] text-ink">
        {item.body}
      </p>
      <dl className="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-1 font-sans text-[12px] text-ink/70">
        <dt>Submitted</dt>
        <dd className="font-mono text-[11.5px]">
          {new Date(item.createdAt).toLocaleString()}
        </dd>
        <dt>Rating</dt>
        <dd className="font-mono text-[11.5px]">{item.rating ?? "N/A"}</dd>
        <dt>Org</dt>
        <dd>{item.orgId ? <CopyId id={item.orgId} /> : <span className="font-mono text-[11.5px] text-ink/40">N/A</span>}</dd>
        <dt>User</dt>
        <dd>{item.userId ? <CopyId id={item.userId} /> : <span className="font-mono text-[11.5px] text-ink/40">N/A</span>}</dd>
        <dt>Page</dt>
        <dd className="break-all font-mono text-[11px]">{item.pageUrl ?? "N/A"}</dd>
        <dt>UA</dt>
        <dd className="break-all font-mono text-[11px] text-ink/60">{item.userAgent ?? "N/A"}</dd>
        <dt>Screenshot</dt>
        <dd className="font-mono text-[11px]">
          {item.screenshotKey
            ? screenshotInline
              ? `inline (${item.screenshotKey.replace("inline:", "")} bytes)`
              : item.screenshotKey
            : "N/A"}
        </dd>
      </dl>
      {item.metadata && (
        <details className="rounded border border-lattice bg-paper-fold/40 px-2 py-1">
          <summary className="cursor-pointer font-sans text-[12px] text-ink/70">
            Metadata
          </summary>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[10.5px] text-ink/80">
            {JSON.stringify(item.metadata, null, 2)}
          </pre>
        </details>
      )}
      <div className="flex flex-col gap-1.5">
        <span className="font-sans text-[11px] uppercase tracking-wide text-ink/60">
          Status
        </span>
        <div className="flex flex-wrap gap-1.5">
          {(["new", "reviewing", "addressed", "won_t_fix"] as const).map(
            (s) => (
              <button
                key={s}
                type="button"
                disabled={busy || item.status === s}
                onClick={() => onStatusChange(s)}
                className={
                  "rounded-full border px-2.5 py-1 font-sans text-[11.5px] " +
                  (item.status === s
                    ? "border-ink bg-ink text-paper"
                    : "border-lattice text-ink hover:bg-paper-fold/50") +
                  (busy ? " opacity-60" : "")
                }
              >
                {s === "won_t_fix" ? "won’t fix" : s}
              </button>
            ),
          )}
        </div>
      </div>
    </div>
  );
}
