"use client";

import { useState } from "react";
import { Download, ExternalLink, Loader2, Receipt } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { EmptyState } from "@/components/empty/EmptyState";

/**
 * Paginated invoice history. Each row links to:
 *   - Stripe's hosted invoice page (`hostedInvoiceUrl`)
 *   - The invoice PDF (`invoicePdf`)
 *
 * Cursor pagination comes from `trpc.billing.invoices.useQuery({ limit,
 * cursor })` which proxies to apps/api and returns the raw Stripe shape
 * (Stripe's own cursor semantics: we don't re-invent them).
 */

const PAGE_SIZE = 10;

export interface BillingHistoryProps {
  /** Hide the heading: useful when embedding inside another card. */
  hideHeading?: boolean;
}

export function BillingHistory({ hideHeading = false }: BillingHistoryProps) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([]);

  const query = trpc.billing.invoices.useQuery({
    limit: PAGE_SIZE,
    cursor,
  });

  const items = query.data?.items ?? [];
  const nextCursor = query.data?.nextCursor ?? null;

  const hasPrev = cursorStack.length > 0;
  const hasNext = !!nextCursor;

  const onNext = () => {
    if (!nextCursor) return;
    setCursorStack((s) => [...s, cursor]);
    setCursor(nextCursor);
  };
  const onPrev = () => {
    setCursorStack((s) => {
      const copy = [...s];
      const prev = copy.pop() ?? null;
      setCursor(prev);
      return copy;
    });
  };

  return (
    <section>
      {!hideHeading && (
        <header className="mb-5">
          <h2 className="font-display text-[22px] text-ink tracking-[-0.01em]">
            Billing history
          </h2>
          <p className="mt-1 font-sans text-[14px] text-graphite">
            Past invoices with PDF downloads.
          </p>
        </header>
      )}

      {query.isLoading ? (
        <div className="flex items-center gap-2 font-sans text-[13px] text-graphite">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading invoices…
        </div>
      ) : query.isError ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4 font-sans text-[13px] text-red-700">
          Couldn&rsquo;t load invoices.{" "}
          <button
            type="button"
            onClick={() => query.refetch()}
            className="underline"
          >
            Retry
          </button>
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Receipt className="h-5 w-5" />}
          title="No invoices yet"
          description="Once your first billing cycle closes, invoices will land here for download."
        />
      ) : (
        <ul className="divide-y divide-lattice/60">
          {items.map((inv) => (
            <li
              key={inv.id}
              className="flex flex-wrap items-center justify-between gap-3 px-6 py-4"
            >
              <div>
                <p className="font-mono text-[13px] text-ink">
                  {inv.number ?? inv.id}
                </p>
                <p className="mt-0.5 font-sans text-[12px] text-graphite">
                  {new Date(inv.created).toLocaleDateString(undefined, {
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                  })}{" "}
                  · {formatMoney(inv.amountPaid, inv.currency)} · {inv.status}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {inv.hostedInvoiceUrl && (
                  <a
                    href={inv.hostedInvoiceUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-full border border-lattice px-3 py-1.5 font-sans text-[12px] text-ink hover:bg-paper-fold/60"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    View
                  </a>
                )}
                {inv.invoicePdf && (
                  <a
                    href={inv.invoicePdf}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-full bg-ink px-3 py-1.5 font-sans text-[12px] text-paper hover:bg-ink/90"
                  >
                    <Download className="h-3.5 w-3.5" />
                    PDF
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {(hasPrev || hasNext) && (
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            disabled={!hasPrev}
            onClick={onPrev}
            className="rounded-full border border-lattice px-4 py-1.5 font-sans text-[12px] text-ink disabled:opacity-50"
          >
            Prev
          </button>
          <button
            type="button"
            disabled={!hasNext}
            onClick={onNext}
            className="rounded-full border border-lattice px-4 py-1.5 font-sans text-[12px] text-ink disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </section>
  );
}

function formatMoney(amountMinor: number, currency: string): string {
  const majorUnit = amountMinor / 100;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency.toUpperCase(),
    }).format(majorUnit);
  } catch {
    return `${majorUnit.toFixed(2)} ${currency.toUpperCase()}`;
  }
}
