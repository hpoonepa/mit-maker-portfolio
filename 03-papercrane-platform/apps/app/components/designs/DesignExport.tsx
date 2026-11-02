"use client";

/**
 * DesignExport: the small "Export ▾" dropdown that lives on a design's
 * detail page (and inside the BatchSelectBar).
 *
 * Two modes:
 *   1. single : exports one design via /api/designs/[id]/export/[format]
 *   2. batch  : exports many designs client-side, building FASTA/CSV/JSON
 *                in memory and streaming a real zip if jszip is available.
 *
 * The component is intentionally dumb about data shape: callers pass an
 * already-resolved Design[] so we don't have to talk to trpc here.
 */

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatFasta } from "@/lib/export/fasta";
import { formatCsv } from "@/lib/export/csv";
import {
  bundleAndDownload,
  downloadText,
  isZipAvailable,
  type ZipFile,
} from "@/lib/export/zip";

export interface ExportableDesign {
  id: string;
  seed: number;
  sequence?: string | null;
  length?: number | null;
  tool?: string | null;
  metrics?: Record<string, number | undefined>;
  /** Optional presigned URL to the predicted CIF/PDB. */
  structureUrl?: string;
}

export type ExportFormat = "cif" | "fasta" | "json" | "csv" | "zip";

export interface DesignExportProps {
  designs: ExportableDesign[];
  /** Filename prefix for batch exports (e.g. "designs-projectname"). */
  archiveName?: string;
  /** Disable the dropdown (e.g. while a previous export is running). */
  disabled?: boolean;
  /** Optional callback for surfacing progress in toasts. */
  onProgress?: (msg: string) => void;
  /** Visual variant: "ghost" matches sticky bars, "solid" for detail pages. */
  variant?: "ghost" | "solid";
}

interface MenuItem {
  format: ExportFormat;
  label: string;
  hint?: string;
  disabled?: boolean;
}

