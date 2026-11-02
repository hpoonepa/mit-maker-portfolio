"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowLeft, KeyRound, Trash2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { DeliveryLog } from "./DeliveryLog";
import { TestWebhookButton } from "./TestWebhookButton";

export interface WebhookDetailProps {
  webhookId: string;
}

/**
 * Webhook detail view. Shows:
 *   - URL, events, status
 *   - actions: delete (test-fire and secret rotation arrive after the beta)
 *   - delivery log placeholder below
 *
 * There is no `webhooks.get` procedure, so the record is derived from
 * `webhooks.list`: which is already cached by the list page.
 */
export function WebhookDetail({ webhookId }: WebhookDetailProps) {
  const router = useRouter();
  const utils = trpc.useUtils();

  const query = trpc.webhooks.list.useQuery();

  const record = useMemo(
    () => query.data?.items.find((w) => w.id === webhookId) ?? null,
    [query.data, webhookId],
  );

  const del = trpc.webhooks.delete.useMutation({
    onSuccess: () => {
      void utils.webhooks.list.invalidate();
      router.push("/app/settings/webhooks");
    },
    onError: (err) =>
      setToast({ kind: "err", message: err.message ?? "Delete failed" }),
  });

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [toast, setToast] = useState<{
    kind: "ok" | "err";
    message: string;
  } | null>(null);

  return (
    <div className="space-y-10">
      <div>
        <Link
          href="/app/settings/webhooks"
          className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          All webhooks
        </Link>
      </div>

      {/* Live region for toast messages */}
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

      {query.isLoading ? (
        <div className="px-6 py-10 text-center font-sans text-[14px] text-graphite">
          Loading…
        </div>
      ) : !record ? (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-6 py-10 text-center font-sans text-[14px] text-crane-deep"
        >
          Webhook not found.
        </div>
      ) : (
        <>
          <header className="space-y-3">
            <p className="font-mono text-[11px] text-graphite-soft">
              {record.id}
            </p>
            <h1 className="font-display text-display-md text-ink break-all">
              {record.url}
            </h1>
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-sans text-[12px]",
                  record.active
                    ? "border-lattice bg-paper text-ink"
                    : "border-lattice bg-paper-fold text-graphite",
                )}
              >
                <span
                  className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    record.active ? "bg-ink" : "bg-graphite-soft",
                  )}
                />
                {record.active ? "active" : "paused"}
              </span>
              {record.events.map((ev) => (
                <span
                  key={ev}
                  className="rounded-full border border-lattice bg-paper px-2 py-0.5 font-sans text-[12px] text-graphite"
                >
                  {ev}
                </span>
              ))}
            </div>
          </header>

          <section className="p-6">
            <h2 className="font-display text-[18px] text-ink">Actions</h2>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <TestWebhookButton
                webhookId={record.id}
                disabled={!record.active}
                onResult={(r) => setToast(r)}
              />
              <span className="inline-flex items-center gap-2">
                <button
                  type="button"
                  disabled
                  aria-disabled="true"
                  title="Secret rotation arrives after the beta"
                  className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-full border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite opacity-60"
                >
                  <KeyRound className="h-3 w-3" aria-hidden="true" />
                  Rotate secret
                </button>
                <span className="font-sans text-[12px] text-graphite-soft">
                  After beta
                </span>
              </span>
              <button
                type="button"
                onClick={() => setConfirmDelete(true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-crane-deep hover:border-crane transition-colors"
              >
                <Trash2 className="h-3 w-3" />
                Delete webhook
              </button>
            </div>
            <p className="mt-3 font-sans text-[12px] text-graphite-soft">
              Test deliveries and secret rotation aren&apos;t available in the
              beta. Your signing secret was shown once when this webhook was
              created; to change it, delete this webhook and create a new one.
            </p>
          </section>

          <DeliveryLog webhookId={record.id} />

          {confirmDelete && (
            <ConfirmDeleteModal
              onCancel={() => setConfirmDelete(false)}
              onConfirm={() => {
                setConfirmDelete(false);
                del.mutate({ id: record.id });
              }}
              url={record.url}
              pending={del.isPending}
            />
          )}

        </>
      )}
    </div>
  );
}

function ConfirmDeleteModal({
  onCancel,
  onConfirm,
  url,
  pending,
}: {
  onCancel: () => void;
  onConfirm: () => void;
  url: string;
  pending: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="webhook-delete-title"
    >
      <div className="relative w-full max-w-md bg-paper p-6">
        <h3
          id="webhook-delete-title"
          className="font-display text-[20px] text-ink"
        >
          Delete webhook?
        </h3>
        <p className="mt-2 font-sans text-[13px] text-graphite break-all">
          Future events will stop being delivered to{" "}
          <code className="font-mono text-[12px]">{url}</code>. This cannot be
          undone.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="btn-primary disabled:opacity-60"
          >
            <Trash2 className="h-4 w-4" />
            {pending ? "Deleting…" : "Delete webhook"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default WebhookDetail;
