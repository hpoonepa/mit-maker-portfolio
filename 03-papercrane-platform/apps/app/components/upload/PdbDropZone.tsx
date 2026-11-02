"use client";

import { useCallback, useRef, useState } from "react";
import { UploadCloud, FileCheck2, AlertCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  formatBytes,
  hasValidExtension,
  validateStructureFile,
} from "@/lib/pdb/validate";
import type { ValidationOk } from "@/lib/pdb/validate";

/**
 * Per-spec the wizard caps uploads at 10 MB. We deliberately do not reuse
 * the larger `limitForTier` cap: those are for paid storage, this dropzone
 * is the lightweight in-app uploader.
 */
const DROPZONE_MAX_BYTES = 10 * 1024 * 1024;

export interface PdbDropZonePayload {
  file: File;
  text: string;
  validation: ValidationOk;
}

export interface PdbDropZoneProps {
  /** Called once a dropped file passes both extension + content sniffing. */
  onAccepted: (payload: PdbDropZonePayload) => void;
  /** Caps file size: defaults to 10 MB. */
  maxBytes?: number;
  /** Disables interactions while an upload is in flight. */
  busy?: boolean;
}

/**
 * Drag-and-drop zone for PDB / mmCIF files. Performs cheap client-side
 * checks (extension, size, "has at least one ATOM record"). The deep parse
 * lives behind `validateStructureFile` which we call here so the parent gets
 * a ready-to-use payload: chains, residues, sequence: without a second
 * read of the file.
 *
 * The crane-glow border on drag-over is the "primary" affordance of the
 * Paper Crane app. Don't soften it.
 */
export function PdbDropZone({
  onAccepted,
  maxBytes = DROPZONE_MAX_BYTES,
  busy = false,
}: PdbDropZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const processFile = useCallback(
    async (file: File) => {
      setError(null);

      if (!hasValidExtension(file.name)) {
        setError(
          "Unsupported file type: expected .pdb, .ent, .cif, or .mmcif",
        );
        return;
      }
      if (file.size === 0) {
        setError("File is empty");
        return;
      }
      if (file.size > maxBytes) {
        setError(
          `File is ${formatBytes(file.size)}: max ${formatBytes(maxBytes)}`,
        );
        return;
      }

      setReading(true);
      try {
        const text = await file.text();

        // Cheap pre-check: scan the first ~1000 lines for an ATOM record.
        // Avoids paying for a full parse when the file is obviously wrong.
        const head = text.split(/\r?\n/, 1000).join("\n");
        if (!/^ATOM\s/m.test(head) && !/_atom_site\./m.test(head)) {
          setError("No ATOM records found in the first 1000 lines");
          return;
        }

        const result = validateStructureFile(text, file.size, "free", file.name);
        if (!result.ok) {
          setError(result.error.message);
          return;
        }
        onAccepted({ file, text, validation: result });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to read file");
      } finally {
        setReading(false);
      }
    },
    [maxBytes, onAccepted],
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLLabelElement>) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files?.[0];
      if (file) void processFile(file);
    },
    [processFile],
  );

  const onInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) void processFile(file);
      e.target.value = ""; // re-pick same file
    },
    [processFile],
  );

  const disabled = busy || reading;

  return (
    <div className="flex flex-col gap-3">
      <label
        onDragEnter={() => setDragActive(true)}
        onDragLeave={() => setDragActive(false)}
        onDragOver={(e) => {
          e.preventDefault();
          if (!dragActive) setDragActive(true);
        }}
        onDrop={onDrop}
        className={cn(
          "group relative flex flex-col items-center justify-center gap-4 rounded-lg border-2 border-dashed px-8 py-14 text-center transition-colors cursor-pointer",
          dragActive
            ? "border-crane bg-crane-glow/40 ring-2 ring-crane-glow"
            : "border-lattice-strong bg-paper-fold/30 hover:border-ink hover:bg-paper-fold/50",
          disabled && "pointer-events-none opacity-70",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          className="sr-only"
          accept=".pdb,.ent,.cif,.mmcif,chemical/x-pdb"
          onChange={onInputChange}
          disabled={disabled}
        />

        <div className="inline-flex h-12 w-12 items-center justify-center bg-paper">
          {reading ? (
            <Loader2 className="w-5 h-5 text-ink animate-spin" />
          ) : (
            <UploadCloud className="w-5 h-5 text-ink" />
          )}
        </div>

        <div className="space-y-1">
          <p className="font-display text-[22px] text-ink tracking-[-0.01em]">
            {reading ? "Reading file…" : "Drop a PDB or mmCIF file"}
          </p>
          <p className="font-sans text-[14px] text-graphite">
            or{" "}
            <span className="underline underline-offset-4 group-hover:text-ink">
              click to choose
            </span>
            . Up to {formatBytes(maxBytes)}.
          </p>
        </div>

        <div className="flex items-center gap-2 font-mono text-[11px] text-graphite-soft">
          <FileCheck2 className="w-3.5 h-3.5" />
          .pdb · .ent · .cif · .mmcif
        </div>
      </label>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
        >
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="font-sans text-[12px] r text-crane-deep/70">
              Validation rejected
            </p>
            <p>{error}</p>
          </div>
          <button
            type="button"
            onClick={() => {
              setError(null);
              inputRef.current?.click();
            }}
            className="shrink-0 font-sans text-[12px] underline underline-offset-4 hover:text-ink"
          >
            Try another file
          </button>
        </div>
      )}
    </div>
  );
}