export function DesignExport({
  designs,
  archiveName = "designs",
  disabled = false,
  onProgress,
  variant = "ghost",
}: DesignExportProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [zipOk, setZipOk] = useState<boolean | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Probe jszip once: same answer for the whole session.
  useEffect(() => {
    let cancelled = false;
    isZipAvailable().then((ok) => {
      if (!cancelled) setZipOk(ok);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Click-outside to close.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const isBatch = designs.length > 1;
  const single = designs[0];

  const items: MenuItem[] = [];
  if (!isBatch && single) {
    items.push({
      format: "cif",
      label: "CIF (structure)",
      hint: "single file",
      disabled: !single.structureUrl,
    });
    items.push({ format: "fasta", label: "FASTA (sequence)" });
    items.push({ format: "json", label: "JSON (full design)" });
    items.push({ format: "csv", label: "CSV (metrics)" });
  } else {
    items.push({
      format: "zip",
      label: zipOk === false ? "CIFs (individual)" : "CIFs (zip)",
      hint:
        zipOk === false
          ? "jszip not installed: files download separately"
          : `${designs.length} files`,
      disabled: !designs.some((d) => d.structureUrl),
    });
    items.push({
      format: "fasta",
      label: "FASTA (combined)",
      hint: `${designs.length} sequences`,
    });
    items.push({
      format: "csv",
      label: "CSV (metrics)",
      hint: `${designs.length} rows`,
    });
    items.push({
      format: "json",
      label: "JSON (full)",
      hint: `${designs.length} designs`,
    });
  }

  const handleSelect = async (fmt: ExportFormat) => {
    setOpen(false);
    if (disabled || busy) return;
    setBusy(true);
    try {
      if (!isBatch && single) {
        await runSingle(single, fmt);
      } else {
        await runBatch(designs, fmt, archiveName, onProgress);
      }
    } catch (err) {
      console.error("[DesignExport] failed", err);
      onProgress?.(
        `Export failed: ${err instanceof Error ? err.message : "unknown error"}`,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={wrapRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled || busy || designs.length === 0}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5",
          "font-sans text-[12px] transition-colors",
          variant === "solid"
            ? "border border-ink bg-ink text-paper hover:bg-ink/90 disabled:opacity-50"
            : "border border-lattice bg-paper text-graphite hover:border-lattice-strong hover:text-ink disabled:opacity-50",
        )}
      >
        <Download className="h-3 w-3" />
        {busy ? "Exporting…" : "Export"}
        <ChevronDown className="h-3 w-3" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-60 overflow-hidden rounded-xl border border-lattice-strong bg-paper"
        >
          {items.map((it) => (
            <button
              key={it.format}
              type="button"
              role="menuitem"
              onClick={() => handleSelect(it.format)}
              disabled={it.disabled}
              className={cn(
                "flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left",
                "font-sans text-[12px] text-ink transition-colors",
                "hover:bg-paper-fold disabled:cursor-not-allowed disabled:opacity-40",
              )}
            >
              <span>{it.label}</span>
              {it.hint && (
                <span className="font-sans text-[12px] text-graphite-soft">
                  {it.hint}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* -------------------------- export runners -------------------------- */

async function runSingle(d: ExportableDesign, fmt: ExportFormat) {
  if (fmt === "cif") {
    if (!d.structureUrl) throw new Error("no structure available");
    const a = document.createElement("a");
    a.href = d.structureUrl;
    a.download = `design_${d.seed}_${d.id.slice(0, 8)}.cif`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    return;
  }
  // For fasta/json/csv we hit the server route: it has the auth context
  // and can pull the row via RLS without us re-implementing it client-side.
  const url = `/api/designs/${d.id}/export/${fmt}`;
  window.location.assign(url);
}

async function runBatch(
  designs: ExportableDesign[],
  fmt: ExportFormat,
  archiveName: string,
  onProgress?: (msg: string) => void,
) {
  const stamp = new Date().toISOString().slice(0, 10);
  const base = `${archiveName}-${stamp}`;

  if (fmt === "fasta") {
    onProgress?.(`Building FASTA (${designs.length} seqs)…`);
    const text = formatFasta(
      designs.map((d) => ({
        id: d.id,
        seed: d.seed,
        sequence: d.sequence ?? "",
        metrics: d.metrics,
      })),
    );
    downloadText(text, `${base}.fasta`, "text/plain;charset=utf-8");
    onProgress?.(`Downloaded ${base}.fasta`);
    return;
  }

  if (fmt === "csv") {
    onProgress?.(`Building CSV…`);
    const text = formatCsv(designs);
    downloadText(text, `${base}.csv`, "text/csv;charset=utf-8");
    onProgress?.(`Downloaded ${base}.csv`);
    return;
  }

  if (fmt === "json") {
    onProgress?.(`Building JSON…`);
    downloadText(
      JSON.stringify(designs, null, 2),
      `${base}.json`,
      "application/json;charset=utf-8",
    );
    onProgress?.(`Downloaded ${base}.json`);
    return;
  }

  if (fmt === "zip") {
    const files: ZipFile[] = designs
      .filter((d) => !!d.structureUrl)
      .map((d) => ({
        name: `design_${d.seed}_${d.id.slice(0, 8)}.cif`,
        url: d.structureUrl as string,
      }));
    if (files.length === 0) {
      onProgress?.("No structures available to bundle.");
      return;
    }
    onProgress?.(`Bundling ${files.length} CIFs…`);
    const result = await bundleAndDownload(files, `${base}.zip`, (done, total, name) => {
      onProgress?.(`(${done}/${total}) ${name}`);
    });
    if (result.mode === "fallback") {
      onProgress?.(
        `Downloaded ${result.count} files (jszip not installed: single-file mode)`,
      );
    } else {
      onProgress?.(`Downloaded ${base}.zip (${result.count} files)`);
    }
    if (result.errors.length > 0) {
      console.warn("[DesignExport] some files failed", result.errors);
    }
    return;
  }

  throw new Error(`unknown batch format: ${fmt}`);
}
