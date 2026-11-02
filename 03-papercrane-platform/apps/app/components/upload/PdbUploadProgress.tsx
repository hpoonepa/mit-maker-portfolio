"use client";

import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/lib/pdb/validate";

/**
 * Errors are categorised so we can show actionable copy:
 *   - validate: client-side reject (extension / size / parse): user fixes the file
 *   - presign:  /api/upload/presign failed: likely auth / server outage
 *   - put:      PUT to storage failed: network or storage issue. In dev the
 *               presign stub returns a fake URL so the PUT is _expected_ to
 *               fail; we surface a "[dev stub]" hint in that case.
 *   - parse:    server parse step failed
 */
export type UploadErrorKind = "validate" | "presign" | "put" | "parse";

export type UploadPhase =
  | { phase: "idle" }
  | { phase: "signing" }
  | { phase: "uploading"; pct: number }
  | { phase: "parsing" }
  | { phase: "done"; checksum?: string }
  | { phase: "error"; message: string; kind?: UploadErrorKind };

export interface PdbUploadProgressProps {
  filename: string;
  sizeBytes: number;
  status: UploadPhase;
  className?: string;
  /** Optional re-upload handler: renders a "Choose another file" link when set. */
  onReset?: () => void;
}

const IS_DEV =
  typeof process !== "undefined" && process.env.NODE_ENV !== "production";

/**
 * Shows the file name + size + a progress bar while we stream to R2 and
 * then ask the server to parse it. Visual states match the four phases of
 * the upload flow so users always know which step is in flight.
 */
export function PdbUploadProgress({
  filename,
  sizeBytes,
  status,
  className,
  onReset,
}: PdbUploadProgressProps) {
  const pct = pctFor(status);
  const label = labelFor(status);
  const errored = status.phase === "error";
  const done = status.phase === "done";
  const checksum = done ? status.checksum : undefined;

  // In dev the presign endpoint returns a stub URL, so PUT failures are
  // expected. Tag them inline so devs don't think it's a real bug.
  const isDevStubFail =
    IS_DEV && errored && (status.kind === "put" || status.kind === "presign");
  const errorHeadline = errored ? headlineFor(status.kind) : null;

  return (
    <div
      className={cn(
        "rounded-lg border border-lattice bg-paper px-4 py-3 space-y-3",
        errored && "border-crane",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-[13px] text-ink">{filename}</p>
          <p className="font-mono text-[11px] text-graphite-soft">
            {formatBytes(sizeBytes)}
            {checksum && (
              <>
                {" · "}
                <span title={checksum}>sha256 {checksum.slice(0, 10)}…</span>
              </>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2 font-sans text-[12px]">
          {errored ? (
            <span className="inline-flex items-center gap-1.5 text-crane-deep">
              <span
                aria-hidden
                className="inline-block w-2 h-2 rounded-full bg-crane"
              />
              {errorHeadline}
            </span>
          ) : done ? (
            <span className="inline-flex items-center gap-1.5 text-ink">
              <span
                aria-hidden
                className="inline-block w-2 h-2 rounded-full bg-crane"
              />
              Done
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-graphite">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              {label}
            </span>
          )}
        </div>
      </div>

      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-px w-full overflow-hidden bg-lattice"
      >
        <div
          className={cn(
            "h-full transition-[width] duration-150 ease-out",
            errored ? "bg-crane" : "bg-ink",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>

      {errored && (
        <div className="flex items-start justify-between gap-3">
          <p className="font-sans text-[12px] text-crane-deep">
            {status.message}
            {isDevStubFail && (
              <span className="ml-1.5 font-sans text-[12px] r text-graphite-soft">
                [dev stub]
              </span>
            )}
          </p>
          {onReset && (
            <button
              type="button"
              onClick={onReset}
              className="shrink-0 font-sans text-[12px] text-ink underline underline-offset-4 hover:text-crane-deep"
            >
              Choose another file
            </button>
          )}
        </div>
      )}

      {done && onReset && (
        <button
          type="button"
          onClick={onReset}
          className="font-sans text-[12px] text-graphite underline underline-offset-4 hover:text-ink"
        >
          Replace file
        </button>
      )}
    </div>
  );
}

function headlineFor(kind: UploadErrorKind | undefined): string {
  switch (kind) {
    case "validate":
      return "Rejected";
    case "presign":
      return "Sign URL failed";
    case "put":
      return "Upload failed";
    case "parse":
      return "Parse failed";
    default:
      return "Failed";
  }
}

function pctFor(s: UploadPhase): number {
  switch (s.phase) {
    case "idle":
      return 0;
    case "signing":
      return 5;
    case "uploading":
      return Math.max(5, Math.min(90, s.pct));
    case "parsing":
      return 95;
    case "done":
      return 100;
    case "error":
      return 100;
  }
}

function labelFor(s: UploadPhase): string {
  switch (s.phase) {
    case "idle":
      return "Waiting…";
    case "signing":
      return "Requesting upload URL…";
    case "uploading":
      return `Uploading… ${s.pct}%`;
    case "parsing":
      return "Parsing structure…";
    case "done":
      return "Done";
    case "error":
      return "Failed";
  }
}
