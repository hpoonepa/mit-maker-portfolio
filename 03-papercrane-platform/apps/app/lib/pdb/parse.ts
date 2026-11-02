/**
 * Lightweight PDB / mmCIF header parser.
 *
 * We deliberately avoid pulling Mol* into the upload path: that bundle is
 * heavyweight and only needed for 3D rendering. For validation + hotspot
 * picking we only need chain ids and a per-chain residue list.
 *
 * Scope:
 *   - PDB ATOM record parser (column-based, per the PDB spec)
 *   - mmCIF _atom_site loop parser (whitespace-tokenised)
 *   - Collapses ATOM rows to one entry per (chain, residue): we ignore HETATM
 *     so ligands/waters don't pollute the residue list.
 *
 * The parser is intentionally tolerant: malformed lines are skipped, not
 * thrown, so a partial structure still yields something usable. Callers that
 * need strict validation should layer `validate.ts` on top.
 */
import {
  AA_THREE_TO_ONE,
  type OneLetter,
} from "./aa";

export type ResidueEntry = {
  /** Sequential index within the chain (1-based). */
  index: number;
  /** Author residue number, as it appears in the PDB file. */
  authSeqId: number;
  /** PDB insertion code (e.g. "A" in 27A). Usually empty. */
  insCode: string;
  /** Three-letter residue code, uppercase. */
  resName: string;
  /** Single-letter amino acid code, or "X" for unknown. */
  oneLetter: OneLetter;
};

export type ChainEntry = {
  id: string;
  residues: ResidueEntry[];
  /** Concatenated one-letter sequence for quick display. */
  sequence: string;
};

export type ParsedStructure = {
  format: "pdb" | "cif";
  /** Header line title, best-effort. */
  title: string | null;
  /** PDB id as written in HEADER / _entry.id. May be null. */
  pdbId: string | null;
  chains: ChainEntry[];
};

const PDB_ID_RE = /^[0-9][A-Za-z0-9]{3}$/;

export function looksLikeCif(text: string): boolean {
  return /^data_/m.test(text) && /_atom_site\./m.test(text);
}

export function looksLikePdb(text: string): boolean {
  // mmCIF files often contain ATOM rows in the `_atom_site` loop that would
  // otherwise satisfy the cheap `^ATOM` sniff below, so reject CIF first.
  if (looksLikeCif(text)) return false;
  // A valid PDB has at least one ATOM record at column 1.
  return /^ATOM\s/m.test(text) || /^HEADER/m.test(text);
}

/**
 * Auto-detects format and parses. Throws if the file matches neither.
 */
export function parseStructure(text: string): ParsedStructure {
  if (looksLikeCif(text)) return parseCif(text);
  if (looksLikePdb(text)) return parsePdb(text);
  throw new Error("Unrecognised structure file (expected PDB or mmCIF)");
}

// ---------------------------------------------------------------------------
// PDB parser
// ---------------------------------------------------------------------------

/**
 * PDB ATOM record columns (1-indexed, inclusive) per the official spec:
 *   1-6   record name   "ATOM  "
 *   7-11  atom serial
 *  13-16  atom name
 *  17     altLoc
 *  18-20  residue name
 *  22     chain id
 *  23-26  residue seq number
 *  27     insertion code
 */
