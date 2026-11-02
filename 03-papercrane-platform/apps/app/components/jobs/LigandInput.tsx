"use client";

import { useEffect, useId, useRef, useState } from "react";
import { FlaskConical, Loader2, Upload, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { trpc } from "@/lib/trpc/client";
import { uploadStructureFile } from "@/lib/pdb/upload";

/** Shape the wizard owns for a small-molecule ligand. */
export type LigandValue = {
  /** How the ligand is supplied. */
  mode: "none" | "ccd" | "file";
  /** RCSB Chemical Component Dictionary code (e.g. HEM, ZN, ATP). */
  ccd?: string;
  /** Staging key for an uploaded .sdf, if any. */
  sdfKey?: string;
  /** Original filename of the uploaded .sdf, for display. */
  filename?: string;
};

/**
 * If `required`: `ccd` mode needs a non-empty code, `file` mode needs an
 * `sdfKey`, and `none` fails. If not required: always valid (none allowed).
 */
export function isLigandValid(v: LigandValue, required: boolean): boolean {
  if (!required) return true;
  if (v.mode === "ccd") return !!v.ccd && v.ccd.trim().length > 0;
  if (v.mode === "file") return !!v.sdfKey;
  return false;
}

/** Serialise to the tool-param shape the backend expects. */
export function ligandToolParams(v: LigandValue): Record<string, unknown> {
  if (v.mode === "ccd" && v.ccd && v.ccd.trim().length > 0) {
    return { ligand: v.ccd.trim() };
  }
  if (v.mode === "file" && v.sdfKey) {
    return { ligand_sdf: v.sdfKey };
  }
  return {};
}

type Phase =
  | { phase: "idle" }
  | { phase: "uploading"; pct: number }
  | { phase: "error"; message: string };

type LigandInputProps = {
  value: LigandValue;
  required: boolean;
  onChange: (patch: Partial<LigandValue>) => void;
  error?: string;
};

/**
 * Small-molecule ligand input: required for LigandMPNN, optional for
 * RFdiffusionAA / BoltzGen. A segmented control switches between "None"
 * (hidden when required), a CCD code, or an uploaded .sdf file. Controlled -
 * only transient upload state is local.
 */
export function LigandInput({
  value,
  required,
  onChange,
  error,
}: LigandInputProps): JSX.Element {
  const ccdId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>({ phase: "idle" });

  const getUploadUrl = trpc.targets.getUploadUrl.useMutation();
  const uploading = phase.phase === "uploading";

  // When the ligand becomes required, nudge the mode away from "none".
  useEffect(() => {
    if (required && value.mode === "none") onChange({ mode: "ccd" });
  }, [required, value.mode, onChange]);

  const handleFile = async (file: File) => {
    setPhase({ phase: "uploading", pct: 0 });
    try {
      const { uploadKey } = await uploadStructureFile({
        file,
        getSignedUrl: async ({ filename, contentLength }) => {
          const out = await getUploadUrl.mutateAsync({ filename, contentLength });
          return { url: out.url, uploadKey: out.uploadKey };
        },
        onProgress: (pct) => setPhase({ phase: "uploading", pct }),
      });
      setPhase({ phase: "idle" });
      onChange({ sdfKey: uploadKey, filename: file.name });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      setPhase({ phase: "error", message });
    }
  };

  const clearFile = () => {
    setPhase({ phase: "idle" });
    onChange({ sdfKey: undefined, filename: undefined });
    if (fileRef.current) fileRef.current.value = "";
  };

  const modes: Array<{ id: LigandValue["mode"]; label: string }> = [
    ...(required ? [] : [{ id: "none" as const, label: "None" }]),
    { id: "ccd", label: "CCD code" },
    { id: "file", label: "Upload .sdf" },
  ];

  return (
    <fieldset
      className="flex flex-col gap-3 p-4"
      data-testid="e2e-ligand-input"
    >
      <legend className="px-1 font-sans text-[12px] text-graphite-soft">
        Ligand
      </legend>
      <div className="flex items-start gap-2.5">
        <FlaskConical
          className="mt-0.5 h-4 w-4 shrink-0 text-graphite-soft"
          aria-hidden="true"
        />
        <p className="font-sans text-[13px] text-graphite">
          A small-molecule ligand to design around.
          {required && (
            <span className="ml-1 text-graphite-soft">
              (required for this tool)
            </span>
          )}
        </p>
      </div>

      <div className="inline-flex bg-paper p-1">
        {modes.map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => onChange({ mode: m.id })}
            aria-pressed={value.mode === m.id}
            className={cn(
              "rounded-lg px-3 py-1.5 font-sans text-[12px] transition-colors",
              value.mode === m.id
                ? "bg-ink text-paper"
                : "text-graphite hover:text-ink",
            )}
          >
            {m.label}
          </button>
        ))}
      </div>

      {value.mode === "ccd" && (
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor={ccdId}
            className="font-sans text-[12px] text-graphite-soft"
          >
            CCD code
          </label>
          <input
            id={ccdId}
            type="text"
            maxLength={3}
            autoComplete="off"
            spellCheck={false}
            placeholder="e.g. HEM, ZN, ATP"
            value={value.ccd ?? ""}
            onChange={(e) =>
              onChange({ ccd: e.target.value.trim().toUpperCase() })
            }
            className={cn(
              "rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:normal-case placeholder:tracking-normal placeholder:text-graphite-soft",
              "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
            )}
          />
        </div>
      )}

      {value.mode === "file" &&
        (value.sdfKey ? (
          <div className="flex items-center justify-between gap-3 bg-paper px-4 py-3">
            <span className="truncate font-mono text-[13px] text-ink">
              {value.filename || "uploaded ligand"}
            </span>
            <button
              type="button"
              onClick={clearFile}
              className="inline-flex items-center gap-1 font-sans text-[12px] text-graphite hover:text-ink"
            >
              <X className="h-3.5 w-3.5" />
              Clear
            </button>
          </div>
        ) : (
          <div>
            <input
              ref={fileRef}
              type="file"
              accept=".sdf"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleFile(file);
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="inline-flex items-center gap-2 rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[13px] text-ink hover:border-ink disabled:opacity-50"
            >
              {uploading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Uploading… {phase.phase === "uploading" ? `${phase.pct}%` : ""}
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" />
                  Upload .sdf
                </>
              )}
            </button>
          </div>
        ))}

      {phase.phase === "error" && (
        <p role="alert" className="font-sans text-[12px] text-crane-deep">
          {phase.message}
        </p>
      )}
      {error && (
        <p role="alert" className="font-sans text-[12px] text-crane-deep">
          {error}
        </p>
      )}
    </fieldset>
  );
}
