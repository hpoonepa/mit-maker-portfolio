"use client";

import { useCallback, useRef, useState } from "react";
import { UploadCloud, FileCheck2, AlertCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  formatBytes,
  hasValidExtension,
  limitForTier,
  validateStructureFile,
  type UploadTier,
  type ValidationOk,
} from "@/lib/pdb/validate";

export type UploadDropzoneProps = {
  tier?: UploadTier;
  /** Called once validation passes and the user is ready to pick a name. */
  onValidated: (payload: ValidatedPayload) => void;
  /** When true the dropzone goes into a "busy" state (upload in flight). */
  busy?: boolean;
};

export type ValidatedPayload = {
  filename: string;
  text: string;
  sizeBytes: number;
  validation: ValidationOk;
};

/**
 * Drag-and-drop + click-to-select file picker for structure uploads. Reads
 * the file as text (we parse client-side first), runs validation, and hands
 * the caller a ready-to-upload payload.
 *
 * We deliberately keep the *network* side of the upload flow in the page
 * component: this dropzone is just the "pick + validate" step so it stays
 * easy to test and reuse.
 */
export function UploadDropzone({
  tier = "free",
  onValidated,
  busy = false,
}: UploadDropzoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const limit = limitForTier(tier);

  const processFile = useCallback(
    async (file: File) => {
      setError(null);

      if (!hasValidExtension(file.name)) {
        setError("Unsupported file type: expected .pdb, .ent, .cif, or .mmcif");
        return;
      }
      if (file.size > limit) {
        setError(
          `File is ${formatBytes(file.size)}: max ${formatBytes(limit)} on ${tier} tier`,
        );
        return;
      }

      setReading(true);
      try {
        const text = await file.text();
        const result = validateStructureFile(text, file.size, tier, file.name);
        if (!result.ok) {
          setError(result.error.message);
          return;
        }
        onValidated({
          filename: file.name,
          text,
          sizeBytes: file.size,
          validation: result,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to read file");
      } finally {
        setReading(false);
      }
    },
    [limit, onValidated, tier],
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
      // Reset so picking the same file twice re-triggers onChange.
      e.target.value = "";
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
            ? "border-ink bg-paper-fold/60"
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
            . Up to {formatBytes(limit)} on the {tier} tier.
          </p>
        </div>

        <div className="flex items-center gap-2 font-mono text-[11px] text-graphite-soft">
          <FileCheck2 className="w-3.5 h-3.5" />
          .pdb · .ent · .cif · .mmcif
        </div>
      </label>

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
