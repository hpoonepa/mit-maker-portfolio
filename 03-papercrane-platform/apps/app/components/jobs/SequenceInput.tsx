"use client";

import { useId } from "react";
import { Type } from "lucide-react";
import { cn } from "@/lib/utils";

/** One parsed amino-acid sequence with a stable id. */
export type SequenceEntry = { id: string; sequence: string };

/** Shape the wizard owns for a sequence-scoring / folding job. */
export type SequenceValue = {
  /** The raw textarea contents (FASTA or one sequence per line). */
  raw: string;
  /** Parsed entries, recomputed from `raw` on every change. */
  sequences: SequenceEntry[];
};

/** Only the 20 canonical amino acids are accepted. */
const AA_RE = /^[ACDEFGHIKLMNPQRSTVWY]+$/;

/** True when an entry is non-empty and contains only canonical residues. */
function isEntryValid(entry: SequenceEntry): boolean {
  return entry.sequence.length > 0 && AA_RE.test(entry.sequence);
}

/**
 * Parse a FASTA blob OR a one-sequence-per-line blob into entries. FASTA
 * headers (lines starting with `>`) name the following record; bare lines each
 * become their own sequence with an auto id `seq_1`, `seq_2`, …. Residues are
 * uppercased and stripped of whitespace.
 */
export function parseSequences(raw: string): SequenceEntry[] {
  const entries: SequenceEntry[] = [];
  let current: SequenceEntry | null = null;
  let bareCount = 0;

  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.length === 0) continue;

    if (trimmed.startsWith(">")) {
      if (current) entries.push(current);
      const header = trimmed.slice(1).trim();
      current = { id: header || `seq_${entries.length + 1}`, sequence: "" };
      continue;
    }

    const residues = trimmed.replace(/\s+/g, "").toUpperCase();
    if (current) {
      current.sequence += residues;
    } else {
      bareCount += 1;
      entries.push({ id: `seq_${bareCount}`, sequence: residues });
    }
  }
  if (current) entries.push(current);
  return entries;
}

/** Valid if there is >=1 parsed sequence and every one is canonical. */
export function isSequenceValid(v: SequenceValue): boolean {
  return v.sequences.length > 0 && v.sequences.every(isEntryValid);
}

type SequenceInputProps = {
  value: SequenceValue;
  onChange: (patch: Partial<SequenceValue>) => void;
  error?: string;
};

/**
 * Free-text entry for one or more raw amino-acid sequences (for ESM-2 / ESM-C
 * / Boltz-1). Accepts FASTA or one sequence per line; parses `raw` into
 * `sequences` on every keystroke and flags any non-canonical sequence.
 * Controlled: no local state, everything lifts up through `onChange`.
 */
export function SequenceInput({
  value,
  onChange,
  error,
}: SequenceInputProps): JSX.Element {
  const areaId = useId();
  const invalid = value.sequences.filter((s) => !isEntryValid(s));
  const count = value.sequences.length;

  return (
    <fieldset
      className="flex flex-col gap-3 p-4"
      data-testid="e2e-sequence-input"
    >
      <legend className="px-1 font-sans text-[12px] text-graphite-soft">
        Sequences
      </legend>
      <div className="flex items-start gap-2.5">
        <Type
          className="mt-0.5 h-4 w-4 shrink-0 text-graphite-soft"
          aria-hidden="true"
        />
        <p className="font-sans text-[13px] text-graphite">
          One or more amino-acid sequences: FASTA (with{" "}
          <span className="font-mono">&gt;</span> headers) or one sequence per
          line.
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <label
          htmlFor={areaId}
          className="font-sans text-[12px] text-graphite-soft"
        >
          Amino-acid sequences
        </label>
        <textarea
          id={areaId}
          rows={6}
          autoComplete="off"
          spellCheck={false}
          placeholder=">seq_a&#10;MKLLVL...&#10;>seq_b&#10;GEVKQ..."
          value={value.raw}
          onChange={(e) => {
            const raw = e.target.value;
            onChange({ raw, sequences: parseSequences(raw) });
          }}
          aria-invalid={invalid.length > 0 || undefined}
          className={cn(
            "rounded-xl border bg-paper px-4 py-3 font-sans text-[13px] text-ink placeholder:normal-case placeholder:tracking-normal placeholder:text-graphite-soft",
            "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
            invalid.length > 0 ? "border-crane" : "border-lattice-strong",
          )}
        />
      </div>

      {count > 0 && (
        <p className="font-sans text-[12px] text-graphite-soft">
          {count} {count === 1 ? "sequence" : "sequences"} parsed
        </p>
      )}

      {invalid.length > 0 && (
        <p role="alert" className="font-sans text-[12px] text-crane-deep">
          Non-canonical residues in:{" "}
          <span className="font-mono">
            {invalid.map((s) => s.id).join(", ")}
          </span>
          . Only the 20 standard amino acids are allowed.
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
