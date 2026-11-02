/**
 * Side-effect-free helpers for the 3D hotspot picker.
 *
 * The React component (`HotspotPicker3D`) wires these into a running Mol*
 * plugin instance. Keeping the logic here means we can test selection /
 * focus behaviour without booting a WebGL canvas in jsdom.
 *
 * Mol* ~4.8.0 API touch-points:
 *   - `managers.structure.selection.fromSelectionQuery('set', query)`: the
 *     same path `MolstarViewer` already uses for highlights.
 *   - `managers.structure.selection.clear()`: resets the selection.
 *   - `managers.camera.focusLoci(loci)`: smooth-zoom to a loci; respects
 *     the trackball animation setting which we gate via `shouldAnimateCamera`.
 *   - `MolScriptBuilder` (`molstar/lib/mol-script/language/builder`): query
 *     construction; dynamic-imported to keep the Mol* chunk off the critical
 *     path.
 */
import type { DesignHighlight } from "@/components/viewer/types";

/** Shape returned by `residueIdFromMolstarEvent`. */
export interface ResidueId {
  chain: string;
  resi: number;
}

/**
 * Pulls a `{chain, resi}` tuple out of a Mol* interaction event. Mol* emits
 * several loci shapes depending on the subscriber (hover vs click, element
 * vs bond). We only care about element-loci payloads that point at exactly
 * one residue.
 *
 * The event shape we accept is deliberately permissive: Mol* does not ship
 * tight types for `behaviors.interaction.{hover,click}` and the internal
 * types move between minor versions. Callers pass through whatever the
 * subscription emits and we dig for `current.loci`.
 */
export function residueIdFromMolstarEvent(event: unknown): ResidueId | null {
  if (!event || typeof event !== "object") return null;
  const current = (event as { current?: unknown }).current;
  if (!current || typeof current !== "object") return null;
  const loci = (current as { loci?: unknown }).loci;
  if (!loci || typeof loci !== "object") return null;

  const kind = (loci as { kind?: string }).kind;
  if (kind === "empty-loci" || kind === undefined) return null;

  const elements = (loci as { elements?: unknown[] }).elements;
  if (!Array.isArray(elements) || elements.length === 0) return null;

  const first = elements[0] as {
    unit?: {
      model?: {
        atomicHierarchy?: {
          residues?: { auth_seq_id?: { value: (i: number) => number } };
          chains?: { auth_asym_id?: { value: (i: number) => string } };
        };
      };
      residueIndex?: { value: (i: number) => number };
      chainIndex?: { value: (i: number) => number };
    };
    indices?: { start?: number };
  };

  const unit = first?.unit;
  const hierarchy = unit?.model?.atomicHierarchy;
  if (!unit || !hierarchy) return null;

  const atomIndex = first.indices?.start ?? 0;
  const residueIndex = unit.residueIndex?.value?.(atomIndex);
  const chainIndex = unit.chainIndex?.value?.(atomIndex);
  if (residueIndex == null || chainIndex == null) return null;

  const resi = hierarchy.residues?.auth_seq_id?.value?.(residueIndex);
  const chain = hierarchy.chains?.auth_asym_id?.value?.(chainIndex);
  if (resi == null || chain == null) return null;

  return { chain: String(chain), resi: Number(resi) };
}

/**
 * Projects the caller's selection Set into the shape the existing
 * `MolstarViewer` already understands. That component already handles the
 * yellow-sphere rendering path; we just have to feed it `DesignHighlight[]`.
 */
export function buildHotspotHighlights(
  selected: Set<number>,
  chainId: string,
): DesignHighlight[] {
  const out: DesignHighlight[] = [];
  for (const resi of selected) {
    out.push({ chainId, resi, style: "sphere" });
  }
  return out;
}

/** Descriptor handed to `animateCameraToSelection`. */
export interface FocusSelection {
  chain: string;
  resis: number[];
}

export function deriveCameraFocusSelection(
  selected: Set<number>,
  chainId: string,
): FocusSelection | null {
  if (selected.size === 0) return null;
  return {
    chain: chainId,
    resis: [...selected].sort((a, b) => a - b),
  };
}

export function shouldAnimateCamera(opts: {
  reducedMotion: boolean;
  hasSelection: boolean;
}): boolean {
  if (opts.reducedMotion) return false;
  return opts.hasSelection;
}

