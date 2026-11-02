/**
 * Amino acid code tables. Split into its own module so parse.ts stays lean
 * and tests can import the mapping directly.
 *
 * Also hosts a few presentation primitives used by the hotspot picker (label
 * formatting, kbd chrome, empty-state microcopy) so the picker UI stays free
 * of stringly-typed magic and matches the Crane / origami visual language.
 *
 * Kept dependency-free (no `import` from parse.ts) to avoid a cycle.
 */

export type OneLetter =
  | "A" | "R" | "N" | "D" | "C" | "E" | "Q" | "G" | "H" | "I"
  | "L" | "K" | "M" | "F" | "P" | "S" | "T" | "W" | "Y" | "V"
  | "X";

export const AA_THREE_TO_ONE: Readonly<Record<string, OneLetter>> = {
  ALA: "A",
  ARG: "R",
  ASN: "N",
  ASP: "D",
  CYS: "C",
  GLU: "E",
  GLN: "Q",
  GLY: "G",
  HIS: "H",
  ILE: "I",
  LEU: "L",
  LYS: "K",
  MET: "M",
  PHE: "F",
  PRO: "P",
  SER: "S",
  THR: "T",
  TRP: "W",
  TYR: "Y",
  VAL: "V",
  // Modified / selenium variants mapped to their canonical parents.
  MSE: "M",
  SEC: "C",
  PYL: "K",
};

/**
 * Tailwind utility class for each chain, cycled. Keeps chain color stable
 * per chain id across the UI without needing a theme prop.
 */
export function chainColorClass(chainId: string): string {
  const palette = [
    "text-ink",
    "text-crane-deep",
    "text-graphite",
    "text-ink-soft",
    "text-crane",
  ];
  let h = 0;
  for (let i = 0; i < chainId.length; i++) h = (h * 31 + chainId.charCodeAt(i)) & 0xffff;
  return palette[h % palette.length]!;
}

// ---------------------------------------------------------------------------
// Hotspot picker presentation primitives
// ---------------------------------------------------------------------------
//
// The picker panel and 3D viewer chips need a single source of truth for how
// a residue is shown / copied / keyed. Putting these here means
// `components/molstar/*` and `components/targets/*` render the same string
// without each rolling their own slice / template.

/** Structural slice of {@link ResidueEntry}: duplicated to avoid a cycle. */
type ResidueLike = {
  authSeqId: number;
  insCode?: string;
  resName: string;
};

/**
 * Display label for a residue in the hotspot panel. Format: `A · 47 · ARG`
 * (chain · author resnum (+insCode if any) · 3-letter aa). The middle dot is
 * U+00B7: paired with `font-mono` (JetBrains Mono) it sits cleanly between
 * tokens without looking like a SaaS-style chip separator.
 */
export function formatResidueLabel(chainId: string, residue: ResidueLike): string {
  const ins = residue.insCode ? residue.insCode : "";
  return `${chainId} · ${residue.authSeqId}${ins} · ${residue.resName}`;
}

/**
 * Canonical copyable token for a residue, e.g. `A47` or `A47A` (with insCode).
 * This is the form consumers paste into BindCraft / RFdiffusion hotspot lists,
 * so we keep it tight and hyphen-free.
 */
export function residueCopyToken(chainId: string, residue: ResidueLike): string {
  return `${chainId}${residue.authSeqId}${residue.insCode ?? ""}`;
}

/**
 * Tailwind class string for the `<kbd>` chrome used in the picker hint
 * ("press h to toggle, Esc to clear"). JetBrains Mono + soft paper bg + thin
 * graphite border. Kept here so the class never drifts between the picker
 * and its tooltip / legend siblings.
 */
export const KBD_CLASS =
  "inline-flex items-center rounded border border-graphite/30 bg-paper px-1.5 py-0.5 font-mono text-[10px] uppercase leading-none text-ink-soft";

/**
 * Empty-state microcopy for the residue list. Two-line origami fold: a quiet
 * primary line and a tiny secondary hint. The picker should render line 2
 * smaller / lighter: the strings themselves stay free of UI chrome.
 */
export const EMPTY_PICKER_COPY = {
  primary: "No residues folded yet.",
  secondary: "Click a residue in the viewer, or press h to start picking.",
} as const;
