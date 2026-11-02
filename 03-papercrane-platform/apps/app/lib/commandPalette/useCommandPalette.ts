"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Global state + keyboard listener for the command palette.
 *
 * Responsibilities:
 *   - open/close flag with toggle
 *   - Cmd+K / Ctrl+K global hotkey (captured on `keydown`, preventDefault to
 *     suppress browser search)
 *   - Escape to close
 *   - Persistent recent-commands list capped at 8 (LOCAL_KEY in localStorage)
 *
 * The hook intentionally knows nothing about fetching or rendering: those
 * concerns live in `CommandPalette.tsx`. This keeps the hook trivially
 * testable later (state transitions only).
 */

export const RECENTS_STORAGE_KEY = "papercrane.cmdk.recent";
export const RECENTS_MAX = 8;

export interface RecentCommandEntry {
  id: string;
  title: string;
  group: string;
  /** epoch ms: newest first */
  at: number;
}

interface UseCommandPaletteResult {
  open: boolean;
  setOpen: (next: boolean) => void;
  toggle: () => void;
  close: () => void;
  recents: RecentCommandEntry[];
  pushRecent: (entry: Omit<RecentCommandEntry, "at">) => void;
  clearRecents: () => void;
}

export function useCommandPalette(): UseCommandPaletteResult {
  const [open, setOpenState] = useState(false);
  const [recents, setRecents] = useState<RecentCommandEntry[]>([]);
  const hydratedRef = useRef(false);

  // Hydrate from localStorage once on mount. SSR-safe.
  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(RECENTS_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        setRecents(parsed.filter(isRecentEntry).slice(0, RECENTS_MAX));
      }
    } catch {
      // Corrupted value: nuke it so next write starts clean.
      try {
        window.localStorage.removeItem(RECENTS_STORAGE_KEY);
      } catch {
        /* ignore */
      }
    }
  }, []);

  const setOpen = useCallback((next: boolean) => setOpenState(next), []);
  const toggle = useCallback(() => setOpenState((prev) => !prev), []);
  const close = useCallback(() => setOpenState(false), []);

  // Cmd+K / Ctrl+K global hotkey + Escape to close.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onKey = (e: KeyboardEvent) => {
      const isModK = (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey &&
        e.key.toLowerCase() === "k";
      if (isModK) {
        e.preventDefault();
        setOpenState((prev) => !prev);
        return;
      }
      if (e.key === "Escape") {
        setOpenState((prev) => (prev ? false : prev));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pushRecent = useCallback(
    (entry: Omit<RecentCommandEntry, "at">) => {
      setRecents((prev) => {
        const filtered = prev.filter((r) => r.id !== entry.id);
        const next: RecentCommandEntry[] = [
          { ...entry, at: Date.now() },
          ...filtered,
        ].slice(0, RECENTS_MAX);
        if (typeof window !== "undefined") {
          try {
            window.localStorage.setItem(
              RECENTS_STORAGE_KEY,
              JSON.stringify(next),
            );
          } catch {
            /* quota exceeded / private mode: ignore */
          }
        }
        return next;
      });
    },
    [],
  );

  const clearRecents = useCallback(() => {
    setRecents([]);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.removeItem(RECENTS_STORAGE_KEY);
      } catch {
        /* ignore */
      }
    }
  }, []);

  return { open, setOpen, toggle, close, recents, pushRecent, clearRecents };
}

function isRecentEntry(x: unknown): x is RecentCommandEntry {
  if (!x || typeof x !== "object") return false;
  const r = x as Record<string, unknown>;
  return (
    typeof r.id === "string" &&
    typeof r.title === "string" &&
    typeof r.group === "string" &&
    typeof r.at === "number"
  );
}
