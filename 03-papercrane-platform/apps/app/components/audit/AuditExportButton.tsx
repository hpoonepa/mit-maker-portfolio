"use client";

import { useState } from "react";
import { Download, FileJson, FileSpreadsheet, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import type { AuditFilters } from "./AuditTable";

interface AuditExportButtonProps {
  filters: AuditFilters;
}

/**
 * CSV / JSONL export. Calls `audit.export`; the server streams rows into R2
 * and returns a presigned GET URL, which we open in a new tab to trigger
 * the browser download.
 */
export function AuditExportButton({ filters }: AuditExportButtonProps) {
  const [menu, setMenu] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // TODO(@papercrane/trpc): `audit.export` procedure declared alongside
  // `audit.list` in packages/trpc/src/routers/audit.ts.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anyTrpc = trpc as any;
  const mutation = anyTrpc.audit.export.useMutation();

  const run = async (format: "csv" | "jsonl") => {
    setError(null);
    setMenu(false);
    try {
      const res = (await mutation.mutateAsync({ format, filters })) as {
        url: string;
        format: "csv" | "jsonl";
        estimatedRows: number;
      };
      if (res?.url) {
        // Pop the download in a new tab. R2 sets Content-Disposition so
        // the browser saves it rather than navigating into the blob.
        window.open(res.url, "_blank", "noopener,noreferrer");
      } else {
        setError("Export succeeded but no URL was returned.");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Export failed.";
      setError(msg);
    }
  };

  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={() => setMenu((x) => !x)}
        disabled={mutation.isPending}
        className={cn(
          "inline-flex items-center gap-2 rounded-xl border border-lattice-strong bg-paper px-3 py-2",
          "font-sans text-[13px] text-ink hover:bg-paper-fold disabled:opacity-60",
        )}
        aria-haspopup="menu"
        aria-expanded={menu}
      >
        {mutation.isPending ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Download className="w-4 h-4" />
        )}
        Export
      </button>

      {menu && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1 w-[180px] rounded-xl border border-lattice-strong bg-paper p-1 shadow-lg z-30"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => run("csv")}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left font-sans text-[13px] text-ink hover:bg-paper-fold"
          >
            <FileSpreadsheet className="w-4 h-4 text-graphite" />
            CSV
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => run("jsonl")}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left font-sans text-[13px] text-ink hover:bg-paper-fold"
          >
            <FileJson className="w-4 h-4 text-graphite" />
            JSONL
          </button>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="absolute right-0 top-full mt-12 w-[260px] rounded-xl border border-crane/40 bg-crane-glow px-3 py-2 font-sans text-[12px] text-crane-deep"
        >
          {error}
        </div>
      )}
    </div>
  );
}

export default AuditExportButton;
