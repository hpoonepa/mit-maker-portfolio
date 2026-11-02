"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { Search, Upload } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PdbFetchError,
  pdbIdSchema,
  validatePdbId,
} from "@/lib/pdb/fetch";

/**
 * Input row for picking a structure source.
 *
 * Two parallel paths:
 *   - Type a 4-char PDB ID → `onPdbId` fires with the validated, upper-cased ID.
 *   - Drop / pick a `.pdb` / `.cif` file → `onFile` fires with the File handle.
 *
 * Validation runs synchronously (shape only): actual existence on RCSB is
 * checked by `<StructureLoader>` after submit. This keeps the component
 * cheap and makes the demo offline-friendly.
 */
export interface PdbInputProps {
  onPdbId: (id: string) => void;
  onFile?: (file: File) => void;
  /** Currently loaded label, displayed as a placeholder. */
  currentLabel?: string;
  /** Disabled while a structure is loading. */
  loading?: boolean;
  className?: string;
}

const QUICK_PICKS = [
  { id: "6X1A", label: "6X1A · SARS-CoV-2 spike RBD" },
  { id: "1CRN", label: "1CRN · crambin" },
  { id: "4HHB", label: "4HHB · hemoglobin" },
];

export function PdbInput({
  onPdbId,
  onFile,
  currentLabel,
  loading,
  className,
}: PdbInputProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // Live shape validation: clears the error as soon as the input becomes
  // valid (or empty). Avoids a stale red border after the user fixes a typo.
  useEffect(() => {
    if (value.trim() === "") {
      setError(null);
      return;
    }
    const parsed = pdbIdSchema.safeParse(value);
    setError(parsed.success ? null : null);
  }, [value]);

  const onSubmit = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      try {
        const id = validatePdbId(value);
        setError(null);
        onPdbId(id);
      } catch (err) {
        setError(
          err instanceof PdbFetchError
            ? err.message
            : "Enter a 4-character PDB ID like 6X1A",
        );
      }
    },
    [onPdbId, value],
  );

  const onPick = useCallback(
    (id: string) => {
      try {
        const valid = validatePdbId(id);
        setValue(valid);
        setError(null);
        onPdbId(valid);
      } catch (err) {
        setError(
          err instanceof PdbFetchError
            ? err.message
            : "Enter a 4-character PDB ID like 6X1A",
        );
      }
    },
    [onPdbId],
  );

  const onFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      onFile?.(file);
      // Reset the input so the same file can be re-selected if the user
      // clears the viewer.
      e.target.value = "";
    },
    [onFile],
  );

  return (
    <div className={cn("flex flex-col gap-2", className)} data-testid="pdb-input">
      <form
        onSubmit={onSubmit}
        className="flex w-full items-stretch gap-2"
        role="search"
        aria-label="Load PDB structure"
      >
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-graphite-500"
            aria-hidden="true"
          />
          <input
            type="text"
            inputMode="text"
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={currentLabel ?? "Enter PDB ID (e.g. 6X1A)"}
            aria-label="PDB ID"
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "pdb-input-error" : undefined}
            disabled={loading}
            className={cn(
              "h-10 w-full rounded-md border bg-white pl-9 pr-3 text-sm",
              "border-graphite-200 focus:border-crane-500 focus:outline-none",
              "disabled:cursor-not-allowed disabled:opacity-60",
              error && "border-red-500 focus:border-red-500",
            )}
          />
        </div>

        <button
          type="submit"
          disabled={loading || value.trim().length === 0}
          className={cn(
            "h-10 rounded-md bg-crane-600 px-4 text-sm font-medium text-white",
            "hover:bg-crane-700 disabled:cursor-not-allowed disabled:opacity-60",
          )}
        >
          {loading ? "Loading…" : "Load"}
        </button>

        {onFile && (
          <>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={loading}
              className={cn(
                "flex h-10 items-center gap-1.5 rounded-md border px-3 text-sm",
                "border-graphite-200 text-graphite-700 hover:bg-graphite-50",
                "disabled:cursor-not-allowed disabled:opacity-60",
              )}
              title="Upload .pdb or .cif"
            >
              <Upload className="h-4 w-4" aria-hidden="true" />
              Upload
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".pdb,.ent,.cif,.mmcif"
              className="hidden"
              onChange={onFileChange}
              aria-label="Upload structure file"
            />
          </>
        )}
      </form>

      {error && (
        <div
          id="pdb-input-error"
          role="alert"
          className="text-xs text-red-600"
        >
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span
          className="font-sans text-[12px] text-graphite-400"
          style={{ fontFamily: "var(--font-jetbrains-mono, ui-monospace, SFMono-Regular, monospace)" }}
        >
          Quick load
        </span>
        {QUICK_PICKS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onPick(p.id)}
            disabled={loading}
            aria-label={`Load ${p.label}`}
            title={p.label}
            className={cn(
              "rounded-full border px-2.5 py-0.5 font-mono transition-colors",
              "border-graphite-200 text-graphite-700 hover:border-crane-500 hover:text-crane-600",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-crane-500 focus-visible:ring-offset-1 focus-visible:border-crane-500",
              "disabled:cursor-not-allowed disabled:opacity-60",
            )}
          >
            {p.id}
          </button>
        ))}
      </div>
    </div>
  );
}

export default PdbInput;
