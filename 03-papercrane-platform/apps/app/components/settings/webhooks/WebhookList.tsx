"use client";

import Link from "next/link";
import { Plus, Webhook as WebhookIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { WebhookCreateForm } from "./WebhookCreateForm";

function formatDate(d?: string | Date | null): string {
  if (!d) return "N/A";
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "N/A";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Top-level webhook management UI. Renders:
 *   - header with "new" affordance
 *   - empty state CTA (matches /app/keys style)
 *   - inline create form (toggle)
 *   - list of existing subscriptions
 *
 * Live announcements go through `role="status"` and `aria-live="polite"`
 * on the toast region so screen readers pick up test/delete results
 * without stealing focus.
 */
export function WebhookList() {
  const query = trpc.webhooks.list.useQuery();
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; message: string } | null>(
    null,
  );

  const rows = useMemo(() => query.data?.items ?? [], [query.data]);

  const notify = (msg: { kind: "ok" | "err"; message: string }) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4500);
  };

  return (
    <div className="space-y-8">
      <header className="flex items-end justify-between gap-6 flex-wrap">
        <div>
          <p className="font-sans text-[12px] text-graphite-soft">
            Integrations
          </p>
          <h1 className="mt-2 font-display text-display-md text-ink">
            Webhooks
          </h1>
          <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
            A webhook tells us where to POST a signed message whenever
            something happens in your account: a job finishes, a top hit
            lands: so your own systems can react without polling us. During
            the beta you can add, pause, and remove endpoints; delivery logs
            and test-fires arrive after the beta.
          </p>
        </div>
        {!creating && (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="btn-primary"
          >
            <Plus className="w-4 h-4" />
            New webhook
          </button>
        )}
      </header>

      {/* Live region for toasts (test delivery sent, etc.) */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {toast?.message}
      </div>

      {toast && (
        <div
          className={cn(
            "rounded-lg border px-4 py-3 font-sans text-[13px]",
            toast.kind === "ok"
              ? "border-lattice bg-paper-fold text-ink"
              : "border-crane/40 bg-crane-glow text-crane-deep",
          )}
        >
          {toast.message}
        </div>
      )}

      {creating && (
        <WebhookCreateForm
          onClose={() => setCreating(false)}
          onCreated={() =>
            notify({ kind: "ok", message: "Webhook created." })
          }
        />
      )}

      <section className="overflow-hidden">
        {query.isLoading ? (
          <div className="px-8 py-14 text-center font-sans text-[14px] text-graphite">
            Loading…
          </div>
        ) : query.isError ? (
          <div
            role="alert"
            className="px-8 py-10 text-center font-sans text-[14px] text-crane-deep"
          >
            Failed to load webhooks: {query.error?.message ?? "unknown error"}
          </div>
        ) : rows.length === 0 ? (
          <div className="px-8 py-14 text-center">
            <div className="mx-auto inline-flex h-12 w-12 items-center justify-center bg-paper">
              <WebhookIcon className="w-5 h-5 text-ink" />
            </div>
            <h2 className="mt-4 font-display text-[22px] text-ink">
              No webhooks yet
            </h2>
            <p className="mt-2 mx-auto max-w-md font-sans text-[14px] text-graphite">
              Add one to stream{" "}
              <code className="font-mono text-[12px]">job.completed</code>,{" "}
              <code className="font-mono text-[12px]">job.failed</code>, and
              top-hit events to your systems.
            </p>
            {!creating && (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="btn-primary mt-6"
              >
                <Plus className="w-4 h-4" />
                New webhook
              </button>
            )}
          </div>
        ) : (
          <table className="w-full border-collapse">
            <thead className="bg-paper-fold">
              <tr className="text-left">
                <Th>URL</Th>
                <Th>Events</Th>
                <Th>Status</Th>
                <Th>Created</Th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((w, idx) => (
                <tr
                  key={w.id}
                  className={cn(
                    "hover:bg-paper/60 transition-colors",
                    idx > 0 && "border-t border-lattice",
                  )}
                >
                  <td className="px-5 py-3 font-mono text-[13px] text-ink break-all max-w-md">
                    {w.url}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex flex-wrap gap-1">
                      {w.events.map((ev) => (
                        <span
                          key={ev}
                          className="rounded-full border border-lattice bg-paper px-2 py-0.5 font-sans text-[12px] text-graphite"
                        >
                          {ev}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-sans text-[12px]",
                        w.active
                          ? "border-lattice bg-paper text-ink"
                          : "border-lattice bg-paper-fold text-graphite",
                      )}
                    >
                      <span
                        className={cn(
                          "inline-block h-1.5 w-1.5 rounded-full",
                          w.active ? "bg-ink" : "bg-graphite-soft",
                        )}
                      />
                      {w.active ? "active" : "paused"}
                    </span>
                  </td>
                  <td className="px-5 py-3 font-sans text-[13px] text-graphite">
                    {formatDate(w.createdAt)}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <Link
                      href={`/app/settings/webhooks/${w.id}`}
                      className="font-sans text-[13px] text-ink hover:text-crane-deep transition-colors"
                    >
                      Open →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-5 py-3 font-sans text-[12px] text-graphite-soft">
      {children}
    </th>
  );
}

export default WebhookList;
