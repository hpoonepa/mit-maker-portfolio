"use client";

import { useId, useRef, useState } from "react";
import { Layers, Loader2, Upload, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { trpc } from "@/lib/trpc/client";
import { uploadStructureFile } from "@/lib/pdb/upload";

/** Shape the wizard owns for a co-fold structure-prediction job. */
export type ComplexInput = {
  /** RCSB id (or S3 key) of structure A: the target. */
  targetPdb: string;
  /** Optional single-letter chain from structure A. */
  targetChain: string;
  /** Display name retained when Structure A is an uploaded private object. */
  targetFilename?: string;
  /** RCSB id (or S3 key) of structure B: the binder/partner. */
  partnerPdb: string;
  /** Optional single-letter chain from structure B. */
  partnerChain: string;
  /** Display name retained when Structure B is an uploaded private object. */
  partnerFilename?: string;
};

/** RCSB PDB ids are 4 chars: a leading digit then three alphanumerics. */
const PDB_ID_RE = /^[0-9][a-zA-Z0-9]{3}$/;

/** A trimmed value passes if it's a well-formed 4-char RCSB id. */
export function isValidPdbId(raw: string): boolean {
  return PDB_ID_RE.test(raw.trim());
}

/** True for a private upload reference minted by the Paper Crane API. */
export function isUploadedStructureReference(raw: string): boolean {
  return /^orgs\/[^/]+\/.+/.test(raw.trim());
}

/** Complex inputs accept either a public RCSB id or a staged private upload. */
export function isValidStructureReference(raw: string): boolean {
  return isValidPdbId(raw) || isUploadedStructureReference(raw);
}

type ComplexInputStepProps = {
  /** Current values: the wizard owns this state (mirrors TargetSelector). */
  value: ComplexInput;
  /** Emits a partial patch; the wizard merges it into its state. */
  onChange: (patch: Partial<ComplexInput>) => void;
  /** Optional top-level error (e.g. from a failed submit). */
  error?: string;
};

/**
 * Structure-prediction input: collects TWO structures to co-fold. Structure A
 * is the target, Structure B the binder/partner. Each accepts a 4-char RCSB
 * PDB id or a private .pdb/.cif upload, plus an optional single-letter chain.
 * Unlike {@link TargetSelector} there are no hotspots: nothing is being
 * designed, the two given structures are simply folded together.
 *
 * Controlled: durable references and filenames lift through `onChange`, while
 * each field keeps only its transient upload progress locally.
 */
export function ComplexInputStep({
  value,
  onChange,
  error,
}: ComplexInputStepProps): JSX.Element {
  return (
    <div className="flex flex-col gap-5" data-testid="e2e-complex-input">
      <div className="flex items-start gap-2.5 px-4 py-3">
        <Layers
          className="mt-0.5 h-4 w-4 shrink-0 text-graphite-soft"
          aria-hidden="true"
        />
        <p className="font-sans text-[13px] leading-relaxed text-graphite">
          Structure prediction co-folds the two structures you give below into a
          single complex. No binders are designed: enter both structures you
          want folded together.
        </p>
      </div>

      <StructureField
        legend="Structure A (target)"
        hint="The structure you're folding against."
        pdb={value.targetPdb}
        chain={value.targetChain}
        filename={value.targetFilename}
        onPdbChange={(targetPdb, targetFilename) =>
          onChange({ targetPdb, targetFilename })
        }
        onChainChange={(targetChain) => onChange({ targetChain })}
      />

      <StructureField
        legend="Structure B (binder / partner)"
        hint="The structure folded together with the target."
        pdb={value.partnerPdb}
        chain={value.partnerChain}
        filename={value.partnerFilename}
        onPdbChange={(partnerPdb, partnerFilename) =>
          onChange({ partnerPdb, partnerFilename })
        }
        onChainChange={(partnerChain) => onChange({ partnerChain })}
      />

      {error && (
        <p role="alert" className="font-sans text-[12px] text-crane-deep">
          {error}
        </p>
      )}
    </div>
  );
}

function StructureField({
  legend,
  hint,
  pdb,
  chain,
  filename,
  onPdbChange,
  onChainChange,
}: {
  legend: string;
  hint: string;
  pdb: string;
  chain: string;
  filename?: string;
  onPdbChange: (value: string, filename?: string) => void;
  onChainChange: (value: string) => void;
}) {
  const pdbId = useId();
  const chainId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<
    | { phase: "idle" }
    | { phase: "uploading"; pct: number }
    | { phase: "error"; message: string }
  >({ phase: "idle" });
  const getUploadUrl = trpc.targets.getUploadUrl.useMutation();
  const uploaded = isUploadedStructureReference(pdb);
  const uploading = phase.phase === "uploading";
  const invalid = pdb.trim().length > 0 && !isValidStructureReference(pdb);

  const handleFile = async (file: File) => {
    setPhase({ phase: "uploading", pct: 0 });
    try {
      const { uploadKey } = await uploadStructureFile({
        file,
        getSignedUrl: async ({ filename: name, contentLength }) => {
          const out = await getUploadUrl.mutateAsync({
            filename: name,
            contentLength,
          });
          return { url: out.url, uploadKey: out.uploadKey };
        },
        onProgress: (pct) => setPhase({ phase: "uploading", pct }),
      });
      setPhase({ phase: "idle" });
      onPdbChange(uploadKey, file.name);
    } catch (err) {
      setPhase({
        phase: "error",
        message: err instanceof Error ? err.message : "Upload failed",
      });
    }
  };

  const clearUpload = () => {
    setPhase({ phase: "idle" });
    onPdbChange("", undefined);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <fieldset className="flex flex-col gap-3 p-4">
      <legend className="px-1 font-sans text-[12px] text-graphite-soft">
        {legend}
      </legend>
      <p className="font-sans text-[13px] text-graphite">{hint}</p>

      <div className="grid items-end gap-3 sm:grid-cols-[1fr_120px]">
        <div className="flex flex-col gap-1.5">
          {uploaded ? (
            <>
              <span className="font-sans text-[12px] text-graphite-soft">
                Uploaded structure
              </span>
              <div className="flex min-h-[50px] items-center justify-between gap-3 bg-paper px-4 py-3">
                <span className="truncate font-mono text-[13px] text-ink">
                  {filename || "uploaded structure"}
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
                inputMode="text"
                maxLength={4}
                autoComplete="off"
                spellCheck={false}
                placeholder="e.g. 1ABC"
                value={pdb}
                onChange={(e) => onPdbChange(e.target.value.trim(), undefined)}
                aria-invalid={invalid || undefined}
                className={cn(
                  "rounded-xl border bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:normal-case placeholder:tracking-normal placeholder:text-graphite-soft",
                  "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
                  invalid ? "border-crane" : "border-lattice-strong",
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
            inputMode="text"
            maxLength={1}
            autoComplete="off"
            spellCheck={false}
            placeholder="A"
            value={chain}
            onChange={(e) =>
              onChainChange(e.target.value.trim().slice(0, 1).toUpperCase())
            }
            className={cn(
              "rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft",
              "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
            )}
          />
        </div>
      </div>

      {!uploaded && (
        <div className="flex items-center gap-3">
          <span className="h-px flex-1 bg-lattice" />
          <span className="font-sans text-[12px] text-graphite-soft">
            or
          </span>
          <span className="h-px flex-1 bg-lattice" />
        </div>
      )}

      {!uploaded && (
        <div>
          <input
            ref={fileRef}
            type="file"
            accept=".pdb,.cif,.mmcif,.ent"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
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

      {invalid && (
        <p role="alert" className="font-sans text-[12px] text-crane-deep">
          Enter a 4-character RCSB PDB id or upload a structure file.
        </p>
      )}
    </fieldset>
  );
}
