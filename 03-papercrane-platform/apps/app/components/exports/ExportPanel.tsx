"use client";

/** Export all pages into independently usable files with a completeness manifest. */

import { useMemo, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { buildResearchArchive, collectArchiveDesigns } from "@/lib/export/archive";

const FORMATS = ["fasta", "cif", "json", "csv"] as const;
type Format = (typeof FORMATS)[number];

interface DesignLite {
  id: string;
  seed: number;
}

export interface ExportPanelProps {
  mode: "project" | "job";
  /** Either a projectId or a jobId depending on mode. */
  targetId: string;
  /** Display name for the bundle filename. */
  label?: string;
  onDone?: (count: number) => void;
}

const FORMAT_LABEL: Record<Format, string> = {
  fasta: "FASTA",
  cif: "CIF (mmCIF)",
  json: "JSON",
  csv: "CSV",
};

export function ExportPanel({ mode, targetId, label, onDone }: ExportPanelProps) {
  const [picked, setPicked] = useState<Set<Format>>(new Set(["fasta", "csv"]));
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [result, setResult] = useState<{ message: string; incomplete: boolean } | null>(null);
  const utils = trpc.useUtils();

  // Pull designs via existing tRPC procs: both already exist.
  const projectQuery = trpc.designs.listByProject.useQuery(
    { projectId: targetId, limit: 500 },
    { enabled: mode === "project" && !!targetId },
  );
  const jobQuery = trpc.designs.listByJob.useQuery(
    { jobId: targetId, limit: 500 },
    { enabled: mode === "job" && !!targetId },
  );

  const designs = useMemo<DesignLite[]>(() => {
    const items =
      mode === "project"
        ? projectQuery.data?.items
        : jobQuery.data?.items;
    return (items ?? []).map((d) => ({ id: d.id, seed: d.seed }));
  }, [mode, projectQuery.data, jobQuery.data]);

  const isLoading = mode === "project" ? projectQuery.isLoading : jobQuery.isLoading;
  const isError = mode === "project" ? projectQuery.isError : jobQuery.isError;

  function toggle(fmt: Format) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(fmt)) next.delete(fmt);
      else next.add(fmt);
      return next;
    });
  }

  async function downloadBundle() {
    if (designs.length === 0 || picked.size === 0 || busy) return;
    setBusy(true);
    setResult(null);
    setProgress("Collecting all designs…");
    try {
      const formats = Array.from(picked);
      const snapshotAt = new Date().toISOString();
      const allDesigns = await collectArchiveDesigns((cursor) =>
        utils.client.designs.exportPage.query({ scope: mode, id: targetId, snapshotAt, cursor, limit: 500 }),
      );
      if (!allDesigns.length) throw new Error("No designs remain available for export. Refresh and try again.");
      const archive = await buildResearchArchive({
        designs: allDesigns, formats, scope: mode, scopeId: targetId, snapshotAt,
        onProgress: (done, total) => setProgress(`Fetching files ${done}/${total}…`),
      });
      const blob = new Blob([new Uint8Array(archive.bytes).buffer], { type: "application/zip" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const safeLabel = (label ?? mode).replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 80);
      a.download = `${safeLabel}-${targetId.slice(0, 8)}${archive.manifest.complete ? "" : "-INCOMPLETE"}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      const { exportedFiles, requestedFiles, failedFiles, completeDesigns, complete } = archive.manifest;
      setResult({ incomplete: !complete, message: complete
        ? `Archive ready: ${completeDesigns} designs, ${exportedFiles} files.`
        : `Incomplete archive: ${exportedFiles}/${requestedFiles} files exported; ${failedFiles} failed. See manifest.json for missing files and retry the export.` });
      if (complete) onDone?.(completeDesigns);
    } catch (error) {
      setResult({ incomplete: true, message: error instanceof Error ? error.message : "Export failed. Please retry." });
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  if (!targetId) {
    return (
      <p className="font-sans text-[13px] text-graphite-soft">
        Select a {mode} to begin.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="font-sans text-[13px] text-graphite">
        {isLoading
          ? "Resolving designs…"
          : isError
            ? "Failed to load designs."
            : `${designs.length === 500 ? "At least " : ""}${designs.length} design${designs.length === 1 ? "" : "s"} available. All pages will be included.`}
      </div>

      <fieldset disabled={busy} className="flex flex-wrap gap-3">
        <legend className="sr-only">Export formats</legend>
        {FORMATS.map((fmt) => (
          <label
            key={fmt}
            className="inline-flex items-center gap-2 rounded-full border border-lattice-strong bg-paper px-3 py-1.5 font-sans text-[13px] text-ink hover:border-crane/50 cursor-pointer"
          >
            <input
              type="checkbox"
              checked={picked.has(fmt)}
              onChange={() => toggle(fmt)}
              className="accent-crane"
            />
            {FORMAT_LABEL[fmt]}
          </label>
        ))}
      </fieldset>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={downloadBundle}
          disabled={busy || isLoading || isError || designs.length === 0 || picked.size === 0}
          className="inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2 font-sans text-[13px] text-paper hover:bg-ink/85 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {busy ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Download className="w-3.5 h-3.5" />
          )}
          Download bundle
        </button>
        {progress && (
          <span role="status" className="font-sans text-[12px] text-graphite-soft">{progress}</span>
        )}
      </div>

      <p className="font-sans text-[12px] text-graphite-soft">
        ZIP archive with separate files and a manifest recording origin, checksums,
        and any missing downloads. Designs created after the export starts are excluded.
        Browser archives are limited to 128 MB; export individual jobs for larger projects.
      </p>
      {result && <p role={result.incomplete ? "alert" : "status"} className="font-sans text-[13px] text-graphite">{result.message}</p>}
    </div>
  );
}
