"use client";

import { useCallback, useMemo, useState } from "react";

/**
 * useDesignSelection: ephemeral multi-select state for the designs list page.
 *
 * Returns a Set-backed selection with O(1) toggle/has and a hard cap so
 * batch actions stay bounded. No persistence: selection clears on page
 * unmount or refresh, which is the desired behaviour for an in-page batch.
 */

export const DEFAULT_SELECTION_CAP = 8;

export interface UseDesignSelectionOptions {
  /** Maximum number of simultaneously selected designs. Defaults to 8. */
  max?: number;
  /** Optional callback fired when a `toggle` is rejected by the cap. */
  onCapReached?: (max: number) => void;
}

export interface UseDesignSelectionResult {
  /** The current selection as a (cloned, immutable-feel) Set. */
  selected: Set<string>;
  /** Sorted list of selected ids: convenient for stable rendering. */
  ids: string[];
  /** Number of selected designs. */
  count: number;
  /** True when at least one design is selected. */
  hasAny: boolean;
  /** True when count >= max. */
  isFull: boolean;
  /** Test membership without re-creating the set in callers. */
  has: (id: string) => boolean;
  /**
   * Toggle a design's selection. Returns the new selected state for the
   * id, or `null` when the toggle was rejected because the cap was hit.
   */
  toggle: (id: string) => boolean | null;
  /** Imperatively select one or more ids (respects cap). */
  select: (ids: string | string[]) => void;
  /** Imperatively deselect one or more ids. */
  deselect: (ids: string | string[]) => void;
  /** Clear the entire selection. */
  clear: () => void;
}

export function useDesignSelection(
  options: UseDesignSelectionOptions = {},
): UseDesignSelectionResult {
  const max = Math.max(1, options.max ?? DEFAULT_SELECTION_CAP);
  const onCapReached = options.onCapReached;

  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const has = useCallback(
    (id: string) => selected.has(id),
    [selected],
  );

  const toggle = useCallback(
    (id: string): boolean | null => {
      let result: boolean | null = null;
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(id)) {
          next.delete(id);
          result = false;
          return next;
        }
        if (next.size >= max) {
          result = null;
          onCapReached?.(max);
          return prev;
        }
        next.add(id);
        result = true;
        return next;
      });
      return result;
    },
    [max, onCapReached],
  );

  const select = useCallback(
    (ids: string | string[]) => {
      const list = Array.isArray(ids) ? ids : [ids];
      setSelected((prev) => {
        const next = new Set(prev);
        for (const id of list) {
          if (next.size >= max) {
            onCapReached?.(max);
            break;
          }
          next.add(id);
        }
        return next;
      });
    },
    [max, onCapReached],
  );

  const deselect = useCallback((ids: string | string[]) => {
    const list = Array.isArray(ids) ? ids : [ids];
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of list) next.delete(id);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setSelected((prev) => (prev.size === 0 ? prev : new Set()));
  }, []);

  const ids = useMemo(() => Array.from(selected).sort(), [selected]);
  const count = selected.size;

  return {
    selected,
    ids,
    count,
    hasAny: count > 0,
    isFull: count >= max,
    has,
    toggle,
    select,
    deselect,
    clear,
  };
}

export default useDesignSelection;
