/**
 * FASTA serialisation for Design[].
 *
 * Header convention (matches design-export spec):
 *   >design_<seed>_<id-prefix> ipTM=X pAE=Y
 *   <sequence>
 *
 * - `id-prefix` is the first 8 chars of the design id so the header stays
 *   readable in genome browsers and grep output.
 * - Numeric metrics that exist on the design are appended in a stable order
 *   so two exports of the same design always produce identical bytes.
 * - Sequences are wrapped at 60 chars per line: that's the FASTA-spec
 *   default and what most downstream tools (HMMER, BLAST, PyMOL) expect.
 */

import { normaliseDesignProvenance } from "@papercrane/types";

export interface FastaDesignInput {
  id: string;
  seed: number;
  sequence: string;
  provenance?: string | null;
  metrics?: Record<string, number | undefined>;
}

// Keep model-native numbers in downloaded sequences, including ProteinMPNN's
// score/global_score/seq_recovery. Do not invent a cross-model ranking.
const NON_SCORE_FIELDS = new Set(["length", "seed", "rank", "composite_rank"]);

/** Wrap a sequence at `width` chars/line. Empty input yields no lines. */
export function wrapSequence(seq: string, width = 60): string {
  if (!seq) return "";
  const out: string[] = [];
  for (let i = 0; i < seq.length; i += width) {
    out.push(seq.slice(i, i + width));
  }
  return out.join("\n");
}

/** Format a single design as a FASTA record (header + wrapped sequence). */
export function formatFastaRecord(d: FastaDesignInput): string {
  const idShort = d.id.slice(0, 8);
  const metricBits: string[] = [];
  const m = d.metrics ?? {};
  for (const k of Object.keys(m).sort()) {
    const v = m[k];
    if (!NON_SCORE_FIELDS.has(k) && /^[a-zA-Z0-9_.-]+$/.test(k) && typeof v === "number" && Number.isFinite(v)) {
      metricBits.push(`${k}=${v}`);
    }
  }
  const header = `>design_${d.seed}_${idShort} provenance=${normaliseDesignProvenance(d.provenance)}${
    metricBits.length ? " " + metricBits.join(" ") : ""
  }`;
  return `${header}\n${wrapSequence(d.sequence)}\n`;
}

/** Concatenate many designs into a single multi-FASTA blob. */
export function formatFasta(designs: FastaDesignInput[]): string {
  return designs.map(formatFastaRecord).join("");
}
