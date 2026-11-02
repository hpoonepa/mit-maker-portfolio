"use client";

import { useMemo, useState } from "react";
import { Check, Copy, Palette } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Mono-spaced sequence display with optional secondary-structure track.
 *
 * Secondary structure (DSSP-style) is rendered as a colored band beneath
 * the row using single-letter codes: H = helix, E = sheet, T = turn,
 * any other char (`-`, ` `, `C`) renders as coil. Track may be omitted.
 *
 * The display reflows responsively: rows wrap at a configurable column
 * count (default 60) so long sequences stay readable.
 */

export interface SequenceViewerProps {
  sequence: string;
  /** Same length as `sequence` when present. Extra characters are clipped. */
  secondaryStructure?: string | null;
  cols?: number;
  /** Highlight specific 0-indexed residue positions. */
  highlight?: number[];
  className?: string;
}

const HYDROPHOBIC = new Set([..."AVILMFWPCG"]);
const POLAR = new Set([..."STYNQH"]);
const POSITIVE = new Set([..."KR"]);
const NEGATIVE = new Set([..."DE"]);

export function SequenceViewer({
  sequence,
  secondaryStructure,
  cols = 60,
  highlight,
  className,
}: SequenceViewerProps) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const [colorMode, setColorMode] = useState<"chemistry" | "plain">(
    "plain",
  );

  const highlightSet = useMemo(() => new Set(highlight ?? []), [highlight]);

  const chunks = useMemo(() => {
    const rows: Array<{ start: number; seq: string; ss?: string }> = [];
    for (let i = 0; i < sequence.length; i += cols) {
      rows.push({
        start: i,
        seq: sequence.slice(i, i + cols),
        ss: secondaryStructure
          ? secondaryStructure.slice(i, i + cols)
          : undefined,
      });
    }
    return rows;
  }, [sequence, secondaryStructure, cols]);

  const handleCopy = async () => {
    try {
      setCopyError(false);
      await navigator.clipboard.writeText(sequence);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopyError(true);
    }
  };

  return (
    <div
      className={cn(
        "rounded-lg border border-lattice bg-paper-fold/40 p-5",
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-sans text-[12px] text-graphite">
            Sequence
          </h3>
          <p className="mt-1 font-sans text-[12px] text-graphite-soft">
            {sequence.length} residues
            {secondaryStructure ? " · DSSP track" : ""}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() =>
              setColorMode((m) => (m === "chemistry" ? "plain" : "chemistry"))
            }
            className={cn(
              "inline-flex items-center gap-1 rounded-lg border px-2 py-1 font-sans text-[12px] transition-colors",
              colorMode === "chemistry"
                ? "border-ink bg-ink text-paper"
                : "border-lattice bg-paper text-graphite hover:text-ink",
            )}
            aria-pressed={colorMode === "chemistry"}
          >
            <Palette className="h-3 w-3" />
            Chemistry
          </button>
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded-lg border border-lattice bg-paper px-2 py-1 font-sans text-[12px] text-graphite hover:text-ink transition-colors"
          >
            {copied ? (
              <Check className="h-3 w-3" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto bg-paper px-4 py-3">
        <div className="flex flex-col gap-3 font-mono text-[13px] leading-relaxed">
          {chunks.map((row) => (
            <div key={row.start} className="flex items-start gap-4">
              <span className="shrink-0 select-none pt-0.5 font-mono text-[10px] text-graphite-soft tabular-nums">
                {String(row.start + 1).padStart(4, " ")}
              </span>
              <div className="flex-1">
                <div className="flex flex-wrap">
                  {row.seq.split("").map((aa, i) => {
                    const idx = row.start + i;
                    return (
                      <span
                        key={i}
                        className={cn(
                          "px-[1px]",
                          colorMode === "chemistry" && chemistryClass(aa),
                          highlightSet.has(idx) &&
                            "rounded-sm bg-crane-glow text-crane-deep",
                        )}
                      >
                        {aa}
                      </span>
                    );
                  })}
                </div>
                {row.ss && (
                  <div className="mt-1 flex">
                    {row.ss.split("").map((c, i) => (
                      <span
                        key={i}
                        className={cn(
                          "inline-block w-[7.2px] text-center font-mono text-[8px] leading-none",
                          ssClass(c),
                        )}
                        title={ssLabel(c)}
                      >
                        {ssGlyph(c)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <span className="shrink-0 select-none pt-0.5 font-mono text-[10px] text-graphite-soft tabular-nums">
                {row.start + row.seq.length}
              </span>
            </div>
          ))}
        </div>
      </div>

      {copyError && <p role="alert" className="mt-2 text-xs text-crane-deep">Could not copy. Select the sequence or download FASTA.</p>}
      {colorMode === "chemistry" && (
        <div className="mt-3 flex flex-wrap gap-3">
          <Legend label="Hydrophobic" className="text-[#7a8e6f]" />
          <Legend label="Polar" className="text-[#3e6a8c]" />
          <Legend label="Positive" className="text-[#b8845a]" />
          <Legend label="Negative" className="text-[#c0633d]" />
        </div>
      )}
    </div>
  );
}

function chemistryClass(aa: string): string {
  const c = aa.toUpperCase();
  if (HYDROPHOBIC.has(c)) return "text-[#7a8e6f]";
  if (POSITIVE.has(c)) return "text-[#b8845a]";
  if (NEGATIVE.has(c)) return "text-[#c0633d]";
  if (POLAR.has(c)) return "text-[#3e6a8c]";
  return "text-graphite";
}

function ssClass(c: string): string {
  switch (c.toUpperCase()) {
    case "H":
      return "text-[#b8845a]";
    case "E":
      return "text-[#7a8e6f]";
    case "T":
      return "text-graphite-soft";
    default:
      return "text-graphite-soft";
  }
}

function ssGlyph(c: string): string {
  switch (c.toUpperCase()) {
    case "H":
      return "α";
    case "E":
      return "β";
    case "T":
      return "↺";
    default:
      return "·";
  }
}

function ssLabel(c: string): string {
  switch (c.toUpperCase()) {
    case "H":
      return "α-helix";
    case "E":
      return "β-strand";
    case "T":
      return "turn";
    default:
      return "coil";
  }
}

function Legend({ label, className }: { label: string; className: string }) {
  return (
    <span className="inline-flex items-center gap-1 font-sans text-[12px] text-graphite-soft">
      <span className={cn("font-mono text-[12px]", className)}>A</span>
      {label}
    </span>
  );
}
