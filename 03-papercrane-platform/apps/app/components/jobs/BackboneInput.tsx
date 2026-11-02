"use client";

import { useId, useRef, useState } from "react";
import { Boxes, Loader2, Upload, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { trpc } from "@/lib/trpc/client";
import { uploadStructureFile } from "@/lib/pdb/upload";
import { isValidPdbId } from "@/components/jobs/ComplexInputStep";

/** Shape the wizard owns for a backbone-to-redesign job. */
export type BackboneValue = {
  /** RCSB id typed by the user (or the uploaded file's name once uploaded). */
  pdb: string;
  /** Optional single-letter chain to redesign. */
  chain: string;
  /** Staging key returned by the upload pipeline, if a file was uploaded. */
  uploadKey?: string;
};

/** Valid if a file was uploaded, or `pdb` is a well-formed 4-char RCSB id. */
export function isBackboneValid(v: BackboneValue): boolean {
  return !!v.uploadKey || isValidPdbId(v.pdb);
}

/** What to send as `DesignRequest.targetPdb`: the upload key wins, else the id. */
export function backboneRequestValue(v: BackboneValue): string {
  return v.uploadKey ?? v.pdb.trim();
}

type Phase =
  | { phase: "idle" }
  | { phase: "uploading"; pct: number }
  | { phase: "error"; message: string };

type BackboneInputProps = {
  value: BackboneValue;
  onChange: (patch: Partial<BackboneValue>) => void;
  error?: string;
};

/**
 * Collects the backbone structure whose sequence a redesign model
 * (ProteinMPNN / SolubleMPNN / LigandMPNN) should design. Two supply paths:
 * type a 4-char RCSB PDB id, or upload a .pdb/.cif file. Controlled: it lifts
 * every edit up through `onChange` and keeps only transient upload state local.
 */
export function BackboneInput({
  value,
  onChange,
  error,
}: BackboneInputProps): JSX.Element {
  const pdbId = useId();
  const chainId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>({ phase: "idle" });

  const getUploadUrl = trpc.targets.getUploadUrl.useMutation();
  const uploading = phase.phase === "uploading";
  const invalidId =
    !value.uploadKey && value.pdb.trim().length > 0 && !isValidPdbId(value.pdb);

  const handleFile = async (file: File) => {
    setPhase({ phase: "uploading", pct: 0 });
    try {
      const { uploadKey } = await uploadStructureFile({
        file,
        getSignedUrl: async ({ filename, contentLength }) => {
          const out = await getUploadUrl.mutateAsync({
            filename,
            contentLength,
          });
          return { url: out.url, uploadKey: out.uploadKey };
        },
        onProgress: (pct) => setPhase({ phase: "uploading", pct }),
      });
      setPhase({ phase: "idle" });
      onChange({ uploadKey, pdb: file.name });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      setPhase({ phase: "error", message });
    }
  };

  const clearUpload = () => {
    setPhase({ phase: "idle" });
    onChange({ uploadKey: undefined, pdb: "" });
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <fieldset
      className="flex flex-col gap-3 p-4"
      data-testid="e2e-backbone-input"
    >
      <legend className="px-1 font-sans text-[12px] text-graphite-soft">
        Backbone
      </legend>
      <div className="flex items-start gap-2.5">
        <Boxes
          className="mt-0.5 h-4 w-4 shrink-0 text-graphite-soft"
          aria-hidden="true"
        />
        <p className="font-sans text-[13px] text-graphite">
          The backbone structure whose sequence you want the model to design.
        </p>
      </div>

      <div className="grid items-end gap-3 sm:grid-cols-[1fr_120px]">
        <div className="flex flex-col gap-1.5">
          {value.uploadKey ? (
            <>
              <span className="font-sans text-[12px] text-graphite-soft">
                Uploaded structure
              </span>
              <div className="flex min-h-[50px] items-center justify-between gap-3 bg-paper px-4 py-3">
                <span className="truncate font-mono text-[13px] text-ink">
                  {value.pdb || "uploaded structure"}
                </span>
                <button
                  type="button"
                  onClick={clearUpload}
                  className="inline-flex items-center gap-1 font-sans text-[12px] text-graphite hover:text-ink"
                >
                  <X className="h-3.5 w-3.5" />
                  Clear
                </button>
              </div>
            </>
          ) : (
            <>
              <label
                htmlFor={pdbId}
                className="font-sans text-[12px] text-graphite-soft"
              >
                PDB id
              </label>
              <input
                id={pdbId}
                type="text"
                maxLength={4}
                autoComplete="off"
                spellCheck={false}
                placeholder="e.g. 1ABC"
                value={value.pdb}
                onChange={(e) => onChange({ pdb: e.target.value.trim() })}
                aria-invalid={invalidId || undefined}
                className={cn(
                  "rounded-xl border bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:normal-case placeholder:tracking-normal placeholder:text-graphite-soft",
                  "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
                  invalidId ? "border-crane" : "border-lattice-strong",
                )}
              />
            </>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <label
            htmlFor={chainId}
            className="font-sans text-[12px] text-graphite-soft"
          >
            Chain
            <span className="ml-1 lowercase tracking-normal text-graphite-soft">
              (optional)
            </span>
          </label>
          <input
            id={chainId}
            type="text"
            maxLength={1}
            autoComplete="off"
            spellCheck={false}
            placeholder="A"
            value={value.chain}
            onChange={(e) =>
              onChange({
                chain: e.target.value.trim().slice(0, 1).toUpperCase(),
              })
            }
            className={cn(
              "rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft",
              "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
            )}
          />
        </div>
      </div>

      {!value.uploadKey && (
        <div className="flex items-center gap-3">
          <span className="h-px flex-1 bg-lattice" />
          <span className="font-sans text-[12px] text-graphite-soft">
            or
          </span>
          <span className="h-px flex-1 bg-lattice" />
        </div>
      )}

      {!value.uploadKey && (
        <div>
          <input
            ref={fileRef}
            type="file"
            accept=".pdb,.cif,.mmcif,.ent"
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
                Upload .pdb / .cif
              </>
            )}
          </button>
        </div>
      )}

      {phase.phase === "error" && (
        <p role="alert" className="font-sans text-[12px] text-crane-deep">
          {phase.message}
        </p>
      )}
      {invalidId && (
        <p role="alert" className="font-sans text-[12px] text-crane-deep">
          Enter a 4-character RCSB PDB id.
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