export function parsePdb(text: string): ParsedStructure {
  const lines = text.split(/\r?\n/);

  let title: string | null = null;
  let pdbId: string | null = null;
  const chainMap = new Map<string, ResidueEntry[]>();
  // Dedup key: "chain|seq|ins": multiple atoms per residue collapse to one.
  const seen = new Set<string>();

  for (const raw of lines) {
    if (raw.startsWith("HEADER")) {
      // Columns 63-66 hold the PDB id.
      const maybeId = raw.slice(62, 66).trim();
      if (PDB_ID_RE.test(maybeId)) pdbId = maybeId.toUpperCase();
      continue;
    }
    if (raw.startsWith("TITLE") && title == null) {
      title = raw.slice(10).trim() || null;
      continue;
    }
    if (!raw.startsWith("ATOM")) continue;

    // Must be long enough to cover chain + residue seq.
    if (raw.length < 27) continue;

    const altLoc = raw.charAt(16);
    // Only keep primary altLoc (space or 'A'): skip alternates to avoid dupes.
    if (altLoc !== " " && altLoc !== "A") continue;

    const resName = raw.slice(17, 20).trim().toUpperCase();
    const chainId = raw.charAt(21).trim() || "A";
    const seqRaw = raw.slice(22, 26).trim();
    const insCode = raw.charAt(26).trim();
    const authSeqId = Number.parseInt(seqRaw, 10);
    if (!Number.isFinite(authSeqId)) continue;

    const key = `${chainId}|${authSeqId}|${insCode}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const oneLetter = AA_THREE_TO_ONE[resName] ?? "X";

    const arr = chainMap.get(chainId) ?? [];
    arr.push({
      index: arr.length + 1,
      authSeqId,
      insCode,
      resName,
      oneLetter,
    });
    chainMap.set(chainId, arr);
  }

  const chains = Array.from(chainMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map<ChainEntry>(([id, residues]) => ({
      id,
      residues,
      sequence: residues.map((r) => r.oneLetter).join(""),
    }));

  return { format: "pdb", title, pdbId, chains };
}

// ---------------------------------------------------------------------------
// mmCIF parser (minimal: just enough to extract chains + residues)
// ---------------------------------------------------------------------------

/**
 * mmCIF has more structure than PDB but we only care about the `_atom_site`
 * loop. We find the loop header, map the column names we need, then walk data
 * rows until the next loop/save frame/blank line block.
 */
export function parseCif(text: string): ParsedStructure {
  const lines = text.split(/\r?\n/);

  let pdbId: string | null = null;
  let title: string | null = null;

  // Locate `loop_` introducing `_atom_site.*`.
  let loopStart = -1;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!.trim();
    if (line.startsWith("_entry.id")) {
      const m = line.match(/_entry\.id\s+(\S+)/);
      if (m && m[1] && PDB_ID_RE.test(m[1])) pdbId = m[1].toUpperCase();
    }
    if (line.startsWith("_struct.title")) {
      const m = line.match(/_struct\.title\s+'(.*)'/);
      if (m && m[1] !== undefined) title = m[1];
    }
    if (line === "loop_") {
      // Peek the next non-empty line: must be an _atom_site.* column header.
      let j = i + 1;
      while (j < lines.length && lines[j]!.trim() === "") j++;
      if (j < lines.length && lines[j]!.trim().startsWith("_atom_site.")) {
        loopStart = i;
        break;
      }
    }
  }

  if (loopStart === -1) {
    // No atom_site loop: return what we have.
    return { format: "cif", title, pdbId, chains: [] };
  }

  // Collect column headers.
  const columns: string[] = [];
  let dataStart = loopStart + 1;
  while (dataStart < lines.length) {
    const t = lines[dataStart]!.trim();
    if (!t.startsWith("_atom_site.")) break;
    columns.push(t.replace(/^_atom_site\./, ""));
    dataStart++;
  }

  const colIdx = (name: string) => columns.indexOf(name);
  const iGroup = colIdx("group_PDB");
  const iResName = colIdx("label_comp_id");
  const iAuthChain = colIdx("auth_asym_id");
  const iLabelChain = colIdx("label_asym_id");
  const iAuthSeq = colIdx("auth_seq_id");
  const iLabelSeq = colIdx("label_seq_id");
  const iInsCode = colIdx("pdbx_PDB_ins_code");
  const iAltLoc = colIdx("label_alt_id");

  const chainCol = iAuthChain >= 0 ? iAuthChain : iLabelChain;
  const seqCol = iAuthSeq >= 0 ? iAuthSeq : iLabelSeq;
  if (chainCol < 0 || seqCol < 0 || iResName < 0) {
    return { format: "cif", title, pdbId, chains: [] };
  }

  const chainMap = new Map<string, ResidueEntry[]>();
  const seen = new Set<string>();

  for (let k = dataStart; k < lines.length; k++) {
    const raw = lines[k]!;
    const trimmed = raw.trim();
    if (trimmed === "" || trimmed.startsWith("#")) continue;
    // Hitting the next loop or save frame ends the data block.
    if (trimmed.startsWith("loop_") || trimmed.startsWith("_") || trimmed.startsWith("save_")) {
      break;
    }

    const tokens = trimmed.split(/\s+/);
    if (tokens.length < columns.length) continue;

    // Filter by group_PDB if present: only ATOM, not HETATM.
    if (iGroup >= 0 && tokens[iGroup]!.toUpperCase() !== "ATOM") continue;

    // Drop non-primary altLocs.
    if (iAltLoc >= 0) {
      const alt = tokens[iAltLoc];
      if (alt !== "." && alt !== "?" && alt !== "A") continue;
    }

    const resName = tokens[iResName]!.toUpperCase();
    const chainId = tokens[chainCol]!;
    const seqRaw = tokens[seqCol]!;
    const insCode =
      iInsCode >= 0 && tokens[iInsCode] !== "?" && tokens[iInsCode] !== "."
        ? (tokens[iInsCode] ?? "")
        : "";
    const authSeqId = Number.parseInt(seqRaw, 10);
    if (!Number.isFinite(authSeqId)) continue;

    const key = `${chainId}|${authSeqId}|${insCode}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const oneLetter = AA_THREE_TO_ONE[resName] ?? "X";
    const arr = chainMap.get(chainId) ?? [];
    arr.push({
      index: arr.length + 1,
      authSeqId,
      insCode,
      resName,
      oneLetter,
    });
    chainMap.set(chainId, arr);
  }

  const chains = Array.from(chainMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map<ChainEntry>(([id, residues]) => ({
      id,
      residues,
      sequence: residues.map((r) => r.oneLetter).join(""),
    }));

  return { format: "cif", title, pdbId, chains };
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

/**
 * Returns the chain with the most residues (usually the canonical target).
 */
export function largestChain(parsed: ParsedStructure): ChainEntry | null {
  if (parsed.chains.length === 0) return null;
  return parsed.chains.reduce((a, b) =>
    a.residues.length >= b.residues.length ? a : b,
  );
}

/**
 * Given a list of author residue numbers, returns the subset that do NOT
 * exist in the provided chain. Empty result ⇒ all valid.
 */
export function findInvalidResidues(
  chain: ChainEntry,
  authSeqIds: number[],
): number[] {
  const present = new Set(chain.residues.map((r) => r.authSeqId));
  return authSeqIds.filter((n) => !present.has(n));
}
