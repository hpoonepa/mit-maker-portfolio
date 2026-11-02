"use client";

/**
 * Global state + Cmd+K keybinding for the dashboard command palette.
 *
 * Mounted once inside the `(dashboard)` layout so the hotkey works on
 * every authenticated page. Renders `<CommandPalette>` lazily: the
 * heavy tree only mounts when the palette is open, which keeps the
 * Server Component layout fast.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import dynamic from "next/dynamic";

const CommandPalette = dynamic(
  () => import("./CommandPalette").then((m) => m.CommandPalette),
  { ssr: false },
);

export interface RecentItem {
  id: string;
  title: string;
  href: string;
  group: string;
  ts: number;
}

const RECENTS_KEY = "papercrane:command:recents";
const RECENT_LIMIT = 5;

interface SearchContextValue {
  open: boolean;
  setOpen: (next: boolean) => void;
  toggle: () => void;
  recents: RecentItem[];
  pushRecent: (item: Omit<RecentItem, "ts">) => void;
  clearRecents: () => void;
  currentProjectSlug?: string;
}

const SearchContext = createContext<SearchContextValue | null>(null);

function loadRecents(): RecentItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (r): r is RecentItem =>
          !!r &&
          typeof r === "object" &&
          typeof (r as RecentItem).id === "string" &&
          typeof (r as RecentItem).href === "string",
      )
      .slice(0, RECENT_LIMIT);
  } catch {
    return [];
  }
}

function saveRecents(items: RecentItem[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(RECENTS_KEY, JSON.stringify(items));
  } catch {
    /* quota / private mode: degrade silently */
  }
}

export interface SearchProviderProps {
  children: ReactNode;
  /** Slug of the project the current page is scoped to, if any. */
  currentProjectSlug?: string;
}

export function SearchProvider({
  children,
  currentProjectSlug,
}: SearchProviderProps) {
  const [open, setOpen] = useState(false);
  const [recents, setRecents] = useState<RecentItem[]>([]);

  // Hydrate recents on mount.
  useEffect(() => {
    setRecents(loadRecents());
  }, []);

  // Cmd+K (mac) / Ctrl+K (linux/windows) global hotkey.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isPaletteHotkey =
        (e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K");
      if (isPaletteHotkey) {
        e.preventDefault();
        setOpen((prev) => !prev);
        return;
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pushRecent = useCallback((item: Omit<RecentItem, "ts">) => {
    setRecents((prev) => {
      const next: RecentItem[] = [
        { ...item, ts: Date.now() },
        ...prev.filter((r) => r.id !== item.id),
      ].slice(0, RECENT_LIMIT);
      saveRecents(next);
      return next;
    });
  }, []);

  const clearRecents = useCallback(() => {
    setRecents([]);
    saveRecents([]);
  }, []);

  const toggle = useCallback(() => setOpen((prev) => !prev), []);

  const value = useMemo<SearchContextValue>(
    () => ({
      open,
      setOpen,
      toggle,
      recents,
      pushRecent,
      clearRecents,
      currentProjectSlug,
    }),
    [open, toggle, recents, pushRecent, clearRecents, currentProjectSlug],
  );

  return (
    <SearchContext.Provider value={value}>
      {children}
      {open ? <CommandPalette /> : null}
    </SearchContext.Provider>
  );
}

export function useSearch(): SearchContextValue {
  const ctx = useContext(SearchContext);
  if (!ctx) {
    throw new Error("useSearch must be used inside <SearchProvider>");
  }
  return ctx;
}