/**
 * Move the keyboard focus ring to the next/previous residue. The component
 * owns the current focus and passes us the ordered residue list straight
 * from the parsed chain. Arrow keys beyond the ends clamp rather than wrap
 *: wrapping is surprising when skimming a hotspot panel.
 */
export function nextFocusResidue(
  residues: number[],
  currentFocus: number | null,
  key: string,
): number | null {
  const first = residues[0];
  if (first === undefined) return null;
  if (key !== "ArrowLeft" && key !== "ArrowRight") {
    return currentFocus ?? first;
  }
  if (currentFocus == null) return first;
  const idx = residues.indexOf(currentFocus);
  if (idx === -1) return first;
  if (key === "ArrowRight") {
    const nextIdx = idx >= residues.length - 1 ? idx : idx + 1;
    return residues[nextIdx] ?? first;
  }
  const prevIdx = idx <= 0 ? 0 : idx - 1;
  return residues[prevIdx] ?? first;
}

/**
 * Enforce the hotspot cap. Returns a new Set plus a `denied` flag the caller
 * can use to flash a "cap reached" animation.
 */
export function clampSelectionToggle(
  selected: Set<number>,
  resi: number,
  cap: number,
): { selected: Set<number>; denied: boolean } {
  if (selected.has(resi)) {
    const next = new Set(selected);
    next.delete(resi);
    return { selected: next, denied: false };
  }
  if (selected.size >= cap) {
    return { selected, denied: true };
  }
  const next = new Set(selected);
  next.add(resi);
  return { selected: next, denied: false };
}

// ---------------------------------------------------------------------------
// Mol* plugin integration
// ---------------------------------------------------------------------------

interface MolstarPluginLite {
  managers?: {
    structure?: {
      selection?: {
        fromSelectionQuery?: (mode: string, query: unknown) => Promise<void> | void;
        clear?: () => void;
      };
    };
    camera?: {
      focusLoci?: (loci: unknown, opts?: unknown) => void;
      reset?: () => void;
    };
  };
}

/**
 * Push the caller's selection into Mol*'s selection manager as the set of
 * highlighted residues. Same MolScript pattern `MolstarViewer` uses, just
 * split out so 3D picker doesn't fork it.
 */
export async function highlightSelectedResidues(
  plugin: MolstarPluginLite | null,
  selected: Set<number>,
  opts: { chainId: string },
): Promise<void> {
  if (!plugin?.managers?.structure?.selection) return;
  const sel = plugin.managers.structure.selection;
  if (selected.size === 0) {
    sel.clear?.();
    return;
  }

  try {
    const { MolScriptBuilder: MS } = await import(
      "molstar/lib/mol-script/language/builder"
    );
    const resis = [...selected];
    const query = MS.struct.generator.atomGroups({
      "chain-test": MS.core.rel.eq([MS.ammp("auth_asym_id"), opts.chainId]),
      "residue-test": MS.core.logic.or(
        resis.map((r) => MS.core.rel.eq([MS.ammp("auth_seq_id"), r])),
      ),
    });
    await sel.fromSelectionQuery?.("set", query);
  } catch (e) {
    // Swallow: Mol* versions reshuffle builder paths across minors and we
    // do not want a highlight failure to crash the picker.
    if (typeof console !== "undefined") {
      console.warn("[viewer] highlightSelectedResidues failed", e);
    }
  }
}

/**
 * Smooth-zoom the camera so every selected residue fits in the viewport.
 * Delegates to `managers.camera.focusLoci` which already handles the
 * bounding-sphere math inside Mol*. When the structure manager exposes a
 * loci for the current structure we pass the MolScript selection through;
 * otherwise we fall back to a plain camera reset.
 */
export async function animateCameraToSelection(
  plugin: MolstarPluginLite | null,
  selected: Set<number>,
  opts: { chainId: string },
): Promise<void> {
  if (!plugin?.managers?.camera?.focusLoci) return;
  if (selected.size === 0) return;

  try {
    const { MolScriptBuilder: MS } = await import(
      "molstar/lib/mol-script/language/builder"
    );
    const resis = [...selected];
    const query = MS.struct.generator.atomGroups({
      "chain-test": MS.core.rel.eq([MS.ammp("auth_asym_id"), opts.chainId]),
      "residue-test": MS.core.logic.or(
        resis.map((r) => MS.core.rel.eq([MS.ammp("auth_seq_id"), r])),
      ),
    });
    plugin.managers.camera.focusLoci(query, { extraRadius: 4 });
  } catch {
    plugin.managers.camera.reset?.();
  }
}
