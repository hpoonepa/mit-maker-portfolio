"use client";

/**
 * Hotspot selection store: a tiny React-Context-based store that owns the
 * set of residues currently picked as hotspots in the 3D Mol* viewer.
 *
 * The shape is intentionally small: a Set keyed by `${chain}:${resi}` plus a
 * handful of imperative actions. This sidesteps a zustand dependency (the
 * agent contract forbids `pnpm install`) while keeping the API equivalent.
 *
 * Persisting / saving to the DB is up to the caller: the store is purely
 * client-side ephemeral state. The `target` page wires `flush()` into a
 * tRPC `saveHotspots` mutation.
 */
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

/** Composite residue identifier: `${chain}:${authSeqId}`. */
export type HotspotKey = `${string}:${number}`;

export interface Hotspot {
  /** Author chain id, e.g. "A". */
  chain: string;
  /** 1-indexed PDB residue number. */
  resi: number;
}

/** Encode a chain+resi pair into the composite key. */
export function hotspotKey(h: Hotspot): HotspotKey {
  return `${h.chain}:${h.resi}` as HotspotKey;
}

/** Decode a composite key back to its chain + resi parts. */
export function parseHotspotKey(key: HotspotKey): Hotspot {
  const [chain, rest] = key.split(":");
  return { chain: chain ?? "A", resi: Number(rest ?? 0) };
}

interface HotspotStoreState {
  /** Selected residues, keyed by `${chain}:${resi}`. */
  selection: Set<HotspotKey>;
  /** True while the user is in hotspot picking mode (bound to "h"). */
  pickingMode: boolean;
}

interface HotspotStoreActions {
  /** Add a residue to the selection. No-op if already present. */
  add: (h: Hotspot) => void;
  /** Remove a residue from the selection. No-op if absent. */
  remove: (h: Hotspot) => void;
  /** Toggle a residue. */
  toggle: (h: Hotspot) => void;
  /** Replace the whole selection in one shot. */
  replace: (items: Hotspot[]) => void;
  /** Drop every residue. */
  clear: () => void;
  /** Toggle picking mode (bound to the `h` shortcut). */
  togglePickingMode: () => void;
  setPickingMode: (on: boolean) => void;
  /** True iff the residue is currently selected. */
  has: (h: Hotspot) => boolean;
  /** Selected residues grouped by chain: convenient for the tRPC payload. */
  groupByChain: () => Array<{ chain: string; residues: number[] }>;
}

export type HotspotStore = HotspotStoreState & HotspotStoreActions;

const HotspotStoreContext = createContext<HotspotStore | null>(null);

export interface HotspotStoreProviderProps {
  children: ReactNode;
  /** Optional initial selection: typically the persisted hotspots from DB. */
  initial?: Hotspot[];
}

/**
 * Provides the hotspot store to descendants. Mount this once near the root
 * of any page that contains a Mol* viewer + chip rail + save button.
 */
export function HotspotStoreProvider({
  children,
  initial,
}: HotspotStoreProviderProps) {
  const [selection, setSelection] = useState<Set<HotspotKey>>(
    () => new Set((initial ?? []).map(hotspotKey)),
  );
  const [pickingMode, setPickingMode] = useState(true);

  // Imperative ref so callbacks can read the latest selection without
  // re-binding every keystroke (the keyboard listeners attach once).
  const selectionRef = useRef(selection);
  selectionRef.current = selection;

  const add = useCallback((h: Hotspot) => {
    setSelection((prev) => {
      const k = hotspotKey(h);
      if (prev.has(k)) return prev;
      const next = new Set(prev);
      next.add(k);
      return next;
    });
  }, []);

  const remove = useCallback((h: Hotspot) => {
    setSelection((prev) => {
      const k = hotspotKey(h);
      if (!prev.has(k)) return prev;
      const next = new Set(prev);
      next.delete(k);
      return next;
    });
  }, []);

  const toggle = useCallback((h: Hotspot) => {
    setSelection((prev) => {
      const k = hotspotKey(h);
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }, []);

  const replace = useCallback((items: Hotspot[]) => {
    setSelection(new Set(items.map(hotspotKey)));
  }, []);

  const clear = useCallback(() => setSelection(new Set()), []);

  const togglePickingMode = useCallback(
    () => setPickingMode((v) => !v),
    [],
  );

  const has = useCallback(
    (h: Hotspot) => selectionRef.current.has(hotspotKey(h)),
    [],
  );

  const groupByChain = useCallback(() => {
    const byChain = new Map<string, number[]>();
    for (const k of selectionRef.current) {
      const { chain, resi } = parseHotspotKey(k);
      const arr = byChain.get(chain) ?? [];
      arr.push(resi);
      byChain.set(chain, arr);
    }
    return [...byChain.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([chain, residues]) => ({
        chain,
        residues: residues.sort((a, b) => a - b),
      }));
  }, []);

  const value = useMemo<HotspotStore>(
    () => ({
      selection,
      pickingMode,
      add,
      remove,
      toggle,
      replace,
      clear,
      togglePickingMode,
      setPickingMode,
      has,
      groupByChain,
    }),
    [
      selection,
      pickingMode,
      add,
      remove,
      toggle,
      replace,
      clear,
      togglePickingMode,
      has,
      groupByChain,
    ],
  );

  return createElement(HotspotStoreContext.Provider, { value }, children);
}

/**
 * Access the hotspot store. Must be called inside a `<HotspotStoreProvider>`.
 */
export function useHotspotStore(): HotspotStore {
  const ctx = useContext(HotspotStoreContext);
  if (!ctx) {
    throw new Error(
      "useHotspotStore must be used inside a <HotspotStoreProvider>",
    );
  }
  return ctx;
}

/**
 * Build a tRPC-ready payload from the current selection.
 * Mirrors the `HotspotSchema` from `@papercrane/types`.
 */
export function selectionToHotspots(
  selection: Set<HotspotKey>,
): Array<{ chain: string; residues: number[] }> {
  const byChain = new Map<string, number[]>();
  for (const k of selection) {
    const { chain, resi } = parseHotspotKey(k);
    const arr = byChain.get(chain) ?? [];
    arr.push(resi);
    byChain.set(chain, arr);
  }
  return [...byChain.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([chain, residues]) => ({
      chain,
      residues: residues.sort((a, b) => a - b),
    }));
}
