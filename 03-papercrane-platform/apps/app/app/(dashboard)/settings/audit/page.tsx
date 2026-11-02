import { Suspense } from "react";
import { createServerTrpc } from "@/lib/trpc/server";
import { AuditTable, type AuditRow } from "@/components/audit/AuditTable";
import { AuditFilterBarContainer } from "./filter-bar-client";
import { AuditExportButton } from "@/components/audit/AuditExportButton";

export const dynamic = "force-dynamic";
export const revalidate = 0;

/**
 * Audit log: org admin view.
 *
 * Server-renders the first page of audit entries. Filters and pagination
 * are client-driven (tRPC React Query) because they don't need to be
 * bookmarkable right now; the URL stays clean and the initial paint is
 * already populated.
 */
export default async function AuditLogPage() {
  const trpc = await createServerTrpc();

  let initialRows: AuditRow[] = [];
  let initialCursor: string | null = null;
  let fetchError: string | null = null;

  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const res = (await (trpc as any).audit.list.query({
      limit: 50,
      filters: {},
    })) as { items: AuditRow[]; nextCursor: string | null };
    initialRows = res.items ?? [];
    initialCursor = res.nextCursor ?? null;
  } catch (e) {
    fetchError = e instanceof Error ? e.message : "Failed to load audit log.";
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4 flex-wrap border-b border-graphite-soft/15 pb-5">
        <div>
          <p className="font-sans text-[12px] text-graphite-soft">
            Security
          </p>
          <h1 className=".5 font-sans text-[22px] font-medium tracking-tight text-ink">
            Audit log
          </h1>
          <p className="mt-1.5 max-w-2xl font-sans text-[13.5px] leading-relaxed text-graphite">
            Every privileged action on this organisation: API keys, webhooks,
            members, plan changes, cancellations. Retained 365 days on Pro,
            90 days on Free. Append-only.
          </p>
        </div>
      </header>

      {fetchError && (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
        >
          {fetchError}
        </div>
      )}

      <Suspense fallback={null}>
        <AuditFilterBarContainer>
          {(filters) => (
            <>
              <div className="flex justify-end">
                <AuditExportButton filters={filters} />
              </div>
              <AuditTable
                initialRows={initialRows}
                initialNextCursor={initialCursor}
                filters={filters}
              />
            </>
          )}
        </AuditFilterBarContainer>
      </Suspense>
    </div>
  );
}
